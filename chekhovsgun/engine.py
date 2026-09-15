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

from . import sites
from .adapters import AdapterError, SourceAdapter, build_adapter, context_from_url, identify_url
from .config import Config, load_config
from .ingest import IngestPipeline, IngestReport
from .llm.explain import Explainer, Explanation
from .models import (
    MEDIA_POST,
    STATUS_DIGESTED,
    STATUS_MUTED,
    Comment,
    Context,
    ItemHit,
    SavedItem,
    Segment,
)
from .rag.embeddings import Embedder, get_embedder
from .rag.retriever import Retriever
from .rag.store import Store

log = logging.getLogger(__name__)

CACHE_TTL = 180.0
CACHE_MAX = 256

#: Fields a capture payload may carry, beyond the url that is always required.
_CAPTURE_FIELDS = (
    "title", "author", "text", "excerpt", "thumbnail", "folder", "source",
    "media_kind", "tags", "comments", "published_at", "saved_at",
)


def _capture_kwargs(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _CAPTURE_FIELDS if row.get(key)}


def _paragraph_segments(text: str) -> list[Segment]:
    """Split a post body into untimed segments, one per paragraph.

    Paragraphs are the closest thing a post has to subtitle cues, and feeding
    them through the same merger the transcript path uses means a post's chunks
    obey exactly the same size rules as a video's — so retrieval does not have
    to know which kind of item it is looking at.
    """
    if not text:
        return []
    paragraphs = [" ".join(part.split()) for part in text.replace("\r", "").split("\n")]
    return [Segment(text=part) for part in paragraphs if part]


class Engine:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.config.ensure_home()
        self._lock = threading.RLock()
        self._store: Store | None = None
        self._embedder: Embedder | None = None
        self._retriever: Retriever | None = None
        self._explainer: Explainer | None = None
        self._pipeline: IngestPipeline | None = None
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

    @property
    def pipeline(self) -> IngestPipeline:
        """Shared because capture calls it once per saved page, not once per sync.

        Building one costs a Whisper availability probe, which is cheap but not
        free, and there is nothing per-run in a pipeline's state.
        """
        with self._lock:
            if self._pipeline is None:
                self._pipeline = IngestPipeline(self.config, self.store, self.embedder)
            return self._pipeline

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None
            self._pipeline = None

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
    def _silenced_items(self) -> set[str]:
        """Items the user has told us to stop interrupting them about."""
        statuses = [STATUS_MUTED]
        if self.config.retrieval.exclude_digested:
            statuses.append(STATUS_DIGESTED)
        return self.store.item_ids_with_status(statuses)

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

        needed = self.config.retrieval.min_library_items
        held = self.store.item_count()
        if held < needed:
            return {
                "fired": False,
                "reason_code": "library_too_small",
                "reason": f"only {held} saves indexed; the popup waits for {needed}",
                "hits": [],
                "explanation": None,
                "library": {"items": held, "needed": needed},
            }

        key = self._cache_key(context, limit)
        if use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return {**cached, "cached": True}

        started = time.perf_counter()
        hits: list[ItemHit] = self.retriever.relate(
            context, limit=limit, exclude_items=self._silenced_items()
        )
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

    def relate_url(self, url: str, *, fetch_missing: bool = False, **kwargs: Any) -> dict[str, Any]:
        """Answer "would this page have interrupted me?" for a bare URL.

        The extension never comes through here — it has already read the page and
        posts the text. This is for a URL typed into the dashboard or the CLI,
        where the only thing we know is the address. If the page is already in
        the library we match on what we stored; otherwise there is nothing to
        match on at all, and ``fetch_missing`` says whether it is acceptable to
        go and read the page. Off by default, because a retrieval call reaching
        out to the network is a surprise worth opting into.
        """
        context = context_from_url(url)
        if context is None:
            return {
                "fired": False,
                "reason_code": "unknown_url",
                "reason": f"not a usable url: {url!r}",
                "hits": [],
                "explanation": None,
            }
        stored = self.store.get_item(f"{context.source}:{context.source_id}")
        if stored is not None:
            context.title = context.title or stored.title
            context.author = context.author or stored.author
            context.description = context.description or stored.description
        elif fetch_missing:
            from .extract import fetch_readable

            readable = fetch_readable(url)
            context.title = readable.title
            context.author = readable.author
            context.description = readable.text[:4000]
        if not (context.title or context.description):
            # Saying "nothing matched" here would be a lie: we never had
            # anything to match against in the first place.
            return {
                "fired": False,
                "reason_code": "page_unreadable",
                "reason": "couldn't read anything from that page to match on",
                "hits": [],
                "explanation": None,
            }
        result = self.relate(context, **kwargs)
        # Previewing a URL that is itself in the library is the common confusing
        # case: the video is excluded from its own results by design, so say so
        # rather than reporting a bare "no match".
        if not result["fired"] and stored is not None:
            result["reason_code"] = "self_saved"
            result["reason"] = "this video is itself in your library; nothing else matched it"
        return result

    def search(self, query: str, *, limit: int = 10, sources: set[str] | None = None) -> list[ItemHit]:
        """Explicit search sees everything — muting stops interruptions, not recall."""
        return self.retriever.search_items(query, limit=limit, sources=sources)

    def mark(
        self,
        item_id: str,
        *,
        status: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        item = self.store.set_item_status(
            item_id, status=status, add_tags=add_tags, remove_tags=remove_tags, note=note
        )
        if item is None:
            return None
        self.invalidate_cache()
        if status:
            self.store.log_event("status", source=item.source, item_id=item.id,
                                 payload={"status": status})
        return item.to_dict()

    # ---------------------------------------------------------------- capture
    def capture(
        self,
        url: str,
        *,
        title: str = "",
        author: str = "",
        text: str = "",
        excerpt: str = "",
        thumbnail: str = "",
        folder: str = "",
        source: str = "",
        media_kind: str = "",
        tags: Iterable[str] | None = None,
        comments: Iterable[dict[str, Any]] | None = None,
        published_at: float = 0.0,
        saved_at: float = 0.0,
        origin: str = "extension",
        force: bool = False,
    ) -> dict[str, Any]:
        """Take in a page the browser read for us.

        This is the other half of ingest. An adapter goes out and fetches what a
        platform will admit to; capture receives what the user's own logged-in
        browser can already see — which is the only way to reach sites with no
        API, and the only way to reach content behind a login without asking for
        a password. The page arrives already extracted, so there is nothing to
        fetch and the whole call is chunk → embed → store.
        """
        url = (url or "").strip()
        if not url:
            raise ValueError("capture needs a url")
        canonical = sites.canonical_url(url)
        detected_source, source_id, detected_kind = identify_url(canonical)
        item = SavedItem(
            source=source or detected_source or sites.GENERIC_SOURCE,
            source_id=source_id,
            media_kind=media_kind or detected_kind or MEDIA_POST,
            title=(title or canonical)[:300],
            url=canonical,
            author=author[:120],
            # The excerpt is metadata; the body goes in as segments. For a post
            # the chunker drops the description when a body is present, so
            # sending both never double-indexes the same prose.
            description=excerpt[:4000],
            thumbnail=thumbnail,
            folder=folder[:120],
            published_at=published_at,
            saved_at=saved_at or time.time(),
            tags=[str(t)[:40] for t in (tags or []) if t][:20],
            extra={"captured_via": origin},
        )
        segments = _paragraph_segments(text)
        comment_objects = [
            Comment(
                text=str(row.get("text", ""))[:2000],
                author=str(row.get("author", ""))[:80],
                likes=int(row.get("likes", 0) or 0),
                replies=[str(r)[:800] for r in (row.get("replies") or [])][:4],
            )
            for row in (comments or [])
            if str(row.get("text", "")).strip()
        ]
        outcome = self.pipeline.ingest_one(
            item,
            segments,
            comment_objects,
            transcript_source="capture" if segments else "pending",
            force=force,
        )
        if outcome.state != "skipped":
            self.invalidate_cache()
            self.store.log_event(
                "captured",
                source=item.source,
                item_id=item.id,
                payload={
                    "title": item.title[:120],
                    "origin": origin,
                    "body_chars": len(text or ""),
                    "state": outcome.state,
                },
            )
        return {
            "item_id": item.id,
            "state": outcome.state,
            "chunks": outcome.chunks,
            "error": outcome.error,
            "url": canonical,
            "source": item.source,
            "media_kind": item.media_kind,
            "needs_body": not segments,
        }

    def capture_many(
        self, rows: Iterable[dict[str, Any]], *, origin: str = "scan"
    ) -> dict[str, Any]:
        """Bulk capture, used by the favourites scan. Never raises for one bad row."""
        summary = {"added": 0, "updated": 0, "skipped": 0, "failed": 0, "needs_body": 0}
        errors: list[str] = []
        for row in rows:
            try:
                result = self.capture(str(row.get("url", "")), origin=origin, **_capture_kwargs(row))
            except Exception as exc:
                summary["failed"] += 1
                if len(errors) < 20:
                    errors.append(str(exc)[:200])
                continue
            state = result["state"]
            summary[state] = summary.get(state, 0) + 1
            if result["needs_body"]:
                summary["needs_body"] += 1
        return {**summary, "errors": errors}

    def pending_body_count(self) -> int:
        return self.store.count_items_awaiting_body()

    def hydrate_pending(
        self, *, limit: int = 200, progress: Callable[[str, dict], None] | None = None
    ) -> dict[str, Any]:
        """Fetch and index the bodies of items captured as bare links.

        The favourites scan collects hundreds of links in the time it would take
        to load a handful of pages, so it stores them immediately and leaves the
        bodies to this. An item whose page cannot be read — a login wall, a
        JavaScript-only app, a dead link — keeps its title and stops being
        retried, because retrying it on every run would starve the ones that can
        be read.
        """
        from .extract import fetch_readable

        done = {"fetched": 0, "indexed": 0, "failed": 0, "chunks": 0}
        items = self.store.items_awaiting_body(limit=limit)
        for index, item in enumerate(items, 1):
            if progress:
                progress("hydrate", {"title": item.title, "seen": index, "total": len(items)})
            readable = fetch_readable(item.url)
            done["fetched"] += 1
            if not readable:
                # Mark it resolved-but-empty so the next run skips it.
                self.store.set_transcript_source(item.id, "none")
                done["failed"] += 1
                continue
            if readable.title and (not item.title or item.title == item.url):
                item.title = readable.title[:300]
            if readable.author and not item.author:
                item.author = readable.author[:120]
            outcome = self.pipeline.ingest_one(
                item,
                _paragraph_segments(readable.text),
                transcript_source="capture",
                force=True,
            )
            if outcome.state == "failed":
                done["failed"] += 1
                continue
            done["indexed"] += 1
            done["chunks"] += outcome.chunks
        if done["indexed"]:
            self.invalidate_cache()
        return done

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
        stats["pending_body"] = self.store.count_items_awaiting_body()
        return {
            "version": __import__("chekhovsgun").__version__,
            "stats": stats,
            "adapters": adapters,
            "embedding": self.embedder.signature,
            # How many saves the popup needs before it trusts itself. Clients
            # show the gap so a deliberately quiet extension does not read as a
            # broken one.
            "popup_threshold": self.config.retrieval.min_library_items,
            "llm": {
                "enabled": self.config.llm.enabled,
                "usable": self.config.llm.usable,
                "model": self.config.llm.model if self.config.llm.usable else "",
            },
            "home": str(self.config.home),
        }


__all__ = ["AdapterError", "Engine"]
