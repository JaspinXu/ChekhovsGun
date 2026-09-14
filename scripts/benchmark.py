#!/usr/bin/env python3
"""Synthetic scale benchmark.

Answers the only question that matters for the browser extension: at a realistic
library size, is a lookup fast enough to happen on every scroll without the user
noticing? Generates a throwaway library, then measures index build, cold cache
rebuild and warm query latency.

    python scripts/benchmark.py --items 2000
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chekhovsgun.config import load_config
from chekhovsgun.engine import Engine
from chekhovsgun.ingest import Indexer
from chekhovsgun.models import Context, SavedItem, Segment

TOPICS = [
    "数据库索引", "向量检索", "分布式共识", "前端渲染", "网络拥塞控制", "编译器优化",
    "机器学习训练", "容器编排", "消息队列", "缓存策略", "transformer attention",
    "garbage collection", "query planning", "stream processing", "type systems",
]
ZH = ["系统", "性能", "优化", "实现", "原因", "设计", "架构", "延迟", "吞吐", "一致性", "分区", "副本", "索引", "缓存", "队列", "调度"]
EN = ["system", "performance", "latency", "throughput", "replica", "consistency", "index", "cache", "queue", "scheduler"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=2000)
    parser.add_argument("--segments", type=int, default=25, help="subtitle segments per item")
    parser.add_argument("--queries", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    home = Path(tempfile.mkdtemp(prefix="chekhovsgun-bench-"))
    try:
        config = load_config(home)
        engine = Engine(config)
        indexer = Indexer(config, engine.store, engine.embedder)

        started = time.perf_counter()
        for i in range(args.items):
            topic = random.choice(TOPICS)
            item = SavedItem(
                source=random.choice(["youtube", "bilibili"]),
                source_id=f"bench{i}",
                title=f"{topic} 第 {i} 讲 " + " ".join(random.sample(ZH, 3)),
                url=f"https://example.com/{i}",
                author=f"UP{i % 50}",
                description=" ".join(random.sample(ZH + EN, 10)),
                folder=topic,
            )
            segments = [
                Segment(text=" ".join(random.sample(ZH + EN, 12)), start=j * 8.0, end=j * 8.0 + 8.0)
                for j in range(args.segments)
            ]
            indexer.index_item(item, segments)
        build = time.perf_counter() - started

        stats = engine.store.stats()
        print(f"library          {stats['items']} items · {stats['chunks']} chunks")
        print(f"index build      {build:.1f}s  ({stats['chunks'] / build:.0f} chunks/s)")

        engine.store._cache_revision = -1  # force a cold rebuild
        started = time.perf_counter()
        engine.retriever.search_items("向量检索 延迟", limit=5)
        print(f"cold query       {(time.perf_counter() - started) * 1000:.0f} ms (rebuilds indexes)")

        timings = []
        for _ in range(args.queries):
            query = f"{random.choice(TOPICS)} " + " ".join(random.sample(ZH, 2))
            started = time.perf_counter()
            engine.retriever.search_items(query, limit=5)
            timings.append((time.perf_counter() - started) * 1000)
        timings.sort()
        print(
            f"warm query       p50 {statistics.median(timings):.1f} ms · "
            f"p95 {timings[int(len(timings) * 0.95)]:.1f} ms · max {timings[-1]:.1f} ms"
        )

        started = time.perf_counter()
        for _ in range(20):
            engine.relate(
                Context(source="youtube", source_id="live", title=f"{random.choice(TOPICS)} 实践"),
                use_cache=False,
            )
        print(f"relate           {(time.perf_counter() - started) / 20 * 1000:.1f} ms avg")

        matrix = engine.store._matrix
        print(f"on disk          {os.path.getsize(config.db_path) / 1e6:.1f} MB")
        if matrix is not None:
            print(f"resident vectors {matrix.shape} = {matrix.nbytes / 1e6:.1f} MB")
        engine.close()
        return 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
