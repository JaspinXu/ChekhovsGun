# YouTube 接入笔记

## 两条路径

YouTube 把「列出你收藏了什么」和「拿到字幕」放在了两个完全不同的体系里。

### 列表：YouTube Data API v3

- **API key** 能读任何公开或不公开（unlisted）的播放列表。
  在 Google Cloud Console 建项目 → 启用 *YouTube Data API v3* → 创建 API 密钥。
- **Liked（`LL`）和 Watch Later（`WL`）是账号私有的**，API key 读不了，
  必须用 OAuth access token（scope `youtube.readonly`）。
  用 API key 请求它们会返回 403 或空列表。

用到的接口：

| 用途 | 接口 | 配额 |
| --- | --- | --- |
| 播放列表内容 | `playlistItems.list?part=snippet,contentDetails` | 1 / 页（50 条） |
| 视频详情 | `videos.list?part=snippet,contentDetails,statistics` | 1 / 50 个 id |
| 评论 | `commentThreads.list?videoId=&order=relevance` | 1 / 视频 |

默认配额是每天 10000 单位，对个人收藏夹绰绰有余。
`videos.list` 一次最多 50 个 id，所以代码里是批量拿的——
一条一条请求会把配额烧掉 50 倍。

`WL` 在很多账号上即使带 OAuth 也读不到（Google 在逐步收紧）。
所以单个播放列表读失败只会 warning 跳过，不会中断整次同步。

### 字幕：不走 API

`captions.list` 需要 OAuth **并且**要求你是频道所有者，对别人的视频没用。
所以字幕走播放器那条路：

1. 请求 `https://www.youtube.com/watch?v=<id>`
2. 从 HTML 里取出 `ytInitialPlayerResponse` 这个 JSON
3. 读 `captions.playerCaptionsTracklistRenderer.captionTracks[]`
4. 取 `baseUrl`，加上 `&fmt=json3` 请求，得到：

```json
{ "events": [ { "tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "…"}] } ] }
```

选轨规则：优先配置里的语言顺序（默认 `zh-Hans, zh-CN, zh, en`），
同语言下人工字幕优于自动生成（`kind == "asr"`）。

这条路依赖页面结构，YouTube 改版就会失效。所以如果装了
`youtube-transcript-api`（`pip install -e ".[youtube]"`）就优先用它——
那个库会跟进 YouTube 的变化。代码同时兼容它 0.x 和 1.x 的两套 API 形状。

解析 `ytInitialPlayerResponse` 用的是手写的括号配对扫描而不是正则：
JSON 里的字符串含有大括号，正则会截断。

## 会失败的情况

- 年龄限制 / 地区限制的视频：`watch` 页面里没有 player response，抛错跳过。
- 完全没有字幕轨：抛错跳过，条目仍会按标题和简介入库。
- 请求过快：给网页那条路设了 350ms 最小间隔。API 那条路不受影响。

## 评论

`commentThreads.list` 的 `order=relevance` 就是 YouTube 自己的"热门评论"排序，
一次一个配额单位，便宜到可以给每个收藏都跑一遍。关闭了评论的视频返回 403，
这是正常情况，跳过即可，不算失败。
