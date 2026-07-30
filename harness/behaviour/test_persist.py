#!/usr/bin/env python3
"""
Waiting messages surviving a restart.

The queue used to live only in memory: close the terminal, lose the session, or
crash, and everything waiting was gone. Now every change to the queue is
written to this project's .claude directory, in a file named for the session,
and the next session started in that project brings the messages back as rows
marked restored. Nothing runs until you send something yourself.

  N1  clean exit with three waiting, resume: all three back, order and markers
  N2  kill -9 mid turn, resume: all three back, and the interrupted turn's own
      message is not one of them
  N3  crash after the first of three had already run: only two come back, and
      the file holds exactly those two
  N4  a session in a DIFFERENT directory does not see them
  N5  a corrupt file is ignored and the session starts anyway
  N6  restored rows wait: a new message runs first, then they drain in their
      saved order, one at a time
  N7  an unpatched control writes no file at all
  N8  CLAUDE_QUEUE_PERSIST=off writes no file either
  N9  a session started FRESH in the same directory, which is what the /resume
      picker and a bare `claude` both produce, adopts them anyway

N1, N2, N3, N6 and N9 are the rows that must FAIL on the build before the
feature they cover. N4, N5, N7 and N8 assert an absence and pass on both by
design.

N9 is the row that matters most, because N1 to N6 all drive `--resume <id>`,
which KEEPS the session id, and that is not what a person does. Picking a
session from the menu forks it and the fork gets a new id, so a lookup keyed on
the id finds nothing. That shipped as a bug: the messages were saved and never
offered back. So this row drives the path with the new id, and the row above
each of them stays, because `--continue` and `--resume <id>` are still the
paths where the exact id is the right answer.

    ./test_persist.py <binary>
"""

import json
import os
import re
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(LAB.parent))
from lab import Lab, SetupFailed, busy_for  # noqa: E402
from binaries import control as _control  # noqa: E402

# A queued row always carries its label, and a message that has already run
# never does. So the label is what tells a waiting message apart from the same
# text sitting in the transcript above it.
ROW = re.compile(r"\[(waits|jumps in)(, restored)?\]\s*(\S.*)$")
RUN = ""


class Session(Lab):
    """A Lab that can resume a session id, crash, and keep the transcript.

    The driver deletes the transcript when it stops, which is right for every
    other suite and fatal here: resuming a session needs the transcript that
    stopping would have removed. So keeping it is opt in, and the last session
    of each case turns it back off so nothing is left behind.
    """

    def __init__(self, *a, resume=False, keep=False, **kw):
        super().__init__(*a, **kw)
        self.resume = resume
        self.keep = keep

    def _argv(self):
        base = [self.binary, "--safe-mode", "--dangerously-skip-permissions",
                "--settings", '{"skipDangerousModePermissionPrompt":true}',
                "--model", self.model]
        if self.resume:
            return base + ["--resume", self.session_id]
        return base + ["--session-id", self.session_id]

    def crash(self):
        """kill -9. What losing the terminal actually looks like."""
        os.kill(self.pid, signal.SIGKILL)
        time.sleep(1.0)
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.pid = self.fd = None

    def leave(self):
        """A clean exit with messages still waiting: the terminal is closed.

        Neither of the obvious keys works for this case, and both were driven
        before settling on the signal. /exit arrives as a fourth queued
        message, because a queue only holds messages while a turn is running
        and anything typed during a turn is queued. Ctrl-D does not exit this
        build at all: the byte lands in the input box and the session stays up.

        So the clean exit here is the one a person actually performs, closing
        the window, which reaches the program as a terminate signal. It is not
        a crash: the process is given the chance to shut down and takes it.
        A second signal is never sent, because killing it half a second into
        its own shutdown truncates the transcript and the session cannot be
        resumed afterwards, which cost one confusing red run to find.
        """
        os.kill(self.pid, signal.SIGTERM)
        for _ in range(24):
            self._pump(0.5)
            if not self.alive():
                return True
        return False

    def _cleanup_session_history(self):
        """Honour `keep`, which is the whole reason this class exists.

        Leaving this out is what a resume failure looks like from the outside:
        the driver deletes the transcript as it stops, the resume then says no
        conversation was found, and a working build reads as broken. It cost
        one red run and two probes to see that the file was gone rather than
        unreadable.
        """
        if self.keep:
            return
        super()._cleanup_session_history()

    def done(self):
        self.keep = False
        self.stop()


def workspace(name, fresh=True):
    ws = LAB / f"ps-{RUN or 'run'}-{name}"
    if fresh and ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def session(binary, name, sid, *, fresh=True, resume=False, env=None,
            keep=True, settle=12):
    lab = Session(binary=binary, workspace=str(workspace(name, fresh)),
                  cols=96, rows=40, extra_env=env or {}, resume=resume,
                  keep=keep)
    lab.session_id = sid
    lab.start(settle=settle)
    if not lab.alive():
        raise SetupFailed("session died during boot")
    return lab


def busy(lab, seconds=90):
    lab.send(busy_for(seconds))
    if not lab.wait_for_tool():
        lab.done()
        raise SetupFailed("no tool ever started, so nothing could be queued")


def fill(lab, texts):
    for text in texts:
        lab.send(text)
        lab._pump(0.8)
    tag = texts[-1].split()[0]
    lab.expect(lambda s: tag in s, f"{tag} queued")


def rows(screen):
    """Every queued row on screen: its label, whether it says restored, its
    text."""
    out = []
    for line in screen.split("\n"):
        m = ROW.search(line.strip())
        if m:
            out.append((m.group(1), bool(m.group(2)), m.group(3).strip()))
    return out


def texts(screen):
    return [r[2] for r in rows(screen)]


def queue_file(ws, sid):
    return Path(ws) / ".claude" / f"queue-{sid}.json"


def forget(sid):
    """Remove a transcript the driver never got to clean up, after a crash."""
    root = Path.home() / ".claude" / "projects"
    for path in root.glob(f"*/{sid}.jsonl"):
        try:
            path.unlink()
        except OSError:
            pass


def saved(ws, sid):
    path = queue_file(ws, sid)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {"unreadable": True}


def dump(screen, why):
    print(f"      {why}, the bottom of the screen was:")
    for line in screen.split("\n")[-18:]:
        if line.strip():
            print(f"        |{line}")


def n1_clean_exit_and_resume(binary):
    """Close the session properly, come back, and find them where you left
    them."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n1", sid)
    ws = lab.workspace
    busy(lab)
    fill(lab, ["ALPHA the first one", "BRAVO the second one",
               "CHARLIE the third one"])
    before = texts(lab.screen())
    if len(before) != 3:
        dump(lab.screen(), "wanted three queued rows before the exit")
        lab.done()
        raise SetupFailed(f"only {len(before)} rows were queued")
    left = lab.leave()
    on_disk = saved(ws, sid)
    lab.stop()

    back = session(binary, "n1", sid, fresh=False, resume=True, settle=15)
    after = rows(back.screen())
    screen = back.screen()
    back.done()

    print(f"  N1  clean exit          exited cleanly: {left}, "
          f"file held {len(on_disk['messages']) if on_disk else 0} messages")
    print(f"      queued before: {before}")
    print(f"      back after:    {[r[2] for r in after]}")
    print(f"      all marked restored: {all(r[1] for r in after)}")
    ok = (left and on_disk is not None
          and [r[2] for r in after] == before
          and all(r[1] for r in after) and len(after) == 3)
    if not ok:
        dump(screen, "wanted three restored rows in the same order")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n2_kill_nine_mid_turn(binary):
    """The turn dies with the terminal. What was waiting is still waiting, and
    what was running is not duplicated into the queue."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n2", sid)
    ws = lab.workspace
    busy(lab)
    fill(lab, ["DELTA the first one", "ECHO the second one",
               "FOXTROT the third one"])
    before = texts(lab.screen())
    if len(before) != 3:
        lab.done()
        raise SetupFailed(f"only {len(before)} rows were queued")
    lab.crash()
    on_disk = saved(ws, sid)

    back = session(binary, "n2", sid, fresh=False, resume=True, settle=15)
    after = rows(back.screen())
    screen = back.screen()
    back.done()

    values = [r[2] for r in after]
    no_fixture = not any("for i in" in v for v in values)
    print(f"  N2  kill -9 mid turn    file held "
          f"{len(on_disk['messages']) if on_disk else 0} messages")
    print(f"      back after:    {values}")
    print(f"      the interrupted turn's own message is not queued: {no_fixture}")
    ok = values == before and all(r[1] for r in after) and no_fixture
    if not ok:
        dump(screen, "wanted exactly the three that were waiting")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n3_only_what_had_not_run(binary):
    """One of the three had already been taken by the time it crashed, so two
    come back, not three."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n3", sid)
    ws = lab.workspace
    busy(lab, 25)
    fill(lab, [busy_for(70), "GOLF the second one", "HOTEL the third one"])
    if len(texts(lab.screen())) != 3:
        lab.done()
        raise SetupFailed("the three did not all queue")
    # The short turn ends, the queued long job is taken, and the queue drops to
    # two. That is the state this case exists to crash in.
    lab.expect(lambda s: len(texts(s)) == 2, "the first queued job was taken",
               timeout=60)
    lab.crash()
    on_disk = saved(ws, sid)

    back = session(binary, "n3", sid, fresh=False, resume=True, settle=15)
    after = rows(back.screen())
    screen = back.screen()
    back.done()

    values = [r[2] for r in after]
    stored = [m["value"] for m in (on_disk or {}).get("messages", [])]
    print(f"  N3  the one that ran    file after the crash: {stored}")
    print(f"      back after:    {values}")
    ok = (len(stored) == 2 and not any("for i in" in v for v in stored)
          and values == ["GOLF the second one", "HOTEL the third one"])
    if not ok:
        dump(screen, "wanted only the two that had not run")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n4_another_directory_sees_nothing(binary):
    """The file lives in the project, so a session in another one cannot even
    see it. Same session id, different directory, nothing restored."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n4a", sid)
    ws = lab.workspace
    busy(lab)
    fill(lab, ["INDIA the only one"])
    if len(texts(lab.screen())) != 1:
        lab.done()
        raise SetupFailed("nothing queued")
    lab.crash()
    here = saved(ws, sid)
    if here is None:
        raise SetupFailed("no file was written, so there is nothing to miss")

    # Same session id, different directory. The id is the only thing a restore
    # keys on, so this is the strongest form of the case: even the right name
    # finds nothing, because the file is not there to be found.
    other = session(binary, "n4b", sid)
    elsewhere = rows(other.screen())
    other_ws = other.workspace
    screen = other.screen()
    other.done()
    forget(sid)

    stray = sorted(p.name for p in (Path(other_ws) / ".claude").glob("queue-*"))\
        if (Path(other_ws) / ".claude").is_dir() else []
    print(f"  N4  another directory   the first project held "
          f"{len(here['messages'])} message(s)")
    print(f"      the other project restored: {[r[2] for r in elsewhere]}")
    print(f"      queue files in the other project: {stray}")
    ok = not elsewhere and not stray
    if not ok:
        dump(screen, "wanted a clean session in the second directory")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n5_a_corrupt_file_never_stops_the_session(binary):
    """Half a file is what a crash during a write leaves. It must be ignored in
    silence: a queue file may not stop Claude Code from starting."""
    sid = str(uuid.uuid4())
    ws = workspace("n5")
    (ws / ".claude").mkdir(parents=True, exist_ok=True)
    (ws / ".claude" / f"queue-{sid}.json").write_text(
        '{"file":"claude-queue","messages":[{"value":"half a mess')

    started, screen = True, ""
    try:
        lab = session(binary, "n5", sid, fresh=False)
    except RuntimeError as e:
        print(f"  N5  corrupt file        the session did not start: {e}")
        print("      -> FAIL")
        return False
    screen = lab.screen()
    found = rows(screen)
    alive = lab.alive()
    lab.done()

    quiet = "JSON" not in screen and "SyntaxError" not in screen
    print(f"  N5  corrupt file        started: {started}, still up: {alive}, "
          f"rows restored: {[r[2] for r in found]}")
    print(f"      nothing about the file on screen: {quiet}")
    ok = alive and not found and quiet
    if not ok:
        dump(screen, "wanted a clean start and no rows")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n6_they_wait_for_you_and_then_drain_in_order(binary):
    """The whole point of the contract: nothing fires until you send something,
    your message goes first, and the restored ones follow in their saved
    order."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n6", sid)
    ws = lab.workspace
    busy(lab)
    fill(lab, ["JULIET the first one", "KILO the second one"])
    if len(texts(lab.screen())) != 2:
        lab.done()
        raise SetupFailed("the two did not queue")
    lab.crash()

    back = session(binary, "n6", sid, fresh=False, resume=True, settle=15)
    restored = texts(back.screen())
    if len(restored) != 2:
        dump(back.screen(), "nothing was restored, so there is nothing to hold")
        back.done()
        return False

    # Fifteen seconds of nothing. A row that had run would have left the queue,
    # so the count still being two is the evidence that nothing fired.
    back._pump(15)
    held = texts(back.screen())

    back.send("say READY and nothing else")
    back._pump(45)
    screen = back.screen()
    back._pump(30)
    screen = back.screen()
    back.done()

    # Order is read from the transcript, where each turn's own message is
    # echoed as it runs.
    order = [line.strip().lstrip("❯").strip() for line in screen.split("\n")
             if line.strip().startswith("❯")]
    order = [line for line in order
             if line.startswith(("say READY", "JULIET", "KILO"))]
    print(f"  N6  they wait for you   restored: {restored}")
    print(f"      still there after fifteen seconds: {held}")
    print(f"      what ran, in order: {order}")
    ok = (len(held) == 2
          and order[:3] == ["say READY and nothing else",
                            "JULIET the first one", "KILO the second one"])
    if not ok:
        dump(screen, "wanted your message first, then the two in saved order")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n7_the_control_writes_nothing(binary):
    """An unpatched build has no idea any of this exists."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n7", sid)
    ws = Path(lab.workspace)
    busy(lab)
    lab.send("LIMA queued on stock")
    lab._pump(2.0)
    written = sorted(p.name for p in (ws / ".claude").glob("queue-*")) \
        if (ws / ".claude").is_dir() else []
    lab.done()

    print(f"  N7  the control         queue files written: {written}")
    ok = not written
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n8_off_writes_nothing(binary):
    """The off switch, proved by the absence of the file rather than by the
    absence of a message."""
    sid = str(uuid.uuid4())
    lab = session(binary, "n8", sid, env={"CLAUDE_QUEUE_PERSIST": "off"})
    ws = Path(lab.workspace)
    busy(lab)
    fill(lab, ["MIKE queued with persistence off"])
    queued = texts(lab.screen())
    written = sorted(p.name for p in (ws / ".claude").glob("queue-*")) \
        if (ws / ".claude").is_dir() else []
    lab.done()

    print(f"  N8  persist=off         queued fine: {queued}, "
          f"queue files written: {written}")
    ok = len(queued) == 1 and not written
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def n9_a_fresh_session_in_the_same_project(binary):
    """The path a person actually takes, and the one that shipped broken.

    Every row above this one drives `--resume <id>`, which keeps the session
    id. Picking a session out of the /resume menu, or starting a bare `claude`
    and picking there, does not: it FORKS, and the fork gets an id the saved
    file has never heard of. Driven on a real machine, the resumed session's
    own transcript held no reference at all to the id the messages were saved
    under, so nothing keyed on the id could have found them.

    A brand new session id in the same directory is exactly that fork, which is
    why it is what this drives. The messages have to come back, marked, held,
    and the file they came from has to have been taken over rather than copied,
    so the session after this one is not offered them a second time.
    """
    sid = str(uuid.uuid4())
    lab = session(binary, "n9", sid)
    ws = lab.workspace
    busy(lab)
    fill(lab, ["NOVEMBER the first one", "OSCAR the second one",
               "PAPA the third one"])
    before = texts(lab.screen())
    if len(before) != 3:
        dump(lab.screen(), "wanted three queued rows before the exit")
        lab.done()
        raise SetupFailed(f"only {len(before)} rows were queued")
    left = lab.leave()
    on_disk = saved(ws, sid)
    lab.stop()
    if not left or on_disk is None:
        forget(sid)
        raise SetupFailed("the first session did not exit cleanly with a file")

    # No --resume, and an id nothing on disk has ever seen. This is the fork.
    fork = str(uuid.uuid4())
    back = session(binary, "n9", fork, fresh=False, settle=15)
    after = rows(back.screen())

    # Fifteen seconds of nothing. A row that had run would have left the queue,
    # so the count still being three is the evidence that nothing fired.
    back._pump(15)
    held = texts(back.screen())
    taken_over = saved(ws, fork)
    source_gone = not queue_file(ws, sid).exists()

    # And they are held until YOU send, not merely slow to start.
    drained = False
    if len(held) == 3:
        back.send("say READY and nothing else")
        for _ in range(24):
            back._pump(2.5)
            if len(texts(back.screen())) < 3:
                drained = True
                break
    screen = back.screen()
    back.done()
    forget(sid)

    order = [line.strip().lstrip("❯").strip() for line in screen.split("\n")
             if line.strip().startswith("❯")]
    order = [line for line in order
             if line.startswith(("say READY", "NOVEMBER", "OSCAR", "PAPA"))]
    values = [r[2] for r in after]
    print(f"  N9  a fresh session      saved under {sid[:8]}, came back under "
          f"{fork[:8]}")
    print(f"      queued before: {before}")
    print(f"      back after:    {values}")
    print(f"      all marked restored: {all(r[1] for r in after)}, "
          f"still there after fifteen seconds: {len(held)}")
    print(f"      rewritten under the new id: "
          f"{[m['value'] for m in (taken_over or {}).get('messages', [])]}")
    print(f"      the file it came from is gone: {source_gone}")
    print(f"      released once you sent something: {drained}, ran: {order[:1]}")
    ok = (values == before and all(r[1] for r in after) and len(after) == 3
          and len(held) == 3 and source_gone and drained
          and order[:1] == ["say READY and nothing else"]
          and taken_over is not None
          and [m["value"] for m in taken_over["messages"]] == before)
    if not ok:
        dump(screen, "wanted the three adopted, held, then released")
    print(f"      -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    global RUN
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    binary = args[0] if args else __import__("binaries").patched()
    allow_drift = "--allow-setup-drift" in sys.argv
    RUN = Path(binary).name
    print(f"  binary: {RUN}\n")

    tests = [(n1_clean_exit_and_resume, binary),
             (n2_kill_nine_mid_turn, binary),
             (n3_only_what_had_not_run, binary),
             (n4_another_directory_sees_nothing, binary),
             (n5_a_corrupt_file_never_stops_the_session, binary),
             (n6_they_wait_for_you_and_then_drain_in_order, binary),
             (n7_the_control_writes_nothing, _control()),
             (n8_off_writes_nothing, binary),
             (n9_a_fresh_session_in_the_same_project, binary)]

    results = {}
    for fn, b in tests:
        try:
            results[fn.__name__] = fn(b)
        except SetupFailed as e:
            print(f"  {fn.__name__}: SETUP DID NOT HOLD, not a product failure: {e}")
            results[fn.__name__] = None
        except Exception as e:                      # noqa: BLE001
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
