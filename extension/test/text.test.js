/**
 * Parity tests for the tokenizer port.
 *
 * The fixtures in `fixtures-text.json` were captured by running the real
 * `chekhovsgun.rag.text` functions. Dense and lexical retrieval both consume
 * `tokenize`, and the Python and JavaScript engines federate their results, so
 * a drift here would silently degrade every query rather than fail loudly.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { normalize, scriptOf, sentences, snippet, tokenize } from "../core/text.js";

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures-text.json", import.meta.url), "utf-8")
);

test("normalize matches Python", () => {
  for (const c of fixtures.tokenize) {
    assert.equal(normalize(c.text), c.normalize, `normalize(${JSON.stringify(c.text)})`);
  }
});

test("tokenize matches Python", () => {
  for (const c of fixtures.tokenize) {
    assert.deepEqual(tokenize(c.text), c.tokens, `tokenize(${JSON.stringify(c.text)})`);
  }
});

test("tokenize with stopwords kept matches Python", () => {
  for (const c of fixtures.tokenize) {
    assert.deepEqual(
      tokenize(c.text, { dropStopwords: false }),
      c.tokens_keep,
      `tokenize(${JSON.stringify(c.text)}, keep)`
    );
  }
});

test("scriptOf matches Python", () => {
  for (const c of fixtures.tokenize) {
    assert.equal(scriptOf(c.text), c.script, `scriptOf(${JSON.stringify(c.text)})`);
  }
});

test("sentences matches Python", () => {
  for (const c of fixtures.sentences) {
    assert.deepEqual(sentences(c.text), c.sentences, `sentences(${JSON.stringify(c.text)})`);
  }
});

test("snippet centres on the first query token present", () => {
  const text = "x".repeat(200) + " the real failure mode of pure vector search is terminology " + "y".repeat(200);
  const out = snippet(text, "vector search");
  assert.match(out, /vector search/);
  assert.ok(out.length < text.length);
  assert.ok(out.startsWith("…"));
});

test("snippet returns short text unchanged", () => {
  assert.equal(snippet("short enough", "anything"), "short enough");
});
