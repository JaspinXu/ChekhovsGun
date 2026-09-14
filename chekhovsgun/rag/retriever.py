"""Hybrid retrieval: dense vectors + BM25, fused, diversified, aggregated.

Design notes
------------
*Why hybrid.* The zero-config embedder is a hashed bag of n-grams; it captures
topical drift but misses exact terminology ("KV cache", "BV1xx4y1..."). BM25 is
the mirror image. Fusing them recovers most of what a real encoder would give
you, and keeps working when you *do* plug in a real encoder.

*Why RRF and not a weighted score sum.* Cosine similarity and BM25 live on
incomparable scales, and BM25's range shifts with corpus size. Reciprocal Rank
Fusion only looks at ranks, so it needs no calibration and cannot be destabilised
by one outlier score.

*Why a per-item cap instead of MMR.* A 40-minute lecture produces dozens of
near-identical chunks, and without a diversity step the candidate list is five
slices of one video. Maximal Marginal Relevance is the textbook answer, but it
is the wrong tool here: results are aggregated up to the *item*, so multiple
passages from one save are corroborating evidence, not redundancy — and MMR
actively deletes them, including (observed in practice) the single
best-matching passage, because it sits closest to an already-selected sibling.
Capping how many chunks each item may contribute achieves the same spread
across saves while keeping each save's strongest evidence intact.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..config import RetrievalConfig
from ..models import Context, Hit, ItemHit
from .embeddings import Embedder
from .store import Store
from .text import script_of, tokenize

log = logging.getLogger(__name__)

# Chunk kinds carry different amounts of signal: a title match is a strong
# topical hint, a description match is weaker (descriptions are full of
# boilerplate). Kept deliberately mild — rank-fusion scores are tightly packed,
# so a larger spread here would let a weak title match outrank a passage that
# was the top result of *both* retrievers.
_KIND_WEIGHT = {"title": 1.06, "transcript": 1.0, "description": 0.92}


def _rrf(ranked_ids: list[str], k: int) -> dict[str, float]:
    return {cid: 1.0 / (k + rank + 1) for rank, cid in enumerate(ranked_ids)}



def _partition_by_script(weights: dict[str, float]) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, float]] = {"cjk": {}, "latin": {}, "mixed": {}}
    for token, weight in weights.items():
        bucket = "cjk" if any(ord(ch) > 0x2E80 for ch in token) else "latin"
        buckets[bucket][token] = weight
    buckets["mixed"] = dict(weights)
    return buckets


def _coverage(
    buckets: dict[str, dict[str, float]], text: str, chunk_tokens: frozenset[str]
) -> float:
    """IDF-weighted recall of the query's vocabulary inside this passage.

    Two corrections make this number mean what it should:

    *Unknown words are ignored.* ``buckets`` already excludes tokens the library
    has never seen, so "how I made my React app faster" is judged on ``react``
    alone rather than being diluted by four words no saved item could contain.

    *Scripts are scored separately.* A Chinese query term cannot appear in an
    English transcript no matter how relevant that transcript is, so an English
    passage is scored only against the query's latin terms (and vice versa).
    Without this, every cross-language match looks irrelevant — and a library of
    Chinese and English saves is exactly the case this project is built for.
    """
    weights = buckets.get(script_of(text)) or buckets["mixed"]
    if not weights:
        weights = buckets["mixed"]
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    matched_tokens = [token for token in weights if token in chunk_tokens]
    if not matched_tokens:
        return 0.0
    ratio = min(1.0, sum(weights[token] for token in matched_tokens) / total)
    # A ratio computed from a single shared word is not evidence, however rare
    # that word looks in a small library — "红烧肉的做法" and a Redis talk both
    # contain 做法, and both would otherwise score a perfect 1.0. Saturating on
    # the *number* of distinct matched terms caps a lone match well below a
    # genuine multi-term overlap, and approaches 1.0 as the overlap grows.
    saturation = len(matched_tokens) / (len(matched_tokens) + 0.8)
    return ratio * saturation


def confidence_of(dense: float, coverage: float) -> float:
    """Blend semantic similarity with literal term coverage into one 0..1 gate.

    Either signal alone is exploitable: cosine similarity from a hashed embedder
    reads high for any two texts in the same register, and term coverage reads
    high when a long passage happens to contain the query's words scattered
    across unrelated sentences. Requiring both to be non-trivial is what stops
    "a monad is a design pattern" from surfacing under a query about chunking.
    """
    dense = max(0.0, min(1.0, dense))
    coverage = max(0.0, min(1.0, coverage))
    arithmetic = 0.45 * dense + 0.55 * coverage
    geometric = (dense * coverage) ** 0.5  # zero unless *both* signals fire
    return 0.55 * arithmetic + 0.45 * geometric


class Retriever:
    """Turns a query (or a "what I'm watching now" context) into ranked saves."""

    def __init__(self, store: Store, embedder: Embedder, config: RetrievalConfig | None = None) -> None:
        self.store = store
        self.embedder = embedder
        self.config = config or RetrievalConfig()

    # ------------------------------------------------------------- chunk level
    def search_chunks(
        self,
        query: str,
        *,
        limit: int | None = None,
        exclude_items: set[str] | None = None,
        sources: set[str] | None = None,
    ) -> list[Hit]:
        cfg = self.config
        limit = limit or cfg.top_k_chunks
        query = (query or "").strip()
        if not query:
            return []

        pool = max(limit * 4, 64)
        dense = self.store.dense_search(self.embedder.embed_one(query), pool)
        lexical = self.store.lexical_search(query, pool)
        if not dense and not lexical:
            return []

        dense_scores = dict(dense)
        lexical_scores = dict(lexical)
        fused_dense = _rrf([cid for cid, _ in dense], cfg.rrf_k)
        fused_lexical = _rrf([cid for cid, _ in lexical], cfg.rrf_k)

        fused: dict[str, float] = defaultdict(float)
        for cid, score in fused_dense.items():
            fused[cid] += cfg.dense_weight * score
        for cid, score in fused_lexical.items():
            fused[cid] += cfg.lexical_weight * score

        candidate_ids = sorted(fused, key=lambda cid: -fused[cid])[: pool]
        chunks = self.store.get_chunks(candidate_ids)
        items = self.store.get_items({c.item_id for c in chunks.values()})

        # Apply filters and per-kind weighting before diversification, so MMR
        # ranks only things the caller can actually use.
        filtered: list[str] = []
        relevance: dict[str, float] = {}
        for cid in candidate_ids:
            chunk = chunks.get(cid)
            if chunk is None:
                continue
            item = items.get(chunk.item_id)
            if item is None:
                continue
            if exclude_items and item.id in exclude_items:
                continue
            if sources and item.source not in sources:
                continue
            filtered.append(cid)
            relevance[cid] = fused[cid] * _KIND_WEIGHT.get(chunk.kind, 1.0)

        if not filtered:
            return []

        # Spread the budget across saves: one long lecture must not consume the
        # whole candidate list, but each save keeps its strongest passages.
        per_item: dict[str, int] = defaultdict(int)
        selected: list[str] = []
        for cid in sorted(filtered, key=lambda cid: -relevance[cid]):
            item_id = chunks[cid].item_id
            if per_item[item_id] >= cfg.max_chunks_per_item:
                continue
            per_item[item_id] += 1
            selected.append(cid)
            if len(selected) >= limit:
                break

        hits = [
            Hit(
                chunk=chunks[cid],
                item=items[chunks[cid].item_id],
                score=relevance[cid],
                dense_score=dense_scores.get(cid, 0.0),
                lexical_score=lexical_scores.get(cid, 0.0),
            )
            for cid in selected
        ]
        hits.sort(key=lambda hit: -hit.score)
        return hits

    # -------------------------------------------------------------- item level
    def search_items(
        self,
        query: str,
        *,
        limit: int | None = None,
        exclude_items: set[str] | None = None,
        sources: set[str] | None = None,
        min_score: float | None = None,
    ) -> list[ItemHit]:
        """Aggregate chunk hits up to the item the user actually saved."""
        cfg = self.config
        limit = limit or cfg.top_k_items
        hits = self.search_chunks(
            query,
            limit=max(cfg.top_k_chunks, limit * 6),
            exclude_items=exclude_items,
            sources=sources,
        )
        if not hits:
            return []

        grouped: dict[str, list[Hit]] = defaultdict(list)
        for hit in hits:
            grouped[hit.item.id].append(hit)
        for item_hits in grouped.values():
            item_hits.sort(key=lambda h: -h.score)

        query_buckets = _partition_by_script(
            self.store.idf_weights([t for t in tokenize(query) if len(t) >= 2])
        )
        # Only the passages that actually contribute to the score need tokens.
        token_sets = self.store.token_sets(
            [hit.chunk.id for group in grouped.values() for hit in group[:4]]
        )

        results: list[ItemHit] = []
        for item_hits in grouped.values():
            best = item_hits[0].score
            # Extra matching passages are corroborating evidence, but with
            # sharply diminishing returns — one strong match beats five weak ones.
            support = sum(h.score for h in item_hits[1:4]) * 0.25
            confidence = max(
                confidence_of(
                    h.dense_score,
                    _coverage(query_buckets, h.chunk.text, token_sets.get(h.chunk.id, frozenset())),
                )
                for h in item_hits[:4]
            )
            results.append(
                ItemHit(
                    item=item_hits[0].item,
                    score=best + support,
                    chunks=[h.chunk for h in item_hits[:3]],
                    timestamps=[h.chunk.start for h in item_hits[:3] if h.chunk.kind == "transcript"],
                    confidence=confidence,
                )
            )

        # Final ordering is driven by confidence, with the fusion score as a
        # tie-breaker rather than the primary signal. Rank fusion over-rewards a
        # long passage that merely shares common bigrams with the query;
        # confidence is the calibrated "is this the same subject" number, and
        # measuring both on the golden set put the right answer first in every
        # case only once confidence carried ~80% of the weight.
        results.sort(key=lambda r: -(r.score * (0.2 + 0.8 * r.confidence)))
        if not results:
            return []

        # Two cuts, doing two different jobs. ``confidence`` is absolute and
        # corpus-independent: it answers "is this the same subject at all?".
        # ``min_score_ratio`` is relative: once a query has one excellent match,
        # it suppresses the long tail that merely ranked next.
        floor = cfg.min_confidence if min_score is None else min_score
        top = results[0].score or 1.0
        kept = [
            result
            for result in results
            if result.confidence >= floor and (result.score / top) >= cfg.min_score_ratio
        ][:limit]
        for result in kept:
            result.score = round(result.score / top, 5)
        return kept

    # ------------------------------------------------------------ live context
    def relate(self, context: Context, *, limit: int | None = None) -> list[ItemHit]:
        """The core "your bookmark is about to fire" query."""
        exclude: set[str] = set()
        if self.config.exclude_same_video and context.source and context.source_id:
            exclude.add(f"{context.source}:{context.source_id}")
        return self.search_items(context.as_query(), limit=limit, exclude_items=exclude)
