"""Test proxy deployments in temporary directories without services or network access."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from scripts.proxy_release import FILES, activate, snapshot, verify_backup


class ReleaseTests(unittest.TestCase):
    """Check managed file updates, idempotency, drift, and recovery."""

    def setUp(self):
        """Build a fake server and candidate release in a temporary directory."""

        self.temp = tempfile.TemporaryDirectory()

        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name) / "host"
        self.stage = Path(self.temp.name) / "candidate"

        self.stage.mkdir()

        for name, relative in FILES.items():
            path = self.root / relative

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("previous " + name)
            (self.stage / name).write_text("next " + name)

        self.before = snapshot(self.root)

    def test_update_and_explicit_rollback(self):
        """Preserve a verified backup and restore it using a newly reviewed fingerprint."""

        result = activate(self.root, self.stage, self.before["fingerprint"], Mock())
        backup = self.root / "var/lib/workshop-proxy-backups" / result["backup"]

        verify_backup(backup)

        restored = activate(self.root, backup, result["fingerprint"], Mock())

        self.assertEqual(restored["fingerprint"], self.before["fingerprint"])
        self.assertNotEqual(result["backup"], restored["backup"])

    def test_restart_failure_restores_old_files(self):
        """Restore original files when the new service cannot start."""

        restart = Mock(side_effect=[RuntimeError("failed"), None])

        with self.assertRaisesRegex(RuntimeError, "restored"):
            activate(self.root, self.stage, self.before["fingerprint"], restart)

        self.assertEqual(snapshot(self.root), self.before)
        self.assertEqual(restart.call_count, 2)

    def test_drift_does_not_write(self):
        """Reject stale reviews before creating backups or restarting."""

        restart = Mock()

        with self.assertRaises(ValueError):
            activate(self.root, self.stage, "0" * 64, restart)

        self.assertEqual(snapshot(self.root), self.before)
        self.assertFalse((self.root / "var").exists())
        restart.assert_not_called()

    def test_same_files_do_not_restart(self):
        """Avoid backups and restarts when the candidate is already installed."""

        for name, relative in FILES.items():
            (self.stage / name).write_bytes((self.root / relative).read_bytes())

        restart = Mock()
        result = activate(self.root, self.stage, self.before["fingerprint"], restart)

        self.assertEqual(result["status"], "unchanged")
        restart.assert_not_called()

    def test_tampered_backup_is_rejected(self):
        """Reject backups whose contents do not match the manifest."""

        (self.stage / "manifest.json").write_text(json.dumps(self.before))

        with self.assertRaises(ValueError):
            verify_backup(self.stage)
