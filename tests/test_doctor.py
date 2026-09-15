"""Test diagnostics without contacting AWS or executing real care."""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app.config import load_settings
from scripts.doctor import Report, cloud_checks, diagnose


ROOT = Path(__file__).resolve().parents[1]


class DoctorTests(unittest.TestCase):
    """Verify account isolation, explicit inference consent, and safe reports."""

    def setUp(self):
        """Prepare fake identity and data for all remote checks."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        self.session = Mock()
        self.client = self.session.client.return_value
        self.session.get_partition_for_region.return_value = "aws"
        self.client.get_caller_identity.return_value = {
            "Account": self.settings.account_id
        }
        self.client.get_item.return_value = {
            "Item": {"pet_id": {"S": self.settings.team_id}}
        }
        self.client.converse.return_value = {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": "listo"}]}},
        }

    def test_offline_never_creates_session(self):
        """Validate example files without creating an AWS session."""

        with (
            patch("scripts.doctor.local_environment", return_value=True),
            patch("boto3.Session") as session,
        ):
            result = diagnose(ROOT / "scripts/config_defaults/app.json", offline=True)

            self.assertTrue(result["success"])
            session.assert_not_called()
            self.assertTrue(any(item["status"] == "SKIP" for item in result["checks"]))

    def test_wrong_account_stops_resource_checks(self):
        """Reject other accounts before reading data or requesting inference."""

        self.client.get_caller_identity.return_value = {"Account": "999999999999"}
        report = Report()

        cloud_checks(report, self.settings, None, self.session, inference=True)

        self.assertFalse(report.result()["success"])
        self.client.get_item.assert_not_called()
        self.client.converse.assert_not_called()
        self.assertEqual(self.session.client.call_count, 1)

    def test_inspection_only_and_explicit_inference(self):
        """Check inspection only and require authorization for direct model calls."""

        for inference in (False, True):
            with (
                self.subTest(inference=inference),
                patch("app.backend.PetBackend") as backend,
                patch("app.remote.RemoteAgent") as agent,
            ):
                self.client.converse.reset_mock()

                backend.return_value.invoke.return_value = {
                    "success": True,
                    "pet": {"pet_id": self.settings.team_id},
                }
                report = Report()

                cloud_checks(
                    report, self.settings, Mock(), self.session, inference=inference
                )

                self.assertTrue(report.result()["success"])
                backend.return_value.invoke.assert_called_once()
                self.assertEqual(
                    backend.return_value.invoke.call_args.args[:2], ("inspect", {})
                )
                agent.return_value.preflight.assert_called_once()
                agent.return_value.send.assert_not_called()
                self.assertEqual(self.client.converse.call_count, int(inference))

                if inference:
                    self.assertNotIn(
                        "toolConfig", self.client.converse.call_args.kwargs
                    )

    def test_changed_record_fails_without_retry(self):
        """Report divergent reads without automatically repeating invocations."""

        with patch("app.backend.PetBackend") as backend:
            backend.return_value.invoke.return_value = {
                "success": True,
                "pet": {"pet_id": "other"},
            }
            report = Report()

            cloud_checks(report, self.settings, None, self.session)

            self.assertFalse(report.result()["success"])
            backend.return_value.invoke.assert_called_once()

    def test_error_does_not_expose_exception_text(self):
        """Preserve failure types while omitting messages that could contain secrets."""

        report = Report()

        report.check("Prueba", Mock(side_effect=RuntimeError("secret-token")))

        self.assertFalse(report.result()["success"])
        self.assertNotIn("secret-token", str(report.result()))
        self.assertIn("RuntimeError", str(report.result()))


if __name__ == "__main__":
    unittest.main()
