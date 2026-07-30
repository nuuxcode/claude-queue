#!/usr/bin/env python3
"""
Every marker form and every near-miss, in one session.

These are the cheap gaps from SCENARIOS.md group A. They all check the same
thing from different angles: did the marker get read the way a person would
expect, and did anything that merely LOOKS like a marker survive untouched.

The near-misses matter more than the hits. An earlier draft of the marker
pattern matched the letter "t", so "start the server" was sent as "art the
server". A queue tool that quietly eats the first two characters of your
message is worse than no queue tool.

    ./test_markers.py <binary>
"""

import re
import shutil
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab, busy_for  # noqa: E402

# what you type, what should end up queued, which label it should carry
CASES = [
    ("q qform alpha",       "qform alpha",        "[waits]"),
    ("q: colonq charlie",   "colonq charlie",     "[waits]"),
    ("s sform delta",       "sform delta",        "[jumps in]"),
    ("s: colons foxtrot",   "colons foxtrot",     "[jumps in]"),
    ("Q upperq golf",       "upperq golf",        "[waits]"),
    ("S upperS hotel",      "upperS hotel",       "[jumps in]"),
    # near misses: these are ordinary words and must survive whole
    ("start the india",     "start the india",    "[waits]"),
    ("stop the juliet",     "stop the juliet",    "[waits]"),
    ("queueing kilo",       "queueing kilo",      "[waits]"),
    ("same lima",           "same lima",          "[waits]"),
    ("Queue depth is high", "Queue depth is high", "[waits]"),
    ("Steer clear of this", "Steer clear of this", "[waits]"),
    (" q spaced mike",      "q spaced mike",      "[waits]"),
]


def labeled_line(screen, expected_text, expected_label):
    return next(
        (line for line in screen.splitlines()
         if expected_text in line and expected_label in line),
        None,
    )


def main():
    binary = sys.argv[1] if len(sys.argv) > 1 else __import__("binaries").patched()
    ws = LAB / "markers"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44)
    lab.start()
    lab.send(busy_for(90))
    if not lab.wait_for_tool(timeout=90):
        screen = lab.screen()
        lab.stop()
        print("  SETUP DID NOT HOLD: no tool call started, so no marker "
              "behavior was tested")
        print(screen)
        return 1

    snapshots = {}
    for typed, expected_text, expected_label in CASES:
        lab.send(typed)
        deadline = time.time() + 4
        screen = lab.screen()
        while time.time() < deadline and not labeled_line(
                screen, expected_text, expected_label):
            lab._pump(0.2)
            screen = lab.screen()
        # The final terminal viewport is not evidence for every prior message:
        # a long queue can scroll its early rows away. Capture each assertion
        # while the item is known to be in view and after its redraw settles.
        snapshots[typed] = screen
    lab._pump(2.0)

    lab.stop()
    evidence = "\n\n".join(
        f"=== {typed} ===\n{snapshots[typed]}" for typed, _, _ in CASES
    )
    (LAB / "markers-screen.txt").write_text(evidence)

    print(f"  binary: {Path(binary).name}\n")
    passed = 0
    for typed, expect_text, expect_label in CASES:
        line = labeled_line(snapshots[typed], expect_text, expect_label)
        ok = line is not None
        # the marker itself must never survive into the queued text
        if ok and typed.strip() != expect_text:
            head = typed.strip().split(" ")[0].lower()
            if head in ("q", "s", "q:", "s:") and \
                    re.search(rf"\b{re.escape(head)}\s+{re.escape(expect_text)}", line, re.I):
                ok = False
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  typed {typed!r:24} -> "
              f"{(line.strip() if line else 'NOT FOUND')!r}")

    print(f"\n  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
