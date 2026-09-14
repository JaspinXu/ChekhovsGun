"""System-tray runner: the server without a terminal.

The single biggest barrier to anyone else using this project was never a
feature — it was that the local API had to be started from a terminal and kept
there. A tray icon turns ChekhovsGun into something you install, start once,
and forget, which is the shape every comparable local-first tool ships in.

The tray is optional (``pip install -e ".[tray]"``); ``chekhovsgun serve``
still works exactly as before for anyone who prefers a terminal.
"""

from __future__ import annotations

import logging
import threading
import time
import webbrowser
from typing import Any

from .config import Config, load_config
from .engine import Engine

log = logging.getLogger(__name__)


class TrayUnavailable(RuntimeError):
    pass


def _import_pillow():
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise TrayUnavailable(
            'the tray icon needs Pillow — run: pip install -e ".[tray]"'
        ) from exc
    return Image, ImageDraw


def _import_pystray():
    """Import pystray, mapping every failure mode onto one clear error.

    pystray picks and initialises a platform backend at *import* time, so on a
    headless Linux box (SSH, a container, a server) the import itself raises an
    X display error rather than ImportError. Catching only ImportError left
    those users with a raw Xlib traceback instead of "use `serve` instead".
    """
    try:
        import pystray  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise TrayUnavailable(
            'tray support needs pystray — run: pip install -e ".[tray]"'
        ) from exc
    except Exception as exc:  # pragma: no cover - headless / no display
        raise TrayUnavailable(
            f"no system tray available on this machine ({exc}). "
            "Use `chekhovsgun serve` instead — it is the same server without the icon."
        ) from exc
    return pystray


def build_icon_image(size: int = 64):
    """The bookmark-with-a-spark mark, drawn at runtime.

    Drawn rather than loaded so a PyInstaller one-file build has no data
    dependency to resolve at startup.
    """
    Image, ImageDraw = _import_pillow()
    scale = 8
    s = size * scale
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accent = (224, 164, 88, 255)
    plate = (20, 23, 31, 255)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.23), fill=plate)
    left, right = int(s * 0.30), int(s * 0.70)
    top, bottom = int(s * 0.20), int(s * 0.80)
    notch = int(s * 0.14)
    draw.polygon(
        [(left, top), (right, top), (right, bottom), (s // 2, bottom - notch), (left, bottom)],
        fill=accent,
    )
    draw.ellipse(
        [int(s * 0.60), int(s * 0.12), int(s * 0.60) + int(s * 0.20), int(s * 0.12) + int(s * 0.20)],
        fill=plate,
    )
    draw.ellipse(
        [int(s * 0.635), int(s * 0.155), int(s * 0.635) + int(s * 0.13), int(s * 0.155) + int(s * 0.13)],
        fill=(255, 226, 176, 255),
    )
    return image.resize((size, size), Image.LANCZOS)


class TrayApp:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.engine = Engine(self.config)
        self._server: Any = None
        self._syncing = False
        self._last_sync = ""

    @property
    def url(self) -> str:
        return f"http://{self.config.server.host}:{self.config.server.port}/"

    # ---------------------------------------------------------------- server
    def _serve(self) -> None:
        import uvicorn

        from .server.app import create_app

        uvicorn_config = uvicorn.Config(
            create_app(self.config, self.engine),
            host=self.config.server.host,
            port=self.config.server.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(uvicorn_config)
        self._server.run()

    def start_server(self) -> threading.Thread:
        thread = threading.Thread(target=self._serve, name="chekhovsgun-server", daemon=True)
        thread.start()
        # Give uvicorn a moment to bind, so "open dashboard" right after launch
        # does not land on a connection error.
        time.sleep(1.0)
        return thread

    # ----------------------------------------------------------------- menu
    def open_dashboard(self, *_args: Any) -> None:
        webbrowser.open(self.url)

    def sync_now(self, *_args: Any) -> None:
        if self._syncing:
            return

        def worker() -> None:
            self._syncing = True
            try:
                reports = self.engine.ingest_all()
                added = sum(r.added for r in reports)
                updated = sum(r.updated for r in reports)
                self._last_sync = f"上次同步：新增 {added} · 更新 {updated}"
            except Exception as exc:  # pragma: no cover - surfaced in the menu
                log.exception("tray sync failed")
                self._last_sync = f"同步失败：{exc}"
            finally:
                self._syncing = False

        threading.Thread(target=worker, name="chekhovsgun-sync", daemon=True).start()

    def status_text(self, *_args: Any) -> str:
        try:
            stats = self.engine.store.stats()
        except Exception:  # pragma: no cover
            return "索引不可用"
        return f"{stats['items']} 个收藏 · 已消化 {stats.get('items_digested', 0)}"

    def quit(self, icon: Any, *_args: Any) -> None:
        if self._server is not None:
            self._server.should_exit = True
        icon.stop()

    # ------------------------------------------------------------------ run
    def run(self, *, open_browser: bool = False) -> None:
        pystray = _import_pystray()
        self.start_server()
        if open_browser:
            self.open_dashboard()

        menu = pystray.Menu(
            pystray.MenuItem(self.status_text, None, enabled=False),
            pystray.MenuItem(lambda _i: self._last_sync or "尚未同步", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开仪表盘", self.open_dashboard, default=True),
            pystray.MenuItem(
                lambda _i: "同步中…" if self._syncing else "立即同步收藏",
                self.sync_now,
                enabled=lambda _i: not self._syncing,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self.quit),
        )
        icon = pystray.Icon(
            "chekhovsgun",
            icon=build_icon_image(64),
            title=f"ChekhovsGun · {self.url}",
            menu=menu,
        )
        icon.run()


def run_tray(config: Config | None = None, *, open_browser: bool = False) -> None:
    TrayApp(config).run(open_browser=open_browser)
