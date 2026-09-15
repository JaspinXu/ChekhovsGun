/**
 * URL canonicalisation and site identity — port of `chekhovsgun/sites.py` plus
 * the video-URL patterns the adapters own.
 *
 * Two jobs, both of which have to happen before a page can be stored or matched.
 *
 * **Canonicalisation.** The same Zhihu answer reached from the feed, from search
 * and from a share sheet carries three different query strings. Without
 * stripping them the library accumulates three copies of one answer, and the
 * "you already saved this" card fires on the very page the user is looking at —
 * the most annoying failure this product has.
 *
 * **Identification.** This has to agree with the Python implementation
 * character for character. An item id is `source:source_id`, so if the two
 * engines derive different ids for one page, the same save shows up twice the
 * moment somebody runs the optional backend. `test/sites.test.js` checks the
 * agreement against fixtures captured from Python.
 */

import { MEDIA_POST, MEDIA_VIDEO } from "./ids.js";

/**
 * Query parameters that never change which page you land on. Anything matching
 * one of the prefixes below is dropped too, which covers the `utm_*` family and
 * Bilibili's ever-growing `spm_*` / `share_*` telemetry.
 */
const JUNK_PARAMS = new Set([
  "from", "from_source", "from_spmid", "seid", "vd_source", "unique_k",
  "referrer", "refer", "ref", "ref_src", "ref_url", "hmsr", "hmpl", "hmcu",
  "hmkw", "hmci", "bbid", "ts", "timestamp", "_trigger", "sharer_shareid",
  "sharer_sharetime", "scene", "click_id", "gclid", "fbclid", "msclkid",
  "igshid", "si", "feature", "app", "utm", "channel", "track_id",
  // `shareRedId` is spelled with capitals in the Python set while the lookup
  // lowercases the key, so it never actually matches there. It is reproduced
  // verbatim rather than corrected: these functions derive item ids, and an id
  // that disagrees with the backend's shows the same save twice. Fix it in both
  // places at once or not at all.
  "xhsshare", "appuid", "apptime", "shareRedId", "utm_content",
]);
const JUNK_PREFIXES = ["utm_", "spm_", "share_", "from_", "hm_", "wx", "_hsenc", "_hsmi"];

function isJunk(key) {
  const lowered = key.toLowerCase();
  if (JUNK_PARAMS.has(lowered)) return true;
  return JUNK_PREFIXES.some((prefix) => lowered.startsWith(prefix));
}

/**
 * Strip tracking noise so the same page always produces the same string.
 *
 * Keeps the fragment out entirely: a `#comment-42` anchor is a position on a
 * page, not a different page, and the text-fragment deep links we generate
 * would otherwise round-trip back in as new items.
 */
export function canonicalUrl(url) {
  url = String(url || "").trim();
  if (!url) return "";
  if (!url.includes("://")) url = `https://${url}`;
  let parts;
  try {
    parts = new URL(url);
  } catch {
    return url;
  }
  let host = (parts.hostname || "").toLowerCase();
  if (host.startsWith("www.")) host = host.slice(4);

  // A non-default port is part of the identity; the default one is noise.
  let netloc = host;
  const port = parts.port ? Number(parts.port) : null;
  if (port && port !== 80 && port !== 443) netloc = `${host}:${port}`;

  const kept = [];
  for (const [key, value] of parts.searchParams) {
    if (!isJunk(key)) kept.push([key, value]);
  }
  const query = kept.map(([k, v]) => `${encodeParam(k)}=${encodeParam(v)}`).join("&");
  const path = parts.pathname.replace(/\/+$/, "") || "/";
  return `https://${netloc}${path}${query ? `?${query}` : ""}`;
}

/** `urlencode` in Python quotes with `quote_plus` semantics. */
function encodeParam(value) {
  return encodeURIComponent(value).replace(/%20/g, "+").replace(/[!'()*]/g, (c) =>
    `%${c.charCodeAt(0).toString(16).toUpperCase()}`
  );
}

/** sha1(canonical)[:16] — must match `url_digest` in Python. */
export async function urlDigest(url) {
  const bytes = new TextEncoder().encode(canonicalUrl(url));
  const digest = await crypto.subtle.digest("SHA-1", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

// ------------------------------------------------------------------- videos

const VIDEO_ID = "[A-Za-z0-9_-]{11}";
const VIDEO_PATTERNS = [
  ["youtube", new RegExp(`(?:youtube\\.com|youtube-nocookie\\.com)/watch\\?(?:[^#]*&)?v=(${VIDEO_ID})`)],
  ["youtube", new RegExp(`youtu\\.be/(${VIDEO_ID})`)],
  ["youtube", new RegExp(`youtube\\.com/(?:shorts|embed|v|live)/(${VIDEO_ID})`)],
  ["bilibili", /bilibili\.com\/video\/(BV[0-9A-Za-z]{10})/],
  ["bilibili", /bilibili\.com\/video\/(av\d+)/i],
  ["bilibili", /bilibili\.com\/bangumi\/play\/(ep\d+|ss\d+)/i],
];

/**
 * `[source, sourceId]` for a URL one of the adapters owns, else `["", ""]`.
 * Deliberately narrow: this answers "can we sync this platform?", not "what
 * page is this?".
 */
export function detectSource(url) {
  for (const [name, pattern] of VIDEO_PATTERNS) {
    const match = pattern.exec(url || "");
    if (match) return [name, match[1]];
  }
  return ["", ""];
}

// -------------------------------------------------------------------- sites

function reId(pattern) {
  const compiled = new RegExp(pattern);
  return (path) => {
    const match = compiled.exec(path);
    if (!match) return "";
    return match.slice(1).filter(Boolean).join("-");
  };
}

/**
 * Post-shaped sites worth naming. Anything absent still works — it just lands
 * under `web` with a hashed id and a generic label.
 */
const SITES = [
  { name: "zhihu", label: "知乎", hosts: ["zhihu.com", "zhuanlan.zhihu.com"],
    id: reId("/(?:question/(\\d+)/answer/(\\d+)|p/(\\d+)|pin/(\\d+)|answer/(\\d+))") },
  { name: "xiaohongshu", label: "小红书", hosts: ["xiaohongshu.com", "xhslink.com"],
    id: reId("/(?:explore|discovery/item|item)/([0-9a-f]+)") },
  { name: "weibo", label: "微博", hosts: ["weibo.com", "m.weibo.cn"],
    id: reId("/(?:detail|status)/(\\w+)|/\\d+/(\\w+)$") },
  { name: "wechat", label: "微信公众号", hosts: ["mp.weixin.qq.com"], id: null },
  { name: "juejin", label: "掘金", hosts: ["juejin.cn"], id: reId("/post/(\\d+)") },
  { name: "csdn", label: "CSDN", hosts: ["blog.csdn.net", "csdn.net"],
    id: reId("/article/details/(\\d+)") },
  { name: "jianshu", label: "简书", hosts: ["jianshu.com"], id: reId("/p/(\\w+)") },
  { name: "douban", label: "豆瓣", hosts: ["douban.com"],
    id: reId("/(?:note|topic|status)/(\\d+)") },
  { name: "segmentfault", label: "SegmentFault", hosts: ["segmentfault.com"], id: null },
  { name: "reddit", label: "Reddit", hosts: ["reddit.com", "old.reddit.com"],
    id: reId("/comments/(\\w+)") },
  { name: "x", label: "X / Twitter", hosts: ["twitter.com", "x.com"],
    id: reId("/status/(\\d+)") },
  { name: "medium", label: "Medium", hosts: ["medium.com"], id: reId("-([0-9a-f]{8,})$") },
  { name: "stackoverflow", label: "Stack Overflow",
    hosts: ["stackoverflow.com", "stackexchange.com"], id: reId("/questions/(\\d+)") },
  { name: "github", label: "GitHub", hosts: ["github.com"], id: null },
  { name: "substack", label: "Substack", hosts: ["substack.com"], id: null },
];

export const GENERIC_SOURCE = "web";
export const GENERIC_LABEL = "网页 / Web";

const BY_HOST = new Map();
const BY_NAME = new Map();
for (const site of SITES) {
  BY_NAME.set(site.name, site);
  for (const host of site.hosts) BY_HOST.set(host, site);
}

/** Exact host, then parent domains, so `m.zhihu.com` finds `zhihu.com`. */
function matchHost(host) {
  const labels = host.split(".");
  for (let i = 0; i < labels.length - 1; i += 1) {
    const site = BY_HOST.get(labels.slice(i).join("."));
    if (site) return site;
  }
  return null;
}

/**
 * `{source, sourceId, mediaKind}` for *any* URL.
 *
 * Adapter-owned video sites keep the ids their adapters parse; everything else
 * falls through to the site table, which names the site when it knows it and
 * hashes the canonical URL when it does not. The consequence that matters:
 * `relate` can answer about a page from a site this project has never seen,
 * matching on its text alone.
 */
export async function identifyUrl(url) {
  const [videoSource, videoId] = detectSource(url);
  if (videoSource) {
    return { source: videoSource, sourceId: videoId, mediaKind: MEDIA_VIDEO };
  }

  const canonical = canonicalUrl(url);
  if (!canonical) return { source: "", sourceId: "", mediaKind: MEDIA_POST };

  let host = "";
  try {
    host = new URL(canonical).hostname || "";
  } catch {
    host = "";
  }
  const site = matchHost(host);
  if (!site) {
    return {
      source: GENERIC_SOURCE,
      sourceId: await urlDigest(canonical),
      mediaKind: MEDIA_POST,
    };
  }
  let path = "";
  try {
    path = new URL(canonical).pathname;
  } catch {
    path = "";
  }
  const sourceId = (site.id ? site.id(path) : "") || (await urlDigest(canonical));
  return { source: site.name, sourceId, mediaKind: MEDIA_POST };
}

export function labelFor(source) {
  const site = BY_NAME.get(source);
  if (site) return site.label;
  if (source === "youtube") return "YouTube";
  if (source === "bilibili") return "哔哩哔哩";
  return GENERIC_LABEL;
}
