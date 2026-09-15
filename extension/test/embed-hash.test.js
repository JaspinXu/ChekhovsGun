import test from "node:test";
import assert from "node:assert/strict";

import { HashingEmbedder, dot } from "../core/embed-hash.js";

const embedder = new HashingEmbedder();

test("vectors are unit length", () => {
  for (const text of ["vector databases", "红烧肉的做法", "mixed 中英 text"]) {
    assert.ok(Math.abs(dot(embedder.embedOne(text), embedder.embedOne(text)) - 1) < 1e-5);
  }
});

test("empty text yields a zero vector, not NaN", () => {
  const v = embedder.embedOne("");
  assert.ok(v.every((x) => x === 0), "expected all zeros");
});

test("related texts score above unrelated ones", () => {
  const query = embedder.embedOne("vector search and embeddings");
  const near = embedder.embedOne("embeddings for vector search");
  const far = embedder.embedOne("红烧肉怎么炖才入味");
  assert.ok(dot(query, near) > dot(query, far));
});

test("buckets are well spread — no single bucket dominates", () => {
  // A poor hash puts every CJK bigram sharing a leading character into the
  // same bucket, which silently collapses the whole vector space.
  const counts = new Map();
  const e = new HashingEmbedder();
  for (let i = 0; i < 4000; i += 1) {
    const [index] = e._indexAndSign(`token${i}`);
    counts.set(index, (counts.get(index) || 0) + 1);
  }
  const worst = Math.max(...counts.values());
  assert.ok(counts.size > 500, `only ${counts.size} buckets used`);
  assert.ok(worst < 30, `one bucket got ${worst} of 4000 tokens`);
});

test("signature is distinct from the Python backend's", () => {
  assert.equal(embedder.signature, "local-hash-js:512");
});
