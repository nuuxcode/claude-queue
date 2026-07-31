#!/usr/bin/env python3
"""Is the session free while it waits for a BACKGROUND AGENT?

Two different things get confused here, so both are driven:

  T1  a message TYPED during "Waiting for N background agents to finish"
  T2  a message already QUEUED when the turn ends, with an agent still alive

T2 is the one that was actually reported. T1 alone cannot answer it, because a
typed message on an idle prompt bypasses the queue entirely.

The background agent is kept alive with the same bash loop the harness uses
for the main thread, so it lives a known ~100 seconds. The first attempt used
`sleep 100` as a single command and the subagent refused it as wasteful, which
closed the window to 6 seconds and made the result unreadable.

Every event is timestamped from the session start, so "it ran while the agent
was alive" is a measurement, not an impression.
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelab import FreeLab  # noqa: E402
from paths import WORKSPACE, patched_binary, scratch, stock_binary  # noqa: E402

PATCHED = patched_binary()
STOCK = stock_binary()
WS = WORKSPACE
LOG = scratch("bgagent2-evidence.txt")

LOOP = "for i in {1..100}; do echo $i; sleep 1; done"
LAUNCH = (
    "Use the Agent tool exactly once, with subagent_type \"general-purpose\", "
    "run_in_background true, and this prompt: \"Run this exact bash command in "
    "the foreground and wait for it to finish. Do not change it, do not "
    "background it, do not shorten it. It is a timing fixture and it is "
    "supposed to take 100 seconds: " + LOOP + " . Then reply DONE.\" "
    "Do not call any other tool and do not wait for the agent. As soon as the "
    "Agent tool returns, reply with the single word LAUNCHED and end your turn.")
SHORT_BUSY = ("run this exact bash command in the foreground and wait for it to "
              "finish. do not run it in the background, do not change it: "
              "for i in {1..25}; do echo $i; sleep 1; done")

lines = []


def say(s=""):
    print(s)
    lines.append(s)


def dump(lab, title):
    say(f"    --- screen: {title} ---")
    for ln in lab.screen().splitlines():
        if ln.strip():
            say("    | " + ln.rstrip())
    say("    --- end ---")


def clean():
    for f in glob.glob(os.path.join(WS, ".claude", "queue-*.json")):
        os.remove(f)


def agent_alive(s):
    return "background agent" in s.lower() and "waiting" in s.lower()


def turn_running(s):
    return "esc to interrupt" in s


def qrows(lab):
    return [ln.strip() for ln in lab.screen().splitlines()
            if "[waits" in ln or "[jumps in" in ln or "[paused" in ln]


def answered(lab, word, prompt_text):
    for ln in lab.screen().splitlines():
        if word not in ln:
            continue
        if prompt_text in ln:
            continue
        if any(t in ln for t in ("[waits", "[jumps in", "[paused")):
            continue
        if ln.strip().startswith("❯"):
            continue
        return True
    return False


def wait_until(lab, pred, limit, step=2):
    end = time.time() + limit
    while time.time() < end:
        lab._pump(step)
        if pred(lab.screen()):
            return True
    return False


# ---------------------------------------------------------------- T1
def t1(binary, label):
    clean()
    say(f"\n---- T1  typed during the wait, {label} ----")
    lab = FreeLab(workspace=WS, binary=binary, model="haiku", cols=100, rows=44)
    lab.start()
    r = {}
    try:
        t0 = time.time()
        lab.send(LAUNCH, label="launch")
        ok = wait_until(lab, lambda s: not turn_running(s) and agent_alive(s), 120)
        r["reached_wait_state"] = ok
        r["t_wait_state"] = round(time.time() - t0, 1)
        if not ok:
            dump(lab, "never reached the wait state")
            return r
        say(f"    t={r['t_wait_state']}s  agent alive, main turn over")
        lab.send("say PINEAPPLE and nothing else", label="probe")
        r["t_typed"] = round(time.time() - t0, 1)
        got = False
        for _ in range(30):
            lab._pump(2)
            if answered(lab, "PINEAPPLE", "say PINEAPPLE"):
                got = True
                break
        r["ran"] = got
        r["t_answer"] = round(time.time() - t0, 1)
        r["agent_still_alive_at_answer"] = agent_alive(lab.screen())
        r["queued_instead"] = any("PINEAPPLE" in x for x in qrows(lab))
        say(f"    t={r['t_typed']}s  typed   t={r['t_answer']}s  answered={got}"
            f"  agent still alive={r['agent_still_alive_at_answer']}")
        dump(lab, "T1 result")
    finally:
        lab.stop()
        clean()
    return r


# ---------------------------------------------------------------- T2
def t2(binary, label):
    clean()
    say(f"\n---- T2  QUEUED before the turn ended, {label} ----")
    lab = FreeLab(workspace=WS, binary=binary, model="haiku", cols=100, rows=44)
    lab.start()
    r = {}
    try:
        t0 = time.time()
        lab.send(LAUNCH, label="launch agent")
        ok = wait_until(lab, lambda s: not turn_running(s) and agent_alive(s), 120)
        r["agent_up"] = ok
        if not ok:
            dump(lab, "agent never came up")
            return r
        say(f"    t={round(time.time()-t0,1)}s  agent up")

        # a 25s main turn, so the agent outlives it by ~70s
        lab.send(SHORT_BUSY, label="short busy")
        wait_until(lab, turn_running, 20, step=1)
        time.sleep(2)
        lab.send("q say KIWI and nothing else", label="queued while busy")
        lab._pump(2)
        r["queued_ok"] = any("KIWI" in x for x in qrows(lab)) or "KIWI" in lab.screen()
        say(f"    t={round(time.time()-t0,1)}s  queued: {qrows(lab)}")

        # watch the moment the main turn ends
        t_turn_end = None
        t_kiwi = None
        t_agent_gone = None
        for _ in range(90):
            lab._pump(2)
            s = lab.screen()
            now = round(time.time() - t0, 1)
            if t_turn_end is None and not turn_running(s) and "KIWI" not in \
                    "".join(x for x in s.splitlines() if "esc to interrupt" in x):
                if not turn_running(s):
                    t_turn_end = now
                    r["agent_alive_at_turn_end"] = agent_alive(s)
                    r["queued_at_turn_end"] = qrows(lab)
                    say(f"    t={now}s  main turn ended. agent alive="
                        f"{r['agent_alive_at_turn_end']}  queue={qrows(lab)}")
            if t_agent_gone is None and t_turn_end is not None and \
                    not agent_alive(s):
                t_agent_gone = now
            if t_kiwi is None and answered(lab, "KIWI", "say KIWI"):
                t_kiwi = now
                say(f"    t={now}s  KIWI ANSWERED. agent alive="
                    f"{agent_alive(s)}")
            if t_kiwi is not None and t_agent_gone is not None:
                break
        r["t_turn_end"] = t_turn_end
        r["t_kiwi"] = t_kiwi
        r["t_agent_gone"] = t_agent_gone
        r["drained_while_agent_alive"] = bool(
            t_kiwi is not None and t_agent_gone is not None
            and t_kiwi < t_agent_gone)
        dump(lab, "T2 result")
    finally:
        lab.stop()
        clean()
    return r



res = {}
for binary, label in ((PATCHED, "PATCHED"), (STOCK, "STOCK")):
    for name, fn in (("T1", t1), ("T2", t2)):
        try:
            res[f"{label} {name}"] = fn(binary, label)
        except Exception as e:                                # noqa: BLE001
            say(f"    ERROR {label} {name}: {type(e).__name__}: {e}")
            res[f"{label} {name}"] = {"error": str(e)}

say("\n\n================ VERDICT ================")
for k, v in res.items():
    say(f"\n{k}")
    for kk, vv in v.items():
        say(f"    {kk:32} {vv}")

with open(LOG, "w") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nevidence: {LOG}")
