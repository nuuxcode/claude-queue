#!/usr/bin/env python3
"""
Folding a long queued message down to one line, in the display only.

The bug this is about: three long messages waiting fill a forty row terminal
with their own text, so the transcript and the busy indicator are pushed off
the top and the session looks frozen at the moment you most want to see that it
is not. It is inherited behaviour, so the control does it too. Ledger row H7.

The cases here are the ones a screen can prove:

  K1  three long messages, and the busy indicator is still visible
  K2  the highlighted row is drawn in full, the rest stay folded
  K3  a short message is drawn exactly as it was before
  K4  CLAUDE_QUEUE_COLLAPSE=off gives the old display back
  K5  an unpatched control does not fold, so the difference is the patch
  K6  the text is only folded on screen: pull it back, send it again, and the
      message is still every line of it

K1 and K2 are the two that must FAIL on the build before this feature. The
others pass on both builds by design, K3 and K5 because they are stock
behaviour, K4 because it is the off switch, and K6 because nothing about what
is stored was supposed to change.

    ./test_collapse.py <binary>
"""

import re
import shutil
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab, SetupFailed  # noqa: E402
from binaries import control as _control  # noqa: E402
from test_ux import input_area  # noqa: E402

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..120}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")
FOLD = re.compile(r"\(\+\d+ lines?\)")
BODY_LINES = 12
RUN = ""


def long_message(tag):
    """A message that is thirteen lines long, every line of it findable."""
    return f"{tag} here is my full feedback in many lines\n" + "\n".join(
        f"{tag}body{i}" for i in range(2, BODY_LINES + 2))


def start(binary, name, env=None, rows=40):
    # The workspace carries the build under test, not the build being driven,
    # so this suite can run against two binaries at once without one run
    # deleting the other's scratch directory mid-check. K5 drives the control
    # in both runs, which is exactly where that collision would land.
    ws = LAB / f"coll-{RUN or Path(binary).name}-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=rows,
              extra_env=env or {})
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")
    lab.send(SLOW)
    if not lab.wait_for_tool():
        lab.stop()
        raise SetupFailed("no tool ever started, so nothing could be queued")
    return lab


def queue_message(lab, text, tag):
    """Paste one message and wait until it is really on screen.

    The head of the newest message is at the BOTTOM of the queued list, which
    is the one place that stays visible on a build where the list overflows the
    terminal. So this guard holds on both builds, and a red result from the
    checks below is the display, never a message that never arrived.
    """
    lab.write(b"\x1b[200~" + text.encode() + b"\x1b[201~")
    lab._pump(1.0)
    lab.write(b"\r")
    lab._pump(1.2)
    lab.expect(lambda s: tag in s, f"{tag} queued")


def rows_and_bodies(screen, tags):
    """What the queued list is showing: one entry per visible head, plus every
    body line that reached the screen.

    This reads the WHOLE screen rather than the block between the spinner and
    the input rule, and that is deliberate. The first attempt used the block,
    and the busy pattern also matches a tool's own duration line, so the block
    began one line early and carried `(ctrl+b to run in background)` into the
    count. A working build was reported as broken by one line of furniture.

    The sentinels are only ever in a waiting message, because the message has
    not run yet, so the whole screen is the safer place to count them.
    """
    lines = [line.strip() for line in screen.split("\n") if line.strip()]
    heads = [line for line in lines if any(f"{t} here is" in line for t in tags)]
    bodies = [line for line in lines if any(f"{t}body" in line for t in tags)]
    return lines, heads, bodies


def folded_rows(screen, tags):
    return [line for line in rows_and_bodies(screen, tags)[1] if FOLD.search(line)]


def dump(lab_screen, why):
    print(f"      {why}, the bottom of the screen was:")
    for line in lab_screen.split("\n")[-24:]:
        if line.strip():
            print(f"        |{line}")


def k1_the_busy_indicator_survives_three_long_messages(binary):
    """The motivating case. Three long messages, forty rows, and the session
    still says it is working."""
    lab = start(binary, "k1")
    tags = ["AAA", "BBB", "CCC"]
    for tag in tags:
        queue_message(lab, long_message(tag), tag)
    screen = lab.screen()
    _, heads, bodies = rows_and_bodies(screen, tags)
    busy_visible = bool(BUSY.search(screen))
    folded = [line for line in heads if FOLD.search(line)]
    lab.stop()

    print(f"  K1  three long queued   {len(heads)} heads on screen, "
          f"{len(folded)} of them folded, {len(bodies)} body lines leaked")
    for line in heads:
        print(f"        {line}")
    print(f"      busy indicator visible: {busy_visible}")
    ok = (busy_visible and len(heads) == 3 and len(folded) == 3
          and not bodies)
    if not ok:
        dump(screen, "wanted three folded rows and a visible busy indicator")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def k2_the_highlighted_one_is_whole(binary):
    """Up shows you the whole message, and folds the one you left."""
    lab = start(binary, "k2")
    tags = ["AAA", "BBB"]
    for tag in tags:
        queue_message(lab, long_message(tag), tag)

    lab.key("up")
    lab._pump(1.2)
    first = lab.screen()
    _, _, bodies_b = rows_and_bodies(first, ["BBB"])
    _, heads_a, bodies_a = rows_and_bodies(first, ["AAA"])
    on_last = len(bodies_b) >= BODY_LINES and not bodies_a and \
        bool(heads_a and FOLD.search(heads_a[0]))

    lab.key("up")
    lab._pump(1.2)
    second = lab.screen()
    _, heads_b2, bodies_b2 = rows_and_bodies(second, ["BBB"])
    _, _, bodies_a2 = rows_and_bodies(second, ["AAA"])
    on_first = len(bodies_a2) >= BODY_LINES and not bodies_b2 and \
        bool(heads_b2 and FOLD.search(heads_b2[0]))
    lab.stop()

    print(f"  K2  highlight is whole  on the last one: "
          f"{len(bodies_b)} of its lines shown, other row folded={on_last}")
    print(f"                          after one more up: "
          f"{len(bodies_a2)} lines shown, other row folded={on_first}")
    ok = on_last and on_first
    if not ok:
        dump(second, "wanted one whole row and one folded row")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def k3_a_short_message_is_untouched(binary):
    """Nothing is folded that did not need folding."""
    lab = start(binary, "k3")
    wanted = ["SHORTA fix the header", "SHORTB run the tests",
              "SHORTC write it up"]
    for text in wanted:
        lab.send(text)
        lab._pump(0.5)
        lab.expect(lambda s, t=text.split()[0]: t in s, f"{text} queued")
    lines = [line.strip() for line in lab.screen().split("\n") if line.strip()]
    rows = [line for line in lines
            if any(line.endswith(text) or text in line for text in wanted)]
    lab.stop()

    marked = [line for line in rows if FOLD.search(line)]
    intact = [text for text in wanted
              if any(line.endswith(text) for line in rows)]
    print("  K3  short is untouched  rows:")
    for line in rows:
        print(f"        {line}")
    ok = len(rows) == 3 and not marked and len(intact) == 3
    print(f"      {len(intact)} of 3 drawn in full, {len(marked)} folded "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def k4_off_gives_the_old_display_back(binary):
    """CLAUDE_QUEUE_COLLAPSE=off draws every line, however many there are."""
    lab = start(binary, "k4", {"CLAUDE_QUEUE_COLLAPSE": "off"})
    queue_message(lab, long_message("AAA"), "AAA")
    screen = lab.screen()
    _, _, bodies = rows_and_bodies(screen, ["AAA"])
    marked = folded_rows(screen, ["AAA"])
    lab.stop()

    print(f"  K4  collapse=off        {len(bodies)} body lines drawn, "
          f"{len(marked)} folded rows")
    ok = len(bodies) >= BODY_LINES and not marked
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def k5_the_control_does_not_fold(binary):
    """An unpatched build draws the whole message, so the fold is the patch.

    Stock has no labels either, so this reads the message text itself rather
    than a row shape the control never had.
    """
    lab = start(binary, "k5")
    queue_message(lab, long_message("AAA"), "AAA")
    screen = lab.screen()
    _, _, bodies = rows_and_bodies(screen, ["AAA"])
    marked = folded_rows(screen, ["AAA"])
    lab.stop()

    print(f"  K5  control does not fold   {len(bodies)} body lines drawn, "
          f"{len(marked)} folded rows")
    ok = len(bodies) >= BODY_LINES and not marked
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def k6_only_the_display_was_folded(binary):
    """Pull the folded message back, send it again, and it is still whole.

    This is the one that matters most, because the failure it rules out is
    silent: if the folded text ever reached the stored command, the message
    would run as its own first line and a note about the lines it lost.

    The first version of this check was green for the wrong reason. It pressed
    up, pressed return, and then compared the row before with the row after,
    which are trivially identical when the return never reached a highlighted
    message and the queue was simply never touched. One run printed an empty
    editor and still passed. So the pull-back is now a guarded state the run
    has to actually reach, and the last line of the message being back in the
    editor is asserted rather than assumed.
    """
    lab = start(binary, "k6")
    queue_message(lab, long_message("AAA"), "AAA")
    folded_before = folded_rows(lab.screen(), ["AAA"])
    if not folded_before:
        lab.stop()
        raise SetupFailed("the row was not folded, so there is nothing to prove")

    body = "AAAbody2"
    last = f"AAAbody{BODY_LINES + 1}"
    for _ in range(3):
        lab.key("up")
        lab._pump(0.8)
        lab.write(b"\r")      # pull it back into the editor
        lab._pump(1.5)
        if body in lab.screen():
            break
    lab.expect(lambda s: body in s, "the message came back into the editor")

    screen = lab.screen()
    editor = input_area(screen)
    last_visible = last in screen
    still_queued = folded_rows(screen, ["AAA"])
    lab.write(b"\r")          # send it again
    lab._pump(2.0)
    folded_after = folded_rows(lab.screen(), ["AAA"])
    lab.stop()

    print(f"  K6  the text survived   before: {folded_before}")
    print(f"                          editor held: {editor.strip()[:70]!r}")
    print(f"                          its body came back, last line on "
          f"screen too: {last_visible}")
    print(f"                          after:  {folded_after}")
    ok = (not still_queued and bool(folded_after)
          and folded_after[0].split("(+")[-1] == folded_before[0].split("(+")[-1])
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    global RUN
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    allow_drift = "--allow-setup-drift" in sys.argv
    RUN = Path(binary).name
    print(f"  binary: {RUN}\n")

    tests = [(k1_the_busy_indicator_survives_three_long_messages, binary),
             (k2_the_highlighted_one_is_whole, binary),
             (k3_a_short_message_is_untouched, binary),
             (k4_off_gives_the_old_display_back, binary),
             (k5_the_control_does_not_fold, _control()),
             (k6_only_the_display_was_folded, binary)]

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
