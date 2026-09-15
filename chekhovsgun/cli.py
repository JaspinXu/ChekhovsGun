"""Command line interface.

    chekhovsgun demo            # seed a sample library and try it immediately
    chekhovsgun ingest          # sync every configured source
    chekhovsgun serve           # start the local API + dashboard
    chekhovsgun relate <url>    # what would fire on this video?
    chekhovsgun capture <url>   # take in a page by hand (what the extension does)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
import time
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import REGISTRY, AdapterError, LocalFileAdapter
from .config import load_config
from .engine import Engine
from .models import Context

DEMO_DATA = Path(__file__).parent / "data" / "demo.json"


# ------------------------------------------------------------------- printing
def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)


style = Style(_supports_color())


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _print_hits(hits: list[Any], *, width: int = 96) -> None:
    if not hits:
        print(style.dim("  (nothing matched)"))
        return
    for index, hit in enumerate(hits, start=1):
        item = hit.item
        head = f"{index}. {style.bold(item.title)}"
        meta = " · ".join(
            part for part in (item.author, item.source, item.folder, f"score {hit.score:.2f}") if part
        )
        print(f"  {head}")
        print(style.dim(f"     {meta}"))
        print(style.cyan(f"     {hit.deep_link()}"))
        for chunk in hit.chunks[:2]:
            stamp = f"[{_fmt_time(chunk.start)}] " if chunk.start else ""
            body = textwrap.shorten(chunk.text, width=width, placeholder="…")
            print(style.dim(f"     {stamp}{body}"))
        print()


# ------------------------------------------------------------------- commands
def cmd_status(engine: Engine, args: argparse.Namespace) -> int:
    status = engine.status()
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    stats = status["stats"]
    print(style.bold(f"ChekhovsGun {status['version']}"))
    print(f"  home            {status['home']}")
    print(f"  index           {stats['db_path']}")
    print(f"  saved items     {stats['items']}  ({stats['items_with_transcript']} with transcript)")
    print(f"  chunks          {stats['chunks']}")
    by_source = ", ".join(f"{k}={v}" for k, v in sorted(stats["by_source"].items())) or "—"
    print(f"  by source       {by_source}")
    by_media = stats.get("by_media") or {}
    print(f"  视频 / 帖子      {by_media.get('video', 0)} / {by_media.get('post', 0)}")
    if stats.get("pending_body"):
        print(style.yellow(f"  待取正文         {stats['pending_body']}  (run `chekhovsgun hydrate`)"))
    needed = engine.config.retrieval.min_library_items
    if stats["items"] < needed:
        print(style.yellow(
            f"  弹窗未启用       再收藏 {needed - stats['items']} 条就会开始提醒 "
            f"(库太小时 IDF 不可靠，会误弹；搜索不受影响)"
        ))
    print(f"  已开火 fired     {stats['items_fired']}  ({stats['fire_rate'] * 100:.1f}% of library)")
    print(f"  已学完 digested  {stats['items_digested']}  ({stats['coverage'] * 100:.1f}% — the number that matters)")
    if stats.get("comment_chunks"):
        print(f"  评论片段         {stats['comment_chunks']}")
    if stats.get("items_transcribed"):
        print(f"  whisper 转写     {stats['items_transcribed']}")
    print(f"  embedding       {status['embedding']}")
    llm = status["llm"]
    print(f"  llm             {llm['model'] or 'extractive fallback (no API key)'}")
    print()
    print(style.bold("  sources"))
    for adapter in status["adapters"]:
        mark = style.green("ready") if adapter["configured"] else style.yellow("not configured")
        print(f"    {adapter['label']:<16} {mark}")
        if adapter["hint"]:
            print(style.dim(f"      {adapter['hint']}"))
    return 0


def cmd_ingest(engine: Engine, args: argparse.Namespace) -> int:
    sources = [args.source] if args.source else None
    last_report = time.time()

    def progress(stage: str, payload: dict) -> None:
        nonlocal last_report
        title = textwrap.shorten(payload.get("title", ""), width=52, placeholder="…")
        if stage == "transcribing":
            # Whisper takes minutes; without this the CLI looks frozen.
            print(f"\r  {style.dim('转写中'):<8} {title:<62}", end="", flush=True)
            last_report = time.time()
        elif stage == "item" and time.time() - last_report > 0.4:
            last_report = time.time()
            print(f"\r  {payload.get('seen', 0):>5}    {title:<62}", end="", flush=True)

    total_failed = 0
    for adapter in engine.adapters(sources):
        if not adapter.configured:
            print(style.yellow(f"skip {adapter.label}: ") + adapter.setup_hint())
            adapter.close()
            continue
        print(style.bold(f"syncing {adapter.label}…"))
        report = engine.ingest(
            adapter,
            limit=args.limit,
            force=args.force,
            fetch_transcripts=not args.no_transcripts,
            fetch_comments=not args.no_comments,
            transcribe=args.whisper,
            progress=progress,
        )
        print("\r" + " " * 74, end="\r")
        print(
            f"  seen {report.seen} · new {style.green(str(report.added))} · updated {report.updated}"
            f" · unchanged {report.skipped} · failed {style.red(str(report.failed)) if report.failed else 0}"
        )
        extras = [f"{report.with_transcript} with transcript"]
        if report.transcribed:
            extras.append(f"{report.transcribed} via whisper")
        if report.with_comments:
            extras.append(f"{report.with_comments} with comments")
        print(style.dim(f"  {', '.join(extras)}, {report.chunks} chunks, {report.duration:.1f}s"))
        for error in report.errors[:5]:
            print(style.red(f"  ! {error}"))
        total_failed += report.failed
    return 1 if total_failed else 0


def cmd_import(engine: Engine, args: argparse.Namespace) -> int:
    adapter = LocalFileAdapter(engine.config, args.path, source=args.source)
    if not adapter.configured:
        print(style.red(f"no such file: {args.path}"))
        return 1
    print(style.bold(f"importing {args.path}…"))
    report = engine.ingest(adapter, limit=args.limit, force=args.force)
    print(f"  new {report.added} · updated {report.updated} · chunks {report.chunks}")
    for error in report.errors[:5]:
        print(style.red(f"  ! {error}"))
    return 0


def cmd_capture(engine: Engine, args: argparse.Namespace) -> int:
    """Take in a page by URL, the same path the browser extension uses.

    Useful without the extension installed, and the quickest way to check that a
    site extracts cleanly before trusting a whole folder to the scan.
    """
    urls: list[str] = list(args.urls)
    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            print(style.red(f"no such file: {path}"))
            return 1
        urls.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    if not urls:
        print(style.red("nothing to capture — pass one or more urls, or --file"))
        return 1

    print(style.bold(f"capturing {len(urls)} page(s)…"))
    summary = engine.capture_many(
        [{"url": url, "folder": args.folder} for url in urls], origin="cli"
    )
    print(f"  new {summary['added']} · updated {summary['updated']} · unchanged {summary['skipped']}"
          f" · failed {summary['failed']}")
    for error in summary["errors"][:5]:
        print(style.red(f"  ! {error}"))
    if summary["needs_body"]:
        print(style.dim(f"  {summary['needs_body']} page(s) still need their text fetched"))
        return cmd_hydrate(engine, args)
    return 0


def cmd_hydrate(engine: Engine, args: argparse.Namespace) -> int:
    """Fetch and index the bodies of saves that arrived as bare links."""
    pending = engine.pending_body_count()
    if not pending:
        print(style.dim("nothing waiting for its text"))
        return 0
    print(style.bold(f"fetching text for {pending} save(s)…"))
    done = engine.hydrate_pending(
        limit=getattr(args, "limit", None) or 500,
        progress=lambda _stage, payload: print(
            style.dim(f"  [{payload['seen']}/{payload['total']}] {payload['title'][:60]}")
        ),
    )
    print(f"  indexed {done['indexed']} · unreadable {done['failed']} · chunks {done['chunks']}")
    if done["failed"]:
        print(style.dim("  unreadable pages keep their title; they are not retried"))
    return 0


def cmd_demo(engine: Engine, args: argparse.Namespace) -> int:
    print(style.bold("seeding a sample library so you can try retrieval right now…"))
    adapter = LocalFileAdapter(engine.config, DEMO_DATA, source="local")
    report = engine.ingest(adapter, force=True)
    print(f"  indexed {report.added + report.updated} items, {report.chunks} chunks\n")

    probe = Context(
        source="youtube",
        source_id="demo-probe",
        title="Why is my retrieval so bad? Chunking and hybrid search explained",
        author="Some Channel",
        description="A walkthrough of chunk size, BM25, embeddings and reranking for RAG systems.",
    )
    print(style.bold("pretending you just scrolled onto:"))
    print(f"  {probe.title}\n")
    result = engine.relate(probe, use_cache=False)
    explanation = result.get("explanation") or {}
    if explanation.get("text"):
        print(style.bold("  ChekhovsGun says:"))
        for line in textwrap.wrap(explanation["text"], width=88):
            print(f"    {line}")
        print()
    hits = engine.search(probe.as_query(), limit=3)
    _print_hits(hits)
    print(style.dim("Next: `chekhovsgun serve`, then load extension/ in your browser."))
    return 0


def cmd_search(engine: Engine, args: argparse.Namespace) -> int:
    hits = engine.search(args.query, limit=args.limit, sources={args.source} if args.source else None)
    if args.json:
        print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2))
        return 0
    print(style.bold(f'"{args.query}" → {len(hits)} saved item(s)\n'))
    _print_hits(hits)
    return 0


def cmd_relate(engine: Engine, args: argparse.Namespace) -> int:
    if args.url.startswith("http"):
        result = engine.relate_url(
            args.url, limit=args.limit, use_cache=False, fetch_missing=not args.no_fetch
        )
    else:
        result = engine.relate(
            Context(title=args.url), limit=args.limit, use_cache=False
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if not result["fired"]:
        print(style.dim(f"no shot fired — {result['reason']}"))
        return 0
    explanation = result.get("explanation") or {}
    if explanation.get("text"):
        tag = "llm" if explanation.get("generated") else "extractive"
        print(style.bold(f"ChekhovsGun says ({tag}):"))
        for line in textwrap.wrap(explanation["text"], width=88):
            print(f"  {line}")
        print()
    print(style.bold(f"{len(result['hits'])} saved item(s) match:"))
    for index, hit in enumerate(result["hits"], start=1):
        item = hit["item"]
        print(f"  {index}. {style.bold(item['title'])} — {item['author']}  ({hit['score']:.2f})")
        print(style.cyan(f"     {hit['deep_link']}"))
    return 0


def cmd_items(engine: Engine, args: argparse.Namespace) -> int:
    items = engine.store.list_items(
        source=args.source, query=args.query, status=args.status, tag=args.tag, limit=args.limit
    )
    marks = {"digested": style.green("✓"), "muted": style.yellow("⊘"), "active": " "}
    for item in items:
        print(f"  {marks.get(item.status, ' ')} {style.bold(item.title)}")
        meta = " · ".join(
            part for part in (item.source, item.author, item.folder, *item.user_tags) if part
        )
        print(style.dim(f"    {meta}"))
        print(style.dim(f"    {item.id}"))
    print(style.dim(f"\n  {len(items)} item(s)"))
    return 0


def cmd_mark(engine: Engine, args: argparse.Namespace) -> int:
    """Mark a save as digested / muted, or tag it."""
    target = args.target
    if target.startswith("http"):
        from .adapters import detect_source

        source, source_id = detect_source(target)
        if not source:
            print(style.red(f"not a recognised url: {target}"), file=sys.stderr)
            return 2
        target = f"{source}:{source_id}"

    status = None
    for flag, value in (("digested", "digested"), ("muted", "muted"), ("active", "active")):
        if getattr(args, flag, False):
            status = value
    updated = engine.mark(
        target,
        status=status,
        add_tags=args.tag or [],
        remove_tags=args.untag or [],
        note=args.note,
    )
    if updated is None:
        print(style.red(f"no such item: {target}"), file=sys.stderr)
        return 1
    labels = {"digested": style.green("已学完"), "muted": style.yellow("已静音"),
              "active": "还欠着"}
    print(f"  {style.bold(updated['title'])}")
    print(style.dim(f"    {labels.get(updated['status'], updated['status'])}"
                    f"{' · ' + ', '.join(updated['user_tags']) if updated['user_tags'] else ''}"))
    if updated["note"]:
        print(style.dim(f"    {updated['note']}"))
    return 0


def cmd_reindex(engine: Engine, args: argparse.Namespace) -> int:
    print(style.bold("re-embedding every chunk with the current backend…"))
    count = engine.reindex(lambda stage, payload: None)
    print(f"  {count} chunks reindexed with {engine.embedder.signature}")
    return 0


def cmd_serve(engine: Engine, args: argparse.Namespace) -> int:
    import uvicorn

    from .server.app import create_app

    config = engine.config
    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.port = args.port
    url = f"http://{config.server.host}:{config.server.port}/"
    print(style.bold(f"ChekhovsGun {__version__}"))
    print(f"  dashboard  {style.cyan(url)}")
    print(f"  api docs   {style.cyan(url + 'docs')}")
    print(style.dim(f"  index      {config.db_path}"))
    print(style.dim("  load extension/ as an unpacked extension to arm YouTube and Bilibili\n"))
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(create_app(config, engine), host=config.server.host, port=config.server.port,
                log_level=args.log_level)
    return 0


def cmd_tray(engine: Engine, args: argparse.Namespace) -> int:
    """Run in the background with a tray icon — no terminal required."""
    from .tray import TrayUnavailable, run_tray

    config = engine.config
    if args.port:
        config.server.port = args.port
    print(style.bold("ChekhovsGun 正在后台运行"))
    print(f"  仪表盘  {style.cyan(f'http://{config.server.host}:{config.server.port}/')}")
    print(style.dim("  托盘图标右键可以同步收藏或退出"))
    try:
        run_tray(config, open_browser=not args.no_open)
    except TrayUnavailable as exc:
        print(style.red(f"error: {exc}"), file=sys.stderr)
        print(style.dim("  你也可以直接用 `chekhovsgun serve`，功能完全一样。"))
        return 2
    return 0


def cmd_config(engine: Engine, args: argparse.Namespace) -> int:
    print(json.dumps(engine.config.redacted(), ensure_ascii=False, indent=2, default=str))
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chekhovsgun",
        description="每一件收藏都必须开火 — learn from what you already saved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            quick start:
              chekhovsgun demo                     seed sample data and see it work
              chekhovsgun ingest --source bilibili  sync your 收藏夹 (needs SESSDATA)
              chekhovsgun tray                      run in the background, no terminal needed
              chekhovsgun serve --open              same thing, in the foreground
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"chekhovsgun {__version__}")
    parser.add_argument("--home", help="override the data directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show the library and which sources are configured")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ingest", help="sync saved items from a source")
    p.add_argument("--source", choices=sorted(REGISTRY), help="default: every configured source")
    p.add_argument("--limit", type=int, help="stop after N items (useful for a first test)")
    p.add_argument("--force", action="store_true", help="re-index even if unchanged")
    p.add_argument("--no-transcripts", action="store_true", help="metadata only, much faster")
    p.add_argument("--no-comments", action="store_true", help="skip comment threads")
    p.add_argument("--whisper", dest="whisper", action="store_true", default=None,
                   help="force local transcription for videos without subtitles")
    p.add_argument("--no-whisper", dest="whisper", action="store_false",
                   help="never run local transcription")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("import", help="import saves from a json/jsonl/csv/txt file")
    p.add_argument("path")
    p.add_argument("--source", default="local")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("capture", help="take in a page by url (what the extension does)")
    p.add_argument("urls", nargs="*", help="one or more page urls")
    p.add_argument("--file", help="a text file with one url per line")
    p.add_argument("--folder", default="", help="label these saves, e.g. '知乎收藏夹/检索'")
    p.add_argument("--limit", type=int, default=500, help="max pages to fetch text for")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("hydrate", help="fetch the text of saves stored as bare links")
    p.add_argument("--limit", type=int, default=500)
    p.set_defaults(func=cmd_hydrate)

    p = sub.add_parser("demo", help="seed a sample library and run one retrieval")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("search", help="search your saved library")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--source", choices=sorted(REGISTRY))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("relate", help="what would pop up if you opened this page?")
    p.add_argument("url", help="a YouTube/Bilibili url, or just some text")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-fetch", action="store_true",
                   help="don't read the page; match on what is already indexed")
    p.set_defaults(func=cmd_relate)

    p = sub.add_parser("items", help="list indexed items")
    p.add_argument("--source", choices=sorted(REGISTRY), default="")
    p.add_argument("--query", default="")
    p.add_argument("--status", choices=["active", "digested", "muted"], default="")
    p.add_argument("--tag", default="")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_items)

    p = sub.add_parser("mark", help="mark a save as digested/muted, or tag it")
    p.add_argument("target", help="an item id (source:id) or the video url")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--digested", action="store_true", help="你看完了，停止提醒（计入覆盖率）")
    group.add_argument("--muted", action="store_true", help="别再拿这个烦我（不计入覆盖率）")
    group.add_argument("--active", action="store_true", help="放回「还欠着」")
    p.add_argument("--tag", action="append", help="add a tag (repeatable)")
    p.add_argument("--untag", action="append", help="remove a tag (repeatable)")
    p.add_argument("--note", help="attach a note")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("reindex", help="re-embed everything (after changing backend)")
    p.set_defaults(func=cmd_reindex)

    p = sub.add_parser("serve", help="run the local API and dashboard")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("tray", help="run in the background with a tray icon")
    p.add_argument("--port", type=int)
    p.add_argument("--no-open", action="store_true", help="do not open the dashboard on start")
    p.set_defaults(func=cmd_tray)

    p = sub.add_parser("config", help="print the effective configuration")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    engine = Engine(load_config(args.home))
    try:
        return int(args.func(engine, args) or 0)
    except AdapterError as exc:
        print(style.red(f"error: {exc}"), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
