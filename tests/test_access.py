"""Test identity authorization, expiry, and session changes without contacting AWS."""

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

from app.access import authorize, load_policy
from app.login_ui import require_team


class AccessTests(unittest.TestCase):
    """Verify that only registered identities receive their authorized team."""

    def setUp(self):
        """Build a rehearsal policy and fake claims already verified by OIDC."""

        self.policy = replace(
            load_policy(
                Path(__file__).resolve().parents[1] / "scripts/config_defaults/access.json"
            ),
            enabled=True,
            opens_at=100,
            closes_at=10000,
            members=MappingProxyType({"subject-1": "team-01", "subject-2": "team-02"}),
        )
        self.claims = {
            "iss": self.policy.issuer,
            "aud": self.policy.client_id,
            "token_use": "id",
            "sub": "subject-1",
            "iat": 500,
            "exp": 2000,
        }

    def test_team_comes_only_from_registry(self):
        """Ignore claimed team and email values and keep two users isolated."""

        self.assertEqual(
            authorize(self.policy, self.claims | {"team": "team-02"}, 1000), "team-01"
        )
        self.assertEqual(
            authorize(self.policy, self.claims | {"sub": "subject-2"}, 1000), "team-02"
        )

        with self.assertRaises(PermissionError):
            authorize(
                self.policy,
                self.claims | {"sub": "unknown", "email": "student@example.com"},
                1000,
            )

    def test_invalid_identity_and_expiration(self):
        """Reject tokens with a different issuer or client and invalid or expired timestamps."""

        for key, value in (
            ("iss", "https://other.example"),
            ("aud", "other"),
            ("token_use", "access"),
            ("sub", None),
            ("iat", 1001),
            ("exp", 1000),
            ("exp", True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(PermissionError):
                authorize(self.policy, self.claims | {key: value}, 1000)

        with self.assertRaises(PermissionError):
            authorize(replace(self.policy, max_session_seconds=300), self.claims, 1000)

    def test_four_hour_session(self):
        """Allow three hours and preserve token, session and event deadlines."""

        policy = replace(self.policy, max_session_seconds=14400, closes_at=20000)
        claims = self.claims | {"exp": 14900}
        self.assertEqual(authorize(policy, claims, 11300), "team-01")

        for candidate, token, now in (
            (policy, claims, 14900),
            (policy, claims | {"exp": 20000}, 14900),
            (policy, self.claims, 2000),
            (replace(policy, closes_at=10000), claims, 11300),
        ):
            with self.subTest(now=now), self.assertRaises(PermissionError):
                authorize(candidate, token, now)

    def test_event_and_revocation(self):
        """Close access when the event is disabled, its window expires, or the assignment is removed."""

        for policy in (
            replace(self.policy, enabled=False),
            replace(self.policy, closes_at=1000),
            replace(self.policy, opens_at=1001),
            replace(self.policy, members={}),
        ):
            with self.assertRaises(PermissionError):
                authorize(policy, self.claims, 1000)

    def test_anonymous_stops_before_policy(self):
        """Stop anonymous access before team resolution and clear previous session data."""

        with patch("app.login_ui.st") as ui, patch("app.login_ui.load_policy") as load:
            ui.user = SimpleNamespace(is_logged_in=False)
            ui.session_state = {"remote_history": ["private"]}
            ui.stop.side_effect = RuntimeError("stopped")

            with self.assertRaises(RuntimeError):
                require_team("unused")

            load.assert_not_called()
            self.assertEqual(ui.session_state, {})

    def test_identity_switch_clears_session(self):
        """Discard previous chat and pet data when the authorized identity changes."""

        with (
            patch("app.login_ui.st") as ui,
            patch("app.login_ui.load_policy", return_value=self.policy),
            patch("app.access.time.time", return_value=1000),
        ):
            ui.user.is_logged_in = True
            ui.user.keys.return_value = self.claims.keys()
            ui.user.__getitem__.side_effect = self.claims.__getitem__
            ui.session_state = {
                "remote_history": ["private"],
                "pet_snapshot": {"team": "team-02"},
            }

            self.assertEqual(require_team("unused"), "team-01")
            self.assertEqual(set(ui.session_state), {"authorized_identity"})

    def test_denial_clears_session(self):
        """Hide previous content and stop the page when permission is revoked."""

        with (
            patch("app.login_ui.st") as ui,
            patch(
                "app.login_ui.load_policy",
                return_value=replace(self.policy, enabled=False),
            ),
        ):
            ui.user.is_logged_in = True
            ui.session_state = {"remote_history": ["private"]}
            ui.stop.side_effect = RuntimeError("stopped")

            with self.assertRaises(RuntimeError):
                require_team("unused")

            self.assertEqual(ui.session_state, {})
