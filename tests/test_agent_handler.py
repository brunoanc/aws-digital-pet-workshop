"""Test the Lambda contract and code-defined agent tool registration."""

from dataclasses import asdict
import json
import runpy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import boto3

from agent_lambda.handler import handle, lambda_handler
from app.agent import PetConversation
from app.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


class AgentHandlerTests(unittest.TestCase):
    """Validate isolated requests without invoking real services."""

    def setUp(self):
        """Prepare public configuration, remaining time, and simulated services."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        environment = patch.dict(
            "os.environ", {"APP_SETTINGS": json.dumps(asdict(self.settings))}
        )

        environment.start()
        self.addCleanup(environment.stop)

        self.context = Mock(aws_request_id="test-request")
        self.context.get_remaining_time_in_millis.return_value = 90000

    def test_invalid_input_never_creates_clients(self):
        """Reject history, extra targets, and invalid messages before accessing AWS."""

        with patch("agent_lambda.handler.boto3.Session") as session:
            for event in (
                None,
                {},
                {"message": ""},
                {"message": 1},
                {"message": "hola", "history": []},
                {"message": "hola", "team_id": "another"},
                {"message": "x" * (self.settings.max_input_chars + 1)},
            ):
                self.assertEqual(
                    handle(event, self.context)["reason"], "INVALID_REQUEST"
                )

            session.assert_not_called()

    def test_insufficient_time_never_creates_clients(self):
        """Prevent queries when insufficient execution time remains."""

        self.context.get_remaining_time_in_millis.return_value = 15000

        with patch("agent_lambda.handler.boto3.Session") as session:
            self.assertEqual(
                handle({"message": "hola"}, self.context)["reason"], "TIME_LIMIT"
            )
            session.assert_not_called()

    def test_fixed_destination_and_fresh_conversations(self):
        """Use the execution role and create a fresh conversation for each request."""

        with (
            patch("agent_lambda.handler.boto3.Session") as session,
            patch("agent_lambda.handler.PetBackend") as backend,
            patch("agent_lambda.handler.PetConversation") as conversation,
            patch("agent_lambda.agent_builder.create_agent", create=True),
        ):
            session.return_value.get_partition_for_region.return_value = "aws"
            conversation.return_value.failed = False
            conversation.return_value.send.return_value = "Hola."
            conversation.return_value.gateway.enabled = frozenset()
            conversation.return_value.gateway.events = []

            for _ in range(2):
                result = handle({"message": "hola"}, self.context)

                self.assertEqual(
                    result,
                    {
                        "success": True,
                        "message": "Hola.",
                        "registered_tools": [],
                        "activity": [],
                    },
                )

            self.assertEqual(conversation.call_count, 2)
            session.assert_called_with(region_name="us-east-1")
            backend.return_value.preflight.assert_called()
            session.return_value.client.assert_not_called()
            self.assertEqual(conversation.call_args.args[3], ["inspect_pet"])

    def test_errors_do_not_expose_internal_details(self):
        """Hide exception details and log only execution metadata."""

        with (
            patch(
                "agent_lambda.handler.handle",
                side_effect=RuntimeError("sensitive detail"),
            ),
            patch("builtins.print") as output,
        ):
            result = lambda_handler({"message": "hola"}, self.context)

            self.assertEqual(result["reason"], "AGENT_ERROR")
            self.assertNotIn(
                "sensitive detail", json.dumps(result) + str(output.call_args_list)
            )

            diagnostic = json.loads(output.call_args_list[0].args[0])

            self.assertEqual(diagnostic["event"], "TEAM_AGENT_EXCEPTION")
            self.assertEqual(diagnostic["exception_type"], "RuntimeError")
            self.assertTrue(diagnostic["frames"])

    def test_aws_error_diagnostic_omits_service_message(self):
        """Record AWS error metadata without logging the service message."""

        from botocore.exceptions import ClientError

        error = ClientError(
            {
                "Error": {
                    "Code": "TooManyRequestsException",
                    "Message": "private detail",
                },
                "ResponseMetadata": {"RequestId": "aws-request"},
            },
            "GetFunctionConfiguration",
        )

        with (
            patch("agent_lambda.handler.handle", side_effect=error),
            patch("builtins.print") as output,
        ):
            result = lambda_handler({"message": "hola"}, self.context)
            diagnostic = json.loads(output.call_args_list[0].args[0])

            self.assertEqual(diagnostic["aws_code"], "TooManyRequestsException")
            self.assertEqual(diagnostic["aws_request_id"], "aws-request")
            self.assertEqual(diagnostic["aws_operation"], "GetFunctionConfiguration")
            self.assertNotIn(
                "private detail", json.dumps(result) + str(output.call_args_list)
            )

    def test_empty_student_file_is_not_ready(self):
        """Accept an empty student file and return the starter notice without inference."""

        with (
            patch("agent_lambda.handler.PetBackend"),
            patch("agent_lambda.handler.boto3.Session"),
            patch("builtins.print"),
        ):
            result = lambda_handler({"message": "hola"}, self.context)

            self.assertEqual(result["reason"], "AGENT_NOT_READY")

    def test_factory_registration_controls_capabilities(self):
        """Derive capabilities from the created agent and reject unauthorized tools."""

        backend = Mock()
        backend.session = boto3.Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            region_name="us-east-1",
        )

        for filename, names in (
            ("01_conversation.py", []),
            ("02_prompt.py", []),
            ("03_inspect.py", ["inspect_pet"]),
        ):
            factory = runpy.run_path(str(ROOT / "checkpoints" / filename))[
                "create_agent"
            ]
            conversation = PetConversation(
                self.settings,
                backend,
                "Sé amable.",
                ["inspect_pet"],
                agent_factory=factory,
            )

            self.assertEqual(conversation.gateway.enabled, frozenset(names))

            if filename == "01_conversation.py":
                self.assertIsNone(conversation.agent.system_prompt)
            else:
                self.assertIn("Eres el cuidador", conversation.agent.system_prompt)
                self.assertNotIn(
                    "Personalidad solicitada", conversation.agent.system_prompt
                )

        for filename in ("04_care.py", "05_custom.py"):
            with self.assertRaises(ValueError):
                PetConversation(
                    self.settings,
                    backend,
                    "Sé amable.",
                    ["inspect_pet"],
                    agent_factory=runpy.run_path(str(ROOT / "checkpoints" / filename))[
                        "create_agent"
                    ],
                )


if __name__ == "__main__":
    unittest.main()
