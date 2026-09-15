/**
 * The in-memory searchable view of the library — the JavaScript counterpart of
 * the caches `chekhovsgun.rag.store.Store` builds in `_ensure_caches`.
 *
 * Storage (IndexedDB, or SQLite on Android) hands over plain rows; everything
 * queries need — the BM25 postings, the vector matrix, the per-chunk token sets
 * — is derived here. Tokens are computed once at write time and carried on the
 * row, because tokenising the candidate set on every query was the single
 * largest cost in the Python hot path and would be worse here.
 */

import { Bm25Index } from "./bm25.js";
import { dot } from "./embed-hash.js";
import { tokenize } from "./text.js";

export class MemoryIndex {
  /**
   * @param {object[]} items
   * @param {object[]} chunks rows carrying `tokens`, and `vector`/`embedder`
   * @param {string} embedderSignature only vectors from this embedder are
   *   comparable; chunks embedded by a different one still participate in BM25,
   *   so nothing in the library becomes invisible during a re-embed.
   */
  constructor(items, chunks, embedderSignature = "") {
    this.items = new Map(items.map((item) => [item.id, item]));
    this.chunks = new Map(chunks.map((chunk) => [chunk.id, chunk]));
    this.embedderSignature = embedderSignature;

    this.chunkIds = chunks.map((c) => c.id);
    this.tokenSets = new Map();
    const tokenLists = chunks.map((chunk) => {
      const tokens = chunk.tokens && chunk.tokens.length ? chunk.tokens : tokenize(chunk.text);
      this.tokenSets.set(chunk.id, new Set(tokens));
      return tokens;
    });
    this.bm25 = new Bm25Index(this.chunkIds, tokenLists);

    // Only same-space vectors go into the dense matrix. A chunk embedded by a
    // different backend is not dropped from the library — it still answers
    // through BM25 — it just cannot be compared against this query vector.
    this.vectorIds = [];
    this.vectors = [];
    for (const chunk of chunks) {
      if (!chunk.vector || !chunk.vector.length) continue;
      if (embedderSignature && chunk.embedder !== embedderSignature) continue;
      this.vectorIds.push(chunk.id);
      this.vectors.push(chunk.vector);
    }
    this._vectorIdSet = new Set(this.vectorIds);
  }

  get itemCount() {
    return this.items.size;
  }

  /** How much of the library the active embedder can actually see. */
  get vectorCoverage() {
    return this.chunkIds.length ? this.vectorIds.length / this.chunkIds.length : 0;
  }

  denseSearch(queryVector, limit) {
    if (!this.vectors.length || !queryVector) return [];
    if (queryVector.length !== this.vectors[0].length) return [];
    const scored = [];
    for (let i = 0; i < this.vectors.length; i += 1) {
      scored.push([this.vectorIds[i], dot(this.vectors[i], queryVector)]);
    }
    scored.sort((a, b) => b[1] - a[1]);
    return scored.slice(0, Math.min(limit, scored.length));
  }

  lexicalSearch(query, limit) {
    const tokens = tokenize(query);
    if (!tokens.length) return [];
    return this.bm25
      .search(tokens, limit)
      .map(([index, score]) => [this.chunkIds[index], score]);
  }

  idfWeights(tokens) {
    return this.bm25.idfWeights(tokens);
  }

  /**
   * Whether this chunk's vector is comparable to a query from the active
   * embedder. Retrieval needs the distinction between "the encoder compared
   * this and scored it low" and "there was nothing to compare" — see
   * `confidenceLexicalOnly` in `retrieve.js`.
   */
  hasVector(chunkId) {
    return this._vectorIdSet.has(chunkId);
  }

  tokensOf(chunkId) {
    return this.tokenSets.get(chunkId) || new Set();
  }
}
