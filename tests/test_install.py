import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.repo = Path(self.tmp.name) / "repo"
        self.home.mkdir()
        (self.repo / "bin").mkdir(parents=True)
        shutil.copy2(ROOT / "install.sh", self.repo / "install.sh")
        (self.repo / "bin" / "claude").write_text("launcher\n")
        cli = self.repo / "bin" / "claude-queue"
        cli.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$HOME/calls\"\n")
        cli.chmod(0o755)
        self.rc = self.home / ".zshrc"
        self.rc.write_text("")
        self.env = {**os.environ, "HOME": str(self.home)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args):
        return subprocess.run(
            ["bash", str(self.repo / "install.sh"), *args],
            env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
        )

    def test_unknown_option_is_rejected_without_mutation(self):
        before = self.rc.read_text()
        result = self.run_install("--dry-rnu")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.rc.read_text(), before)
        self.assertFalse((self.home / "calls").exists())

    def test_noninteractive_install_requires_yes(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires --yes", result.stderr)
        self.assertEqual(self.rc.read_text(), "")

    def test_dry_run_changes_no_modes_or_shell_files(self):
        launcher = self.repo / "bin" / "claude"
        before_mode = launcher.stat().st_mode & 0o777
        result = self.run_install("--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(launcher.stat().st_mode & 0o777, before_mode)
        self.assertEqual(self.rc.read_text(), "")
        self.assertEqual((self.home / "calls").read_text().splitlines(), ["doctor"])

    def test_unrelated_claude_comment_does_not_block_launcher_line(self):
        self.rc.write_text("# claude-api key is in the environment\n")
        result = self.run_install("--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("export PATH=", self.rc.read_text())
        self.assertEqual((self.home / "calls").read_text().splitlines(), ["install"])


if __name__ == "__main__":
    unittest.main()
