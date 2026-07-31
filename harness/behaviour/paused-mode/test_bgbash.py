#!/usr/bin/env python3
"""The OTHER background state: bash work sent to the background with ctrl+B.

T1 and T2 proved a background AGENT does not hold the queue. This is the
control for the state that looks similar on screen but is not the same thing:
a long bash command pushed to the background with ctrl+B while it runs.

If this one holds the queue and the agent one does not, then "q+" would only
ever be about this state, and the screen wording is what tells them apart.

RESULT: it does NOT hold the queue either. Backgrounded at 13.8s, the queued
message drained at 39.6s with the shell still alive and about 45 seconds left
to run. So neither background state blocks the queue, and "q+" has nowhere
left to be useful.

Two earlier attempts at this file said the opposite, and both were wrong for
the same reason, recorded here because it is easy to repeat:

  1. ctrl+B was pressed as soon as "esc to interrupt" appeared. That is the
     start of the TURN, seconds before the Bash tool runs, and ctrl+b only
     fires inside the Task key context. The press was swallowed, the command
     ran to completion in the foreground, and the late answer looked like a
     held queue. Wait for the app to print "ctrl+b to run in background".
  2. The liveness check matched the exact string "1 shell". The footer grows
     to "1 shell, 1 monitor" once Claude starts watching the output, so a live
     shell read as finished and the script printed the wrong verdict under
     correct data. Match the count with a regex.

Neither mistake failed loudly. Both produced a readable, plausible, wrong
answer, which is the only kind of test failure worth writing down.
"""
import glob
import os
import re
import sys
import time

sys.path.insert(0, "/private/tmp/claude-501/-Users-hamzadebbarh/"
                   "01760ee6-421a-4114-a9ad-bc3289f8e897/scratchpad")
from freelab import FreeLab  # noqa: E402

PATCHED = "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
WS = os.path.expanduser("~/Developer/_claude-lab/workspace")
LOG = ("/private/tmp/claude-501/-Users-hamzadebbarh/"
       "01760ee6-421a-4114-a9ad-bc3289f8e897/scratchpad/bgbash-evidence.txt")
CTRL_B = b"\x02"
BUSY = ("run this exact bash command in the foreground and wait for it to "
        "finish. do not run it in the background, do not change it: "
        "for i in {1..70}; do echo $i; sleep 1; done")

lines = []


def say(s=""):
    print(s)
    lines.append(s)


for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
    os.remove(f)

lab = FreeLab(binary=PATCHED, model="haiku", cols=100, rows=44)
lab.start()
try:
    t0 = time.time()
    lab.send(BUSY, label="busy")
    # Wait for the app to OFFER the background gesture, not merely for the turn
    # to start. "esc to interrupt" appears the moment the turn begins, seconds
    # before the Bash tool is running, and ctrl+b only fires inside the Task
    # key context. Pressing it early is a no-op and the command then runs to
    # completion in the foreground, which is a passing-looking test of nothing.
    #
    # Pump, never time.sleep. Sleeping stops reading the pty, so the app cannot
    # progress and the state never arrives.
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
    s = lab.screen()
    backgrounded = "Running in the background" in s
    say(f"t={round(time.time()-t0,1)}s  backgrounded: {backgrounded}")
    if not backgrounded:
        raise SystemExit("ctrl+b did not take")

    lab.send("q say MANGO and nothing else", label="queued")
    lab._pump(2)
    rows = [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]
    say(f"t={round(time.time()-t0,1)}s  queue: {rows}")

    t_mango = None
    t_shell_gone = None
    for _ in range(60):
        lab._pump(2)
        sc = lab.screen()
        # The footer counts what is alive and the wording grows: "1 shell",
        # then "1 shell, 1 monitor". Match the count, not one exact phrase, or
        # a live shell reads as finished and the test prints the wrong verdict.
        shell_alive = re.search(r"\d+ shell", sc) is not None
        if t_shell_gone is None and not shell_alive:
            t_shell_gone = round(time.time() - t0, 1)
            say(f"t={t_shell_gone}s  the backgrounded shell ended")
        if t_mango is None and any(
                "MANGO" in ln and "say MANGO" not in ln
                and not ln.strip().startswith("❯")
                and "[waits" not in ln for ln in sc.splitlines()):
            t_mango = round(time.time() - t0, 1)
            say(f"t={t_mango}s  MANGO ANSWERED. shell still alive="
                f"{shell_alive}")
            break
    if t_mango is None:
        say("MANGO never ran inside the window")
    say("")
    for ln in lab.screen().splitlines():
        if ln.strip():
            say(" | " + ln.rstrip())
finally:
    lab.stop()
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)

with open(LOG, "w") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nevidence: {LOG}")
