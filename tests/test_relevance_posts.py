"""The relevance gate, for post-shaped saves.

Everything in the retrieval path was tuned against subtitles: hundreds of
passages per item, each a loose transcription of speech. A Zhihu answer is the
opposite — one to three dense, edited passages — and the two knobs that decide
whether the popup fires (``min_confidence`` and the saturating coverage curve)
are absolute, not relative. So a post can be both the only sane answer and fall
under the bar, or be so short that a single shared word clears it.

These cases pin both directions: a post must be able to fire, and a post must
not fire on a page that merely shares its vocabulary.
"""

from __future__ import annotations

import pytest

from chekhovsgun.models import Context

POSTS = [
    {
        "url": "https://www.zhihu.com/question/100/answer/1",
        "title": "为什么你的 RAG 检索不准？混合检索与重排序讲清楚",
        "author": "检索工程师",
        "folder": "知乎收藏夹/检索",
        "text": (
            "纯向量检索最大的失败模式是专有名词。嵌入会把精确的术语抹平，KV cache 这种词会被当成普通短语。\n"
            "BM25 的失败模式正好相反：它对专有名词极准，但完全不理解同义改写，两者的错误几乎不重叠。\n"
            "所以把两路召回用 RRF 融合，只看排名不看分数，就不需要校准两条量纲完全不同的分数线。\n"
            "重排序模型可以再捞一把，但代价是每次查询都要过一遍交叉编码器，延迟从毫秒级涨到百毫秒级。"
        ),
    },
    {
        "url": "https://zhuanlan.zhihu.com/p/200",
        "title": "Postgres 索引选择：什么时候该建部分索引",
        "author": "数据库老王",
        "folder": "知乎收藏夹/数据库",
        "text": (
            "部分索引只对满足条件的行建立条目，适合那种绝大多数行都是同一个值的布尔列。\n"
            "比如软删除场景里 deleted_at IS NULL 的行占九成九，给它建部分索引能把索引体积压到十分之一。\n"
            "代价是查询必须显式带上同样的条件，否则规划器不会选中这个索引，这一点经常被忽略。"
        ),
    },
    {
        "url": "https://mp.weixin.qq.com/s/abcdef",
        "title": "手冲咖啡的水温到底该多少度",
        "author": "咖啡日记",
        "folder": "微信收藏",
        "text": (
            "浅烘豆子建议用九十二到九十四度的水，温度低了萃取不足，喝起来是尖酸而不是明亮的果酸。\n"
            "深烘豆子反过来，八十八度左右就够了，再高就会把焦苦味一起萃出来，压过本来的甜感。\n"
            "闷蒸三十秒让二氧化碳跑掉，之后分两到三段注水，整杯控制在两分半左右。"
        ),
    },
]


def _capture_all(engine):
    for post in POSTS:
        engine.capture(
            post["url"],
            title=post["title"],
            author=post["author"],
            folder=post["folder"],
            text=post["text"],
        )
    return engine


@pytest.fixture
def posts(seeded):
    """Posts alongside the demo videos — a mixed library, which is the product.

    Deliberately *not* posts alone. Confidence leans on IDF, and a three-item
    library makes every word look rare; measuring relevance there measures the
    cold-start artifact rather than the retrieval. The cold-start behaviour has
    its own tests below.
    """
    return _capture_all(seeded)


class TestPostsCanFire:
    @pytest.mark.parametrize(
        "watching, expected",
        [
            ("混合检索是怎么回事？BM25 和向量召回的融合", "RAG 检索不准"),
            ("RRF 融合为什么不需要校准分数", "RAG 检索不准"),
            ("数据库部分索引 partial index 用法", "Postgres 索引选择"),
            ("软删除的表怎么建索引更省空间", "Postgres 索引选择"),
            ("手冲咖啡闷蒸和注水手法", "手冲咖啡"),
        ],
    )
    def test_a_related_page_surfaces_the_post(self, posts, watching, expected):
        titles = [hit.item.title for hit in posts.search(watching, limit=3)]
        assert any(expected in title for title in titles), f"{watching!r} -> {titles}"

    def test_a_short_post_outranks_everything_else_on_its_own_subject(self, posts):
        # A post carries a fraction of a lecture's text, so it must not need a
        # transcript's worth of evidence to win its own topic.
        hits = posts.search("RRF 融合 只看排名不看分数", limit=3)
        assert hits and "RAG 检索不准" in hits[0].item.title
        assert hits[0].item.media_kind == "post"

    def test_an_english_page_can_surface_a_chinese_post(self, posts):
        # Cross-language is the reason this project indexes both sides at once.
        # With the default hashed encoder it runs on shared terminology rather
        # than on semantics — BM25 is exact on proper nouns, which is why the
        # two retrievers are fused. (A neural encoder removes the need for the
        # shared tokens; see CHEKHOVSGUN_EMBEDDING_BACKEND.)
        for query, expected in [
            ("deleted_at IS NULL partial index", "Postgres 索引选择"),
            ("RRF reciprocal rank fusion BM25", "RAG 检索不准"),
        ]:
            titles = [hit.item.title for hit in posts.search(query, limit=3)]
            assert any(expected in title for title in titles), f"{query!r} -> {titles}"


class TestPostsStaySilent:
    @pytest.mark.parametrize(
        "watching",
        [
            "红烧肉的做法，先焯水还是先煎",
            "猫咪第一次剪指甲的全过程记录",
            "周末去爬山的 vlog，风景真好",
        ],
    )
    def test_an_unrelated_page_fires_nothing(self, posts, watching):
        assert posts.search(watching, limit=5) == []

    def test_one_shared_word_is_not_enough(self, posts):
        # 选择 appears in the Postgres answer's title, but a page about choosing
        # a coffee grinder has nothing to do with indexes. A single common term
        # must not carry a match on its own.
        titles = [hit.item.title for hit in posts.search("磨豆机怎么选择", limit=5)]
        assert not any("Postgres" in title for title in titles)

    def test_the_page_you_are_on_does_not_surface_itself(self, posts):
        # Firing here is correct — a *different* save covers the same ground.
        # What must never happen is telling the user they saved the very page
        # they are looking at.
        result = posts.relate_url("https://www.zhihu.com/question/100/answer/1")
        assert "zhihu:100-1" not in [hit["item"]["id"] for hit in result["hits"]]

    def test_a_lone_save_on_its_own_page_says_so(self, seeded):
        # When the page *is* the only match, the reason has to be legible rather
        # than a bare "nothing found".
        seeded.capture("https://mp.weixin.qq.com/s/abcdef", title=POSTS[2]["title"],
                       text=POSTS[2]["text"])
        result = seeded.relate_url("https://mp.weixin.qq.com/s/abcdef")
        assert not result["fired"]
        assert result["reason_code"] == "self_saved"


class TestPostsAndVideosShareOneIndex:
    def test_a_post_can_fire_on_a_video_page(self, seeded):
        """The mixed library is the product: a video you scroll onto pulls up a
        post you saved, and vice versa. Neither medium is a second-class source."""
        seeded.capture(
            "https://www.zhihu.com/question/100/answer/1",
            title="为什么你的 RAG 检索不准？混合检索与重排序讲清楚",
            text=POSTS[0]["text"],
        )
        titles = [hit.item.title for hit in seeded.search("RAG 分块 重排 混合检索", limit=5)]
        assert any("RAG 检索不准" in title for title in titles)

    def test_posts_and_videos_are_both_reachable_by_medium(self, seeded):
        seeded.capture("https://zhuanlan.zhihu.com/p/200", title=POSTS[1]["title"],
                       text=POSTS[1]["text"])
        posts = seeded.store.list_items(media_kind="post")
        videos = seeded.store.list_items(media_kind="video")
        assert len(posts) == 1 and len(videos) > 1


class TestColdStart:
    """A nearly-empty library cannot tell a real match from a shared word.

    With three saves, every term looks rare, so 磨豆机怎么选择 scores 0.38
    against a post about 索引选择 — indistinguishable from a genuine five-term
    match. The same query is correctly silent once the library is a normal size.
    Rather than bend the scoring, the popup declines to fire until it has enough
    to be right.
    """

    def test_the_popup_stays_quiet_until_the_library_is_big_enough(self, engine):
        _capture_all(engine)
        result = engine.relate(Context(title="磨豆机怎么选择，手摇还是电动"))
        assert result["fired"] is False
        assert result["reason_code"] == "library_too_small"
        assert result["library"] == {"items": 3, "needed": 15}

    def test_search_is_never_gated(self, engine):
        # Silence is about not interrupting. When the user asks a question
        # outright they get everything, exactly as muting works.
        _capture_all(engine)
        assert engine.search("RRF 融合 排名") != []

    def test_a_full_library_fires_normally(self, posts):
        assert posts.store.item_count() >= 15
        result = posts.relate(Context(title="磨豆机怎么选择，手摇还是电动"))
        assert result["reason_code"] != "library_too_small"
