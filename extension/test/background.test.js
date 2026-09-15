/**
 * The service worker, exercised end to end against a stubbed `chrome`.
 *
 * Everything below this file is already covered in isolation; what is only
 * testable here is the wiring — that a message from the content script reaches
 * the engine, comes back in the snake_case shape the card renders, and that the
 * optional backend genuinely cannot break the path when it misbehaves.
 *
 * The stub is deliberately faithful about the two MV3 behaviours that bite:
 * `sendMessage` delivers to listeners rather than resolving by magic, and the
 * offscreen API refuses a second document.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { IDBFactory } from "fake-indexeddb";

function installChromeStub() {
  const messageListeners = [];
  const storage = { sync: {}, session: {} };

  const area = (name) => ({
    async get(defaults) {
      if (typeof defaults === "string") return { [defaults]: storage[name][defaults] };
      if (Array.isArray(defaults)) {
        const out = {};
        for (const key of defaults) out[key] = storage[name][key];
        return out;
      }
      return { ...(defaults || {}), ...storage[name] };
    },
    async set(values) {
      Object.assign(storage[name], values);
    },
  });

  globalThis.chrome = {
    runtime: {
      lastError: null,
      id: "test-extension",
      getURL: (path) => `chrome-extension://test/${path}`,
      onMessage: { addListener: (fn) => messageListeners.push(fn) },
      onInstalled: { addListener: () => {} },
      onStartup: { addListener: () => {} },
      async getContexts() {
        return [];
      },
      sendMessage(message, callback) {
        // Nothing in these tests provides an offscreen document, which is
        // exactly the fresh-install state: no model, hashing embedder only.
        if (message && message.target === "offscreen") {
          globalThis.chrome.runtime.lastError = { message: "no offscreen document" };
          callback(undefined);
          globalThis.chrome.runtime.lastError = null;
          return;
        }
        for (const listener of messageListeners) listener(message, {}, callback);
      },
    },
    storage: {
      sync: area("sync"),
      session: area("session"),
      onChanged: { addListener: () => {} },
    },
    alarms: {
      create: () => {},
      clear: () => {},
      onAlarm: { addListener: () => {} },
    },
    offscreen: {
      async createDocument() {
        throw new Error("offscreen unavailable in this test");
      },
    },
  };

  globalThis.indexedDB = new IDBFactory();
  return {
    storage,
    send: (message) =>
      new Promise((resolve) => globalThis.chrome.runtime.sendMessage(message, resolve)),
  };
}

const { storage, send } = installChromeStub();
// Imported after the stub exists: the worker touches `chrome` while loading.
await import("../background.js");

/** Capture enough items that the library clears the min-library gate. */
async function seedLibrary() {
  const rows = [
    ["如何理解混合检索", "向量检索擅长语义，BM25 擅长精确术语。\n\n用 RRF 融合起来可以同时拿到两边的好处。"],
    ["红烧肉的家常做法", "五花肉先焯水去腥，然后炒糖色，小火慢炖四十分钟。"],
    ["Kubernetes 网络模型", "每个 pod 在集群里都有自己的 IP 地址，service 提供稳定的虚拟 IP。"],
    ["Rust 的所有权", "借用检查器保证同一时刻只有一个可变引用存在。"],
    ["PostgreSQL 索引选择", "B-Tree 适合范围查询，GIN 适合全文检索和数组包含。"],
    ["HTTP 缓存策略", "强缓存看 Cache-Control，协商缓存靠 ETag 和 Last-Modified。"],
    ["Python 的 GIL", "全局解释器锁让同一时刻只有一个线程执行字节码。"],
    ["React 渲染优化", "memo 和 useMemo 减少不必要的重渲染开销。"],
    ["Docker 镜像分层", "每一条指令产生一层，合并指令可以减小镜像体积。"],
    ["Git rebase 与 merge", "rebase 重写提交历史，merge 保留分叉的真实形状。"],
    ["TLS 握手过程", "客户端和服务端协商密码套件并交换密钥材料。"],
    ["消息队列的语义", "至少一次、至多一次和恰好一次的投递保证各有代价。"],
    ["CSS 层叠上下文", "z-index 只在同一个层叠上下文内部可比较。"],
    ["编译器的寄存器分配", "图着色是寄存器分配的经典建模方式。"],
    ["分布式共识 Raft", "leader 选举和日志复制是 Raft 的两个核心机制。"],
    ["向量数据库怎么工作", "近似最近邻索引用召回率换查询速度。"],
  ];
  for (const [title, text] of rows) {
    const response = await send({
      type: "capture",
      payload: {
        url: `https://www.zhihu.com/p/${encodeURIComponent(title)}`,
        source: "zhihu",
        media_kind: "post",
        title,
        text,
        excerpt: text.slice(0, 60),
        tags: [],
        origin: "toolbar",
      },
    });
    assert.equal(response.ok, true, `capture failed for ${title}`);
  }
}

test("the worker answers a status message on a cold, empty library", async () => {
  const result = await send({ type: "status" });
  assert.equal(result.ok, true);
  assert.equal(result.status.items, 0);
  assert.equal(result.status.ready, false);
  assert.equal(result.status.backend, false, "the backend is off until opted into");
  assert.equal(result.status.model, null, "a fresh install has no encoder");
  assert.equal(
    result.status.embedder,
    "local-hash-js:512",
    "and falls back to the hashing embedder without complaint"
  );
});

test("settings come back with the standalone-first defaults", async () => {
  const settings = await send({ type: "settings" });
  assert.equal(settings.enabled, true);
  assert.equal(settings.useBackend, false);
  assert.equal(settings.captureOnSave, true);
});

test("a full capture → relate round trip produces a renderable card", async () => {
  await seedLibrary();

  const status = await send({ type: "status" });
  assert.equal(status.status.items, 16);
  assert.equal(status.status.ready, true, "16 items clears the min-library gate of 15");

  const result = await send({
    type: "relate",
    context: {
      source: "web",
      source_id: "some-article",
      title: "BM25 和向量召回怎么融合才好",
      url: "https://example.com/article",
    },
  });

  assert.equal(result.fired, true, `expected a hit, reason: ${result.reason}`);
  const [hit] = result.hits;

  // The card reads exactly these fields; a camelCase leak here renders blank.
  assert.ok(hit.item.id);
  assert.equal(typeof hit.item.media_kind, "string");
  assert.equal(typeof hit.item.source_id, "string");
  assert.equal(typeof hit.deep_link, "string");
  assert.ok(hit.deep_link.startsWith("https://"));
  assert.ok(Array.isArray(hit.chunks));
  assert.ok(hit.item.title.includes("混合检索"), `got ${hit.item.title}`);
});

test("the same page a second time is muted rather than firing twice", async () => {
  const context = {
    source: "web",
    source_id: "repeat-article",
    title: "分布式共识 Raft 的 leader 选举",
    url: "https://example.com/raft",
  };
  const first = await send({ type: "relate", context });
  assert.equal(first.fired, true);

  await send({ type: "mute", key: "web:repeat-article" });
  const second = await send({ type: "relate", context });
  assert.equal(second.fired, false);
  assert.match(second.reason, /muted/);
});

test("marking an item 学完了 stops it coming back", async () => {
  const context = {
    source: "web",
    source_id: "rust-article",
    title: "Rust 借用检查器与可变引用",
    url: "https://example.com/rust",
  };
  const before = await send({ type: "relate", context });
  assert.equal(before.fired, true);
  const itemId = before.hits[0].item.id;

  const marked = await send({ type: "mark", itemId, status: "digested" });
  assert.equal(marked.ok, true);

  // A fresh context id, so the session mute is not what is being measured.
  const after = await send({
    type: "relate",
    context: { ...context, source_id: "rust-article-2" },
  });
  assert.ok(
    !after.hits.some((h) => h.item.id === itemId),
    "a digested item must stop interrupting"
  );
});

test("an unrelated page stays silent", async () => {
  const result = await send({
    type: "relate",
    context: {
      source: "web",
      source_id: "grinder",
      title: "best espresso grinder under 300 dollars",
      url: "https://example.com/grinder",
    },
  });
  assert.equal(result.fired, false, `fired on: ${JSON.stringify(result.hits?.[0]?.item?.title)}`);
});

test("explicit search works regardless of the min-library gate", async () => {
  const result = await send({ type: "search", query: "GIN 索引 全文检索" });
  assert.equal(result.ok, true);
  assert.ok(result.hits.length > 0);
  assert.ok(result.hits[0].item.title.includes("PostgreSQL"));
});

test("disabling the extension silences it without erroring", async () => {
  await chrome.storage.sync.set({ enabled: false });
  const result = await send({
    type: "relate",
    context: { source: "web", source_id: "anything", title: "分布式共识 Raft" },
  });
  assert.equal(result.fired, false);
  assert.match(result.reason, /disabled/);
  await chrome.storage.sync.set({ enabled: true });
});

test("a per-site switch silences just that site", async () => {
  await chrome.storage.sync.set({ sites: { zhihu: false } });
  const result = await send({
    type: "relate",
    context: { source: "zhihu", source_id: "x1", title: "分布式共识 Raft" },
  });
  assert.equal(result.fired, false);
  assert.match(result.reason, /zhihu/);
  await chrome.storage.sync.set({ sites: { zhihu: true } });
});

test("an unknown message is refused rather than hanging the channel", async () => {
  const result = await send({ type: "no-such-thing" });
  assert.equal(result.ok, false);
  assert.match(result.error, /unknown message/);
});

test("the missing encoder never surfaces as a failure", async () => {
  // Everything above ran with no offscreen document available, which is the
  // fresh-install state. If that leaked out as an error the whole suite would
  // have failed — assert it explicitly so the guarantee is stated, not implied.
  const status = await send({ type: "status" });
  assert.equal(status.ok, true);
  assert.equal(status.status.model, null);
  assert.ok(status.status.items > 0, "and the library still works");
  void storage;
});
