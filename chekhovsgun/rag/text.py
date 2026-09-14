"""Tokenisation and normalisation that behave sensibly for Chinese *and* English.

Chinese has no spaces, so a whitespace tokenizer collapses a whole sentence into
one token and destroys lexical matching. We therefore emit CJK **character
bigrams** (the standard cheap stand-in for a word segmenter) alongside ordinary
latin/number word tokens. The same function feeds both the hashed embedder and
the BM25 index, so dense and lexical retrieval see the same view of the text.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x3040, 0x30FF),  # kana, close enough to share the bigram treatment
    (0xAC00, 0xD7AF),  # hangul
)

_LATIN_TOKEN = re.compile(r"[a-z0-9][a-z0-9'_+#.\-]*", re.IGNORECASE)
_SPLITTABLE = re.compile(r"[-_.]+")
_WS = re.compile(r"\s+")

# English function words: no retrieval signal, present in every other title.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "it", "this", "that", "with", "as", "at", "by", "be", "from", "you", "your",
    "we", "i", "how", "what", "why", "was", "were", "will", "can", "do", "does",
    "my", "me", "our", "they", "them", "he", "she", "its", "but", "so", "if",
    "not", "no", "yes", "up", "out", "about", "into", "than", "then", "there",
    "here", "when", "where", "which", "who", "all", "any", "some", "just",
    "very", "more", "most", "one", "two", "get", "got", "make", "made", "let",
}

# Chinese has no spaces, so its function words have to be handled a character at
# a time. Any *bigram* built from two of these — 还是, 就是, 这个, 怎么 — is a
# function word too, and must not count as topical evidence. Without this, a
# query about cooking "matches" a database talk because both contain 还是.
_CJK_FUNCTION_CHARS = set(
    "的了是在和就都而及与也很到我你他她它们这那个可以什么怎样还有要会能说去来做"
    "得着过被把让给对从向为于不没无上下中里外前后之其此但因所然则又再才只更最太"
    "些种时候用好大小多少等吧呢吗啊呀哦嗯如果或者且并虽且比如及至由该们哪谁咱您"
)
_STOPWORDS |= _CJK_FUNCTION_CHARS

# Video-title genre words. These are not function words — they are perfectly
# good nouns — but on Chinese video platforms they appear in a large fraction of
# every title regardless of subject, so they behave like boilerplate. IDF would
# eventually learn this on a large library; excluding them explicitly means a
# freshly seeded index does not rank "Redis 持久化原理" against a query about
# vector search purely because both say 原理.
_GENRE_WORDS = {
    "原理", "详解", "讲解", "精讲", "精读", "解析", "教程", "入门", "实战", "实测",
    "笔记", "分享", "总结", "干货", "科普", "揭秘", "指南", "手册", "系列", "合集",
    "全集", "完整", "版本", "最新", "推荐", "盘点", "对比", "测评", "体验", "记录",
    "过程", "全程", "手把手", "保姆级", "从零", "零基础", "一文", "看懂", "学会",
    # Generic nouns that carry no subject on their own.
    "做法", "方法", "方式", "情况", "东西", "地方", "内容", "问题", "区别", "意思",
}
_STOPWORDS |= _GENRE_WORDS


def is_function_token(token: str) -> bool:
    """True for tokens that carry no topical signal in either language."""
    if token in _STOPWORDS:
        return True
    return (
        len(token) == 2
        and all(is_cjk(ch) for ch in token)
        and all(ch in _CJK_FUNCTION_CHARS for ch in token)
    )


def script_of(text: str) -> str:
    """'cjk' | 'latin' | 'mixed' — which writing system dominates this text.

    Coverage scoring needs this: a Chinese query token can never appear in an
    English passage, so counting it against that passage would make every
    cross-language match look irrelevant, which is precisely the case where the
    user most benefits from being reminded of what they saved.
    """
    sample = text[:240]  # the opening of a passage settles its script
    cjk = sum(1 for ch in sample if is_cjk(ch))
    latin = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
    total = cjk + latin
    if total < 4:
        return "mixed"
    if cjk / total > 0.75:
        return "cjk"
    if latin / total > 0.75:
        return "latin"
    return "mixed"


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def normalize(text: str) -> str:
    """NFKC-fold, lowercase and squeeze whitespace.

    NFKC matters for Bilibili titles, which are full of full-width punctuation
    and full-width latin letters that would otherwise not match their ASCII form.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _WS.sub(" ", text).strip().lower()


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Split into retrieval tokens: latin words + CJK unigrams and bigrams."""
    text = normalize(text)
    if not text:
        return []

    tokens: list[str] = []
    cjk_run: list[str] = []

    def flush_cjk() -> None:
        if not cjk_run:
            return
        run = cjk_run.copy()
        cjk_run.clear()
        tokens.extend(run)
        tokens.extend(run[i] + run[i + 1] for i in range(len(run) - 1))

    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if is_cjk(ch):
            cjk_run.append(ch)
            i += 1
            continue
        flush_cjk()
        match = _LATIN_TOKEN.match(text, i)
        if match:
            word = match.group(0).strip("-_.")
            if word:
                tokens.append(word)
                # "self-attention" must also match a document that only says
                # "attention", and "B-Tree" one that says "btree" or "b tree".
                parts = [p for p in _SPLITTABLE.split(word) if p]
                if len(parts) > 1:
                    tokens.extend(p for p in parts if len(p) > 1)
                    tokens.append("".join(parts))
            i = match.end()
        else:
            i += 1
    flush_cjk()

    if drop_stopwords:
        tokens = [t for t in tokens if not is_function_token(t)]
    return tokens


@lru_cache(maxsize=4096)
def tokenize_cached(text: str) -> tuple[str, ...]:
    return tuple(tokenize(text))


def sentences(text: str) -> list[str]:
    """Split on sentence-ish boundaries, keeping the terminator."""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;\n])\s*|(?<=[.])\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def snippet(text: str, query: str, width: int = 160) -> str:
    """A short excerpt centred on the first query token that appears."""
    if not text:
        return ""
    if len(text) <= width:
        return text
    lowered = normalize(text)
    for token in tokenize(query):
        if len(token) < 2:
            continue
        pos = lowered.find(token)
        if pos >= 0:
            start = max(0, pos - width // 3)
            end = min(len(text), start + width)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(text) else ""
            return f"{prefix}{text[start:end].strip()}{suffix}"
    return text[:width].strip() + "…"
