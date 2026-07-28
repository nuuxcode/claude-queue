#!/usr/bin/env python3
"""
Turn recorded runs into a table.

The claim this measures is not "Claude Code breaks". It does not. Sometimes it
handles an interruption beautifully. The claim is that you cannot tell in
advance which you are going to get, and that is measurable rather than
arguable.

Per run:

  drift     seconds from your message landing to Claude first touching the file
            that message asked for. Small means it dropped what it was doing.
  order     whether your two follow-ups ran in the order you typed them
  before README
            whether a follow-up file was started before README.md. The task
            asks for README.md last, but the model chooses the real write order,
            so this is a visible proxy rather than a proven turn boundary

Across runs: which files each run produced, because identical input producing
different output is the same problem wearing a different hat.

WHY THERE IS NO "HOW MANY TURNS" COLUMN

There was one. Do not add it back. Claude Code prints a banner when a turn ends
("Brewed for 1m 11s") and it looks like the perfect signal, but it scrolls out
of view within seconds. Two of the four runs behind the README show zero
banners for that reason, including one where three separate turns provably
happened. A detector that reports "0 turns" for a 3-turn run does not just fail
quietly, it accuses the working build of being broken. Everything measured here
has to survive scrolling.

    ./measure.py runs/stock.json runs/patched.json
"""

import json
import re
import statistics
import sys
from pathlib import Path

# The files the two follow-ups ask for, in the order they are typed.
WANTED = ("CHANGELOG.md", "metrics.py")

# The last file the original job writes on its own. A follow-up file appearing
# before this one means the new work was interleaved into the running job.
JOB1_LAST = "README.md"

TOUCH = re.compile(r"(?:Write|Update|Edit|Create)\((?P<f>[\w.\-/]+)")


def analyse(path):
    with open(path) as source:
        d = json.load(source)
    frames, stamps, marks = d["frames"], d["stamps"], d["marks"]

    first = {}
    for i, screen in enumerate(frames):
        for m in TOUCH.finditer(screen):
            first.setdefault(m.group("f"), stamps[i])

    sent = [stamps[i] for i in marks]
    job1_done = first.get(JOB1_LAST)

    rows, missing = [], []
    for k, name in enumerate(WANTED):
        if name not in first or k >= len(sent):
            missing.append(name)
            continue
        rows.append({"file": name, "typed": sent[k], "started": first[name],
                     "drift": first[name] - sent[k],
                     "jumped": (None if job1_done is None
                                else first[name] < job1_done)})

    order_ok = None
    if not missing and len(rows) == len(WANTED):
        order_ok = all(rows[i]["started"] < rows[i + 1]["started"]
                       for i in range(len(rows) - 1))

    return {"name": d.get("label") or Path(path).stem, "rows": rows,
            "order_ok": order_ok, "missing": missing,
            "readme_seen": job1_done is not None,
            "files": d.get("files") or sorted(first),
            "total": d.get("total", stamps[-1] if stamps else 0)}


def main():
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit(__doc__)
    results = [analyse(p) for p in paths]

    w = max(3, *(len(r["name"]) for r in results))
    print()
    print(f"{'run':<{w}} {'file':<14} {'typed':>7} {'started':>8} {'drift':>7}  "
          f"{'ran in typed order':<21} {'before README.md'}")
    print("-" * (w + 78))
    for r in results:
        order = ("yes" if r["order_ok"] else
                 "NO, it reordered you" if r["order_ok"] is False
                 else "INCOMPLETE")
        for j, row in enumerate(r["rows"]):
            before = ("YES" if row["jumped"] is True else
                      "no" if row["jumped"] is False else "? README missing")
            print(f"{r['name']:<{w}} {row['file']:<14} {row['typed']:6.0f}s "
                  f"{row['started']:7.0f}s {row['drift']:6.0f}s  "
                  f"{(order if j == 0 else ''):<21} "
                  f"{before}")
        if r["missing"]:
            print(f"{r['name']:<{w}} {'MISSING':<14} {'-':>7} {'-':>8} {'-':>7}  "
                  f"{'INCOMPLETE':<21} {', '.join(r['missing'])}")
        if not r["readme_seen"]:
            print(f"  {r['name']}: README.md was not observed, so the "
                  "before-README proxy is unknown")

    # Spread is only meaningful inside one build. A single spread quoted over a
    # patched run and an unpatched one together would be a made-up number.
    print("-" * (w + 78))
    for r in results:
        vals = [row["drift"] for row in r["rows"]]
        if len(vals) > 1:
            line = (f"  {r['name']}: drift {min(vals):.0f}s to {max(vals):.0f}s, "
                    f"median {statistics.median(vals):.0f}s")
            if len(vals) > 2:
                line += f", stdev {statistics.stdev(vals):.0f}s"
            print(line)

    if len(results) > 1:
        everything = sorted({f for r in results for f in r["files"]})
        varies = [f for f in everything
                  if not all(f in r["files"] for r in results)]
        if varies:
            print()
            print("  produced by some runs and not others, from identical input:")
            for f in varies:
                had = [r["name"] for r in results if f in r["files"]]
                print(f"    {f:<20} only in {', '.join(had)}")
    print()
    return 1 if any(r["missing"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
