/**
 * Turn a saved item plus its transcript / body into retrievable chunks.
 * Port of `chekhovsgun/rag/chunker.py`.
 *
 * Subtitles arrive as hundreds of 1–3 second fragments; embedding each one is
 * both slow and useless (no fragment carries enough meaning). We merge them
 * into passages bounded by *two* limits at once — characters and wall-clock
 * seconds — so a fast talker and a slow talker both produce comparably sized
 * chunks, and every chunk keeps the timestamp that deep-links into the video.
 */

import { RETRIEVAL_DEFAULTS } from "./config.js";
import { makeChunkId, MEDIA_POST } from "./ids.js";
import { normalize, sentences } from "./text.js";

function clean(text) {
  return String(text || "").replace(/​/g, " ").split(/\s+/).filter(Boolean).join(" ");
}

function makeChunk(itemId, ordinal, text, { start = 0, end = 0, kind = "transcript" } = {}) {
  return { id: makeChunkId(itemId, ordinal, text), itemId, ordinal, text, start, end, kind };
}

/** Merge timed segments into overlapping passages. */
export function chunkSegments(
  itemId,
  segments,
  {
    maxChars = RETRIEVAL_DEFAULTS.chunkChars,
    overlapChars = RETRIEVAL_DEFAULTS.chunkOverlapChars,
    maxSeconds = RETRIEVAL_DEFAULTS.chunkMaxSeconds,
    startOrdinal = 0,
    kind = "transcript",
  } = {}
) {
  const chunks = [];
  let buffer = [];
  let bufferLen = 0;
  let ordinal = startOrdinal;

  const emit = () => {
    const text = clean(buffer.map((s) => s.text).join(" "));
    if (normalize(text).length >= 8) {
      chunks.push(
        makeChunk(itemId, ordinal, text, {
          start: buffer[0].start,
          end: buffer[buffer.length - 1].end || buffer[buffer.length - 1].start,
          kind,
        })
      );
      ordinal += 1;
      return true;
    }
    return false;
  };

  const flush = () => {
    if (!buffer.length) return;
    emit();
    // Carry the tail of this chunk into the next one so a sentence split across
    // a boundary is still retrievable from both sides.
    const carry = [];
    let carried = 0;
    for (let i = buffer.length - 1; i >= 0; i -= 1) {
      if (carried >= overlapChars) break;
      carry.unshift(buffer[i]);
      carried += buffer[i].text.length;
    }
    buffer = carry.length < buffer.length ? carry : [];
    bufferLen = buffer.reduce((n, s) => n + s.text.length, 0);
  };

  for (const segment of segments) {
    const text = clean(segment.text);
    if (!text) continue;
    const seg = { text, start: segment.start || 0, end: segment.end || 0 };
    const span = (seg.end || seg.start) - (buffer.length ? buffer[0].start : seg.start);
    if (buffer.length && (bufferLen + text.length > maxChars || span > maxSeconds)) {
      flush();
    }
    buffer.push(seg);
    bufferLen += text.length;
  }

  // The final flush must not re-carry, or we would loop forever.
  if (buffer.length) emit();
  return chunks;
}

/** Chunk untimed prose (a video description, an article body). */
export function chunkText(
  itemId,
  text,
  { kind = "description", maxChars = RETRIEVAL_DEFAULTS.chunkChars, startOrdinal = 0 } = {}
) {
  text = clean(text);
  if (!text) return [];
  const chunks = [];
  let buffer = "";
  let ordinal = startOrdinal;
  const parts = sentences(text);
  for (const sentence of parts.length ? parts : [text]) {
    if (buffer && buffer.length + sentence.length > maxChars) {
      chunks.push(makeChunk(itemId, ordinal, buffer.trim(), { kind }));
      ordinal += 1;
      buffer = "";
    }
    buffer = `${buffer} ${sentence}`.trim();
  }
  if (buffer) chunks.push(makeChunk(itemId, ordinal, buffer.trim(), { kind }));
  return chunks;
}

/** One chunk per comment thread, most-liked first. */
export function chunkComments(itemId, comments, { maxChars = 600, startOrdinal = 0 } = {}) {
  const chunks = [];
  let ordinal = startOrdinal;
  for (const comment of comments) {
    const passage = [comment.text, ...(comment.replies || []).map((r) => `↳ ${r}`)]
      .map((p) => String(p || "").trim())
      .filter(Boolean)
      .join("\n");
    const text = clean(passage.replace(/\n/g, " ")).slice(0, maxChars);
    if (normalize(text).length < 8) continue;
    chunks.push(makeChunk(itemId, ordinal, text, { kind: "comment" }));
    ordinal += 1;
  }
  return chunks;
}

/**
 * Build the full chunk set for one saved item.
 *
 * Chunk 0 is always a *header* built from title + author + tags. It is what
 * matches when a video has no subtitles at all, and it keeps short, punchy
 * titles competitive against long transcript passages.
 */
export function chunkItem(item, segments = null, config = null, comments = null) {
  const cfg = { ...RETRIEVAL_DEFAULTS, ...(config || {}) };
  const headerParts = [item.title];
  if (item.author) headerParts.push(item.author);
  if (item.tags && item.tags.length) headerParts.push(item.tags.join(" "));
  if (item.folder) headerParts.push(item.folder);
  const header = headerParts.filter(Boolean).join(" · ");

  const chunks = [makeChunk(item.id, 0, header, { kind: "title" })];
  let ordinal = 1;

  const isPost = item.mediaKind === MEDIA_POST;
  const bodyKind = isPost ? "body" : "transcript";

  // A post's description and its body are usually the same text arriving twice
  // (the capture sends an excerpt as the description). Indexing both would
  // double every passage and let one item dominate its own results.
  let description = clean(item.description);
  if (isPost && segments && segments.length) description = "";
  if (description) {
    const descChunks = chunkText(item.id, description.slice(0, 4000), {
      kind: "description",
      maxChars: cfg.chunkChars,
      startOrdinal: ordinal,
    });
    chunks.push(...descChunks);
    ordinal += descChunks.length;
  }

  if (segments && segments.length) {
    const bodyChunks = chunkSegments(item.id, segments, {
      maxChars: cfg.chunkChars,
      overlapChars: cfg.chunkOverlapChars,
      maxSeconds: cfg.chunkMaxSeconds,
      startOrdinal: ordinal,
      kind: bodyKind,
    });
    chunks.push(...bodyChunks);
    ordinal += bodyChunks.length;
  }

  if (comments && comments.length) {
    chunks.push(...chunkComments(item.id, comments, { startOrdinal: ordinal }));
  }

  // Guard against duplicate ids when the same text repeats verbatim (very
  // common in auto-generated subtitles).
  const seen = new Set();
  return chunks.filter((chunk) => {
    if (seen.has(chunk.id)) return false;
    seen.add(chunk.id);
    return true;
  });
}
