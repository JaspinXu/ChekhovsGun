# 藏知 · ChekhovsGun

[English](README.md) · **简体中文**

> 如果第一幕墙上挂着一把枪，第三幕它就必须开火。
> 你收藏的每一条内容，也应该如此。

**你收藏过的东西，会在你刷视频刷到相关内容时自己跳出来找你。**

我们都干过同一件事：刷到一个讲得特别好的教程，点了收藏，想着"以后一定看"，
然后它就永远躺在收藏夹里了。藏知把这件事反过来做——不需要你想起来去翻收藏夹，
而是在你**正在刷**相关视频的那一刻，告诉你「这个你收藏过」，并把当时那条内容里
相关的段落直接讲给你听。

全部在本地运行。你的收藏夹和观看记录不会离开这台机器。

<!-- 目前支持 YouTube 与 哔哩哔哩，两边的收藏可以互相触发：
     刷英文视频时弹出你收藏的中文讲解，反之亦然。 -->

---

## 它是怎么工作的

```
  收藏夹                     索引                        刷视频时
┌──────────┐   字幕/简介   ┌──────────────┐          ┌──────────────┐
│ YouTube  │──────────────▶│  分块 + 向量  │          │ 浏览器扩展    │
│ 收藏夹    │               │  + BM25 倒排  │◀─────────│ 识别当前视频  │
│ Bilibili │──────────────▶│   SQLite     │  混合检索 │              │
└──────────┘               └──────────────┘          └──────┬───────┘
                                   │                        │
                                   └────── 命中的收藏 ───────▶│ 弹出卡片
                                          + 一段解读          └──────────┘
```

1. **抓取** — 从 YouTube 播放列表 / Liked / Watch Later 和 B 站收藏夹、稍后再看
   拉取你保存过的视频，连同字幕（B 站 CC 字幕与 AI 字幕都要）、以及**高赞评论**。
   完全没有字幕的视频，会用本地 Whisper 转写兜底。
2. **索引** — 按时间轴把字幕切成带时间戳的段落，算向量，同时建 BM25 倒排。
3. **检索** — 混合检索 + RRF 融合，再用一个独立的**置信度**决定「到底要不要打扰你」。
4. **开火** — 浏览器扩展识别你当前在看的视频，命中就弹一张卡片，
   点进去直接跳到收藏视频里讲这件事的那一秒。
5. **收枪** — 看完了点一下「已消化」，它就不会再来烦你。
   这个数字（而不是弹出次数）才是这个项目的成功指标。

---

## 30 秒跑起来

不需要任何 API key，先看看它长什么样：

```bash
git clone https://github.com/JaspinXu/ChekhovsGun.git
cd ChekhovsGun
pip install -e .

chekhovsgun demo      # 灌一批示例收藏，并演示一次检索
chekhovsgun tray      # 后台常驻 + 托盘图标，自动打开仪表盘
```

不想装 Python 的话，[Releases](https://github.com/JaspinXu/ChekhovsGun/releases)
里有打包好的单文件程序，双击即可；`chekhovsgun serve` 仍然是等价的前台版本。

`demo` 会输出类似这样的东西：

```
pretending you just scrolled onto:
  Why is my retrieval so bad? Chunking and hybrid search explained

  ChekhovsGun says:
    You already saved 1 related item(s); the closest is “How Vector Databases
    Actually Work” by Engineering Deep Dives. From it: …the real failure mode of
    pure vector search is exact terminology. Hybrid search with BM25 fixes the
    cases where embeddings blur a precise term.

  1. How Vector Databases Actually Work
     Engineering Deep Dives · youtube · Watch Later · score 1.00
     https://www.youtube.com/watch?v=Xpzbywj7HbQ&t=1000s
     [16:40] The real failure mode of pure vector search is exact terminology…
```

中文查询同样会命中英文收藏，反过来也一样——这正是同时接 B 站和 YouTube 的意义。

---

## 接上你自己的收藏夹

### 哔哩哔哩

B 站没有公开 API，所以用你浏览器里的 cookie。在已登录的 bilibili.com 页面按
F12 → Application → Cookies，复制 `SESSDATA`：

```bash
export CHEKHOVSGUN_BILIBILI_SESSDATA="你的 SESSDATA"
export CHEKHOVSGUN_BILIBILI_UID="你的 uid"        # 可选，不填会自动探测

chekhovsgun ingest --source bilibili --limit 20   # 先拿 20 条试试
chekhovsgun ingest --source bilibili              # 全量同步
```

默认会同步**所有**自建收藏夹 + 稍后再看。只要某几个收藏夹的话：

```bash
export CHEKHOVSGUN_BILIBILI_FOLDERS="深度学习,后端"   # 收藏夹名或 media_id
```

> SESSDATA 有效期约一个月，过期后重新复制一次即可。
> 它只保存在你自己的环境变量或 `config.toml` 里，不会发到任何地方。

### YouTube

公开/不公开播放列表用 API key 就够了（Google Cloud → 启用 YouTube Data API v3）：

```bash
export CHEKHOVSGUN_YOUTUBE_API_KEY="AIza..."
export CHEKHOVSGUN_YOUTUBE_PLAYLISTS="PLxxxxxxxx,PLyyyyyyyy"

chekhovsgun ingest --source youtube
```

Liked（`LL`）和 Watch Later（`WL`）是账号私有的，需要 OAuth access token：

```bash
export CHEKHOVSGUN_YOUTUBE_OAUTH_TOKEN="ya29..."
chekhovsgun ingest --source youtube      # 不指定播放列表时自动抓 LL 和 WL
```

字幕推荐装上官方社区的库，覆盖率更高：

```bash
pip install -e ".[youtube]"
```

### 都不想配？

任何 json / jsonl / csv / 纯链接列表都能直接导入：

```bash
chekhovsgun import my-saves.json          # 支持 Google Takeout 导出
chekhovsgun import urls.txt               # 一行一个链接
```

---

## 装上浏览器扩展

1. Chrome / Edge 打开 `chrome://extensions`
2. 打开右上角「开发者模式」
3. 点「加载已解压的扩展程序」，选择本仓库的 `extension/` 目录
4. 确保 `chekhovsgun serve` 正在运行

之后你在 YouTube 或 B 站上打开任何视频，如果收藏夹里有相关内容，
右下角会浮出一张卡片。点击标题栏折叠，点 × 关闭，
「这个视频不再提示」会把它静音到浏览器重启。

扩展只访问 `http://127.0.0.1:8700`，不做任何其他网络请求。
端口、冷却时间、每个站点是否启用，都可以在扩展的选项页里改。

---

## 三个内容源

**字幕**是主力。B 站的 CC 字幕和 AI 字幕都收，人工优先；YouTube 走播放器那条路。

**评论**是被大多数同类工具忽略的一座金矿。高赞评论里常有视频本身没有的东西：
勘误、UP 跳过的前置知识、"其实 7.0 之后已经不是这样了"。而且它是纯文本，
一个请求就能拿到，是这个项目里性价比最高的内容。

```bash
chekhovsgun ingest --no-comments    # 不想要的话
```

**本地语音转写**是兜底。真实收藏夹里大约三分之一的视频两种字幕都没有，
这些以前只能靠标题和简介入库，既检索不准也没法跳转。现在用 faster-whisper
在本地补上：

```bash
pip install -e ".[whisper]"     # faster-whisper + yt-dlp
chekhovsgun ingest --source bilibili
```

音频不出本机。因为转写是分钟级而不是毫秒级的，它有两道闸：单个视频超过 45 分钟
就跳过，每次同步最多花 30 分钟在转写上（都可配置）。它挂在管线上而不是某个
adapter 里——只要有 URL 就能用，所以以后加第三个来源时是白送的。

---

## 收藏的一生

一件收藏有三个状态，用来回答「开火之后呢」：

| 状态 | 含义 | 还会弹吗 | 算进消化率吗 |
| --- | --- | --- | --- |
| 待消化 | 默认 | 会 | — |
| **已消化** | 你回去看完了，学到了 | 不会 | **算** |
| 已静音 | 别再拿这个烦我 | 不会 | 不算 |

```bash
chekhovsgun mark https://www.bilibili.com/video/BV1xx --digested --tag 注意力
chekhovsgun items --status active          # 还欠着的
chekhovsgun items --tag 注意力
```

卡片上直接有「✓ 已消化」按钮，仪表盘里也能按状态和标签筛。

两个设计细节：**静音只停止打扰，不影响检索**——你主动搜的时候它照样出来；
**重新同步永远不会覆盖你的标记**，`upsert` 刻意不碰 `status` / `user_tags` / `note`
这三列，否则每晚一次同步就会把你消化过的东西又翻出来。

---

## 检索是怎么做的（以及为什么这么做）

这部分是整个项目里真正需要动脑子的地方。

**混合检索。** 默认的向量后端是一个零依赖的哈希 n-gram 编码器——克隆下来就能用，
不需要 API key，不需要下模型。代价是它没有真正的语义，
容易被「语域相同但主题无关」的文本骗到。BM25 的失败模式正好相反：
它对专有名词（`KV cache`、`BV1xx4y1`）极准，但完全不懂同义改写。
两个一起用，再用 **RRF** 融合——RRF 只看排名不看分数，
所以不需要校准两条完全不同量纲的分数，也不会被一个离群分数带偏。

**中文分词。** 中文没有空格，直接按空白切会把一整句话变成一个 token。
这里用的是 CJK **字符二元组** + 拉丁词的组合，向量和 BM25 共用同一套分词，
保证两条召回路径看到的是同一份文本。

**置信度与排序是两件事。** RRF 分数只能排序，不能回答「这到底要不要弹出来」——
它的取值范围随语料规模漂移。所以另算了一个 0~1 的**置信度**：
向量余弦 × 查询词的 IDF 加权覆盖率，两者都不高就判定为无关。
几个关键细节：

- **语料里没出现过的词不计入分母。** "How I made my React app 10x faster"
  只应该按 `react` 来判断，而不是被四个收藏里根本不可能出现的词稀释掉。
- **按书写系统分开算覆盖率。** 中文查询词永远不可能出现在英文字幕里，
  把它算进分母会让所有跨语言命中看起来都不相关——
  而跨语言恰恰是这个项目最有价值的场景。
- **单个词的匹配不算证据。**「红烧肉的做法」和一个 Redis 讲解都含有「做法」。
  覆盖率按命中词数做饱和衰减，一个词最多只能拿到约 56% 的分。

**每个收藏最多贡献 N 个片段。** 一个 40 分钟的讲座会切出几十个几乎一样的块。
教科书答案是 MMR，但在这里是错的：结果最终要按**收藏**聚合，
同一个收藏的多个片段是互相印证的证据，而 MMR 会把它们删掉——
实测中它删掉的正是命中最好的那一段。改成按收藏限流，效果好得多。

想要更好的效果，换一个真正的多语言编码器就行，一行配置：

```bash
pip install -e ".[neural]"
export CHEKHOVSGUN_EMBEDDING_BACKEND=sentence-transformers
chekhovsgun reindex
```

或者任何 OpenAI 兼容的 embedding 接口（DashScope / SiliconFlow / Ollama / vLLM）：

```bash
export CHEKHOVSGUN_EMBEDDING_BACKEND=openai
export CHEKHOVSGUN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export CHEKHOVSGUN_EMBEDDING_API_KEY=sk-...
export CHEKHOVSGUN_EMBEDDING_MODEL=text-embedding-v3
chekhovsgun reindex
```

### 性能

在一个合成的 2000 条收藏 / 15555 个片段的库上（`python scripts/benchmark.py`）：

| 指标 | 数值 |
| --- | --- |
| 建索引 | 10.3 s（约 1500 片段/秒，含分词与向量化） |
| 冷启动（重建内存索引） | 1.5 s |
| 检索 p50 / p95 | **6.1 ms / 8.0 ms** |
| 完整 relate（含解读） | 7.3 ms |
| 磁盘 | 65 MB |
| 常驻内存（向量矩阵） | 32 MB |

几个让它变快的点，都是实测出来的而不是猜的：

- **BM25 走 numpy。** 中文分词会产生字符一元组，常见字的倒排链有上万条，
  用 Python 循环遍历一次查询要 56ms——占了整个查询耗时的 90%。
  改成 numpy 数组 + 花式索引累加后降到 6ms。
- **跳过高频词。** 出现在超过 35% 片段里的 token 直接跳过：
  它们的 IDF 接近零，改变不了排序，却背着最长的倒排链。
- **分词结果落库。** 1.5 万个片段分词一次要 6 秒，原来每次重建内存索引都要做一遍；
  现在写入时算好存进 SQLite，冷启动降到 1.5 秒。
- **缓存键用写计数器。** 之前每个请求都跑六条 COUNT，换成 store 的单调写计数器后是零成本。

---

## 那段"解读"

命中之后卡片上会有一段话，说明这条收藏和你正在看的东西是什么关系、
回去看能多得到什么。配了 LLM 就用 LLM 生成，没配就直接摘录字幕原文——
**摘录永远不会编造内容**，所以默认路径是安全的，弹窗也不会卡在加载中。

```bash
export CHEKHOVSGUN_LLM_API_KEY=sk-...
export CHEKHOVSGUN_LLM_MODEL=gpt-4o-mini
export CHEKHOVSGUN_LLM_BASE_URL=            # 任何 OpenAI 兼容端点
```

---

## 命令行

| 命令 | 作用 |
| --- | --- |
| `chekhovsgun demo` | 灌示例数据并跑一次检索 |
| `chekhovsgun status` | 看库存、消化率、各来源是否配好 |
| `chekhovsgun ingest [--source X] [--limit N] [--force]` | 同步收藏 |
| `chekhovsgun ingest --whisper` / `--no-comments` | 强制本地转写 / 跳过评论 |
| `chekhovsgun import <file>` | 从 json/jsonl/csv/txt 导入 |
| `chekhovsgun search "查询"` | 搜自己的收藏 |
| `chekhovsgun relate <url>` | 模拟：刷到这个视频会弹什么 |
| `chekhovsgun mark <url> --digested` | 标记已消化 / 静音 / 打标签 |
| `chekhovsgun items --status active` | 列出还欠着的收藏 |
| `chekhovsgun tray` | 后台常驻，托盘图标 |
| `chekhovsgun serve [--open]` | 前台起服务 + 仪表盘 |
| `chekhovsgun reindex` | 换了 embedding 后重建向量 |

---

## 数据放在哪

| 内容 | 位置 |
| --- | --- |
| 索引数据库 | `$CHEKHOVSGUN_HOME/index.db`（默认 `~/.chekhovsgun/`，Windows 在 `%LOCALAPPDATA%`） |
| 配置 | 同目录下的 `config.toml`，或环境变量（见 `.env.example`） |
| 凭据 | 只在你的环境变量/配置文件里；API 返回时一律打码 |

服务只监听 `127.0.0.1`。没有遥测，没有外部上报。

---

## 开发

```bash
pip install -e ".[dev]"
pytest                      # 全部测试
pytest tests/test_relevance.py -v   # 检索质量的黄金集回归
```

`tests/test_relevance.py` 是最值得看的一个文件：它把「该弹」和「不该弹」
的具体例子钉死了，包括跨语言的。任何检索改动只要破坏了其中一条就会红。

想加第三个来源（小红书、知乎、Pocket……），只需要实现
`chekhovsgun/adapters/base.py` 里的三个方法：列出收藏、取正文、认 URL。
其余代码不知道 chunk 是从哪来的。

---

## 打包

```bash
pip install -e ".[tray]" pyinstaller
pyinstaller chekhovsgun.spec        # → dist/ChekhovsGun(.exe)
```

打出来的单文件双击就是托盘模式；带参数运行时它仍然是完整的 CLI
（`ChekhovsGun.exe ingest --source bilibili`），所以一个二进制两用。
打 tag 推上去会由 CI 自动构建三个平台的产物和扩展压缩包。

## 已知限制

- 默认的哈希编码器没有真正的语义。跨语言、同义改写这类场景建议换神经编码器（上面有）。
- B 站 SESSDATA 约一个月过期；YouTube OAuth token 一小时过期，长期同步需要自己刷新。
- Whisper 兜底需要本机有 ffmpeg，且是 CPU 密集的；第一次运行会下载模型。
- YouTube 评论走 Data API，关闭评论的视频返回 403，这是正常的，会跳过。
- 扩展在 YouTube Shorts 上可用，但竖屏信息流切换很快，默认 1.4 秒防抖可能仍偏敏感。
- 桌面浏览器不是大多数人刷信息流的地方——手机端才是，那是另一个工程。

## License

MIT

## 参考

设计上借鉴了两个项目：[藏知 Studio](https://github.com/Y-iyilin/zangzhi-studio)
（评论作为一等内容源、本地语音转写、local-first 的定位）和
[拾光](https://github.com/zihuv/shiguang)（打包成安装包分发、标签与整理这套库管理）。
两者解决的问题都和本项目不同，但那几个判断是对的。
