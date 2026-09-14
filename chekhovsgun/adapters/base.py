"""The contract every source app must satisfy.

Adding a third source (Xiaohongshu, Zhihu, Pocket, a local folder…) means
implementing three things: list what the user saved, fetch an item's text, and
recognise one of the app's URLs — plus comments if the platform has them worth
reading. Nothing else in the codebase knows which app a chunk came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator

from ..config import Config
from ..models import Comment, Context, SavedItem, Segment


class AdapterError(RuntimeError):
    """Raised when an adapter cannot do its job (bad credentials, API change…)."""


class SourceAdapter(ABC):
    #: stable identifier, used as the ``source`` field on every item
    name: str = "base"
    #: human-readable name for the UI
    label: str = "Base"
    #: hostnames this adapter claims for URL recognition
    hosts: tuple[str, ...] = ()

    def __init__(self, config: Config) -> None:
        self.config = config

    # ------------------------------------------------------------- capability
    @property
    def configured(self) -> bool:
        """Whether credentials are present. Unconfigured adapters are skipped."""
        return True

    def setup_hint(self) -> str:
        """One line telling the user what is missing."""
        return ""

    # ------------------------------------------------------------------ ingest
    @abstractmethod
    def list_saved(self, *, limit: int | None = None) -> Iterable[SavedItem]:
        """Yield the user's saved/bookmarked items, newest first where possible."""

    def fetch_content(self, item: SavedItem) -> Iterator[Segment]:
        """Yield the item's transcript. Default: nothing (title/description only)."""
        return iter(())

    def fetch_comments(self, item: SavedItem) -> Iterator[Comment]:
        """Yield the item's top comment threads. Default: none.

        Comments are optional per source because not every platform has a
        discussion worth indexing — but where they exist they are the cheapest
        high-signal text this project can get.
        """
        return iter(())

    # --------------------------------------------------------------- live side
    @classmethod
    def parse_url(cls, url: str) -> str:
        """Return the source id for a URL of this app, or '' if it is not ours."""
        return ""

    @classmethod
    def context_from_url(cls, url: str) -> Context | None:
        source_id = cls.parse_url(url)
        if not source_id:
            return None
        return Context(source=cls.name, source_id=source_id, url=url)

    def close(self) -> None:  # noqa: B027 - optional hook, not every adapter has one
        """Release network resources. Adapters without any may ignore this."""
