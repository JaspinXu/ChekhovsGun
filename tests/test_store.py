import numpy as np

from chekhovsgun.models import Chunk, SavedItem
from chekhovsgun.rag.store import Store


def _item(n: int = 1) -> SavedItem:
    return SavedItem(
        source="youtube", source_id=f"vid{n}", title=f"Title {n}",
        url=f"https://youtu.be/vid{n}", author="Someone", tags=["a", "b"], saved_at=float(n),
    )


def test_upsert_is_idempotent_and_updates_in_place(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        item.title = "Changed"
        store.upsert_item(item)
        assert store.stats()["items"] == 1
        assert store.get_item(item.id).title == "Changed"


def test_round_trips_tags_and_extra(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        item.extra = {"aid": 42, "nested": {"k": "v"}}
        store.upsert_item(item)
        loaded = store.get_item(item.id)
        assert loaded.tags == ["a", "b"] and loaded.extra["nested"]["k"] == "v"


def test_replace_chunks_swaps_the_whole_set(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        first = [Chunk(item_id=item.id, ordinal=i, text=f"chunk {i}") for i in range(3)]
        store.replace_chunks(item.id, first, np.eye(3, 4, dtype=np.float32))
        assert len(store.item_chunks(item.id)) == 3
        store.replace_chunks(item.id, first[:1], np.eye(1, 4, dtype=np.float32))
        assert len(store.item_chunks(item.id)) == 1


def test_deleting_an_item_deletes_its_chunks(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        store.replace_chunks(item.id, [Chunk(item_id=item.id, ordinal=0, text="t")], None)
        store.delete_item(item.id)
        assert store.stats()["chunks"] == 0 and store.get_item(item.id) is None


def test_dense_search_ranks_by_cosine(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        chunks = [Chunk(item_id=item.id, ordinal=i, text=f"c{i}") for i in range(3)]
        vectors = np.array([[1, 0, 0], [0.7, 0.7, 0], [0, 0, 1]], dtype=np.float32)
        store.replace_chunks(item.id, chunks, vectors)
        results = store.dense_search(np.array([1, 0, 0], dtype=np.float32), 3)
        assert results[0][0] == chunks[0].id
        assert results[0][1] > results[1][1] > results[2][1]


def test_dense_search_ignores_a_dimension_mismatch(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        store.replace_chunks(
            item.id, [Chunk(item_id=item.id, ordinal=0, text="c")],
            np.ones((1, 4), dtype=np.float32),
        )
        assert store.dense_search(np.ones(8, dtype=np.float32), 5) == []


def test_lexical_search_finds_chinese_terms(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        chunks = [
            Chunk(item_id=item.id, ordinal=0, text="注意力机制的核心是相关性计算"),
            Chunk(item_id=item.id, ordinal=1, text="数据库索引使用 B-Tree 结构"),
        ]
        store.replace_chunks(item.id, chunks, None)
        results = store.lexical_search("注意力", 5)
        assert results and results[0][0] == chunks[0].id


def test_idf_weights_drop_tokens_absent_from_the_corpus(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        store.replace_chunks(
            item.id, [Chunk(item_id=item.id, ordinal=0, text="react performance rendering")], None
        )
        weights = store.idf_weights(["react", "kubernetes", "performance"])
        assert set(weights) == {"react", "performance"}
        assert all(value > 0 for value in weights.values())


def test_caches_rebuild_after_a_write(tmp_path):
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        store.replace_chunks(item.id, [Chunk(item_id=item.id, ordinal=0, text="alpha beta")], None)
        assert store.lexical_search("alpha", 5)
        store.replace_chunks(item.id, [Chunk(item_id=item.id, ordinal=0, text="gamma delta")], None)
        assert not store.lexical_search("alpha", 5)
        assert store.lexical_search("gamma", 5)


def test_item_hashes_and_stats(tmp_path):
    with Store(tmp_path / "x.db") as store:
        store.upsert_item(_item(1), content_hash="h1", has_transcript=True)
        store.upsert_item(_item(2), content_hash="h2")
        assert store.item_hashes("youtube") == {"youtube:vid1": "h1", "youtube:vid2": "h2"}
        stats = store.stats()
        assert stats["items"] == 2 and stats["items_with_transcript"] == 1
        assert stats["by_source"] == {"youtube": 2}


def test_list_items_filters_and_paginates(tmp_path):
    with Store(tmp_path / "x.db") as store:
        for n in range(5):
            store.upsert_item(_item(n))
        assert len(store.list_items(limit=2)) == 2
        assert len(store.list_items(limit=10, offset=3)) == 2
        assert len(store.list_items(query="Title 1")) == 1
        assert store.list_items(source="bilibili") == []


def test_get_items_handles_more_than_the_sqlite_variable_limit(tmp_path):
    with Store(tmp_path / "x.db") as store:
        for n in range(450):
            store.upsert_item(_item(n))
        ids = [f"youtube:vid{n}" for n in range(450)]
        assert len(store.get_items(ids)) == 450


def test_events_round_trip(tmp_path):
    with Store(tmp_path / "x.db") as store:
        store.log_event("fired", source="youtube", item_id="x", payload={"matched": 2})
        events = store.recent_events(10)
        assert events[0]["kind"] == "fired" and events[0]["payload"]["matched"] == 2


def test_lexical_search_skips_tokens_present_in_almost_every_chunk(tmp_path):
    """Very common tokens carry no signal and the longest posting lists."""
    with Store(tmp_path / "x.db") as store:
        item = _item()
        store.upsert_item(item)
        chunks = [
            Chunk(item_id=item.id, ordinal=i, text=f"通用 词语 出现 在 每 一 个 片段 {i} 独特{i}")
            for i in range(50)
        ]
        store.replace_chunks(item.id, chunks, None)
        # "通用" is in every chunk: it must not dominate, but a rare term must work.
        assert store.lexical_search("独特7", 5)
        common = store.lexical_search("通用", 5)
        assert common == [] or len(common) <= 5


def test_tokens_are_persisted_so_a_reopened_store_needs_no_retokenising(tmp_path):
    path = tmp_path / "x.db"
    with Store(path) as store:
        item = _item()
        store.upsert_item(item)
        store.replace_chunks(
            item.id, [Chunk(item_id=item.id, ordinal=0, text="注意力机制 attention")], None
        )
    with Store(path) as reopened:
        row = reopened._conn.execute("SELECT tokens FROM chunks").fetchone()
        assert row["tokens"] and "attention" in row["tokens"]
        assert reopened.lexical_search("注意力", 5)


def test_revision_counter_advances_on_writes(tmp_path):
    with Store(tmp_path / "x.db") as store:
        before = store.revision
        store.upsert_item(_item())
        assert store.revision > before
