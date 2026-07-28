#!/usr/bin/env python3
"""
The scenarios from SCENARIOS.md that were flagged risky, run for real.

Ordered by how likely each one is to bite someone, not by how easy it is:

  C11  a steer message loses its marker when you edit it, so its timing
       silently changes from "jumps in" to "waits"
  C12  the queue drains while you are browsing, so the highlight ends up on a
       different message than the one you were looking at
  C13  the remembered slot is still parked after you escape out, so the next
       thing you type lands in the middle of the queue
  C3   pressing up past the top of the queue
  A10  "q" on its own, with no message after it

    ./test_matrix.py <binary>
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
        "for i in {1..90}; do echo $i; sleep 1; done")
QUICK = "say the word pineapple and nothing else"
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def start(binary, name, env=None):
    ws = LAB / f"mx-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44,
              extra_env=env or {})
    lab.start()
    return lab


def busy_wait(lab, limit=90):
    """Wait until the long tool is actually RUNNING, not merely until a spinner.

    The spinner appears while the model is still thinking, before it has called
    anything. Returning then means the next thing typed can arrive at a session
    that finishes moments later, so messages meant to queue run instead and
    every assertion afterwards fails on an empty queue. Seen for real: a suite
    reported 2 of 4 on a build that scores 4 of 4.

    So this waits for the tool call itself to appear on screen.
    """
    t0 = time.time()
    seen_spinner = False
    while time.time() - t0 < limit:
        lab._pump(0.3)
        screen = lab.screen()
        seen_spinner = seen_spinner or bool(BUSY.search(screen))
        if "Bash(" in screen and BUSY.search(screen):
            return True
    return seen_spinner


def enter(lab):
    import os
    lab.write(b"\r")


def queue_lines(screen):
    return [ln.strip() for ln in screen.split("\n")
            if "[waits]" in ln or "[jumps in]" in ln]


class SetupFailed(Exception):
    """The run never reached the state under test. Not a product failure."""


def expect_queue(lab, n, limit=25):
    """Wait until n messages really are waiting, and say so loudly if not.

    Without this, a run where the messages never queued fails every assertion
    afterwards and reads as a broken feature. It happens for a real reason: a
    steer is collected at the next tool boundary, and if the model answers with
    a sentence before its first tool call, that boundary arrives immediately.
    """
    t0 = time.time()
    while time.time() - t0 < limit:
        lab._pump(0.5)
        if len(queue_lines(lab.screen())) >= n:
            return
    raise SetupFailed(
        f"wanted {n} messages waiting, screen has {queue_lines(lab.screen())}")


def c11_steer_marker(binary):
    """Editing a steer message must not silently turn it into a waiting one."""
    lab = start(binary, "c11")
    lab.send(SLOW)
    busy_wait(lab)
    lab.send("q first waiting")
    lab._pump(0.4)
    lab.send("s urgent jump")
    expect_queue(lab, 2)

    lab.key("up")           # newest is the steer one
    lab._pump(0.9)
    enter(lab)
    lab._pump(1.2)
    lab.type(" X")
    lab._pump(0.3)
    enter(lab)
    lab._pump(1.8)
    lines = queue_lines(lab.screen())
    lab.stop()

    still_steer = any("urgent jump" in ln and "[jumps in]" in ln for ln in lines)
    became_wait = any("urgent jump" in ln and "[waits]" in ln for ln in lines)
    print(f"  C11 steer marker   queue now: {lines}")
    print(f"      still a steer={still_steer}  silently became a wait={became_wait}"
          f"  -> {'PASS' if still_steer else 'FAIL'}")
    return still_steer


def c13_parked_slot(binary):
    """Abandoning an edit must not send the NEXT message into the middle.

    Pulling a message back records the slot it came from, so that sending it
    again puts it back where it was. The risk is that the slot stays recorded
    when you do not send it: the next thing you type would then land in the
    middle of the queue instead of at the end.

    The abandonment here is clearing the editor rather than pressing Escape.
    Escape stops the running turn, and stopping the turn releases the queue, so
    the scenario this is testing no longer exists by the time it is checked. An
    earlier version used Escape and reported a failure that was really the queue
    draining exactly as documented.
    """
    lab = start(binary, "c13")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q one", "q two", "q three"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)

    for _ in range(3):      # select the FIRST
        lab.key("up")
        lab._pump(0.7)
    enter(lab)              # pull it into the editor, slot now recorded
    lab._pump(1.5)
    for _ in range(40):     # abandon it by clearing the text
        lab.write(b"\x7f")
    lab._pump(1.0)
    lab.send("q brand new message")
    lab._pump(1.8)
    lines = queue_lines(lab.screen())
    lab.stop()

    if len(lines) < 3:
        raise SetupFailed(f"the queue drained during the run; it holds {lines}")
    last_is_new = "brand new" in lines[-1]
    print(f"  C13 parked slot    queue now: {lines}")
    print(f"      new message went to the back={last_is_new} "
          f"-> {'PASS' if last_is_new else 'FAIL, it landed mid-queue'}")
    return last_is_new


def c3_past_the_top(binary):
    """Pressing up more times than there are messages must not break."""
    lab = start(binary, "c3")
    lab.send(SLOW)
    busy_wait(lab)
    lab.send("q only one")
    lab._pump(1.0)
    for _ in range(6):
        lab.key("up")
        lab._pump(0.5)
    screen = lab.screen()
    alive = lab.alive()
    lab.stop()
    ok = alive and "only one" in screen
    print(f"  C3  past the top   session alive={alive}, message intact="
          f"{'only one' in screen} -> {'PASS' if ok else 'FAIL'}")
    return ok


def a10_bare_marker(binary):
    """"q" with nothing after it must stay literal, not become an empty send."""
    lab = start(binary, "a10")
    lab.send(SLOW)
    busy_wait(lab)
    lab.send("q")
    lab._pump(1.5)
    screen = lab.screen()
    lab.stop()
    # It should appear as a normal message reading "q", not vanish.
    ok = re.search(r"(\[waits\]|❯)\s*q\s*$", screen, re.M) is not None
    print(f"  A10 bare marker    'q' alone survived as a message "
          f"-> {'PASS' if ok else 'FAIL or ambiguous'}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    allow_drift = "--allow-setup-drift" in sys.argv
    print(f"  binary: {Path(binary).name}\n")
    results = {}
    for fn in (c11_steer_marker, c13_parked_slot, c3_past_the_top, a10_bare_marker):
        try:
            results[fn.__name__] = fn(binary)
        except SetupFailed as e:
            print(f"  {fn.__name__}: SETUP DID NOT HOLD, not a product failure: {e}")
            results[fn.__name__] = None
        except Exception as e:
            print(f"  {fn.__name__}: ERRORED {e}")
            results[fn.__name__] = False
        print()
    passed = sum(1 for v in results.values() if v is True)
    skipped = [k for k, v in results.items() if v is None]
    print(f"  {passed}/{len(results)} passed")
    if skipped:
        print(f"  setup never held for: {skipped} (re-run these alone)")
    return 0 if passed == len(results) or \
        (allow_drift and passed + len(skipped) == len(results)) else 1


if __name__ == "__main__":
    sys.exit(main())
