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
from ..models import SavedItem, Segment
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
        from . import detect_source  # local import to avoid a circular import

        for index, row in enumerate(self._rows()):
            if limit and index >= limit:
                return
            url = _pick(row, "url")
            source, source_id = detect_source(url)
            transcript = row.get("transcript") or row.get("segments") or []
            yield SavedItem(
                source=source or self.name,
                source_id=source_id or row.get("id") or f"{self.name}-{index}",
                title=_pick(row, "title") or f"Item {index + 1}",
                url=url,
                author=_pick(row, "author"),
                description=_pick(row, "description"),
                thumbnail=_pick(row, "thumbnail"),
                folder=_pick(row, "folder") or self.path.stem if self.path else "",
                duration=int(row.get("duration", 0) or 0),
                saved_at=float(row.get("saved_at", 0) or time.time()),
                tags=[t for t in (row.get("tags") or []) if t],
                extra={"transcript": transcript} if transcript else {},
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
