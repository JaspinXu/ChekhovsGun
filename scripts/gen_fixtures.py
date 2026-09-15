#!/usr/bin/env python
"""Regenerate the parity fixtures the JavaScript engine is tested against.

``extension/core/`` is a port of the Python retrieval code. The port is held to
the original by replaying these fixtures, which are produced by calling the real
Python functions — so a change on either side that drifts shows up as a failing
JavaScript test rather than as quietly worse retrieval.

What is pinned here is everything that must agree *exactly*:

* tokenizer output, because dense and lexical retrieval both consume it;
* chunk boundaries and chunk ids, because an id mismatch duplicates every chunk;
* URL identity, because an item id is ``source:source_id`` and a disagreement
  shows the same save twice once both engines are running;
* the coverage/confidence arithmetic, which decides whether the card fires.

Ranking itself is deliberately *not* pinned. The two engines use different hash
functions and therefore different vector spaces; they are compared at the result
level, not the vector level, so their scores are not expected to match.

Usage:  python scripts/gen_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "extension" / "test"

from chekhovsgun.adapters import identify_url
from chekhovsgun.models import (
    Comment,
    SavedItem,
    Segment,
    make_chunk_id,
    text_fragment,
)
from chekhovsgun.rag.chunker import chunk_item, chunk_segments, chunk_text
from chekhovsgun.rag.retriever import (
    _coverage,
    _partition_by_script,
    confidence_of,
)
from chekhovsgun.rag.text import normalize, script_of, sentences, tokenize
from chekhovsgun.sites import canonical_url, url_digest


def write(name: str, payload) -> None:
    path = OUT / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  {name}")


def text_fixtures() -> None:
    cases = [
        "How Vector Databases Actually Work",
        "红烧肉的做法，这个视频讲解得很详细",
        "self-attention is all you need",
        "B-Tree vs LSM-Tree 的区别",
        "Redis 持久化原理详解",
        "KV cache 是什么？为什么能加速 LLM 推理",
        "  Ｆｕｌｌ－ＷｉｄＴＨ  ＴｅＸＴ ",
        "chunking and hybrid search explained",
        "我们来聊聊 RAG 的检索质量问题",
        "GPT-4o mini 1.5x faster",
        "",
        "a the of and",
        "这个那个还是就是",
        "エンベディング と 検索",
        "한국어 텍스트",
    ]
    sentence_cases = [
        "第一句。第二句！第三句？",
        "One. Two. Three.",
        "a\nb\nc",
        "混合 sentence. 中文句子。",
    ]
    write(
        "fixtures-text.json",
        {
            "tokenize": [
                {
                    "text": c,
                    "normalize": normalize(c),
                    "tokens": tokenize(c),
                    "tokens_keep": tokenize(c, drop_stopwords=False),
                    "script": script_of(c),
                }
                for c in cases
            ],
            "sentences": [{"text": s, "sentences": sentences(s)} for s in sentence_cases],
        },
    )


def id_fixtures() -> None:
    cases = [
        ("youtube:abc", 0, "hello world"),
        ("zhihu:123", 7, "红烧肉的做法"),
        ("x:1", 0, ""),
        ("bilibili:BV1xx", 42, "a" * 500),
    ]
    write(
        "fixtures-ids.json",
        [
            {"item": i, "ordinal": o, "text": t, "id": make_chunk_id(i, o, t)}
            for i, o, t in cases
        ],
    )


def chunker_fixtures() -> None:
    segs = [
        Segment(
            text=f"sentence number {i} about vector search and embeddings.",
            start=i * 3.0,
            end=i * 3.0 + 3.0,
        )
        for i in range(30)
    ]
    slow = [Segment(text="uh", start=i * 20.0, end=i * 20.0 + 20.0) for i in range(12)]
    prose = "第一句话讲的是向量检索。第二句话讲的是倒排索引。Third sentence is in English. " * 6

    post = SavedItem(
        source="zhihu",
        source_id="42",
        title="怎么做红烧肉",
        url="https://zhihu.com/42",
        author="张三",
        description="这是一个摘要 excerpt",
        tags=["烹饪", "家常菜"],
        folder="收藏夹",
        media_kind="post",
    )
    body = [
        Segment(text=f"第{i}段正文，讲的是火候和糖色的控制方法。", start=0, end=0)
        for i in range(8)
    ]
    comments = [
        Comment(text="很有用的分享", likes=10, replies=["同感，我也试过了"]),
        Comment(text="短", likes=1),
    ]
    video = SavedItem(
        source="youtube",
        source_id="abc",
        title="How Vector DBs Work",
        url="https://y/abc",
        author="Deep Dive",
        description="A talk about ANN indexes and recall.",
        tags=[],
    )

    def dump(chunks):
        return [
            {
                "text": c.text,
                "start": c.start,
                "end": c.end,
                "kind": c.kind,
                "ordinal": c.ordinal,
                "id": c.id,
            }
            for c in chunks
        ]

    write(
        "fixtures-chunker.json",
        {
            "segments": dump(chunk_segments("t:1", segs)),
            "segments_slow": dump(chunk_segments("t:2", slow)),
            "text": dump(chunk_text("t:3", prose)),
            "item": dump(chunk_item(post, body, None, comments)),
            "item_video": dump(chunk_item(video, segs[:6])),
        },
    )


def score_fixtures() -> None:
    confidence = [
        {"dense": d, "coverage": c, "confidence": confidence_of(d, c)}
        for d in (0.0, 0.1, 0.35, 0.5, 0.75, 0.9, 1.0)
        for c in (0.0, 0.2, 0.4, 0.6, 0.85, 1.0)
    ]
    scenarios = [
        ({"vector": 2.1, "search": 1.4, "embedding": 2.8},
         "a talk about vector search and embedding models"),
        ({"vector": 2.1, "search": 1.4, "embedding": 2.8},
         "completely unrelated text about cooking"),
        ({"做法": 1.2, "红烧": 3.0}, "红烧肉的做法要先焯水"),
        ({"做法": 1.2, "红烧": 3.0}, "redis persistence and durability"),
        ({"react": 3.2}, "making my react app faster with memoization"),
    ]
    coverage = [
        {
            "weights": weights,
            "text": text,
            "coverage": _coverage(
                _partition_by_script(weights), text, frozenset(tokenize(text))
            ),
        }
        for weights, text in scenarios
    ]
    write("fixtures-score.json", {"confidence": confidence, "coverage": coverage})


def site_fixtures() -> None:
    urls = [
        "https://www.zhihu.com/question/12345/answer/67890?utm_source=weixin&spm=abc",
        "https://zhuanlan.zhihu.com/p/998877/",
        "https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.999&vd_source=deadbeef",
        "https://www.youtube.com/watch?v=Xpzbywj7HbQ&t=1000s&feature=share",
        "https://youtu.be/Xpzbywj7HbQ",
        "https://www.xiaohongshu.com/explore/65a1b2c3d4e5f6?xhsshare=CopyLink&shareRedId=xyz",
        "https://mp.weixin.qq.com/s/AbCdEfGh?scene=23",
        "https://juejin.cn/post/7123456789",
        "https://blog.csdn.net/user/article/details/123456",
        "https://www.reddit.com/r/rust/comments/abc123/some_title/",
        "https://x.com/someone/status/1234567890",
        "https://stackoverflow.com/questions/4567/how-do-i",
        "https://medium.com/@a/some-title-0123456789ab",
        "https://example.com/some/random/page?a=1&utm_medium=x",
        "https://m.weibo.cn/detail/4899887766",
        "https://www.jianshu.com/p/abc123def",
        "https://news.ycombinator.com/item?id=123",
    ]
    rows = []
    for url in urls:
        source, source_id, media_kind = identify_url(url)
        rows.append(
            {
                "url": url,
                "canonical": canonical_url(url),
                "source": source,
                "source_id": source_id,
                "media_kind": media_kind,
                "digest": url_digest(url),
            }
        )
    write("fixtures-sites.json", rows)


def deeplink_fixtures() -> None:
    cases = [
        "short",
        "a genuinely long passage of body text that should highlight from start to end here",
        "带连字符-的中文句子应该也能正确转义处理",
        "exactly forty eight characters long text here ok",
        "a,b&c-d with syntax characters",
        "混合 mixed 中英文 passage with enough length to trigger the two-ended form of the fragment",
    ]
    write(
        "fixtures-deeplink.json",
        [{"text": c, "fragment": text_fragment(c)} for c in cases],
    )


def main() -> None:
    print(f"Writing fixtures to {OUT.relative_to(ROOT)}/")
    text_fixtures()
    id_fixtures()
    chunker_fixtures()
    score_fixtures()
    site_fixtures()
    deeplink_fixtures()
    print("\nNow run `npm test` to check the JavaScript port still agrees.")


if __name__ == "__main__":
    main()
