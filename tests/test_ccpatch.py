import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import ccpatch  # noqa: E402


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.patches = [
            mock.patch.object(ccpatch, "STATE", self.state),
            mock.patch.object(ccpatch, "REGISTRY", self.state / "registry.json"),
            mock.patch.object(ccpatch, "TRANSACTION", self.state / "transaction.json"),
            mock.patch.object(ccpatch, "BACKUPS", self.state / "backups"),
            mock.patch.object(ccpatch, "WORK", self.state / "work"),
            mock.patch.object(ccpatch, "TWEAKCC", self.state / "tweakcc"),
            mock.patch.object(
                ccpatch,
                "TWEAKCC_MANIFEST",
                Path(self.tmp.name) / "tweakcc-manifest",
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_registry_write_is_atomic_and_shape_checked(self):
        reg = {"stock": None, "patches": {}}
        ccpatch.write_registry(reg)
        self.assertEqual(ccpatch.read_registry(), reg)
        self.assertEqual(ccpatch.REGISTRY.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.state.glob(".registry.json.*.tmp")), [])
        ccpatch.REGISTRY.write_text("[]")
        with self.assertRaises(ccpatch.PatchError):
            ccpatch.read_registry()

    def test_enable_interruption_does_not_publish_desired_registry(self):
        definition = Path(self.tmp.name) / "patch.py"
        definition.write_text("PATCH = None\n")
        before = {"stock": None, "patches": {}}
        ccpatch.write_registry(before)
        patch = ccpatch.Patch("demo", "demo", "marker", [])
        with mock.patch.object(ccpatch, "rebuild", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ccpatch.enable(patch, definition)
        self.assertEqual(ccpatch.read_registry(), before)

    def test_stock_digest_rejects_tampering(self):
        backup = Path(self.tmp.name) / "stock"
        backup.write_bytes(b"stock bytes")
        digest = ccpatch._sha256(backup)
        reg = {"stock": {"path": str(backup), "sha256": digest}, "patches": {}}
        self.assertEqual(ccpatch._verified_stock(reg), (backup, digest))
        backup.write_bytes(b"changed")
        with self.assertRaises(ccpatch.PatchError):
            ccpatch._verified_stock(reg)

    def test_locked_helper_install_runs_inside_staging(self):
        ccpatch.TWEAKCC_MANIFEST.mkdir()
        (ccpatch.TWEAKCC_MANIFEST / "package.json").write_text("{}\n")
        (ccpatch.TWEAKCC_MANIFEST / "package-lock.json").write_text("{}\n")
        observed = {}

        def npm_run(command, *, cwd, capture_output, text):
            observed["command"] = command
            observed["cwd"] = Path(cwd)
            exe = observed["cwd"] / "node_modules" / ".bin" / "tweakcc"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\n")
            return SimpleNamespace(returncode=0, stderr="")

        with mock.patch.object(ccpatch.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(ccpatch.subprocess, "run", side_effect=npm_run):
            installed = ccpatch.ensure_tweakcc(log=lambda _: None)

        self.assertTrue(installed.is_file())
        self.assertNotIn("--prefix", observed["command"])
        self.assertEqual(observed["cwd"].parent, self.state)
        self.assertTrue(observed["cwd"].name.startswith("tweakcc-next-"))

    def test_legacy_digest_can_only_upgrade_when_prefix_matches(self):
        backup = Path(self.tmp.name) / "stock"
        backup.write_bytes(b"stock bytes")
        digest = ccpatch._sha256(backup)
        reg = {"stock": {"path": str(backup), "sha256": digest[:12]}, "patches": {}}
        self.assertEqual(ccpatch._verified_stock(reg)[1], digest)

    def test_missing_definition_drops_only_that_patch(self):
        present = Path(self.tmp.name) / "present.py"
        present.write_text("PATCH = None\n")
        reg = {"stock": None, "patches": {
            "present": {"definition": str(present)},
            "gone": {"definition": str(Path(self.tmp.name) / "gone.py")},
        }}
        logs = []
        self.assertEqual(ccpatch._drop_missing_patches(reg, logs.append), ["gone"])
        self.assertEqual(list(reg["patches"]), ["present"])
        self.assertIn("definition missing", logs[0])

    def test_live_old_lock_is_not_stolen_and_release_is_owner_safe(self):
        lock_path = self.state / "lock"
        lock_path.parent.mkdir(parents=True)
        lock_path.write_text(f"{os.getpid()}:live")
        old = time.time() - 3600
        os.utime(lock_path, (old, old))
        with self.assertRaises(ccpatch.PatchError):
            with ccpatch.Lock(stale_after=0):
                pass

        lock_path.unlink()
        lock = ccpatch.Lock(stale_after=0)
        lock.__enter__()
        lock_path.write_text("999999:replacement")
        lock.__exit__(None, None, None)
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.read_text(), "999999:replacement")

    def test_released_kernel_lock_can_be_reacquired_without_unlinking(self):
        first = ccpatch.Lock()
        first.__enter__()
        first.__exit__(None, None, None)
        self.assertEqual((self.state / "lock").read_text(), "released")
        with ccpatch.Lock():
            self.assertIn(":", (self.state / "lock").read_text())

    def test_interrupted_transaction_restores_binary_and_registry(self):
        binary = Path(self.tmp.name) / "bin" / "claude"
        binary.parent.mkdir()
        binary.write_bytes(b"new")
        rollback = binary.parent / ".claude.claude-patch-test.rollback"
        rollback.write_bytes(b"old")
        rollback.chmod(0o755)
        before = {"stock": None, "patches": {}}
        tx = {"binary": str(binary), "rollback": str(rollback),
              "hardlinks": [], "registry_before": before}
        ccpatch._atomic_write_text(ccpatch.TRANSACTION, json.dumps(tx))
        self.assertTrue(ccpatch.recover_transaction())
        self.assertEqual(binary.read_bytes(), b"old")
        self.assertEqual(ccpatch.read_registry(), before)
        self.assertFalse(ccpatch.TRANSACTION.exists())

    def test_disable_restores_stock_binary_byte_for_byte(self):
        binary = Path(self.tmp.name) / "bin" / "claude"
        binary.parent.mkdir()
        binary.write_bytes(b"patched bytes")
        binary.chmod(0o755)
        stock = Path(self.tmp.name) / "stock"
        stock.write_bytes(b"stock bytes exactly")
        stock.chmod(0o755)
        definition = Path(self.tmp.name) / "patch.py"
        definition.write_text("PATCH = None\n")
        patch = ccpatch.Patch("demo", "demo", "marker", [])
        ccpatch.write_registry({
            "stock": {"path": str(stock), "sha256": ccpatch._sha256(stock)},
            "patches": {"demo": {"definition": str(definition)}},
            "built": {"identity": ccpatch.identity(binary)},
        })
        version = SimpleNamespace(
            returncode=0, stdout="Claude Code 2.1.220\n", stderr="")

        with mock.patch.object(ccpatch, "find_binary", return_value=binary), \
                mock.patch.object(ccpatch.subprocess, "run", return_value=version):
            self.assertTrue(ccpatch.disable(patch))

        self.assertEqual(binary.read_bytes(), stock.read_bytes())
        self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
        self.assertEqual(ccpatch.read_registry()["patches"], {})

    def test_heal_failure_is_reported_to_callers(self):
        reg = {"stock": None, "patches": {
            "demo": {"definition": str(Path(self.tmp.name) / "demo.py")}
        }}
        with mock.patch.object(ccpatch, "is_current", return_value=False), \
                mock.patch.object(ccpatch, "read_registry", return_value=reg), \
                mock.patch.object(ccpatch, "rebuild", side_effect=ccpatch.PatchError("boom")):
            self.assertFalse(ccpatch.self_heal())
            patch = ccpatch.Patch("demo", "demo", "marker", [])
            self.assertEqual(ccpatch.main(patch, ["demo", "heal"]), 1)


if __name__ == "__main__":
    unittest.main()
