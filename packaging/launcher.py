"""Entry point for the packaged build.

A double-clicked binary has no arguments and no terminal, so it goes straight
to the tray runner and opens the dashboard. Passing arguments still reaches the
normal CLI, which keeps the one binary useful for scripting too:

    ChekhovsGun.exe ingest --source bilibili
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # Required before anything else on Windows, or a frozen build re-launches
    # itself for every worker process.
    multiprocessing.freeze_support()

    if len(sys.argv) > 1:
        from chekhovsgun.cli import main as cli_main

        return cli_main(sys.argv[1:])

    from chekhovsgun.config import load_config
    from chekhovsgun.tray import TrayUnavailable, run_tray

    config = load_config()
    try:
        run_tray(config, open_browser=True)
    except TrayUnavailable:
        # No tray on this system — fall back to the plain server so the binary
        # is never simply dead.
        from chekhovsgun.server.app import run

        run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
