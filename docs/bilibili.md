# Bilibili 接入笔记

B 站没有面向第三方的公开 API，所以这里走的是网站自己用的那套 web 接口。
本文记录实现时踩到的点，方便接口变更时快速定位。

## 认证

只需要 `SESSDATA` 这一个 cookie。写操作才需要 `bili_jct`（本项目只读，不需要）。
`DedeUserID` 就是 uid，不填会从 `nav` 接口探测。

```
Cookie: SESSDATA=xxx; DedeUserID=xxx; buvid3=xxx
Referer: https://www.bilibili.com/
```

`Referer` 不能省。缺了它部分接口会直接返回 -403。

有效期约 30 天。过期表现为接口返回 `code: -101`（账号未登录）。

## WBI 签名

2023 年起大部分接口要求 `w_rid` 签名参数。算法：

1. `GET https://api.bilibili.com/x/web-interface/nav` → `data.wbi_img.img_url` / `sub_url`
2. 取两个 URL 的文件名（去掉扩展名）得到 `img_key`、`sub_key`
3. `raw = img_key + sub_key`，按固定的 64 位置换表重排，取前 32 位 → `mixin_key`
4. 参数加上 `wts`（秒级时间戳），按 key 排序、urlencode，**并从值里剔除 `!'()*` 这几个字符**
5. `w_rid = md5(query_string + mixin_key)`

密钥每天轮换，所以客户端缓存一小时（`chekhovsgun/adapters/wbi.py`）。

第 4 步的字符剔除很容易漏掉：漏了在大多数参数上看不出问题，
一旦标题里出现这些字符就会签名失败，非常难查。

置换表和签名逻辑有单测覆盖（`tests/test_wbi.py`），包含官方文档里的参考向量。

## 用到的接口

| 用途 | 接口 | 签名 |
| --- | --- | --- |
| 取 uid / WBI 密钥 | `/x/web-interface/nav` | 否 |
| 自建收藏夹列表 | `/x/v3/fav/folder/created/list-all?up_mid=` | 否 |
| 收藏夹内容 | `/x/v3/fav/resource/list?media_id=&pn=&ps=20&platform=web` | 是 |
| 稍后再看 | `/x/v2/history/toview` | 否 |
| 视频详情（拿 cid） | `/x/web-interface/view?bvid=` | 否 |
| 字幕列表 | `/x/player/wbi/v2?aid=&cid=&bvid=` | 是 |

## 字幕

`/x/player/wbi/v2` 返回 `data.subtitle.subtitles[]`，每项有 `lan`、`ai_status`、
`subtitle_url`。URL 是协议相对的（`//aisubtitle.hdslb.com/...`），要补 `https:`。

内容格式：

```json
{ "body": [ { "from": 1.5, "to": 4.0, "content": "……" } ] }
```

**未登录时这个接口对所有视频都返回空字幕列表**，哪怕视频本身有 CC 字幕。
所以 B 站的字幕抓取强依赖 SESSDATA。

选轨策略（`_pick_track`）：人工中文 > 人工其他 > AI 中文 > AI 其他。
`ai_status != 0` 或 `lan` 以 `ai-` 开头即视为 AI 字幕。

## 收藏夹条目字段

`medias[]` 里比较有用的：

| 字段 | 说明 |
| --- | --- |
| `bvid` / `bv_id` | 视频 BV 号，作为 `source_id` |
| `id` | avid |
| `ugc.first_cid` | 第一个分 P 的 cid，省掉一次 `view` 请求 |
| `type` | 2=视频稿件，12=音频，21=视频合集 |
| `fav_time` | 收藏时间 |
| `pubtime` | 投稿时间 |
| `intro` | 简介（比 `view` 接口的 `desc` 短） |

## 限流

没有公开的配额说明，但请求过快会开始返回 -412（请求被拦截）。
本项目把 Bilibili 客户端的最小请求间隔设为 400ms（约 2.5 req/s），
并对 429/5xx 做指数退避。全量同步一个几百条的收藏夹大约需要几分钟，
主要时间花在逐条取字幕上。
