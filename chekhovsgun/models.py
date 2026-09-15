"""Core data structures shared by adapters, the index and the API."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

#: What shape an item's content has. Everything that differs between a lecture
#: and a Zhihu answer — whether chunks carry timestamps, how a deep link is
#: built, whether "字幕" is a meaningful word in the UI — keys off this.
MEDIA_VIDEO = "video"
MEDIA_POST = "post"
MEDIA_KINDS = (MEDIA_VIDEO, MEDIA_POST)


def _now() -> float:
    return time.time()


def make_item_id(source: str, source_id: str) -> str:
    """Stable, human-debuggable primary key for a saved item."""
    return f"{source}:{source_id}"


def make_chunk_id(item_id: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha1(f"{item_id}|{ordinal}|{text}".encode()).hexdigest()
    return digest[:20]


def _escape_fragment(text: str) -> str:
    # ``-``, ``,`` and ``&`` are syntax inside a text fragment. quote() already
    # escapes the last two, but treats ``-`` as always-safe, so it needs help.
    return quote(text, safe="").replace("-", "%2D")


def _snippet(text: str, limit: int, *, tail: bool = False) -> str:
    """A leading or trailing slice that does not cut a word in half."""
    if len(text) <= limit:
        return text
    if tail:
        piece = text[-limit:]
        return piece[piece.index(" ") + 1:] if " " in piece else piece
    piece = text[:limit]
    return piece[: piece.rindex(" ")] if " " in piece else piece


def text_fragment(text: str, limit: int = 48) -> str:
    """Build a ``:~:text=`` fragment that scrolls to and highlights ``text``.

    Uses the ``textStart,textEnd`` form for a long passage so the whole thing
    highlights rather than just its opening words. Matching is defined to be
    whitespace-normalising and case-insensitive, which is what makes this
    survive the difference between our cleaned chunk text and the rendered page.

    Browsers without text-fragment support ignore an unknown fragment and land
    on the page normally, so the result is always safe to append.
    """
    text = " ".join((text or "").split())
    if len(text) < 8:
        return ""
    start = _snippet(text, limit)
    if len(text) > limit * 2:
        end = _snippet(text, limit, tail=True)
        if end and end != start:
            return f":~:text={_escape_fragment(start)},{_escape_fragment(end)}"
    return f":~:text={_escape_fragment(start)}"


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
    #: '' | 'captions' | 'whisper' | 'capture' | 'none' — where the body came from.
    transcript_source: str = ""
    #: One of :data:`MEDIA_KINDS`. Defaults to video because every item that
    #: existed before posts were supported is one, which makes the column a
    #: pure additive migration with no backfill.
    media_kind: str = MEDIA_VIDEO

    @property
    def id(self) -> str:
        return make_item_id(self.source, self.source_id)

    @property
    def is_post(self) -> bool:
        return self.media_kind == MEDIA_POST

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
        """URL that jumps straight to the most relevant part of the item.

        A video has a timeline, so the link carries a timestamp. A post has no
        timeline but it does have the text itself, so the link carries a text
        fragment that scrolls to and highlights the matching passage — the same
        promise ("go to the exact spot"), honoured with what the medium offers.
        """
        if self.item.is_post:
            return self._post_link()
        return self._video_link()

    def _video_link(self) -> str:
        if not self.timestamps:
            return self.item.url
        seconds = int(max(0.0, self.timestamps[0]))
        if seconds <= 0:
            return self.item.url
        sep = "&" if "?" in self.item.url else "?"
        if self.item.source == "bilibili":
            return f"{self.item.url}{sep}t={seconds}"
        return f"{self.item.url}{sep}t={seconds}s"

    def _post_link(self) -> str:
        chunk = self._anchor_chunk()
        base = self.item.url.split("#", 1)[0]
        if chunk is None:
            return base
        fragment = text_fragment(chunk.text)
        return f"{base}#{fragment}" if fragment else base

    def _anchor_chunk(self) -> Chunk | None:
        """The chunk whose text the deep link should scroll to.

        Body text is preferred over a comment: a comment often sits behind a
        "show more" control, so a fragment pointing at one silently fails to
        match, whereas body text is on the page as soon as it loads.
        """
        fallback: Chunk | None = None
        for chunk in self.chunks:
            if chunk.kind == "title":
                continue
            if chunk.kind == "comment":
                fallback = fallback or chunk
                continue
            return chunk
        return fallback

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
