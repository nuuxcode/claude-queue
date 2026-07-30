#!/usr/bin/env python3
"""One session's queue must never appear in another session.

This is Mounssif's three-terminal reproduction: session one parks a message, a
brand new session comes up, and it should see nothing at all. Then that new
session parks its own, a third starts, and it should see nothing either.

It also checks the case the isolation costs us, resuming the SAME id, which
must still get its own messages back.
"""
import glob
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.expanduser("~/Developer/_claude-lab"))
from lab import Lab  # noqa: E402

LIVE = "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
WS = os.path.expanduser("~/Developer/_claude-lab/workspace")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def qrows(lab):
    return [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]


def clean():
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)


def session(sid):
    lab = Lab(binary=LIVE, model="haiku", cols=100, rows=44)
    lab.session_id = sid
    return lab


clean()
ID1, ID2, ID3 = (str(uuid.uuid4()) for _ in range(3))

# --- session 1 parks a message -----------------------------------------
lab = session(ID1)
lab.start()
try:
    lab.send("p this prompt is in session 1", label="s1")
    lab._pump(6)
    check("1. session one parked its message",
          any("[paused]" in r and "session 1" in r for r in qrows(lab)),
          str(qrows(lab)))
finally:
    lab.stop()

time.sleep(2)

# --- a brand new session must see NOTHING -------------------------------
lab = session(ID2)
lab.start()
try:
    lab._pump(8)
    rows = qrows(lab)
    check("2. a NEW session sees no other session's queue", not rows, str(rows))
    lab.send("p this prompt is for session 2", label="s2")
    lab._pump(6)
    rows = qrows(lab)
    check("3. and it only holds its own",
          len(rows) == 1 and "session 2" in rows[0], str(rows))
finally:
    lab.stop()

time.sleep(2)

# --- a third new session must also see NOTHING --------------------------
lab = session(ID3)
lab.start()
try:
    lab._pump(8)
    rows = qrows(lab)
    check("4. a THIRD session still sees nothing, no accumulation",
          not rows, str(rows))
finally:
    lab.stop()

time.sleep(2)

# --- resuming the SAME id still gets its own queue back -----------------
lab = session(ID1)
lab.start()
try:
    lab._pump(8)
    rows = qrows(lab)
    check("5. resuming the same id gets its OWN messages back",
          any("session 1" in r for r in rows)
          and not any("session 2" in r for r in rows), str(rows))
finally:
    lab.stop()

files = sorted(os.path.basename(f) for f in
               glob.glob(os.path.join(WS, ".claude", "queue-*.json")))
print("\n  queue files on disk:", len(files))
for f in files:
    print("   ", f)
check("6. each session kept its own file, none re-keyed",
      len(files) == 2, str(files))

clean()
print("\n" + ("FAILED: " + "; ".join(fails) if fails else "SESSIONS ARE ISOLATED"))
sys.exit(1 if fails else 0)
