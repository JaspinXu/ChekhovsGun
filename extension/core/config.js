/**
 * Retrieval constants, kept in step with `RetrievalConfig` in
 * `chekhovsgun/config.py`.
 *
 * These were tuned against a golden set; the comments explaining *why* each
 * value is what it is live in the Python file. Do not drift them casually — the
 * local and remote engines are compared against each other at the result level,
 * and divergent cutoffs make that comparison meaningless.
 */
export const RETRIEVAL_DEFAULTS = Object.freeze({
  chunkChars: 420,
  chunkOverlapChars: 80,
  chunkMaxSeconds: 90.0,
  topKChunks: 40,
  topKItems: 5,
  denseWeight: 0.6,
  lexicalWeight: 0.4,
  rrfK: 60,
  /** Minimum confidence for a result to be returned at all. */
  minConfidence: 0.3,
  /** Secondary, relative cut against the best hit of this query. */
  minScoreRatio: 0.45,
  /** How many passages one saved item may contribute to the candidate list. */
  maxChunksPerItem: 4,
  excludeDigested: true,
  excludeSameVideo: true,
  /**
   * The card stays silent until the library holds at least this many items.
   * Confidence leans on IDF, and IDF means nothing over a handful of documents:
   * in a three-item library every word looks rare. Explicit search is never
   * gated by this — only the unprompted popup is.
   */
  minLibraryItems: 15,
});

export function withDefaults(overrides) {
  return { ...RETRIEVAL_DEFAULTS, ...(overrides || {}) };
}
