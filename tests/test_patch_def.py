import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import patch_def  # noqa: E402


class FakeMatch:
    values = {"mode": "mode", "val": "value", "raw": "raw"}

    def group(self, name=0):
        if name == 0:
            return "globalThis.RESULT={value,raw,priority:__qsp,split:__qsx};"
        return self.values[name]


class Groups:
    def __init__(self, whole, **values):
        self.whole = whole
        self.values = values

    def group(self, name=0):
        return self.whole if name == 0 else self.values[name]


def resolve(text, *, pasted=None, invert=None):
    code = patch_def._resolve(FakeMatch())
    script = "\n".join([
        f"let value={json.dumps(text)},raw=value,mode='prompt';",
        f"globalThis.__qsPastes={json.dumps(pasted)};",
        f"globalThis.__qsInvert={json.dumps(invert)};",
        code,
        "console.log(JSON.stringify(globalThis.RESULT));",
    ])
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


# The shapes the name finders read, minus the twenty megabytes around them.
QUEUE_SHAPES = (
    "p=x.popEditableAt;g=q.getCommandQueue,"
    "x.getCommandQueue().some(e)}"
    "function n(){z=Object.freeze([...arr]),ee.emit()}"
    "function sid(){return ctx()?.sessionId??State.sessionId}"
    "function mine(c){return c.agentId===Agent()}"
)


def edit_roundtrip(queue):
    remember_match = Groups(
        "let i=state.getState().queueEditIndex;"
        "if(i===null)return!1;let r=pop(i,t,c);",
        i="i", ht="state", r="r", pop="pop", args="t,c",
    )
    queue_shapes = QUEUE_SHAPES
    remember = patch_def.Edit(
        "test slot translation", None, patch_def._remember_slot,
    ).replacement(remember_match, queue_shapes)
    # `guard` and `spread` are carried through from the match rather than
    # written by the builder, because 2.1.223 added a validity check before the
    # push and changed the spread to `{...normalise(cmd)}`. The empty guard and
    # the plain spread here are the pre-2.1.223 shape, which must still work.
    enqueue = patch_def._enqueue_at_slot(Groups(
        "", fn="enqueue", a="a", arr="arr", tail="notify()}",
        guard="", spread="...a",
    ))
    script = "\n".join([
        f"let arr={json.dumps(queue)};",
        "function g(){return arr}",
        "function e(item){return item.mode==='prompt'"
        "&&item.origin==='human'&&!item.isMeta}",
        "function pop(i){let item=g().filter(e)[i];"
        "let at=arr.indexOf(item);"
        "return at<0?undefined:arr.splice(at,1)[0]}",
        "let state={getState:()=>({queueEditIndex:1})},t=null,c=null;",
        "function notify(){}",
        f"function take(){{{remember}return r}}",
        enqueue,
        "take();",
        "enqueue({value:'bravo edited',mode:'prompt',"
        "origin:'human',priority:'later'});",
        "console.log(JSON.stringify(arr.map(item=>item.value)));",
    ])
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fold(text, *, highlighted=False, columns=96, collapse=None):
    """Run the drawn-row folder over one message and report what it drew.

    The arithmetic is the part of this feature that a behaviour suite cannot
    afford to cover: every shape it has to get right would be another paid
    session. So the shapes are driven here, and the suite spends its sessions
    proving the folded row reaches the screen at all.
    """
    code = patch_def._fold_fn(Groups(""))
    script = "\n".join([
        f"Object.defineProperty(process.stdout,'columns',"
        f"{{value:{columns},configurable:true}});",
        "delete process.env.COLUMNS;",
        "" if collapse is None
        else f"process.env.CLAUDE_QUEUE_COLLAPSE={json.dumps(collapse)};",
        code,
        f"let before={{uuid:'u1',message:{{role:'user',"
        f"content:[{{type:'text',text:{json.dumps(text)}}}]}}}};",
        f"let after=__qsFold(before,{json.dumps(highlighted)});",
        "console.log(JSON.stringify({text:after.message.content[0].text,"
        "uuid:after.uuid,same:after===before}));",
    ])
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def persist_scope(*, session="S1", queue=(), persist=None, adopt=None):
    """The saving code with just enough of the queue module around it.

    The real scope is a closure holding the array, the frozen snapshot and the
    emitter. This rebuilds those three by hand so the file format, the atomic
    write and the restore can be driven deterministically, which is the part a
    paid session cannot afford to cover case by case.
    """
    code = patch_def.Edit(
        "test persistence", None, patch_def._persist,
    ).replacement(
        Groups("", fn="notify", snap="snapshot", arr="arr", em="events"),
        QUEUE_SHAPES,
    )
    return "\n".join([
        "" if persist is None
        else f"process.env.CLAUDE_QUEUE_PERSIST={json.dumps(persist)};",
        "" if adopt is None
        else f"process.env.CLAUDE_QUEUE_ADOPT={json.dumps(adopt)};",
        f"let arr={json.dumps(list(queue))};",
        "let snapshot=Object.freeze([]);",
        "let events={emit(){}};",
        f"let State={{sessionId:{json.dumps(session)}}};",
        "function Agent(){return 'agent-of-'+State.sessionId}",
        "function e(c){return c.mode!=='task-notification'&&!c.isMeta"
        "&&(c.origin===undefined||c.origin.kind==='human')}",
        "function dir(){try{return require('fs').readdirSync('.claude').sort()}"
        "catch(x){return[]}}",
        "function saved(id){try{return JSON.parse(require('fs').readFileSync("
        "'.claude/queue-'+(id||State.sessionId)+'.json','utf8'))}"
        "catch(x){return null}}",
        "function row(v,p,extra){return Object.assign({agentId:Agent(),"
        "mode:'prompt',value:v,priority:p||'later'},extra||{})}",
        code,
    ])


def run_persist(body, *, workdir, **kw):
    script = "\n".join([
        f"process.chdir({json.dumps(str(workdir))});",
        persist_scope(**kw),
        body,
    ])
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class PersistenceTests(unittest.TestCase):
    """What survives a restart, and what a broken file is allowed to do."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="qs-persist-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def file_for(self, session="S1"):
        return self.work / ".claude" / f"queue-{session}.json"

    def save(self, *, session="S1", persist=None, rows=(
            ("alpha", "later"), ("bravo", "next"), ("charlie", "later"))):
        pushes = ",".join(
            f"row({json.dumps(v)},{json.dumps(p)})" for v, p in rows)
        body = "\n".join([
            "globalThis.__qsRestore();",
            f"arr.push({pushes});" if pushes else "",
            "notify();",
            "console.log(JSON.stringify({dir:dir(),file:saved()}));",
        ])
        return run_persist(body, workdir=self.work, session=session,
                           persist=persist)

    def restore(self, *, session="S1", persist=None, workdir=None, adopt=None):
        body = "\n".join([
            "let ok=globalThis.__qsRestore();",
            "console.log(JSON.stringify({ok:ok,"
            "hold:globalThis.__qsHold===true,rows:arr,dir:dir()}));",
        ])
        return run_persist(body, workdir=workdir or self.work, session=session,
                           persist=persist, adopt=adopt)

    def plant(self, name, values, *, age=0):
        """A queue file this session did not write, optionally an older one.

        Age is what the fallback sorts on, so it has to be settable: two files
        written in the same millisecond would otherwise make the newest-wins
        case decide itself by directory order.
        """
        path = self.work / ".claude" / f"queue-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "file": "claude-queue: the messages this session still has waiting",
            "session": name, "saved": "2026-01-01T00:00:00.000Z",
            "messages": [{"value": v, "priority": "later", "restored": False}
                         for v in values]}))
        if age:
            when = time.time() - age
            os.utime(path, (when, when))
        return path

    def test_a_saved_queue_comes_back_in_order_and_marked(self):
        self.save()
        got = self.restore()
        self.assertTrue(got["ok"])
        self.assertTrue(got["hold"])
        self.assertEqual([r["value"] for r in got["rows"]],
                         ["alpha", "bravo", "charlie"])
        self.assertEqual([r["priority"] for r in got["rows"]],
                         ["later", "next", "later"])
        self.assertTrue(all(r["restored"] is True for r in got["rows"]))

    def test_a_restored_message_is_stamped_with_todays_agent(self):
        """The saved id would be yesterday's, and the queue only offers a
        command to the main thread when the two match."""
        self.save()
        got = self.restore()
        self.assertTrue(all(r["agentId"] == "agent-of-S1" for r in got["rows"]))
        self.assertNotIn("agentId", json.loads(self.file_for().read_text())
                         ["messages"][0])

    def test_the_restored_mark_never_touches_the_text(self):
        odd = "[waits] literally, and a brace } and a quote \" too"
        self.save(rows=[(odd, "later")])
        got = self.restore()
        self.assertEqual(got["rows"][0]["value"], odd)

    def test_the_file_says_what_it_is_and_which_session_it_belongs_to(self):
        self.save()
        body = json.loads(self.file_for().read_text())
        self.assertEqual(list(body)[0], "file")
        self.assertIn("claude-queue", body["file"])
        self.assertEqual(body["session"], "S1")

    def test_another_session_in_the_same_project_sees_nothing(self):
        """A queue belongs to one session, and this is the whole of it.

        2.1.0 adopted the newest file in the project when the id did not
        match, which was meant for the /resume fork. Every brand new session
        also fails to match, so every new terminal adopted the previous one's
        queue and then saved it forward under its own id. Three terminals in,
        one file held everything ever parked in the project.

        The reported symptom was a message parked in one window turning up in
        another, which reads as the queue being global. It is the same bug.
        """
        self.save()
        got = self.restore(session="OTHER")
        self.assertFalse(got["ok"])
        self.assertEqual(got["rows"], [])
        self.assertTrue(self.file_for("S1").exists(),
                        "the other session must not take the file either")

    def test_adopting_is_available_on_request_and_still_takes_the_file_over(
            self):
        """CLAUDE_QUEUE_ADOPT=on brings 2.1.0 back for anyone who wanted it,
        leak and all, so the fix removes a default rather than a capability."""
        self.save()
        got = self.restore(session="FORK", adopt="on")
        self.assertTrue(got["ok"])
        self.assertTrue(got["hold"])
        self.assertEqual([r["value"] for r in got["rows"]],
                         ["alpha", "bravo", "charlie"])
        self.assertEqual([r["priority"] for r in got["rows"]],
                         ["later", "next", "later"])
        self.assertTrue(all(r["restored"] is True for r in got["rows"]))
        self.assertEqual(got["dir"], ["queue-FORK.json"])
        self.assertFalse(self.file_for("S1").exists())

    def test_its_own_file_wins_over_a_newer_one_beside_it(self):
        """Exact match stays the primary rule: it is the precise answer for
        --continue and --resume <id>, and the scan is only the fallback."""
        self.save()
        self.plant("SOMEONE-ELSE", ["not mine at all"])
        got = self.restore(session="S1")
        self.assertEqual([r["value"] for r in got["rows"]],
                         ["alpha", "bravo", "charlie"])
        self.assertTrue(self.file_for("SOMEONE-ELSE").exists())

    def test_the_newest_file_is_the_one_adopted_when_adopting_is_asked_for(
            self):
        self.plant("OLDER", ["from last week"], age=7 * 24 * 3600)
        self.plant("NEWER", ["from ten minutes ago"], age=600)
        got = self.restore(session="FORK", adopt="on")
        self.assertEqual([r["value"] for r in got["rows"]],
                         ["from ten minutes ago"])
        self.assertTrue(self.file_for("OLDER").exists())
        self.assertFalse(self.file_for("NEWER").exists())

    def test_neither_neighbour_is_touched_when_adopting_is_off(self):
        """The default leaves both files exactly where they are, so opening a
        second terminal costs the first one nothing."""
        self.plant("OLDER", ["from last week"], age=7 * 24 * 3600)
        self.plant("NEWER", ["from ten minutes ago"], age=600)
        got = self.restore(session="FORK")
        self.assertFalse(got["ok"])
        self.assertEqual(got["rows"], [])
        self.assertTrue(self.file_for("OLDER").exists())
        self.assertTrue(self.file_for("NEWER").exists())

    def test_a_fork_in_another_project_still_adopts_nothing(self):
        """The scan cannot leave this project's .claude directory, so the
        wrong-project case stays impossible rather than merely unlikely."""
        self.save()
        elsewhere = Path(tempfile.mkdtemp(prefix="qs-elsewhere-"))
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        got = self.restore(session="FORK", workdir=elsewhere)
        self.assertFalse(got["ok"])
        self.assertEqual(got["rows"], [])
        self.assertTrue(self.file_for("S1").exists())

    def test_a_fork_adopts_nothing_when_persistence_is_off(self):
        self.save()
        got = self.restore(session="FORK", persist="off")
        self.assertFalse(got["ok"])
        self.assertFalse(got["hold"])
        self.assertEqual(got["rows"], [])
        self.assertTrue(self.file_for("S1").exists())

    def test_a_corrupt_neighbour_is_not_adopted_and_not_deleted(self):
        """Nothing here may throw, and taking a file it could not read would
        destroy the only copy of something it did not restore."""
        path = self.file_for("S9")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"messages":[{"value":"half a mess')
        got = self.restore(session="FORK")
        self.assertFalse(got["ok"])
        self.assertEqual(got["rows"], [])
        self.assertTrue(path.exists())

    def test_a_corrupt_file_is_ignored_and_saving_still_works(self):
        self.file_for().parent.mkdir(parents=True, exist_ok=True)
        self.file_for().write_text('{"messages":[{"value":"half a fil')
        got = self.restore()
        self.assertFalse(got["ok"])
        self.assertEqual(got["rows"], [])
        after = self.save(rows=[("written after the corrupt one", "later")])
        self.assertEqual([m["value"] for m in after["file"]["messages"]],
                         ["written after the corrupt one"])

    def test_a_file_that_is_not_json_at_all_is_ignored(self):
        self.file_for().parent.mkdir(parents=True, exist_ok=True)
        self.file_for().write_bytes(b"\x00\x01 not json \xff")
        self.assertFalse(self.restore()["ok"])

    def test_a_file_whose_messages_are_the_wrong_shape_is_ignored(self):
        for body in ('{"messages":"not a list"}', '{"messages":[1,2,3]}',
                     '{"messages":[{"value":"   "}]}', "[]", "null"):
            with self.subTest(body=body):
                self.file_for().parent.mkdir(parents=True, exist_ok=True)
                self.file_for().write_text(body)
                got = self.restore()
                self.assertFalse(got["ok"])
                self.assertEqual(got["rows"], [])

    def test_an_emptied_queue_deletes_the_file(self):
        self.save()
        body = "\n".join([
            "globalThis.__qsRestore();",
            "arr.length=0;notify();",
            "console.log(JSON.stringify({dir:dir()}));",
        ])
        got = run_persist(body, workdir=self.work)
        self.assertEqual(got["dir"], [])

    def test_the_write_leaves_no_half_written_file_behind(self):
        got = self.save()
        self.assertEqual(got["dir"], ["queue-S1.json"])

    def test_nothing_is_written_before_a_restore_was_attempted(self):
        """Otherwise a message enqueued during startup writes the file before
        the saved messages have been read, and deletes what it was protecting.
        """
        body = "\n".join([
            "arr.push(row('typed during startup','later'));notify();",
            "console.log(JSON.stringify({dir:dir()}));",
        ])
        self.assertEqual(run_persist(body, workdir=self.work)["dir"], [])

    def test_off_writes_nothing_and_reads_nothing(self):
        self.save()
        self.assertTrue(self.file_for().exists())
        self.assertFalse(self.restore(persist="off")["ok"])
        self.save(persist="off", rows=[("should not be written", "later")])
        self.assertEqual(
            [m["value"] for m in json.loads(self.file_for().read_text())
             ["messages"]],
            ["alpha", "bravo", "charlie"])

    def test_any_other_value_of_the_switch_keeps_the_default(self):
        for i, value in enumerate(("on", "", "OFF", "yes")):
            with self.subTest(value=value):
                # A fresh session AND a fresh directory each time. A fresh id
                # alone stopped being isolation when the fallback landed: the
                # next id in the same project adopts what the previous one
                # left, and the case would count "kept" once per pass.
                shutil.rmtree(self.work / ".claude", ignore_errors=True)
                got = self.save(session=f"V{i}", persist=value,
                                rows=[("kept", "later")])
                self.assertEqual([m["value"] for m in got["file"]["messages"]],
                                 ["kept"])

    def test_only_text_prompts_are_saved(self):
        """A shell command would run itself on the next resume, a task
        notification is not yours, and a message carrying an image is not a
        string. None of them are the thing this promises to bring back."""
        queue = [
            {"agentId": "agent-of-S1", "mode": "prompt", "value": "keep me",
             "priority": "later"},
            {"agentId": "agent-of-S1", "mode": "bash", "value": "! rm -rf tmp",
             "priority": "later"},
            {"agentId": "agent-of-S1", "mode": "task-notification",
             "value": "a subagent finished", "priority": "next"},
            {"agentId": "agent-of-S1", "mode": "prompt", "value": "   ",
             "priority": "later"},
            {"agentId": "agent-of-S1", "mode": "prompt",
             "value": [{"type": "image"}], "priority": "later"},
            {"agentId": "agent-of-S1", "mode": "prompt", "value": "internal",
             "priority": "later", "isMeta": True},
        ]
        body = "\n".join([
            "globalThis.__qsRestore();notify();",
            "console.log(JSON.stringify(saved()));",
        ])
        got = run_persist(body, workdir=self.work, queue=queue)
        self.assertEqual([m["value"] for m in got["messages"]], ["keep me"])

    def test_a_restored_message_that_is_saved_again_stays_restored(self):
        self.save()
        body = "\n".join([
            "globalThis.__qsRestore();notify();",
            "console.log(JSON.stringify(saved()));",
        ])
        got = run_persist(body, workdir=self.work)
        self.assertTrue(all(m["restored"] is True for m in got["messages"]))

    def test_a_missing_project_directory_is_created(self):
        self.assertFalse((self.work / ".claude").exists())
        self.save(rows=[("first message ever", "later")])
        self.assertTrue(self.file_for().exists())


class FoldingTests(unittest.TestCase):
    """What a queued row is drawn as when it is not the highlighted one."""

    def test_a_short_message_is_left_exactly_as_it_is(self):
        got = fold("[waits] fix the header")
        self.assertTrue(got["same"])
        self.assertEqual(got["text"], "[waits] fix the header")

    def test_a_message_that_fills_one_line_is_still_left_alone(self):
        got = fold("x" * 73)
        self.assertTrue(got["same"])

    def test_one_column_more_than_a_line_folds(self):
        got = fold("x" * 74)
        self.assertFalse(got["same"])
        self.assertTrue(got["text"].endswith("(+1 line)"), got["text"])

    def test_a_pasted_block_says_how_many_lines_it_is_holding_back(self):
        text = "[waits] here my full feedback in many lines\n" + \
            "\n".join(f"point {i}" for i in range(14))
        got = fold(text)
        self.assertEqual(
            got["text"], "[waits] here my full feedback in many lines (+14 lines)")

    def test_a_folded_row_never_exceeds_one_line(self):
        for text in ("y" * 400, "z" * 400 + "\n" + "z" * 400,
                     "\n".join("w" * 90 for _ in range(6))):
            with self.subTest(text=text[:20]):
                got = fold(text)
                self.assertLessEqual(len(got["text"]), 73)
                self.assertIn("...", got["text"])

    def test_the_count_is_the_lines_you_would_see_not_the_newlines(self):
        got = fold("a" * 73 * 3)          # one line, wraps three times
        self.assertTrue(got["text"].endswith("(+2 lines)"), got["text"])

    def test_the_highlighted_row_is_never_folded(self):
        text = "one\ntwo\nthree"
        self.assertTrue(fold(text, highlighted=True)["same"])

    def test_collapse_off_draws_everything_in_full(self):
        text = "one\ntwo\nthree"
        self.assertTrue(fold(text, collapse="off")["same"])

    def test_any_other_value_keeps_the_default(self):
        text = "one\ntwo\nthree"
        for value in ("on", "", "OFF", "yes"):
            with self.subTest(value=value):
                self.assertFalse(fold(text, collapse=value)["same"])

    def test_a_folded_row_gets_a_new_uuid_so_the_renderer_redraws_it(self):
        got = fold("one\ntwo")
        self.assertNotEqual(got["uuid"], "u1")

    def test_a_narrow_terminal_folds_sooner_and_still_fits(self):
        got = fold("q" * 60, columns=60)
        self.assertFalse(got["same"])
        self.assertLessEqual(len(got["text"]), 51)

    def test_the_narrowest_source_wins_when_they_disagree(self):
        """Under a pty nobody resized, the stream says eighty and the app is
        drawing to whatever COLUMNS asked for. Believing the wider one puts the
        wrap back."""
        code = patch_def._fold_fn(Groups(""))
        script = "\n".join([
            "Object.defineProperty(process.stdout,'columns',"
            "{value:80,configurable:true});",
            "process.env.COLUMNS='60';",
            code,
            "let m={uuid:'u',message:{content:[{type:'text',"
            "text:'k'.repeat(60)}]}};",
            "console.log(JSON.stringify(__qsFold(m,false)"
            ".message.content[0].text.length));",
        ])
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), 51)

    def test_trailing_blank_lines_are_not_counted_as_hidden(self):
        self.assertTrue(fold("just this  \n\n  ")["same"])

    def test_a_first_line_that_is_blank_falls_through_to_the_first_real_one(self):
        got = fold("\n\nthe actual first line\nand more")
        self.assertTrue(got["text"].startswith("the actual first line"))

    def test_content_that_is_not_a_single_text_block_is_left_alone(self):
        code = patch_def._fold_fn(Groups(""))
        script = "\n".join([
            code,
            "let cases=[{uuid:'u',message:{content:'plain string'}},"
            "{uuid:'u',message:{content:[{type:'image'}]}},"
            "{uuid:'u',message:{content:[{type:'text',text:'a\\nb'},"
            "{type:'text',text:'c'}]}},"
            "{uuid:'u',message:{content:[]}},{uuid:'u'}];",
            "console.log(JSON.stringify("
            "cases.map((c)=>__qsFold(c,false)===c)));",
        ])
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True] * 5)


class MarkerPolicyTests(unittest.TestCase):
    def test_ordinary_queue_and_steer_words_are_literal(self):
        for text in ("Queue depth is high", "Steer clear of this module"):
            with self.subTest(text=text):
                result = resolve(text)
                self.assertEqual(result["value"], text)
                self.assertEqual(result["priority"], "later")
                self.assertIsNone(result["split"])

    def test_short_typed_markers_still_work(self):
        self.assertEqual(resolve("q fix this")["value"], "fix this")
        self.assertEqual(resolve("s fix this")["priority"], "next")

    def test_pasted_code_is_one_literal_message(self):
        text = "def rebuild():\n    pass\nq = deque()\ns = socket()"
        result = resolve(text, pasted=[text])
        self.assertEqual(result["value"], text)
        self.assertIsNone(result["split"])

    def test_explicit_colon_paste_is_a_batch(self):
        text = "q: write notes\ns: check logs"
        result = resolve(text, pasted=[text])
        self.assertEqual(
            result["split"],
            [{"v": "write notes", "p": "later"},
             {"v": "check logs", "p": "next"}],
        )

    def test_paste_with_leading_text_does_not_become_a_batch(self):
        text = "leading text\nq: second line"
        result = resolve(text, pasted=[text])
        self.assertEqual(result["value"], text)
        self.assertIsNone(result["split"])

    def test_tab_inversion_is_bound_to_the_submitted_text(self):
        self.assertEqual(resolve("same", invert="same")["priority"], "next")
        self.assertEqual(resolve("next", invert="old slash")["priority"], "later")

    def test_tab_shape_refuses_multiple_matches(self):
        shape = "if(a)a(b.text),c=!0;return b}"
        self.assertEqual(patch_def._tab_names(shape)["submit"], "a")
        with self.assertRaises(patch_def.PatchError):
            patch_def._tab_names(shape + shape)

    def test_edited_message_returns_to_raw_slot_around_noneditable_items(self):
        editable = [
            {"value": "alpha", "mode": "prompt", "origin": "human"},
            {"value": "bravo", "mode": "prompt", "origin": "human"},
        ]
        cases = [
            (editable, ["alpha", "bravo edited"]),
            ([{"value": "! printf done", "mode": "bash", "origin": "human"},
              *editable],
             ["! printf done", "alpha", "bravo edited"]),
            ([{"value": "task finished", "mode": "task-notification"},
              *editable],
             ["task finished", "alpha", "bravo edited"]),
            ([editable[0],
              {"value": "task finished", "mode": "task-notification"},
              editable[1]],
             ["alpha", "task finished", "bravo edited"]),
            ([{"value": "internal note", "mode": "prompt",
               "origin": "human", "isMeta": True},
              *editable],
             ["internal note", "alpha", "bravo edited"]),
            ([{"value": "agent output", "mode": "prompt", "origin": "agent"},
              *editable],
             ["agent output", "alpha", "bravo edited"]),
        ]
        for queue, expected in cases:
            with self.subTest(queue=queue):
                self.assertEqual(edit_roundtrip(queue), expected)


class AnchorSpellingTests(unittest.TestCase):
    """Anchors must be able to spell every name a minifier can emit.

    Claude Code 2.1.221 renamed a queue helper to `s$t`. Three anchors spelled
    names as `\\w+`, which cannot match a `$`, so they found nothing, the patch
    refused to apply, and the update left Claude Code unpatched. Not one line
    of the code those anchors describe had changed.

    That failure is invisible until someone updates, and the person updating is
    never the person who wrote the anchor. So it is a test, not a note.
    """

    def test_no_anchor_spells_a_name_with_backslash_w(self):
        offenders = [e.name for e in patch_def.PATCH.edits
                     if r"\w+" in e.anchor.pattern]
        self.assertEqual(
            offenders, [],
            "these anchors use \\w+, which cannot match a $ in a minified "
            "name; use [\\w$]+ instead: " + ", ".join(offenders))

    def test_every_regex_in_the_module_accepts_dollar(self):
        """The by-shape name lookups have the same hazard as the anchors."""
        source = Path(patch_def.__file__).read_text(encoding="utf-8")
        bad = [ln.strip() for ln in source.splitlines()
               if r"\w+" in ln and not ln.strip().startswith("#")]
        self.assertEqual(
            bad, [],
            "every regex in patch_def must spell names as [\\w$]+: "
            + "; ".join(bad))


class NameLookupTests(unittest.TestCase):
    """Names written INTO the replacements cannot be hardcoded either.

    2.1.221 also renamed the enqueue function and a telemetry call, both of
    which had been literals in the replacement text. Those now come from a
    match group or a by-shape lookup, and the lookup has to fail loudly rather
    than quietly pick the wrong one.
    """

    def test_enqueue_is_found_by_the_property_it_is_bound_from(self):
        self.assertEqual(
            patch_def._enqueue_name("var a=1,Pv=Ly.enqueue,b=2;"), "Pv")
        self.assertEqual(
            patch_def._enqueue_name("var s$t=q$.enqueue;"), "s$t")

    def test_no_anchor_pins_the_number_of_arguments_a_call_takes(self):
        """2.1.224 gave three helpers one more argument each and four anchors
        found nothing, with none of the code they describe having changed.

        An argument list is not a shape. Anchors that reach across one capture
        the whole list and paste it back, so an added argument travels through
        instead of stopping the patch. These are the four that were caught
        counting, checked at the arity they were written for and at one more.
        """
        cases = [
            ("bring back one queued message, not all of them",
             'let w=pop(a,b);if(!w)return!1;x"input_queue_pop_to_edit"',
             'let w=pop(a,b,c,d);if(!w)return!1;x"input_queue_pop_to_edit"'),
            ("remember which slot a message came from",
             "let i=ht.getState().queueEditIndex;if(i===null)return!1;"
             "let r=pop(i,a,b);",
             "let i=ht.getState().queueEditIndex;if(i===null)return!1;"
             "let r=pop(i,a,b,c={});"),
        ]
        by_name = {e.name: e for e in patch_def.PATCH.edits}
        for name, before, after in cases:
            for js in (before, after):
                with self.subTest(edit=name, args=js.count(",")):
                    self.assertIsNotNone(by_name[name].anchor.search(js))

    def test_the_marker_anchor_survives_a_rewritten_text_extraction(self):
        """It used to spell the line that pulls the text out of the message.
        2.1.224 replaced one call with a helper and a destructure."""
        edit = {e.name: e for e in patch_def.PATCH.edits}[
            "give a message its marker back when you edit it"]
        old = ("function f(i,cur,off){let c=arr.filter(ed)[i];if(!c)return;"
               "let v=raw(c.value),o=[v,cur].filter(Boolean).join(`\n`),"
               "n=v.length+1+off,")
        new = ("function f(i,cur,off,opts={}){let c=arr.filter(ed)[i];"
               "if(!c)return;let[h]=pull([c],cur,opts),{text:v,entries:en}=h,"
               "o=[v,cur].filter(Boolean).join(`\n`),n=v.length+1+off,")
        for js in (old, new):
            with self.subTest(js=js[:40]):
                self.assertIsNotNone(edit.anchor.search(js))

    def test_the_resolver_anchor_survives_an_extra_declarator(self):
        """2.1.224 declared a pastedContents test in the same `let`."""
        edit = {e.name: e for e in patch_def.PATCH.edits}["resolve the marker"]
        tail = ('preExpansionValue:e.i==="suggestion_accepted"?void 0:r,'
                "mode:m,")
        for js in ("let c={agentId:A(),value:v," + tail,
                   "let w=U&&e.i!==\"x\"&&f(r).some((y)=>1),"
                   "c={agentId:A(),value:v," + tail):
            with self.subTest(js=js[:30]):
                match = edit.anchor.search(js)
                self.assertIsNotNone(match)
                self.assertTrue(match.group(0).startswith("let "),
                                "the insertion point must stay a statement")

    def test_enqueue_lookup_refuses_when_it_is_not_unique(self):
        for js in ("nothing here at all", "a=x.enqueue;b=y.enqueue;"):
            with self.subTest(js=js):
                with self.assertRaises(patch_def.PatchError):
                    patch_def._enqueue_name(js)


def background(tasks, *, shapes=True):
    """Run the background gate against a fake store holding these tasks.

    Returns what the three globals say, plus whether the finished-work wake-up
    fired, so one call answers "is it busy", "what does the row say" and "does
    the queue get told" together.
    """
    # Claude Code's own filter, and the predicate it is built on. The gate
    # finds the first by shape, so the same text is both what it reads and
    # what runs.
    live = (
        "function live(t){return Object.values(t).filter(T0)"
        '.filter((c)=>c.type!=="remote_agent"&&c.type!=="dream")'
        '.filter((c)=>!(c.type==="monitor_ws"&&c.ambient))}'
    )
    js = "x=y.recheckCommandQueue," + (live if shapes else "")
    code = patch_def._background_gate(Groups("", tab="TABLE"), js)
    script = "\n".join([
        "let TABLE,rechecks=0;",
        "function x(){rechecks++}",
        'function T0(e){if(e.status!=="running"&&e.status!=="pending")'
        'return!1;if("isBackgrounded" in e&&e.isBackgrounded===!1)return!1;'
        "return!0}",
        live,
        "let listeners=[],state={tasks:{}};",
        "globalThis.__qsApp={getState:()=>state,"
        "subscribe:(f)=>listeners.push(f)};",
        code,
        f"state={{tasks:{json.dumps(tasks)}}};listeners.forEach((f)=>f());",
        "let busy=globalThis.__qsBusy(),label=globalThis.__qsBg();",
        "let whenBusy=TABLE.after;",
        "state={tasks:{}};listeners.forEach((f)=>f());",
        # undefined would vanish from the JSON, and it is the whole point.
        "console.log(JSON.stringify({busy,label,"
        "whenBusy:whenBusy??null,whenIdle:TABLE.after??null,rechecks}));",
    ])
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


SHELL = {"id": "b1", "type": "local_bash", "status": "running"}
AGENT = {"id": "a1", "type": "local_agent", "status": "running"}


class BackgroundGateTests(unittest.TestCase):
    """A turn ending is not the work ending.

    A background agent, a shell left running, a monitor or a workflow all
    outlive the turn that started them. An ordinary waiting message runs
    straight into them, which is what Mounssif hit: the footer read "1 shell
    still running" and the queue drained anyway.
    """

    def test_a_running_shell_makes_the_session_busy(self):
        r = background({"b1": SHELL})
        self.assertTrue(r["busy"])
        self.assertEqual(r["label"], "1 shell")

    def test_nothing_running_is_not_busy_and_has_no_label(self):
        r = background({})
        self.assertFalse(r["busy"])
        self.assertIsNone(r["label"])

    def test_the_after_priority_is_invisible_while_work_runs(self):
        """Undefined is not a key in the table, so all three selectors skip it,
        exactly the way they skip a parked message."""
        self.assertIsNone(background({"b1": SHELL})["whenBusy"])

    def test_the_after_priority_becomes_an_ordinary_wait_once_it_is_over(self):
        self.assertEqual(background({"b1": SHELL})["whenIdle"], 2)

    def test_the_queue_is_told_when_the_last_task_finishes(self):
        """Nothing else pokes it: no turn ends and no key is pressed."""
        self.assertEqual(background({"b1": SHELL})["rechecks"], 1)

    def test_the_row_names_what_it_is_waiting_for(self):
        r = background({"b1": SHELL, "a1": AGENT,
                        "a2": {"id": "a2", "type": "local_agent",
                               "status": "pending"}})
        self.assertEqual(r["label"], "1 shell, 2 agents")

    def test_a_monitor_is_named_as_a_monitor_not_a_shell(self):
        r = background({"m1": {"id": "m1", "type": "local_bash",
                               "kind": "monitor", "status": "running"}})
        self.assertEqual(r["label"], "1 monitor")

    def test_a_finished_task_is_not_waited_for(self):
        self.assertFalse(background({"b1": {**SHELL,
                                            "status": "completed"}})["busy"])

    def test_a_synchronous_subagent_is_the_turn_not_the_background(self):
        self.assertFalse(background({"a1": {**AGENT,
                                            "isBackgrounded": False}})["busy"])

    def test_a_cloud_session_is_never_a_reason_to_wait(self):
        self.assertFalse(background({"r1": {"id": "r1",
                                            "type": "remote_agent",
                                            "status": "running"}})["busy"])

    def test_an_ambient_monitor_is_never_a_reason_to_wait(self):
        self.assertFalse(background({"s1": {"id": "s1", "type": "monitor_ws",
                                            "status": "running",
                                            "ambient": True}})["busy"])

    def test_it_still_works_when_claude_code_renames_its_own_filter(self):
        """That lookup is allowed to fail. It decides how long a message waits,
        not what runs, so a rename must not leave anyone unpatched."""
        r = background({"b1": SHELL,
                        "r1": {"id": "r1", "type": "remote_agent",
                               "status": "running"}}, shapes=False)
        self.assertTrue(r["busy"])
        self.assertEqual(r["label"], "1 shell")

    def test_the_fallback_agrees_with_the_real_filter(self):
        cases = [
            {},
            {"b1": SHELL},
            {"a1": {**AGENT, "isBackgrounded": False}},
            {"r1": {"id": "r1", "type": "remote_agent", "status": "running"}},
            {"d1": {"id": "d1", "type": "dream", "status": "running"}},
            {"b1": {**SHELL, "status": "failed"}},
        ]
        for tasks in cases:
            with self.subTest(tasks=sorted(tasks)):
                self.assertEqual(background(tasks)["label"],
                                 background(tasks, shapes=False)["label"])

    def test_the_wake_up_is_installed_once_however_the_order_falls(self):
        self.assertIn("__qsWatching", patch_def._background_gate(
            Groups("", tab="T"), "x=y.recheckCommandQueue,"))

    def test_the_recheck_lookup_refuses_when_it_is_not_unique(self):
        for js in ("nothing here", "a=x.recheckCommandQueue,b=y."
                                   "recheckCommandQueue,"):
            with self.subTest(js=js):
                with self.assertRaises(patch_def.PatchError):
                    patch_def._recheck_name(js)


class BackgroundMarkerTests(unittest.TestCase):
    """The marker side of the same feature."""

    def test_x_asks_to_wait_for_the_background(self):
        self.assertEqual(resolve("x run the tests")["priority"], "after")
        self.assertEqual(resolve("x: run the tests")["priority"], "after")

    def test_the_marker_never_reaches_the_model(self):
        self.assertEqual(resolve("x run the tests")["value"], "run the tests")

    def test_a_pasted_assignment_is_still_literal(self):
        r = resolve("x = compute()", pasted=["x = compute()"])
        self.assertEqual(r["value"], "x = compute()")
        self.assertNotEqual(r["priority"], "after")

    def test_it_takes_its_place_in_a_pasted_batch(self):
        r = resolve("q: write the notes\nx: run the tests\ns: check the logs",
                    pasted=["q: write the notes\nx: run the tests\n"
                            "s: check the logs"])
        self.assertEqual([m["p"] for m in r["split"]],
                         ["later", "after", "next"])


if __name__ == "__main__":
    unittest.main()
