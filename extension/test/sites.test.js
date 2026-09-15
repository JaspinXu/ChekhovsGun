/**
 * URL identity parity.
 *
 * An item id is `source:source_id`. If this file and `chekhovsgun/sites.py`
 * ever disagree about a URL, the same save gets two ids and the user sees it
 * twice the moment they switch the optional backend on — so every case is
 * checked against output captured from Python rather than reasoned about.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { canonicalUrl, identifyUrl, labelFor, urlDigest } from "../core/sites.js";

const fx = JSON.parse(
  readFileSync(new URL("./fixtures-sites.json", import.meta.url), "utf-8")
);

test("canonicalUrl matches Python for every fixture", () => {
  for (const c of fx) {
    assert.equal(canonicalUrl(c.url), c.canonical, c.url);
  }
});

test("urlDigest matches Python for every fixture", async () => {
  for (const c of fx) {
    assert.equal(await urlDigest(c.url), c.digest, c.url);
  }
});

test("identifyUrl matches Python for every fixture", async () => {
  for (const c of fx) {
    const got = await identifyUrl(c.url);
    assert.equal(got.source, c.source, `source for ${c.url}`);
    assert.equal(got.sourceId, c.source_id, `source_id for ${c.url}`);
    assert.equal(got.mediaKind, c.media_kind, `media_kind for ${c.url}`);
  }
});

test("the same page reached three ways gets one id", async () => {
  const forms = [
    "https://www.zhihu.com/question/12345/answer/67890",
    "https://www.zhihu.com/question/12345/answer/67890?utm_source=wechat_session",
    "https://zhihu.com/question/12345/answer/67890/#comment-42",
  ];
  const ids = [];
  for (const url of forms) {
    const { source, sourceId } = await identifyUrl(url);
    ids.push(`${source}:${sourceId}`);
  }
  assert.equal(new Set(ids).size, 1, `got ${JSON.stringify(ids)}`);
});

test("an unknown site still gets a usable identity", async () => {
  const got = await identifyUrl("https://some-blog.example/post/hello");
  assert.equal(got.source, "web");
  assert.ok(got.sourceId.length === 16);
});

test("labelFor names the sites the card displays", () => {
  assert.equal(labelFor("zhihu"), "知乎");
  assert.equal(labelFor("youtube"), "YouTube");
  assert.equal(labelFor("bilibili"), "哔哩哔哩");
  assert.equal(labelFor("nonesuch"), "网页 / Web");
});
