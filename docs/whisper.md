# 本地语音转写

真实收藏夹里大约三分之一的视频既没有 CC 字幕也没有 AI 字幕。这些条目以前只能靠
标题和简介入库——检索质量差，而且没法做到「跳到讲这件事的那一秒」。
`chekhovsgun/transcribe.py` 用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
在本地补上这一块。

## 开启

```bash
pip install -e ".[whisper]"      # faster-whisper + yt-dlp
# 还需要系统里有 ffmpeg
```

装上之后默认就会用。只在 adapter 没拿到字幕时才触发，有字幕的视频完全不受影响。

```bash
chekhovsgun ingest --source bilibili        # 自动兜底
chekhovsgun ingest --no-whisper             # 这次不要转写
chekhovsgun ingest --whisper                # 强制开启（即使配置里关了）
```

## 为什么它不在 adapter 里

它只需要一个 URL 就能工作，所以放在 ingest 管线上而不是某个 adapter 里：
两个来源都自动拥有，以后加小红书或知乎时也是白送的。

## 两道闸

转写是分钟级而不是毫秒级的操作，所以它必须有上限，否则一次「同步全部」可能跑一整夜：

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `whisper.max_duration_seconds` | 2700（45 分钟） | 单个视频超过就跳过 |
| `whisper.run_budget_seconds` | 1800（30 分钟） | 每次同步花在转写上的总时长 |

预算用完之后，剩下的条目照常按标题和简介入库，下次同步再继续——
因为增量同步会跳过内容没变的条目，所以多跑几次就会慢慢补齐。

## 模型选择

| 模型 | 大小 | 中文效果 | 速度（CPU） |
| --- | --- | --- | --- |
| `tiny` | ~75 MB | 差 | 最快 |
| `base` | ~150 MB | 一般 | 快 |
| `small`（默认） | ~500 MB | 可用 | 中等 |
| `medium` | ~1.5 GB | 好 | 慢 |
| `large-v3` | ~3 GB | 最好 | 很慢，建议有 GPU |

```bash
export CHEKHOVSGUN_WHISPER_MODEL=medium
export CHEKHOVSGUN_WHISPER_DEVICE=cuda      # 有显卡的话
export CHEKHOVSGUN_WHISPER_COMPUTE=float16  # 配合 cuda
```

第一次运行会下载模型，之后缓存在本地。模型只加载一次并在整轮同步里复用——
加载本身要几秒和几百兆内存，四十个视频不应该付四十次。

## 实现上的两个细节

**开了 VAD。** `vad_filter=True` 会把长段静音切掉。不开的话 Whisper 在静音上
很容易产生幻觉输出（反复吐出片尾曲字幕之类）。

**关了 `condition_on_previous_text`。** 它会让模型把前一段的输出当上下文，
在讲座类长音频上容易陷入重复循环，而字幕并不需要这种跨段连贯性。

**贪心解码。** `beam_size=1` 比默认的束搜索快一倍左右，
对字幕这种用途质量差异很小——反正下游还要分块和检索。

## 隐私

音频下载到系统临时目录，转写完立刻删除；模型在本机跑，音频不出这台机器。
这条是刻意的：整个项目的承诺是索引和观看记录都不离开本机，
转写如果调云端 API 就会破坏这个承诺。
