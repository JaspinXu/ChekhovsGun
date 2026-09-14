"""Turn retrieval results into one short, honest paragraph.

The popup has about three seconds of the user's attention, so the generated
text must answer exactly one question: *what did I already save that relates to
this, and what would I get from going back to it?*

The LLM is strictly optional. With no API key the explainer still produces a
useful card by quoting the best-matching transcript passage verbatim — an
extractive answer that can never hallucinate. That fallback is also what runs
when the API call fails or times out, so the extension never shows a spinner
that never resolves.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..config import LLMConfig
from ..models import Context, ItemHit
from ..rag.text import is_cjk, snippet

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ChekhovsGun, a study companion built into a video feed.
The user is scrolling and has just landed on a video. From their own saved library
you have been given the passages that best match it.

Write a short note (2-3 sentences, under 90 words) that:
1. names the concrete connection between what they are watching and what they saved;
2. says what the saved item adds that the current video does not;
3. ends with one specific thing worth going back for.

Rules: rely only on the passages provided; never invent facts, numbers or titles.
If the connection is weak, say so plainly instead of stretching it.
Do not greet, do not use headings, do not use bullet points. Reply in {language}."""

_FALLBACK_ZH = "你收藏过 {count} 个相关内容，最接近的是《{title}》{author_part}。其中提到：{quote}"
_FALLBACK_EN = (
    "You already saved {count} related item(s); the closest is “{title}”{author_part}. "
    "From it: {quote}"
)


def detect_language(*texts: str) -> str:
    """'zh' if the material is mostly Chinese, else 'en'."""
    sample = " ".join(t for t in texts if t)[:600]
    if not sample:
        return "en"
    cjk = sum(1 for ch in sample if is_cjk(ch))
    letters = sum(1 for ch in sample if ch.isalpha())
    return "zh" if letters and cjk / max(letters, 1) > 0.2 else "en"


@dataclass
class Explanation:
    text: str
    generated: bool = False
    model: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "generated": self.generated,
            "model": self.model,
            "sources": self.sources,
        }


def _best_quote(hit: ItemHit, query: str, limit: int = 140) -> str:
    for chunk in hit.chunks:
        if chunk.kind == "transcript" and len(chunk.text) > 24:
            return snippet(chunk.text, query, limit)
    for chunk in hit.chunks:
        if len(chunk.text) > 16:
            return snippet(chunk.text, query, limit)
    return hit.item.title


def _format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


class Explainer:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    # ------------------------------------------------------------- public API
    def explain(self, context: Context, hits: list[ItemHit]) -> Explanation:
        if not hits:
            return Explanation(text="")
        language = self._language(context, hits)
        if self.config.usable:
            try:
                text = self._generate(context, hits, language)
                if text:
                    return Explanation(
                        text=text,
                        generated=True,
                        model=self.config.model,
                        sources=[hit.item.id for hit in hits],
                    )
            except Exception as exc:
                log.warning("LLM explanation failed, using extractive fallback: %s", exc)
        return self.fallback(context, hits, language)

    def fallback(self, context: Context, hits: list[ItemHit], language: str = "") -> Explanation:
        """Extractive, zero-dependency, never wrong about what you saved."""
        language = language or self._language(context, hits)
        best = hits[0]
        author_part = ""
        if best.item.author:
            author_part = f"（{best.item.author}）" if language == "zh" else f" by {best.item.author}"
        template = _FALLBACK_ZH if language == "zh" else _FALLBACK_EN
        return Explanation(
            text=template.format(
                count=len(hits),
                title=best.item.title,
                author_part=author_part,
                quote=_best_quote(best, context.as_query()),
            ),
            generated=False,
            sources=[hit.item.id for hit in hits],
        )

    # ------------------------------------------------------------- generation
    def _language(self, context: Context, hits: list[ItemHit]) -> str:
        if self.config.language in {"zh", "en"}:
            return self.config.language
        return detect_language(context.title, *(hit.item.title for hit in hits[:3]))

    def _build_prompt(self, context: Context, hits: list[ItemHit]) -> str:
        lines = [
            "### 当前正在观看 / Now watching",
            f"平台 source: {context.source or 'unknown'}",
            f"标题 title: {context.title}",
        ]
        if context.author:
            lines.append(f"作者 author: {context.author}")
        if context.description:
            lines.append(f"简介 description: {context.description[:400]}")

        lines.append("")
        lines.append("### 用户收藏过的相关内容 / Saved items that matched")
        for index, hit in enumerate(hits[:4], start=1):
            lines.append(f"[{index}] {hit.item.title} — {hit.item.author or 'unknown'}")
            lines.append(f"    saved in: {hit.item.folder or 'n/a'} · relevance {hit.score:.2f}")
            for chunk in hit.chunks[:2]:
                stamp = f"@{_format_timestamp(chunk.start)} " if chunk.start else ""
                lines.append(f"    {stamp}{chunk.text[:320]}")
        return "\n".join(lines)

    def _generate(self, context: Context, hits: list[ItemHit], language: str) -> str:
        import httpx

        base = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        language_name = "Chinese (简体中文)" if language == "zh" else "English"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(language=language_name)},
                {"role": "user", "content": self._build_prompt(context, hits)},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content", "")
        # Some models still open with a heading despite the instruction.
        return re.sub(r"^#+\s*", "", content.strip()).strip()
