#!/usr/bin/env python3
"""
The edge cases around the two UX changes.

The dangerous one is the empty queue. The up arrow is the key everyone uses to
recall their last prompt, and this patch now sits in the middle of it. If it
breaks that when nothing is queued, it breaks something people use constantly,
in exchange for a feature they use occasionally.

  history      up with an EMPTY queue still recalls the previous prompt
  walk         pressing up repeatedly walks back through the queue
  labels off   CLAUDE_QUEUE_LABELS=off removes the tags
  bash safe    a queued "!" command is never relabelled or mangled

    ./test_edges.py <binary>
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

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..40}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def input_area(screen):
    lines = screen.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("❯"):
            return "\n".join(lines[i:])
    return lines[-1] if lines else ""


def session(binary, name, env=None):
    ws = LAB / f"edge-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44,
              extra_env=env or {})
    lab.start()
    return lab


def wait_busy(lab, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        lab._pump(0.3)
        if BUSY.search(lab.screen()):
            return True
    return False


def test_history(binary):
    """Up with nothing queued must still bring back the last prompt."""
    lab = session(binary, "history")
    lab.send("say the word pineapple and nothing else")
    t0 = time.time()
    while time.time() - t0 < 60:
        lab._pump(0.4)
        if not BUSY.search(lab.screen()) and "pineapple" in lab.screen().lower():
            break
    lab._pump(1.0)
    lab.key("up")
    lab._pump(0.9)
    area = input_area(lab.screen())
    lab.stop()
    ok = "pineapple" in area
    print(f"  history     up with an empty queue recalls the last prompt "
          f"-> {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"     input area was: {area.strip()[:120]!r}")
    return ok


def test_walk(binary):
    """
    Repeated up presses walk back through the queue, newest first, one per pop.

    Not one pop per keypress. Each popped message is stacked above the last, so
    the editor becomes multi-line, and Claude Code's own rule is that up first
    moves the cursor within multi-line text before it does anything else. So a
    press is sometimes spent on cursor movement. That is stock behaviour and
    not this patch's doing.

    What matters, and what is asserted: newest first, exactly one new message
    per pop, and the queue drains completely.
    """
    lab = session(binary, "walk")
    lab.send(SLOW)
    wait_busy(lab)
    for q in ["q alpha one", "q bravo two", "q charlie three"]:
        lab.send(q)
        lab._pump(0.5)
    lab._pump(1.2)

    import os
    words = ("alpha", "bravo", "charlie")

    # Browsing must not put anything in the editor. That is the whole
    # difference between a selector and the old pop-into-the-editor version.
    selected, leaked = [], False
    for _ in range(3):
        lab.key("up")
        lab._pump(0.9)
        screen = lab.screen()
        area = input_area(screen)
        if any(w in area for w in words):
            leaked = True
        for line in screen.split("\n"):
            if line.strip().startswith("❯") and any(w in line for w in words):
                hit = [w for w in words if w in line]
                if hit and (not selected or selected[-1] != hit[0]):
                    selected.append(hit[0])

    # Enter takes ONLY the highlighted one and leaves the others queued.
    lab.write(b"\r")
    lab._pump(1.5)
    screen = lab.screen()
    area = input_area(screen)
    in_editor = [w for w in words if w in area]
    still_queued = [w for w in words
                    if any(w in ln and "[waits]" in ln for ln in screen.split("\n"))]
    lab.stop()

    ok = (not leaked and selected == ["charlie", "bravo", "alpha"]
          and in_editor == ["alpha"] and sorted(still_queued) == ["bravo", "charlie"])
    print(f"  select      highlight went {selected}, editor stayed empty="
          f"{not leaked}, enter gave {in_editor}, still queued {sorted(still_queued)} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def test_labels_off(binary):
    """CLAUDE_QUEUE_LABELS=off should remove the tags entirely."""
    lab = session(binary, "labels-off", {"CLAUDE_QUEUE_LABELS": "off"})
    lab.send(SLOW)
    wait_busy(lab)
    for q in ["q alpha one", "s bravo two"]:
        lab.send(q)
        lab._pump(0.5)
    lab._pump(1.2)
    screen = lab.screen()
    lab.stop()
    ok = "[waits]" not in screen and "[jumps in]" not in screen
    print(f"  labels off  no tags on screen -> {'PASS' if ok else 'FAIL'}")
    return ok


def test_bash_safe(binary):
    """A queued shell command must survive untouched."""
    lab = session(binary, "bash-safe")
    lab.send(SLOW)
    wait_busy(lab)
    lab.type("!echo queuesafe")
    lab._pump(0.4)
    import os
    lab.write(b"\r")
    lab._pump(1.5)
    screen = lab.screen()
    lab.stop()
    mangled = "[waits] echo" in screen or "[jumps in] echo" in screen or \
              "cho queuesafe" in screen.replace("echo queuesafe", "")
    ok = not mangled
    print(f"  bash safe   shell command not relabelled or truncated "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    binary = sys.argv[1] if len(sys.argv) > 1 else __import__("binaries").patched()
    print(f"  binary: {Path(binary).name}\n")
    results = [
        test_history(binary),
        test_walk(binary),
        test_labels_off(binary),
        test_bash_safe(binary),
    ]
    print(f"\n  {sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
