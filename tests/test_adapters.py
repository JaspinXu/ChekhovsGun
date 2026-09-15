import json

from chekhovsgun.adapters import context_from_url, detect_source, identify_url
from chekhovsgun.adapters.bilibili import BilibiliAdapter
from chekhovsgun.adapters.local import LocalFileAdapter
from chekhovsgun.adapters.youtube import (
    YouTubeAdapter,
    parse_iso_duration,
    parse_rfc3339,
)


class TestYouTubeUrls:
    def test_watch_url(self):
        assert YouTubeAdapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ&t=42s"
        assert YouTubeAdapter.parse_url(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert YouTubeAdapter.parse_url("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"

    def test_shorts_and_embed(self):
        assert YouTubeAdapter.parse_url("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
        assert YouTubeAdapter.parse_url("https://www.youtube.com/embed/abcdefghijk") == "abcdefghijk"

    def test_rejects_other_hosts(self):
        assert YouTubeAdapter.parse_url("https://vimeo.com/12345") == ""
        assert YouTubeAdapter.parse_url("") == ""


class TestBilibiliUrls:
    def test_bvid(self):
        assert BilibiliAdapter.parse_url("https://www.bilibili.com/video/BV1GJ411x7h7") == "BV1GJ411x7h7"

    def test_bvid_with_trailing_path_and_query(self):
        url = "https://www.bilibili.com/video/BV1GJ411x7h7/?spm_id_from=333.1007&p=2"
        assert BilibiliAdapter.parse_url(url) == "BV1GJ411x7h7"

    def test_avid_and_bangumi(self):
        assert BilibiliAdapter.parse_url("https://www.bilibili.com/video/av170001") == "av170001"
        assert BilibiliAdapter.parse_url("https://www.bilibili.com/bangumi/play/ep123") == "ep123"

    def test_rejects_other_hosts(self):
        assert BilibiliAdapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == ""


def test_detect_source_routes_to_the_right_adapter():
    assert detect_source("https://youtu.be/dQw4w9WgXcQ") == ("youtube", "dQw4w9WgXcQ")
    assert detect_source("https://www.bilibili.com/video/BV1GJ411x7h7") == ("bilibili", "BV1GJ411x7h7")
    assert detect_source("https://example.com") == ("", "")


def test_identify_url_names_post_sites_and_falls_back_for_the_rest():
    assert identify_url("https://youtu.be/dQw4w9WgXcQ") == ("youtube", "dQw4w9WgXcQ", "video")
    source, source_id, kind = identify_url(
        "https://www.zhihu.com/question/123/answer/456?utm_source=wechat"
    )
    assert (source, source_id, kind) == ("zhihu", "123-456", "post")
    # An unknown site is still identifiable — that is what lets relate answer
    # about a page no adapter has ever heard of.
    source, source_id, kind = identify_url("https://example.com/blog/hello")
    assert source == "web" and kind == "post" and len(source_id) == 16


def test_context_from_url():
    context = context_from_url("https://youtu.be/dQw4w9WgXcQ")
    assert context is not None and context.source == "youtube"
    # Any real URL now yields a context; only an unusable string yields None.
    assert context_from_url("https://example.com") is not None
    assert context_from_url("") is None


def test_parse_iso_duration():
    assert parse_iso_duration("PT1H2M3S") == 3723
    assert parse_iso_duration("PT45S") == 45
    assert parse_iso_duration("PT2M") == 120
    assert parse_iso_duration("P1DT1H") == 90000
    assert parse_iso_duration("") == 0
    assert parse_iso_duration("garbage") == 0


def test_parse_rfc3339():
    assert parse_rfc3339("2024-01-01T00:00:00Z") == 1704067200.0
    assert parse_rfc3339("nonsense") == 0.0


class TestBilibiliSubtitleSelection:
    def test_prefers_human_chinese_over_ai(self):
        tracks = [
            {"lan": "ai-zh", "ai_status": 2, "subtitle_url": "//ai"},
            {"lan": "zh-CN", "ai_status": 0, "subtitle_url": "//cc"},
        ]
        assert BilibiliAdapter._pick_track(tracks)["subtitle_url"] == "//cc"

    def test_falls_back_to_ai_when_that_is_all_there_is(self):
        tracks = [{"lan": "ai-en", "ai_status": 2, "subtitle_url": "//ai"}]
        assert BilibiliAdapter._pick_track(tracks)["subtitle_url"] == "//ai"

    def test_parses_a_subtitle_body(self):
        segments = BilibiliAdapter._parse_body(
            {"body": [{"from": 1.5, "to": 4.0, "content": "你好"}, {"content": "   "}]}
        )
        assert len(segments) == 1
        assert segments[0].text == "你好" and segments[0].start == 1.5


class TestYouTubeCaptions:
    def test_parses_json3_events(self):
        segments = YouTubeAdapter._parse_json3(
            {
                "events": [
                    {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
                    {"tStartMs": 4000, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 5000},
                ]
            }
        )
        assert len(segments) == 1
        assert segments[0].text == "hello world"
        assert segments[0].start == 1.0 and segments[0].end == 3.0


class TestLocalAdapter:
    def test_imports_json_and_detects_the_real_source(self, config, tmp_path):
        path = tmp_path / "saves.json"
        path.write_text(
            json.dumps(
                [{"url": "https://youtu.be/dQw4w9WgXcQ", "title": "T", "channel": "C",
                  "transcript": [{"start": 0, "duration": 2, "text": "hi there"}]}]
            ),
            encoding="utf-8",
        )
        items = list(LocalFileAdapter(config, path).list_saved())
        assert len(items) == 1
        assert items[0].source == "youtube" and items[0].source_id == "dQw4w9WgXcQ"
        assert items[0].author == "C"
        assert [s.text for s in LocalFileAdapter(config, path).fetch_content(items[0])] == ["hi there"]

    def test_imports_a_plain_url_list(self, config, tmp_path):
        path = tmp_path / "urls.txt"
        path.write_text(
            "# comment\nhttps://www.bilibili.com/video/BV1GJ411x7h7\n\n", encoding="utf-8"
        )
        items = list(LocalFileAdapter(config, path).list_saved())
        assert len(items) == 1 and items[0].source == "bilibili"
