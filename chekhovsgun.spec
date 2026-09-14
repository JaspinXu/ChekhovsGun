# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for a single-file ChekhovsGun.

    pip install pyinstaller
    pyinstaller chekhovsgun.spec

Produces `dist/ChekhovsGun` (or .exe on Windows) that launches the tray runner:
double-click, the dashboard opens, nothing else to install. The browser
extension is still loaded separately — see the README.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden = [
    # uvicorn resolves these by string at runtime, so PyInstaller cannot see them.
    *collect_submodules("uvicorn"),
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["."],
    binaries=[],
    # The demo library and the dashboard are read from disk at runtime.
    datas=[
        ("chekhovsgun/data/demo.json", "chekhovsgun/data"),
        ("chekhovsgun/server/static", "chekhovsgun/server/static"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Optional heavyweights: whoever wants them installs the package properly.
    excludes=["faster_whisper", "sentence_transformers", "torch", "matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ChekhovsGun",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,  # tray app: no console window on Windows
    icon="packaging/icon.ico",
)
