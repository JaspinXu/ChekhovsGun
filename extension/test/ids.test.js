/**
 * The chunk id is a cross-language contract: the Python adapters and the
 * extension both write into the same conceptual library, and a mismatch would
 * duplicate every chunk. Fixtures come from `chekhovsgun.models.make_chunk_id`.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { makeChunkId, makeItemId } from "../core/ids.js";

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures-ids.json", import.meta.url), "utf-8")
);

test("makeChunkId matches Python for every fixture", () => {
  for (const c of fixtures) {
    assert.equal(makeChunkId(c.item, c.ordinal, c.text), c.id, JSON.stringify(c.text.slice(0, 30)));
  }
});

test("makeItemId matches the Python format", () => {
  assert.equal(makeItemId("youtube", "Xpzbywj7HbQ"), "youtube:Xpzbywj7HbQ");
});

test("chunk ids are stable and text-sensitive", () => {
  assert.equal(makeChunkId("a:b", 1, "x"), makeChunkId("a:b", 1, "x"));
  assert.notEqual(makeChunkId("a:b", 1, "x"), makeChunkId("a:b", 1, "y"));
  assert.notEqual(makeChunkId("a:b", 1, "x"), makeChunkId("a:b", 2, "x"));
});
