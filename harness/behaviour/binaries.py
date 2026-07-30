#!/usr/bin/env python3
"""
Find the binaries used by the behaviour tests.

Every suite drives a patched Claude Code. The specific stock-comparison cases
also drive an unpatched control. Nothing here guesses: if a required binary
cannot be found it says which one and how to provide it, rather than running
half a comparison and reporting a number.
"""

import os
import shutil
import sys
from pathlib import Path

BACKUPS = Path.home() / ".claude-patch" / "backups"


class MissingBinary(SystemExit):
    pass


def patched(argv_value=None) -> str:
    """The build under test.

    Order: the path you passed, then $CLAUDE_QUEUE_BINARY, then whatever
    `claude` resolves to, which is your own install once this is applied.
    """
    for candidate in (argv_value, os.environ.get("CLAUDE_QUEUE_BINARY"),
                      shutil.which("claude")):
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve())
    raise MissingBinary(
        "no patched binary found. Pass one as the first argument, or set "
        "CLAUDE_QUEUE_BINARY, or install claude-queue so `claude` resolves to it."
    )


def control() -> str:
    """An UNPATCHED Claude Code, to compare against.

    Order: $CLAUDE_QUEUE_CONTROL, then the newest stock copy this patch saved
    before it first modified anything.
    """
    env = os.environ.get("CLAUDE_QUEUE_CONTROL")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    if BACKUPS.is_dir():
        saved = sorted(BACKUPS.glob("*"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        saved = [p for p in saved if p.is_file()]
        if saved:
            return str(saved[0].resolve())
    raise MissingBinary(
        f"no control binary found. Set CLAUDE_QUEUE_CONTROL to an unpatched "
        f"Claude Code, or install claude-queue once so a stock copy is saved "
        f"in {BACKUPS}."
    )


if __name__ == "__main__":
    try:
        print("patched:", patched(sys.argv[1] if len(sys.argv) > 1 else None))
    except MissingBinary as e:
        print("patched: ", e)
    try:
        print("control:", control())
    except MissingBinary as e:
        print("control: ", e)
