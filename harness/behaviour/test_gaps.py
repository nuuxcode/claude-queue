#!/usr/bin/env python3
"""
The scenarios from SCENARIOS.md that were still marked gap or risky.

Grouped so one session covers several related checks, because each session
costs a real turn. Ordered by how likely each is to bite someone.

    ./test_gaps.py [binary]
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
from binaries import control as _control  # noqa: E402
from test_reorder import transcript_order  # noqa: E402

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..90}; do echo $i; sleep 1; done")
SHORT = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
         "for i in {1..30}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def start(binary, name):
    ws = LAB / f"gap-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=44)
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")
    return lab, ws


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
    lab.write(b"\r")
    lab._pump(0.6)


def queued(screen):
    out = []
    for ln in screen.split("\n"):
        if "[waits]" not in ln and "[jumps in]" not in ln:
            continue
        text = ln.split("]", 1)[1].strip()
        # the fold suffixes a multi-line row with its held-back line count;
        # checks compare message text, so the suffix comes off here
        text = re.sub(r" \(\+\d+ lines?\)$", "", text)
        out.append((ln.strip().startswith("❯"), text))
    return out


def texts(screen):
    return [t for _, t in queued(screen)]


def picked(screen):
    hits = [t for h, t in queued(screen) if h]
    return hits[0] if len(hits) == 1 else None


def input_area(screen):
    """The editor box, which is the block between the last two rule lines.

    The obvious version, "the first line starting with the prompt arrow", finds
    the user's own message at the top of the transcript instead, and then
    reports an empty editor for every test that uses it. That cost a round of
    false failures.
    """
    lines = screen.split("\n")
    rules = [i for i, ln in enumerate(lines)
             if ln.count("─") >= 20 and len(ln.strip()) - ln.count("─") <= 2]
    if len(rules) < 2:
        return ""
    return "\n".join(lines[rules[-2] + 1:rules[-1]])


# --------------------------------------------------------------------------


class SetupFailed(Exception):
    """The run never reached the state under test. Not a product failure."""


def expect_three(lab, n=3, limit=25):
    """Wait until n messages really are waiting, and say so loudly if not."""
    t0 = time.time()
    while time.time() - t0 < limit:
        lab._pump(0.5)
        if len(texts(lab.screen())) >= n:
            return
    raise SetupFailed(
        f"wanted {n} messages waiting, screen has {texts(lab.screen())}")


def g1_idle_marker(binary):
    """A14 + B6: a marker typed with nothing running still gets stripped."""
    lab, ws = start(binary, "idle")
    lab.send("q say the word IDLEWORD and nothing else")
    t0 = time.time()
    while time.time() - t0 < 120:
        lab._pump(1.0)
        if "IDLEWORD" in lab.screen() and not BUSY.search(lab.screen()):
            break
    lab._pump(3.0)
    seen, where = transcript_order(ws, ["q say the word", "say the word IDLEWORD"])
    lab.stop()
    clean = seen == ["say the word IDLEWORD"]
    print(f"  G1  marker while idle    model received: {seen}")
    print(f"      marker stripped, ran straight away -> {'PASS' if clean else 'FAIL'}")
    return clean


def g2_slash_while_busy(binary, control):
    """A12: a slash command typed while busy behaves exactly as it does stock.

    It is not queued at all. A slash command that opens a panel opens it on the
    spot, while the turn keeps running, on both builds. The first version of
    this test assumed it would join the queue and waited for it to run later,
    which asserted a shape neither build has.
    """
    def run(b, name):
        lab, _ = start(b, name)
        lab.send(SHORT)
        busy_wait(lab, limit=60)
        lab.send("/status")
        lab._pump(2.5)
        s = lab.screen()
        out = {
            "panel_opened": "Session ID" in s,
            "queued_instead": texts(s) != [],
            "still_busy": bool(BUSY.search(s)),
            "alive": lab.alive(),
        }
        lab.stop()
        return out

    a = run(binary, "slash-p")
    b = run(control, "slash-c")
    ok = a == b and a["panel_opened"] and a["alive"]
    print(f"  G2  /slash while busy    patched {a}")
    print(f"                           control {b}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def g3_six_queued(binary):
    """B8: six waiting messages run one at a time, in the order shown."""
    lab, ws = start(binary, "six")
    lab.send(SHORT)
    busy_wait(lab, limit=60)
    words = ["ONEWORD", "TWOWORD", "THREEWORD", "FOURWORD", "FIVEWORD", "SIXWORD"]
    for w in words:
        lab.send(f"q say the word {w} and nothing else")
        lab._pump(0.4)
    lab._pump(1.5)
    shown = len(texts(lab.screen()))

    t0 = time.time()
    while time.time() - t0 < 420:
        lab._pump(3.0)
        if not texts(lab.screen()) and not BUSY.search(lab.screen()):
            break
    lab._pump(4.0)
    seen, _ = transcript_order(ws, words)
    lab.stop()
    ok = shown == 6 and seen == words
    print(f"  G3  six queued           all six shown={shown == 6}")
    print(f"      ran in order: {seen}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def g4_selector_walk(binary):
    """C4, C7, C8, D5: walk the list, edit the middle one, keep the rest."""
    lab, _ = start(binary, "walk")
    lab.send(SLOW)
    busy_wait(lab)
    long_one = "delta " + "very long tail that wraps across several lines " * 4
    for q in ["q alpha", "q bravo", "q charlie", "q " + long_one]:
        lab.send(q)
        lab._pump(0.5)
    lab._pump(1.5)
    start_rows = texts(lab.screen())

    for _ in range(4):        # up to the top
        lab.key("up")
        lab._pump(0.6)
    at_top = picked(lab.screen())

    lab.key("down")           # C4: back down through the list
    lab._pump(0.7)
    second = picked(lab.screen())
    for _ in range(3):        # C4: past the bottom clears the selection
        lab.key("down")
        lab._pump(0.6)
    cleared = picked(lab.screen()) is None

    lab.key("up")             # back on the last one, C8
    lab._pump(0.7)
    on_last = picked(lab.screen())

    lab.key("up")             # C7: the middle one
    lab.key("up")
    lab._pump(0.7)
    middle = picked(lab.screen())
    enter(lab)
    lab._pump(1.5)
    editor = input_area(lab.screen())
    left = texts(lab.screen())
    alive = lab.alive()
    lab.stop()

    checks = {
        "four queued": len(start_rows) == 4,
        "top is alpha": at_top == "alpha",
        "down goes to bravo": second == "bravo",
        "past the bottom clears": cleared,
        "last is the long one": bool(on_last) and on_last.startswith("delta"),
        "middle is bravo": middle == "bravo",
        "bravo reached the editor": "bravo" in editor,
        "the other three stay": left[:2] == ["alpha", "charlie"] and len(left) == 3,
        "alive": alive,
    }
    ok = all(checks.values())
    print(f"  G4  walk the selector    top={at_top!r}, then {second!r}, "
          f"last={str(on_last)[:22]!r}, edited={middle!r}")
    print(f"      still queued={left}")
    if not ok:
        print(f"      failed: {[k for k, v in checks.items() if not v]}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def g5_escape_and_empty(binary):
    """C9 + C10: abandoning an edit, and sending an edit with nothing left.

    Escape empties the whole queue into the editor and interrupts the turn.
    That looks alarming written down, and it is exactly what an unpatched build
    does: the same probe against the control produced the same two effects. So
    this asserts the stock shape, and any drift away from it is the failure.
    """
    lab, _ = start(binary, "esc")
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q one", "q two"]:
        lab.send(q)
        lab._pump(0.5)
    lab._pump(1.2)

    lab.key("up")             # on "two"
    lab._pump(0.7)
    enter(lab)                # pull it into the editor
    lab._pump(1.2)
    in_editor = "two" in input_area(lab.screen())
    lab.key("escape")         # C9: abandon it
    lab._pump(1.0)
    after_escape = texts(lab.screen())
    still_typed = "two" in input_area(lab.screen())

    # C10: clear the editor completely and press enter
    for _ in range(40):
        lab.write(b"\x7f")
    lab._pump(0.8)
    enter(lab)
    lab._pump(1.5)
    after_empty = texts(lab.screen())
    alive = lab.alive()
    lab.stop()

    ok = (in_editor and alive and after_escape == [] and still_typed
          and after_empty == [])
    print(f"  G5  escape and empty     pulled into editor={in_editor}, "
          f"queue after escape={after_escape} (both texts in editor={still_typed})")
    print(f"      after clearing and pressing enter: {after_empty}, alive={alive}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def g6_ctrl_c(binary, control):
    """D2: Ctrl-C has to end in the same state as it does on a stock build.

    Read at the settled state, after two presses. One press leaves the two
    builds mid-flight in different places for a reason that has nothing to do
    with the key: on stock the message never sat in the queue, it folded into
    the turn immediately, so stock is still working on it when patched is
    already idle. Comparing that instant compares the queue, not Ctrl-C.
    """
    def run(b, name, message):
        lab, _ = start(b, name)
        lab.send(SLOW)
        busy_wait(lab)
        lab.send(message)
        lab._pump(1.2)
        lab.key("ctrl-c")
        lab._pump(2.5)
        lab.key("ctrl-c")
        lab._pump(3.5)
        s = lab.screen()
        out = {
            "alive": lab.alive(),
            "still_busy": bool(BUSY.search(s)),
            "queue_empty": texts(s) == [],
            "message_in_editor": "something waiting" in input_area(s),
            # Read from the whole stream, not the visible screen: the two builds
            # print a different number of lines, so on one of them the notice
            # has already scrolled out of a 44 row window.
            "interrupt_shown": "Interrupted" in lab.raw.decode("utf-8", "replace"),
        }
        lab.stop()
        return out

    a = run(binary, "ctrlc-p", "q something waiting")
    b = run(control, "ctrlc-c", "something waiting")
    # What has to match is the KEY: it interrupts, it settles, and the
    # session survives. What happens to the queue afterwards is the patch
    # itself and is documented as different: stock hands the whole queue
    # to the editor, this releases the first waiting message and holds
    # the rest. Asserting those are identical would be asserting the
    # patch does nothing.
    same = ["alive", "still_busy", "interrupt_shown", "queue_empty"]
    ok = all(a[k] == b[k] for k in same)
    print(f"  G6  ctrl-c vs control    patched {a}")
    print(f"                           control {b}")
    print(f"      key behaviour matches on {same}")
    print(f"      -> {'PASS' if ok else 'FAIL, the key itself behaves differently'}")
    return ok


def g7_vim_mode(binary):
    """D4: with vim mode on, the arrows still pick and shift still reorders."""
    lab, _ = start(binary, "vim")
    lab.send("/vim")
    lab._pump(2.5)
    vim_on = "vim" in lab.screen().lower()
    lab.send(SLOW)
    busy_wait(lab)
    for q in ["q alpha", "q bravo", "q charlie"]:
        lab.send(q)
        lab._pump(0.5)
    expect_three(lab)
    before = texts(lab.screen())

    lab.key("up")
    lab._pump(0.8)
    sel = picked(lab.screen())
    lab.key("shift-up")
    lab._pump(0.9)
    after = texts(lab.screen())
    alive = lab.alive()
    lab.stop()

    ok = (alive and before == ["alpha", "bravo", "charlie"]
          and sel == "charlie" and after == ["alpha", "charlie", "bravo"])
    print(f"  G7  vim mode             vim reported on={vim_on}, {before} -> {after}, "
          f"picked {sel!r}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def g8_multiline_paste(binary):
    """A13: pasted code is literal even when lines begin with q or s.

    Wrapped in real bracketed-paste markers. An earlier version faked the
    newlines with backslash-then-return, which the input treats as typing, not
    pasting, and it submitted at the first line: a test failure that said
    nothing about pasting.
    """
    lab, _ = start(binary, "paste")
    lab.send(SLOW)
    busy_wait(lab)
    lab.write(b"\x1b[200~def rebuild():\n    pass\nq = deque()\n"
              b"s = socket()\nresult = q.get()\x1b[201~")
    lab._pump(1.5)
    enter(lab)
    t0 = time.time()
    while time.time() - t0 < 20:
        lab._pump(0.5)
        if texts(lab.screen()):
            break
    screen = lab.screen()
    rows = texts(screen)
    if not rows:
        lab.stop()
        raise SetupFailed(
            "the pasted block never queued; the turn had already ended")

    # The fold now hides everything after the first line of a multi-line
    # message, so the folded row proves it is ONE message and the body has to
    # be read after unfolding it with the highlight. Before the fold existed
    # this read the body straight off the screen.
    folded = rows == ["def rebuild(): (+4 lines)"]
    lab.key("up")
    lab._pump(1.2)
    unfolded = lab.screen()
    alive = lab.alive()
    lab.stop()

    kept = "q = deque()" in unfolded and "s = socket()" in unfolded
    whole = folded or rows == ["def rebuild():"]
    mangled = any(row.startswith("= deque") or row.startswith("= socket")
                  for row in rows)
    ok = kept and whole and not mangled and alive
    print(f"  G8  pasted code literal  labelled row: {rows}")
    print(f"      folded to one row={folded}, names visible after unfold={kept}, "
          f"mangled={mangled} -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    control = _control()
    allow_drift = "--allow-setup-drift" in sys.argv
    only = [a[2:] for a in sys.argv[1:]
            if a.startswith("--") and a not in ("--", "--allow-setup-drift")]
    print(f"  binary: {Path(binary).name}\n")

    tests = [g1_idle_marker, g2_slash_while_busy, g3_six_queued, g4_selector_walk,
             g5_escape_and_empty, g6_ctrl_c, g7_vim_mode, g8_multiline_paste]
    if only:
        tests = [t for t in tests if any(o in t.__name__ for o in only)]

    results = {}
    for fn in tests:
        try:
            results[fn.__name__] = (fn(binary, control)
                                    if fn in (g6_ctrl_c, g2_slash_while_busy)
                                    else fn(binary))
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
        print(f"  setup never held for: {skipped}")
    for k, v in results.items():
        if not v:
            print(f"    still failing: {k}")
    return 0 if passed == len(results) or \
        (allow_drift and passed + len(skipped) == len(results)) else 1


if __name__ == "__main__":
    sys.exit(main())
