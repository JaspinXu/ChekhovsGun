"""Item lifecycle: digested / muted / tags.

The product's whole point is that a save eventually fires *and gets finished*.
These tests pin the two halves of that: marking something digested stops the
interruptions, and a re-sync must never undo the user's own bookkeeping.
"""

import pytest

from chekhovsgun.models import STATUS_ACTIVE, STATUS_DIGESTED, STATUS_MUTED, Context


def _some_item(engine):
    return engine.store.list_items(query="RAG")[0]


def test_new_items_are_active(seeded):
    assert all(item.status == STATUS_ACTIVE for item in seeded.store.list_items(limit=50))


def test_marking_digested_stops_it_firing(seeded):
    target = _some_item(seeded)
    context = Context(
        source="youtube", source_id="live",
        title="RAG 分块策略与混合检索重排", description="chunking bm25 rerank",
    )
    before = seeded.relate(context, use_cache=False)
    assert any(hit["item"]["id"] == target.id for hit in before["hits"])

    seeded.mark(target.id, status=STATUS_DIGESTED)
    after = seeded.relate(context, use_cache=False)
    assert all(hit["item"]["id"] != target.id for hit in after["hits"])


def test_digested_items_remain_searchable(seeded):
    """Muting stops interruptions; it must not hide things from explicit search."""
    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_DIGESTED)
    hits = seeded.search("RAG 分块 重排 混合检索", limit=5)
    assert any(hit.item.id == target.id for hit in hits)


def test_muting_also_stops_it_firing(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_MUTED)
    assert target.id in seeded._silenced_items()


def test_digested_can_be_put_back(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_DIGESTED)
    seeded.mark(target.id, status=STATUS_ACTIVE)
    assert target.id not in seeded._silenced_items()


def test_exclude_digested_is_configurable(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_DIGESTED)
    seeded.config.retrieval.exclude_digested = False
    assert target.id not in seeded._silenced_items()


def test_tags_add_and_remove_without_duplicates(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, add_tags=["检索", "检索", "笔记"])
    assert seeded.store.get_item(target.id).user_tags == ["检索", "笔记"]
    seeded.mark(target.id, remove_tags=["检索"])
    assert seeded.store.get_item(target.id).user_tags == ["笔记"]


def test_notes_round_trip(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, note="回去看了重排那一段")
    assert seeded.store.get_item(target.id).note == "回去看了重排那一段"


def test_an_unknown_status_is_rejected(seeded):
    with pytest.raises(ValueError):
        seeded.mark(_some_item(seeded).id, status="finished")


def test_marking_an_unknown_item_returns_none(seeded):
    assert seeded.mark("nope:nope", status=STATUS_DIGESTED) is None


def test_resync_preserves_the_users_own_columns(seeded):
    """A nightly sync must not resurrect something marked 已学完."""
    from chekhovsgun.adapters.local import LocalFileAdapter
    from tests.conftest import DEMO

    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_DIGESTED, add_tags=["手动标签"], note="我的笔记")
    seeded.ingest(LocalFileAdapter(seeded.config, DEMO), force=True)

    after = seeded.store.get_item(target.id)
    assert after.status == STATUS_DIGESTED
    assert after.user_tags == ["手动标签"]
    assert after.note == "我的笔记"


def test_listing_filters_by_status_and_tag(seeded):
    target = _some_item(seeded)
    seeded.mark(target.id, status=STATUS_DIGESTED, add_tags=["检索"])
    assert [i.id for i in seeded.store.list_items(status=STATUS_DIGESTED)] == [target.id]
    assert [i.id for i in seeded.store.list_items(tag="检索")] == [target.id]
    assert seeded.store.list_items(tag="不存在的标签") == []


def test_tag_cloud(seeded):
    items = seeded.store.list_items(limit=3)
    for item in items:
        seeded.mark(item.id, add_tags=["共同标签"])
    seeded.mark(items[0].id, add_tags=["独有"])
    tags = dict(seeded.store.all_user_tags())
    assert tags["共同标签"] == 3 and tags["独有"] == 1


def test_coverage_counts_digested_not_fired(seeded):
    """The headline metric is what got finished, not what got shown."""
    stats = seeded.store.stats()
    assert stats["coverage"] == 0.0
    seeded.mark(_some_item(seeded).id, status=STATUS_DIGESTED)
    stats = seeded.store.stats()
    assert stats["items_digested"] == 1
    assert stats["coverage"] > 0
