#!/usr/bin/env python3
"""
Record what Claude Code does when you type while it is already working.

This is the harness behind the numbers in the README. It is here so you do not
have to take those numbers on trust: point it at your own Claude Code, run it
twice, and read your own table.

WHAT IT DOES

Sends one job big enough to run for minutes (a small REST API across eight
files, with tests). While that job is running, it types two follow-ups. Each
follow-up asks for a file that does not exist yet, so "did it start this one"
is a fact on screen rather than an opinion.

    add a CHANGELOG.md listing every endpoint with its method and path
    add a metrics.py that counts how many times each endpoint was called

Note what those messages do NOT say. No "once the API is done". No "after
that". Ordering words are the workaround this patch replaces, and putting them
in makes stock Claude Code behave perfectly, which is why the first four
attempts at this demo proved nothing.

WHY IT REFUSES TO SAVE SOME RUNS

An earlier version sent the follow-ups on a fixed timer. The first job once
finished in 13 seconds, so the "interruptions" arrived when Claude was already
idle. There was nothing to interrupt and the recording was worthless, which was
not noticed until after it had been published.

So a follow-up is only sent while Claude is VERIFIABLY still working and the
first turn has not yet ended. If that cannot be arranged, the run is reported
INVALID and nothing is written.

WHAT IT COSTS

A few minutes of wall clock and a few minutes of tokens per run, on whichever
model you pass. It runs Claude with permissions skipped inside a scratch
directory it creates, because a demo that stops for a permission prompt is not
measuring anything. Read `lab.py`, it is 170 lines, before you run it.

    ./record.py --binary "$(which claude)" --label stock
    ./record.py --binary ~/.claude-patch/... --label patched
    ./measure.py runs/*.json
"""

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab import Lab  # noqa: E402

HERE = Path(__file__).resolve().parent
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
WORKSPACE_MARKER = ".claude-queue-harness-workspace"

TASK = (
    "build a small task-tracker REST API in this folder, no frameworks, standard "
    "library only. separate files: models.py with a Task model and validation, "
    "storage.py with an in-memory repository, api.py with a request router "
    "exposing list, get, create, update and delete, and errors.py with typed "
    "errors. then test_models.py, test_storage.py and test_api.py, each with "
    "several cases covering the happy path and the error cases. then a README.md "
    "documenting every endpoint with an example. write the files one at a time, "
    "run the full test suite at the end, fix anything that fails, and summarise "
    "what you built."
)
FOLLOWUPS = [
    "add a CHANGELOG.md listing every endpoint with its method and path",
    "add a metrics.py that counts how many times each endpoint was called",
]

# Claude Code prints a closing line when a turn ends. Seeing one means the
# first job is over, so anything sent afterwards is not an interruption.
# Only used live, while the line is still on screen. It is deliberately NOT
# used for measurement: these lines scroll out of view within seconds.
#
# Match the SHAPE, not the word. Claude Code picks a random verb every time and
# decorates the still-working spinner exactly like the finished banner:
#
#     ✶ Swooping… (11s · ↓ 912 tokens · thought for 1s)     still working
#     ✻ Brewed for 1m 11s                                   turn is over
#
# Two wrong versions of this line, both worth remembering. Listing the verbs
# also matched half the spinner words, because "Simmered" and "Simmering" share
# a stem. Matching "<word> for <number>" anywhere then matched the spinner's own
# "thought for 1s", and every run was declared invalid within seconds.
#
# So: anchored to the start of a line, and the verb has to be followed
# immediately by " for <number>". The spinner puts "…" there instead.
TURN_END = re.compile(r"^[^\w\n]{0,4}\s*\w+ for \d", re.MULTILINE)
BUSY = re.compile(r"\(\d+s\s*·|esc to interrupt")


def run_paths(label):
    if not LABEL.fullmatch(label):
        raise ValueError(
            "label must be 1 to 64 characters using letters, numbers, dot, "
            "underscore, or hyphen")
    root = HERE.resolve()
    runs = (root / "runs").resolve()
    workspace = (root / f"workspace-{label}").resolve()
    destination = (runs / f"{label}.json").resolve()
    if workspace.parent != root or destination.parent != runs:
        raise ValueError("label resolved outside the harness output directories")
    return runs, workspace, destination


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True, help="the claude executable to drive")
    ap.add_argument("--label", required=True, help="name for this run, e.g. stock")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    try:
        runs, ws, dest = run_paths(a.label)
    except ValueError as e:
        ap.error(str(e))
    runs.mkdir(exist_ok=True)
    if ws.exists():
        if not (ws / WORKSPACE_MARKER).is_file():
            ap.error(
                f"refusing to remove unmarked directory {ws}; move it yourself "
                "if it is disposable")
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    (ws / WORKSPACE_MARKER).write_text("created by harness/record.py\n")

    lab = Lab(binary=a.binary, workspace=str(ws), model=a.model, cols=96, rows=44)
    lab.start()
    lab.send(TASK)
    print(f"  {a.label}: job sent, waiting for it to get going")

    frames, stamps, marks = [], [], []
    seen, sent, invalid, quiet = None, 0, None, None
    t0 = time.time()

    while time.time() - t0 < a.timeout:
        lab._pump(0.15)
        screen = lab.screen()
        busy = bool(BUSY.search(screen))
        turns = len(TURN_END.findall(screen))
        done_steps = screen.count("⎿")          # completed tool calls on screen
        now = time.time() - t0

        if sent < len(FOLLOWUPS) and turns > 0:
            saw = next((ln for ln in screen.split("\n") if TURN_END.search(ln)), "")
            invalid = (f"the first job ended after {now:.0f}s, before follow-up "
                       f"{sent + 1} could be sent\n  the line that said so: "
                       f"{saw.strip()!r}")
            break
        if sent == 0 and busy and done_steps >= 2:
            lab.send(FOLLOWUPS[0])
            marks.append(len(frames))
            sent = 1
            print(f"  [{now:5.1f}s] follow-up 1 landed mid-flight "
                  f"({done_steps} steps done, no turn ended)")
        elif sent == 1 and busy and done_steps >= 5 and now > 40:
            lab.send(FOLLOWUPS[1])
            marks.append(len(frames))
            sent = 2
            print(f"  [{now:5.1f}s] follow-up 2 landed mid-flight "
                  f"({done_steps} steps done, no turn ended)")

        if screen and screen != seen:
            seen = screen
            frames.append(screen)
            stamps.append(time.time() - t0)
            quiet = None
        elif sent == len(FOLLOWUPS) and not busy:
            quiet = quiet or time.time()
            if time.time() - quiet > 15:
                break
    lab.stop()

    if invalid:
        print(f"\n  INVALID RUN: {invalid}")
        print("  Nothing saved. Give the first job more to do and run it again.")
        return 1
    if sent < len(FOLLOWUPS):
        print(f"\n  INVALID RUN: only {sent} of {len(FOLLOWUPS)} follow-ups were sent")
        print("  Nothing saved.")
        return 1

    total = time.time() - t0
    files = sorted(p.name for p in ws.iterdir()
                   if p.is_file() and p.name != WORKSPACE_MARKER)
    with dest.open("w") as fh:
        json.dump({"label": a.label, "binary": a.binary, "model": a.model,
                   "frames": frames, "stamps": stamps, "marks": marks,
                   "total": total, "files": files, "followups": FOLLOWUPS}, fh)

    print(f"\n  {a.label}: {len(frames)} screens over {total:.0f}s, "
          f"both follow-ups landed mid-flight")
    print(f"  files produced: {', '.join(files) if files else 'none'}")
    print(f"  saved {dest}")
    print(f"\n  now run:  ./measure.py {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
