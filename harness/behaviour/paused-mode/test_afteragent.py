#!/usr/bin/env python3
"""The other background state: a background AGENT, not a shell.

test_afterbg.py proves the shell case. This is the one from the screenshot
that started the feature, where the footer reads "Waiting for 1 background
agent to finish" and the turn has visibly ended. A background agent is a
different task type from a backgrounded shell, so it reaches the label through
a different branch, and neither run proves the other.

Same shape as the shell run, so the two are comparable:

    q say PAPAYA      the control. It must run while the agent is alive.
    x say MANGO       the feature. It must NOT, until the agent is done.

The agent is asked for an explicit timing fixture, because a subagent given a
vague job finishes in whatever time it likes and the window under test
disappears.
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
LOG = scratch("afteragent-evidence.txt")
LOOP = "for i in {1..60}; do echo $i; sleep 1; done"
LAUNCH = (
    'Use the Agent tool exactly once, with subagent_type "general-purpose", '
    'run_in_background true, and this prompt: "Run this exact bash command in '
    "the foreground and wait for it to finish. Do not change it, do not "
    "background it, do not shorten it. It is a timing fixture and it is "
    "supposed to take 60 seconds: " + LOOP + ' . Then reply DONE." '
    "Do not call any other tool and do not wait for the agent. As soon as the "
    "Agent tool returns, reply LAUNCHED and stop."
)

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
    lab.send(LAUNCH, label="launch")
    launched = False
    for _ in range(60):
        lab._pump(1)
        if answered(lab.screen(), "LAUNCHED", "reply LAUNCHED"):
            launched = True
            break
    say(f"t={round(time.time()-t0,1)}s  the agent is running: {launched}")
    if not launched:
        raise SystemExit("the agent never launched")

    lab.send("q say PAPAYA and nothing else", label="control")
    lab._pump(1)
    lab.send("x say MANGO and nothing else", label="after")
    lab._pump(2)

    rows = [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]
    say(f"t={round(time.time()-t0,1)}s  queue: {rows}")
    say()
    check(any(re.search(r"\[waits for \d+ agent", r) and "MANGO" in r
              for r in rows),
          "the x row names the agent it is waiting for")

    t_papaya = t_mango = t_agent_done = None
    for _ in range(60):
        lab._pump(2)
        sc = lab.screen()
        if t_agent_done is None and re.search(
                r"(Agent .*(completed|finished)|Background agent .*completed"
                r"|task notification)", sc, re.I):
            t_agent_done = round(time.time() - t0, 1)
            say(f"t={t_agent_done}s  the agent reported back")
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
    check(t_mango is not None, "the x message ran at all")
    check(t_papaya is not None and t_mango is not None
          and t_mango - t_papaya > 10,
          "the x message waited well past the control")
    check(t_agent_done is not None and t_mango is not None
          and t_mango >= t_agent_done,
          "the x message ran only after the agent reported back")

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
