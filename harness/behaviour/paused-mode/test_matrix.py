#!/usr/bin/env python3
"""Every edge case for paused mode, driven on a real terminal.

Three sessions so the states are honest rather than simulated:
  A  an IDLE session, which is where the first version broke
  B  a BUSY session, plus the queue editing keys against a paused row
  C  a restart, to prove a paused message comes back paused
"""
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary  # noqa: E402
from lab import Lab, busy_for  # noqa: E402

LIVE = patched_binary()
WS = WORKSPACE
RIGHT, LEFT, BKSP = b"\x1b[C", b"\x1b[D", b"\x7f"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def qrows(lab):
    return [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]


def phantom(lab, raw=None):
    """A working indicator, or the raw line echoed, with nothing running.

    The screen legitimately contains an ellipsis in truncated hints, so the
    test is the shape of the indicator itself: a single glyph, a verb, then
    the ellipsis, on a short line of its own.
    """
    s = lab.screen()
    if "esc to interrupt" in s:
        return False
    for ln in s.splitlines():
        st = ln.strip()
        if len(st) < 44 and re.match(r"^\S\s+[A-Za-z][A-Za-z']*\u2026", st):
            return "spinner:" + st
    if raw and any(st.strip() == "\u276f " + raw for st in s.splitlines()):
        return "echo:" + raw
    return False


def clear_saved_queue():
    d = os.path.join(WS, ".claude")
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith("queue-") and f.endswith(".json"):
                os.remove(os.path.join(d, f))


def wait_idle(lab, limit=200):
    end = time.time() + limit
    while time.time() < end:
        lab._pump(3)
        if "esc to interrupt" not in lab.screen():
            return True
    return False


# =====================================================================  A
clear_saved_queue()
print("\n=== A: idle session ===")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send("p alo", label="p idle")
    lab._pump(6)
    rows = qrows(lab)
    check("A1. p while idle is queued as [paused]",
          any("[paused]" in r and "alo" in r for r in rows), str(rows))
    ph = phantom(lab, "p alo")
    check("A2. no stuck spinner or echo after it", not ph, str(ph))
    lab._pump(10)
    check("A3. it still has not run 16s later",
          any("[paused]" in r for r in qrows(lab)))

    # a word that merely starts with p must stay literal
    lab.send("print the word MANGO and nothing else", label="print")
    ok = wait_idle(lab)
    s = lab.screen()
    check("A4. 'print ...' is NOT treated as a marker",
          "MANGO" in s and not any("print" in r for r in qrows(lab)))

    # bare p with no text is ordinary text
    lab.send("p", label="bare p")
    lab._pump(6)
    check("A5. a bare 'p' is not a marker",
          not any(r.strip().endswith("[paused]") for r in qrows(lab)))
    wait_idle(lab)

    # mixed batch while idle: the runnable one runs, the paused one waits
    lab.type("q: say KIWI and nothing else\np: say LATER and nothing else")
    lab.write(b"\r")
    lab._pump(4)
    wait_idle(lab)
    s = lab.screen()
    check("A6. mixed batch: the runnable line ran", "KIWI" in s)
    check("A7. mixed batch: the paused line is still queued",
          any("[paused]" in r and "LATER" in r for r in qrows(lab)))
finally:
    lab.stop()

# =====================================================================  B
clear_saved_queue()
print("\n=== B: busy session, and the editing keys ===")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send(busy_for(30), label="busy")
    time.sleep(2)
    lab.send("also say ALPHA", label="default")
    lab.send("s also say BETA", label="s")
    lab.send("p say GAMMA and nothing else", label="p")
    lab._pump(2)
    rows = qrows(lab)
    print("   queued:", rows)
    check("B1. default still waits",
          any("[waits]" in r and "ALPHA" in r for r in rows))
    check("B2. s still jumps in",
          any("[jumps in]" in r and "BETA" in r for r in rows))
    check("B3. p is paused while busy",
          any("[paused]" in r and "GAMMA" in r for r in rows))

    # cycle GAMMA while the turn is still running
    lab.key("up")
    lab._pump(0.8)
    # Four modes since 2.4.0: waits, jumps in, waits for the background,
    # paused. The cycle is one loop, so four presses visit all four.
    seen = []
    for _ in range(4):
        lab.write(RIGHT)
        lab._pump(0.8)
        seen.append(next((t for t in ("[paused]", "[waits for", "[waits]",
                                      "[jumps in]")
                          for r in qrows(lab) if t in r and "GAMMA" in r), None))
    check("B4. cycling works while busy too",
          len(set(seen)) == 4 and all(seen), str(seen))

    # put it back to paused, then reorder and delete against it
    for _ in range(4):
        if any("[paused]" in r and "GAMMA" in r for r in qrows(lab)):
            break
        lab.write(RIGHT)
        lab._pump(0.8)
    check("B5. can return it to paused",
          any("[paused]" in r and "GAMMA" in r for r in qrows(lab)))

    lab.write(BKSP)
    lab._pump(1.0)
    check("B6. delete removes a paused row",
          not any("GAMMA" in r for r in qrows(lab)), str(qrows(lab)))

    for _ in range(4):
        lab.key("down")
        lab._pump(0.4)
    ok = wait_idle(lab, 220)
    check("B7. the turn finished and the queue drained",
          ok and not qrows(lab), str(qrows(lab)))
finally:
    lab.stop()

# =====================================================================  C
clear_saved_queue()
print("\n=== C: a paused message survives a restart ===")
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send("p say DELTA and nothing else", label="p")
    lab._pump(6)
    check("C1. queued paused before restart",
          any("[paused]" in r and "DELTA" in r for r in qrows(lab)))
finally:
    lab.stop()

time.sleep(2)
# The same session resumed by id. A brand new session must NOT see this queue,
# which is what test_isolation.py pins.
lab2 = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab2.session_id = lab.session_id
lab2.start()
try:
    lab2._pump(8)
    rows = qrows(lab2)
    print("   after restart:", rows)
    check("C2. it comes back, and comes back PAUSED",
          any("[paused" in r and "DELTA" in r for r in rows), str(rows))
    check("C3. nothing ran on its own", "DELTA" not in
          "".join(l for l in lab2.screen().splitlines()
                  if "[paused" not in l and "❯" not in l))
finally:
    lab2.stop()

# =====================================================================  D
clear_saved_queue()
print("\n=== D: a held queue must not claim to be busy ===")


def indicator(lab):
    for ln in lab.screen().splitlines():
        st = ln.strip()
        if len(st) < 44 and re.match(r"^\S\s+[A-Za-z][A-Za-z']*\u2026", st):
            return st
    return None


lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send("p say ZEBRA and nothing else", label="park while idle")
    lab._pump(6)
    lab.key("up")
    lab._pump(1.0)
    lab.write(RIGHT)          # paused -> waits, still pointing at it
    lab._pump(2.0)
    check("D1. the arrow moved it to [waits]",
          any("[waits]" in r for r in qrows(lab)), str(qrows(lab)))
    lab._pump(12)
    ind = indicator(lab)
    check("D2. no working indicator while it cannot drain", ind is None, str(ind))
    check("D3. and it has not run", any("[waits]" in r for r in qrows(lab)))
    for _ in range(3):
        lab.key("down")
        lab._pump(0.5)
    ran = False
    for _ in range(20):
        lab._pump(3)
        if "ZEBRA" in lab.screen() and not qrows(lab):
            ran = True
            break
    check("D4. stepping off releases it and it runs", ran)
finally:
    lab.stop()

# =====================================================================  E
clear_saved_queue()
print("\n=== E: reading is free, changing holds, ctrl+enter releases ===")
CTRL_ENTER = b"\x1b[13;5u"
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    # reading the queue must NOT stop it draining
    lab.send(busy_for(22), label="busy")
    time.sleep(2)
    lab.send("q say ALPHA and nothing else", label="q1")
    lab.send("q say BETA and nothing else", label="q2")
    lab._pump(2)
    lab.key("up")          # read only, change nothing
    lab._pump(1.0)
    drained = False
    for _ in range(60):
        lab._pump(3)
        if not qrows(lab):
            drained = True
            break
    check("E1. reading the queue does not stop it draining", drained,
          str(qrows(lab)))
finally:
    lab.stop()

clear_saved_queue()
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.start()
try:
    lab.send("p say ZEBRA and nothing else", label="park")
    lab._pump(6)
    lab.key("up")
    lab._pump(1.0)
    lab.write(RIGHT)       # paused -> waits, this holds the queue
    lab._pump(2.0)
    check("E2. the arrow moved it to [waits]",
          any("[waits]" in r for r in qrows(lab)), str(qrows(lab)))
    lab._pump(10)
    check("E3. changing a mode holds it", any("[waits]" in r for r in qrows(lab)))
    lab.write(CTRL_ENTER)
    ran = False
    for _ in range(20):
        lab._pump(3)
        if "ZEBRA" in lab.screen() and not qrows(lab):
            ran = True
            break
    check("E4. ctrl+enter releases it and it runs", ran, str(qrows(lab)))
finally:
    lab.stop()

# =====================================================================  F
clear_saved_queue()
print("\n=== F: a RESTORED message, cycled, then released ===")
CTRL_ENTER = b"\x1b[13;5u"
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
_sid = lab.session_id
lab.start()
try:
    lab.send("p say OMEGA and nothing else", label="park")
    lab._pump(6)
finally:
    lab.stop()

time.sleep(2)
lab = Lab(workspace=WS, binary=LIVE, model="haiku", cols=100, rows=44)
lab.session_id = _sid          # resumed by id, not a new session
lab.start()
try:
    lab._pump(8)
    check("F1. it came back restored and paused",
          any("[paused, restored]" in r for r in qrows(lab)), str(qrows(lab)))
    lab.key("up")
    lab._pump(1.0)
    lab.write(RIGHT)
    lab._pump(2.0)
    check("F2. the arrow moved it to waits",
          any("[waits" in r for r in qrows(lab)), str(qrows(lab)))
    lab._pump(8)
    check("F3. still held, nothing ran on its own",
          any("[waits" in r for r in qrows(lab)))
    lab.write(CTRL_ENTER)
    ran = False
    for _ in range(20):
        lab._pump(3)
        if "OMEGA" in lab.screen() and not qrows(lab):
            ran = True
            break
    check("F4. ctrl+enter releases a RESTORED message and it runs",
          ran, str(qrows(lab)))
finally:
    lab.stop()

clear_saved_queue()
print("\n" + ("FAILED: " + "; ".join(fails) if fails else "ALL EDGE CASES PASSED"))
sys.exit(1 if fails else 0)
