/**
 * The in-browser engine: storage + core, behind the same shape as the remote
 * one so `background.js` can call either without caring which it has.
 *
 * Everything durable lives in IndexedDB. The MV3 service worker that hosts this
 * is killed after ~30s idle and restarted on the next message, so this class
 * holds nothing it cannot rebuild — the in-memory index is a cache keyed on the
 * store's revision counter, exactly as the Python `Store` caches its BM25
 * postings and vector matrix.
 */

import { RETRIEVAL_DEFAULTS } from "../core/config.js";
import { chunkItem } from "../core/chunker.js";
import { MemoryIndex } from "../core/index-memory.js";
import { Retriever, contextAsQuery } from "../core/retrieve.js";
import { tokenize } from "../core/text.js";
import { makeItemId, STATUS_ACTIVE, STATUS_DIGESTED } from "../core/ids.js";
import { identifyUrl } from "../core/sites.js";

export class LocalEngine {
  /**
   * @param {import("../platform/idb.js").IdbStore} store
   * @param {{embed(texts: string[]): Promise<Float32Array[]>, embedOne(text: string): Promise<Float32Array>|Float32Array, signature: string}} embedder
   */
  constructor(store, embedder, config = null) {
    this.store = store;
    this.embedder = embedder;
    this.config = { ...RETRIEVAL_DEFAULTS, ...(config || {}) };
    this._index = null;
    this._indexRevision = -1;
    this._indexSignature = "";
  }

  /** Swap the embedder (hash → neural) without discarding the library. */
  setEmbedder(embedder) {
    this.embedder = embedder;
    this._index = null; // the vector matrix is now for the wrong space
  }

  async index(signature = this.embedder.signature) {
    if (
      this._index &&
      this._indexRevision === this.store.revision &&
      this._indexSignature === signature
    ) {
      return this._index;
    }
    const revision = this.store.revision;
    const [items, chunks] = await Promise.all([
      this.store.allItems(),
      this.store.allChunks(),
    ]);
    this._index = new MemoryIndex(items, chunks, signature);
    // A write during the read must force the next query to refresh this view.
    this._indexRevision = revision;
    this._indexSignature = signature;
    return this._index;
  }

  /**
   * Retrieval takes a pre-computed query vector rather than an embedder,
   * because the neural backend is asynchronous (it lives in the offscreen
   * document) while `Retriever` is synchronous throughout. The query is one
   * string, so embedding it once up front costs nothing and keeps the whole
   * ranking path free of promises.
   */
  async _retrieverFor(query) {
    const { vectors: [vector], signature } = await this._embed([query], true);
    // Embedding can demote the model. Build the view for the resulting space,
    // so this very query receives lexical fallback for the model's old rows.
    const index = await this.index(signature);
    return new Retriever(index, { embedOne: () => vector }, this.config);
  }

  async _embed(texts, query = false) {
    const encoder = this.embedder;
    if (encoder.embedWithSignature) return encoder.embedWithSignature(texts, { query });
    const signature = encoder.signature;
    const vectors = query ? [await encoder.embedOne(texts[0])] : await encoder.embed(texts);
    return { vectors, signature };
  }

  async search(query, { limit = null } = {}) {
    if (!(query || "").trim()) return [];
    const retriever = await this._retrieverFor(query);
    return retriever.searchItems(query, { limit });
  }

  /**
   * The unprompted "you already saved this" query.
   *
   * Returns `[]` rather than throwing when the library is too small: confidence
   * leans on IDF, and IDF means nothing over a handful of documents — in a
   * three-item library every word looks rare, so an unrelated page matches on
   * one shared common word. Explicit search is never gated this way.
   */
  async relate(context, { limit = null } = {}) {
    const index = await this.index();
    if (index.itemCount < this.config.minLibraryItems) {
      return { hits: [], gated: true, itemCount: index.itemCount };
    }
    const query = contextAsQuery(context);
    if (!query.trim()) return { hits: [], gated: false, itemCount: index.itemCount };
    const retriever = await this._retrieverFor(query);
    return {
      hits: retriever.relate(context, { limit }),
      gated: false,
      itemCount: index.itemCount,
    };
  }

  // ----------------------------------------------------------------- ingest

  /**
   * Take a captured page or video into the library.
   *
   * @param {object} capture `{source, sourceId, title, url, ...}` plus either
   *   `segments` (timed or untimed passages) or `body` text.
   */
  async capture(capture) {
    const item = await normalizeCapture(capture);
    const segments = segmentsOf(capture);
    const chunks = chunkItem(item, segments, this.config, capture.comments || []);

    const { vectors, signature } = await this._embed(chunks.map((c) => c.text));
    const rows = chunks.map((chunk, i) => ({
      ...chunk,
      // Computed once here because tokenising the candidate set on every query
      // was the single largest cost in the Python hot path.
      tokens: tokenize(chunk.text),
      vector: vectors[i],
      embedder: signature,
    }));

    const stored = await this.store.replaceItem(
      { ...item, hasTranscript: segments.length > 0 },
      rows
    );
    await this.store.logEvent("capture", { itemId: item.id, source: item.source });
    return { item: stored, chunks: rows.length };
  }

  async mark(itemId, status = STATUS_DIGESTED) {
    const item = await this.store.setStatus(itemId, status);
    if (item) await this.store.logEvent(status, { itemId });
    return item;
  }

  async unmark(itemId) {
    return this.mark(itemId, STATUS_ACTIVE);
  }

  async remove(itemId) {
    await this.store.deleteItem(itemId);
  }

  async has(url) {
    const identity = await identifyUrl(url);
    return Boolean(await this.store.getItem(makeItemId(identity.source, identity.sourceId)));
  }

  async stats() {
    const [stats, index] = await Promise.all([this.store.stats(), this.index()]);
    return {
      ...stats,
      embedder: this.embedder.signature,
      vectorCoverage: index.vectorCoverage,
      minLibraryItems: this.config.minLibraryItems,
      ready: index.itemCount >= this.config.minLibraryItems,
    };
  }

  /**
   * Re-embed one batch of chunks left behind by an embedder change.
   *
   * Deliberately incremental: the caller loops until this reports zero so the
   * work is spread across service-worker wake-ups rather than held in one long
   * task that the browser may kill halfway through.
   */
  async reembedBatch(size = 64) {
    const stale = await this.store.chunksNeedingEmbedding(this.embedder.signature, size);
    if (!stale.length) return 0;
    const { vectors, signature } = await this._embed(stale.map((c) => c.text));
    await this.store.putVectors(
      stale.map((chunk, i) => ({ id: chunk.id, vector: vectors[i] })),
      signature
    );
    return stale.length;
  }
}

async function normalizeCapture(capture) {
  let url;
  try {
    url = new URL(capture.url);
  } catch {
    throw new Error("capture needs a valid HTTP(S) URL");
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("capture needs a valid HTTP(S) URL");
  }
  // The content script reads the page; it does not decide what the page *is*.
  // Identity comes from the URL through the same rules the Python side uses, so
  // a page captured here and the same page synced by an adapter collide on one
  // id instead of appearing twice.
  const identity = await identifyUrl(capture.url || "");
  const source = capture.source || identity.source || "web";
  const sourceId = capture.sourceId || capture.source_id || identity.sourceId || capture.url || "";
  const mediaKind = capture.mediaKind || capture.media_kind || identity.mediaKind || "post";

  return {
    id: capture.id || makeItemId(source, sourceId),
    source,
    sourceId,
    title: capture.title || "",
    url: url.href,
    author: capture.author || "",
    // A video's `excerpt` is its description; a post's is a preview of a body
    // we are also indexing, and the chunker drops it in that case so one item
    // cannot dominate its own results.
    description: capture.description || capture.excerpt || "",
    thumbnail: capture.thumbnail || "",
    duration: capture.duration || 0,
    publishedAt: capture.publishedAt || capture.published_at || 0,
    savedAt: capture.savedAt || capture.saved_at || Date.now() / 1000,
    folder: capture.folder || "",
    lang: capture.lang || "",
    tags: capture.tags || [],
    mediaKind,
    status: STATUS_ACTIVE,
  };
}

/**
 * Accept either timed segments (a subtitle track) or a plain body string.
 * A post's paragraphs arrive as untimed segments so the chunker can keep them
 * addressable without pretending they have timestamps.
 */
function segmentsOf(capture) {
  if (Array.isArray(capture.segments) && capture.segments.length) {
    return capture.segments.map((s) =>
      typeof s === "string"
        ? { text: s, start: 0, end: 0 }
        : { text: s.text || "", start: s.start || 0, end: s.end || 0 }
    );
  }
  // `text` is what the page recipes produce; `body` is what a direct API caller
  // would send. Both mean the same thing.
  const body = String(capture.body || capture.text || "").trim();
  if (!body) return [];
  return body
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((text) => ({ text, start: 0, end: 0 }));
}
