"""Bilibili adapter: 收藏夹 (favourite folders), 稍后再看, and CC/AI subtitles.

Bilibili has no public API programme, so this talks to the same web endpoints
the site itself uses, authenticated with the ``SESSDATA`` cookie you can copy
out of a logged-in browser. Two practical consequences shape the code:

* most endpoints now require a **WBI signature** (see :mod:`.wbi`);
* the subtitle endpoint returns nothing at all for anonymous callers, so a
  cookie is mandatory for transcripts even on public videos.

Both AI-generated and human ("CC") subtitle tracks are accepted; human tracks
are preferred when both exist.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Iterator

from ..config import Config
from ..http import HttpClient
from ..models import SavedItem, Segment
from .base import AdapterError, SourceAdapter
from .wbi import NAV_URL, WbiSigner

log = logging.getLogger(__name__)

API = "https://api.bilibili.com"
VIDEO_URL = "https://www.bilibili.com/video/{bvid}"

_URL_PATTERNS = (
    re.compile(r"bilibili\.com/video/(BV[0-9A-Za-z]{10})"),
    re.compile(r"bilibili\.com/video/(av\d+)", re.IGNORECASE),
    re.compile(r"bilibili\.com/bangumi/play/(ep\d+|ss\d+)", re.IGNORECASE),
)

#: fav-folder媒体类型: 2=视频稿件, 12=音频, 21=视频合集
MEDIA_TYPE_VIDEO = 2


def _https(url: str) -> str:
    """Bilibili returns protocol-relative URLs (``//i0.hdslb.com/...``)."""
    if url.startswith("//"):
        return "https:" + url
    return url


class BilibiliAdapter(SourceAdapter):
    name = "bilibili"
    label = "哔哩哔哩"
    hosts = ("bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv")

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.settings = config.bilibili
        self._client = HttpClient(
            headers={
                "User-Agent": config.user_agent,
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cookie": self.settings.cookie_header(),
            },
            timeout=config.request_timeout,
            min_interval=0.4,  # Bilibili is quick to throttle; stay under ~3 req/s
        )
        self._signer = WbiSigner(self._fetch_nav)
        self._uid: str = self.settings.dedeuserid

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------- capability
    @property
    def configured(self) -> bool:
        return self.settings.configured

    def setup_hint(self) -> str:
        if self.settings.configured:
            return ""
        return (
            "Set CHEKHOVSGUN_BILIBILI_SESSDATA (and ideally CHEKHOVSGUN_BILIBILI_UID) — "
            "copy the SESSDATA cookie from a logged-in bilibili.com tab: DevTools → "
            "Application → Cookies."
        )

    # ------------------------------------------------------------------- HTTP
    def _fetch_nav(self) -> dict:
        return self._client.get_json(NAV_URL)

    def _get(self, path: str, params: dict[str, Any] | None = None, *, sign: bool = False) -> Any:
        params = dict(params or {})
        if sign:
            params = self._signer.sign(params)
        payload = self._client.get_json(f"{API}{path}", params=params)
        code = payload.get("code", 0)
        if code == 0:
            return payload.get("data")
        if code in (-101, -400, -403, 22115):
            raise AdapterError(
                f"Bilibili rejected {path} (code {code}: {payload.get('message', '')}). "
                "Your SESSDATA is probably missing or expired."
            )
        raise AdapterError(f"Bilibili {path} failed: code={code} {payload.get('message', '')}")

    # -------------------------------------------------------------- user & mid
    def uid(self) -> str:
        """Resolve the account id, from config or from ``nav``."""
        if self._uid:
            return self._uid
        data = self._fetch_nav().get("data") or {}
        mid = data.get("mid")
        if not mid:
            raise AdapterError(
                "Could not determine your Bilibili uid — set CHEKHOVSGUN_BILIBILI_UID, "
                "or check that SESSDATA is still valid."
            )
        self._uid = str(mid)
        return self._uid

    # ---------------------------------------------------------------- folders
    def list_folders(self) -> list[dict[str, Any]]:
        """Every favourite folder the user created, plus 稍后再看 as a pseudo-folder."""
        data = self._get("/x/v3/fav/folder/created/list-all", {"up_mid": self.uid()}) or {}
        folders = [
            {"id": str(entry["id"]), "title": entry.get("title", ""), "count": entry.get("media_count", 0)}
            for entry in (data.get("list") or [])
        ]
        folders.append({"id": "toview", "title": "稍后再看", "count": 0})
        return folders

    def _target_folders(self) -> list[dict[str, Any]]:
        folders = self.list_folders()
        wanted = {str(f) for f in self.settings.folders}
        if not wanted:
            return [f for f in folders if f["id"] != "toview"] + [
                f for f in folders if f["id"] == "toview"
            ]
        return [f for f in folders if f["id"] in wanted or f["title"] in wanted]

    # ----------------------------------------------------------------- listing
    def list_saved(self, *, limit: int | None = None) -> Iterable[SavedItem]:
        budget = limit
        seen: set[str] = set()
        for folder in self._target_folders():
            try:
                if folder["id"] == "toview":
                    entries = self._list_toview(budget)
                else:
                    entries = self._list_folder(folder["id"], budget)
            except AdapterError as exc:
                log.warning("skipping folder %s: %s", folder.get("title") or folder["id"], exc)
                continue

            for media in entries:
                item = self._to_item(media, folder["title"])
                if item is None or item.source_id in seen:
                    continue
                seen.add(item.source_id)
                yield item
                if budget is not None:
                    budget -= 1
                    if budget <= 0:
                        return

    def _list_folder(self, media_id: str, limit: int | None) -> Iterator[dict]:
        page = 1
        fetched = 0
        while True:
            data = self._get(
                "/x/v3/fav/resource/list",
                {
                    "media_id": media_id,
                    "pn": page,
                    "ps": 20,
                    "keyword": "",
                    "order": "mtime",
                    "type": 0,
                    "tid": 0,
                    "platform": "web",
                },
                sign=True,
            ) or {}
            medias = data.get("medias") or []
            for media in medias:
                yield media
                fetched += 1
                if limit and fetched >= limit:
                    return
            if not data.get("has_more") or not medias:
                return
            page += 1
            if page > 200:  # hard stop: 4000 items is well past any real folder
                return

    def _list_toview(self, limit: int | None) -> Iterator[dict]:
        data = self._get("/x/v2/history/toview") or {}
        for index, media in enumerate(data.get("list") or []):
            if limit and index >= limit:
                return
            yield media

    def _to_item(self, media: dict, folder: str) -> SavedItem | None:
        bvid = media.get("bvid") or media.get("bv_id") or ""
        if not bvid:
            return None
        media_type = media.get("type", MEDIA_TYPE_VIDEO)
        upper = media.get("upper") or media.get("owner") or {}
        cid = (media.get("ugc") or {}).get("first_cid") or media.get("cid") or 0
        return SavedItem(
            source=self.name,
            source_id=bvid,
            title=media.get("title", ""),
            url=VIDEO_URL.format(bvid=bvid),
            author=upper.get("name", ""),
            author_id=str(upper.get("mid", "")),
            description=media.get("intro", "") or media.get("desc", ""),
            thumbnail=_https(media.get("cover", "") or media.get("pic", "")),
            duration=int(media.get("duration", 0) or 0),
            published_at=float(media.get("pubtime", 0) or media.get("pubdate", 0) or 0),
            saved_at=float(media.get("fav_time", 0) or media.get("add_at", 0) or 0),
            folder=folder,
            lang="zh",
            tags=[],
            extra={
                "aid": media.get("id") or media.get("aid") or 0,
                "cid": cid,
                "pages": media.get("page", 1),
                "media_type": media_type,
            },
        )

    # -------------------------------------------------------------- transcript
    def _video_view(self, bvid: str) -> dict:
        return self._get("/x/web-interface/view", {"bvid": bvid}) or {}

    def fetch_content(self, item: SavedItem) -> Iterator[Segment]:
        if not self.settings.sessdata:
            raise AdapterError("Bilibili subtitles require SESSDATA")

        aid = item.extra.get("aid") or 0
        cid = item.extra.get("cid") or 0
        if not cid or not aid:
            view = self._video_view(item.source_id)
            aid = view.get("aid", aid)
            cid = view.get("cid", cid)
            if not item.description:
                item.description = view.get("desc", "")
            # Cache it so a re-sync does not pay for this round trip again.
            item.extra["aid"], item.extra["cid"] = aid, cid
        if not cid:
            raise AdapterError(f"no cid for {item.source_id}")

        player = self._get(
            "/x/player/wbi/v2",
            {"aid": aid, "cid": cid, "bvid": item.source_id},
            sign=True,
        ) or {}
        tracks = ((player.get("subtitle") or {}).get("subtitles")) or []
        if not tracks:
            raise AdapterError("no subtitle track (neither CC nor AI) for this video")

        track = self._pick_track(tracks)
        url = _https(track.get("subtitle_url") or track.get("subtitle_url_v2") or "")
        if not url:
            raise AdapterError("subtitle track has no url")

        payload = self._client.get_json(url)
        return iter(self._parse_body(payload))

    @staticmethod
    def _pick_track(tracks: list[dict]) -> dict:
        """Human Chinese > human anything > AI Chinese > AI anything."""

        def rank(track: dict) -> tuple[int, int]:
            lan = str(track.get("lan", "")).lower()
            is_ai = int(track.get("ai_status", 0) or 0) != 0 or lan.startswith("ai-")
            chinese = 0 if lan.startswith(("zh", "ai-zh")) else 1
            return (1 if is_ai else 0, chinese)

        return min(tracks, key=rank)

    @staticmethod
    def _parse_body(payload: dict) -> list[Segment]:
        segments: list[Segment] = []
        for row in (payload or {}).get("body", []):
            content = (row.get("content") or "").strip()
            if not content:
                continue
            segments.append(
                Segment(
                    text=content,
                    start=float(row.get("from", 0.0) or 0.0),
                    end=float(row.get("to", 0.0) or 0.0),
                )
            )
        return segments

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
