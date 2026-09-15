"""Adapter registry — everything that knows about a specific source app."""

from __future__ import annotations

from typing import Iterable

from .. import sites
from ..config import Config
from ..models import MEDIA_VIDEO, Context
from .base import AdapterError, SourceAdapter
from .bilibili import BilibiliAdapter
from .local import LocalFileAdapter
from .youtube import YouTubeAdapter

#: Source adapters that can both ingest and recognise live URLs.
REGISTRY: dict[str, type[SourceAdapter]] = {
    YouTubeAdapter.name: YouTubeAdapter,
    BilibiliAdapter.name: BilibiliAdapter,
}

__all__ = [
    "REGISTRY",
    "AdapterError",
    "BilibiliAdapter",
    "LocalFileAdapter",
    "SourceAdapter",
    "YouTubeAdapter",
    "build_adapter",
    "context_from_url",
    "detect_source",
    "identify_url",
    "iter_adapters",
]


def build_adapter(name: str, config: Config) -> SourceAdapter:
    try:
        return REGISTRY[name](config)
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY))
        raise AdapterError(f"unknown source {name!r}; known sources: {known}") from exc


def iter_adapters(config: Config, names: Iterable[str] | None = None) -> list[SourceAdapter]:
    wanted = list(names) if names else list(REGISTRY)
    return [build_adapter(name, config) for name in wanted]


def detect_source(url: str) -> tuple[str, str]:
    """``(source, source_id)`` for a URL one of our *adapters* owns, else ``('', '')``.

    Deliberately narrow: this answers "can we sync this platform?", not "what
    page is this?". For the latter use :func:`identify_url`, which never fails.
    """
    for name, adapter_cls in REGISTRY.items():
        source_id = adapter_cls.parse_url(url)
        if source_id:
            return name, source_id
    return "", ""


def identify_url(url: str) -> tuple[str, str, str]:
    """``(source, source_id, media_kind)`` for *any* URL.

    Adapter-owned video sites keep the ids their adapters parse; everything else
    falls through to :mod:`chekhovsgun.sites`, which names the site when it
    knows it and hashes the canonical URL when it does not. The consequence that
    matters: ``relate`` can answer about a page from a site this project has
    never seen, matching on its text alone. That is also the seam a phone client
    plugs into — it can POST any URL and get a real answer.
    """
    source, source_id = detect_source(url)
    if source:
        return source, source_id, MEDIA_VIDEO
    return sites.identify(url)


def context_from_url(url: str) -> Context | None:
    source, source_id, _ = identify_url(url)
    if not source:
        return None
    return Context(source=source, source_id=source_id, url=url)
