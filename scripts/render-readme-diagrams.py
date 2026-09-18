"""Generate the editable, self-contained README figures. No third-party dependencies."""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
COPY = {
    "en": {
        "title": "From saved content to useful context",
        "sub": "A browser-native retrieval loop. An optional backend extends the collection.",
        "heads": ["Capture", "Index locally", "Retrieve", "Resurface"],
        "rows": [
            [
                ("Save on a supported site", "or use the extension toolbar"),
                ("Read visible page content", "Article text · video metadata"),
            ],
            [
                ("Split into passages", "Preserve source links"),
                ("IndexedDB", "Items · chunks · vectors"),
            ],
            [
                ("BM25 + vector retrieval", "Rank fusion (RRF)"),
                ("Select relevant passages", "Confidence · item state"),
            ],
            [
                ("A passage, with its source", "Article anchor · video timestamp"),
                ("Read → mark digested", "Exclude from future reminders"),
            ],
        ],
        "browser": "BROWSER / DEFAULT",
        "query": "Current page or explicit search",
        "model": "ENCODER",
        "model1": "Hash vectors by default",
        "model2": "Optional local multilingual-e5-small",
        "rules": "REMINDER POLICY",
        "rule1": "Library-size gate · cooldown · mute",
        "rule2": "Explicit search starts with the first save",
        "backend": "OPTIONAL PYTHON BACKEND",
        "back1": "Platform APIs · subtitles · comments · Whisper*",
        "back2": "Independent SQLite library + retrieval",
        "merge": "Result-level fusion",
        "merge2": "Deduplicate local + remote hits",
        "foot": "* Whisper requires optional dependencies. The two libraries do not share vector spaces or sync bidirectionally.",
        "legend": "Solid: default path     Dashed: optional path",
    },
    "zh": {
        "title": "让收藏，在相关的时刻重新出现",
        "sub": "浏览器内完成采集与检索；可选后端扩充内容来源。",
        "heads": ["顺手采集", "本地索引", "混合检索", "重新发现"],
        "rows": [
            [
                ("站点收藏 / 工具栏保存", "读取当前浏览器可见内容"),
                ("正文与视频元信息", "保留来源，形成收藏条目"),
            ],
            [("内容分块", "段落与原文链接"), ("IndexedDB", "条目 · 分块 · 向量")],
            [("BM25 + 向量召回", "RRF 排名融合"), ("选出相关段落", "置信度 · 条目状态")],
            [
                ("相关段落 + 原文入口", "文章定位 · 视频时间点"),
                ("阅读 → 标记「学完了」", "不再进入自动提醒"),
            ],
        ],
        "browser": "浏览器 / 默认路径",
        "query": "当前页面上下文 / 主动搜索",
        "model": "编码器",
        "model1": "默认使用哈希向量",
        "model2": "可选本地 multilingual-e5-small",
        "rules": "自动提醒策略",
        "rule1": "收藏库门槛 · 冷却 · 静音",
        "rule2": "主动搜索从第一条收藏起可用",
        "backend": "可选 PYTHON 后端",
        "back1": "平台 API · 字幕 · 评论 · Whisper*",
        "back2": "独立 SQLite 收藏库与检索",
        "merge": "结果层融合",
        "merge2": "本地与后端命中去重",
        "foot": "* Whisper 需要可选依赖。两端使用独立收藏库，不共享向量空间，也不进行双向同步。",
        "legend": "实线：默认路径     虚线：可选路径",
    },
}


def render(lang):
    c = COPY[lang]
    parts = []

    def add(s):
        parts.append(s)

    def box(x, y, w, h, fill="#FFFFFF", stroke="#D9E1DF", dash=False):
        add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}"'
            + (' stroke-dasharray="7 5"' if dash else "")
            + "/>"
        )

    def text(x, y, s, size=16, fill="#163244", weight=400):
        add(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}">{escape(s)}</text>'
        )

    def line(path, dash=False, color="#497E79"):
        add(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" marker-end="url(#arrow)"'
            + (' stroke-dasharray="6 5"' if dash else "")
            + "/>"
        )

    add(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="790" viewBox="0 0 1200 790" role="img" aria-labelledby="title desc">'
    )
    add(f'<title id="title">{escape(c["title"])}</title><desc id="desc">{escape(c["sub"])}</desc>')
    add(
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#497E79"/></marker></defs>'
    )
    add('<rect width="1200" height="790" rx="22" fill="#FAF8F2"/>')
    add('<g font-family="Inter, Segoe UI, Microsoft YaHei, Arial, sans-serif">')
    text(36, 46, "CHEKHOVSGUN  /  SYSTEM OVERVIEW", 13, "#497E79", 700)
    text(36, 91, c["title"], 32, weight=700)
    text(36, 122, c["sub"], 17, "#637481")
    box(24, 149, 1152, 394, "#F0F5F1", "#CBDAD2")
    text(44, 180, c["browser"], 13, "#497E79", 700)
    for i, x in enumerate([44, 330, 616, 902]):
        text(x, 220, f"0{i + 1}", 16, "#A77732", 700)
        text(x + 34, 220, c["heads"][i], 22, weight=600)
        for j, (title, sub) in enumerate(c["rows"][i]):
            y = 244 + j * 100
            box(x, y, 254, 82)
            text(x + 16, y + 31, title, 17, weight=600)
            text(x + 16, y + 57, sub, 14, "#637481")
        line(f"M{x + 127} 326V344")
        if i < 3:
            line(f"M{x + 254} 385H{x + 268}V284H{x + 286}")
    # Query entry is independent from saved-content ingestion.
    box(616, 451, 254, 62, "#E1ECE7", "#C4D6CE")
    text(632, 488, c["query"], 16, weight=600)
    line("M630 451H608V284H616")
    box(44, 451, 540, 62, "#F9F7F0", "#DDD9CB")
    text(60, 476, c["model"], 12, "#A77732", 700)
    text(60, 499, c["model1"], 15)
    text(274, 499, c["model2"], 14, "#637481")
    box(902, 451, 254, 62, "#FAECD0", "#E6D4AC")
    text(918, 477, c["rules"], 12, "#966727", 700)
    text(918, 499, c["rule1"], 13, "#6E624B")
    text(620, 570, c["rule2"], 15, "#637481")
    box(24, 604, 846, 112, "#FFFFFF", "#98ABA8", True)
    text(44, 632, c["backend"], 13, "#497E79", 700)
    text(44, 665, c["back1"], 17, weight=600)
    text(44, 693, c["back2"], 16, "#637481")
    box(902, 604, 254, 112, "#E1ECE7", "#98ABA8", True)
    text(918, 646, c["merge"], 20, weight=600)
    text(918, 677, c["merge2"], 14, "#637481")
    line("M870 660H902", True)
    line("M870 405H888V588H1029V604", True)
    # Default local hits go directly to the UI. Optional federation feeds that UI separately.
    line("M1156 660H1170V284H1156", True)
    text(36, 748, c["foot"], 13, "#637481")
    text(36, 772, c["legend"], 12, "#637481")
    add("</g></svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in COPY:
        (OUT / f"architecture-{lang}.svg").write_text(render(lang), encoding="utf-8")
