"""Test authenticated transport, fixed targets, and HTTP events without AWS calls."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from botocore.credentials import Credentials

from agent_lambda.handler import lambda_handler
from app.config import load_settings
from app.function_url import post_signed, validate_url
from app.remote import RemoteAgent, RemoteSettings


ROOT = Path(__file__).resolve().parents[1]
URL = "https://" + "a" * 32 + ".lambda-url.us-east-1.on.aws/"


class FunctionURLTests(unittest.TestCase):
    """Verify that pasted URLs cannot authorize other targets or trigger retries."""

    def setUp(self):
        """Configure a simulated team function and fake signing credentials."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        self.remote = RemoteSettings("dp-rehearsal-team-01-agent", 100, 65536, URL)
        self.session = Mock()
        self.session.get_partition_for_region.return_value = "aws"
        self.session.get_credentials.return_value = Credentials(
            "testing", "secret", "token"
        )
        self.client = self.session.client.return_value
        self.client.get_caller_identity.return_value = {
            "Account": self.settings.account_id
        }
        self.agent = RemoteAgent(self.settings, self.remote, self.session)
        self.client.get_function_configuration.return_value = {
            "FunctionArn": self.agent.arn,
            "State": "Active",
            "LastUpdateStatus": "Successful",
            "Timeout": 90,
            "Environment": {
                "Variables": {"APP_SETTINGS": json.dumps(asdict(self.settings))}
            },
        }
        self.client.get_function_url_config.return_value = {
            "FunctionArn": self.agent.arn,
            "FunctionUrl": URL,
            "AuthType": "AWS_IAM",
        }

    def test_connect_checks_destination_without_invocation(self):
        """Connect only the team's exact endpoint without invoking Lambda or HTTP."""

        with patch("app.remote.post_signed") as post:
            self.assertEqual(self.agent.connect(URL), URL)
            self.agent.client.invoke.assert_not_called()
            post.assert_not_called()

            for url in (
                "https://example.com/",
                URL + "?x=1",
                URL.replace("a" * 32, "b" * 32),
            ):
                with self.assertRaises(ValueError):
                    self.agent.connect(url)

    def test_public_or_reassigned_endpoint_is_rejected(self):
        """Reject URLs without IAM authentication or no longer assigned to the registered function."""

        for change in (
            {"AuthType": "NONE"},
            {"FunctionArn": "other"},
            {"FunctionUrl": URL.replace("a" * 32, "b" * 32)},
        ):
            with patch("app.remote.post_signed") as post:
                self.client.get_function_url_config.return_value = {
                    "FunctionArn": self.agent.arn,
                    "FunctionUrl": URL,
                    "AuthType": "AWS_IAM",
                } | change

                with self.assertRaises(ValueError):
                    self.agent.send("Hola")

                post.assert_not_called()

    def test_signed_transport_has_no_redirects_or_retries(self):
        """Sign messages, reject redirects, and close connections for every outcome."""

        for status, body in ((200, b"{}"), (302, b""), (403, b""), (200, b"x" * 65)):
            with patch("app.function_url.http.client.HTTPSConnection") as https:
                connection = https.return_value
                response = connection.getresponse.return_value
                response.status = status
                response.read.return_value = body

                if status == 200 and len(body) <= 64:
                    self.assertEqual(
                        post_signed(URL, "Hola", self.session, "us-east-1", 100, 64),
                        body,
                    )
                else:
                    with self.assertRaises(ValueError):
                        post_signed(URL, "Hola", self.session, "us-east-1", 100, 64)

                connection.request.assert_called_once()
                self.assertEqual(connection.request.call_args.args, ("POST", "/"))

                headers = connection.request.call_args.kwargs["headers"]

                self.assertIn("Authorization", headers)
                self.assertIn("X-Amz-Security-Token", headers)
                self.assertEqual(
                    json.loads(connection.request.call_args.kwargs["body"]),
                    {"message": "Hola"},
                )
                connection.close.assert_called_once()

    def test_bad_urls_never_open_connections(self):
        """Block arbitrary hosts, ports, user information, fragments, and other regions."""

        for url in (
            "http://127.0.0.1/",
            URL + "#x",
            URL + "?x=1",
            URL.replace("https://", "https://user@"),
            URL.replace("on.aws/", "on.aws:443/"),
            URL.replace("us-east-1", "us-west-2"),
        ):
            with self.assertRaises(ValueError):
                validate_url(url, "us-east-1")

    def test_url_responses_use_existing_validation(self):
        """Reuse result validation without sending history or invoking through the SDK."""

        result = {
            "success": True,
            "message": "Hola",
            "registered_tools": [],
            "activity": [],
        }

        with patch(
            "app.remote.post_signed", return_value=json.dumps(result).encode()
        ) as post:
            self.assertEqual(self.agent.send("Hola"), result)
            post.assert_called_once()
            self.client.invoke.assert_not_called()

    def test_http_adapter_preserves_direct_contract(self):
        """Pass messages to the existing handler and return HTTP JSON without CORS headers."""

        result = {"success": True, "message": "Hola"}
        event = {
            "version": "2.0",
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/",
            "body": json.dumps({"message": "Hola"}),
            "isBase64Encoded": False,
        }

        with (
            patch("agent_lambda.handler.handle", return_value=result) as handle,
            patch("builtins.print"),
        ):
            response = lambda_handler(event, Mock(aws_request_id="request"))

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(json.loads(response["body"]), result)
            handle.assert_called_once()
            self.assertEqual(handle.call_args.args[0], {"message": "Hola"})
            self.assertEqual(response["headers"]["cache-control"], "no-store")

    def test_bad_http_does_not_run_agent(self):
        """Reject unsupported methods, bodies, and paths before running the agent."""

        event = {
            "version": "2.0",
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/",
            "body": "{}",
        }

        for change in (
            {"body": "broken"},
            {"body": "x" * 131073},
            {"rawPath": "/other"},
            {"isBase64Encoded": True},
            {"requestContext": {"http": {"method": "GET"}}},
        ):
            with patch("agent_lambda.handler.handle") as handle:
                self.assertEqual(
                    lambda_handler(event | change, Mock())["statusCode"], 400
                )
                handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
