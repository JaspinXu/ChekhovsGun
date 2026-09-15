/**
 * The service worker: routing and orchestration, and nothing else.
 *
 * MV3 kills this worker after roughly 30 seconds idle and restarts it on the
 * next message, so it deliberately holds no state that matters. The library
 * lives in IndexedDB, the encoder lives in the offscreen document, and the
 * caches here are pure optimisation that cost nothing when they evaporate.
 *
 * Retrieval runs locally first. The Python backend, when one is running, is
 * queried in parallel and merged in — it adds Whisper transcripts and bulk
 * platform-API syncs the browser cannot do — but it is never required, and
 * every failure it can produce degrades to "fewer results".
 */

import { IdbStore } from "./platform/idb.js";
import { HashingEmbedder } from "./core/embed-hash.js";
import { deepLink } from "./core/deeplink.js";
import { LocalEngine } from "./engine/local.js";
import { RemoteEngine } from "./engine/remote.js";
import { FallbackEmbedder, ModelEmbedder } from "./engine/embed-proxy.js";
import { federate } from "./engine/federate.js";

const DEFAULTS = {
  enabled: true,
  serverUrl: "http://127.0.0.1:8700",
  // Off until the user opts in on the options page, which is also where the
  // loopback host permission is requested. A standalone install should not ask
  // for network access it does not use, nor probe a port nobody is listening on.
  useBackend: false,
  // Per-source switches. A site absent from this map defaults to on, so adding
  // a recipe does not require touching settings.
  sites: {
    youtube: true, bilibili: true, zhihu: true, xiaohongshu: true, wechat: true,
    weibo: true, juejin: true, csdn: true, jianshu: true, reddit: true,
    x: true, stackoverflow: true, medium: true,
  },
  // Capture automatically when you click a site's own 收藏 button. This is the
  // whole "只需要收藏" promise; turning it off leaves the toolbar button.
  captureOnSave: true,
  cooldownMinutes: 45,
  maxItems: 3,
  autoCollapse: false,
  useModel: true,
};

const CACHE_TTL_MS = 5 * 60 * 1000;
const cache = new Map(); // item key -> { at, payload }

const store = new IdbStore();
const hashEmbedder = new HashingEmbedder();
const embedder = new FallbackEmbedder(new ModelEmbedder(), hashEmbedder);
const local = new LocalEngine(store, embedder);
const remote = new RemoteEngine(DEFAULTS.serverUrl);

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...stored, sites: { ...DEFAULTS.sites, ...(stored.sites || {}) } };
}

// ----------------------------------------------------------------- the model

const MODEL_ALARM = "chekhovsgun-model";
const REEMBED_ALARM = "chekhovsgun-reembed";

/**
 * Try to bring the neural encoder online.
 *
 * Called on install and on every worker start, because a worker start is the
 * only reliable "the browser is awake" signal MV3 gives us. `probe` never
 * throws: a missing model is the normal state of a fresh clone, not an error,
 * and the extension is fully usable on the hashing embedder meanwhile.
 */
async function bootstrapModel() {
  const settings = await getSettings();
  if (!settings.useModel) return;
  if (embedder.usingModel) return;
  const ready = await ModelEmbedder.probe();
  if (!ready) return;
  embedder.promote();
  local.setEmbedder(embedder);
  await store.setMeta("embedder", embedder.signature);
  // Existing chunks were embedded by the hashing backend and are now in the
  // wrong vector space. They stay findable through BM25 while this catches up.
  chrome.alarms.create(REEMBED_ALARM, { periodInMinutes: 1 });
}

/**
 * One batch of re-embedding per alarm, rather than one long task.
 *
 * A single pass over a large library would outlive the worker and be killed
 * halfway, leaving the work neither done nor recorded; batching means progress
 * is durable after every step.
 */
async function reembedStep() {
  try {
    const done = await local.reembedBatch(64);
    if (!done) chrome.alarms.clear(REEMBED_ALARM);
  } catch (error) {
    console.warn("[chekhovsgun] re-embed paused:", error);
    chrome.alarms.clear(REEMBED_ALARM);
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === REEMBED_ALARM) reembedStep();
  if (alarm.name === MODEL_ALARM) bootstrapModel();
});

// ------------------------------------------------------------------- muting

/**
 * Has this page already fired recently? Kept in session storage so it resets
 * when the browser restarts, which is the cadence people actually want.
 */
async function isMuted(key, cooldownMinutes) {
  const { shots = {} } = await chrome.storage.session.get(["shots"]);
  const last = shots[key];
  if (!last) return false;
  if (last === "forever") return true;
  return Date.now() - last < cooldownMinutes * 60 * 1000;
}

async function markFired(key, forever = false) {
  const { shots = {} } = await chrome.storage.session.get(["shots"]);
  shots[key] = forever ? "forever" : Date.now();
  const keys = Object.keys(shots);
  if (keys.length > 400) delete shots[keys[0]];
  await chrome.storage.session.set({ shots });
}

// ------------------------------------------------------------------ the wire

/**
 * Convert a core hit into the shape the content script renders.
 *
 * The card was written against the Python server's snake_case payload. Keeping
 * that contract means the whole surface layer — recipes, card, highlight
 * scrolling — is untouched by this change, so the risk stays in the engine
 * where it is covered by tests.
 */
function toWire(hit) {
  const item = hit.item || {};
  return {
    score: hit.score || 0,
    confidence: Number((hit.confidence || 0).toFixed(4)),
    deep_link: deepLink(hit),
    origins: hit.origins || ["local"],
    item: {
      id: item.id,
      source: item.source || "",
      source_id: item.sourceId || "",
      title: item.title || "",
      url: item.url || "",
      author: item.author || "",
      thumbnail: item.thumbnail || "",
      duration: item.duration || 0,
      folder: item.folder || "",
      status: item.status || "active",
      media_kind: item.mediaKind || "video",
    },
    chunks: (hit.chunks || []).map((chunk) => ({
      id: chunk.id,
      text: chunk.text || "",
      start: chunk.start || 0,
      end: chunk.end || 0,
      kind: chunk.kind || "transcript",
    })),
    timestamps: hit.timestamps || [],
  };
}

// ----------------------------------------------------------------- handlers

async function handleRelate(context) {
  const settings = await getSettings();
  if (!settings.enabled) return { fired: false, reason: "extension disabled" };
  if (context.source && settings.sites[context.source] === false) {
    return { fired: false, reason: `${context.source} disabled in settings` };
  }

  const key = `${context.source}:${context.source_id}`;
  if (await isMuted(key, settings.cooldownMinutes)) {
    return { fired: false, reason: "muted for this page" };
  }

  const cached = cache.get(key);
  if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
    if (cached.payload.fired) await markFired(key);
    return { ...cached.payload, cached: true };
  }

  const normalized = {
    source: context.source || "",
    sourceId: context.source_id || "",
    title: context.title || "",
    author: context.author || "",
    description: context.description || "",
    tags: context.tags || [],
    url: context.url || "",
  };

  // Local and remote run together; the remote half is allowed to fail and
  // resolves to [] rather than rejecting, so this never needs a catch.
  const [localResult, remoteHits] = await Promise.all([
    local.relate(normalized, { limit: settings.maxItems }),
    settings.useBackend ? remote.relate(context, { limit: settings.maxItems }) : [],
  ]);

  const merged = federate(localResult.hits, remoteHits, { limit: settings.maxItems });
  const payload = {
    fired: merged.length > 0,
    hits: merged.map(toWire),
    gated: localResult.gated,
    itemCount: localResult.itemCount,
    backend: remote._available,
    reason: localResult.gated
      ? `library too small (${localResult.itemCount}/${local.config.minLibraryItems})`
      : "",
  };

  cache.set(key, { at: Date.now(), payload });
  if (cache.size > 200) cache.delete(cache.keys().next().value);
  if (payload.fired) await markFired(key);
  return payload;
}

async function handleCapture(payload, settings) {
  if (payload?.origin === "save-click" && !settings.captureOnSave) {
    return { ok: true, state: "skipped", reason: "captureOnSave disabled" };
  }
  const result = await local.capture(payload || {});
  // A new save can change what fires anywhere, so every page's cached relate is
  // stale, not just this one's.
  cache.clear();

  // Best-effort hand-off so the backend's library stays in step. The local copy
  // is already written, so a failure here costs nothing.
  if (settings.useBackend) remote.forwardCapture(payload).catch(() => {});

  return { ok: true, state: "saved", added: 1, item: result.item, chunks: result.chunks };
}

async function handleCaptureBatch(payload, settings) {
  const rows = (payload && (payload.items || payload.rows)) || [];
  let added = 0;
  let skipped = 0;
  for (const row of rows) {
    try {
      if (await local.has(row.url)) {
        skipped += 1;
        continue;
      }
      await local.capture(row);
      added += 1;
    } catch (error) {
      console.warn("[chekhovsgun] capture failed for", row && row.url, error);
    }
  }
  cache.clear();
  if (settings.useBackend && rows.length) {
    remote.forwardCapture({ items: rows }).catch(() => {});
  }
  return { ok: true, added, skipped, updated: 0 };
}

async function handleStatus() {
  const [stats, settings] = await Promise.all([local.stats(), getSettings()]);
  const backendUp = settings.useBackend ? await remote.available() : false;
  return {
    ok: true,
    status: {
      ...stats,
      local: true,
      backend: backendUp,
      backendError: backendUp ? "" : remote.lastError,
      model: embedder.usingModel ? embedder.model.signature : null,
      modelError: embedder.lastError,
    },
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  // The offscreen document answers its own messages; ignoring them here keeps
  // this listener from replying "unknown message" and closing the channel.
  if (message && message.target === "offscreen") return false;

  (async () => {
    try {
      const settings = await getSettings();
      switch (message?.type) {
        case "relate":
          sendResponse(await handleRelate(message.context || {}));
          break;
        case "capture":
          sendResponse(await handleCapture(message.payload, settings));
          break;
        case "captureBatch":
          sendResponse(await handleCaptureBatch(message.payload, settings));
          break;
        case "settings":
          sendResponse(settings);
          break;
        case "status":
          sendResponse(await handleStatus());
          break;
        case "search":
          sendResponse({
            ok: true,
            hits: (await local.search(message.query, { limit: message.limit || 10 })).map(toWire),
          });
          break;
        case "mute":
          await markFired(message.key, true);
          sendResponse({ ok: true });
          break;
        case "mark":
          await local.mark(message.itemId, message.status || "digested");
          if (settings.useBackend) remote.mark(message.itemId, message.status).catch(() => {});
          cache.clear();
          sendResponse({ ok: true });
          break;
        case "remove":
          await local.remove(message.itemId);
          cache.clear();
          sendResponse({ ok: true });
          break;
        case "feedback":
          await store.logEvent("feedback", message.payload || {});
          sendResponse({ ok: true });
          break;
        case "recent":
          sendResponse({ ok: true, items: await store.allItems() });
          break;
        default:
          sendResponse({ ok: false, error: `unknown message ${message?.type}` });
      }
    } catch (error) {
      console.error("[chekhovsgun]", error);
      sendResponse({ ok: false, fired: false, error: String(error?.message || error) });
    }
  })();
  return true; // keep the message channel open for the async reply
});

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({ ...DEFAULTS, ...current });
  bootstrapModel();
});

chrome.runtime.onStartup.addListener(() => bootstrapModel());

// Settings can point the backend somewhere else at any time.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync") return;
  if (changes.serverUrl) remote.setBaseUrl(changes.serverUrl.newValue);
  if (changes.useModel && changes.useModel.newValue) bootstrapModel();
});

// A worker start is the only reliable "the browser is awake" signal MV3 gives.
bootstrapModel();
