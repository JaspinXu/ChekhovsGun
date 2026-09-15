/**
 * Storage tests, against fake-indexeddb.
 *
 * The behaviour that matters here is not "can it round-trip a row" but the two
 * rules that protect the user's own data: re-capturing a page must replace its
 * stale chunks, and must never resurrect something they marked 学完了.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { IDBFactory } from "fake-indexeddb";

import { IdbStore } from "../platform/idb.js";
import { STATUS_DIGESTED } from "../core/ids.js";

function freshStore(name = `db-${Math.random().toString(36).slice(2)}`) {
  return new IdbStore(new IDBFactory(), name);
}

const item = {
  id: "zhihu:42",
  source: "zhihu",
  sourceId: "42",
  title: "怎么做红烧肉",
  url: "https://www.zhihu.com/answer/42",
  mediaKind: "post",
};

const chunks = [
  { id: "c1", itemId: "zhihu:42", ordinal: 0, text: "标题", kind: "title", tokens: ["红烧"] },
  { id: "c2", itemId: "zhihu:42", ordinal: 1, text: "正文", kind: "body", tokens: ["焯水"] },
];

test("an item round-trips with its chunks", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  const got = await store.getItem("zhihu:42");
  assert.equal(got.title, "怎么做红烧肉");
  assert.equal((await store.allChunks()).length, 2);
  assert.equal(await store.countItems(), 1);
});

test("re-capturing replaces the old chunks instead of accumulating them", async () => {
  // Chunk ids are content-derived, so edited text yields new ids; without the
  // delete pass the stale rows would linger forever and keep matching.
  const store = freshStore();
  await store.replaceItem(item, chunks);
  await store.replaceItem(item, [
    { id: "c9", itemId: "zhihu:42", ordinal: 0, text: "改过的正文", kind: "body", tokens: ["新"] },
  ]);
  const all = await store.allChunks();
  assert.equal(all.length, 1);
  assert.equal(all[0].id, "c9");
});

test("re-capturing does not resurrect an item marked 学完了", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  await store.setStatus("zhihu:42", STATUS_DIGESTED);
  await store.replaceItem({ ...item, title: "改了标题" }, chunks);
  const got = await store.getItem("zhihu:42");
  assert.equal(got.status, STATUS_DIGESTED, "ingest must not own the lifecycle column");
  assert.equal(got.title, "改了标题", "but content should still update");
});

test("deleting an item takes its chunks with it", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  await store.deleteItem("zhihu:42");
  assert.equal(await store.countItems(), 0);
  assert.equal((await store.allChunks()).length, 0);
});

test("vectors survive the round-trip as Float32Array", async () => {
  const store = freshStore();
  await store.replaceItem(item, [
    { ...chunks[0], vector: Float32Array.from([0.1, 0.2, 0.3]), embedder: "local-hash-js:512" },
  ]);
  const [got] = await store.allChunks();
  assert.ok(got.vector instanceof Float32Array);
  assert.ok(Math.abs(got.vector[1] - 0.2) < 1e-6);
});

test("chunksNeedingEmbedding finds rows from another embedder", async () => {
  const store = freshStore();
  await store.replaceItem(item, [
    { ...chunks[0], vector: Float32Array.from([1, 0]), embedder: "old:2" },
    { ...chunks[1], vector: Float32Array.from([0, 1]), embedder: "new:2" },
  ]);
  const stale = await store.chunksNeedingEmbedding("new:2");
  assert.equal(stale.length, 1);
  assert.equal(stale[0].id, "c1");
});

test("chunksNeedingEmbedding finds rows with no vector at all", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  const stale = await store.chunksNeedingEmbedding("new:2");
  assert.equal(stale.length, 2);
});

test("putVectors upgrades rows and stamps the new signature", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  await store.putVectors([{ id: "c1", vector: Float32Array.from([0.5, 0.5]) }], "new:2");
  const all = await store.allChunks();
  const upgraded = all.find((c) => c.id === "c1");
  assert.equal(upgraded.embedder, "new:2");
  assert.equal(upgraded.dim, 2);
  assert.equal((await store.chunksNeedingEmbedding("new:2")).length, 1);
});

test("the revision counter moves on every write", async () => {
  const store = freshStore();
  const before = store.revision;
  await store.replaceItem(item, chunks);
  assert.ok(store.revision > before, "the index cache keys off this");
});

test("findItemByUrl locates a save by the page it came from", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  const got = await store.findItemByUrl("https://www.zhihu.com/answer/42");
  assert.equal(got.id, "zhihu:42");
  assert.equal(await store.findItemByUrl("https://example.com/nope"), null);
});

test("stats summarise the library", async () => {
  const store = freshStore();
  await store.replaceItem(item, chunks);
  await store.replaceItem({ ...item, id: "youtube:v1", source: "youtube", url: "https://y/1" }, []);
  await store.setStatus("zhihu:42", STATUS_DIGESTED);
  const stats = await store.stats();
  assert.equal(stats.items, 2);
  assert.equal(stats.digested, 1);
  assert.deepEqual(stats.bySource, { zhihu: 1, youtube: 1 });
});
