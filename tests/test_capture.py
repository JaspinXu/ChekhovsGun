"""The browser-capture path: a page the extension read, taken into the library.

These pin the behaviour that makes 「只需要收藏」 true for sites with no API —
the user clicks 收藏 on Zhihu and the answer becomes retrievable, with no
credentials, no adapter and no export step.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from chekhovsgun.models import MEDIA_POST, MEDIA_VIDEO, Chunk, ItemHit, SavedItem, text_fragment

ANSWER = """
纯向量检索最大的失败模式是专有名词。嵌入会把精确的术语抹平，KV cache 这样的词被当成普通短语。
BM25 的失败模式正好相反：它对专有名词极准，但完全不理解同义改写，两者的错误几乎不重叠。
所以把两路召回用 RRF 融合，只看排名不看分数，就不需要校准两条量纲完全不同的分数线。
"""


def capture_answer(engine, **overrides):
    payload = {
        "url": "https://www.zhihu.com/question/123/answer/456?utm_source=wechat",
        "title": "为什么混合检索比纯向量好",
        "author": "某位答主",
        "text": ANSWER,
        "folder": "知乎收藏夹/检索",
        **overrides,
    }
    return engine.capture(payload.pop("url"), **payload)


class TestCapture:
    def test_a_captured_page_becomes_a_retrievable_item(self, engine):
        result = capture_answer(engine)
        assert result["state"] == "added"
        assert result["source"] == "zhihu"
        assert result["media_kind"] == MEDIA_POST
        assert result["chunks"] > 1

        item = engine.store.get_item(result["item_id"])
        assert item is not None
        assert item.media_kind == MEDIA_POST
        assert item.folder == "知乎收藏夹/检索"
        assert item.transcript_source == "capture"

    def test_the_stored_url_is_canonical(self, engine):
        # Tracking parameters are stripped before storage, so the same answer
        # reached from a share link and from search is one item, not two.
        result = capture_answer(engine)
        assert result["url"] == "https://zhihu.com/question/123/answer/456"
        assert engine.store.get_item(result["item_id"]).url == result["url"]

    def test_recapturing_the_same_page_is_a_no_op(self, engine):
        capture_answer(engine)
        assert capture_answer(engine)["state"] == "skipped"

    def test_recapturing_an_edited_post_updates_it(self, engine):
        capture_answer(engine)
        result = capture_answer(engine, text=ANSWER + "\n补充：实测中 MMR 会删掉最该保留的那段。")
        assert result["state"] == "updated"
        texts = [c.text for c in engine.store.item_chunks(result["item_id"])]
        assert any("MMR" in text for text in texts)

    def test_body_text_is_searchable(self, engine):
        capture_answer(engine)
        hits = engine.search("RRF 融合 排名")
        assert hits and hits[0].item.source == "zhihu"

    def test_body_chunks_are_labelled_body_not_transcript(self, engine):
        result = capture_answer(engine)
        kinds = {chunk.kind for chunk in engine.store.item_chunks(result["item_id"])}
        assert "body" in kinds
        assert "transcript" not in kinds

    def test_excerpt_is_not_indexed_twice_alongside_the_body(self, engine):
        result = capture_answer(engine, excerpt="纯向量检索最大的失败模式是专有名词。")
        kinds = [chunk.kind for chunk in engine.store.item_chunks(result["item_id"])]
        assert "description" not in kinds

    def test_comments_come_along(self, engine):
        result = capture_answer(
            engine,
            comments=[{"text": "补充一点：RRF 的 k 取 60 是经验值，不是推导出来的。", "likes": 120}],
        )
        kinds = {chunk.kind for chunk in engine.store.item_chunks(result["item_id"])}
        assert "comment" in kinds

    def test_an_unknown_site_still_captures(self, engine):
        result = engine.capture("https://some-blog.example/p/1", title="随手记", text=ANSWER)
        assert result["state"] == "added"
        assert result["source"] == "web"

    def test_a_url_is_required(self, engine):
        with pytest.raises(ValueError):
            engine.capture("  ")

    def test_capture_is_visible_in_the_event_log(self, engine):
        capture_answer(engine)
        assert any(event["kind"] == "captured" for event in engine.store.recent_events(10))


class TestStubsAndHydration:
    def test_a_bodyless_capture_parks_in_the_hydration_queue(self, engine):
        result = engine.capture("https://zhihu.com/p/1", title="待补正文", origin="scan")
        assert result["needs_body"] is True
        assert engine.pending_body_count() == 1

    def test_hydration_fetches_indexes_and_clears_the_queue(self, engine, monkeypatch):
        from chekhovsgun.extract import Readable

        engine.capture("https://zhihu.com/p/1", title="待补正文", origin="scan")

        def fake_fetch(url, **_kwargs):
            return Readable(title="真正的标题", author="某位答主", text=ANSWER)

        monkeypatch.setattr("chekhovsgun.extract.fetch_readable", fake_fetch)
        done = engine.hydrate_pending()

        assert done == {"fetched": 1, "indexed": 1, "failed": 0, "chunks": done["chunks"]}
        assert engine.pending_body_count() == 0
        assert engine.search("RRF 融合")

    def test_an_unreadable_page_leaves_the_queue_and_is_not_retried(self, engine, monkeypatch):
        from chekhovsgun.extract import Readable

        engine.capture("https://paywalled.example/x", title="登录墙", origin="scan")
        monkeypatch.setattr(
            "chekhovsgun.extract.fetch_readable",
            lambda url, **_k: Readable(note="HTTP 403"),
        )
        first = engine.hydrate_pending()
        assert first["failed"] == 1
        # The item keeps its title but stops consuming the queue, so one dead
        # link cannot starve the rest of a scan on every subsequent run.
        assert engine.pending_body_count() == 0
        assert engine.store.get_item("web:" + engine.store.list_items()[0].source_id) is not None
        assert engine.hydrate_pending()["fetched"] == 0

    def test_scan_batches_report_per_state_counts(self, engine):
        summary = engine.capture_many(
            [
                {"url": "https://zhihu.com/p/1", "title": "一"},
                {"url": "https://zhihu.com/p/2", "title": "二"},
                {"url": "https://zhihu.com/p/1", "title": "一"},  # already seen
                {"url": "", "title": "坏行"},
            ]
        )
        assert summary["added"] == 2
        assert summary["skipped"] == 1
        assert summary["failed"] == 1
        assert summary["needs_body"] == 3


class TestPostDeepLinks:
    def _hit(self, text, url="https://zhihu.com/p/1", kind="body"):
        item = SavedItem(
            source="zhihu", source_id="1", title="T", url=url, media_kind=MEDIA_POST
        )
        return ItemHit(item=item, score=1.0, chunks=[Chunk(item_id=item.id, ordinal=1,
                                                           text=text, kind=kind)])

    def test_a_post_link_carries_a_text_fragment(self):
        link = self._hit("RRF 只看排名不看分数，所以不需要校准两条量纲不同的分数线").deep_link()
        base, _, fragment = link.partition("#")
        assert base == "https://zhihu.com/p/1"
        assert fragment.startswith(":~:text=")
        assert "RRF" in unquote(fragment)

    def test_a_video_link_still_carries_a_timestamp(self):
        item = SavedItem(source="bilibili", source_id="BV1", title="T",
                         url="https://bilibili.com/video/BV1", media_kind=MEDIA_VIDEO)
        hit = ItemHit(item=item, score=1.0, timestamps=[1000.0])
        assert hit.deep_link() == "https://bilibili.com/video/BV1?t=1000"

    def test_body_text_is_preferred_over_a_comment_for_the_anchor(self):
        item = SavedItem(source="zhihu", source_id="1", title="T",
                         url="https://zhihu.com/p/1", media_kind=MEDIA_POST)
        hit = ItemHit(
            item=item,
            score=1.0,
            chunks=[
                Chunk(item_id=item.id, ordinal=1, text="一条藏在折叠区里的评论内容", kind="comment"),
                Chunk(item_id=item.id, ordinal=2, text="正文里真正讲清楚这件事的那一段", kind="body"),
            ],
        )
        assert "正文" in unquote(hit.deep_link())

    def test_a_post_with_nothing_to_anchor_to_links_to_itself(self):
        item = SavedItem(source="zhihu", source_id="1", title="T",
                         url="https://zhihu.com/p/1#old", media_kind=MEDIA_POST)
        assert ItemHit(item=item, score=1.0).deep_link() == "https://zhihu.com/p/1"


class TestTextFragment:
    def test_long_passages_anchor_both_ends(self):
        passage = (
            "The real failure mode of pure vector search is exact terminology, "
            "and hybrid search with BM25 fixes precisely the cases where an "
            "embedding blurs a term that had to stay sharp."
        )
        fragment = text_fragment(passage)
        assert fragment.count(",") == 1
        start, end = fragment.removeprefix(":~:text=").split(",")
        assert unquote(start).startswith("The real failure mode")
        assert unquote(end).endswith("stay sharp.")

    def test_a_passage_whose_ends_are_identical_anchors_only_once(self):
        # Degenerate but real: a chunk of repeated boilerplate. Emitting
        # "text=X,X" would ask the browser for a range from X to the *next* X.
        assert text_fragment("alpha " * 40).count(",") == 0

    def test_short_passages_anchor_only_the_start(self):
        assert "," not in text_fragment("a short but sufficient passage")

    def test_syntactic_characters_are_escaped(self):
        # '-', ',' and '&' delimit the parts of a text fragment; leaving one raw
        # would silently change which range the browser highlights.
        fragment = text_fragment("well-known A&B, and more text here")
        for char in ("-", "&"):
            assert char not in fragment.removeprefix(":~:text=")

    def test_too_short_to_anchor_yields_nothing(self):
        assert text_fragment("hi") == ""
        assert text_fragment("") == ""
