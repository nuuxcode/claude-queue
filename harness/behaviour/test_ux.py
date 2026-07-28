#!/usr/bin/env python3
"""
The two UX changes, checked against an unpatched control.

  labels     every queued message says what it will do, [waits] or [jumps in]
  edit one   up highlights, enter brings back ONE and leaves the rest queued

The "edit one" step used to be a single press of up, because an earlier patch
popped the newest message straight into the editor. The next release replaced
that with a highlight you move first, so a single press correctly does nothing
to the editor. The test kept asserting the old shape and reported a working
build as broken, which is the same failure mode as four of the harness bugs it was
written to catch. It now drives the current shape: up, then enter.

These are direct patched-build checks. Cross-build comparisons live in the
suites whose assertions depend on stock behavior.

    ./test_ux.py <binary>
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

TASK = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..40}; do echo $i; sleep 1; done")
QUEUED = ["q alpha one", "q bravo two", "s charlie three"]
WORDS = ["alpha", "bravo", "charlie"]
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def queue_block(screen):
    """The lines between the spinner and the input divider."""
    out, seen_spinner = [], False
    for line in screen.split("\n"):
        if BUSY.search(line):
            seen_spinner = True
            continue
        if seen_spinner:
            if set(line.strip()) <= {"─"} and line.strip():
                break
            if line.strip():
                out.append(line.strip())
    return out


def input_area(screen):
    lines = screen.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("❯"):
            return "\n".join(lines[i:])
    return lines[-1] if lines else ""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    allow_drift = "--allow-setup-drift" in sys.argv
    tag = Path(binary).name
    ws = LAB / f"ux-{tag}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44)
    lab.start()
    lab.send(TASK)
    print(f"  {tag}: task sent")

    t0 = time.time()
    while time.time() - t0 < 90:
        lab._pump(0.3)
        if BUSY.search(lab.screen()):
            break

    for q in QUEUED:
        lab.send(q)
        lab._pump(0.5)

    # Wait until all three are really waiting. The steer is collected at the
    # next tool boundary, so if the run looks a moment too late it has already
    # gone and the labels count comes back 2 and 0 on a build that is fine.
    t0 = time.time()
    while time.time() - t0 < 20:
        lab._pump(0.5)
        if len(queue_block(lab.screen())) >= len(QUEUED):
            break

    block = queue_block(lab.screen())
    if len(block) < len(QUEUED):
        print(f"  SETUP DID NOT HOLD, not a product failure: wanted "
              f"{len(QUEUED)} waiting, screen has {len(block)}")
        lab.stop()
        return 0 if allow_drift else 1
    print("  queued list on screen:")
    for line in block:
        print(f"     {line}")

    waits = sum(1 for line in block if "[waits]" in line)
    jumps = sum(1 for line in block if "[jumps in]" in line)

    lab.key("up")
    lab._pump(1.0)
    parked = input_area(lab.screen())
    early = [w for w in WORDS if w in parked]
    import os
    lab.write(b"\r")
    lab._pump(1.5)
    area = input_area(lab.screen())
    back = [w for w in WORDS if w in area]
    print(f"  after up alone, the input holds: {early or 'nothing'} (want nothing)")
    print(f"  after up then enter, the input holds: {back or 'nothing'}")
    lab.stop()

    print()
    ok_labels = waits == 2 and jumps == 1
    ok_one = len(back) == 1 and len(early) == 0
    print(f"  labels    [waits] x{waits}, [jumps in] x{jumps}  "
          f"-> {'PASS' if ok_labels else 'FAIL, expected 2 and 1'}")
    print(f"  edit one  {len(early)} back on up, {len(back)} after enter  "
          f"-> {'PASS' if ok_one else 'FAIL, expected 0 then exactly 1'}")
    return 0 if (ok_labels and ok_one) else 1


if __name__ == "__main__":
    sys.exit(main())
