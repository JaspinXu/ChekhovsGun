from chekhovsgun.config import RetrievalConfig
from chekhovsgun.models import SavedItem, Segment
from chekhovsgun.rag.chunker import chunk_item, chunk_segments, chunk_text


def _segments(count: int, words: int = 12) -> list[Segment]:
    return [
        Segment(text=" ".join(f"word{i}-{w}" for w in range(words)), start=i * 3.0, end=i * 3.0 + 3.0)
        for i in range(count)
    ]


def test_chunk_segments_respects_character_budget():
    chunks = chunk_segments("item", _segments(40), max_chars=300, overlap_chars=40)
    assert chunks
    assert all(len(chunk.text) <= 420 for chunk in chunks)


def test_chunk_segments_respects_time_budget():
    slow = [
        Segment(text=f"a sentence spoken slowly number {i}", start=i * 30.0, end=i * 30.0 + 30.0)
        for i in range(10)
    ]
    chunks = chunk_segments("item", slow, max_chars=10_000, max_seconds=60.0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.end - chunk.start <= 95.0


def test_chunk_segments_keeps_timestamps_monotonic():
    chunks = chunk_segments("item", _segments(30), max_chars=200)
    starts = [chunk.start for chunk in chunks]
    assert starts == sorted(starts)


def test_chunk_segments_terminates_on_a_single_huge_segment():
    chunks = chunk_segments("item", [Segment(text="x" * 5000, start=0, end=10)], max_chars=100)
    assert len(chunks) == 1


def test_chunk_segments_on_empty_input():
    assert chunk_segments("item", []) == []


def test_chunk_text_splits_prose():
    chunks = chunk_text("item", "一。" * 200, max_chars=100)
    assert len(chunks) > 1
    assert all(chunk.kind == "description" for chunk in chunks)


def test_chunk_item_always_emits_a_title_chunk_first():
    item = SavedItem(source="s", source_id="1", title="标题", url="u", author="作者", tags=["x"])
    chunks = chunk_item(item, [])
    assert chunks[0].kind == "title"
    assert "标题" in chunks[0].text and "作者" in chunks[0].text and "x" in chunks[0].text


def test_chunk_item_deduplicates_repeated_text():
    item = SavedItem(source="s", source_id="1", title="t", url="u")
    repeated = [Segment(text="完全一样的一句话", start=i, end=i + 1) for i in range(6)]
    chunks = chunk_item(item, repeated, RetrievalConfig(chunk_chars=20, chunk_overlap_chars=0))
    assert len({chunk.id for chunk in chunks}) == len(chunks)
