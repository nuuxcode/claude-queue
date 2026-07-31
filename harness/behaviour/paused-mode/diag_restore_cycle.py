#!/usr/bin/env python3
"""Restore a paused message, then change its mode with the arrows.

The path in the screenshots: a paused message comes back after a restart, the
arrows move it to [waits], and then a working indicator runs while nothing
happens.
"""
import glob
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary  # noqa: E402
from lab import Lab  # noqa: E402

LIVE = patched_binary()
RIGHT = b"\x1b[C"
WS = WORKSPACE

for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
    os.remove(f)


def tail(lab, tag, n=9):
    print(f"\n== {tag} ==")
    for ln in [l.rstrip() for l in lab.screen().splitlines() if l.strip()][-n:]:
        print("  |", ln)


print("--- session 1: park a message ---")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
lab.send("p say ZEBRA and nothing else", label="park")
lab._pump(6)
tail(lab, "parked")
lab.stop()

time.sleep(2)
print("\n--- session 2: restore, then cycle it to waits ---")
lab2 = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab2.start()
lab2._pump(6)
tail(lab2, "after restart")

lab2.key("up")
lab2._pump(1.0)
lab2.write(RIGHT)
lab2._pump(1.5)
tail(lab2, "after one RIGHT (paused -> waits?)")

for secs in (10, 25, 45):
    lab2._pump(10 if secs == 10 else 15 if secs == 25 else 20)
    s = lab2.screen()
    running = "esc to interrupt" in s
    answered = "ZEBRA" in s and not any(
        "ZEBRA" in ln and ("[waits" in ln or "[paused" in ln)
        for ln in s.splitlines())
    print(f"  t~{secs}s  footer says running: {running}   model answered: {answered}")
tail(lab2, "after waiting")

print("\n--- now step off the list ---")
for _ in range(3):
    lab2.key("down")
    lab2._pump(0.5)
lab2._pump(12)
tail(lab2, "after stepping off")

print("\n--- now send something ---")
lab2.send("say OKAY and nothing else", label="release")
lab2._pump(20)
tail(lab2, "after sending")
lab2.stop()

for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
    os.remove(f)
