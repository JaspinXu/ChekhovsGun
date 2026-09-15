"""Pull the readable body out of an HTML page.

Needed in two places that both boil down to "we have a URL and nothing else":
the ``扫我的收藏夹`` scan, which collects hundreds of links far faster than it
could collect their bodies, and ``chekhovsgun import urls.txt``, which until now
stored a title and left the item unretrievable.

This is deliberately a heuristic and not a dependency. A full Readability port
would be a large third-party surface for a job that, on the article-shaped pages
people actually bookmark, is won by one rule: the element carrying the most text
that is *not* inside links is the article. Navigation, sidebars, related-post
rails and comment threads all fail that test, because they are mostly anchors.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

log = logging.getLogger(__name__)

#: Never contributes to the body, whatever it contains.
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "svg", "canvas", "template", "iframe",
     "nav", "header", "footer", "aside", "form", "button", "select", "textarea",
     "figure", "figcaption", "picture", "video", "audio"}
)
#: Tags that end a line of prose when the text is flattened.
_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "main", "li", "tr", "br", "hr", "pre",
     "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "td"}
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
     "meta", "param", "source", "track", "wbr"}
)

#: Class/id substrings that mark a container as the thing we want, or as chrome.
#: Covers the Chinese sites this project targets as well as the usual CMS names.
_GOOD = re.compile(
    r"article|content|post|entry|body|answer|richtext|rich_media|note-?text|"
    r"markdown|question|story|main",
    re.I,
)
_BAD = re.compile(
    r"comment|sidebar|footer|header|nav|menu|banner|promo|advert|\bads?\b|"
    r"related|recommend|share|social|subscribe|newsletter|popup|modal|toolbar|"
    r"breadcrumb|pagination|tag-?list|author-?card",
    re.I,
)

#: Below this *weighted* length, whatever we found is chrome rather than an
#: article, and the caller is better off with the title alone than with a menu
#: indexed as prose.
MIN_BODY_CHARS = 180

_CJK = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]"
)


def weighted_len(text: str) -> int:
    """Length in units of "about as much meaning as one English character".

    A CJK character is a morpheme; a Latin character is a letter. Counting them
    the same way means every threshold tuned on English prose rejects Chinese
    articles several paragraphs long — which is most of what this project
    indexes. 2.5 is roughly the ratio of characters needed to say the same
    thing in the two scripts.
    """
    cjk = len(_CJK.findall(text))
    return int(len(text) - cjk + cjk * 2.5)


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: str = ""
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    #: (text, is_link) pairs owned directly by this node.
    texts: list[tuple[str, bool]] = field(default_factory=list)


@dataclass(slots=True)
class Readable:
    """What a page turned out to contain."""

    title: str = ""
    author: str = ""
    text: str = ""
    #: Why extraction produced what it did — surfaced in job progress, not UI.
    note: str = ""

    def __bool__(self) -> bool:
        return weighted_len(self.text) >= MIN_BODY_CHARS


class _Parser(HTMLParser):
    """Builds a shallow tree and records which text sits inside an anchor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("__root__")
        self.node = self.root
        #: <title> carries the site name too ("… - 知乎"); og:title is the bare
        #: headline, so it wins when the page bothers to publish one.
        self.doc_title = ""
        self.og_title = ""
        self.author = ""
        self._skip_depth = 0
        self._link_depth = 0
        self._in_title = False

    # -- structure ---------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            if tag == "br":
                self.node.texts.append(("\n", False))
            if tag == "meta":
                self._read_meta(dict(attrs))
            return
        if self._skip_depth or tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._link_depth += 1
        blob = " ".join(
            value for key, value in attrs if key in ("class", "id") and value
        )
        child = _Node(tag, attrs=blob, parent=self.node)
        self.node.children.append(child)
        self.node = child

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._link_depth:
            self._link_depth -= 1
        # Walk up to the nearest matching ancestor. Real pages leave tags
        # unclosed constantly; anchoring on the tag name keeps one stray <p>
        # from swallowing the rest of the document.
        node: _Node | None = self.node
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.node = node.parent

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        if self._in_title and not self.doc_title:
            self.doc_title = data.strip()
            return
        self.node.texts.append((data, self._link_depth > 0))

    def _read_meta(self, attrs: dict[str, str | None]) -> None:
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        value = (attrs.get("content") or "").strip()
        if not value:
            return
        if key in ("og:title", "twitter:title") and not self.og_title:
            self.og_title = value
        elif key in ("author", "article:author", "og:article:author") and not self.author:
            self.author = value


def _measure(node: _Node, memo: dict[int, tuple[int, int]]) -> tuple[int, int]:
    """``(text_chars, link_chars)`` for a node and everything beneath it."""
    cached = memo.get(id(node))
    if cached is not None:
        return cached
    total = links = 0
    for text, is_link in node.texts:
        length = weighted_len(text.strip())
        total += length
        if is_link:
            links += length
    for child in node.children:
        child_total, child_links = _measure(child, memo)
        total += child_total
        links += child_links
    memo[id(node)] = (total, links)
    return total, links


def _score(node: _Node, memo: dict[int, tuple[int, int]]) -> float:
    total, links = _measure(node, memo)
    if total < 80:
        return 0.0
    # Link text counts double against the node: a nav block is nearly all
    # anchors, an article is nearly none, and nothing else separates them
    # so cheaply across sites with completely unrelated markup.
    score = float(total - 2 * links)
    if node.tag in ("article", "main"):
        score *= 1.6
    if node.attrs:
        if _GOOD.search(node.attrs):
            score *= 1.4
        if _BAD.search(node.attrs):
            score *= 0.25
    return score


def _flatten(node: _Node, out: list[str]) -> None:
    for text, _ in node.texts:
        out.append(text)
    for child in node.children:
        if child.tag in _BLOCK_TAGS:
            out.append("\n")
        _flatten(child, out)
        if child.tag in _BLOCK_TAGS:
            out.append("\n")


def _tidy(raw: str) -> str:
    lines = [" ".join(line.split()) for line in unescape(raw).split("\n")]
    kept = [line for line in lines if line]
    # Collapse the runs of one- and two-character fragments that survive from
    # icon labels and button text; they are noise for retrieval either way.
    return "\n".join(line for line in kept if len(line) > 1)


def extract(html: str, *, url: str = "") -> Readable:
    """Best-effort title, author and body text for one HTML document."""
    parser = _Parser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # malformed markup is normal, not exceptional
        log.debug("html parse failed for %s: %s", url or "<string>", exc)

    memo: dict[int, tuple[int, int]] = {}
    best: _Node | None = None
    best_score = 0.0
    stack = [parser.root]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        score = _score(node, memo)
        if score > best_score:
            best, best_score = node, score

    parts: list[str] = []
    if best is not None:
        _flatten(best, parts)
    text = _tidy("".join(parts))
    note = "" if weighted_len(text) >= MIN_BODY_CHARS else "no article-shaped block found"
    return Readable(
        title=parser.og_title or parser.doc_title,
        author=parser.author,
        text=text,
        note=note,
    )


def fetch_readable(url: str, *, timeout: float = 20.0) -> Readable:
    """Download a page and extract it. Raises nothing — failure is an empty body.

    Login walls, bot checks and JavaScript-only pages are the normal outcome for
    a meaningful share of any real bookmark folder, so a failure here has to
    leave the item in the library with its title rather than abort the scan.
    """
    from .http import HttpClient

    client = HttpClient(
        headers={
            # Sites serve a stub to clients that do not look like browsers, and
            # a stub extracts to nothing.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=timeout,
        max_retries=1,
    )
    try:
        response = client.get(url)
        if response.status_code >= 400:
            return Readable(note=f"HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and content_type:
            return Readable(note=f"not html ({content_type.split(';')[0]})")
        return extract(response.text, url=url)
    except Exception as exc:
        log.debug("fetch failed for %s: %s", url, exc)
        return Readable(note=str(exc)[:160])
    finally:
        client.close()


__all__ = ["MIN_BODY_CHARS", "Readable", "extract", "fetch_readable", "weighted_len"]
