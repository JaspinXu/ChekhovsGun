"""The ingest pipeline: adapter → transcript → chunks → vectors → index.

Ingest is *incremental*. Each item gets a content hash over the fields that
would change its chunks; unchanged items skip transcript fetching and embedding
entirely. That matters because transcript fetching is the slow, rate-limited,
ban-prone part of the whole system, and a nightly re-sync of a 2 000-item
library should touch only what actually changed.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .adapters.base import SourceAdapter
from .config import Config
from .models import SavedItem, Segment
from .rag.chunker import chunk_item
from .rag.embeddings import Embedder
from .rag.store import Store

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, dict], None]


@dataclass
class IngestReport:
    source: str = ""
    seen: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    with_transcript: int = 0
    chunks: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "seen": self.seen,
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "with_transcript": self.with_transcript,
            "chunks": self.chunks,
            "errors": self.errors[:20],
            "duration": round(self.duration, 2),
        }

    def merge(self, other: IngestReport) -> IngestReport:
        self.seen += other.seen
        self.added += other.added
        self.updated += other.updated
        self.skipped += other.skipped
        self.failed += other.failed
        self.with_transcript += other.with_transcript
        self.chunks += other.chunks
        self.errors.extend(other.errors)
        return self


def content_hash(item: SavedItem) -> str:
    """Hash of everything that would change the item's chunks."""
    payload = "|".join(
        [
            item.title,
            item.author,
            item.description[:4000],
            item.folder,
            ",".join(item.tags),
            str(int(item.duration)),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]


class Indexer:
    """Embeds and stores items. Usable standalone for imports without an adapter."""

    def __init__(self, config: Config, store: Store, embedder: Embedder) -> None:
        self.config = config
        self.store = store
        self.embedder = embedder
        signature = embedder.signature
        previous = store.get_meta("embedding_signature")
        if previous and previous != signature:
            log.warning(
                "embedding backend changed (%s -> %s); existing vectors will not match. "
                "Run `chekhovsgun reindex` to rebuild.",
                previous,
                signature,
            )
        store.set_meta("embedding_signature", signature)

    def index_item(self, item: SavedItem, segments: Sequence[Segment] | None = None) -> int:
        """Chunk, embed and persist a single item. Returns the chunk count."""
        chunks = chunk_item(item, list(segments or []), self.config.retrieval)
        if not chunks:
            return 0
        vectors = self.embedder.embed([c.text for c in chunks])
        self.store.upsert_item(
            item,
            content_hash=content_hash(item),
            has_transcript=bool(segments),
        )
        self.store.replace_chunks(item.id, chunks, vectors)
        return len(chunks)

    def reindex_all(self, progress: ProgressFn | None = None) -> int:
        """Re-embed every stored chunk — needed after switching embedding backend."""
        total = 0
        offset = 0
        while True:
            items = self.store.list_items(limit=100, offset=offset)
            if not items:
                break
            offset += len(items)
            for item in items:
                chunks = self.store.item_chunks(item.id)
                if not chunks:
                    continue
                vectors = self.embedder.embed([c.text for c in chunks])
                self.store.replace_chunks(item.id, chunks, vectors)
                total += len(chunks)
                if progress:
                    progress("reindex", {"item": item.title, "chunks": len(chunks)})
        self.store.set_meta("embedding_signature", self.embedder.signature)
        return total


class IngestPipeline:
    def __init__(self, config: Config, store: Store, embedder: Embedder) -> None:
        self.config = config
        self.store = store
        self.indexer = Indexer(config, store, embedder)

    def run(
        self,
        adapter: SourceAdapter,
        *,
        limit: int | None = None,
        force: bool = False,
        fetch_transcripts: bool = True,
        progress: ProgressFn | None = None,
    ) -> IngestReport:
        report = IngestReport(source=adapter.name)
        known = self.store.item_hashes(adapter.name)

        def emit(stage: str, payload: dict) -> None:
            if progress:
                try:
                    progress(stage, payload)
                except Exception:  # pragma: no cover - progress must never break ingest
                    log.debug("progress callback failed", exc_info=True)

        items: Iterable[SavedItem]
        try:
            items = adapter.list_saved(limit=limit)
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"list_saved failed: {exc}")
            report.finished_at = time.time()
            log.exception("listing saved items failed for %s", adapter.name)
            return report

        for item in items:
            report.seen += 1
            emit("item", {"title": item.title, "seen": report.seen})
            try:
                new_hash = content_hash(item)
                existing = known.get(item.id)
                if existing and existing == new_hash and not force:
                    report.skipped += 1
                    continue

                segments: list[Segment] = []
                if fetch_transcripts:
                    try:
                        segments = list(adapter.fetch_content(item))
                    except Exception as exc:
                        # A missing transcript is normal, not a failure: the item
                        # still indexes from its title and description.
                        log.debug("transcript unavailable for %s: %s", item.id, exc)
                        emit("no_transcript", {"title": item.title, "reason": str(exc)})

                count = self.indexer.index_item(item, segments)
                report.chunks += count
                if segments:
                    report.with_transcript += 1
                if existing:
                    report.updated += 1
                else:
                    report.added += 1
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"{item.id}: {exc}")
                log.exception("failed to index %s", item.id)

            if limit and (report.added + report.updated + report.skipped) >= limit:
                break

        report.finished_at = time.time()
        self.store.log_event("ingest", source=adapter.name, payload=report.to_dict())
        return report
