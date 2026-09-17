/**
 * Engine tests: the local engine end to end against fake-indexeddb, and the
 * remote client against a stubbed `fetch`.
 *
 * The rule these exist to protect is that the backend is optional. Every remote
 * failure mode — refused connection, timeout, a 500, garbage JSON — has to
 * leave the extension working on local results alone.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { IDBFactory } from "fake-indexeddb";

import { IdbStore } from "../platform/idb.js";
import { HashingEmbedder } from "../core/embed-hash.js";
import { LocalEngine } from "../engine/local.js";
import { RemoteEngine } from "../engine/remote.js";
import { STATUS_DIGESTED } from "../core/ids.js";
import { FallbackEmbedder } from "../engine/embed-proxy.js";

function freshEngine(config = {}) {
  const store = new IdbStore(new IDBFactory(), `db-${Math.random().toString(36).slice(2)}`);
  return new LocalEngine(store, new HashingEmbedder(), config);
}

const capture = (n, title, body) => ({
  source: "zhihu",
  sourceId: String(n),
  title,
  url: `https://www.zhihu.com/answer/${n}`,
  body,
  mediaKind: "post",
});

test("a capture becomes searchable immediately", async () => {
  const engine = freshEngine();
  const result = await engine.capture(
    capture(1, "向量数据库是怎么工作的", "混合检索把 BM25 和向量召回融合起来。\n\n分块策略比编码器更重要。")
  );
  assert.ok(result.chunks > 0);
  const hits = await engine.search("混合检索 BM25");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].item.id, "zhihu:1");
});

test("capture accepts a plain body and splits it into passages", async () => {
  const engine = freshEngine();
  const { chunks } = await engine.capture(capture(2, "T", "第一段。\n\n第二段。\n\n第三段。"));
  assert.ok(chunks >= 2, `expected the body to be split, got ${chunks} chunk(s)`);
});

test("re-capturing the same URL does not duplicate the item", async () => {
  const engine = freshEngine();
  await engine.capture(capture(3, "原标题", "一些正文内容在这里。"));
  await engine.capture(capture(3, "改过的标题", "换了的正文内容在这里。"));
  const stats = await engine.stats();
  assert.equal(stats.items, 1);
  assert.equal((await engine.store.getItem("zhihu:3")).title, "改过的标题");
});

test("relate stays silent until the library is big enough", async () => {
  // Confidence leans on IDF, which means nothing over a handful of documents.
  const engine = freshEngine();
  await engine.capture(capture(1, "向量检索入门", "讲的是 BM25 与向量召回的融合。"));
  const result = await engine.relate({ title: "BM25 与向量召回", source: "web", sourceId: "x" });
  assert.equal(result.gated, true);
  assert.deepEqual(result.hits, []);
  assert.equal(result.itemCount, 1);
});

test("relate fires once the library clears the threshold", async () => {
  const engine = freshEngine({ minLibraryItems: 3 });
  await engine.capture(capture(1, "向量数据库的工作原理", "混合检索把 BM25 和向量召回融合起来解决术语匹配。"));
  await engine.capture(capture(2, "红烧肉的家常做法", "五花肉先焯水，再炒糖色，小火慢炖。"));
  await engine.capture(capture(3, "Kubernetes 网络模型", "每个 pod 在集群里都有自己的 IP 地址。"));
  const result = await engine.relate({
    title: "BM25 和向量召回怎么融合",
    source: "web",
    sourceId: "elsewhere",
  });
  assert.equal(result.gated, false);
  assert.ok(result.hits.length > 0, "expected a hit once the gate opens");
  assert.equal(result.hits[0].item.id, "zhihu:1");
});

test("marking an item 学完了 stops it firing but keeps it searchable", async () => {
  const engine = freshEngine({ minLibraryItems: 1 });
  await engine.capture(capture(1, "向量数据库的工作原理", "混合检索把 BM25 和向量召回融合起来解决术语匹配。"));
  await engine.mark("zhihu:1", STATUS_DIGESTED);

  const related = await engine.relate({ title: "BM25 和向量召回", source: "w", sourceId: "e" });
  assert.equal(related.hits.length, 0, "a digested item must stop interrupting");

  const searched = await engine.search("BM25 向量召回 融合");
  assert.equal(searched.length, 1, "but explicit search must still find it");
});

test("the library survives an embedder swap without losing items", async () => {
  const engine = freshEngine({ minLibraryItems: 1 });
  await engine.capture(capture(1, "向量数据库的工作原理", "混合检索把 BM25 和向量召回融合起来解决术语匹配问题。"));

  // Pretend the neural encoder arrived: a different signature, different width.
  const fake = {
    signature: "pretend-model:4",
    embedOne: () => Float32Array.from([0.5, 0.5, 0.5, 0.5]),
    embed: async (texts) => texts.map(() => Float32Array.from([0.5, 0.5, 0.5, 0.5])),
  };
  engine.setEmbedder(fake);

  const index = await engine.index();
  assert.equal(index.itemCount, 1, "the item must not vanish");
  assert.equal(index.vectorCoverage, 0, "its vectors are for the old space");

  const hits = await engine.search("BM25 向量召回 融合 术语");
  assert.equal(hits.length, 1, "lexical retrieval must carry it through the gap");
});

test("reembedBatch upgrades chunks and then reports it is done", async () => {
  const engine = freshEngine();
  await engine.capture(capture(1, "标题在这里", "一些正文内容用来生成分块。\n\n第二段正文内容。"));
  const fake = {
    signature: "pretend-model:4",
    embedOne: () => Float32Array.from([1, 0, 0, 0]),
    embed: async (texts) => texts.map(() => Float32Array.from([1, 0, 0, 0])),
  };
  engine.setEmbedder(fake);

  assert.ok((await engine.reembedBatch(100)) > 0, "there was stale work to do");
  assert.equal(await engine.reembedBatch(100), 0, "and now there is none");
  assert.equal((await engine.index()).vectorCoverage, 1, "every chunk is comparable again");
});

test("stats report what the popup needs to explain itself", async () => {
  const engine = freshEngine({ minLibraryItems: 2 });
  await engine.capture(capture(1, "标题", "正文内容在这里面。"));
  const stats = await engine.stats();
  assert.equal(stats.items, 1);
  assert.equal(stats.ready, false);
  assert.equal(stats.minLibraryItems, 2);
  assert.equal(stats.embedder, "local-hash-js:512");
  assert.equal(stats.vectorCoverage, 1);
});

// ------------------------------------------------------------------- remote

function stubFetch(handler) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = original;
  };
}

const ok = (body) => ({ ok: true, status: 200, statusText: "OK", json: async () => body });

test("a backend that is not running is simply unavailable", async () => {
  const restore = stubFetch(async () => {
    throw new Error("ECONNREFUSED");
  });
  try {
    const remote = new RemoteEngine();
    assert.equal(await remote.available(), false);
    assert.deepEqual(await remote.relate({ title: "x" }), []);
    assert.deepEqual(await remote.search("x"), []);
    assert.equal(await remote.forwardCapture({}), false);
    assert.equal(await remote.stats(), null);
  } finally {
    restore();
  }
});

test("a backend that 500s on a query does not throw into the card path", async () => {
  const restore = stubFetch(async (url) => {
    if (String(url).endsWith("/healthz")) return ok({ ok: true });
    return { ok: false, status: 500, statusText: "Internal Server Error" };
  });
  try {
    const remote = new RemoteEngine();
    assert.equal(await remote.available(), true);
    assert.deepEqual(await remote.relate({ title: "x" }), []);
  } finally {
    restore();
  }
});

test("remote hits are converted from snake_case to the core's shape", async () => {
  const restore = stubFetch(async (url) => {
    if (String(url).endsWith("/healthz")) return ok({ ok: true });
    return ok({
      results: [
        {
          item: {
            id: "youtube:v1",
            source: "youtube",
            source_id: "v1",
            title: "How Vector DBs Work",
            url: "https://y/v1",
            media_kind: "video",
          },
          chunks: [{ id: "c1", text: "passage", start: 12.5, kind: "transcript" }],
          score: 1.0,
          confidence: 0.8,
        },
      ],
    });
  });
  try {
    const remote = new RemoteEngine();
    const [hit] = await remote.relate({ title: "x" });
    assert.equal(hit.item.sourceId, "v1");
    assert.equal(hit.item.mediaKind, "video");
    assert.equal(hit.chunks[0].start, 12.5);
    assert.equal(hit.confidence, 0.8);
  } finally {
    restore();
  }
});

test("the health probe is cached rather than run per query", async () => {
  let probes = 0;
  const restore = stubFetch(async (url) => {
    if (String(url).endsWith("/healthz")) {
      probes += 1;
      return ok({ ok: true });
    }
    return ok({ results: [] });
  });
  try {
    const remote = new RemoteEngine();
    for (let i = 0; i < 5; i += 1) await remote.relate({ title: "x" });
    assert.equal(probes, 1, "scrolling a feed must not health-check per page");
  } finally {
    restore();
  }
});

test("changing the backend address forces a re-probe", async () => {
  let probes = 0;
  const restore = stubFetch(async () => {
    probes += 1;
    return ok({ ok: true });
  });
  try {
    const remote = new RemoteEngine();
    await remote.available();
    remote.setBaseUrl("http://127.0.0.1:9999");
    await remote.available();
    assert.equal(probes, 2);
  } finally {
    restore();
  }
});

test("a payload in the exact shape recipes.js produces is captured correctly", async () => {
  // This is the real integration seam: `readPage()` emits snake_case with
  // `text`/`excerpt` and no source id at all, and nothing else in the pipeline
  // would notice if the mapping were wrong — the item would just be stored
  // under a `web:<hash>` id with an empty body.
  const engine = freshEngine({ minLibraryItems: 1 });
  await engine.capture({
    url: "https://www.zhihu.com/question/12345/answer/67890?utm_source=wechat",
    source: "zhihu",
    media_kind: "post",
    title: "如何理解混合检索",
    author: "某位答主",
    text: "向量检索擅长语义，BM25 擅长精确术语。\n\n把两者用 RRF 融合起来可以同时拿到两边的好处。",
    excerpt: "向量检索擅长语义，BM25 擅长精确术语。",
    thumbnail: "",
    tags: ["检索", "RAG"],
    origin: "save-click",
  });

  const stored = await engine.store.getItem("zhihu:12345-67890");
  assert.ok(stored, "identity must come from the URL, matching the Python rules");
  assert.equal(stored.mediaKind, "post");
  assert.deepEqual(stored.tags, ["检索", "RAG"]);

  const hits = await engine.search("RRF 融合 向量 BM25");
  assert.equal(hits.length, 1);
  assert.ok(
    hits[0].chunks.some((c) => c.text.includes("RRF")),
    "the body must have been indexed, not just the title"
  );
});

test("a video payload keeps its excerpt as a description", async () => {
  const engine = freshEngine({ minLibraryItems: 1 });
  await engine.capture({
    url: "https://www.youtube.com/watch?v=Xpzbywj7HbQ",
    media_kind: "video",
    title: "How Vector Databases Actually Work",
    author: "Engineering Deep Dives",
    text: "",
    excerpt: "A talk about approximate nearest neighbour indexes and recall.",
  });
  const stored = await engine.store.getItem("youtube:Xpzbywj7HbQ");
  assert.ok(stored, "a YouTube URL must be identified by the adapter pattern");
  assert.equal(stored.source, "youtube");
  const hits = await engine.search("approximate nearest neighbour recall");
  assert.equal(hits.length, 1, "the description has to be indexed for a video");
});

test("the first query after model failure uses lexical fallback for model vectors", async () => {
  const engine = freshEngine();
  const hash = new HashingEmbedder();
  const model = {
    signature: "model:4",
    embed: async (texts) => texts.map(() => Float32Array.from([1, 0, 0, 0])),
    embedOne: async () => { throw new Error("model unavailable"); },
  };
  const fallback = new FallbackEmbedder(model, hash);
  fallback.promote();
  engine.setEmbedder(fallback);
  await engine.capture(capture(1, "BM25 向量召回 融合", "混合检索把 BM25 和向量召回融合起来解决术语匹配。"));
  const first = await engine.search("BM25 向量召回 融合");
  assert.equal(first.length, 1, "the failing query itself must remain searchable");
  assert.deepEqual(first, await engine.search("BM25 向量召回 融合"));
});

test("capture rejects missing and non-web URLs before storing anything", async () => {
  const engine = freshEngine();
  for (const url of ["", "javascript:alert(1)", "file:///private", "not a url"]) {
    await assert.rejects(engine.capture({ url, title: "invalid" }), /url/i);
  }
  assert.equal((await engine.stats()).items, 0);
});

test("capturing an HTTP-only page preserves its navigable URL", async () => {
  const engine = freshEngine();
  const { item } = await engine.capture({ url: "http://localhost:8080/article", title: "Local article" });
  assert.equal(item.url, "http://localhost:8080/article");
});

test("batch forwarding uses the backend batch route", async () => {
  const requests = [];
  const restore = stubFetch(async (url, options) => {
    requests.push({ url, body: options.body && JSON.parse(options.body) });
    return ok({ ok: true });
  });
  try {
    const remote = new RemoteEngine();
    const payload = { items: [{ url: "https://example.com/a", title: "A" }], origin: "scan" };
    assert.equal(await remote.forwardCapture(payload), true);
    assert.equal(requests.at(-1).url, "http://127.0.0.1:8700/api/capture/batch");
    assert.deepEqual(requests.at(-1).body, payload);
  } finally { restore(); }
});

test("an in-flight capture keeps its model signature after another query demotes it", async () => {
  let finish, started;
  const pending = new Promise((resolve) => { started = resolve; });
  const model = { signature: "model:4",
    embed: (texts) => new Promise((resolve) => {
      finish = () => resolve(texts.map(() => Float32Array.from([1, 0, 0, 0])));
      started();
    }),
    embedOne: async () => { throw new Error("model failure"); },
  };
  const engine = freshEngine();
  const embedder = new FallbackEmbedder(model, new HashingEmbedder());
  embedder.promote();
  engine.setEmbedder(embedder);
  const saving = engine.capture(capture(1, "BM25 向量召回", "混合检索把 BM25 和向量召回融合起来。"));
  await pending;
  await embedder.embedOne("query");
  finish();
  await saving;
  const rows = await engine.store.allChunks();
  assert.ok(rows.every((row) => row.embedder === "model:4" && row.vector.length === 4));
  assert.equal((await engine.index()).vectorCoverage, 0);
});
