"""Check saved Function URLs without trusting browser storage for access."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from app.browser_url import restore_url, url_scope


class BrowserUrlTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            account_id="444455556666", region="us-east-1", team_id="team-00"
        )
        self.remote = SimpleNamespace(
            function_name="dp-workshop-team-00-agent",
            function_url="https://" + "a" * 32 + ".lambda-url.us-east-1.on.aws/",
        )
        self.scope = url_scope(self.settings, self.remote)
        self.saved = {"scope": self.scope, "url": self.remote.function_url}

    def test_scope_separates_targets(self):
        for field in ("account_id", "region", "team_id"):
            changed = SimpleNamespace(**vars(self.settings))
            setattr(changed, field, "different")
            self.assertNotEqual(self.scope, url_scope(changed, self.remote))
        changed = SimpleNamespace(**vars(self.remote))
        changed.function_name = "different"
        self.assertNotEqual(self.scope, url_scope(self.settings, changed))

    def test_restores_only_after_fresh_validation(self):
        state = {}
        connect = Mock(return_value=self.remote.function_url)
        restore_url(self.scope, self.remote, self.saved, state, connect)
        self.assertEqual(state["connected_url"], self.remote.function_url)
        restore_url(self.scope, self.remote, self.saved, state, connect)
        connect.assert_called_once_with(self.remote.function_url)

    def test_rejects_other_teams_and_untrusted_values(self):
        for saved in (None, "url", {}, {**self.saved, "scope": "another-team"},
                      {**self.saved, "url": "https://example.com"},
                      {**self.saved, "url": [self.remote.function_url]}):
            with self.subTest(saved=saved):
                state, connect = {}, Mock()
                restore_url(self.scope, self.remote, saved, state, connect)
                connect.assert_not_called()
                self.assertNotIn("connected_url", state)

    def test_failed_validation_does_not_connect_or_retry(self):
        state = {}
        connect = Mock(side_effect=PermissionError("Session expired"))
        for _ in range(2):
            restore_url(self.scope, self.remote, self.saved, state, connect)
        connect.assert_called_once()
        self.assertNotIn("connected_url", state)

    def test_empty_storage_does_not_block_manual_connection(self):
        state, connect = {}, Mock()
        restore_url(self.scope, self.remote, {**self.saved, "url": None}, state, connect)
        connect.assert_not_called()
        self.assertTrue(state["saved_url_attempted"])

    def test_unexpected_validation_result_stays_disconnected(self):
        state = {}
        restore_url(self.scope, self.remote, self.saved, state, Mock(return_value="other"))
        self.assertNotIn("connected_url", state)
