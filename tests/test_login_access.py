"""Test guarded policy replacement and preservation of the previous authorization state."""

import builtins
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.login_access import build, remote_update


class LoginAccessTests(unittest.TestCase):
    """Exercise local policy updates without contacting AWS or changing service files."""

    def test_update_preserves_backup_and_rejects_stale_review(self):
        """Preserve the original policy and refuse stale fingerprints or provider changes."""

        original = Path("scripts/config_defaults/access.json").read_bytes()
        fingerprint = hashlib.sha256(original).hexdigest()
        policy = json.loads(original)
        real_open = builtins.open

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "access.json"

            target.write_bytes(original)

            def redirected_open(path, *args, **kwargs):
                """Keep the remote lock inside the temporary test directory."""

                if path == "/run/workshop-login-access.lock":
                    path = Path(directory) / "lock"

                return real_open(path, *args, **kwargs)

            with (
                patch("scripts.login_access.Path", return_value=target),
                patch("builtins.open", side_effect=redirected_open),
            ):
                self.assertEqual(
                    remote_update({"policy": None})["fingerprint"], fingerprint
                )

                with self.assertRaises(ValueError):
                    remote_update(
                        {
                            "policy": policy | {"client_id": "another"},
                            "expected": fingerprint,
                        }
                    )

                self.assertEqual(target.read_bytes(), original)

                updated = remote_update(
                    {
                        "policy": policy | {"members": {"subject": "team-01"}},
                        "expected": fingerprint,
                    }
                )

                self.assertEqual(
                    (target.parent / updated["backup"]).read_bytes(), original
                )
                self.assertEqual(target.stat().st_mode & 0o777, 0o640)

                with self.assertRaises(ValueError):
                    remote_update({"policy": policy, "expected": fingerprint})

    def test_update_requires_review(self):
        """Require a complete fingerprint for writes but allow read-only status queries."""

        with self.assertRaises(ValueError):
            build({}, None)

        self.assertIn("/opt/workshop-login/venv/bin/python", build(None, None))
