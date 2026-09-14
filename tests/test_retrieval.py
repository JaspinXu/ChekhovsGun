"""Retrieval behaviour, including the relevance gate that decides whether the
browser extension is allowed to interrupt the user at all."""

import numpy as np

from chekhovsgun.config import EmbeddingConfig
from chekhovsgun.models import Context
from chekhovsgun.rag.embeddings import HashingEmbedder, get_embedder
from chekhovsgun.rag.retriever import confidence_of


class TestEmbedder:
    def test_vectors_are_unit_length(self):
        vectors = HashingEmbedder(128).embed(["hello world", "注意力机制"])
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)

    def test_is_deterministic(self):
        a = HashingEmbedder(128).embed_one("同一段文字 same text")
        b = HashingEmbedder(128).embed_one("同一段文字 same text")
        assert np.allclose(a, b)

    def test_related_texts_score_higher_than_unrelated(self):
        embedder = HashingEmbedder(512)
        base, near, far = embedder.embed(
            ["数据库索引的 B-Tree 原理", "B-Tree 索引如何加速数据库查询", "如何做一道番茄炒蛋"]
        )
        assert float(base @ near) > float(base @ far)

    def test_empty_text_is_handled(self):
        vectors = HashingEmbedder(64).embed(["", "   "])
        assert vectors.shape == (2, 64)

    def test_empty_batch(self):
        assert HashingEmbedder(64).embed([]).shape == (0, 64)

    def test_unknown_backend_falls_back_to_local(self):
        embedder = get_embedder(EmbeddingConfig(backend="does-not-exist"))
        assert isinstance(embedder, HashingEmbedder)

    def test_openai_backend_without_a_key_falls_back(self):
        embedder = get_embedder(EmbeddingConfig(backend="openai", api_key=""))
        assert isinstance(embedder, HashingEmbedder)


class TestConfidence:
    def test_requires_both_signals(self):
        assert confidence_of(0.95, 0.02) < 0.45
        assert confidence_of(0.02, 0.95) < 0.45
        assert confidence_of(0.8, 0.8) > 0.7

    def test_is_bounded(self):
        assert 0.0 <= confidence_of(-5, 5) <= 1.0
        assert confidence_of(0, 0) == 0.0

    def test_is_monotonic(self):
        assert confidence_of(0.6, 0.5) > confidence_of(0.5, 0.5)
        assert confidence_of(0.5, 0.6) > confidence_of(0.5, 0.5)


class TestSearch:
    def test_finds_the_right_item_across_languages(self, seeded):
        hits = seeded.search("self-attention and multi-head attention explained", limit=3)
        assert hits, "an English query should reach the Chinese Transformer video"
        assert "Transformer" in hits[0].item.title

    def test_finds_chinese_query_against_english_content(self, seeded):
        hits = seeded.search("向量数据库 HNSW 近似最近邻", limit=3)
        assert any("Vector Databases" in hit.item.title for hit in hits)

    def test_unrelated_query_fires_nothing(self, seeded):
        assert seeded.search("番茄炒蛋的家常做法，先放糖还是先放盐", limit=5) == []
        assert seeded.search("周末去爬山的 vlog，风景真好", limit=5) == []

    def test_results_carry_a_deep_link_with_a_timestamp(self, seeded):
        hits = seeded.search("最左前缀原则 复合索引", limit=1)
        assert hits and "t=" in hits[0].deep_link()

    def test_respects_the_source_filter(self, seeded):
        hits = seeded.search("index", limit=5, sources={"bilibili"})
        assert all(hit.item.source == "bilibili" for hit in hits)

    def test_confidence_gate_is_configurable(self, seeded):
        query = "Haskell functor applicative monad"
        seeded.config.retrieval.min_confidence = 0.05
        assert seeded.search(query, limit=5)
        seeded.config.retrieval.min_confidence = 0.99
        assert seeded.search(query, limit=5) == []

    def test_diversifies_across_items(self, seeded):
        hits = seeded.search("检索 向量 数据库 索引", limit=5)
        assert len({hit.item.id for hit in hits}) == len(hits)

    def test_empty_query(self, seeded):
        assert seeded.search("", limit=5) == []


class TestRelate:
    def test_excludes_the_video_being_watched(self, seeded):
        target = seeded.store.list_items(query="RAG")[0]
        context = Context(
            source=target.source, source_id=target.source_id,
            title=target.title, description=target.description,
        )
        result = seeded.relate(context, use_cache=False)
        assert all(hit["item"]["id"] != target.id for hit in result["hits"])

    def test_fires_with_an_explanation(self, seeded):
        context = Context(
            source="youtube", source_id="live1",
            title="Chunking strategies for RAG and why hybrid search wins",
            description="bm25 embeddings reranking chunk size",
        )
        result = seeded.relate(context, use_cache=False)
        assert result["fired"] is True
        assert result["explanation"]["text"]
        # No API key in tests, so the extractive path must be the one used.
        assert result["explanation"]["generated"] is False

    def test_does_not_fire_on_an_unrelated_video(self, seeded):
        context = Context(source="bilibili", source_id="x", title="猫咪剪指甲全过程记录")
        assert seeded.relate(context, use_cache=False)["fired"] is False

    def test_empty_context_does_not_fire(self, seeded):
        assert seeded.relate(Context(), use_cache=False)["fired"] is False

    def test_cache_returns_the_same_answer(self, seeded):
        context = Context(source="youtube", source_id="c1", title="vector database HNSW")
        first = seeded.relate(context)
        second = seeded.relate(context)
        assert second["cached"] is True
        assert [h["item"]["id"] for h in first["hits"]] == [h["item"]["id"] for h in second["hits"]]

    def test_relate_url_resolves_a_known_item(self, seeded):
        result = seeded.relate_url("https://www.bilibili.com/video/BV1hd4y1e7Zc", use_cache=False)
        assert "hits" in result

    def test_relate_url_rejects_an_unknown_host(self, seeded):
        assert seeded.relate_url("https://example.com/x")["fired"] is False
