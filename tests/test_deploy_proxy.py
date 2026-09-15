"""Test proxy installation and rejection of incorrect remote targets."""

import json
from pathlib import Path
import re
import shlex
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from streamlit.auth_util import build_logout_url

from scripts.deploy_proxy import (
    commands,
    deploy,
    proxy_files,
    release_commands,
    verify_https,
)


class ProxyTests(unittest.TestCase):
    """Validate secret-free templates and preflight checks before remote writes."""

    def setUp(self):
        """Load fake configuration without contacting AWS."""

        self.config = json.loads(
            (
                Path(__file__).resolve().parents[1] / "scripts/config_defaults/proxy.json"
            ).read_text()
        )

    def test_installer_is_verified_and_guarded(self):
        """Require a verified hash and absent managed files before installing services."""

        script = "\n".join(commands(self.config))

        self.assertIn("sha256sum -c -", script)
        self.assertIn("test ! -e /etc/caddy/Caddyfile", script)
        self.assertNotIn("secrets.toml", script)
        self.assertLess(script.index("sha256sum"), script.index("tar -xzf"))

    def test_rejects_shell_input(self):
        """Reject shell interpolation in domains, versions, and identifiers."""

        for key in ("domain", "version", "instance_id", "sha256"):
            with self.assertRaises(ValueError):
                commands(self.config | {key: "$(whoami)"})

    def test_routes_are_explicit_and_bounded(self):
        """Default older configurations to maintenance and allow only the isolated login destination."""

        legacy = {key: value for key, value in self.config.items() if key != "route"}

        self.assertIn('respond "El taller', proxy_files(legacy)["Caddyfile"])
        self.assertIn(
            "reverse_proxy 127.0.0.1:8501",
            proxy_files(legacy | {"route": "login"})["Caddyfile"],
        )
        self.assertEqual(commands(legacy), commands(legacy | {"route": "maintenance"}))
        self.assertNotEqual(
            release_commands(legacy, "update", "a" * 64),
            release_commands(legacy | {"route": "login"}, "update", "a" * 64),
        )

        for extra in ({"route": "chat"}, {"route": None}, {"upstream": "example.com"}):
            with self.assertRaises(ValueError):
                commands(legacy | extra)

    def test_login_verification_checks_health(self):
        """Require the login shell, health response, and same-host redirect before reporting transport success."""

        with (
            patch("scripts.deploy_proxy.http.client.HTTPSConnection") as https,
            patch("scripts.deploy_proxy.http.client.HTTPConnection") as http,
        ):
            shell = Mock(status=200)
            shell.read.return_value = b"<title>Streamlit</title>"
            shell.getheader.return_value = "no-store, no-cache"
            health = Mock(status=200)
            health.read.return_value = b"ok"
            health.getheader.return_value = "no-store"
            redirect = Mock(status=308)
            redirect.getheader.return_value = f"https://{self.config['domain']}/"
            http.return_value.getresponse.return_value = redirect
            https.return_value.getresponse.side_effect = [shell, health]

            self.assertEqual(
                verify_https(self.config | {"route": "login"})["https"], "verified"
            )
            self.assertEqual(https.return_value.close.call_count, 2)
            https.return_value.request.assert_called_with("GET", "/_stcore/health")

            for response in (Mock(status=502), shell, health):
                response.read.return_value = b"unexpected"
                response.getheader.return_value = "no-store"
                https.return_value.getresponse.side_effect = [response]

                with self.assertRaises(RuntimeError):
                    verify_https(self.config | {"route": "login"})

    def test_cognito_logout_keeps_streamlit_redirect_and_adds_allowed_origin(self):
        """Adapt only Cognito logout responses to the configured app origin."""

        template = proxy_files(self.config | {"route": "login"})["Caddyfile"]
        rule = next(line for line in template.splitlines() if "header_down Location" in line)
        _, _, pattern, replacement = shlex.split(rule)
        replacement = replacement.replace("$1", r"\g<1>")
        endpoint = "https://example.auth.us-east-1.amazoncognito.com/logout"
        origin = "https://" + self.config["domain"]
        for token in (None, "fake-token"):
            url = build_logout_url(endpoint, "test-client", origin + "/oauth2callback", token)
            adapted = re.sub(pattern, replacement, url)
            params = parse_qs(urlsplit(adapted).query)
            self.assertEqual(params["logout_uri"], [origin])
            self.assertEqual(params["client_id"], ["test-client"])
            self.assertTrue(adapted.startswith(url + "&"))

        for url in (
            endpoint + "?client_id=test-client&logout_uri=" + origin,
            endpoint.replace("/logout", "/oauth2/authorize") + "?post_logout_redirect_uri=bad",
            "https://other.example/logout?post_logout_redirect_uri=bad",
            endpoint.replace("amazoncognito.com", "amazoncognito.com.other.example") + "?post_logout_redirect_uri=bad",
            origin + "/",
        ):
            self.assertEqual(re.sub(pattern, replacement, url), url)

    def test_wrong_account_does_not_send_command(self):
        """Prevent commands when credentials belong to a different account."""

        with patch("scripts.deploy_proxy.boto3.Session") as session:
            client = session.return_value.client.return_value
            client.get_caller_identity.return_value = {"Account": "999999999999"}

            with self.assertRaises(ValueError):
                deploy(self.config)

            client.send_command.assert_not_called()

    def test_updates_require_reviewed_fingerprint(self):
        """Require prior review and constrain backup identifiers before contacting AWS."""

        with self.assertRaises(ValueError):
            release_commands(self.config, "update")

        with self.assertRaises(ValueError):
            release_commands(self.config, "rollback", "a" * 64, "../../etc")

        self.assertEqual(len(release_commands(self.config, "status")), 1)
        self.assertEqual(len(release_commands(self.config, "update", "a" * 64)), 1)

    def test_https_verification_checks_content_and_redirect(self):
        """Check maintenance content and redirects without contacting the real domain."""

        with (
            patch("scripts.deploy_proxy.http.client.HTTPSConnection") as https,
            patch("scripts.deploy_proxy.http.client.HTTPConnection") as http,
        ):
            secure = Mock(status=503)
            secure.read.return_value = "El taller está en preparación.".encode()
            secure.getheader.return_value = "no-store"
            redirect = Mock(status=308)
            redirect.getheader.return_value = f"https://{self.config['domain']}/"
            https.return_value.getresponse.return_value = secure
            http.return_value.getresponse.return_value = redirect

            self.assertEqual(verify_https(self.config)["https"], "verified")
            https.assert_called_once_with(self.config["domain"], timeout=15)
            https.return_value.close.assert_called_once()
            http.return_value.close.assert_called_once()

            redirect.getheader.return_value = "https://unexpected.example/"

            with self.assertRaises(RuntimeError):
                verify_https(self.config)

            secure.status = 200

            with self.assertRaises(RuntimeError):
                verify_https(self.config)
