#!/usr/bin/env python3
"""x waits for the background work. q does not. Both in one run.

The bug this proves fixed: the turn ending is not the work ending. A shell
pushed to the background with ctrl+B keeps running after Claude hands the
prompt back, the footer says so, and a waiting message drained straight into
it anyway. test_bgbash.py measured exactly that on the unpatched behaviour:
backgrounded at 13.8s, the queued message ran at 39.6s with the shell alive
and 45 seconds still to go.

So this run queues two messages behind the same background shell:

    q say PAPAYA      the control. It must run while the shell is alive.
    x say MANGO       the feature. It must NOT, until the shell is gone.

Running both together is what makes the result mean something. If MANGO is
simply late, the two look identical; PAPAYA answering first, in the same
session, with the same shell alive, is what separates "waits for the
background" from "waited a while".

The two mistakes from test_bgbash.py apply here unchanged and are the reason
this file borrows its timing wholesale:

  1. ctrl+B only fires inside the Task key context. Wait for the app to print
     "ctrl+b to run in background", not for the turn to start.
  2. The footer grows from "1 shell" to "1 shell, 1 monitor". Match the count
     with a regex or a live shell reads as finished.

And a third, found here, which is the same mistake wearing a different hat.
The first version of this file asked whether "N shell" was anywhere on screen.
It is: every finished turn leaves its own status row in the transcript, and
"1 shell, 1 monitor still running" stays legible forever after the shell is
gone. So the liveness read said busy when nothing was, both timing checks
failed, and the underlying behaviour had been correct all along. A screen is
a log, not a gauge. This waits on the app's own one-off event line instead,
"Background command ... completed", which is printed once and means one thing.

Pump, never time.sleep. Sleeping stops reading the pty, so the app cannot
progress and the state under test never arrives.
"""
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelab import FreeLab  # noqa: E402
from paths import WORKSPACE, patched_binary, scratch  # noqa: E402

PATCHED = patched_binary()
WS = WORKSPACE
LOG = scratch("afterbg-evidence.txt")
CTRL_B = b"\x02"
BUSY = ("run this exact bash command in the foreground and wait for it to "
        "finish. do not run it in the background, do not change it: "
        "for i in {1..70}; do echo $i; sleep 1; done")

lines = []
failures = []


def say(s=""):
    print(s)
    lines.append(s)


def check(ok, what):
    say(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def answered(screen, word, asked):
    """The model said the word, rather than the row that asked for it."""
    return any(word in ln and asked not in ln
               and not ln.strip().startswith("❯")
               and "[waits" not in ln and "[paused" not in ln
               for ln in screen.splitlines())


for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
    os.remove(f)

lab = FreeLab(workspace=WS, binary=PATCHED, model="haiku", cols=100, rows=44)
lab.start()
try:
    t0 = time.time()
    lab.send(BUSY, label="busy")
    offered = False
    for _ in range(40):
        lab._pump(1)
        if "ctrl+b to run in background" in lab.screen():
            offered = True
            break
    say(f"t={round(time.time()-t0,1)}s  the app offered ctrl+b: {offered}")
    if not offered:
        raise SystemExit("never reached the state under test")

    lab.write(CTRL_B)
    lab._pump(4)
    if "Running in the background" not in lab.screen():
        raise SystemExit("ctrl+b did not take")
    say(f"t={round(time.time()-t0,1)}s  the shell is in the background")

    lab.send("q say PAPAYA and nothing else", label="control")
    lab._pump(1)
    lab.send("x say MANGO and nothing else", label="after")
    lab._pump(2)

    rows = [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]
    say(f"t={round(time.time()-t0,1)}s  queue: {rows}")
    say()
    # The control is allowed to have gone already. It is a plain waiting
    # message behind a turn that has ended, so draining before this snapshot
    # is the control doing exactly what it is here to do, and the timing
    # checks below prove it either way.
    control = [r for r in rows if "PAPAYA" in r]
    check(not control or "[waits]" in control[0],
          "the control row, if still queued, reads [waits]")
    check(any(re.search(r"\[waits for \d+ shell", r) and "MANGO" in r
              for r in rows),
          "the x row names the shell it is waiting for")

    t_papaya = t_mango = t_shell_gone = None
    for _ in range(60):
        lab._pump(2)
        sc = lab.screen()
        if t_shell_gone is None and re.search(
                r"Background command.*\n?.*completed", sc):
            t_shell_gone = round(time.time() - t0, 1)
            say(f"t={t_shell_gone}s  the backgrounded shell reported done")
        if t_papaya is None and answered(sc, "PAPAYA", "say PAPAYA"):
            t_papaya = round(time.time() - t0, 1)
            say(f"t={t_papaya}s  PAPAYA answered")
        if t_mango is None and answered(sc, "MANGO", "say MANGO"):
            t_mango = round(time.time() - t0, 1)
            say(f"t={t_mango}s  MANGO answered")
        if t_mango is not None and t_papaya is not None:
            break

    say()
    check(t_papaya is not None, "the control ran at all")
    check(t_shell_gone is not None, "the shell reported done inside the run")
    check(t_papaya is not None and t_shell_gone is not None
          and t_papaya < t_shell_gone,
          "the control ran while the shell was still going")
    check(t_mango is not None, "the x message ran at all")
    check(t_mango is not None and t_shell_gone is not None
          and t_mango > t_shell_gone,
          "the x message ran only after the shell was done")
    check(t_papaya is not None and t_mango is not None
          and t_mango - t_papaya > 10,
          "the x message did not simply follow the control out")

    say()
    for ln in lab.screen().splitlines():
        if ln.strip():
            say(" | " + ln.rstrip())
finally:
    lab.stop()
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)

say()
say(f"{len(failures)} failed" if failures else "all checks passed")
with open(LOG, "w") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nevidence: {LOG}")
sys.exit(1 if failures else 0)
