/* Service worker: the only place that talks to the local ChekhovsGun server.
 *
 * Content scripts could call 127.0.0.1 directly — browsers treat loopback as a
 * secure origin, so there is no mixed-content problem — but routing through the
 * worker keeps the page's own Content-Security-Policy out of the picture
 * entirely, and gives one place to cache, debounce and hold settings.
 */

const DEFAULTS = {
  enabled: true,
  serverUrl: "http://127.0.0.1:8700",
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
  explain: true,
  autoCollapse: false,
};

const CACHE_TTL_MS = 5 * 60 * 1000;
const cache = new Map(); // videoKey -> { at, payload }

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...stored, sites: { ...DEFAULTS.sites, ...(stored.sites || {}) } };
}

async function request(path, options, timeoutMs = 12000) {
  const settings = await getSettings();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(settings.serverUrl.replace(/\/+$/, "") + path, {
      ...options,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`server returned ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

/** Has this video already fired recently? Kept in session storage so it resets
 *  when the browser restarts, which is the cadence people actually want. */
async function isMuted(key, cooldownMinutes) {
  const store = await chrome.storage.session.get(["shots"]);
  const shots = store.shots || {};
  const last = shots[key];
  if (!last) return false;
  if (last === "forever") return true;
  return Date.now() - last < cooldownMinutes * 60 * 1000;
}

async function markFired(key, forever = false) {
  const store = await chrome.storage.session.get(["shots"]);
  const shots = store.shots || {};
  shots[key] = forever ? "forever" : Date.now();
  const keys = Object.keys(shots);
  if (keys.length > 400) delete shots[keys[0]];
  await chrome.storage.session.set({ shots });
}

async function handleRelate(context) {
  const settings = await getSettings();
  if (!settings.enabled) return { fired: false, reason: "extension disabled" };
  if (context.source && settings.sites[context.source] === false) {
    return { fired: false, reason: `${context.source} disabled in settings` };
  }

  const key = `${context.source}:${context.source_id}`;
  if (await isMuted(key, settings.cooldownMinutes)) {
    return { fired: false, reason: "muted for this video" };
  }

  const cached = cache.get(key);
  if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
    if (cached.payload.fired) await markFired(key);
    return { ...cached.payload, cached: true };
  }

  const payload = await request("/api/relate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...context, limit: settings.maxItems, explain: settings.explain }),
  });
  cache.set(key, { at: Date.now(), payload });
  if (cache.size > 200) cache.delete(cache.keys().next().value);
  if (payload.fired) await markFired(key);
  return payload;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    try {
      switch (message?.type) {
        case "relate":
          sendResponse(await handleRelate(message.context || {}));
          break;
        case "capture": {
          const settings = await getSettings();
          if (message.payload?.origin === "save-click" && !settings.captureOnSave) {
            sendResponse({ ok: true, state: "skipped", reason: "captureOnSave disabled" });
            break;
          }
          const saved = await request("/api/capture", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(message.payload || {}),
          });
          // A new save can change what fires anywhere, so the relate cache for
          // every page is stale, not just this one's.
          cache.clear();
          sendResponse({ ok: true, ...saved });
          break;
        }
        case "captureBatch": {
          const saved = await request(
            "/api/capture/batch",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(message.payload || {}),
            },
            // A folder scan sends hundreds of rows; the default timeout is for
            // single requests and would abort a large one mid-write.
            120000
          );
          cache.clear();
          sendResponse({ ok: true, ...saved });
          break;
        }
        case "settings":
          sendResponse(await getSettings());
          break;
        case "status":
          sendResponse({ ok: true, status: await request("/api/status", {}, 5000) });
          break;
        case "mute":
          await markFired(message.key, true);
          sendResponse({ ok: true });
          break;
        case "mark":
          // Server-side and permanent, unlike "mute" which only lasts the session.
          await request(`/api/items/${encodeURIComponent(message.itemId)}/mark`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: message.status }),
          });
          cache.clear();
          sendResponse({ ok: true });
          break;
        case "feedback":
          await request("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(message.payload || {}),
          });
          sendResponse({ ok: true });
          break;
        default:
          sendResponse({ ok: false, error: `unknown message ${message?.type}` });
      }
    } catch (error) {
      sendResponse({ ok: false, fired: false, error: String(error.message || error) });
    }
  })();
  return true; // keep the message channel open for the async reply
});

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({ ...DEFAULTS, ...current });
});
