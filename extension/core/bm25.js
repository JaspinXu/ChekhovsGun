/**
 * BM25 over an in-memory inverted index — a port of `_LexicalIndex` from
 * `chekhovsgun/rag/store.py`.
 *
 * Built once per index revision and kept in memory: rebuilding costs a pass
 * over the chunk list, and queries then cost only the postings of the tokens
 * actually present.
 */

// A token in most of the library discriminates nothing and costs a full
// postings scan, so it is skipped outright.
const MAX_DF_RATIO = 0.55;
const K1 = 1.4;
const B = 0.72;

export class Bm25Index {
  /**
   * @param {string[]} chunkIds
   * @param {string[][]} tokenLists token list per chunk, same order
   */
  constructor(chunkIds, tokenLists) {
    this.chunkIds = chunkIds;
    this.total = chunkIds.length;
    this.docLen = new Float32Array(this.total);
    /** @type {Map<string, {indices: Int32Array, freqs: Float32Array}>} */
    this.postings = new Map();

    const raw = new Map();
    let lenSum = 0;
    for (let index = 0; index < tokenLists.length; index += 1) {
      const tokens = tokenLists[index] || [];
      this.docLen[index] = tokens.length;
      lenSum += tokens.length;
      const counts = new Map();
      for (const token of tokens) counts.set(token, (counts.get(token) || 0) + 1);
      for (const [token, count] of counts) {
        let entries = raw.get(token);
        if (!entries) raw.set(token, (entries = []));
        entries.push(index, count);
      }
    }
    for (const [token, flat] of raw) {
      const n = flat.length / 2;
      const indices = new Int32Array(n);
      const freqs = new Float32Array(n);
      for (let i = 0; i < n; i += 1) {
        indices[i] = flat[i * 2];
        freqs[i] = flat[i * 2 + 1];
      }
      this.postings.set(token, { indices, freqs });
    }

    this.avgLen = this.total ? lenSum / this.total : 1.0;
    this.maxDf = Math.max(8, Math.floor(this.total * MAX_DF_RATIO));
  }

  docFreq(token) {
    const posting = this.postings.get(token);
    return posting ? posting.indices.length : 0;
  }

  /**
   * @returns {Array<[number, number]>} [chunkIndex, score], best first
   */
  search(tokens, limit, k1 = K1, b = B) {
    if (!this.total) return [];
    const scores = new Float32Array(this.total);
    const avg = this.avgLen || 1.0;
    let touched = false;
    for (const token of new Set(tokens)) {
      const posting = this.postings.get(token);
      if (!posting) continue;
      const { indices, freqs } = posting;
      const df = indices.length;
      if (df > this.maxDf) continue;
      const idf = Math.log(1.0 + (this.total - df + 0.5) / (df + 0.5));
      for (let i = 0; i < df; i += 1) {
        const doc = indices[i];
        const tf = freqs[i];
        const norm =
          (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + (b * this.docLen[doc]) / avg));
        scores[doc] += idf * norm;
      }
      touched = true;
    }
    if (!touched) return [];

    const ranked = [];
    for (let i = 0; i < this.total; i += 1) {
      if (scores[i] > 0) ranked.push([i, scores[i]]);
    }
    ranked.sort((a, b2) => b2[1] - a[1]);
    return ranked.slice(0, Math.min(limit, ranked.length));
  }

  /**
   * `token -> idf`, omitting tokens the library has never seen.
   *
   * A query word that appears nowhere cannot discriminate between saved items,
   * so it must not count towards — or against — a coverage score. Dropping it
   * is what lets "how I made my React app faster" be judged on `react` alone.
   */
  idfWeights(tokens) {
    const weights = new Map();
    if (!this.total) return weights;
    for (const token of new Set(tokens)) {
      const freq = this.docFreq(token);
      if (freq) weights.set(token, Math.log(1.0 + this.total / freq));
    }
    return weights;
  }
}
