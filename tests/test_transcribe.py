"""The Whisper fallback.

The model itself is not exercised here — downloading half a gigabyte and
decoding audio does not belong in a unit test. What is pinned instead is the
decision logic around it, which is where the bugs that cost real time live:
when it declines to run, and that missing dependencies degrade gracefully
rather than breaking ingest.
"""

import pytest

from chekhovsgun.config import WhisperConfig
from chekhovsgun.models import SavedItem
from chekhovsgun.transcribe import TranscriptionUnavailable, WhisperTranscriber


def _item(duration: int = 600, url: str = "https://youtu.be/abcdefghijk") -> SavedItem:
    return SavedItem(source="youtube", source_id="x", title="t", url=url, duration=duration)


def test_disabled_config_declines():
    transcriber = WhisperTranscriber(WhisperConfig(enabled=False))
    ok, reason = transcriber.should_transcribe(_item())
    assert not ok and "disabled" in reason
    assert transcriber.available is False


def test_long_videos_are_skipped():
    transcriber = WhisperTranscriber(WhisperConfig(max_duration_seconds=600))
    ok, reason = transcriber.should_transcribe(_item(duration=5400))
    assert not ok and "cap" in reason


def test_videos_within_the_cap_are_accepted():
    transcriber = WhisperTranscriber(WhisperConfig(max_duration_seconds=3600))
    ok, _ = transcriber.should_transcribe(_item(duration=1200))
    assert ok


def test_items_without_a_url_are_skipped():
    transcriber = WhisperTranscriber(WhisperConfig())
    ok, reason = transcriber.should_transcribe(_item(url=""))
    assert not ok and "url" in reason


def test_run_budget_stops_further_work():
    transcriber = WhisperTranscriber(WhisperConfig(run_budget_seconds=60))
    transcriber.start_run()
    transcriber._budget_spent = 90.0
    ok, reason = transcriber.should_transcribe(_item())
    assert not ok and "budget" in reason


def test_a_zero_budget_means_unlimited():
    transcriber = WhisperTranscriber(WhisperConfig(run_budget_seconds=0))
    transcriber.start_run()
    transcriber._budget_spent = 10_000.0
    ok, _ = transcriber.should_transcribe(_item())
    assert ok


def test_transcribe_raises_rather_than_running_when_declined():
    transcriber = WhisperTranscriber(WhisperConfig(enabled=False))
    with pytest.raises(TranscriptionUnavailable):
        transcriber.transcribe(_item())


def test_setup_hint_explains_what_is_missing():
    assert "disabled" in WhisperTranscriber(WhisperConfig(enabled=False)).setup_hint()


def test_ingest_continues_when_transcription_is_unavailable(engine):
    """A machine without faster-whisper must still index everything."""
    from tests.test_ingest import FakeAdapter

    engine.config.whisper.enabled = True
    adapter = FakeAdapter(
        engine.config,
        [SavedItem(source="fake", source_id="v1", title="一个没有字幕的视频 关于向量检索",
                   url="https://example.com/1", description="索引 召回")],
        fail_transcripts=True,
    )
    report = engine.ingest(adapter)
    assert report.failed == 0 and report.added == 1
    assert engine.store.item_chunks("fake:v1")


def test_transcript_source_is_recorded(seeded):
    item = seeded.store.list_items(limit=1)[0]
    assert item.transcript_source in {"captions", "none", ""}
