#!/usr/bin/env python3
"""
The three scenarios that were left open because they each need a driver the
other suites do not have.

  H1  a message queued while a SUBAGENT is running
  H2  a queued message carrying a pasted IMAGE
  H3  the turn ending at the instant you press enter

H3 cannot be triggered on demand from outside the program, so it is run as a
statistical check rather than a single case: the same submit is fired at many
different offsets around the end of a turn, and the claim is that the message is
never lost and never duplicated. That is weaker than a deterministic test and
it is labelled as such.

    ./test_hard.py [binary]
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab  # noqa: E402
from binaries import patched as _patched  # noqa: E402

SLOW = ("run this exact bash command in the foreground and wait for it "
        "to finish. do not run it in the background, do not change it: "
        "for i in {1..90}; do echo $i; sleep 1; done")
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")
PROJECTS = Path.home() / ".claude" / "projects"


class SetupFailed(Exception):
    """The run never reached the state under test. Not a product failure."""


def start(binary, name, rows=44):
    ws = LAB / f"hd-{name}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    lab = Lab(binary=binary, workspace=str(ws), cols=96, rows=rows)
    lab.start(settle=12)
    if not lab.alive():
        raise RuntimeError("session died during boot")
    return lab, ws


def texts(screen):
    out = []
    for ln in screen.split("\n"):
        if "[waits]" in ln or "[jumps in]" in ln:
            out.append(ln.split("]", 1)[1].strip())
    return out


def wait_for(lab, needle, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        lab._pump(0.4)
        if needle in lab.screen():
            return True
    return False


# --------------------------------------------------------------------------


def h1_subagent(binary):
    """A message queued while a subagent works must wait for the WHOLE turn.

    A subagent is a turn inside a turn. The worry is that its completion looks
    like a turn boundary and releases the queue early, which would mean a
    waiting message landing in the middle of the parent's work.
    """
    lab, ws = start(binary, "subagent")
    lab.send(
        "use the Task tool to launch one general-purpose agent, and tell it to "
        "run this exact bash command in the foreground and report the output: "
        "for i in {1..40}; do echo $i; sleep 1; done. do nothing else yourself.")
    if not wait_for(lab, "Agent(", limit=90):
        lab.stop()
        raise SetupFailed("no subagent was launched, so there is nothing to test")

    lab.send("q after the subagent")
    lab._pump(1.5)
    queued_now = texts(lab.screen())
    if not queued_now:
        lab.stop()
        raise SetupFailed("the message did not queue; the turn had already ended")

    # It must still be waiting while the subagent is working.
    t0, stayed = time.time(), True
    while time.time() - t0 < 25:
        lab._pump(1.0)
        s = lab.screen()
        if "after the subagent" not in " ".join(texts(s)):
            stayed = "Agent(" not in s or not BUSY.search(s)
            break
    still_running = bool(BUSY.search(lab.screen()))
    lab.stop()

    ok = stayed
    print(f"  H1  queued during a subagent  queued while the subagent ran="
          f"{bool(queued_now)}, still waiting after 25s={stayed}, "
          f"turn still going={still_running}")
    print(f"      -> {'PASS' if ok else 'FAIL, it was released mid-turn'}")
    return ok


def _clipboard_png(path):
    """Put a real PNG on the system clipboard. macOS only."""
    if sys.platform != "darwin":
        raise SetupFailed("clipboard image paste is only wired for macOS here")
    script = (f'set the clipboard to (read (POSIX file "{path}") '
              f'as «class PNGf»)')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise SetupFailed(f"could not put the image on the clipboard: {r.stderr.strip()}")


def h2_queued_image(binary):
    """A queued message carrying an image keeps the image.

    Anthropic's changelog has fixed image loss in queued messages twice, at
    2.1.72 and 2.1.105, so this is a real place for things to go wrong rather
    than a hypothetical.
    """
    png = LAB / "hd-tiny.png"
    if not png.exists():
        # a 1x1 PNG, written by hand so the test needs no assets
        png.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6360000002000100" "05fe02fe" "a7d5b3f0"
            "0000000049454e44ae426082"))
    _clipboard_png(png)

    lab, _ = start(binary, "image")
    lab.send(SLOW)
    if not wait_for(lab, "Bash(", limit=90):
        lab.stop()
        raise SetupFailed("the long turn never started")

    lab.type("q look at this ")
    lab._pump(0.5)
    lab.write(b"\x16")                 # ctrl+v
    lab._pump(2.0)
    pasted = lab.screen()
    has_image = bool(re.search(r"\[Image|\[image|Image #", pasted))
    if not has_image:
        lab.stop()
        raise SetupFailed(
            "ctrl+v did not attach an image, so this is testing the clipboard "
            "rather than the queue")

    lab.write(b"\r")
    lab._pump(2.5)
    screen = lab.screen()
    rows = texts(screen)
    kept = bool(re.search(r"\[Image|\[image|Image #", screen))
    alive = lab.alive()
    lab.stop()

    ok = len(rows) == 1 and "look at this" in rows[0] and kept and alive
    print(f"  H2  queued with an image      queued as {rows}, "
          f"image still attached={kept}")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def h3_submit_at_the_boundary(binary, rounds=8):
    """Fire the same submit at many offsets around the end of a turn.

    This cannot be aimed precisely from outside, so it is a statistical claim:
    across many attempts the message is always either queued or run, exactly
    once, and never lost or doubled.
    """
    lost, doubled, ran, queued = 0, 0, 0, 0
    for i in range(rounds):
        lab, ws = start(binary, f"race{i}", rows=40)
        lab.send("run this exact bash command in the foreground and wait for it "
                 "to finish. do not run it in the background, do not change it: "
                 f"for i in {{1..{4 + i}}}; do echo $i; sleep 1; done")
        # aim at the end of a turn whose length grows by a second each round,
        # so the submit lands at a different point in the turn every time
        t0 = time.time()
        while time.time() - t0 < 4 + i + 0.4:
            lab._pump(0.2)
        word = f"RACEWORD{i}"
        lab.send(f"q say {word} and nothing else")

        t1 = time.time()
        while time.time() - t1 < 90:
            lab._pump(1.0)
            if not BUSY.search(lab.screen()) and not texts(lab.screen()):
                break
        lab._pump(3.0)
        stream = lab.raw.decode("utf-8", "replace")

        # the transcript is the authority on how many times it was delivered
        seen = 0
        for f in PROJECTS.glob("*/*.jsonl"):
            try:
                body = f.read_text(errors="ignore")
            except OSError:
                continue
            if str(ws) not in body[:4000]:
                continue
            for line in body.splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "user" and not rec.get("isMeta"):
                    if word in json.dumps(rec.get("message", {}).get("content", "")):
                        seen += 1
        lab.stop()
        if seen == 0:
            lost += 1
        elif seen > 1:
            doubled += 1
        else:
            ran += 1
        queued += 1 if f"[waits] say {word}" in stream else 0

    ok = lost == 0 and doubled == 0
    print(f"  H3  submit near a boundary    {rounds} rounds at different offsets")
    print(f"      delivered exactly once={ran}, lost={lost}, duplicated={doubled}, "
          f"visibly queued first={queued}")
    print(f"      -> {'PASS' if ok else 'FAIL'}  (statistical, not deterministic)")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = _patched(args[0] if args else None)
    allow_drift = "--allow-setup-drift" in sys.argv
    print(f"  binary: {Path(binary).name}\n")

    results = {}
    for fn in (h1_subagent, h2_queued_image, h3_submit_at_the_boundary):
        try:
            results[fn.__name__] = fn(binary)
        except SetupFailed as e:
            print(f"  {fn.__name__}: SETUP DID NOT HOLD, not a product failure: {e}")
            results[fn.__name__] = None
        except Exception as e:
            print(f"  {fn.__name__}: ERRORED {type(e).__name__} {e}")
            results[fn.__name__] = False
        print()
    passed = sum(1 for v in results.values() if v is True)
    skipped = [k for k, v in results.items() if v is None]
    print(f"  {passed}/{len(results)} passed")
    if skipped:
        print(f"  setup never held for: {skipped}")
    return 0 if passed == len(results) or \
        (allow_drift and passed + len(skipped) == len(results)) else 1


if __name__ == "__main__":
    sys.exit(main())
