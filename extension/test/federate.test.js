import test from "node:test";
import assert from "node:assert/strict";

import { canonicalUrl, federate } from "../engine/federate.js";

const hit = (id, url, { chunks = 1, confidence = 0.5 } = {}) => ({
  item: { id, url, title: id },
  chunks: Array.from({ length: chunks }, (_, i) => ({ id: `${id}-${i}`, text: "x" })),
  confidence,
  score: 1,
});

test("canonicalUrl strips the noise that makes one save look like two", () => {
  const forms = [
    "https://www.bilibili.com/video/BV1xx?spm_id_from=333.999&vd_source=abc",
    "https://m.bilibili.com/video/BV1xx/",
    "https://bilibili.com/video/BV1xx#reply",
    "https://www.bilibili.com/video/BV1xx?utm_source=weixin",
  ];
  const canonical = forms.map(canonicalUrl);
  assert.equal(new Set(canonical).size, 1, `got ${JSON.stringify(canonical)}`);
});

test("canonicalUrl keeps parameters that actually identify the page", () => {
  assert.notEqual(
    canonicalUrl("https://www.youtube.com/watch?v=aaa"),
    canonicalUrl("https://www.youtube.com/watch?v=bbb")
  );
});

test("canonicalUrl survives a malformed URL", () => {
  assert.equal(canonicalUrl("not a url"), "not a url");
  assert.equal(canonicalUrl(""), "");
});

test("with no backend the local list passes through untouched", () => {
  const local = [hit("a", "https://x/a"), hit("b", "https://x/b")];
  assert.deepEqual(federate(local, []), local.slice(0, 5));
});

test("with no local results the backend list is used", () => {
  const remote = [hit("a", "https://x/a")];
  assert.equal(federate([], remote).length, 1);
});

test("both empty yields nothing rather than throwing", () => {
  assert.deepEqual(federate([], []), []);
  assert.deepEqual(federate(null, undefined), []);
});

test("the same save from both sides appears once", () => {
  const local = [hit("zhihu:42", "https://www.zhihu.com/answer/42/")];
  const remote = [hit("zhihu:42", "https://zhihu.com/answer/42?utm_source=x")];
  const merged = federate(local, remote);
  assert.equal(merged.length, 1);
  assert.deepEqual(merged[0].origins, ["local", "remote"]);
});

test("a save both sides rank highly outranks one only a single side knows", () => {
  const local = [hit("shared", "https://x/shared"), hit("localonly", "https://x/l")];
  const remote = [hit("shared", "https://x/shared"), hit("remoteonly", "https://x/r")];
  const merged = federate(local, remote);
  assert.equal(merged[0].item.id, "shared");
});

test("the record with more passages wins the merge", () => {
  const local = [hit("a", "https://x/a", { chunks: 1 })];
  const remote = [hit("a", "https://x/a", { chunks: 3 })];
  const merged = federate(local, remote);
  assert.equal(merged[0].chunks.length, 3, "keep the side with more evidence to show");
});

test("the limit is honoured across the merged list", () => {
  const local = Array.from({ length: 9 }, (_, i) => hit(`l${i}`, `https://x/l${i}`));
  const remote = Array.from({ length: 9 }, (_, i) => hit(`r${i}`, `https://x/r${i}`));
  assert.equal(federate(local, remote, { limit: 3 }).length, 3);
});

test("items with no URL still merge on their id", () => {
  const local = [{ item: { id: "youtube:v1", url: "" }, chunks: [], confidence: 0.4 }];
  const remote = [{ item: { id: "youtube:v1", url: "" }, chunks: [], confidence: 0.6 }];
  assert.equal(federate(local, remote).length, 1);
});

test("case-sensitive video IDs are not collapsed into a single save", () => {
  const merged = federate(
    [hit("youtube:Abcdefghijk", "https://youtube.com/watch?v=Abcdefghijk")],
    [hit("youtube:abcdefghijk", "https://youtube.com/watch?v=abcdefghijk")]
  );
  assert.equal(merged.length, 2);
});

test("stable item IDs deduplicate short and watch URLs", () => {
  const merged = federate(
    [hit("youtube:abcdefghijk", "https://youtu.be/abcdefghijk")],
    [hit("youtube:abcdefghijk", "https://youtube.com/watch?v=abcdefghijk&t=12")]
  );
  assert.equal(merged.length, 1);
});

test("a backend-only result keeps its origin", () => {
  assert.deepEqual(federate([], [hit("a", "https://x/a")])[0].origins, ["remote"]);
});
