from __future__ import annotations

import pytest

from chekhovsgun.sites import canonical_url, identify, label_for, url_digest


class TestCanonicalUrl:
    def test_strips_tracking_parameters_but_keeps_real_ones(self):
        url = (
            "https://www.zhihu.com/question/123/answer/456"
            "?utm_source=wechat&spm_id_from=333.999&sort=created&from=search"
        )
        assert canonical_url(url) == "https://zhihu.com/question/123/answer/456?sort=created"

    def test_drops_the_fragment(self):
        # Our own deep links append a text fragment. If canonicalisation kept
        # it, following one and re-saving the page would create a second item.
        assert (
            canonical_url("https://example.com/post#:~:text=hello%20there")
            == "https://example.com/post"
        )

    def test_normalises_scheme_host_case_and_trailing_slash(self):
        assert canonical_url("HTTP://WWW.Example.COM/Path/") == "https://example.com/Path"

    def test_bare_host_gets_a_scheme(self):
        assert canonical_url("example.com/x") == "https://example.com/x"

    def test_keeps_a_non_default_port(self):
        assert canonical_url("http://localhost:8700/a") == "https://localhost:8700/a"

    def test_empty_stays_empty(self):
        assert canonical_url("") == ""
        assert canonical_url("   ") == ""

    @pytest.mark.parametrize(
        "a, b",
        [
            (
                "https://www.bilibili.com/video/BV1xx?spm_id_from=333.1007&vd_source=abc",
                "https://bilibili.com/video/BV1xx/",
            ),
            (
                "https://xiaohongshu.com/explore/abc123?xhsshare=CopyLink&appuid=9",
                "https://www.xiaohongshu.com/explore/abc123",
            ),
        ],
    )
    def test_share_links_and_clean_links_agree(self, a, b):
        assert canonical_url(a) == canonical_url(b)
        assert url_digest(a) == url_digest(b)


class TestIdentify:
    def test_zhihu_answer_gets_a_readable_id(self):
        assert identify("https://www.zhihu.com/question/123/answer/456") == (
            "zhihu", "123-456", "post",
        )

    def test_zhihu_column_post(self):
        assert identify("https://zhuanlan.zhihu.com/p/987654")[:2] == ("zhihu", "987654")

    def test_subdomains_resolve_to_the_parent_site(self):
        # m.zhihu.com is the same site; a phone share link must not create a
        # second copy of an answer already saved from the desktop.
        assert identify("https://m.zhihu.com/question/1/answer/2")[0] == "zhihu"

    def test_known_site_without_an_id_pattern_still_names_the_site(self):
        source, source_id, kind = identify("https://mp.weixin.qq.com/s/AbCdEf")
        assert source == "wechat" and kind == "post" and len(source_id) == 16

    def test_unknown_site_falls_back_to_a_hashed_web_id(self):
        source, source_id, kind = identify("https://some-blog.example/2024/post")
        assert source == "web" and kind == "post" and len(source_id) == 16

    def test_the_same_page_always_identifies_identically(self):
        first = identify("https://example.com/a?utm_source=x")
        second = identify("https://www.example.com/a/")
        assert first == second

    def test_empty_url_identifies_as_nothing(self):
        assert identify("")[0] == ""


def test_label_for_names_known_sites_and_shrugs_at_the_rest():
    assert label_for("zhihu") == "知乎"
    assert label_for("web") == "网页 / Web"
    assert label_for("bilibili") == "bilibili"
