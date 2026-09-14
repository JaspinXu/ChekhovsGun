"""A golden set for the relevance gate.

These are the cases that actually matter in production: the popup must fire on
a genuinely related save (including across languages), and must stay silent
otherwise. Retrieval changes that look harmless in isolation tend to break
exactly one of these, which is why they are pinned here rather than checked by
hand.
"""

import pytest

# (query, titles that must surface, titles that must NOT surface)
GOLDEN = [
    pytest.param(
        "手把手教你做一个 RAG 检索系统：分块、向量召回与重排",
        ["RAG 检索不准"], ["Monad", "React", "B-Tree"], id="zh-rag",
    ),
    pytest.param(
        "Self-attention explained visually: queries, keys and values",
        ["Transformer 论文"], ["SQLite", "React", "Monad"], id="en-query-zh-save",
    ),
    pytest.param(
        "向量数据库 HNSW 近似最近邻搜索原理",
        ["Vector Databases"], ["React", "Monad"], id="zh-query-en-save",
    ),
    pytest.param(
        "MySQL 复合索引为什么失效？最左前缀原则详解",
        ["B-Tree"], ["Monad", "React", "Transformer"], id="zh-index",
    ),
    pytest.param(
        "How I made my React app 10x faster",
        ["React Performance"], ["SQLite", "Transformer", "Monad"], id="en-react",
    ),
    pytest.param(
        "单文件数据库能不能扛住生产流量？WAL 并发实测",
        ["SQLite"], ["React", "Monad", "Transformer"], id="zh-sqlite",
    ),
    pytest.param(
        "Haskell 里的 functor applicative monad 到底是什么",
        ["Monad"], ["React", "SQLite", "B-Tree"], id="mixed-monad",
    ),
    pytest.param(
        "大模型预训练的 scaling law 是怎么回事",
        ["Large Language Models"], ["React", "SQLite", "Monad"], id="zh-llm",
    ),
    pytest.param(
        "docker 容器之间怎么通过名字互相访问",
        ["Docker Networking"], ["React", "Monad", "Transformer"], id="zh-docker",
    ),
    pytest.param(
        "Kubernetes 调度器是怎么选节点的",
        ["Kubernetes"], ["React", "Monad", "CSS"], id="zh-k8s",
    ),
    pytest.param(
        "Redis 到底用 RDB 还是 AOF",
        ["Redis"], ["React", "Monad", "Transformer"], id="zh-redis",
    ),
    pytest.param(
        "红烧肉的做法，先焯水还是先煎",
        [], ["Redis", "Python", "Transformer", "React", "SQLite"], id="unrelated-cooking-2",
    ),
    pytest.param(
        "周末去爬山的 vlog，风景真好",
        [], ["Redis", "Python", "Transformer", "React", "SQLite", "Docker"], id="unrelated-vlog",
    ),
    pytest.param(
        "今天做了个番茄炒蛋，家常菜教程，先放糖还是先放盐",
        [], ["Transformer", "React", "SQLite", "Monad", "B-Tree", "RAG", "Vector"],
        id="unrelated-cooking",
    ),
    pytest.param(
        "猫咪第一次剪指甲的全过程记录",
        [], ["Transformer", "React", "SQLite", "Monad", "B-Tree", "RAG", "Vector"],
        id="unrelated-cats",
    ),
]


@pytest.mark.parametrize("query,expected,forbidden", GOLDEN)
def test_relevance_golden_set(seeded, query, expected, forbidden):
    titles = [hit.item.title for hit in seeded.search(query, limit=5)]
    for want in expected:
        assert any(want in title for title in titles), f"{want!r} missing from {titles}"
    for avoid in forbidden:
        assert not any(avoid in title for title in titles), f"{avoid!r} should not surface"


def test_the_best_match_ranks_first(seeded):
    """Ranking, not just recall: the obvious answer has to be the top result."""
    for query, expected in [
        ("向量数据库 HNSW 近似最近邻搜索原理", "Vector Databases"),
        ("MySQL 复合索引为什么失效？最左前缀原则详解", "B-Tree"),
        ("RAG 分块策略与重排序", "RAG 检索不准"),
        ("WAL 模式下的写并发", "SQLite"),
        ("asyncio 为什么不能跑 CPU 密集任务", "Python 异步"),
        ("git rebase 会不会把提交历史搞乱", "Git rebase"),
        ("How does BBR congestion control work", "TCP Congestion"),
        ("TypeScript 条件类型和 infer 怎么用", "TypeScript"),
        ("CSS 布局应该用 grid 还是 flex", "CSS Grid"),
    ]:
        hits = seeded.search(query, limit=5)
        assert hits, query
        assert expected in hits[0].item.title, f"{query!r} -> {hits[0].item.title!r}"


def test_confidence_separates_related_from_unrelated(seeded):
    related = seeded.search("RAG 分块 重排 混合检索", limit=1)
    assert related and related[0].confidence > 0.45
    for unrelated in ("红烧肉的做法", "猫咪第一次剪指甲全过程", "周末爬山 vlog 风景"):
        assert seeded.search(unrelated, limit=5) == [], unrelated
