"""The facade the CLI, the HTTP server and any embedder of this library use.

Everything expensive is built lazily and exactly once: the SQLite connection,
the embedding backend (which may download a model), and the in-memory indexes.
``relate`` additionally caches per video, because the browser extension will ask
about the same video every time the user scrolls back to it, and because the
"should this popup fire at all?" decision must feel instant.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterable

from .adapters import AdapterError, SourceAdapter, build_adapter, context_from_url
from .config import Config, load_config
from .ingest import IngestPipeline, IngestReport
from .llm.explain import Explainer, Explanation
from .models import Context, ItemHit
from .rag.embeddings import Embedder, get_embedder
from .rag.retriever import Retriever
from .rag.store import Store

log = logging.getLogger(__name__)

CACHE_TTL = 180.0
CACHE_MAX = 256


class Engine:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.config.ensure_home()
        self._lock = threading.RLock()
        self._store: Store | None = None
        self._embedder: Embedder | None = None
        self._retriever: Retriever | None = None
        self._explainer: Explainer | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ------------------------------------------------------------ lazy wiring
    @property
    def store(self) -> Store:
        with self._lock:
            if self._store is None:
                assert self.config.db_path is not None
                self._store = Store(self.config.db_path)
            return self._store

    @property
    def embedder(self) -> Embedder:
        with self._lock:
            if self._embedder is None:
                self._embedder = get_embedder(self.config.embedding)
                log.info("embedding backend: %s", self._embedder.signature)
            return self._embedder

    @property
    def retriever(self) -> Retriever:
        with self._lock:
            if self._retriever is None:
                self._retriever = Retriever(self.store, self.embedder, self.config.retrieval)
            return self._retriever

    @property
    def explainer(self) -> Explainer:
        with self._lock:
            if self._explainer is None:
                self._explainer = Explainer(self.config.llm)
            return self._explainer

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None

    # ------------------------------------------------------------------ cache
    def _cache_key(self, context: Context, limit: int) -> str:
        # The store's write counter is the whole invalidation story, and reading
        # it is free — the previous key ran six COUNT queries per request.
        return (
            f"{self.store.revision}|{context.source}:{context.source_id}"
            f"|{limit}|{context.title[:60]}|{context.description[:60]}"
        )

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        created, value = entry
        if time.time() - created > CACHE_TTL:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: dict[str, Any]) -> None:
        if len(self._cache) >= CACHE_MAX:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (time.time(), value)

    def invalidate_cache(self) -> None:
        self._cache.clear()

    # -------------------------------------------------------------- retrieval
    def relate(
        self,
        context: Context,
        *,
        limit: int | None = None,
        explain: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """The endpoint the browser extension calls on every video change."""
        limit = limit or self.config.retrieval.top_k_items
        if not (context.title or context.description or context.source_id):
            return {
                "fired": False,
                "reason_code": "empty_context",
                "reason": "nothing to match on",
                "hits": [],
                "explanation": None,
            }

        key = self._cache_key(context, limit)
        if use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return {**cached, "cached": True}

        started = time.perf_counter()
        hits: list[ItemHit] = self.retriever.relate(context, limit=limit)
        explanation: Explanation | None = None
        if hits and explain:
            explanation = self.explainer.explain(context, hits)

        result = {
            "fired": bool(hits),
            "reason_code": "" if hits else "no_match",
            "reason": "" if hits else "nothing saved matches this closely enough",
            "query": context.as_query()[:300],
            "hits": [hit.to_dict() for hit in hits],
            "explanation": explanation.to_dict() if explanation else None,
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
            "cached": False,
        }
        if use_cache:
            self._cache_put(key, result)
        if hits:
            self.store.log_event(
                "fired",
                source=context.source,
                item_id=hits[0].item.id,
                payload={"watching": context.title[:120], "matched": len(hits)},
            )
        return result

    def relate_url(self, url: str, **kwargs: Any) -> dict[str, Any]:
        context = context_from_url(url)
        if context is None:
            return {
                "fired": False,
                "reason_code": "unknown_url",
                "reason": f"not a YouTube or Bilibili url: {url}",
                "hits": [],
                "explanation": None,
            }
        stored = self.store.get_item(f"{context.source}:{context.source_id}")
        if stored is not None:
            context.title = context.title or stored.title
            context.author = context.author or stored.author
            context.description = context.description or stored.description
        result = self.relate(context, **kwargs)
        # Previewing a URL that is itself in the library is the common confusing
        # case: the video is excluded from its own results by design, so say so
        # rather than reporting a bare "no match".
        if not result["fired"] and stored is not None:
            result["reason_code"] = "self_saved"
            result["reason"] = "this video is itself in your library; nothing else matched it"
        return result

    def search(self, query: str, *, limit: int = 10, sources: set[str] | None = None) -> list[ItemHit]:
        return self.retriever.search_items(query, limit=limit, sources=sources)

    # ----------------------------------------------------------------- ingest
    def adapters(self, names: Iterable[str] | None = None) -> list[SourceAdapter]:
        from .adapters import REGISTRY

        wanted = list(names) if names else list(REGISTRY)
        return [build_adapter(name, self.config) for name in wanted]

    def ingest(
        self,
        source: str | SourceAdapter,
        *,
        limit: int | None = None,
        force: bool = False,
        fetch_transcripts: bool = True,
        progress: Callable[[str, dict], None] | None = None,
    ) -> IngestReport:
        adapter = build_adapter(source, self.config) if isinstance(source, str) else source
        if not adapter.configured:
            report = IngestReport(source=adapter.name)
            report.errors.append(adapter.setup_hint() or "adapter is not configured")
            report.finished_at = time.time()
            return report
        pipeline = IngestPipeline(self.config, self.store, self.embedder)
        try:
            report = pipeline.run(
                adapter,
                limit=limit,
                force=force,
                fetch_transcripts=fetch_transcripts,
                progress=progress,
            )
        finally:
            adapter.close()
        self.store.set_meta("cache_epoch", str(int(time.time())))
        self.invalidate_cache()
        return report

    def ingest_all(self, **kwargs: Any) -> list[IngestReport]:
        reports: list[IngestReport] = []
        for adapter in self.adapters():
            if not adapter.configured:
                log.info("skipping %s: %s", adapter.name, adapter.setup_hint())
                adapter.close()
                continue
            reports.append(self.ingest(adapter, **kwargs))
        return reports

    def reindex(self, progress: Callable[[str, dict], None] | None = None) -> int:
        from .ingest import Indexer

        count = Indexer(self.config, self.store, self.embedder).reindex_all(progress)
        self.store.set_meta("cache_epoch", str(int(time.time())))
        self.invalidate_cache()
        return count

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        adapters = []
        for adapter in self.adapters():
            adapters.append(
                {
                    "name": adapter.name,
                    "label": adapter.label,
                    "configured": adapter.configured,
                    "hint": adapter.setup_hint(),
                }
            )
            adapter.close()
        stats = self.store.stats()
        return {
            "version": __import__("chekhovsgun").__version__,
            "stats": stats,
            "adapters": adapters,
            "embedding": self.embedder.signature,
            "llm": {
                "enabled": self.config.llm.enabled,
                "usable": self.config.llm.usable,
                "model": self.config.llm.model if self.config.llm.usable else "",
            },
            "home": str(self.config.home),
        }


__all__ = ["AdapterError", "Engine"]
