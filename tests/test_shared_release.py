"""Test isolated release packaging and service staging without changing the active host."""

import json
import gzip
import tomllib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.shared_card import load_targets
from scripts.deploy_shared import build
from scripts.shared_release import stage


class SharedReleaseTests(unittest.TestCase):
    """Verify explicit targets, bounded commands, and safe release paths."""

    def test_packaging_requires_matching_targets_and_review(self):
        """Reject missing review or cross-account destinations before deployment."""

        proxy = json.loads(Path("scripts/config_defaults/proxy.json").read_text())
        targets = load_targets("scripts/config_defaults/shared-card.json")

        with self.assertRaises(ValueError):
            build(proxy, "update", targets)

        with self.assertRaises(ValueError):
            build(proxy, "update", targets | {"account_id": "999999999999"}, "a" * 64)

        self.assertLess(len(build(proxy, "update", targets, "a" * 64).encode()), 60000)

        with self.assertRaises(ValueError):
            build(proxy, "rollback", expected="a" * 64, backup="../../etc")

    def test_release_configuration(self):
        """Package the configured theme while keeping the server behind the proxy."""

        proxy = json.loads(Path("scripts/config_defaults/proxy.json").read_text())
        targets = load_targets("scripts/config_defaults/shared-card.json")

        with patch(
            "scripts.deploy_shared.gzip.compress", wraps=gzip.compress
        ) as compress:
            build(proxy, "update", targets, "a" * 64)

        bundle = json.loads(compress.call_args.args[0])
        self.assertIn("app/browser_url.py", bundle["files"])
        self.assertIn("app/assets/browser_url.js", bundle["files"])
        config = tomllib.loads(bundle["files"][".streamlit/config.toml"])
        expected = tomllib.loads(Path(".streamlit/config.toml").read_text())

        self.assertEqual(config["theme"], expected["theme"])
        self.assertEqual(config["server"]["address"], "127.0.0.1")
        self.assertNotIn("@@THEME@@", bundle["files"][".streamlit/config.toml"])

    def test_stage_preserves_original_service_and_limits_paths(self):
        """Create a separate candidate and reject files outside the release allowlist."""

        service = Path("hosting/login.service").read_text()
        bundle = {
            "files": {"app/shared_ui.py": '"""Display the shared card."""\n'},
            "targets": {},
            "service": service,
        }

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("scripts.shared_release.subprocess.run") as run,
        ):
            directory = Path(temporary)
            unit = stage(bundle, directory)

            self.assertIn(f"WorkingDirectory={directory}", unit)
            self.assertIn("PET_UI_ENTRY=app/shared_ui.py", unit)
            self.assertIn("ExecStart=/opt/workshop-login/venv/bin/python", unit)
            self.assertEqual(Path("hosting/login.service").read_text(), service)
            run.assert_called_once()

            with self.assertRaises(ValueError):
                stage(bundle | {"files": {"../outside.py": ""}}, directory)
