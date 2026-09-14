"""YouTube adapter: playlists (including Liked / Watch Later) + captions.

Two access paths, because YouTube splits them:

* **YouTube Data API v3** with an API key reads any public or unlisted playlist.
  Personal collections — Liked videos (``LL``) and Watch Later (``WL``) — are
  private to the account, so those need an OAuth access token instead.
* **Captions** are not exposed by the Data API without OAuth *and* channel
  ownership, so we read them the way the player does: pull ``captionTracks``
  out of the watch page's ``ytInitialPlayerResponse`` and fetch the track as
  JSON. If ``youtube-transcript-api`` is installed we prefer it, since it
  tracks YouTube's changes for us.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from ..config import Config
from ..http import HttpClient
from ..models import Comment, SavedItem, Segment
from .base import AdapterError, SourceAdapter

log = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/youtube/v3"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

_VIDEO_ID = r"[A-Za-z0-9_-]{11}"
_URL_PATTERNS = (
    re.compile(rf"(?:youtube\.com|youtube-nocookie\.com)/watch\?(?:[^#]*&)?v=({_VIDEO_ID})"),
    re.compile(rf"youtu\.be/({_VIDEO_ID})"),
    re.compile(rf"youtube\.com/(?:shorts|embed|v|live)/({_VIDEO_ID})"),
)
_ISO_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)
_PLAYER_RESPONSE = re.compile(r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var|</script>)", re.S)


def parse_iso_duration(value: str) -> int:
    """``PT1H2M3S`` → seconds."""
    if not value:
        return 0
    match = _ISO_DURATION.fullmatch(value.strip())
    if not match:
        return 0
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def parse_rfc3339(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        ).timestamp()
    except ValueError:
        return 0.0


def _extract_json_object(text: str, start: int) -> str:
    """Read one balanced ``{...}`` starting at ``start``, ignoring braces in strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unbalanced JSON object")


class YouTubeAdapter(SourceAdapter):
    name = "youtube"
    label = "YouTube"
    hosts = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com")

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.settings = config.youtube
        self._api = HttpClient(
            headers={"User-Agent": config.user_agent, "Accept": "application/json"},
            timeout=config.request_timeout,
            min_interval=0.05,
        )
        self._web = HttpClient(
            headers={
                "User-Agent": config.user_agent,
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            },
            timeout=config.request_timeout,
            min_interval=0.35,  # captions come from the public site: be gentle
        )

    def close(self) -> None:
        self._api.close()
        self._web.close()

    # ------------------------------------------------------------- capability
    @property
    def configured(self) -> bool:
        return self.settings.configured

    def setup_hint(self) -> str:
        if self.settings.configured:
            return ""
        return (
            "Set CHEKHOVSGUN_YOUTUBE_API_KEY (Google Cloud → YouTube Data API v3) for public "
            "playlists, or CHEKHOVSGUN_YOUTUBE_OAUTH_TOKEN to read Liked (LL) / Watch Later (WL)."
        )

    # ------------------------------------------------------------------- HTTP
    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self.settings.oauth_token:
            headers["Authorization"] = f"Bearer {self.settings.oauth_token}"
        elif self.settings.api_key:
            params["key"] = self.settings.api_key
        else:
            raise AdapterError("YouTube is not configured: " + self.setup_hint())
        return headers, params

    def _api_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers, auth_params = self._auth()
        merged = {**params, **auth_params}
        response = self._api.get(f"{API_ROOT}/{path}", params=merged, headers=headers)
        if response.status_code == 403:
            raise AdapterError(
                "YouTube API refused the request (quota exhausted, or this playlist is "
                f"private and needs an OAuth token): {response.text[:200]}"
            )
        if response.status_code == 404:
            raise AdapterError(f"YouTube API: not found — {params.get('playlistId', path)}")
        if response.status_code >= 400:
            raise AdapterError(f"YouTube API {response.status_code}: {response.text[:200]}")
        return response.json()

    def _paginate(self, path: str, params: dict[str, Any], limit: int | None) -> Iterator[dict]:
        page_token = ""
        fetched = 0
        while True:
            page_params = dict(params)
            page_params["maxResults"] = min(50, limit - fetched) if limit else 50
            if page_token:
                page_params["pageToken"] = page_token
            payload = self._api_get(path, page_params)
            for entry in payload.get("items", []):
                yield entry
                fetched += 1
                if limit and fetched >= limit:
                    return
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                return

    # ----------------------------------------------------------------- listing
    def target_playlists(self) -> list[str]:
        """Which playlists to ingest."""
        if self.settings.playlists:
            return list(self.settings.playlists)
        if self.settings.oauth_token:
            # LL = Liked videos, WL = Watch Later. These *are* the YouTube
            # equivalent of "my favourites".
            return ["LL", "WL"]
        raise AdapterError(
            "No playlist configured. Set CHEKHOVSGUN_YOUTUBE_PLAYLISTS=PLxxxx,PLyyyy "
            "(a playlist id is the PL... part of its URL), or provide an OAuth token to "
            "read your Liked videos automatically."
        )

    def list_saved(self, *, limit: int | None = None) -> Iterable[SavedItem]:
        playlists = self.target_playlists()
        budget = limit
        seen: set[str] = set()
        for playlist_id in playlists:
            try:
                entries = list(
                    self._paginate(
                        "playlistItems",
                        {"part": "snippet,contentDetails,status", "playlistId": playlist_id},
                        budget,
                    )
                )
            except AdapterError as exc:
                # One unreadable playlist (WL is often inaccessible) must not
                # abort the whole sync.
                log.warning("skipping playlist %s: %s", playlist_id, exc)
                continue

            video_ids: list[str] = []
            saved_at: dict[str, float] = {}
            for entry in entries:
                snippet = entry.get("snippet", {})
                details = entry.get("contentDetails", {})
                video_id = details.get("videoId") or snippet.get("resourceId", {}).get("videoId")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)
                video_ids.append(video_id)
                saved_at[video_id] = parse_rfc3339(
                    snippet.get("publishedAt", "") or details.get("videoPublishedAt", "")
                )

            for item in self._hydrate(video_ids, playlist_id, saved_at):
                yield item
                if budget is not None:
                    budget -= 1
                    if budget <= 0:
                        return

    def _hydrate(
        self, video_ids: list[str], folder: str, saved_at: dict[str, float]
    ) -> Iterator[SavedItem]:
        """Batch ``videos.list`` — 50 ids per call instead of one call per video."""
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            payload = self._api_get(
                "videos",
                {"part": "snippet,contentDetails,statistics", "id": ",".join(batch)},
            )
            for video in payload.get("items", []):
                snippet = video.get("snippet", {})
                thumbnails = snippet.get("thumbnails", {})
                thumbnail = (
                    thumbnails.get("medium")
                    or thumbnails.get("high")
                    or thumbnails.get("default")
                    or {}
                ).get("url", "")
                video_id = video.get("id", "")
                yield SavedItem(
                    source=self.name,
                    source_id=video_id,
                    title=snippet.get("title", ""),
                    url=WATCH_URL.format(video_id=video_id),
                    author=snippet.get("channelTitle", ""),
                    author_id=snippet.get("channelId", ""),
                    description=snippet.get("description", ""),
                    thumbnail=thumbnail,
                    duration=parse_iso_duration(video.get("contentDetails", {}).get("duration", "")),
                    published_at=parse_rfc3339(snippet.get("publishedAt", "")),
                    saved_at=saved_at.get(video_id, 0.0),
                    folder=folder,
                    lang=snippet.get("defaultAudioLanguage", "") or snippet.get("defaultLanguage", ""),
                    tags=list(snippet.get("tags", []) or [])[:25],
                    extra={"views": video.get("statistics", {}).get("viewCount", "")},
                )

    # -------------------------------------------------------------- transcript
    def fetch_content(self, item: SavedItem) -> Iterator[Segment]:
        segments = self._transcript_via_library(item.source_id)
        if segments is None:
            segments = self._transcript_via_player(item.source_id)
        return iter(segments or [])

    def _preferred_langs(self) -> list[str]:
        return list(self.settings.transcript_langs or ["en"])

    def _transcript_via_library(self, video_id: str) -> list[Segment] | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        except ImportError:
            return None
        try:
            # The library's API changed shape across majors; support both.
            if hasattr(YouTubeTranscriptApi, "list_transcripts"):
                listing = YouTubeTranscriptApi.list_transcripts(video_id)
                try:
                    transcript = listing.find_transcript(self._preferred_langs())
                except Exception:
                    transcript = next(iter(listing))
                rows = transcript.fetch()
            else:  # >= 1.0 instance API
                fetched = YouTubeTranscriptApi().fetch(video_id, languages=self._preferred_langs())
                rows = getattr(fetched, "snippets", fetched)
            out: list[Segment] = []
            for row in rows:
                text = getattr(row, "text", None) or (row.get("text") if isinstance(row, dict) else "")
                start = getattr(row, "start", None)
                if start is None and isinstance(row, dict):
                    start = row.get("start", 0.0)
                duration = getattr(row, "duration", None)
                if duration is None and isinstance(row, dict):
                    duration = row.get("duration", 0.0)
                start = float(start or 0.0)
                out.append(Segment(text=str(text or ""), start=start, end=start + float(duration or 0.0)))
            return out or None
        except Exception as exc:
            log.debug("youtube-transcript-api failed for %s: %s", video_id, exc)
            return None

    def _transcript_via_player(self, video_id: str) -> list[Segment]:
        """Read caption tracks out of the watch page, the way the player does."""
        response = self._web.get(WATCH_URL.format(video_id=video_id))
        if response.status_code >= 400:
            raise AdapterError(f"watch page {response.status_code} for {video_id}")
        html = response.text

        marker = "ytInitialPlayerResponse"
        position = html.find(marker)
        if position < 0:
            raise AdapterError("no player response on the watch page (age-gated or blocked?)")
        brace = html.find("{", position)
        try:
            player = json.loads(_extract_json_object(html, brace))
        except Exception as exc:
            raise AdapterError(f"could not parse player response: {exc}") from exc

        tracks = (
            player.get("captions", {})
            .get("playerCaptionsTracklistRenderer", {})
            .get("captionTracks", [])
        )
        if not tracks:
            raise AdapterError("this video has no caption tracks")

        track = self._pick_track(tracks)
        base_url = track.get("baseUrl", "")
        if not base_url:
            raise AdapterError("caption track has no url")
        separator = "&" if "?" in base_url else "?"
        payload = self._web.get(f"{base_url}{separator}fmt=json3")
        if payload.status_code >= 400:
            raise AdapterError(f"caption fetch {payload.status_code}")
        return self._parse_json3(payload.json())

    def _pick_track(self, tracks: list[dict]) -> dict:
        """Prefer a human track in a preferred language; fall back to anything."""
        preferred = [lang.lower() for lang in self._preferred_langs()]

        def rank(track: dict) -> tuple[int, int]:
            code = str(track.get("languageCode", "")).lower()
            try:
                language_rank = next(
                    i for i, want in enumerate(preferred)
                    if code == want or code.startswith(want.split("-")[0])
                )
            except StopIteration:
                language_rank = len(preferred)
            # kind == 'asr' marks auto-generated captions: usable, but worse.
            return (language_rank, 1 if track.get("kind") == "asr" else 0)

        return min(tracks, key=rank)

    @staticmethod
    def _parse_json3(payload: dict) -> list[Segment]:
        segments: list[Segment] = []
        for event in payload.get("events", []):
            runs = event.get("segs")
            if not runs:
                continue
            text = "".join(run.get("utf8", "") for run in runs).strip()
            if not text or text == "\n":
                continue
            start = float(event.get("tStartMs", 0)) / 1000.0
            duration = float(event.get("dDurationMs", 0)) / 1000.0
            segments.append(Segment(text=text, start=start, end=start + duration))
        return segments

    # ---------------------------------------------------------------- comments
    def fetch_comments(self, item: SavedItem) -> Iterator[Comment]:
        """Top comment threads via ``commentThreads.list``.

        ``order=relevance`` is YouTube's own "top comments" ranking, and the
        call costs one quota unit — cheap enough to run for every saved video.
        Comments disabled on a video returns 403, which is normal, not an error.
        """
        settings = self.config.comments
        if not settings.enabled:
            return iter(())
        try:
            payload = self._api_get(
                "commentThreads",
                {
                    "part": "snippet,replies",
                    "videoId": item.source_id,
                    "order": "relevance",
                    "maxResults": min(50, max(settings.max_per_item * 2, 20)),
                    "textFormat": "plainText",
                },
            )
        except AdapterError as exc:
            log.debug("comments unavailable for %s: %s", item.source_id, exc)
            return iter(())
        return iter(self._parse_comment_threads(payload.get("items", []), settings))

    @staticmethod
    def _parse_comment_threads(threads: list[dict], settings) -> list[Comment]:
        out: list[Comment] = []
        for thread in threads:
            top = (
                (thread.get("snippet") or {}).get("topLevelComment", {}).get("snippet", {})
            )
            text = (top.get("textOriginal") or top.get("textDisplay") or "").strip()
            likes = int(top.get("likeCount", 0) or 0)
            if len(text) < settings.min_chars or likes < settings.min_likes:
                continue
            sub: list[str] = []
            if settings.include_replies:
                # See the note in the Bilibili adapter: replies are corroboration
                # and are legitimately terse, so they clear a lower bar.
                reply_floor = max(6, settings.min_chars // 2)
                for child in ((thread.get("replies") or {}).get("comments") or [])[
                    : settings.max_replies_per_thread
                ]:
                    snippet = child.get("snippet") or {}
                    reply = (snippet.get("textOriginal") or snippet.get("textDisplay") or "").strip()
                    if len(reply) >= reply_floor:
                        sub.append(reply)
            out.append(
                Comment(
                    text=text,
                    author=top.get("authorDisplayName", ""),
                    likes=likes,
                    replies=sub,
                )
            )
        out.sort(key=lambda c: -c.likes)
        return out[: settings.max_per_item]

    # --------------------------------------------------------------- URL match
    @classmethod
    def parse_url(cls, url: str) -> str:
        if not url:
            return ""
        for pattern in _URL_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return ""
