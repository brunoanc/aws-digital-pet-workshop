"""Test capacity transport rejection paths without AWS or inference."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.capacity_aws import CapacityAWS
from scripts.capacity_execute import execute, main
from scripts.capacity_plan import build_plan


class CapacityAWSTests(unittest.TestCase):
    """Check fail-closed preflight and state comparisons before escalating load."""

    def setUp(self):
        """Prepare a transport with mocked AWS clients and local examples."""

        self.config = json.loads(Path("config/capacity.example.json").read_text())
        self.plan = build_plan(self.config)

        with patch("scripts.capacity_aws.boto3.Session"):
            self.transport = CapacityAWS(
                self.config, self.plan, {team: {} for team in self.plan["teams"]}
            )

        self.transport.clients = {
            service: Mock()
            for service in ("sts", "lambda", "iam", "dynamodb", "service-quotas")
        }

    def test_wrong_account_stops_before_quotas(self):
        """Reject another account before inspecting or invoking destinations."""

        self.transport.clients["sts"].get_caller_identity.return_value = {
            "Account": "999999999999"
        }

        with self.assertRaises(ValueError):
            self.transport.preflight()

        self.transport.clients["service-quotas"].get_service_quota.assert_not_called()

    def test_small_quota_stops_before_functions(self):
        """Reject insufficient concurrency without querying any function."""

        self.transport.clients["sts"].get_caller_identity.return_value = {
            "Account": self.config["account_id"]
        }
        self.transport.clients["service-quotas"].get_service_quota.return_value = {
            "Quota": {"Value": 10}
        }

        with self.assertRaises(ValueError):
            self.transport.preflight()

        self.transport.clients["lambda"].get_function_configuration.assert_not_called()

    def test_missing_deny_is_rejected(self):
        """Reject a pet role that lacks the explicit table mutation deny."""

        iam = self.transport.clients["iam"]
        iam.list_role_policies.return_value = {"PolicyNames": ["pet-data-and-logs"]}
        iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
        iam.get_role_policy.return_value = {"PolicyDocument": {"Statement": []}}

        with self.assertRaises(ValueError):
            self.transport.check_pet_policy("dp-capacity-team-81")

    def test_changed_code_stops_before_url(self):
        """Reject a changed function package before resolving its invocation URL."""

        team = "team-81"
        name = "dp-capacity-team-81"
        self.transport.expected[team] = {"pet_code_sha256": "reviewed"}
        self.transport.clients["lambda"].get_function_configuration.return_value = {
            "FunctionArn": f"arn:aws:lambda:us-east-1:{self.config['account_id']}:function:{name}",
            "State": "Active",
            "LastUpdateStatus": "Successful",
            "CodeSha256": "changed",
        }

        with self.assertRaises(ValueError):
            self.transport.check_team(team)

        self.transport.clients["lambda"].get_function_url_config.assert_not_called()

    def test_cli_defaults_to_local_plan(self):
        """Keep the default command from creating an AWS transport."""

        with (
            patch(
                "sys.argv", ["capacity", "--config", "config", "--expected", "expected"]
            ),
            patch(
                "scripts.capacity_execute.Path.read_text",
                side_effect=[json.dumps(self.config), "{}"],
            ),
            patch("scripts.capacity_execute.CapacityAWS") as transport,
            patch("builtins.print"),
        ):
            main()

        transport.assert_not_called()

    def test_empty_pet_stops_snapshot(self):
        """Refuse an unseeded capacity environment before inference."""

        self.transport.clients["dynamodb"].get_item.return_value = {}

        with self.assertRaises(ValueError):
            self.transport.snapshot()

    def test_changed_state_stops_after_batch(self):
        """Save a failed report and prevent later batches when state changes."""

        transport = Mock()
        transport.snapshot.side_effect = [{"state": 1}, {"state": 2}]
        transport.invoke.return_value = {"success": False}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"

            with self.assertRaises(ValueError):
                execute(
                    self.config,
                    {},
                    output,
                    transport_factory=Mock(return_value=transport),
                )

            self.assertEqual(transport.invoke.call_count, 2)
            self.assertEqual(
                json.loads((output / "result.json").read_text())["status"], "failed"
            )

    def test_preflight_failure_never_invokes(self):
        """Record a failed preflight without sending model requests."""

        transport = Mock()
        transport.preflight.side_effect = ValueError("Denied.")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                execute(
                    self.config,
                    {},
                    Path(directory) / "run",
                    transport_factory=Mock(return_value=transport),
                )

        transport.invoke.assert_not_called()
