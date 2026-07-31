#!/usr/bin/env python3
"""Escape empties the queue into the editor. It must leave parked rows alone.

Reported from a real session: a parked message was sitting in the queue, the
person pressed Escape on the way to the rewind picker, and the parked text was
swept out of the queue and into the input box. Escape is how you reach rewind,
so a thought deliberately set aside vanished as a side effect of navigating.

Escape emptying the queue is stock behaviour and stays, because for waiting
messages it is the right answer: you stopped the turn, here is what was about
to run. A parked message was never about to run.

Reaching the state under test is the hard part, and two earlier versions of
this file did not:

  * Escape while a turn is RUNNING only stops the turn. The queue is untouched.
    A test that pressed Escape once, mid-turn, reported PASS against the build
    that still had the bug.
  * Adding a waiting message to the same queue does not help either. Stopping
    the turn starts the first waiting message, so the next Escape stops THAT
    turn rather than emptying the queue, and the pop path is never reached.

The path that empties the queue is an Escape with nothing running, so every
case here gets the session idle first and keeps waiting messages out of it.
The signal is the queue row itself: if a parked message were popped, its
[paused] row would be gone. That is unambiguous, unlike reading the input box,
which cannot be told apart from the transcript's own echo of earlier messages.
"""
import glob
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary  # noqa: E402
from lab import Lab, busy_for  # noqa: E402

WS = WORKSPACE
LIVE = patched_binary()
ESC = b"\x1b"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def qrows(lab):
    return [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]


def parked(lab, word):
    return any("[paused" in r and word in r for r in qrows(lab))


def idle(lab, limit=90):
    end = time.time() + limit
    while time.time() < end:
        lab._pump(2)
        if "esc to interrupt" not in lab.screen():
            return True
    return False


def clean():
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)


# ================================================================== A
clean()
print("\n=== A: escape on an idle session, parked messages only ===")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send("p FIRSTPARK keep me", label="park 1")
    lab._pump(5)
    lab.send("p SECONDPARK keep me too", label="park 2")
    lab._pump(5)
    check("A1. two parked messages are queued",
          parked(lab, "FIRSTPARK") and parked(lab, "SECONDPARK"),
          str(qrows(lab)))

    lab.write(ESC)
    lab._pump(3)
    check("A2. both survive one escape",
          parked(lab, "FIRSTPARK") and parked(lab, "SECONDPARK"),
          str(qrows(lab)))

    lab.write(ESC)
    lab._pump(3)
    check("A3. both survive a second escape",
          parked(lab, "FIRSTPARK") and parked(lab, "SECONDPARK"),
          str(qrows(lab)))

    lab._pump(10)
    check("A4. and neither has run", "esc to interrupt" not in lab.screen()
          and parked(lab, "FIRSTPARK") and parked(lab, "SECONDPARK"),
          str(qrows(lab)))
finally:
    lab.stop()
    clean()

# ================================================================== B
print("\n=== B: escape after interrupting a turn ===")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send(busy_for(30), label="busy")
    time.sleep(3)
    lab.send("p AFTERSTOP keep me", label="park")
    lab._pump(2)
    check("B1. parked while a turn is running", parked(lab, "AFTERSTOP"),
          str(qrows(lab)))

    lab.write(ESC)                       # stops the turn, queue untouched
    lab._pump(3)
    check("B2. it survives the escape that stopped the turn",
          parked(lab, "AFTERSTOP"), str(qrows(lab)))

    # now the session is idle, so THIS escape is the one that empties the queue
    if not idle(lab):
        print("   (never reached idle; B3 would not be testing the pop path)")
    lab.write(ESC)
    lab._pump(3)
    check("B3. it survives the escape that empties the queue",
          parked(lab, "AFTERSTOP"), str(qrows(lab)))
finally:
    lab.stop()
    clean()

print("\n" + ("FAILED: " + "; ".join(fails) if fails
              else "ESCAPE LEAVES PARKED MESSAGES ALONE"))
sys.exit(1 if fails else 0)
