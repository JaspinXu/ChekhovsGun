from __future__ import annotations

from chekhovsgun.extract import MIN_BODY_CHARS, extract, weighted_len

ZHIHU = """
<html><head>
  <title>为什么混合检索比纯向量好 - 知乎</title>
  <meta property="og:title" content="为什么混合检索比纯向量好">
  <meta name="author" content="某位答主">
</head><body>
  <nav class="AppHeader"><a href="/">首页</a><a href="/hot">热榜</a><a href="/explore">发现</a></nav>
  <div class="Sidebar"><a href="/a">相关问题一</a><a href="/b">相关问题二</a><a href="/c">更多相关</a></div>
  <div class="RichText ztext Post-RichText">
    <p>纯向量检索最大的失败模式是专有名词。嵌入会把精确的术语抹平，导致 KV cache 这样的词被当成普通短语处理。</p>
    <p>BM25 的失败模式正好相反：它对专有名词极准，但完全不理解同义改写。两者的错误几乎不重叠。</p>
    <p>所以把两路召回用 RRF 融合，只看排名不看分数，就不需要校准两条量纲完全不同的分数线。</p>
  </div>
  <div class="Comments"><a href="/u1">用户甲</a><span>写得好</span></div>
  <footer><a href="/about">关于</a><a href="/terms">条款</a></footer>
</body></html>
"""

ENGLISH = """
<html><head><title>Chunking strategies</title></head><body>
<header><a href="/">Home</a><a href="/blog">Blog</a><a href="/about">About</a></header>
<article class="post-content">
  <p>Fixed-size chunking is the default for a reason: it is predictable and it never
     surprises you with a chunk that will not fit the context window.</p>
  <p>The cost is that it cuts sentences in half. Overlap papers over that, at the price
     of indexing the same words more than once and letting one document dominate.</p>
</article>
<div class="related"><a href="/x">Read this next</a><a href="/y">And this</a></div>
</body></html>
"""


class TestWeightedLength:
    def test_cjk_counts_for_more_than_a_latin_character(self):
        # 40 Chinese characters say about as much as 100 English ones, and a
        # threshold that cannot tell them apart rejects real Chinese articles.
        assert weighted_len("研究表明") == 10
        assert weighted_len("abcd") == 4

    def test_mixed_text_adds_up(self):
        assert weighted_len("KV cache 缓存") == len("KV cache ") + 5


class TestExtract:
    def test_keeps_the_article_and_drops_the_chrome(self):
        result = extract(ZHIHU)
        assert "纯向量检索最大的失败模式" in result.text
        assert "RRF 融合" in result.text
        for noise in ("热榜", "相关问题一", "写得好", "条款"):
            assert noise not in result.text

    def test_reads_metadata(self):
        result = extract(ZHIHU)
        assert result.title == "为什么混合检索比纯向量好"
        assert result.author == "某位答主"

    def test_a_chinese_article_is_long_enough_to_count(self):
        result = extract(ZHIHU)
        assert bool(result) is True
        assert result.note == ""

    def test_english_article_survives_its_navigation(self):
        result = extract(ENGLISH)
        assert "Fixed-size chunking is the default" in result.text
        assert "Read this next" not in result.text
        assert "Home" not in result.text
        assert bool(result) is True

    def test_paragraphs_stay_on_separate_lines(self):
        # The capture path splits on newlines to build segments, so losing the
        # breaks would merge an entire article into one unsplittable chunk.
        assert len([line for line in extract(ZHIHU).text.split("\n") if line]) == 3

    def test_a_page_with_no_article_reports_why(self):
        result = extract("<html><body><nav><a href='/'>Home</a></nav></body></html>")
        assert not result
        assert result.note == "no article-shaped block found"

    def test_malformed_markup_does_not_raise(self):
        result = extract("<div><p>unclosed paragraph <div>and a nested div" + "x" * 300)
        assert isinstance(result.text, str)

    def test_scripts_and_styles_never_reach_the_text(self):
        html = (
            "<html><body><script>var secret = 'do not index me';</script>"
            "<style>.a{color:red}</style>"
            f"<article><p>{'real prose about retrieval. ' * 12}</p></article></body></html>"
        )
        result = extract(html)
        assert "do not index me" not in result.text
        assert "color:red" not in result.text
        assert weighted_len(result.text) >= MIN_BODY_CHARS
