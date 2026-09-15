import test from "node:test";
import assert from "node:assert/strict";

import { Bm25Index } from "../core/bm25.js";
import { tokenize } from "../core/text.js";

const docs = [
  ["a", "vector database stores embeddings for similarity search"],
  ["b", "bm25 is a lexical ranking function over an inverted index"],
  ["c", "hybrid search fuses vector similarity with bm25"],
  ["d", "红烧肉 要 先 焯水 再 炖"],
  ["e", "the cat sat on the mat"],
];
const index = new Bm25Index(
  docs.map(([id]) => id),
  docs.map(([, text]) => tokenize(text))
);

test("ranks the document that shares the most rare terms first", () => {
  const ranked = index.search(tokenize("bm25 lexical inverted index"), 5);
  assert.equal(index.chunkIds[ranked[0][0]], "b");
});

test("returns nothing when no query token appears", () => {
  assert.deepEqual(index.search(tokenize("quantum chromodynamics"), 5), []);
});

test("respects the limit", () => {
  const ranked = index.search(tokenize("search vector bm25"), 2);
  assert.equal(ranked.length, 2);
});

test("skips tokens that appear in most of the corpus", () => {
  // The cutoff is max(8, total * MAX_DF_RATIO), so the floor of 8 protects a
  // small library and the ratio only bites on a real corpus. Forty documents
  // put the cutoff at 22; a token in 30 of them must contribute nothing.
  const ids = Array.from({ length: 40 }, (_, i) => `d${i}`);
  const tokenLists = ids.map((_, i) =>
    i < 30 ? ["common", `body${i}`] : [`body${i}`]
  );
  const wide = new Bm25Index(ids, tokenLists);
  assert.equal(wide.maxDf, 22);
  assert.deepEqual(wide.search(["common"], 5), []);
  assert.equal(wide.search(["body3"], 5).length, 1);
});

test("idfWeights drops tokens the library has never seen", () => {
  const weights = index.idfWeights(["bm25", "neverseenanywhere"]);
  assert.ok(weights.has("bm25"));
  assert.ok(!weights.has("neverseenanywhere"));
});

test("rarer tokens get a higher idf", () => {
  // `vector` appears in two documents, `焯水` in exactly one.
  const weights = index.idfWeights(["vector", "焯水"]);
  assert.ok(weights.get("焯水") > weights.get("vector"));
});

test("empty index answers without throwing", () => {
  const empty = new Bm25Index([], []);
  assert.deepEqual(empty.search(["anything"], 5), []);
  assert.equal(empty.idfWeights(["anything"]).size, 0);
});
