"""Validate species, text escaping, and action evidence before animation."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from boto3.dynamodb.types import TypeSerializer

from app.config import load_settings
from app.scene import render_scene, scene_html, verified_action
from app.species import species_art, species_key


ROOT = Path(__file__).resolve().parents[1]


class SceneTests(unittest.TestCase):
    """Check culture-independent selection and rejection of fabricated activity."""

    def setUp(self):
        """Prepare a fake operation and resulting state without contacting AWS."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        self.pet = json.loads((ROOT / "fixtures/starter.json").read_text()) | {
            "pet_id": "team-01",
            "name": "Draco",
        }
        self.result = {"success": True, "message": "Listo", "pet": self.pet}
        self.event = {
            "action": "custom",
            "parameters": {},
            "operation_id": "operation-1",
            "result": self.result,
        }

    def test_unicode_catalog_without_aliases(self):
        """Accept Unicode spelling variants but reject legacy names and paths."""

        for value in ("DRAGÓN", "draGon", "  Drago\u0301n  ", "ＤＲＡＧＯＮ"):
            self.assertEqual(species_key(value), "dragon")

        for value in ("Dragón de la nube", "cat", "../dragon", "<script>", None):
            self.assertIsNone(species_key(value))

        for value in ("GATO", "zOrRo", "AJOLOTE"):
            self.assertEqual(species_key(value), value.casefold())

        self.assertEqual(
            len(
                {species_art(value) for value in ("Dragón", "Gato", "Zorro", "Ajolote")}
            ),
            4,
        )

    def test_names_are_text_not_markup(self):
        """Escape names and species containing tags or template markers."""

        self.pet.update(
            name="<script>alert(1)</script>{{ART}}",
            species='"><img src=x onerror=alert(1)>',
        )

        html = scene_html(self.pet)

        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("{{ART}}", html)
        self.assertIn("prefers-reduced-motion", html)

    def test_receipt_must_match_state_and_action(self):
        """Animate only operations whose fingerprint, result, and state match DynamoDB."""

        fingerprint = hashlib.sha256(
            json.dumps({"action": "custom", "parameters": {}}, sort_keys=True).encode()
        ).hexdigest()
        receipt = {"fingerprint": fingerprint, "result": self.result}
        encode = TypeSerializer().serialize

        with patch("app.scene.boto3.Session") as session:
            client = session.return_value.client.return_value
            client.get_caller_identity.return_value = {
                "Account": self.settings.account_id
            }
            session.return_value.get_partition_for_region.return_value = "aws"
            client.get_item.return_value = {
                "Item": {key: encode(value) for key, value in receipt.items()}
            }

            self.assertEqual(
                verified_action(self.settings, self.event, self.pet),
                {"action": "custom", "operation_id": "operation-1"},
            )
            self.assertEqual(
                client.get_item.call_args.kwargs["Key"],
                {"pet_id": {"S": "_op#operation-1"}},
            )

            receipt["fingerprint"] = "wrong"
            client.get_item.return_value = {
                "Item": {key: encode(value) for key, value in receipt.items()}
            }

            self.assertIsNone(verified_action(self.settings, self.event, self.pet))

    def test_rejections_and_stale_state_never_read_receipt(self):
        """Ignore rejections, inspections, and divergent state without additional calls."""

        for event in (
            dict(self.event, action="inspect"),
            dict(self.event, result={"success": False}),
            dict(self.event, operation_id="bad/id"),
        ):
            with patch("app.scene.boto3.Session") as session:
                self.assertIsNone(verified_action(self.settings, event, self.pet))
                session.assert_not_called()

        self.assertIsNone(
            verified_action(self.settings, self.event, dict(self.pet, version=999))
        )

    def test_events_are_consumed_once_and_never_replayed_on_refresh(self):
        """Consume each operation once and discard effects for stale reads."""

        state = {"scene_pending": [self.event]}
        confirmed = {"action": "custom", "operation_id": "operation-1"}

        with (
            patch("app.scene.st.session_state", state),
            patch("app.scene.st.iframe") as frame,
            patch("app.scene.verified_action", return_value=confirmed) as verify,
        ):
            render_scene(self.settings, {"pet": self.pet}, True)

            self.assertIn('data-event="operation-1"', frame.call_args.args[0])

            state["scene_pending"] = [self.event]

            render_scene(self.settings, {"pet": self.pet}, True)

            self.assertIn('data-event=""', frame.call_args.args[0])
            verify.assert_called_once()

            state["scene_pending"] = [dict(self.event, operation_id="second")]

            render_scene(self.settings, {"pet": self.pet}, False)

            verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
