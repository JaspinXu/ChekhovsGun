/**
 * Tests for the embedder fallback policy.
 *
 * The property being protected is that the reported signature always describes
 * the vectors actually being produced. If those ever disagree, retrieval
 * compares vectors from two different spaces and returns results that are
 * confidently wrong rather than merely worse.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { FallbackEmbedder } from "../engine/embed-proxy.js";
import { HashingEmbedder } from "../core/embed-hash.js";

function fakeModel({ fail = false } = {}) {
  return {
    signature: "multilingual-e5-small:384",
    calls: 0,
    async embed(texts) {
      this.calls += 1;
      if (fail) throw new Error("onnx blew up");
      return texts.map(() => Float32Array.from(new Array(384).fill(0.05)));
    },
    async embedOne(text) {
      return (await this.embed([text]))[0];
    },
  };
}

test("before promotion everything goes through the hashing embedder", async () => {
  const model = fakeModel();
  const embedder = new FallbackEmbedder(model, new HashingEmbedder());
  const [vector] = await embedder.embed(["hello world"]);
  assert.equal(vector.length, 512);
  assert.equal(embedder.signature, "local-hash-js:512");
  assert.equal(model.calls, 0, "the model must not be touched before it is ready");
});

test("after promotion the model is used and the signature follows", async () => {
  const model = fakeModel();
  const embedder = new FallbackEmbedder(model, new HashingEmbedder());
  embedder.promote();
  const [vector] = await embedder.embed(["hello world"]);
  assert.equal(vector.length, 384);
  assert.equal(embedder.signature, "multilingual-e5-small:384");
});

test("a model failure falls back for that call and the signature follows it down", async () => {
  const embedder = new FallbackEmbedder(fakeModel({ fail: true }), new HashingEmbedder());
  embedder.promote();
  const [vector] = await embedder.embed(["hello world"]);
  assert.equal(vector.length, 512, "the call still has to return something usable");
  assert.equal(
    embedder.signature,
    "local-hash-js:512",
    "reporting the model signature here would mix two vector spaces in one ranking"
  );
  assert.match(embedder.lastError, /onnx blew up/);
});

test("a failure on embedOne demotes as well", async () => {
  const embedder = new FallbackEmbedder(fakeModel({ fail: true }), new HashingEmbedder());
  embedder.promote();
  const vector = await embedder.embedOne("a query");
  assert.equal(vector.length, 512);
  assert.equal(embedder.usingModel, false);
});

test("once demoted it stays on the fallback rather than retrying every call", async () => {
  const model = fakeModel({ fail: true });
  const embedder = new FallbackEmbedder(model, new HashingEmbedder());
  embedder.promote();
  await embedder.embed(["one"]);
  await embedder.embed(["two"]);
  await embedder.embed(["three"]);
  assert.equal(model.calls, 1, "a broken encoder must not be re-tried on every query");
});
