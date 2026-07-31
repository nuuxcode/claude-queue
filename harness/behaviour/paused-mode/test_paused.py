#!/usr/bin/env python3
"""Drive the real terminal and prove the paused mode does what it says.

Four claims, each checked on the rendered screen rather than on the stream:

  1. "p ..." is queued and drawn as [paused]
  2. a paused message does not run when the turn it was typed into ends,
     while a "q ..." typed at the same moment does
  3. left and right cycle the highlighted message through the three modes
  4. a message cycled off paused runs like any other queued message
"""
import glob
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary  # noqa: E402

WS = WORKSPACE
from lab import Lab, busy_for  # noqa: E402

LIVE = patched_binary()
LEFT, RIGHT = b"\x1b[D", b"\x1b[C"

fails = []


def clear_saved_queue_at_start():
    """A queue file left by an earlier run restores rows into this one and
    every count in here is then measuring the wrong session."""
    d = os.path.join(WORKSPACE, ".claude")
    for f in glob.glob(os.path.join(d, "queue-*.json")):
        os.remove(f)


clear_saved_queue_at_start()


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def rows(screen):
    return [ln.strip() for ln in screen.splitlines() if ln.strip()]


def queue_rows(screen):
    return [r for r in rows(screen) if "[paused" in r or "[waits" in r
            or "[jumps in" in r]


lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
print("session up\n")

try:
    # A turn long enough to type into.
    lab.send(busy_for(22), label="busy turn")
    time.sleep(2)

    lab.send("p say PINEAPPLE and nothing else", label="paused msg")
    lab.send("q say BANANA and nothing else", label="waiting msg")
    time.sleep(1)

    s = lab.screen()
    print("--- queue while busy ---")
    for r in queue_rows(s):
        print("   ", r)
    check("1. paused message is drawn as [paused]",
          any("[paused]" in r and "PINEAPPLE" in r for r in queue_rows(s)))
    check("1b. waiting message is drawn as [waits]",
          any("[waits]" in r and "BANANA" in r for r in queue_rows(s)))

    # Let the turn end and the queue drain.
    print("\nwaiting for the turn to end ...")
    deadline = time.time() + 150
    ran_banana = False
    while time.time() < deadline:
        lab._pump(3)
        s = lab.screen()
        if "BANANA" in s and not any("BANANA" in r for r in queue_rows(s)):
            ran_banana = True
            break
    lab._pump(8)

    s = lab.screen()
    still_queued = queue_rows(s)
    print("\n--- queue after the turn ended ---")
    for r in still_queued:
        print("   ", r)

    check("2. the waiting message ran", ran_banana)
    check("2b. the paused message is STILL queued",
          any("[paused]" in r and "PINEAPPLE" in r for r in still_queued))

    # 3. cycle the highlighted message with left / right.
    lab.key("up")
    lab._pump(0.6)
    before = queue_rows(lab.screen())
    print("\n--- highlighted ---")
    for r in before:
        print("   ", r)

    seen = []
    for i in range(3):
        lab.write(RIGHT)
        lab._pump(0.8)
        cur = queue_rows(lab.screen())
        tag = next((t for t in ("[paused]", "[waits]", "[jumps in]")
                    for r in cur if t in r and "PINEAPPLE" in r), None)
        seen.append(tag)
        print(f"   right #{i+1} -> {tag}")
    check("3. right cycles through the modes",
          len([t for t in seen if t]) == 3 and len(set(seen)) == 3,
          f"saw {seen}")

    back = []
    for i in range(2):
        lab.write(LEFT)
        lab._pump(0.8)
        cur = queue_rows(lab.screen())
        tag = next((t for t in ("[paused]", "[waits]", "[jumps in]")
                    for r in cur if t in r and "PINEAPPLE" in r), None)
        back.append(tag)
        print(f"   left  #{i+1} -> {tag}")
    check("3b. left cycles the other way", len(set(back)) == 2, f"saw {back}")

    # 4. land it on [waits] and make it run.
    for _ in range(4):
        cur = queue_rows(lab.screen())
        if any("[waits]" in r and "PINEAPPLE" in r for r in cur):
            break
        lab.write(RIGHT)
        lab._pump(0.8)
    landed = any("[waits]" in r and "PINEAPPLE" in r
                 for r in queue_rows(lab.screen()))
    check("4. can be set back to [waits]", landed)

    if landed:
        lab.send("say KIWI and nothing else", label="release")
        deadline = time.time() + 150
        ran = False
        while time.time() < deadline:
            lab._pump(3)
            s = lab.screen()
            if "PINEAPPLE" in s and not any(
                    "PINEAPPLE" in r for r in queue_rows(s)):
                ran = True
                break
        check("4b. the un-paused message then runs", ran)

finally:
    print("\n--- final screen ---")
    print(lab.screen())
    lab.stop()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED"))
sys.exit(1 if fails else 0)
