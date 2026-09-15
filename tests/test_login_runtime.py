"""Test isolated login packaging and private credential preparation without AWS calls."""

import base64
import gzip
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from scripts.deploy_login import build
from scripts.login_runtime import prepare, render_secrets


class LoginRuntimeTests(unittest.TestCase):
    """Verify fixed OIDC bindings, private files, and a secret-free deployment bundle."""

    def setUp(self):
        """Prepare matching fake deployment settings and credentials for each test."""

        self.login = json.loads(Path("scripts/config_defaults/login-bootstrap.json").read_text())
        self.proxy = json.loads(Path("scripts/config_defaults/proxy.json").read_text())
        self.proxy["domain"] = self.login["app_origin"].removeprefix("https://")
        self.payload = {
            "auth": {
                "redirect_uri": self.login["app_origin"] + "/oauth2callback",
                "client_id": self.login["client_id"],
                "cookie_secret": "a" * 64,
                "client_secret": "fake-client-secret-for-tests",
                "server_metadata_url": f"https://cognito-idp.{self.login['region']}.amazonaws.com/{self.login['user_pool_id']}/.well-known/openid-configuration",
                "client_kwargs": {
                    "scope": "openid email profile",
                    "identity_provider": "IdentityCenter",
                    "prompt": "login",
                },
            }
        }

    def test_toml_round_trip(self):
        """Render only supported authentication fields without changing their values."""

        self.assertEqual(
            tomllib.loads(render_secrets(self.payload, self.login)), self.payload
        )

    def test_reject_other_provider_or_origin(self):
        """Reject mismatched callbacks, secrets, and providers before writing a runtime file."""

        for changes in (
            {"redirect_uri": "https://other.example/oauth2callback"},
            {"client_kwargs": {"identity_provider": "COGNITO"}},
            {"cookie_secret": "short"},
            {"client_secret": "secret\n[unsafe]"},
            {"extra": "unexpected"},
        ):
            with self.assertRaises(ValueError):
                render_secrets({"auth": self.payload["auth"] | changes}, self.login)

    def test_private_file_and_no_overwrite(self):
        """Write credentials with owner-only permissions and reject existing files."""

        client = Mock()
        client.get_caller_identity.return_value = {"Account": self.login["account_id"]}
        client.get_secret_value.return_value = {
            "ARN": self.login["secret_arn"],
            "SecretString": json.dumps(self.payload),
        }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("scripts.login_runtime.boto3.Session") as session,
        ):
            session.return_value.client.return_value = client
            target = Path(directory) / "secrets.toml"

            prepare(self.login, target)

            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(tomllib.loads(target.read_text()), self.payload)

            with self.assertRaises(FileExistsError):
                prepare(self.login, target)

    def test_wrong_account_never_reads_secret(self):
        """Stop before accessing credentials when the instance role belongs to another account."""

        with patch("scripts.login_runtime.boto3.Session") as session:
            client = session.return_value.client.return_value
            client.get_caller_identity.return_value = {"Account": "999999999999"}

            with self.assertRaises(ValueError):
                prepare(self.login, Path("unused"))

            client.get_secret_value.assert_not_called()

    def test_bundle_excludes_chat_and_starts_denied(self):
        """Package only login sources and locked requirements with no participant assignments or secrets."""

        with patch(
            "scripts.deploy_login.subprocess.run",
            return_value=Mock(stdout="example==1 --hash=sha256:abc\n"),
        ):
            command = build(self.proxy, self.login)

        candidates = re.findall(r"[A-Za-z0-9+/=]{100,}", command)
        bundle = next(
            json.loads(gzip.decompress(base64.b64decode(value)))
            for value in candidates
            if base64.b64decode(value).startswith(b"\x1f\x8b")
        )

        self.assertEqual(
            set(bundle["files"]),
            {
                "app/__init__.py",
                "app/access.py",
                "app/login_ui.py",
                "scripts/login_runtime.py",
                "requirements.txt",
                ".streamlit/config.toml",
            },
        )
        self.assertFalse(bundle["access"]["enabled"])
        self.assertEqual(bundle["access"]["members"], {})
        self.assertNotIn("profile", bundle["runtime"])
        self.assertNotIn(self.payload["auth"]["client_secret"], command)

        config = tomllib.loads(bundle["files"][".streamlit/config.toml"])

        self.assertEqual(config["server"]["address"], "127.0.0.1")
        self.assertTrue(config["server"]["enableXsrfProtection"])

    def test_mismatched_host_does_not_export(self):
        """Reject a mismatched deployment domain before exporting dependencies."""

        with patch("scripts.deploy_login.subprocess.run") as export:
            with self.assertRaises(ValueError):
                build(self.proxy | {"domain": "other.example.com"}, self.login)

            export.assert_not_called()
