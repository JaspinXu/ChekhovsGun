"""Turn a saved item plus its subtitle track into retrievable chunks.

Subtitles arrive as hundreds of 1–3 second fragments; embedding each one is both
slow and useless (no fragment carries enough meaning). We merge them into
passages bounded by *two* limits at once — characters and wall-clock seconds —
so a fast talker and a slow talker both produce comparably sized chunks, and
every chunk keeps the timestamp that lets us deep-link into the video.
"""

from __future__ import annotations

from ..config import RetrievalConfig
from ..models import Chunk, Comment, SavedItem, Segment
from .text import normalize, sentences


def _clean(text: str) -> str:
    return " ".join(text.replace("\u200b", " ").split())


def chunk_segments(
    item_id: str,
    segments: list[Segment],
    *,
    max_chars: int = 420,
    overlap_chars: int = 80,
    max_seconds: float = 90.0,
    start_ordinal: int = 0,
) -> list[Chunk]:
    """Merge timed segments into overlapping passages."""
    chunks: list[Chunk] = []
    buffer: list[Segment] = []
    buffer_len = 0
    ordinal = start_ordinal

    def flush() -> None:
        nonlocal buffer, buffer_len, ordinal
        if not buffer:
            return
        text = _clean(" ".join(s.text for s in buffer))
        if len(normalize(text)) >= 8:
            chunks.append(
                Chunk(
                    item_id=item_id,
                    ordinal=ordinal,
                    text=text,
                    start=buffer[0].start,
                    end=buffer[-1].end or buffer[-1].start,
                    kind="transcript",
                )
            )
            ordinal += 1
        # Carry the tail of this chunk into the next one so a sentence split
        # across a boundary is still retrievable from both sides.
        carry: list[Segment] = []
        carried = 0
        for seg in reversed(buffer):
            if carried >= overlap_chars:
                break
            carry.insert(0, seg)
            carried += len(seg.text)
        buffer = carry if len(carry) < len(buffer) else []
        buffer_len = sum(len(s.text) for s in buffer)

    for segment in segments:
        text = _clean(segment.text)
        if not text:
            continue
        seg = Segment(text=text, start=segment.start, end=segment.end)
        span = (seg.end or seg.start) - (buffer[0].start if buffer else seg.start)
        if buffer and (buffer_len + len(text) > max_chars or span > max_seconds):
            flush()
        buffer.append(seg)
        buffer_len += len(text)

    # Final flush must not re-carry, or we would loop forever.
    if buffer:
        text = _clean(" ".join(s.text for s in buffer))
        if len(normalize(text)) >= 8:
            chunks.append(
                Chunk(
                    item_id=item_id,
                    ordinal=ordinal,
                    text=text,
                    start=buffer[0].start,
                    end=buffer[-1].end or buffer[-1].start,
                    kind="transcript",
                )
            )
    return chunks


def chunk_text(
    item_id: str,
    text: str,
    *,
    kind: str = "description",
    max_chars: int = 420,
    start_ordinal: int = 0,
) -> list[Chunk]:
    """Chunk untimed prose (a video description, an article body)."""
    text = _clean(text)
    if not text:
        return []
    chunks: list[Chunk] = []
    buffer = ""
    ordinal = start_ordinal
    for sentence in sentences(text) or [text]:
        if buffer and len(buffer) + len(sentence) > max_chars:
            chunks.append(Chunk(item_id=item_id, ordinal=ordinal, text=buffer.strip(), kind=kind))
            ordinal += 1
            buffer = ""
        buffer = f"{buffer} {sentence}".strip()
    if buffer:
        chunks.append(Chunk(item_id=item_id, ordinal=ordinal, text=buffer.strip(), kind=kind))
    return chunks


def chunk_comments(
    item_id: str,
    comments: list[Comment],
    *,
    max_chars: int = 600,
    start_ordinal: int = 0,
) -> list[Chunk]:
    """One chunk per comment thread, most-liked first."""
    chunks: list[Chunk] = []
    ordinal = start_ordinal
    for comment in comments:
        text = _clean(comment.as_passage().replace("\n", " "))[:max_chars]
        if len(normalize(text)) < 8:
            continue
        chunks.append(Chunk(item_id=item_id, ordinal=ordinal, text=text, kind="comment"))
        ordinal += 1
    return chunks


def chunk_item(
    item: SavedItem,
    segments: list[Segment] | None = None,
    config: RetrievalConfig | None = None,
    comments: list[Comment] | None = None,
) -> list[Chunk]:
    """Build the full chunk set for one saved item.

    Chunk 0 is always a *header* built from title + author + tags. It is what
    matches when a video has no subtitles at all, and it keeps short, punchy
    titles competitive against long transcript passages.
    """
    cfg = config or RetrievalConfig()
    header_parts = [item.title]
    if item.author:
        header_parts.append(item.author)
    if item.tags:
        header_parts.append(" ".join(item.tags))
    if item.folder:
        header_parts.append(item.folder)
    header = " · ".join(p for p in header_parts if p)

    chunks: list[Chunk] = [Chunk(item_id=item.id, ordinal=0, text=header, kind="title")]
    ordinal = 1

    description = _clean(item.description)
    if description:
        desc_chunks = chunk_text(
            item.id,
            description[:4000],
            kind="description",
            max_chars=cfg.chunk_chars,
            start_ordinal=ordinal,
        )
        chunks.extend(desc_chunks)
        ordinal += len(desc_chunks)

    if segments:
        transcript_chunks = chunk_segments(
            item.id,
            segments,
            max_chars=cfg.chunk_chars,
            overlap_chars=cfg.chunk_overlap_chars,
            max_seconds=cfg.chunk_max_seconds,
            start_ordinal=ordinal,
        )
        chunks.extend(transcript_chunks)
        ordinal += len(transcript_chunks)

    if comments:
        chunks.extend(chunk_comments(item.id, comments, start_ordinal=ordinal))

    # Guard against duplicate ids when the same text repeats verbatim
    # (very common in auto-generated subtitles).
    seen: set[str] = set()
    unique: list[Chunk] = []
    for chunk in chunks:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        unique.append(chunk)
    return unique
