from chekhovsgun.adapters.base import AdapterError, SourceAdapter
from chekhovsgun.ingest import content_hash
from chekhovsgun.models import SavedItem, Segment


class FakeAdapter(SourceAdapter):
    name = "fake"
    label = "Fake"

    def __init__(self, config, items, transcripts=None, fail_transcripts=False):
        super().__init__(config)
        self._items = items
        self._transcripts = transcripts or {}
        self._fail = fail_transcripts
        self.transcript_calls = 0

    def list_saved(self, *, limit=None):
        return self._items[:limit] if limit else self._items

    def fetch_content(self, item):
        self.transcript_calls += 1
        if self._fail:
            raise AdapterError("no captions")
        return iter(self._transcripts.get(item.source_id, []))


def _item(n, title=None):
    return SavedItem(
        source="fake", source_id=f"v{n}", title=title or f"视频 {n} 关于向量检索",
        url=f"https://example.com/{n}", author="UP", description="索引 与 召回",
    )


def test_content_hash_changes_only_with_indexable_fields():
    item = _item(1)
    base = content_hash(item)
    item.thumbnail = "https://cdn/new.jpg"
    assert content_hash(item) == base, "cosmetic fields must not trigger a re-index"
    item.title = "新标题"
    assert content_hash(item) != base


def test_ingest_indexes_items_and_transcripts(engine):
    adapter = FakeAdapter(
        engine.config, [_item(1), _item(2)],
        {"v1": [Segment(text="一段足够长的字幕文本用于测试", start=0, end=5)]},
    )
    report = engine.ingest(adapter)
    assert report.added == 2 and report.failed == 0
    assert report.with_transcript == 1
    assert engine.store.stats()["items"] == 2


def test_second_ingest_skips_unchanged_items(engine):
    items = [_item(1), _item(2)]
    first = FakeAdapter(engine.config, items)
    engine.ingest(first)
    second = FakeAdapter(engine.config, items)
    report = engine.ingest(second)
    assert report.skipped == 2 and report.added == 0
    assert second.transcript_calls == 0, "unchanged items must not refetch transcripts"


def test_force_reingests_everything(engine):
    items = [_item(1)]
    engine.ingest(FakeAdapter(engine.config, items))
    report = engine.ingest(FakeAdapter(engine.config, items), force=True)
    assert report.updated == 1 and report.skipped == 0


def test_changed_title_triggers_an_update(engine):
    engine.ingest(FakeAdapter(engine.config, [_item(1)]))
    report = engine.ingest(FakeAdapter(engine.config, [_item(1, title="换了个标题的视频")]))
    assert report.updated == 1


def test_a_missing_transcript_is_not_a_failure(engine):
    adapter = FakeAdapter(engine.config, [_item(1)], fail_transcripts=True)
    report = engine.ingest(adapter)
    assert report.failed == 0 and report.added == 1
    assert engine.store.item_chunks("fake:v1"), "title/description must still be indexed"


def test_no_transcripts_flag_skips_fetching(engine):
    adapter = FakeAdapter(engine.config, [_item(1)])
    engine.ingest(adapter, fetch_transcripts=False)
    assert adapter.transcript_calls == 0


def test_limit_is_respected(engine):
    adapter = FakeAdapter(engine.config, [_item(n) for n in range(10)])
    report = engine.ingest(adapter, limit=3)
    assert report.seen <= 3 and engine.store.stats()["items"] <= 3


def test_unconfigured_adapter_reports_its_hint(engine):
    class Unconfigured(FakeAdapter):
        @property
        def configured(self):
            return False

        def setup_hint(self):
            return "set FAKE_TOKEN"

    report = engine.ingest(Unconfigured(engine.config, []))
    assert report.errors == ["set FAKE_TOKEN"]


def test_reindex_reembeds_every_chunk(seeded):
    before = seeded.store.stats()["chunks"]
    assert seeded.reindex() == before
