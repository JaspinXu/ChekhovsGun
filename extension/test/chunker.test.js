/**
 * Chunker parity. Boundaries here decide what a retrieved passage looks like to
 * the user, and the char/second double-limit plus the overlap carry are easy to
 * get subtly wrong, so every case is checked against Python's output.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { chunkComments, chunkItem, chunkSegments, chunkText } from "../core/chunker.js";
import { MEDIA_POST } from "../core/ids.js";

const fx = JSON.parse(
  readFileSync(new URL("./fixtures-chunker.json", import.meta.url), "utf-8")
);

const segs = Array.from({ length: 30 }, (_, i) => ({
  text: `sentence number ${i} about vector search and embeddings.`,
  start: i * 3.0,
  end: i * 3.0 + 3.0,
}));

test("chunkSegments matches Python on a normal transcript", () => {
  const got = chunkSegments("t:1", segs);
  assert.equal(got.length, fx.segments.length);
  got.forEach((c, i) => {
    assert.equal(c.text, fx.segments[i].text, `chunk ${i} text`);
    assert.equal(c.start, fx.segments[i].start, `chunk ${i} start`);
    assert.equal(c.end, fx.segments[i].end, `chunk ${i} end`);
    assert.equal(c.id, fx.segments[i].id, `chunk ${i} id`);
  });
});

test("chunkSegments splits on the seconds limit, not just characters", () => {
  // Twelve two-character segments 20s apart: far under maxChars, far over
  // maxSeconds. If the wall-clock bound were missing this would be one chunk.
  const slow = Array.from({ length: 12 }, (_, i) => ({
    text: "uh",
    start: i * 20.0,
    end: i * 20.0 + 20.0,
  }));
  const got = chunkSegments("t:2", slow);
  assert.equal(got.length, fx.segments_slow.length);
  assert.ok(got.length > 1, "the seconds limit must have split this");
  got.forEach((c, i) => assert.equal(c.text, fx.segments_slow[i].text, `chunk ${i}`));
});

test("chunkText matches Python", () => {
  const prose = "第一句话讲的是向量检索。第二句话讲的是倒排索引。Third sentence is in English. ".repeat(6);
  const got = chunkText("t:3", prose);
  assert.equal(got.length, fx.text.length);
  got.forEach((c, i) => assert.equal(c.text, fx.text[i].text, `chunk ${i}`));
});

test("chunkItem matches Python for a post with body and comments", () => {
  const item = {
    id: "zhihu:42",
    title: "怎么做红烧肉",
    author: "张三",
    description: "这是一个摘要 excerpt",
    tags: ["烹饪", "家常菜"],
    folder: "收藏夹",
    mediaKind: MEDIA_POST,
  };
  const body = Array.from({ length: 8 }, (_, i) => ({
    text: `第${i}段正文，讲的是火候和糖色的控制方法。`,
    start: 0,
    end: 0,
  }));
  const comments = [
    { text: "很有用的分享", likes: 10, replies: ["同感，我也试过了"] },
    { text: "短", likes: 1 },
  ];
  const got = chunkItem(item, body, null, comments);
  assert.deepEqual(
    got.map((c) => [c.ordinal, c.kind, c.text]),
    fx.item.map((c) => [c.ordinal, c.kind, c.text])
  );
  got.forEach((c, i) => assert.equal(c.id, fx.item[i].id, `chunk ${i} id`));
});

test("chunkItem matches Python for a video with a description", () => {
  const item = {
    id: "youtube:abc",
    title: "How Vector DBs Work",
    author: "Deep Dive",
    description: "A talk about ANN indexes and recall.",
    tags: [],
  };
  const got = chunkItem(item, segs.slice(0, 6));
  assert.deepEqual(
    got.map((c) => [c.ordinal, c.kind, c.text]),
    fx.item_video.map((c) => [c.ordinal, c.kind, c.text])
  );
});

test("chunk 0 is always the header, even with no body at all", () => {
  const got = chunkItem({ id: "x:1", title: "Only A Title", author: "Someone", tags: [] });
  assert.equal(got.length, 1);
  assert.equal(got[0].kind, "title");
  assert.equal(got[0].text, "Only A Title · Someone");
});

test("a post's description is dropped when its body is present", () => {
  // The capture sends an excerpt as the description; indexing both would double
  // every passage and let the item dominate its own results.
  const base = { id: "z:9", title: "T", tags: [], mediaKind: MEDIA_POST, description: "excerpt text here" };
  const withBody = chunkItem(base, [{ text: "the full body of the answer goes here", start: 0, end: 0 }]);
  assert.ok(!withBody.some((c) => c.kind === "description"));
  const withoutBody = chunkItem(base, []);
  assert.ok(withoutBody.some((c) => c.kind === "description"));
});

test("duplicate passages are de-duplicated by id", () => {
  // Auto-generated subtitles repeat verbatim lines constantly.
  const repeated = Array.from({ length: 40 }, () => ({
    text: "exactly the same sentence repeated over and over again",
    start: 0,
    end: 0,
  }));
  const got = chunkItem({ id: "d:1", title: "T", tags: [] }, repeated);
  const ids = got.map((c) => c.id);
  assert.equal(new Set(ids).size, ids.length);
});

test("comments too short to carry meaning are skipped", () => {
  const got = chunkComments("c:1", [{ text: "短" }, { text: "a genuinely useful comment" }]);
  assert.equal(got.length, 1);
  assert.equal(got[0].kind, "comment");
});
