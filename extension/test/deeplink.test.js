/**
 * Deep-link parity. The text fragment is what makes "jump to the exact
 * paragraph" work; a mis-escaped one fails silently — the browser just lands on
 * the top of the page — so it is checked against Python rather than eyeballed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { deepLink, textFragment } from "../core/deeplink.js";

const fx = JSON.parse(
  readFileSync(new URL("./fixtures-deeplink.json", import.meta.url), "utf-8")
);

test("textFragment matches Python", () => {
  for (const c of fx) {
    assert.equal(textFragment(c.text), c.fragment, JSON.stringify(c.text.slice(0, 40)));
  }
});

test("a video link carries the timestamp of the matching passage", () => {
  const hit = {
    item: { url: "https://www.youtube.com/watch?v=abc", source: "youtube", mediaKind: "video" },
    timestamps: [1000.4],
  };
  assert.equal(deepLink(hit), "https://www.youtube.com/watch?v=abc&t=1000s");
});

test("bilibili uses its own timestamp parameter form", () => {
  const hit = {
    item: { url: "https://www.bilibili.com/video/BV1xx", source: "bilibili", mediaKind: "video" },
    timestamps: [65.9],
  };
  assert.equal(deepLink(hit), "https://www.bilibili.com/video/BV1xx?t=65");
});

test("a video with no usable timestamp links to the video itself", () => {
  const item = { url: "https://y/abc", source: "youtube", mediaKind: "video" };
  assert.equal(deepLink({ item, timestamps: [] }), "https://y/abc");
  assert.equal(deepLink({ item, timestamps: [0] }), "https://y/abc");
});

test("a post links to the body passage, not to a comment", () => {
  // A comment usually sits behind a "show more" control, so a fragment pointing
  // at one silently fails to match.
  const hit = {
    item: { url: "https://www.zhihu.com/answer/42", source: "zhihu", mediaKind: "post" },
    chunks: [
      { kind: "title", text: "the title" },
      { kind: "comment", text: "a comment that is long enough to anchor" },
      { kind: "body", text: "the body passage that is long enough to anchor" },
    ],
  };
  assert.match(deepLink(hit), /#:~:text=the%20body%20passage/);
});

test("a post falls back to a comment when there is no body", () => {
  const hit = {
    item: { url: "https://www.zhihu.com/answer/42", mediaKind: "post" },
    chunks: [
      { kind: "title", text: "the title" },
      { kind: "comment", text: "a comment that is long enough to anchor" },
    ],
  };
  assert.match(deepLink(hit), /#:~:text=a%20comment/);
});

test("a post with nothing to anchor links to the page itself", () => {
  const hit = { item: { url: "https://x/1#old", mediaKind: "post" }, chunks: [] };
  assert.equal(deepLink(hit), "https://x/1");
});
