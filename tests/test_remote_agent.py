"""Test remote agent transport, isolation, and presentation with simulated AWS."""

from copy import deepcopy
from dataclasses import asdict
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from app.config import load_settings
from app.remote import RemoteAgent, load_remote_settings


ROOT = Path(__file__).resolve().parents[1]


class RemoteAgentTests(unittest.TestCase):
    """Ensure browsers cannot choose targets or resend responses as instructions."""

    def setUp(self):
        """Prepare an active simulated Lambda and an empty inspection response."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        self.remote = load_remote_settings(ROOT / "scripts/config_defaults/remote-agent.json")
        self.session = Mock()
        self.session.get_partition_for_region.return_value = "aws"
        self.client = self.session.client.return_value
        self.client.get_caller_identity.return_value = {
            "Account": self.settings.account_id
        }
        self.agent = RemoteAgent(self.settings, self.remote, self.session)
        self.function = {
            "FunctionArn": self.agent.arn,
            "State": "Active",
            "LastUpdateStatus": "Successful",
            "Timeout": 90,
            "Environment": {
                "Variables": {"APP_SETTINGS": json.dumps(asdict(self.settings))}
            },
        }
        self.client.get_function_configuration.return_value = self.function
        self.result = {
            "success": True,
            "message": "Hola.",
            "registered_tools": [],
            "activity": [],
        }

    def response(self, result):
        """Return a fresh response body to test stream reading and closure."""

        stream = io.BytesIO(json.dumps(result).encode())
        self.client.invoke.return_value = {"StatusCode": 200, "Payload": stream}

        return stream

    def test_only_message_is_sent_to_fixed_arn(self):
        """Send only the question to the configured function without card data or history."""

        stream = self.response(self.result)

        self.assertEqual(self.agent.send("Hola"), self.result)

        call = self.client.invoke.call_args.kwargs

        self.assertEqual(call["FunctionName"], self.agent.arn)
        self.assertEqual(json.loads(call["Payload"]), {"message": "Hola"})
        self.assertTrue(stream.closed)
        self.assertEqual(self.agent.client_config.retries["total_max_attempts"], 1)

    def test_wrong_account_or_team_never_invokes(self):
        """Reject other accounts or team configurations before running remote code."""

        self.client.get_caller_identity.return_value = {"Account": "999999999999"}

        with self.assertRaises(ValueError):
            self.agent.send("Hola")

        self.client.invoke.assert_not_called()

        self.client.get_caller_identity.return_value = {
            "Account": self.settings.account_id
        }
        runtime = asdict(self.settings)
        runtime["team_id"] = "team-02"
        self.function["Environment"]["Variables"]["APP_SETTINGS"] = json.dumps(runtime)

        with self.assertRaises(ValueError):
            self.agent.send("Hola")

        self.client.invoke.assert_not_called()

    def test_timeout_never_retries(self):
        """Preserve transport failures as unknown outcomes without a second invocation."""

        self.client.invoke.side_effect = TimeoutError("private")

        with self.assertRaises(TimeoutError):
            self.agent.send("Descansa")

        self.client.invoke.assert_called_once()

    def test_rejects_large_and_cross_team_responses(self):
        """Close oversized bodies and reject other teams' results or unknown tools."""

        for result in (
            dict(self.result, message="x" * self.remote.max_response_bytes),
            dict(self.result, registered_tools=["shell"]),
            dict(
                self.result,
                registered_tools=["inspect_pet"],
                activity=[
                    {
                        "tool": "inspect_pet",
                        "result": {"success": True, "pet": {"pet_id": "team-02"}},
                    }
                ],
            ),
        ):
            stream = self.response(result)

            with self.assertRaises(ValueError):
                self.agent.send("Hola")

            self.assertTrue(stream.closed)




if __name__ == "__main__":
    unittest.main()
