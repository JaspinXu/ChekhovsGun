/**
 * Hybrid retrieval: dense vectors + BM25, fused, diversified, aggregated.
 * Port of `chekhovsgun/rag/retriever.py`.
 *
 * *Why hybrid.* The zero-download embedder is a hashed bag of n-grams; it
 * captures topical drift but misses exact terminology ("KV cache", "BV1xx4y1…").
 * BM25 is the mirror image. Fusing them recovers most of what a real encoder
 * would give you, and keeps working when you *do* plug one in.
 *
 * *Why RRF and not a weighted score sum.* Cosine similarity and BM25 live on
 * incomparable scales, and BM25's range shifts with corpus size. Reciprocal
 * Rank Fusion only looks at ranks, so it needs no calibration and cannot be
 * destabilised by one outlier score.
 *
 * *Why a per-item cap instead of MMR.* A 40-minute lecture produces dozens of
 * near-identical chunks. Results are aggregated up to the *item*, so multiple
 * passages from one save are corroborating evidence, not redundancy — and MMR
 * actively deletes them, including the single best-matching passage, because it
 * sits closest to an already-selected sibling. Capping how many chunks each
 * item may contribute spreads results across saves while keeping each save's
 * strongest evidence intact.
 */

import { RETRIEVAL_DEFAULTS } from "./config.js";
import { STATUS_ACTIVE } from "./ids.js";
import { scriptOf, tokenize } from "./text.js";

// Chunk kinds carry different amounts of signal: a title match is a strong
// topical hint, a description match is weaker (descriptions are full of
// boilerplate). Kept deliberately mild — rank-fusion scores are tightly packed,
// so a larger spread would let a weak title match outrank a passage that was
// the top result of *both* retrievers.
const KIND_WEIGHT = {
  title: 1.06,
  transcript: 1.0,
  body: 1.0,
  comment: 0.95,
  description: 0.92,
};

function rrf(rankedIds, k) {
  const out = new Map();
  rankedIds.forEach((cid, rank) => out.set(cid, 1.0 / (k + rank + 1)));
  return out;
}

function partitionByScript(weights) {
  const buckets = { cjk: new Map(), latin: new Map(), mixed: new Map(weights) };
  for (const [token, weight] of weights) {
    const bucket = /[⺀-￿]/.test(token) ? "cjk" : "latin";
    buckets[bucket].set(token, weight);
  }
  return buckets;
}

/**
 * IDF-weighted recall of the query's vocabulary inside this passage.
 *
 * Two corrections make this number mean what it should. *Unknown words are
 * ignored*: `buckets` already excludes tokens the library has never seen, so
 * "how I made my React app faster" is judged on `react` alone rather than being
 * diluted by four words no saved item could contain. *Scripts are scored
 * separately*: a Chinese query term cannot appear in an English transcript no
 * matter how relevant that transcript is, so an English passage is scored only
 * against the query's latin terms. Without this, every cross-language match
 * looks irrelevant — and a library of Chinese and English saves is exactly the
 * case this project is built for.
 */
export function coverage(buckets, text, chunkTokens) {
  let weights = buckets[scriptOf(text)];
  if (!weights || !weights.size) weights = buckets.mixed;
  if (!weights.size) return 0.0;

  let total = 0;
  for (const w of weights.values()) total += w;
  if (total <= 0) return 0.0;

  let matchedWeight = 0;
  let matchedCount = 0;
  for (const [token, weight] of weights) {
    if (chunkTokens.has(token)) {
      matchedWeight += weight;
      matchedCount += 1;
    }
  }
  if (!matchedCount) return 0.0;

  const ratio = Math.min(1.0, matchedWeight / total);
  // A ratio computed from a single shared word is not evidence, however rare
  // that word looks in a small library — "红烧肉的做法" and a Redis talk both
  // contain 做法, and both would otherwise score a perfect 1.0. Saturating on
  // the *number* of distinct matched terms caps a lone match well below a
  // genuine multi-term overlap, and approaches 1.0 as the overlap grows.
  const saturation = matchedCount / (matchedCount + 0.8);
  return ratio * saturation;
}

/**
 * Blend semantic similarity with literal term coverage into one 0..1 gate.
 *
 * Either signal alone is exploitable: cosine similarity from a hashed embedder
 * reads high for any two texts in the same register, and term coverage reads
 * high when a long passage happens to contain the query's words scattered
 * across unrelated sentences. Requiring both to be non-trivial is what stops
 * "a monad is a design pattern" from surfacing under a query about chunking.
 */
export function confidenceOf(dense, cov) {
  dense = Math.max(0, Math.min(1, dense));
  cov = Math.max(0, Math.min(1, cov));
  const arithmetic = 0.45 * dense + 0.55 * cov;
  const geometric = Math.sqrt(dense * cov); // zero unless *both* signals fire
  return 0.55 * arithmetic + 0.45 * geometric;
}

/**
 * Penalty applied when only lexical evidence exists. Chosen so that a passage
 * still has to reach ~0.35 coverage to clear the 0.30 confidence floor — a
 * genuine multi-term overlap, not one shared word.
 */
const LEXICAL_ONLY_FACTOR = 0.85;

/**
 * Confidence for a chunk whose vector cannot be compared to the query.
 *
 * This is not the same situation as "the encoder looked and saw nothing".
 * `confidenceOf` deliberately multiplies in a geometric term that is zero
 * unless *both* signals fire, so feeding it `dense = 0` for a chunk that simply
 * has no comparable vector would gate that chunk out permanently, no matter how
 * well its text matches. That state is reachable in normal use — it is exactly
 * what every chunk looks like between the moment the neural encoder becomes
 * available and the moment the background re-embed reaches that chunk — so the
 * missing signal is treated as unknown rather than as evidence of irrelevance,
 * and the surviving signal is discounted instead of annihilated.
 */
export function confidenceLexicalOnly(cov) {
  return Math.max(0, Math.min(1, cov)) * LEXICAL_ONLY_FACTOR;
}

export class Retriever {
  /**
   * @param {import("./index-memory.js").MemoryIndex} index
   * @param {{embedOne(text: string): Float32Array}} embedder
   */
  constructor(index, embedder, config = null) {
    this.index = index;
    this.embedder = embedder;
    this.config = { ...RETRIEVAL_DEFAULTS, ...(config || {}) };
  }

  searchChunks(query, { limit = null, excludeItems = null, sources = null } = {}) {
    const cfg = this.config;
    limit = limit || cfg.topKChunks;
    query = (query || "").trim();
    if (!query) return [];

    const pool = Math.max(limit * 4, 64);
    const dense = this.index.denseSearch(this.embedder.embedOne(query), pool);
    const lexical = this.index.lexicalSearch(query, pool);
    if (!dense.length && !lexical.length) return [];

    const denseScores = new Map(dense);
    const lexicalScores = new Map(lexical);
    const fusedDense = rrf(dense.map(([cid]) => cid), cfg.rrfK);
    const fusedLexical = rrf(lexical.map(([cid]) => cid), cfg.rrfK);

    const fused = new Map();
    for (const [cid, score] of fusedDense) {
      fused.set(cid, (fused.get(cid) || 0) + cfg.denseWeight * score);
    }
    for (const [cid, score] of fusedLexical) {
      fused.set(cid, (fused.get(cid) || 0) + cfg.lexicalWeight * score);
    }

    const candidateIds = [...fused.keys()]
      .sort((a, b) => fused.get(b) - fused.get(a))
      .slice(0, pool);

    // Apply filters and per-kind weighting before diversification, so the cap
    // ranks only things the caller can actually use.
    const relevance = new Map();
    const filtered = [];
    for (const cid of candidateIds) {
      const chunk = this.index.chunks.get(cid);
      if (!chunk) continue;
      const item = this.index.items.get(chunk.itemId);
      if (!item) continue;
      if (excludeItems && excludeItems.has(item.id)) continue;
      if (sources && !sources.has(item.source)) continue;
      filtered.push(cid);
      relevance.set(cid, fused.get(cid) * (KIND_WEIGHT[chunk.kind] ?? 1.0));
    }
    if (!filtered.length) return [];

    // Spread the budget across saves: one long lecture must not consume the
    // whole candidate list, but each save keeps its strongest passages.
    const perItem = new Map();
    const selected = [];
    for (const cid of filtered.sort((a, b) => relevance.get(b) - relevance.get(a))) {
      const itemId = this.index.chunks.get(cid).itemId;
      const used = perItem.get(itemId) || 0;
      if (used >= cfg.maxChunksPerItem) continue;
      perItem.set(itemId, used + 1);
      selected.push(cid);
      if (selected.length >= limit) break;
    }

    return selected
      .map((cid) => {
        const chunk = this.index.chunks.get(cid);
        return {
          chunk,
          item: this.index.items.get(chunk.itemId),
          score: relevance.get(cid),
          denseScore: denseScores.get(cid) || 0,
          lexicalScore: lexicalScores.get(cid) || 0,
        };
      })
      .sort((a, b) => b.score - a.score);
  }

  /** Aggregate chunk hits up to the item the user actually saved. */
  searchItems(
    query,
    { limit = null, excludeItems = null, sources = null, minScore = null } = {}
  ) {
    const cfg = this.config;
    limit = limit || cfg.topKItems;
    const hits = this.searchChunks(query, {
      limit: Math.max(cfg.topKChunks, limit * 6),
      excludeItems,
      sources,
    });
    if (!hits.length) return [];

    const grouped = new Map();
    for (const hit of hits) {
      if (!grouped.has(hit.item.id)) grouped.set(hit.item.id, []);
      grouped.get(hit.item.id).push(hit);
    }
    for (const group of grouped.values()) group.sort((a, b) => b.score - a.score);

    const queryBuckets = partitionByScript(
      this.index.idfWeights(tokenize(query).filter((t) => t.length >= 2))
    );

    const results = [];
    for (const group of grouped.values()) {
      const best = group[0].score;
      // Extra matching passages are corroborating evidence, but with sharply
      // diminishing returns — one strong match beats five weak ones.
      const support = group.slice(1, 4).reduce((n, h) => n + h.score, 0) * 0.25;
      const confidence = Math.max(
        ...group.slice(0, 4).map((h) => {
          const cov = coverage(queryBuckets, h.chunk.text, this.index.tokensOf(h.chunk.id));
          return this.index.hasVector(h.chunk.id)
            ? confidenceOf(h.denseScore, cov)
            : confidenceLexicalOnly(cov);
        })
      );
      results.push({
        item: group[0].item,
        score: best + support,
        chunks: group.slice(0, 3).map((h) => h.chunk),
        timestamps: group
          .slice(0, 3)
          .filter((h) => h.chunk.kind === "transcript")
          .map((h) => h.chunk.start),
        confidence,
      });
    }

    // Final ordering is driven by confidence, with the fusion score as a
    // tie-breaker rather than the primary signal. Rank fusion over-rewards a
    // long passage that merely shares common bigrams with the query;
    // confidence is the calibrated "is this the same subject" number, and
    // measuring both on the golden set put the right answer first in every case
    // only once confidence carried ~80% of the weight.
    results.sort(
      (a, b) => b.score * (0.2 + 0.8 * b.confidence) - a.score * (0.2 + 0.8 * a.confidence)
    );

    // Two cuts, doing two different jobs. `confidence` is absolute and
    // corpus-independent: it answers "is this the same subject at all?".
    // `minScoreRatio` is relative: once a query has one excellent match, it
    // suppresses the long tail that merely ranked next.
    const floor = minScore === null ? cfg.minConfidence : minScore;
    const top = results[0].score || 1.0;
    const kept = results
      .filter((r) => r.confidence >= floor && r.score / top >= cfg.minScoreRatio)
      .slice(0, limit);
    for (const result of kept) result.score = Number((result.score / top).toFixed(5));
    return kept;
  }

  /** The core "your bookmark is about to fire" query. */
  relate(context, { limit = null, excludeItems = null } = {}) {
    const cfg = this.config;
    const exclude = new Set(excludeItems || []);
    if (cfg.excludeSameVideo && context.source && context.sourceId) {
      exclude.add(`${context.source}:${context.sourceId}`);
    }
    if (cfg.excludeDigested) {
      // Items marked 学完了 stop firing. They stay fully searchable — the point
      // is to stop being interrupted about them, not to hide them.
      for (const item of this.index.items.values()) {
        if (item.status && item.status !== STATUS_ACTIVE) exclude.add(item.id);
      }
    }
    return this.searchItems(contextAsQuery(context), { limit, excludeItems: exclude });
  }
}

/** Mirrors `Context.as_query` in `chekhovsgun/models.py`. */
export function contextAsQuery(context) {
  return [
    context.title,
    context.author,
    (context.tags || []).join(" "),
    (context.description || "").slice(0, 600),
  ]
    .filter(Boolean)
    .join("\n")
    .trim();
}
