# 架构

```
chekhovsgun/
├── models.py          SavedItem / Chunk / Hit / ItemHit / Context
├── config.py          环境变量 + config.toml + 默认值
├── http.py            带退避和限速的共享 HTTP 客户端
├── engine.py          门面：CLI 和服务端都只跟它打交道
├── ingest.py          适配器 → 字幕 → 分块 → 向量 → 索引（增量）
├── cli.py             命令行
├── adapters/
│   ├── base.py        SourceAdapter 抽象：三个方法
│   ├── youtube.py     播放列表 + 字幕
│   ├── bilibili.py    收藏夹 + CC/AI 字幕
│   ├── wbi.py         B 站 WBI 签名
│   └── local.py       json/jsonl/csv/txt 导入
├── rag/
│   ├── text.py        中英混合分词、停用词、书写系统判定
│   ├── chunker.py     按字数 + 时长双约束切分，保留时间戳
│   ├── embeddings.py  local / openai / sentence-transformers
│   ├── store.py       SQLite + 内存向量矩阵 + BM25 倒排
│   └── retriever.py   混合检索、RRF 融合、置信度、按收藏聚合
├── llm/explain.py     可选的解读生成，默认降级为原文摘录
└── server/            FastAPI + 仪表盘
extension/             MV3 浏览器扩展
```

## 几个设计选择

**为什么是 SQLite 而不是向量数据库。** 个人收藏夹是几千个片段的量级，
不是几百万。一个文件、零服务、随便备份；一个 float32 矩阵在内存里暴力算余弦，
十万片段也就几毫秒，远低于扩展需要的延迟。真到了需要 ANN 的规模再说。

**缓存靠 revision 计数器。** `Store` 每次写操作递增一个计数器，
向量矩阵和 BM25 统计在计数器变化时才重建。长时间跑的服务端不会反复读库。

**增量同步。** 每个条目算一个内容哈希（只包含会影响分块的字段）。
没变的条目跳过取字幕和算向量——取字幕是整个流程里最慢、最容易被限流的一步，
每晚同步两千条的库应该只动真正变了的那些。

**扩展通过 service worker 请求。** content script 直接请求 127.0.0.1 也可以
（浏览器把回环地址当作安全来源，不触发混合内容拦截），
但走 service worker 可以完全绕开页面自身的 CSP，
并且把缓存、防抖、设置集中在一个地方。

**UI 放在 shadow DOM 里。** YouTube 和 B 站都有很强的全局样式，
影子树是保证卡片在两边长得一样、且不污染页面的唯一可靠方式。

## 检索链路

```
查询文本
  ├─▶ 向量召回 (top 160)  ─┐
  └─▶ BM25 召回  (top 160) ─┴─▶ RRF 融合 ─▶ 片段类型加权
                                              │
                        每个收藏最多 N 个片段 ◀─┘
                                              │
                                   按收藏聚合 ─┴─▶ 置信度 = f(余弦, IDF 覆盖率)
                                                        │
                                         置信度门槛 + 相对分数门槛
                                                        │
                                          按 0.2·分数 + 0.8·置信度 排序
```

置信度和排序分数是两个不同的东西，理由见 README 的「检索是怎么做的」。
`tests/test_relevance.py` 把这条链路的行为钉成了黄金集回归。
