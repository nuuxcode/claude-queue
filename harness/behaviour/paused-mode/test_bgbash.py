#!/usr/bin/env python3
"""The OTHER background state: bash work sent to the background with ctrl+B.

T1 and T2 proved a background AGENT does not hold the queue. This is the
control for the state that looks similar on screen but is not the same thing:
a long bash command pushed to the background with ctrl+B while it runs.

If this one holds the queue and the agent one does not, then "q+" would only
ever be about this state, and the screen wording is what tells them apart.

STATUS: INCONCLUSIVE, and the reason is the harness, not the product. ctrl+B
never took inside the pty. Both a single press and the documented double press
were sent while the bash tool was visibly running, and both times the command
ran to completion in the FOREGROUND (70 of 70 lines, ~1m 20s), so the state
under test was never entered. The MANGO answer at ~83s is therefore the
ordinary post-turn drain and proves nothing about backgrounded bash.

Do not read a verdict out of this file. Either drive it by hand in a real
terminal or find how ctrl+B is read, before trusting any claim about the
backgrounded-bash state.
"""
import glob
import os
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
    # wait for the bash tool to actually be running, then push it to the back
    for _ in range(20):
        lab._pump(1)
        if "esc to interrupt" in lab.screen():
            break
    time.sleep(4)
    lab.write(CTRL_B)
    lab._pump(0.4)
    lab.write(CTRL_B)
    lab._pump(3)
    s = lab.screen()
    backgrounded = any("background" in ln.lower() and "do not run it" not in ln.lower() and "do not change it" not in ln.lower()
                       for ln in s.splitlines())
    say(f"t={round(time.time()-t0,1)}s  ctrl+B sent. screen mentions "
        f"background: {backgrounded}")

    lab.send("q say MANGO and nothing else", label="queued")
    lab._pump(2)
    rows = [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]
    say(f"t={round(time.time()-t0,1)}s  queue: {rows}")

    t_mango = None
    for _ in range(50):
        lab._pump(2)
        sc = lab.screen()
        if t_mango is None and any(
                "MANGO" in ln and "say MANGO" not in ln
                and not ln.strip().startswith("❯")
                and "[waits" not in ln for ln in sc.splitlines()):
            t_mango = round(time.time() - t0, 1)
            say(f"t={t_mango}s  MANGO ANSWERED")
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
