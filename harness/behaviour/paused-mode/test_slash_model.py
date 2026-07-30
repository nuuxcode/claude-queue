#!/usr/bin/env python3
"""Does /model open straight away mid-turn, on stock and on the patch?

Claude Code's changelog says 2.1.30 changed /model to execute immediately
instead of being queued. Mounssif saw it queued as "[waits] /model" on the
patched build, so the question is whether the patch caused that or whether
stock does the same thing. Both binaries, same script, same timing.
"""
import glob
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.expanduser("~/Developer/_claude-lab"))
from lab import Lab, busy_for  # noqa: E402

PATCHED = "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
STOCK_SRC = os.path.expanduser(
    "~/.claude-patch/backups/claude-2.1.220-8addc857f3fe.orig")
STOCK = "/private/tmp/claude-501/-Users-hamzadebbarh/" \
        "01760ee6-421a-4114-a9ad-bc3289f8e897/scratchpad/stock-claude.exe"
WS = os.path.expanduser("~/Developer/_claude-lab/workspace")

if not os.path.exists(STOCK):
    shutil.copy2(STOCK_SRC, STOCK)
    os.chmod(STOCK, 0o755)


def clean():
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)


def run(binary, label):
    clean()
    lab = Lab(binary=binary, model="haiku", cols=100, rows=44)
    lab.start()
    out = {}
    try:
        lab.send(busy_for(40), label="busy")
        time.sleep(4)
        # confirm a turn really is running before we type
        out["was_running"] = "esc to interrupt" in lab.screen()
        lab.send("/model", label="slash model")
        lab._pump(4)
        s = lab.screen()
        out["queued_row"] = any(
            "/model" in ln and ("[waits" in ln or "[jumps in" in ln)
            for ln in s.splitlines())
        # the picker shows a list of models to choose from
        out["picker_open"] = any(
            k in s for k in ("Select model", "Switch model", "Choose a model",
                             "Sonnet", "Opus 4", "opusplan", "Default (recommended)"))
        out["tail"] = [ln.rstrip() for ln in s.splitlines() if ln.strip()][-9:]
    finally:
        lab.stop()
        clean()
    return out


for binary, label in ((STOCK, "STOCK"), (PATCHED, "PATCHED")):
    r = run(binary, label)
    print(f"\n===== {label} =====")
    print(f"  a turn was running when /model was typed : {r['was_running']}")
    print(f"  /model appeared as a queued row          : {r['queued_row']}")
    print(f"  the model picker opened                  : {r['picker_open']}")
    print("  screen tail:")
    for ln in r["tail"]:
        print("   |", ln)
