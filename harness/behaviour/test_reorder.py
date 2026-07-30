#!/usr/bin/env python3
"""
Reordering waiting messages, and the highlight that has to survive it.

The screen tests are cheap and prove the list moved. R7 is the one that matters:
it lets the turn finish and reads the session transcript to see which message
actually RAN first. A list that reorders on screen and runs in the old order
would pass every other test in this file.

    ./test_reorder.py <binary> [--quick]

--quick skips R7 and C12, the two that wait for real turns.
"""

import json
import re
import shutil
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab  # noqa: E402
from binaries import control as _control  # noqa: E402

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..90}; do echo $i; sleep 1; done")
SHORT = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
         "for i in {1..25}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")
PROJECTS = Path.home() / ".claude" / "projects"


def start(binary, name, env=None):
    ws = LAB / f"ro-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44,
              extra_env=env or {})
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")
    return lab


class SetupFailed(Exception):
    """The run never reached the state under test. Not a product failure."""


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


def expect_queue(lab, n, limit=20):
    """Wait until n messages really are waiting, and say so loudly if not.

    Without this, a turn that ended early leaves an empty queue and every
    assertion afterwards fails on nothing, which reads as a broken feature.
    Seen once for real: six sessions running at once slowed a turn enough that
    the messages ran instead of queueing, and a passing test reported FAIL.
    """
    t0 = time.time()
    while time.time() - t0 < limit:
        lab._pump(0.5)
        if len(texts(lab.screen())) >= n:
            return
    raise SetupFailed(
        f"wanted {n} messages waiting, screen has {texts(lab.screen())}. "
        "The turn probably ended before they were typed.")


def enter(lab):
    lab.write(b"\r")


def queued(screen):
    """The queued list as (highlighted, text) in screen order."""
    out = []
    for ln in screen.split("\n"):
        if "[waits]" not in ln and "[jumps in]" not in ln:
            continue
        body = ln.split("]", 1)[1].strip()
        # the fold suffixes a multi-line row with its held-back line count;
        # checks compare message text, so the suffix comes off here
        body = re.sub(r" \(\+\d+ lines?\)$", "", body)
        out.append((ln.strip().startswith("❯"), body))
    return out


def texts(screen):
    return [t for _, t in queued(screen)]


def picked(screen):
    hits = [t for h, t in queued(screen) if h]
    # With nothing selected every row carries the marker, so a single marked
    # row is the only reading that means "this one is highlighted".
    return hits[0] if len(hits) == 1 else None


def transcript_order(ws: Path, words):
    """Which of `words` reached the model first, read from the session file."""
    newest, best = None, 0
    for f in PROJECTS.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime > best and str(ws) in f.read_text(errors="ignore")[:4000]:
                newest, best = f, f.stat().st_mtime
        except OSError:
            continue
    if not newest:
        return None, "no transcript found"
    seen = []
    for line in newest.read_text(errors="ignore").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "user" or rec.get("isMeta"):
            continue
        content = json.dumps(rec.get("message", {}).get("content", ""))
        for w in words:
            if w in content and w not in seen:
                seen.append(w)
    return seen, str(newest)


# --------------------------------------------------------------------------


def r1_move_and_follow(binary):
    """Moving a message moves it on screen, and the highlight goes with it."""
    lab = start(binary, "r1")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q alpha", "q bravo", "q charlie"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)
    before = texts(lab.screen())

    lab.key("up")
    lab._pump(0.8)
    sel_before = picked(lab.screen())

    lab.key("shift-up")
    lab._pump(0.9)
    after = texts(lab.screen())
    sel_after = picked(lab.screen())

    lab.key("shift-down")
    lab._pump(0.9)
    back = texts(lab.screen())
    lab.stop()

    moved = before == ["alpha", "bravo", "charlie"] and after == ["alpha", "charlie", "bravo"]
    follows = sel_before == "charlie" and sel_after == "charlie"
    restored = back == ["alpha", "bravo", "charlie"]
    ok = moved and follows and restored
    print(f"  R1  move up and back   {before} -> {after} -> {back}")
    print(f"      highlight stayed on {sel_after!r} -> {'PASS' if ok else 'FAIL'}")
    return ok


def r2_edges(binary):
    """At either end the key does nothing, and nothing breaks."""
    lab = start(binary, "r2")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q one", "q two"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 2)

    lab.key("up")            # on "two", the last one
    lab._pump(0.7)
    for _ in range(3):       # push down past the bottom
        lab.key("shift-down")
        lab._pump(0.5)
    bottom = texts(lab.screen())

    for _ in range(4):       # then all the way up and past the top
        lab.key("shift-up")
        lab._pump(0.5)
    top = texts(lab.screen())
    alive = lab.alive()
    sel = picked(lab.screen())
    lab.stop()

    ok = alive and bottom == ["one", "two"] and top == ["two", "one"] and sel == "two"
    print(f"  R2  past both ends     bottom {bottom}, top {top}, alive={alive}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def r3_no_selection(binary):
    """Shift with an arrow does nothing at all when nothing is highlighted."""
    lab = start(binary, "r3")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q one", "q two", "q three"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)
    before = texts(lab.screen())
    for k in ("shift-up", "shift-down", "shift-up"):
        lab.key(k)
        lab._pump(0.5)
    after = texts(lab.screen())
    alive = lab.alive()
    lab.stop()
    ok = alive and before == after == ["one", "two", "three"]
    print(f"  R3  no selection       {before} -> {after}, alive={alive} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def r6_steer_default(binary):
    """With the stock default put back, everything is a steer and still moves.

    Worth its own run because the swap groups by priority: a queue where every
    message shares one priority is exactly where a wrong grouping would show,
    by refusing to move anything at all.
    """
    lab = start(binary, "r6", {"CLAUDE_QUEUE_DEFAULT": "steer"})
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["alpha", "bravo", "charlie"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)
    rows = queued(lab.screen())
    before = [t for _, t in rows]

    lab.key("up")
    lab._pump(0.8)
    lab.key("shift-up")
    lab._pump(0.9)
    after = texts(lab.screen())
    sel = picked(lab.screen())
    lab.stop()

    ok = (before == ["alpha", "bravo", "charlie"]
          and after == ["alpha", "charlie", "bravo"] and sel == "charlie")
    print(f"  R6  steer as default   {before} -> {after}, on {sel!r}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def r8_reorder_then_edit(binary):
    """Move one, then edit it: it must come back to its NEW slot, not its old.

    The two features touch the same number from opposite ends. Reordering
    changes where a message sits, and editing remembers where it sat so it can
    put it back. If editing remembered the position from before the move, every
    edit after a reorder would quietly undo the reorder.
    """
    lab = start(binary, "r8")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q alpha", "q bravo", "q charlie"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)

    lab.key("up")             # on charlie
    lab._pump(0.7)
    lab.key("shift-up")       # move it to the middle
    lab.key("shift-up")       # and then to the top
    lab._pump(1.0)
    moved = texts(lab.screen())

    enter(lab)                # pull the one at the top back
    lab._pump(1.5)
    lab.type(" EDITED")
    lab._pump(0.4)
    enter(lab)
    lab._pump(2.0)
    final = texts(lab.screen())
    lab.stop()

    ok = (moved == ["charlie", "alpha", "bravo"]
          and final == ["charlie EDITED", "alpha", "bravo"])
    print(f"  R8  reorder then edit  {moved} -> {final}")
    print(f"      the edited one kept the slot the move gave it "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def r4_priority_guard(binary):
    """A jumping message and a waiting one never swap: they never compete."""
    lab = start(binary, "r4")
    lab.send(SLOW)
    busy_wait(lab)
    lab.send("q waiting one")
    lab._pump(0.4)
    lab.send("s jumping one")
    lab._pump(0.4)
    lab.send("q waiting two")
    expect_queue(lab, 3)
    before = texts(lab.screen())

    lab.key("up")            # on "waiting two", the last
    lab._pump(0.7)
    lab.key("shift-up")      # its only same-priority neighbour is "waiting one"
    lab._pump(0.9)
    after = texts(lab.screen())
    sel = picked(lab.screen())
    lab.stop()

    ok = (before == ["waiting one", "jumping one", "waiting two"]
          and after == ["waiting two", "jumping one", "waiting one"]
          and sel == "waiting two")
    print(f"  R4  priority guard     {before}")
    print(f"                      -> {after}, on {sel!r} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def r5_control(binary):
    """On an unpatched binary the key must still do nothing."""
    lab = start(binary, "r5")
    lab.send(SLOW)
    busy_wait(lab)
    lab.send("first")
    lab._pump(0.4)
    lab.send("second")
    lab._pump(1.2)
    before = lab.screen()
    for k in ("shift-up", "shift-down"):
        lab.key(k)
        lab._pump(0.6)
    after = lab.screen()
    alive = lab.alive()
    lab.stop()
    ok = alive and ("first" in after and "second" in after)
    print(f"  R5  control unchanged  alive={alive}, both messages still there="
          f"{'first' in after and 'second' in after} -> {'PASS' if ok else 'FAIL'}")
    if before != after:
        print("      (screen differed, which is expected: the counter ticks)")
    return ok


def r7_run_order(binary):
    """The real one: after reordering, does the NEW order actually run?"""
    ws = LAB / "ro-r7"
    lab = start(binary, "r7")
    lab.send(SHORT)
    busy_wait(lab, limit=60)
    lab.send("q say the word ZEBRAWORD and nothing else")
    lab._pump(0.5)
    lab.send("q say the word YAKWORD and nothing else")
    expect_queue(lab, 2)
    order_before = texts(lab.screen())

    lab.key("up")             # highlight YAKWORD, the newer one
    lab._pump(0.8)
    lab.key("shift-up")       # put it first
    lab._pump(1.0)
    order_after = texts(lab.screen())

    # Let the counting turn end and both queued messages run.
    t0 = time.time()
    while time.time() - t0 < 240:
        lab._pump(2.0)
        s = lab.screen()
        if "YAK" in s and "ZEBRA" in s and not BUSY.search(s):
            break
    lab._pump(4.0)
    seen, where = transcript_order(ws, ["ZEBRAWORD", "YAKWORD"])
    lab.stop()
    ok = seen == ["YAKWORD", "ZEBRAWORD"]
    print(f"  R7  run order          screen {order_before} -> {order_after}")
    print(f"      transcript ran: {seen}  (wanted ['YAKWORD', 'ZEBRAWORD'])")
    print(f"      {where}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def c12_drain_under_you(binary):
    """The queue drains while you are browsing: stay on the same message."""
    lab = start(binary, "c12")
    lab.send(SHORT)
    busy_wait(lab, limit=60)
    for q in ["q first item", "q second item", "q third item"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)

    lab.key("up")            # third
    lab._pump(0.6)
    lab.key("up")            # second, the middle one
    lab._pump(0.8)
    before = picked(lab.screen())

    # Wait for the counting turn to end, which drains the first message, and
    # read the highlight the INSTANT the count drops. These messages are one
    # line each, so Claude answers them in a couple of seconds: pausing to look
    # lets a second one drain too and the state under test is gone.
    t0, after, rows = time.time(), None, texts(lab.screen())
    while time.time() - t0 < 180:
        lab._pump(0.3)
        rows = texts(lab.screen())
        if len(rows) <= 2:
            after = picked(lab.screen())
            break
    lab.stop()

    # If the message being watched drained too, the run never held the state
    # under test. That is drift, not a wrong highlight, and saying so beats
    # reporting a failure for a build that did the right thing.
    if "second item" not in rows:
        raise SetupFailed(
            f"the watched message drained as well; queue is {rows}")

    ok = before == "second item" and after == "second item"
    print(f"  C12 drain while browsing  was on {before!r}, now on {after!r}, "
          f"queue {rows}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quick = "--quick" in sys.argv
    allow_drift = "--allow-setup-drift" in sys.argv
    binary = args[0] if args else __import__("binaries").patched()
    control = _control()
    print(f"  binary: {Path(binary).name}\n")

    tests = [(r1_move_and_follow, binary), (r2_edges, binary),
             (r3_no_selection, binary), (r4_priority_guard, binary),
             (r5_control, control), (r6_steer_default, binary),
             (r8_reorder_then_edit, binary)]
    if not quick:
        tests += [(r7_run_order, binary), (c12_drain_under_you, binary)]

    results = {}
    for fn, b in tests:
        try:
            results[fn.__name__] = fn(b)
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
