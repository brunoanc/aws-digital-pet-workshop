"""Test authenticated card reads without contacting AWS or sharing credentials between teams."""

from decimal import Decimal
from contextlib import nullcontext
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from boto3.dynamodb.types import TypeSerializer
from streamlit.testing.v1 import AppTest

from app.shared_card import load_targets, plain_numbers, read_card
from app.card_limits import CardReadLimitError


class SharedCardTests(unittest.TestCase):
    """Check fixed destinations and authorization before and after protected reads."""

    def setUp(self):
        """Prepare private-target fixtures and a typed DynamoDB pet response."""

        self.targets = load_targets("scripts/config_defaults/shared-card.json")
        slot = patch(
            "app.shared_card.card_read_slot", side_effect=lambda team: nullcontext()
        )

        slot.start()
        self.addCleanup(slot.stop)

        for name, value in (
            ("load_policy", Mock(issuer="test-issuer")),
            ("authorize", "team-01"),
            ("load_targets", self.targets),
        ):
            mocked = patch("app.shared_ui." + name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

        self.pet = {
            "pet_id": "team-01",
            "name": "Draco",
            "species": "Dragón",
            "health": 87,
            "energy": 63,
            "fullness": 50,
            "happiness": 79,
            "experience": 20,
            "version": 4,
            "inventory": {"healthy_meal": 1, "cake": 1},
        }

    def test_shared_screen_displays_pet_values(self):
        """Display the authenticated pet statistics and inventory."""

        self.pet["inventory"] = {"healthy_meal": 3, "cake": 2}
        snapshot = {"pet": self.pet, "read_at": "12:00:00 UTC"}

        with (
            patch("app.shared_ui.read_card", return_value=("team-01", snapshot)),
            patch("app.shared_ui.st.user", {}),
        ):
            app = AppTest.from_string(
                "import streamlit as st\n"
                "from app.shared_ui import render_authenticated_card\n"
                'with st.container(border=True, key="pet_card"):\n'
                '    render_authenticated_card("access", "targets")\n'
            ).run()

        self.assertFalse(app.exception)
        self.assertCountEqual(
            [metric.value.split()[0] for metric in app.metric],
            ["87/100", "50/100", "63/100", "79/100", "20", "3", "2"],
        )

    def test_unassigned_identity_never_creates_aws_session(self):
        """Reject unauthorized identities before resolving any AWS client."""

        with (
            patch("app.shared_card.load_policy"),
            patch("app.shared_card.authorize", side_effect=PermissionError("Denied.")),
            patch("app.shared_card.boto3.Session") as session,
        ):
            with self.assertRaises(PermissionError):
                read_card("access", "targets", {})

            session.assert_not_called()

    def test_reruns_keep_card_and_refresh_after_chat_or_button(self):
        """Read once on load and again only for an explicit refresh or chat."""

        snapshots = [
            ("team-01", {"pet": dict(self.pet, energy=energy), "read_at": str(energy)})
            for energy in (63, 70, 80)
        ]
        with (
            patch("app.shared_ui.read_card", side_effect=snapshots) as read,
            patch("app.shared_ui.st.user", {"sub": "user-01"}),
        ):
            app = AppTest.from_string(
                "from app.shared_ui import render_authenticated_card\n"
                'render_authenticated_card("access", "targets")\n'
            ).run()
            for _ in range(3):
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.metric), 7)
                self.assertEqual(len(app.info), 0)
            self.assertEqual(read.call_count, 1)

            app.button[0].click().run()
            self.assertEqual(read.call_count, 2)
            self.assertIn("70/100", [metric.value for metric in app.metric])

            app.session_state["card_refresh"] = True
            app.run()
            self.assertEqual(read.call_count, 3)
            self.assertIn("80/100", [metric.value for metric in app.metric])
            app.run()
            self.assertEqual(read.call_count, 3)

    def test_failed_refresh_keeps_last_card_and_marks_it_stale(self):
        """Keep the last successful read when a refresh is throttled or fails."""

        snapshot = {"pet": self.pet, "read_at": "12:00:00 UTC"}
        with (
            patch("app.shared_ui.read_card", side_effect=[
                ("team-01", snapshot), CardReadLimitError("Espera."),
                RuntimeError("AWS unavailable"), ("team-01", snapshot),
            ]) as read,
            patch("app.shared_ui.st.user", {"sub": "user-01"}),
        ):
            app = AppTest.from_string(
                "from app.shared_ui import render_authenticated_card\n"
                'render_authenticated_card("access", "targets")\n'
            ).run()
            for _ in range(2):
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.metric), 7)
                self.assertEqual(len(app.info), 1)
                self.assertIn("sin actualizar", app.caption[0].value)
                calls = read.call_count
                app.run()
                self.assertEqual(read.call_count, calls)
            app.button[0].click().run()
            self.assertEqual(len(app.info), 0)
            self.assertNotIn("sin actualizar", app.caption[0].value)

    def test_cached_card_is_hidden_after_revocation(self):
        """Recheck access even when the rerun does not need an AWS read."""

        with (
            patch("app.shared_ui.read_card", return_value=(
                "team-01", {"pet": self.pet, "read_at": "12:00:00 UTC"},
            )) as read,
            patch("app.shared_ui.st.user", {"sub": "user-01"}),
        ):
            app = AppTest.from_string(
                "from app.shared_ui import render_authenticated_card\n"
                'render_authenticated_card("access", "targets")\n'
            ).run()
            with patch("app.shared_ui.authorize", side_effect=PermissionError("Revoked.")):
                app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 0)
            self.assertEqual(app.warning[0].value, "Revoked.")
            self.assertNotIn("shared_card", app.session_state)
            self.assertEqual(read.call_count, 1)

    def test_identity_or_target_change_discards_cached_card(self):
        """Never reuse another identity's or destination's snapshot."""

        for change in ("identity", "team", "target"):
            with (
                self.subTest(change=change),
                patch("app.shared_ui.read_card", side_effect=[
                    ("team-01", {"pet": self.pet, "read_at": "12:00:00 UTC"}),
                    CardReadLimitError("Espera."),
                ]) as read,
                patch("app.shared_ui.st.user", {"sub": "user-01"}),
            ):
                app = AppTest.from_string(
                    "from app.shared_ui import render_authenticated_card\n"
                    'render_authenticated_card("access", "targets")\n'
                ).run()
                targets = json.loads(json.dumps(self.targets))
                if change == "identity":
                    update = patch("app.shared_ui.st.user", {"sub": "user-02"})
                elif change == "team":
                    targets["teams"]["team-02"] = targets["teams"]["team-01"]
                    update = patch("app.shared_ui.authorize", return_value="team-02")
                else:
                    targets["teams"]["team-01"]["table_name"] = "other-table"
                    update = nullcontext()
                with update, patch("app.shared_ui.load_targets", return_value=targets):
                    app.run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.metric), 0)
                self.assertEqual(read.call_count, 2)

    def test_throttled_read_never_calls_aws(self):
        """Reject a limited read before creating any AWS session."""

        with (
            patch("app.shared_card.load_policy"),
            patch("app.shared_card.load_targets", return_value=self.targets),
            patch("app.shared_card.authorize", return_value="team-01"),
            patch(
                "app.shared_card.card_read_slot",
                side_effect=CardReadLimitError("Espera."),
            ),
            patch("app.shared_card.boto3.Session") as session,
        ):
            with self.assertRaises(CardReadLimitError):
                read_card("access", "targets", {})

            session.assert_not_called()

    def test_throttled_card_does_not_stop_chat_rendering(self):
        """Show a limit notice without stale metrics or stopping the rest of the page."""

        with (
            patch(
                "app.shared_ui.read_card", side_effect=CardReadLimitError("Espera.")
            ),
            patch("app.shared_ui.st.user", {}),
        ):
            app = AppTest.from_string(
                "import streamlit as st\n"
                "from app.shared_ui import render_authenticated_card\n"
                'render_authenticated_card("access", "targets")\n'
                'st.chat_input("Envía un mensaje...")\n'
            ).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(app.info[0].value, "Espera.")
        self.assertEqual(len(app.chat_input), 1)

    def test_scoped_read_and_revocation(self):
        """Use only the authorized team destination and discard results after revocation."""

        host, scoped = Mock(), Mock()
        sts = host.client.return_value
        sts.get_caller_identity.return_value = {"Account": self.targets["account_id"]}
        sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "fake",
                "SecretAccessKey": "fake",
                "SessionToken": "fake",
            }
        }
        scoped.client.return_value.get_item.return_value = {
            "Item": {
                key: TypeSerializer().serialize(value)
                for key, value in self.pet.items()
            }
        }

        with (
            patch("app.shared_card.load_policy"),
            patch("app.shared_card.load_targets", return_value=self.targets),
            patch("app.shared_card.authorize", return_value="team-01") as auth,
            patch(
                "app.shared_card.boto3.Session",
                side_effect=[host, scoped, host, scoped],
            ) as sessions,
        ):
            team, snapshot = read_card("access", "targets", {"team": "team-02"})

            self.assertEqual(team, "team-01")
            self.assertEqual(snapshot["pet"], self.pet)
            self.assertIs(type(snapshot["pet"]["health"]), int)
            self.assertEqual(
                sts.assume_role.call_args.kwargs["RoleArn"],
                self.targets["teams"]["team-01"]["role_arn"],
            )
            self.assertEqual(
                scoped.client.return_value.get_item.call_args.kwargs["Key"],
                {"pet_id": {"S": "team-01"}},
            )
            self.assertEqual(sessions.call_count, 2)

            auth.side_effect = [
                "team-01",
                "team-01",
                "team-01",
                "team-01",
                PermissionError("Revoked."),
            ]

            with self.assertRaises(PermissionError):
                read_card("access", "targets", {})

    def test_wrong_host_account_never_assumes_role(self):
        """Refuse scoped credentials when the host belongs to another AWS account."""

        with (
            patch("app.shared_card.load_policy"),
            patch("app.shared_card.load_targets", return_value=self.targets),
            patch("app.shared_card.authorize", return_value="team-01"),
            patch("app.shared_card.boto3.Session") as session,
        ):
            session.return_value.client.return_value.get_caller_identity.return_value = {
                "Account": "999999999999"
            }

            with self.assertRaises(ValueError):
                read_card("access", "targets", {})

            session.return_value.client.return_value.assume_role.assert_not_called()

    def test_configuration_rejects_cross_account_roles(self):
        """Reject mismatched role accounts and preserve fractional values for metric validation."""

        bad = json.loads(Path("scripts/config_defaults/shared-card.json").read_text())
        bad["teams"]["team-01"]["role_arn"] = "arn:aws:iam::999999999999:role/other"

        with patch("app.shared_card.Path.read_text", return_value=json.dumps(bad)):
            with self.assertRaises(ValueError):
                load_targets("unused")

        self.assertEqual(plain_numbers(Decimal("2")), 2)
        self.assertIsInstance(plain_numbers(Decimal("2.5")), Decimal)
