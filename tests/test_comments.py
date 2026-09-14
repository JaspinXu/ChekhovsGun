"""Comment threads as a retrieval source.

The value of this feature is entirely in the cases below: information that is
in the comments and *nowhere else* in the video must be findable.
"""

from chekhovsgun.adapters.bilibili import BilibiliAdapter
from chekhovsgun.adapters.youtube import YouTubeAdapter
from chekhovsgun.config import CommentsConfig
from chekhovsgun.models import Comment, SavedItem
from chekhovsgun.rag.chunker import chunk_comments, chunk_item


class TestCommentModel:
    def test_thread_keeps_replies_attached(self):
        comment = Comment(text="主评论", replies=["回复一", "回复二"])
        passage = comment.as_passage()
        assert "主评论" in passage and "↳ 回复一" in passage and "↳ 回复二" in passage

    def test_empty_replies_are_dropped(self):
        assert Comment(text="只有主评论", replies=["", "  "]).as_passage() == "只有主评论"


class TestChunking:
    def test_one_chunk_per_thread(self):
        comments = [Comment(text=f"一条足够长的评论内容编号 {i}") for i in range(3)]
        chunks = chunk_comments("item", comments)
        assert len(chunks) == 3
        assert all(chunk.kind == "comment" for chunk in chunks)

    def test_too_short_threads_are_skipped(self):
        assert chunk_comments("item", [Comment(text="好")]) == []

    def test_comments_are_appended_after_the_transcript(self):
        item = SavedItem(source="s", source_id="1", title="标题", url="u")
        chunks = chunk_item(item, [], None, [Comment(text="一条足够长的评论内容用于测试")])
        kinds = [chunk.kind for chunk in chunks]
        assert kinds[0] == "title" and "comment" in kinds
        assert len({chunk.ordinal for chunk in chunks}) == len(chunks)


class TestBilibiliParsing:
    def _settings(self, **kwargs):
        return CommentsConfig(**kwargs)

    def test_parses_threads_with_replies(self):
        replies = [
            {
                "content": {"message": "这里视频讲错了，复杂度是序列长度的平方"},
                "member": {"uname": "某人"},
                "like": 120,
                "replies": [{"content": {"message": "确实，我也发现了这个问题"}}],
            }
        ]
        out = BilibiliAdapter._parse_replies(replies, self._settings())
        assert len(out) == 1
        assert out[0].author == "某人" and out[0].likes == 120
        assert out[0].replies == ["确实，我也发现了这个问题"]

    def test_replies_clear_a_lower_bar_than_top_level_comments(self):
        """A three-word correction is the most useful line in many threads."""
        replies = [
            {
                "content": {"message": "这里视频讲错了，复杂度是序列长度的平方"},
                "member": {}, "like": 50,
                "replies": [{"content": {"message": "对，是 O(n²)"}}],
            }
        ]
        out = BilibiliAdapter._parse_replies(replies, self._settings())
        assert out[0].replies == ["对，是 O(n²)"]

    def test_drops_low_effort_comments(self):
        replies = [
            {"content": {"message": "沙发"}, "like": 999, "member": {}},
            {"content": {"message": "一条内容足够长但是没人点赞的评论"}, "like": 0, "member": {}},
        ]
        assert BilibiliAdapter._parse_replies(replies, self._settings()) == []

    def test_sorts_by_likes_and_caps(self):
        replies = [
            {"content": {"message": f"一条内容足够长的评论，编号是第 {i} 条"}, "like": i * 10, "member": {}}
            for i in range(1, 8)
        ]
        out = BilibiliAdapter._parse_replies(replies, self._settings(max_per_item=3))
        assert len(out) == 3
        assert [c.likes for c in out] == [70, 60, 50]

    def test_replies_can_be_disabled(self):
        replies = [
            {
                "content": {"message": "一条内容足够长的主评论，用于测试回复开关"},
                "member": {}, "like": 50,
                "replies": [{"content": {"message": "一条足够长的回复内容"}}],
            }
        ]
        out = BilibiliAdapter._parse_replies(replies, self._settings(include_replies=False))
        assert out[0].replies == []


class TestYouTubeParsing:
    def test_parses_comment_threads(self):
        threads = [
            {
                "snippet": {
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": "The video skips the part about index build time",
                            "authorDisplayName": "someone",
                            "likeCount": 42,
                        }
                    }
                },
                "replies": {
                    "comments": [
                        {"snippet": {"textOriginal": "Yes, efConstruction is immutable afterwards"}}
                    ]
                },
            }
        ]
        out = YouTubeAdapter._parse_comment_threads(threads, CommentsConfig())
        assert len(out) == 1 and out[0].likes == 42
        assert out[0].replies == ["Yes, efConstruction is immutable afterwards"]

    def test_drops_short_and_unliked(self):
        threads = [
            {"snippet": {"topLevelComment": {"snippet": {"textOriginal": "first", "likeCount": 99}}}},
        ]
        assert YouTubeAdapter._parse_comment_threads(threads, CommentsConfig()) == []


class TestRetrieval:
    def test_finds_information_that_only_exists_in_a_comment(self, seeded):
        """FlashAttention is mentioned nowhere in the demo transcripts."""
        hits = seeded.search("FlashAttention 有没有降低注意力的复杂度", limit=3)
        assert hits, "a comment-only fact must still be retrievable"
        assert "Transformer" in hits[0].item.title
        assert any(chunk.kind == "comment" for chunk in hits[0].chunks)

    def test_comment_only_fact_in_english_library(self, seeded):
        hits = seeded.search("AOF 重写还需要双倍磁盘空间吗", limit=3)
        assert hits and "Redis" in hits[0].item.title

    def test_comments_are_indexed_as_their_own_kind(self, seeded):
        assert seeded.store.stats()["comment_chunks"] > 0
