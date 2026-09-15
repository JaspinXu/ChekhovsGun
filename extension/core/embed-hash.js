/**
 * The zero-download embedding backend — a port of `HashingEmbedder` from
 * `chekhovsgun/rag/embeddings.py`.
 *
 * This is what makes the extension useful the second it is installed, before
 * the neural encoder has been fetched. It is deliberately weak on semantics,
 * which is exactly why retrieval fuses it with BM25 (see `retrieve.js`) — the
 * two fail in different places.
 *
 * *Why the hash differs from Python's.* The original uses blake2b, which the
 * web platform does not provide and which is not worth 200 lines to reproduce:
 * vectors never cross the Python/JavaScript boundary (the two engines federate
 * at the *result* level, not the vector level), so the only requirement is that
 * the hash be well-distributed and stable within this engine. We use FNV-1a
 * with a murmur3 finalizer, and the signature says `local-hash-js` so a vector
 * from one side can never be mistaken for a vector from the other.
 */

import { tokenize } from "./text.js";

const DIMENSIONS = 512;

/** FNV-1a over UTF-8 code units, then murmur3's finalizer for avalanche. */
function hash32(token) {
  let h = 0x811c9dc5;
  for (let i = 0; i < token.length; i += 1) {
    h ^= token.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  // Without this the low bits (which choose the bucket) barely move between
  // tokens that share a prefix, and every CJK bigram starting with the same
  // character would collide into a handful of buckets.
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

export class HashingEmbedder {
  constructor(dimensions = DIMENSIONS) {
    this.dimensions = Math.max(64, dimensions | 0);
    this.name = "local-hash-js";
    this._cache = new Map();
  }

  get signature() {
    return `${this.name}:${this.dimensions}`;
  }

  _indexAndSign(token) {
    let entry = this._cache.get(token);
    if (entry === undefined) {
      const h = hash32(token);
      // Bucket comes from the low bits, sign from the top bit; after the
      // finalizer above these are effectively independent.
      entry = [h % this.dimensions, h >>> 31 ? 1 : -1];
      // Bounded so a long indexing run cannot grow this without limit.
      if (this._cache.size > 20000) this._cache.clear();
      this._cache.set(token, entry);
    }
    return entry;
  }

  embedOne(text) {
    const vector = new Float32Array(this.dimensions);
    const counts = new Map();
    for (const token of tokenize(text)) {
      counts.set(token, (counts.get(token) || 0) + 1);
    }
    for (const [token, count] of counts) {
      const [index, sign] = this._indexAndSign(token);
      // Longer tokens (CJK bigrams, real words) are more specific than single
      // characters, so let them carry more weight. Sublinear term frequency
      // keeps a repeated filler word from swamping the vector.
      const specificity = 1.0 + 0.35 * Math.min(token.length, 4);
      vector[index] += sign * (1.0 + Math.log(count)) * specificity;
    }
    return l2Normalize(vector);
  }

  async embed(texts) {
    return texts.map((t) => this.embedOne(t));
  }
}

export function l2Normalize(vector) {
  let sum = 0;
  for (let i = 0; i < vector.length; i += 1) sum += vector[i] * vector[i];
  const norm = Math.max(Math.sqrt(sum), 1e-9);
  for (let i = 0; i < vector.length; i += 1) vector[i] /= norm;
  return vector;
}

export function dot(a, b) {
  let sum = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) sum += a[i] * b[i];
  return sum;
}
