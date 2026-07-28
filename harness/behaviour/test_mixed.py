#!/usr/bin/env python3
"""
Two waiting messages and one interrupting one. Which runs first?

This is the case that had a bug once: the end-of-turn sweep matched on kind
only, so an interrupting message could drag a waiting one into its turn and
silently cancel its wait. It is worth a test of its own rather than an
assumption.

Each message asks for a differently named file, so the order they ran in is a
fact on disk rather than a reading of the transcript.

Expected, from the design:

    STEER.txt   first, mid-turn, at the next tool boundary
    ONE.txt     then, its own turn, after the current job finishes
    TWO.txt     then, its own turn

    ./test_mixed.py
"""

import re
import shutil
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab  # noqa: E402

# Long enough to interrupt, short enough that the turn actually ENDS inside the
# window. The first version asked for a full API with tests, which is right for
# a demo and wrong for a test: the turn was still running when the window
# closed, so the waiting messages had not had their turn to drain yet and the
# test called that a failure.
TASK = ("write four small python files in this folder, one at a time: "
        "shapes.py with a Circle and a Square class, area.py with a function "
        "for each shape's area, convert.py with cm and inch helpers, and "
        "report.py that prints a summary using the others. keep every file "
        "under 30 lines, write no tests, and do not run anything.")

SENDS = [
    ("q ", "write a file called ONE.txt containing the word one"),
    ("q ", "write a file called TWO.txt containing the word two"),
    ("s ", "write a file called STEER.txt containing the word steer"),
]
WATCH = ["STEER.txt", "ONE.txt", "TWO.txt"]

# "Busy" has to match what this build actually prints. The first version of
# this test looked for "esc to interrupt" only, which never appears here, so
# nothing was ever sent and the test reported FAIL against a feature it had
# not exercised. The spinner's own elapsed counter is the reliable signal.
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def main():
    ws = LAB / "mixed-test"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    lab = Lab(binary=__import__("binaries").patched(), workspace=str(ws),
              cols=96, rows=44)
    lab.start()
    lab.send(TASK)
    print("  task sent")

    seen, sent, t0, quiet_since, screen = {}, 0, time.time(), None, ""
    while time.time() - t0 < 600:
        lab._pump(0.2)
        now = time.time() - t0
        screen = lab.screen()
        busy = bool(BUSY.search(screen))
        steps = screen.count("⎿")

        # Send all three while it is genuinely still working.
        if sent < len(SENDS) and busy and steps >= 2 + sent:
            prefix, body = SENDS[sent]
            lab.send(prefix + body)
            print(f"  [{now:5.1f}s] sent {prefix.strip()!r:5} -> "
                  f"{body.split('called ')[1].split(' ')[0]}")
            sent += 1

        for name in WATCH:
            if name not in seen and (ws / name).exists():
                seen[name] = now
                print(f"  [{now:5.1f}s] APPEARED  {name}")

        if len(seen) == len(WATCH):
            break

        # Stop only on SUSTAINED silence. The spinner blinks off between tool
        # calls, and treating one of those gaps as "finished" ended an earlier
        # run after a minute, with half the job still unwritten, and reported
        # a failure against work that had never been given a chance to run.
        if busy or sent < len(SENDS):
            quiet_since = None
        else:
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since > 25:
                break
    lab.stop()

    for name in WATCH:                      # last look after the pty is closed
        if name not in seen and (ws / name).exists():
            seen[name] = time.time() - t0
    (LAB / "mixed-test-final-screen.txt").write_text(screen)

    order = sorted(seen, key=seen.get)
    print(f"\n  order they were written: {' -> '.join(order) or 'nothing'}")
    missing = [n for n in WATCH if n not in seen]
    if missing:
        print(f"  never written: {', '.join(missing)}")

    ok = order[:1] == ["STEER.txt"] and order[1:] == ["ONE.txt", "TWO.txt"]
    print(f"  steer first, then the queue in order: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
