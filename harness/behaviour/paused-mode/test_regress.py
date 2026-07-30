#!/usr/bin/env python3
"""Everything that already worked must still work.

The changes with the widest blast radius were the busy/idle branch (a paused
message now joins the queue path), the idle split (it picks the first runnable
line rather than the first line), the busy counter (paused rows stopped being
counted as work) and the browsing hold (nothing drains while you point at the
queue). Each of those sits underneath behaviour that shipped, so this drives
the shipped behaviour rather than the new feature.
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/Developer/_claude-lab"))
from lab import Lab, busy_for  # noqa: E402

LIVE = "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
fails = []


def clear_saved_queue_at_start():
    """A queue file left by an earlier run restores rows into this one and
    every count in here is then measuring the wrong session."""
    d = os.path.expanduser("~/Developer/_claude-lab/workspace/.claude")
    for f in glob.glob(os.path.join(d, "queue-*.json")):
        os.remove(f)


clear_saved_queue_at_start()


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def qrows(s):
    return [ln.strip() for ln in s.splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]


lab = Lab(binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    # --- 1. the default is still "waits", and s still jumps in -------------
    lab.send(busy_for(20), label="busy")
    time.sleep(2)
    lab.send("also say ALPHA", label="no marker")
    lab.send("s also say BETA", label="s marker")
    time.sleep(1)
    rows = qrows(lab.screen())
    print("--- queued ---")
    for r in rows:
        print("   ", r)
    check("1. no marker still waits",
          any("[waits]" in r and "ALPHA" in r for r in rows))
    check("2. s still jumps in",
          any("[jumps in]" in r and "BETA" in r for r in rows))

    # BETA should reach the model during the turn, ALPHA should not.
    got_beta_early = False
    deadline = time.time() + 60
    while time.time() < deadline:
        lab._pump(2)
        s = lab.screen()
        if "BETA" in s and not any("BETA" in r for r in qrows(s)):
            got_beta_early = any("ALPHA" in r for r in qrows(s))
            break
    check("3. the jumping message landed while the waiting one stayed queued",
          got_beta_early)

    # let everything finish
    for _ in range(40):
        lab._pump(3)
        if not qrows(lab.screen()):
            break
    check("4. the waiting message drained after the turn",
          not qrows(lab.screen()))

    # --- 2. queue editing keys still work ---------------------------------
    lab.send(busy_for(25), label="busy again")
    time.sleep(2)
    lab.send("q first message", label="q1")
    lab.send("q second message", label="q2")
    lab.send("q third message", label="q3")
    time.sleep(1)
    before = qrows(lab.screen())
    print("--- three queued ---")
    for r in before:
        print("   ", r)
    check("5. three messages queued in order",
          len(before) == 3 and "first" in before[0] and "third" in before[2])

    # highlight the last one and move it up
    lab.key("up")
    lab._pump(0.6)
    lab.key("shift-up")
    lab._pump(0.8)
    after = qrows(lab.screen())
    print("--- after shift+up ---")
    for r in after:
        print("   ", r)
    check("6. shift+up still reorders",
          len(after) == 3 and "third" in after[1] and "second" in after[2])

    # delete the highlighted one
    lab.write(b"\x7f")   # backspace, which the patch also binds
    lab._pump(0.8)
    gone = qrows(lab.screen())
    print("--- after delete ---")
    for r in gone:
        print("   ", r)
    check("7. delete still removes the highlighted message",
          len(gone) == 2 and not any("third" in r for r in gone))

    # step off the queue, then let it drain
    for _ in range(4):
        lab.key("down")
        lab._pump(0.4)
    print("\nwaiting for the queue to drain after stepping off ...")
    drained = False
    deadline = time.time() + 180
    while time.time() < deadline:
        lab._pump(3)
        if not qrows(lab.screen()):
            drained = True
            break
    check("8. the queue drains again once you stop browsing", drained)

finally:
    if fails:
        print("\n--- final screen ---")
        print(lab.screen())
    lab.stop()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "NO REGRESSIONS"))
sys.exit(1 if fails else 0)
