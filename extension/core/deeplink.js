/**
 * "Go to the exact spot" — port of the deep-link helpers in
 * `chekhovsgun/models.py`.
 *
 * A video has a timeline, so the link carries a timestamp. A post has no
 * timeline but it does have the text itself, so the link carries a text
 * fragment that scrolls to and highlights the matching passage — the same
 * promise, honoured with whatever the medium offers.
 */

import { MEDIA_POST } from "./ids.js";

/**
 * `-`, `,` and `&` are syntax inside a text fragment. `encodeURIComponent`
 * escapes the last two but treats `-` as always-safe, so it needs help.
 */
function escapeFragment(text) {
  return encodeURIComponent(text)
    .replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
    .replace(/-/g, "%2D");
}

/** A leading or trailing slice that does not cut a word in half. */
function snippetOf(text, limit, tail = false) {
  if (text.length <= limit) return text;
  if (tail) {
    const piece = text.slice(-limit);
    const space = piece.indexOf(" ");
    return space >= 0 ? piece.slice(space + 1) : piece;
  }
  const piece = text.slice(0, limit);
  const space = piece.lastIndexOf(" ");
  return space >= 0 ? piece.slice(0, space) : piece;
}

/**
 * Build a `:~:text=` fragment that scrolls to and highlights `text`.
 *
 * Uses the `textStart,textEnd` form for a long passage so the whole thing
 * highlights rather than just its opening words. Matching is defined to be
 * whitespace-normalising and case-insensitive, which is what makes this survive
 * the difference between our cleaned chunk text and the rendered page.
 *
 * Browsers without text-fragment support ignore an unknown fragment and land on
 * the page normally, so the result is always safe to append.
 */
export function textFragment(text, limit = 48) {
  text = String(text || "").split(/\s+/).filter(Boolean).join(" ");
  if (text.length < 8) return "";
  const start = snippetOf(text, limit);
  if (text.length > limit * 2) {
    const end = snippetOf(text, limit, true);
    if (end && end !== start) {
      return `:~:text=${escapeFragment(start)},${escapeFragment(end)}`;
    }
  }
  return `:~:text=${escapeFragment(start)}`;
}

/**
 * The chunk whose text the deep link should scroll to.
 *
 * Body text is preferred over a comment: a comment often sits behind a "show
 * more" control, so a fragment pointing at one silently fails to match, whereas
 * body text is on the page as soon as it loads.
 */
function anchorChunk(chunks) {
  let fallback = null;
  for (const chunk of chunks || []) {
    if (chunk.kind === "title") continue;
    if (chunk.kind === "comment") {
      fallback = fallback || chunk;
      continue;
    }
    return chunk;
  }
  return fallback;
}

export function deepLink(hit) {
  const item = hit.item || {};
  const url = item.url || "";
  if (item.mediaKind === MEDIA_POST) {
    const base = url.split("#")[0];
    const chunk = anchorChunk(hit.chunks);
    if (!chunk) return base;
    const fragment = textFragment(chunk.text);
    return fragment ? `${base}#${fragment}` : base;
  }
  const timestamps = hit.timestamps || [];
  if (!timestamps.length) return url;
  const seconds = Math.floor(Math.max(0, timestamps[0]));
  if (seconds <= 0) return url;
  const sep = url.includes("?") ? "&" : "?";
  return item.source === "bilibili"
    ? `${url}${sep}t=${seconds}`
    : `${url}${sep}t=${seconds}s`;
}
