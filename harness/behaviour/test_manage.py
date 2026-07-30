#!/usr/bin/env python3
"""
The v1.7.0 pair: removing a queued message, and one submission becoming several.

Delete is the dangerous one. It binds a key everybody uses constantly, so most
of these tests are about the cases where it must do NOTHING.

    ./test_manage.py <binary>
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
from test_reorder import (SetupFailed, expect_queue, picked,  # noqa: E402
                          texts, transcript_order)

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..90}; do echo $i; sleep 1; done")
SHORT = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
         "for i in {1..25}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")
BACKSPACE = b"\x7f"
DEL = b"\x1b[3~"


def start(binary, name, env=None):
    ws = LAB / f"mg-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=40,
              extra_env=env or {})
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")
    lab.send(SLOW if name not in ("order",) else SHORT)
    t0 = time.time()
    while time.time() - t0 < 90:
        lab._pump(0.3)
        if BUSY.search(lab.screen()):
            break
    return lab, ws


def paste(lab, text):
    lab.write(b"\x1b[200~" + text.encode() + b"\x1b[201~")
    lab._pump(1.2)


def enter(lab):
    lab.write(b"\r")
    lab._pump(1.5)


def key(lab, raw):
    lab.write(raw)
    lab._pump(1.0)


# -- delete ----------------------------------------------------------------


def d1_delete_the_picked_one(binary):
    """The highlighted message goes, the others do not move."""
    lab, _ = start(binary, "d1")
    for q in ["q alpha", "q bravo", "q charlie"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)

    lab.key("up")
    lab.key("up")
    lab._pump(0.7)
    on = picked(lab.screen())
    key(lab, BACKSPACE)
    after = texts(lab.screen())
    now_on = picked(lab.screen())
    alive = lab.alive()
    lab.stop()

    ok = on == "bravo" and after == ["alpha", "charlie"] and alive
    print(f"  D1  delete the picked   was on {on!r}, queue now {after}, "
          f"highlight now {now_on!r}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def d2_text_wins(binary):
    """With anything typed, the key edits the text and never the queue.

    This is the whole safety argument for binding backspace at all. If it ever
    fails, the feature has to be moved to a key nobody presses by reflex.
    """
    lab, _ = start(binary, "d2")
    for q in ["q alpha", "q bravo"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 2)

    lab.key("up")
    lab._pump(0.7)
    lab.type("hello")
    lab._pump(0.6)
    for _ in range(3):
        key(lab, BACKSPACE)
    screen = lab.screen()
    after = texts(screen)
    editor_has = "he" in screen and "hello" not in screen
    alive = lab.alive()
    lab.stop()

    ok = after == ["alpha", "bravo"] and editor_has and alive
    print(f"  D2  typed text wins     queue untouched={after == ['alpha', 'bravo']}, "
          f"text was edited={editor_has}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def d3_nothing_picked(binary):
    """With no highlight, the key does nothing to the queue."""
    lab, _ = start(binary, "d3")
    for q in ["q alpha", "q bravo"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 2)
    before = texts(lab.screen())
    for _ in range(4):
        key(lab, BACKSPACE)
    key(lab, DEL)
    screen = lab.screen()
    after = texts(screen)
    alive = lab.alive()
    still_busy = bool(BUSY.search(screen))
    lab.stop()

    # If the turn ended, the queue drained on its own and this says nothing
    # about the key. Claiming "backspace ate a message" on that evidence would
    # be exactly the mistake this suite exists to avoid.
    if not still_busy:
        raise SetupFailed(
            f"the turn ended during the run, so the queue drained by itself; "
            f"it holds {after}")

    ok = before == after == ["alpha", "bravo"] and alive
    print(f"  D3  nothing picked      {before} -> {after}, alive={alive} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def d4_delete_them_all(binary):
    """Emptying the queue one at a time must not break the session."""
    lab, _ = start(binary, "d4")
    for q in ["q alpha", "q bravo", "q charlie"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 3)

    lab.key("up")
    lab._pump(0.7)
    for _ in range(3):
        key(lab, BACKSPACE)
    after = texts(lab.screen())
    alive = lab.alive()
    # the session must still take a new message afterwards
    lab.send("q survivor")
    lab._pump(1.5)
    final = texts(lab.screen())
    lab.stop()

    ok = after == [] and alive and final == ["survivor"]
    print(f"  D4  delete them all     empty after three={after == []}, "
          f"still usable={final}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def d5_delete_key_too(binary):
    """The forward-delete key does the same thing as backspace."""
    lab, _ = start(binary, "d5")
    for q in ["q alpha", "q bravo"]:
        lab.send(q)
        lab._pump(0.4)
    expect_queue(lab, 2)
    lab.key("up")
    lab._pump(0.7)
    key(lab, DEL)
    after = texts(lab.screen())
    alive = lab.alive()
    lab.stop()
    ok = after == ["alpha"] and alive
    print(f"  D5  forward delete      queue now {after} -> {'PASS' if ok else 'FAIL'}")
    return ok


def d6_control(binary):
    """On an unpatched build the key destroys nothing and the session lives.

    The claim cannot be "the queued messages are still queued", because on
    stock they are not queued for long: typed mid-turn they fold into the
    running turn and scroll away. An earlier version of this test looked for
    them on the visible screen, found they had already run, and reported a
    working control as broken.

    So it asserts the thing that actually matters for a control: pressing the
    key repeatedly with an empty editor changes nothing and breaks nothing.
    """
    lab, _ = start(binary, "d6")
    for q in ["alpha", "bravo"]:
        lab.send(q)
        lab._pump(0.4)
    lab._pump(1.5)
    lab.key("up")
    lab._pump(0.7)
    for _ in range(3):
        key(lab, BACKSPACE)
    lab._pump(1.0)
    stream = lab.raw.decode("utf-8", "replace")
    alive = lab.alive()
    lab.stop()

    both_sent = "alpha" in stream and "bravo" in stream
    ok = alive and both_sent
    print(f"  D6  control survives    both messages reached the session={both_sent}, "
          f"alive after three backspaces={alive}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


# -- one submission, several messages --------------------------------------


def s1_every_line_marked(binary):
    """Three marked lines become three messages, each with its own timing."""
    lab, _ = start(binary, "s1")
    paste(lab, "q: write the notes\nq: run the tests\ns: check the logs")
    enter(lab)
    lab._pump(1.5)
    screen = lab.screen()
    lab.stop()

    got = texts(screen)
    # each line keeps the timing its own marker asked for, so the s line must
    # be the only jumping one
    kinds = ["jumps" if "[jumps in]" in ln else "waits"
             for ln in screen.split("\n")
             if "[waits]" in ln or "[jumps in]" in ln]
    ok = (got == ["write the notes", "run the tests", "check the logs"]
          and kinds == ["waits", "waits", "jumps"])
    print(f"  S1  every line marked   {got}")
    print(f"      timings {kinds} -> {'PASS' if ok else 'FAIL'}")
    return ok


def s2_mixed_block_stays_one(binary):
    """Only the first line marked: it stays ONE message, markers intact."""
    lab, _ = start(binary, "s2")
    paste(lab, "q: one paragraph\nsecond line no marker\nthird line")
    enter(lab)
    lab._pump(1.5)
    rows = texts(lab.screen())
    # the fold hides the body, so unfold with the highlight before reading it
    lab.key("up")
    lab._pump(1.2)
    screen = lab.screen()
    kept = "second line no marker" in screen and "third line" in screen
    lab.stop()
    ok = rows == ["one paragraph"] and kept
    print(f"  S2  mixed block         labelled rows {rows}, later lines kept={kept}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def s3_split_runs_in_order(binary):
    """The real one: split messages run as separate turns, in order."""
    lab, ws = start(binary, "order")
    paste(lab, "q: say the word ONEWORD and nothing else\n"
               "q: say the word TWOWORD and nothing else\n"
               "q: say the word REDWORD and nothing else")
    enter(lab)
    lab._pump(2.0)
    shown = len(texts(lab.screen()))

    t0 = time.time()
    while time.time() - t0 < 300:
        lab._pump(3.0)
        if not texts(lab.screen()) and not BUSY.search(lab.screen()):
            break
    lab._pump(4.0)
    seen, _ = transcript_order(ws, ["ONEWORD", "TWOWORD", "REDWORD"])
    lab.stop()
    ok = shown == 3 and seen == ["ONEWORD", "TWOWORD", "REDWORD"]
    print(f"  S3  split runs in order three queued={shown == 3}, ran {seen}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def s4_split_then_manage(binary):
    """Split messages are ordinary queue members: movable, editable, removable."""
    lab, _ = start(binary, "s4")
    paste(lab, "q: alpha\nq: bravo\nq: charlie")
    enter(lab)
    lab._pump(1.5)
    before = texts(lab.screen())

    lab.key("up")            # charlie
    lab._pump(0.7)
    lab.key("shift-up")      # move it up
    lab._pump(0.9)
    moved = texts(lab.screen())
    key(lab, BACKSPACE)      # and remove it
    after = texts(lab.screen())
    alive = lab.alive()
    lab.stop()

    ok = (before == ["alpha", "bravo", "charlie"]
          and moved == ["alpha", "charlie", "bravo"]
          and after == ["alpha", "bravo"] and alive)
    print(f"  S4  split then manage   {before} -> {moved} -> {after}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def s5_continuation_lines(binary):
    """A marker starts a message; an unmarked line continues the one above."""
    lab, _ = start(binary, "s5")
    paste(lab, "q: alpha\nq: bravo\nstill bravo\nq: delta")
    enter(lab)
    lab._pump(2.0)
    screen = lab.screen()
    rows = texts(screen)
    # the fold count on the bravo row IS the continuation proof
    joined = "bravo (+1 line)" in screen
    lab.stop()

    ok = rows == ["alpha", "bravo", "delta"] and joined
    print(f"  S5  continuation lines  'q: alpha / q: bravo / still bravo / q: delta'")
    print(f"      -> {rows}, the unmarked line stayed attached={joined}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def s6_leading_text(binary):
    """A paste with leading text stays literal instead of becoming a batch."""
    lab, _ = start(binary, "s6")
    paste(lab, "leading words\nq: after that")
    enter(lab)
    lab._pump(2.0)
    rows = texts(lab.screen())
    lab.key("up")
    lab._pump(1.2)
    screen = lab.screen()
    lab.stop()
    literal = "q: after that" in screen
    ok = rows == ["leading words"] and literal
    print(f"  S6  leading paste text  {rows}, colon line literal after unfold="
          f"{literal} -> {'PASS' if ok else 'FAIL'}")
    return ok


def s7_split_when_idle(binary):
    """Idle: the first job becomes the turn, the rest queue behind it.

    This was broken until Mounssif reported it. A block typed into a session
    with nothing running arrived as one message, which looked from outside like
    "the split only works when something is already queued".
    """
    ws = LAB / "mg-idle"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=40)
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")

    # The first job has to take a while, or it finishes before anything can be
    # read and the next one drains: the state under test would be gone.
    paste(lab, "q: " + SLOW + "\nq: say IDLETWO only\nq: say IDLETHREE only")
    enter(lab)
    t0 = time.time()
    while time.time() - t0 < 60:
        lab._pump(0.4)
        if "Bash(" in lab.screen():
            break
    lab._pump(1.5)
    screen = lab.screen()
    rows = texts(screen)
    first_ran = "Bash(" in screen
    lab.stop()

    ok = first_ran and rows == ["say IDLETWO only", "say IDLETHREE only"]
    print(f"  S7  split while idle    first became the turn={first_ran}, "
          f"queued behind it={rows}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def s8_edge_shapes(binary):
    """The shapes that are easy to get wrong, each read rather than assumed.

    A blank line between jobs must not become a job. A marker with no body is
    not a marker, so it continues the line above. The leading-space escape still
    works inside a block. And six at once is six.
    """
    checks = [
        ("blank line between jobs", "q: first job\n\nq: second job",
         ["first job", "second job"]),
        ("marker with no body", "q: real one\nq:\nq: other one",
         ["real one", "other one"]),
        ("leading space escape", "q: first\n q: not a marker\nq: real marker",
         ["first", "real marker"]),
        ("six at once", "\n".join(f"q: job{i}" for i in range(1, 7)),
         [f"job{i}" for i in range(1, 7)]),
    ]
    ok = True
    for title, text, want in checks:
        lab, _ = start(binary, "s8")
        paste(lab, text)
        enter(lab)
        lab._pump(2.5)
        got = texts(lab.screen())
        lab.stop()
        good = got == want
        ok = ok and good
        print(f"  S8  {title:24} {got}")
        print(f"      wanted {want} -> {'PASS' if good else 'FAIL'}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def t1_tab_is_the_opposite(binary):
    """Tab sends with the opposite timing to your default, and a marker wins.

    Both defaults are driven, because the whole point of the key is that it
    works whichever way round you like your default. With the stock default put
    back it is Codex's exact arrangement: enter steers, tab queues.
    """
    ok = True
    for env, want_enter, want_tab in (
            ({}, "waits", "jumps"),
            ({"CLAUDE_QUEUE_DEFAULT": "steer"}, "jumps", "waits")):
        lab, _ = start(binary, "tab", env)
        lab.send("sent with enter")
        lab._pump(1.5)
        lab.type("sent with tab")
        lab._pump(0.5)
        lab.write(b"\t")
        lab._pump(2.0)
        lab.type("q marker wins over tab")
        lab._pump(0.5)
        lab.write(b"\t")
        lab._pump(2.0)
        rows = [("jumps" if "[jumps in]" in ln else "waits",
                 ln.split("]", 1)[1].strip())
                for ln in lab.screen().split("\n")
                if "[waits]" in ln or "[jumps in]" in ln]
        lab.stop()

        got = dict((t, k) for k, t in rows)
        good = (got.get("sent with enter") == want_enter
                and got.get("sent with tab") == want_tab
                and got.get("marker wins over tab") == "waits")
        ok = ok and good
        name = "default" if not env else "DEFAULT=steer"
        print(f"  T1  tab, {name:14} enter={got.get('sent with enter')} "
              f"(want {want_enter}), tab={got.get('sent with tab')} "
              f"(want {want_tab}), marker={got.get('marker wins over tab')} "
              f"(want waits)")
        print(f"      -> {'PASS' if good else 'FAIL'}")
    return ok


def t2_tab_on_slash_does_not_leak(binary):
    """Tab may submit a slash command, but cannot invert the next message."""
    lab, _ = start(binary, "tab-slash", {"CLAUDE_QUEUE_DEFAULT": "steer"})
    lab.type("/status ")
    key(lab, b"\t")
    lab.key("escape")
    lab._pump(0.5)
    lab.send("AFTER_SLASH_TAB")
    lab._pump(1.5)
    screen = lab.screen()
    line = next((ln for ln in screen.splitlines()
                 if "AFTER_SLASH_TAB" in ln and "[" in ln), "")
    lab.stop()
    ok = "[jumps in]" in line
    print(f"  T2  tab on slash        next message row={line.strip()!r}")
    print(f"      -> {'PASS' if ok else 'FAIL, inversion leaked'}")
    return ok


def t3_tab_on_shell_is_contained(binary):
    """Tab submits shell input and cannot invert the next prompt."""
    lab, _ = start(binary, "tab-shell", {"CLAUDE_QUEUE_DEFAULT": "steer"})
    lab.type("! printf TAB_SHELL")
    key(lab, b"\t")
    key(lab, BACKSPACE)  # leave the persistent shell editor
    lab.send("AFTER_SHELL_TAB")
    lab._pump(1.5)
    screen = lab.screen()
    line = next((ln for ln in screen.splitlines()
                 if "AFTER_SHELL_TAB" in ln and "[" in ln), "")
    shell_kept = "! printf TAB_SHELL" in screen
    lab.stop()
    ok = shell_kept and "[jumps in]" in line
    print(f"  T3  tab on shell        shell kept={shell_kept}, "
          f"next message row={line.strip()!r}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    control = _control()
    allow_drift = "--allow-setup-drift" in sys.argv
    print(f"  binary: {Path(binary).name}\n")

    tests = [(d1_delete_the_picked_one, binary), (d2_text_wins, binary),
             (d3_nothing_picked, binary), (d4_delete_them_all, binary),
             (d5_delete_key_too, binary), (d6_control, control),
             (s1_every_line_marked, binary), (s2_mixed_block_stays_one, binary),
             (s4_split_then_manage, binary), (s5_continuation_lines, binary),
             (s6_leading_text, binary), (s7_split_when_idle, binary),
             (s8_edge_shapes, binary), (t1_tab_is_the_opposite, binary),
             (t2_tab_on_slash_does_not_leak, binary),
             (t3_tab_on_shell_is_contained, binary),
             (s3_split_runs_in_order, binary)]

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
        print(f"  setup never held for: {skipped}")
    for k, v in results.items():
        if v is False:
            print(f"    still failing: {k}")
    return 0 if passed == len(results) or \
        (allow_drift and passed + len(skipped) == len(results)) else 1


if __name__ == "__main__":
    sys.exit(main())
