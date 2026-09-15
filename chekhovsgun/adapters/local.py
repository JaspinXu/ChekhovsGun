"""A file-backed adapter: import saves from JSON/JSONL/CSV, or a list of URLs.

This is the escape hatch. It covers Google Takeout exports, a hand-kept reading
list, a scraper someone wrote for a third app — and it is what ``chekhovsgun
demo`` uses to give a brand-new clone something to retrieve against.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Iterable, Iterator

from ..config import Config
from ..models import MEDIA_VIDEO, Comment, SavedItem, Segment
from .base import AdapterError, SourceAdapter

_FIELD_ALIASES = {
    "title": ("title", "name", "video_title"),
    "url": ("url", "link", "video_url", "href"),
    "author": ("author", "channel", "uploader", "up", "owner"),
    "description": ("description", "desc", "intro", "summary", "note", "notes"),
    "folder": ("folder", "playlist", "collection", "category"),
    "thumbnail": ("thumbnail", "cover", "image", "pic"),
}


def _pick(row: dict, field: str) -> str:
    for alias in _FIELD_ALIASES[field]:
        value = row.get(alias)
        if value:
            return str(value).strip()
    return ""


class LocalFileAdapter(SourceAdapter):
    name = "local"
    label = "本地导入 / Local import"

    def __init__(self, config: Config, path: str | Path | None = None, source: str = "local") -> None:
        super().__init__(config)
        self.path = Path(path).expanduser() if path else None
        self.name = source or "local"

    @property
    def configured(self) -> bool:
        return self.path is not None and self.path.exists()

    def setup_hint(self) -> str:
        return "Pass a .json / .jsonl / .csv / .txt file of saved items."

    def _rows(self) -> Iterator[dict]:
        if self.path is None or not self.path.exists():
            raise AdapterError(f"import file not found: {self.path}")
        suffix = self.path.suffix.lower()
        text = self.path.read_text(encoding="utf-8")
        if suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if line:
                    yield json.loads(line)
        elif suffix == ".json":
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get("items", [])
            yield from rows
        elif suffix == ".csv":
            yield from csv.DictReader(text.splitlines())
        else:  # a plain list of URLs
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    yield {"url": line, "title": line}

    def list_saved(self, *, limit: int | None = None) -> Iterable[SavedItem]:
        from . import identify_url  # local import to avoid a circular import

        for index, row in enumerate(self._rows()):
            if limit and index >= limit:
                return
            url = _pick(row, "url")
            # identify_url names the site for a post link too, so a plain list of
            # Zhihu URLs imports as Zhihu posts rather than an undifferentiated
            # "local" blob — and lands with the right media_kind for deep links.
            source, source_id, media_kind = identify_url(url)
            transcript = row.get("transcript") or row.get("segments") or []
            comments = row.get("comments") or []
            yield SavedItem(
                source=source or self.name,
                source_id=source_id or row.get("id") or f"{self.name}-{index}",
                media_kind=str(row.get("media_kind") or media_kind or MEDIA_VIDEO),
                title=_pick(row, "title") or f"Item {index + 1}",
                url=url,
                author=_pick(row, "author"),
                description=_pick(row, "description"),
                thumbnail=_pick(row, "thumbnail"),
                folder=_pick(row, "folder") or self.path.stem if self.path else "",
                duration=int(row.get("duration", 0) or 0),
                saved_at=float(row.get("saved_at", 0) or time.time()),
                tags=[t for t in (row.get("tags") or []) if t],
                extra={
                    **({"transcript": transcript} if transcript else {}),
                    **({"comments": comments} if comments else {}),
                },
            )

    def fetch_comments(self, item: SavedItem) -> Iterator[Comment]:
        for row in item.extra.get("comments") or []:
            if isinstance(row, str):
                yield Comment(text=row)
            else:
                yield Comment(
                    text=str(row.get("text", "")),
                    author=str(row.get("author", "")),
                    likes=int(row.get("likes", 0) or 0),
                    replies=[str(r) for r in (row.get("replies") or [])],
                )

    def fetch_content(self, item: SavedItem) -> Iterator[Segment]:
        rows = item.extra.get("transcript") or []
        for row in rows:
            if isinstance(row, str):
                yield Segment(text=row)
            else:
                start = float(row.get("start", 0.0) or 0.0)
                yield Segment(
                    text=str(row.get("text", "")),
                    start=start,
                    end=float(row.get("end", start + float(row.get("duration", 0) or 0))),
                )
