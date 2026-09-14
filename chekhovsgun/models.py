"""Core data structures shared by adapters, the index and the API."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any


def _now() -> float:
    return time.time()


def make_item_id(source: str, source_id: str) -> str:
    """Stable, human-debuggable primary key for a saved item."""
    return f"{source}:{source_id}"


def make_chunk_id(item_id: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha1(f"{item_id}|{ordinal}|{text}".encode()).hexdigest()
    return digest[:20]


@dataclass(slots=True)
class Segment:
    """One timed slice of a transcript / subtitle track."""

    text: str
    start: float = 0.0
    end: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class Comment:
    """One top-level comment thread, with its best replies folded in.

    Threads are kept whole rather than split per reply: a reply like "其实是反
    过来的" is meaningless without the comment it answers, and splitting them
    would produce two chunks that each retrieve badly.
    """

    text: str
    author: str = ""
    likes: int = 0
    replies: list[str] = field(default_factory=list)

    def as_passage(self) -> str:
        parts = [self.text.strip()]
        for reply in self.replies:
            reply = reply.strip()
            if reply:
                parts.append(f"↳ {reply}")
        return "\n".join(parts)


#: Item lifecycle. ``digested`` and ``muted`` both stop an item from firing;
#: the difference is what the user meant, and only ``digested`` counts as the
#: product actually having worked.
STATUS_ACTIVE = "active"
STATUS_DIGESTED = "digested"
STATUS_MUTED = "muted"
STATUSES = (STATUS_ACTIVE, STATUS_DIGESTED, STATUS_MUTED)


@dataclass(slots=True)
class SavedItem:
    """Something the user bookmarked in a source app."""

    source: str
    source_id: str
    title: str
    url: str
    author: str = ""
    author_id: str = ""
    description: str = ""
    thumbnail: str = ""
    duration: int = 0
    published_at: float = 0.0
    saved_at: float = 0.0
    folder: str = ""
    lang: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    #: One of :data:`STATUSES`. Set by the user, never by ingest.
    status: str = STATUS_ACTIVE
    #: The user's own tags, kept separate from the platform's ``tags`` so a
    #: re-sync can overwrite platform metadata without destroying their work.
    user_tags: list[str] = field(default_factory=list)
    note: str = ""
    #: '' | 'captions' | 'whisper' | 'none' — where the transcript came from.
    transcript_source: str = ""

    @property
    def id(self) -> str:
        return make_item_id(self.source, self.source_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.id
        return data


@dataclass(slots=True)
class Chunk:
    """A retrievable slice of an item's content."""

    item_id: str
    ordinal: int
    text: str
    start: float = 0.0
    end: float = 0.0
    kind: str = "transcript"  # transcript | description | title
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_chunk_id(self.item_id, self.ordinal, self.text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Hit:
    """A retrieval result: a chunk, its parent item, and why it surfaced."""

    chunk: Chunk
    item: SavedItem
    score: float
    dense_score: float = 0.0
    lexical_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 5),
            "dense_score": round(self.dense_score, 5),
            "lexical_score": round(self.lexical_score, 5),
            "chunk": self.chunk.to_dict(),
            "item": self.item.to_dict(),
        }


@dataclass(slots=True)
class ItemHit:
    """Item-level result after aggregating its best chunks."""

    item: SavedItem
    score: float
    chunks: list[Chunk] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    #: 0..1 estimate of "is this actually about the same thing?", independent of
    #: corpus size. ``score`` orders results; ``confidence`` decides whether the
    #: popup is allowed to fire at all.
    confidence: float = 0.0

    def deep_link(self) -> str:
        """URL that jumps straight to the most relevant moment."""
        if not self.timestamps:
            return self.item.url
        seconds = int(max(0.0, self.timestamps[0]))
        if seconds <= 0:
            return self.item.url
        sep = "&" if "?" in self.item.url else "?"
        if self.item.source == "bilibili":
            return f"{self.item.url}{sep}t={seconds}"
        return f"{self.item.url}{sep}t={seconds}s"

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 5),
            "confidence": round(self.confidence, 4),
            "item": self.item.to_dict(),
            "deep_link": self.deep_link(),
            "chunks": [c.to_dict() for c in self.chunks],
            "timestamps": self.timestamps,
        }


@dataclass(slots=True)
class Context:
    """What the user is looking at right now, in the source app."""

    source: str = ""
    source_id: str = ""
    title: str = ""
    author: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    url: str = ""

    def as_query(self) -> str:
        parts = [self.title, self.author, " ".join(self.tags), self.description[:600]]
        return "\n".join(p for p in parts if p).strip()
