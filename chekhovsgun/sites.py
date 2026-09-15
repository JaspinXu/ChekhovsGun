"""URL canonicalisation and site identity for everything that is not a video.

Two jobs, both of which have to happen before a page can be stored or matched:

**Canonicalisation.** The same Zhihu answer reached from the feed, from search
and from a share sheet carries three different query strings. Without stripping
them the library accumulates three copies of one answer, and the "you already
saved this" popup fires on the very page the user is looking at — the most
annoying failure this product has.

**Identification.** The live side needs a stable id for whatever page the user
is on, *including* pages from sites this project has never heard of. Known post
sites get a readable id derived from their URL shape; everything else falls back
to a hash of the canonical URL under the ``web`` source. The point is that
``relate`` degrades to "match on the page's text" instead of refusing to answer,
which is also what makes a future mobile client possible: it can POST any URL.

Video sites are deliberately absent. Their ids belong to their adapters, which
already parse them, and :func:`chekhovsgun.adapters.identify_url` consults those
first.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MEDIA_VIDEO = "video"
MEDIA_POST = "post"

#: Query parameters that never change which page you land on. Anything matching
#: one of the prefixes below is dropped too, which covers the ``utm_*`` family
#: and Bilibili's ever-growing ``spm_*`` / ``share_*`` telemetry.
_JUNK_PARAMS = frozenset(
    {
        "from", "from_source", "from_spmid", "seid", "vd_source", "unique_k",
        "referrer", "refer", "ref", "ref_src", "ref_url", "hmsr", "hmpl", "hmcu",
        "hmkw", "hmci", "bbid", "ts", "timestamp", "_trigger", "sharer_shareid",
        "sharer_sharetime", "scene", "click_id", "gclid", "fbclid", "msclkid",
        "igshid", "si", "feature", "app", "utm", "channel", "track_id",
        "xhsshare", "appuid", "apptime", "shareRedId", "utm_content",
    }
)
_JUNK_PREFIXES = ("utm_", "spm_", "share_", "from_", "hm_", "wx", "_hsenc", "_hsmi")


def _is_junk(key: str) -> bool:
    lowered = key.lower()
    return lowered in _JUNK_PARAMS or lowered.startswith(_JUNK_PREFIXES)


def canonical_url(url: str) -> str:
    """Strip tracking noise so the same page always produces the same string.

    Keeps the fragment out entirely: a ``#comment-42`` anchor is a position on a
    page, not a different page, and text-fragment deep links we generate later
    would otherwise round-trip back in as new items.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # A non-default port is part of the identity; the default one is noise.
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _is_junk(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, query, ""))


def url_digest(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------- sites
@dataclass(frozen=True, slots=True)
class Site:
    name: str
    label: str
    hosts: tuple[str, ...]
    media_kind: str
    #: Returns a stable id from the canonical URL, or '' to fall back to a hash.
    identifier: Callable[[str], str] | None = None


def _re_id(pattern: str) -> Callable[[str], str]:
    compiled = re.compile(pattern)

    def extract(path: str) -> str:
        match = compiled.search(path)
        return "-".join(g for g in match.groups() if g) if match else ""

    return extract


#: Post-shaped sites worth naming. Anything absent still works — it just lands
#: under ``web`` with a hashed id and a generic label.
SITES: tuple[Site, ...] = (
    Site("zhihu", "知乎", ("zhihu.com", "zhuanlan.zhihu.com"), MEDIA_POST,
         _re_id(r"/(?:question/(\d+)/answer/(\d+)|p/(\d+)|pin/(\d+)|answer/(\d+))")),
    Site("xiaohongshu", "小红书", ("xiaohongshu.com", "xhslink.com"), MEDIA_POST,
         _re_id(r"/(?:explore|discovery/item|item)/([0-9a-f]+)")),
    Site("weibo", "微博", ("weibo.com", "m.weibo.cn"), MEDIA_POST,
         _re_id(r"/(?:detail|status)/(\w+)|/\d+/(\w+)$")),
    Site("wechat", "微信公众号", ("mp.weixin.qq.com",), MEDIA_POST, None),
    Site("juejin", "掘金", ("juejin.cn",), MEDIA_POST, _re_id(r"/post/(\d+)")),
    Site("csdn", "CSDN", ("blog.csdn.net", "csdn.net"), MEDIA_POST,
         _re_id(r"/article/details/(\d+)")),
    Site("jianshu", "简书", ("jianshu.com",), MEDIA_POST, _re_id(r"/p/(\w+)")),
    Site("douban", "豆瓣", ("douban.com",), MEDIA_POST,
         _re_id(r"/(?:note|topic|status)/(\d+)")),
    Site("segmentfault", "SegmentFault", ("segmentfault.com",), MEDIA_POST, None),
    Site("reddit", "Reddit", ("reddit.com", "old.reddit.com"), MEDIA_POST,
         _re_id(r"/comments/(\w+)")),
    Site("x", "X / Twitter", ("twitter.com", "x.com"), MEDIA_POST,
         _re_id(r"/status/(\d+)")),
    Site("medium", "Medium", ("medium.com",), MEDIA_POST, _re_id(r"-([0-9a-f]{8,})$")),
    Site("stackoverflow", "Stack Overflow", ("stackoverflow.com", "stackexchange.com"),
         MEDIA_POST, _re_id(r"/questions/(\d+)")),
    Site("github", "GitHub", ("github.com",), MEDIA_POST, None),
    Site("substack", "Substack", ("substack.com",), MEDIA_POST, None),
)

#: The source every unrecognised page lands under.
GENERIC_SOURCE = "web"
GENERIC_LABEL = "网页 / Web"

_BY_HOST: dict[str, Site] = {host: site for site in SITES for host in site.hosts}
_BY_NAME: dict[str, Site] = {site.name: site for site in SITES}


def _match_host(host: str) -> Site | None:
    """Exact host, then parent domains, so ``m.zhihu.com`` finds ``zhihu.com``."""
    labels = host.split(".")
    for index in range(len(labels) - 1):
        candidate = ".".join(labels[index:])
        site = _BY_HOST.get(candidate)
        if site is not None:
            return site
    return None


def identify(url: str) -> tuple[str, str, str]:
    """``(source, source_id, media_kind)`` for any URL that is not a video.

    Never returns an empty source for a usable URL: an unknown site is still
    identifiable, just generically. Callers that need "is this a site we have an
    adapter for?" should ask the adapter registry, not this.
    """
    canonical = canonical_url(url)
    if not canonical:
        return "", "", MEDIA_POST
    parts = urlsplit(canonical)
    host = parts.hostname or ""
    site = _match_host(host)
    if site is None:
        return GENERIC_SOURCE, url_digest(canonical), MEDIA_POST
    source_id = ""
    if site.identifier is not None:
        source_id = site.identifier(parts.path)
    return site.name, source_id or url_digest(canonical), site.media_kind


def label_for(source: str) -> str:
    site = _BY_NAME.get(source)
    if site is not None:
        return site.label
    return GENERIC_LABEL if source == GENERIC_SOURCE else source


def is_known_post_site(url: str) -> bool:
    """Whether the URL belongs to a site in :data:`SITES` (not the generic fallback)."""
    parts = urlsplit(canonical_url(url))
    return _match_host(parts.hostname or "") is not None


__all__ = [
    "GENERIC_LABEL",
    "GENERIC_SOURCE",
    "MEDIA_POST",
    "MEDIA_VIDEO",
    "SITES",
    "Site",
    "canonical_url",
    "identify",
    "is_known_post_site",
    "label_for",
    "url_digest",
]
