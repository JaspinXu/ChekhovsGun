from chekhovsgun.rag.text import normalize, sentences, snippet, tokenize


def test_normalize_folds_fullwidth_and_case():
    assert normalize("ＨＥＬＬＯ　Ｗｏｒｌｄ") == "hello world"
    assert normalize("  a\n\n b ") == "a b"


def test_tokenize_emits_cjk_unigrams_and_bigrams():
    tokens = tokenize("注意力机制")
    assert "注" in tokens and "意" in tokens
    assert "注意" in tokens and "意力" in tokens


def test_tokenize_splits_hyphenated_terms():
    tokens = tokenize("self-attention")
    assert {"self-attention", "self", "attention", "selfattention"} <= set(tokens)


def test_tokenize_keeps_latin_words_and_numbers():
    tokens = tokenize("GPT-4 scales to 128k context")
    assert "gpt" in tokens and "gpt4" in tokens and "128k" in tokens


def test_tokenize_drops_stopwords():
    assert "the" not in tokenize("the quick brown fox")
    assert "的" not in tokenize("很好的东西")


def test_tokenize_handles_mixed_scripts():
    tokens = tokenize("用 Transformer 做中文分词")
    assert "transformer" in tokens
    assert "分词" in tokens and "中文" in tokens


def test_tokenize_drops_chinese_function_bigrams():
    """Without this, a cooking query "matches" a database talk: both say 还是."""
    from chekhovsgun.rag.text import is_function_token

    for token in ("还是", "就是", "这个", "怎么", "可以", "什么"):
        assert is_function_token(token), token
    for token in ("数据", "向量", "索引", "分词"):
        assert not is_function_token(token), token


def test_script_detection():
    from chekhovsgun.rag.text import script_of

    assert script_of("How Vector Databases Actually Work") == "latin"
    assert script_of("注意力机制详解与位置编码") == "cjk"
    assert script_of("ab") == "mixed"


def test_sentences_splits_on_cjk_and_latin_terminators():
    assert sentences("第一句。第二句！Third one. Fourth") == [
        "第一句。",
        "第二句！",
        "Third one.",
        "Fourth",
    ]


def test_snippet_centres_on_the_query_term():
    body = "前置内容 " * 30 + "关键词出现在这里" + " 后置内容" * 30
    out = snippet(body, "关键词", width=60)
    assert "关键词" in out
    assert len(out) <= 64


def test_snippet_returns_short_text_untouched():
    assert snippet("短文本", "任何", width=100) == "短文本"
