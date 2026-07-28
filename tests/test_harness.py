import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


record = load("record_harness", ROOT / "harness" / "record.py")
measure = load("measure_harness", ROOT / "harness" / "measure.py")
markers = load(
    "marker_harness", ROOT / "harness" / "behaviour" / "test_markers.py"
)


class HarnessTests(unittest.TestCase):
    def test_lab_disables_customizations_and_names_its_session(self):
        with tempfile.TemporaryDirectory() as td:
            lab = record.Lab(
                binary="/bin/true", workspace=td,
                extra_env={"CLAUDE_CONFIG_DIR": "/should/not/win"},
            )
            lab_module = sys.modules[record.Lab.__module__]
            with mock.patch.dict(
                    lab_module.os.environ,
                    {"CLAUDE_CODE_PARENT": "parent", "CLAUDECODE": "1",
                     "CLAUDE_CONFIG_DIR": "/real/config"}):
                env = lab._child_env()
            self.assertNotIn("CLAUDE_CODE_PARENT", env)
            self.assertNotIn("CLAUDECODE", env)
            self.assertIn("--safe-mode", lab._argv())
            self.assertIn("--session-id", lab._argv())
            self.assertIn(lab.session_id, lab._argv())
            self.assertIn("skipDangerousModePermissionPrompt", " ".join(lab._argv()))

    def test_lab_retries_partial_pty_writes(self):
        lab = record.Lab(binary="/bin/true")
        lab.fd = 99
        received = bytearray()

        def short_write(_fd, data):
            chunk = bytes(data[:2])
            received.extend(chunk)
            return len(chunk)

        lab_module = sys.modules[record.Lab.__module__]
        with mock.patch.object(lab_module.os, "write", side_effect=short_write):
            lab.write(b"abcdef")
        self.assertEqual(received, b"abcdef")

    def test_lab_waits_for_a_tool_not_only_a_spinner(self):
        lab = record.Lab(binary="/bin/true")
        screens = iter([
            "thinking (1s · esc to interrupt)",
            "Bash(for i in {1..17}) (2s · esc to interrupt)",
        ])
        with mock.patch.object(lab, "_pump"), \
                mock.patch.object(lab, "screen", side_effect=screens):
            self.assertTrue(lab.wait_for_tool(timeout=1))

    def test_marker_assertion_selects_the_labeled_row(self):
        screen = (
            "q: colonq charlie\n"
            "  ❯ [waits] colonq charlie\n"
        )
        self.assertEqual(
            markers.labeled_line(screen, "colonq charlie", "[waits]"),
            "  ❯ [waits] colonq charlie",
        )

    def test_lab_removes_only_its_named_session_history(self):
        with tempfile.TemporaryDirectory() as td:
            lab_module = sys.modules[record.Lab.__module__]
            root = Path(td) / ".claude" / "projects"
            existing = root / "existing"
            existing.mkdir(parents=True)
            keep = existing / "keep.jsonl"
            keep.write_text("keep")
            lab = record.Lab(binary="/bin/true")
            lab._history_dirs_before = {str(root), str(existing)}
            created = root / "created"
            created.mkdir()
            (created / f"{lab.session_id}.jsonl").write_text("test")
            owned = existing / lab.session_id / "subagents"
            owned.mkdir(parents=True)
            (owned / "agent-child.jsonl").write_text("test")
            with mock.patch.object(lab_module, "HOME", td):
                lab._cleanup_session_history()
            self.assertTrue(keep.is_file())
            self.assertFalse(created.exists())
            self.assertFalse((existing / lab.session_id).exists())

    def test_record_labels_are_basenames(self):
        for label in ("../behaviour", "x/../behaviour", "/tmp/registry", "", "a" * 65):
            with self.subTest(label=label), self.assertRaises(ValueError):
                record.run_paths(label)
        runs, workspace, destination = record.run_paths("stock-2.1.220")
        self.assertEqual(workspace.parent, record.HERE.resolve())
        self.assertEqual(destination.parent, runs)

    def test_measurement_reports_dropped_followup_as_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.json"
            path.write_text(json.dumps({
                "label": "partial", "frames": ["Write(CHANGELOG.md)"],
                "stamps": [10], "marks": [0, 0], "files": ["CHANGELOG.md"],
            }))
            result = measure.analyse(path)
            self.assertEqual(result["missing"], ["metrics.py"])
            old = sys.argv
            sys.argv = ["measure.py", str(path)]
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    status = measure.main()
            finally:
                sys.argv = old
            self.assertEqual(status, 1)
            self.assertIn("INCOMPLETE", out.getvalue())
            self.assertIn("metrics.py", out.getvalue())


if __name__ == "__main__":
    unittest.main()
