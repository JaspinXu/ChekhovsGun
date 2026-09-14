"""Bilibili WBI request signing.

Since 2023 Bilibili requires a ``w_rid`` signature on most web API endpoints.
The scheme: take two rotating keys out of the ``nav`` endpoint, interleave them
through a fixed 64-entry permutation to get a 32-character "mixin key", then
MD5 the sorted query string concatenated with it. The keys rotate daily, so the
client caches them for an hour rather than per request.

Reference implementation follows the community-documented algorithm; see
``docs/bilibili.md`` for the endpoints that need it.
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from typing import Any, Callable

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

# Bilibili strips these characters from parameter values before signing;
# signing an unstripped value produces a signature the server rejects.
_FORBIDDEN = "!'()*"

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
KEY_TTL = 3600.0


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_params(params: dict[str, Any], key: str, *, timestamp: float | None = None) -> dict[str, Any]:
    """Return ``params`` plus ``wts`` and ``w_rid``."""
    signed: dict[str, Any] = dict(params)
    signed["wts"] = int(timestamp if timestamp is not None else time.time())
    cleaned = {
        name: "".join(ch for ch in str(value) if ch not in _FORBIDDEN)
        for name, value in sorted(signed.items())
    }
    query = urllib.parse.urlencode(cleaned)
    signed["w_rid"] = hashlib.md5((query + key).encode("utf-8")).hexdigest()
    return signed


def keys_from_nav(payload: dict) -> tuple[str, str]:
    """Pull ``img_key``/``sub_key`` out of a ``nav`` response.

    ``nav`` answers with code -101 (not logged in) for anonymous callers but
    still includes ``wbi_img``, so signing works without a session.
    """
    wbi = (payload or {}).get("data", {}).get("wbi_img", {})
    img_url = wbi.get("img_url", "")
    sub_url = wbi.get("sub_url", "")
    if not img_url or not sub_url:
        raise ValueError("nav response did not contain wbi_img keys")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


class WbiSigner:
    """Caches the daily mixin key and signs parameter dicts."""

    def __init__(self, fetch_nav: Callable[[], dict], ttl: float = KEY_TTL) -> None:
        self._fetch_nav = fetch_nav
        self._ttl = ttl
        self._key = ""
        self._fetched_at = 0.0

    def key(self, *, force: bool = False) -> str:
        if force or not self._key or (time.time() - self._fetched_at) > self._ttl:
            img_key, sub_key = keys_from_nav(self._fetch_nav())
            self._key = mixin_key(img_key, sub_key)
            self._fetched_at = time.time()
        return self._key

    def sign(self, params: dict[str, Any]) -> dict[str, Any]:
        return sign_params(params, self.key())
