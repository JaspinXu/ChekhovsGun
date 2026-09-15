/**
 * Retrieval tests.
 *
 * `confidenceOf` and `coverage` are pure arithmetic, so they are checked
 * against values captured from Python. The ranking itself cannot be compared
 * numerically — the two engines deliberately use different hash functions and
 * therefore different vector spaces — so it is tested on the behaviour that
 * actually matters: does the right save come first, and does the confidence
 * gate stay shut when nothing is relevant.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { HashingEmbedder } from "../core/embed-hash.js";
import { MemoryIndex } from "../core/index-memory.js";
import {
  Retriever,
  confidenceOf,
  confidenceLexicalOnly,
  coverage,
  contextAsQuery,
} from "../core/retrieve.js";
import { chunkItem } from "../core/chunker.js";
import { tokenize } from "../core/text.js";
import { STATUS_DIGESTED } from "../core/ids.js";

const fx = JSON.parse(
  readFileSync(new URL("./fixtures-score.json", import.meta.url), "utf-8")
);

const embedder = new HashingEmbedder();

test("confidenceOf matches Python for every sampled pair", () => {
  for (const c of fx.confidence) {
    assert.ok(
      Math.abs(confidenceOf(c.dense, c.coverage) - c.confidence) < 1e-9,
      `confidenceOf(${c.dense}, ${c.coverage})`
    );
  }
});

test("coverage matches Python", () => {
  for (const c of fx.coverage) {
    const weights = new Map(Object.entries(c.weights));
    const buckets = { cjk: new Map(), latin: new Map(), mixed: new Map(weights) };
    for (const [token, weight] of weights) {
      buckets[/[⺀-￿]/.test(token) ? "cjk" : "latin"].set(token, weight);
    }
    const got = coverage(buckets, c.text, new Set(tokenize(c.text)));
    assert.ok(Math.abs(got - c.coverage) < 1e-9, `coverage(${JSON.stringify(c.text)})`);
  }
});

test("a single shared common word is not enough to look confident", () => {
  // 做法 appears in both a braise recipe and, say, a database talk. On its own
  // it must not produce a high coverage score.
  const one = new Map([["做法", 1.2]]);
  const buckets = { cjk: one, latin: new Map(), mixed: one };
  const got = coverage(buckets, "红烧肉的做法", new Set(["做法"]));
  assert.ok(got < 0.6, `lone match scored ${got}`);
});

// ---------------------------------------------------------------- a library

function buildLibrary(items) {
  const allChunks = [];
  for (const { item, segments } of items) {
    for (const chunk of chunkItem(item, segments || [])) {
      const vector = embedder.embedOne(chunk.text);
      allChunks.push({
        ...chunk,
        tokens: tokenize(chunk.text),
        vector,
        embedder: embedder.signature,
      });
    }
  }
  return new MemoryIndex(items.map((i) => i.item), allChunks, embedder.signature);
}

function video(id, title, author, body, extra = {}) {
  return {
    item: {
      id: `youtube:${id}`,
      source: "youtube",
      sourceId: id,
      title,
      author,
      url: `https://www.youtube.com/watch?v=${id}`,
      tags: [],
      status: "active",
      ...extra,
    },
    segments: body.map((text, i) => ({ text, start: i * 30, end: i * 30 + 30 })),
  };
}

const library = buildLibrary([
  video("v1", "How Vector Databases Actually Work", "Engineering Deep Dives", [
    "The real failure mode of pure vector search is exact terminology.",
    "Hybrid search with BM25 fixes the cases where embeddings blur a precise term.",
    "Chunking strategy matters more than the encoder you pick for retrieval quality.",
  ]),
  video("v2", "红烧肉的家常做法", "厨房日记", [
    "先把五花肉焯水去腥，然后下锅炒糖色。",
    "小火慢炖四十分钟，收汁的时候火候是关键。",
  ]),
  video("v3", "Kubernetes Networking Explained", "Cloud Native TV", [
    "Every pod gets its own IP address inside the cluster network.",
    "Services provide a stable virtual IP in front of a set of pods.",
  ]),
  video("v4", "Rust Ownership and Borrowing", "Systems Weekly", [
    "The borrow checker enforces that only one mutable reference exists at a time.",
    "Lifetimes tell the compiler how long a reference stays valid.",
  ]),
]);

test("the relevant save ranks first for an on-topic query", () => {
  const retriever = new Retriever(library, embedder);
  const hits = retriever.searchItems("chunking and hybrid search for retrieval quality");
  assert.ok(hits.length > 0, "expected at least one hit");
  assert.equal(hits[0].item.id, "youtube:v1");
});

test("a Chinese query reaches a Chinese save", () => {
  const retriever = new Retriever(library, embedder);
  const hits = retriever.searchItems("五花肉怎么炒糖色才不苦");
  assert.ok(hits.length > 0);
  assert.equal(hits[0].item.id, "youtube:v2");
});

test("an unrelated query is gated out entirely", () => {
  const retriever = new Retriever(library, embedder);
  const hits = retriever.searchItems("best espresso grinder under 300 dollars");
  assert.equal(hits.length, 0, `expected silence, got ${hits.map((h) => h.item.title)}`);
});

test("no query at all returns nothing rather than everything", () => {
  const retriever = new Retriever(library, embedder);
  assert.deepEqual(retriever.searchItems("   "), []);
});

test("one item cannot monopolise the candidate list", () => {
  const long = video(
    "v5",
    "A Very Long Lecture",
    "Someone",
    Array.from({ length: 60 }, (_, i) => `passage ${i} about distributed consensus and raft leader election`)
  );
  const index = buildLibrary([long]);
  const retriever = new Retriever(index, embedder);
  const hits = retriever.searchChunks("raft leader election consensus", { limit: 40 });
  assert.ok(hits.length <= 4, `per-item cap let ${hits.length} chunks through`);
});

test("relate excludes the item you are already looking at", () => {
  const retriever = new Retriever(library, embedder);
  const hits = retriever.relate({
    source: "youtube",
    sourceId: "v1",
    title: "How Vector Databases Actually Work",
    author: "Engineering Deep Dives",
  });
  assert.ok(!hits.some((h) => h.item.id === "youtube:v1"), "should not surface itself");
});

test("relate excludes items marked 学完了", () => {
  const withDigested = buildLibrary([
    video("v1", "How Vector Databases Actually Work", "Engineering Deep Dives", [
      "Hybrid search with BM25 fixes the cases where embeddings blur a precise term.",
      "Chunking strategy matters more than the encoder you pick.",
    ], { status: STATUS_DIGESTED }),
  ]);
  const retriever = new Retriever(withDigested, embedder);
  const hits = retriever.relate({
    source: "blog",
    sourceId: "x",
    title: "chunking and hybrid search explained",
  });
  assert.equal(hits.length, 0, "a digested item must stop firing");
});

test("contextAsQuery matches the Python Context.as_query shape", () => {
  assert.equal(
    contextAsQuery({ title: "T", author: "A", tags: ["x", "y"], description: "D" }),
    "T\nA\nx y\nD"
  );
  assert.equal(contextAsQuery({ title: "T" }), "T");
});

test("chunks embedded by another backend still answer through BM25", () => {
  // This is the guarantee that makes the model upgrade safe: while chunks are
  // being re-embedded, the not-yet-upgraded ones must remain findable.
  const chunks = [...library.chunks.values()].map((c) => ({
    ...c,
    embedder: "some-other-embedder:768",
  }));
  const stale = new MemoryIndex([...library.items.values()], chunks, embedder.signature);
  assert.equal(stale.vectorCoverage, 0, "no vector should be comparable");
  const retriever = new Retriever(stale, embedder);
  const hits = retriever.searchItems("hybrid search bm25 embeddings terminology");
  assert.ok(hits.length > 0, "lexical retrieval must still find it");
  assert.equal(hits[0].item.id, "youtube:v1");
});

test("the lexical-only path does not start firing on unrelated pages", () => {
  // The fallback above discounts rather than annihilates the surviving signal,
  // so it must be checked in both directions: the stale index has to stay quiet
  // for a query that has nothing to do with anything in the library.
  const chunks = [...library.chunks.values()].map((c) => ({
    ...c,
    embedder: "some-other-embedder:768",
  }));
  const stale = new MemoryIndex([...library.items.values()], chunks, embedder.signature);
  const retriever = new Retriever(stale, embedder);
  const hits = retriever.searchItems("best espresso grinder under 300 dollars");
  assert.equal(hits.length, 0, `expected silence, got ${hits.map((h) => h.item.title)}`);
});

test("confidenceLexicalOnly still demands a real overlap", () => {
  // Clearing the 0.30 floor must take roughly 0.35 coverage — a multi-term
  // overlap, not one shared word.
  assert.ok(confidenceLexicalOnly(0.2) < 0.3, "one weak match must not fire");
  assert.ok(confidenceLexicalOnly(0.5) > 0.3, "a solid overlap must fire");
  assert.equal(confidenceLexicalOnly(0), 0);
});
