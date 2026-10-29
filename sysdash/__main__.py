"""Command line entry point.

``sysdash`` redraws in place on a TTY and keeps stdout clean one-shot output
when piped, so it also works as ``sysdash --once --no-color >> log.txt``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from typing import List, Optional

from . import __version__
from .collect import collect_snapshot
from .metrics import snapshot_to_dict
from .render import render

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[H\033[2J"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sysdash",
        description=(
            "Zero-dependency terminal dashboard: memory, CPU, load, thermal, "
            "disk, network and battery. Built for Android/Termux, works on Linux."
        ),
    )
    parser.add_argument("--once", action="store_true", help="print one frame and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="refresh interval in seconds (default: 1.0, minimum: 0.2)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON (one object per line when looping)"
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument(
        "--width", type=int, default=None, metavar="COLS", help="frame width in columns"
    )
    parser.add_argument(
        "--disk",
        action="append",
        metavar="PATH",
        help="filesystem to report (repeatable; default: / plus mounted /data, /sdcard)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _width(args: argparse.Namespace) -> int:
    if args.width:
        return args.width
    return shutil.get_terminal_size((64, 24)).columns


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    interval = max(0.2, args.interval)
    width = _width(args)
    color = not args.no_color and sys.stdout.isatty()
    disk_paths: Optional[List[str]] = args.disk or None
    prev = None
    tty = sys.stdout.isatty()

    try:
        if args.once:
            snap = collect_snapshot(disk_paths=disk_paths)
            if args.json:
                print(json.dumps(snapshot_to_dict(snap), ensure_ascii=False))
            else:
                print(render(snap, width=width, color=color))
            return 0

        if tty:
            sys.stdout.write(HIDE_CURSOR)
            sys.stdout.flush()

        while True:
            snap = collect_snapshot(disk_paths=disk_paths)
            if args.json:
                sys.stdout.write(json.dumps(snapshot_to_dict(snap), ensure_ascii=False) + "\n")
            elif tty:
                sys.stdout.write(CLEAR + render(snap, prev=prev, width=width, color=color) + "\n")
            else:
                sys.stdout.write(render(snap, prev=prev, width=width, color=color) + "\n")
            sys.stdout.flush()
            prev = snap
            time.sleep(interval)
    except KeyboardInterrupt:
        if tty:
            sys.stdout.write("\n")
        return 0
    finally:
        if tty:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
