"""Check shared-region rendering and private configuration safeguards."""

import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.configure_environment import ROOT, render, write_new


class EnvironmentTests(unittest.TestCase):
    """Verify common settings without credentials or AWS resources."""

    def setUp(self):
        """Load the public input examples."""

        self.env = json.loads((ROOT / "config/environment.example.json").read_text())
        self.teams = json.loads((ROOT / "config/teams.example.json").read_text())

    def render(self):
        """Generate files for the test environment."""

        return render(self.env, self.teams, ROOT / ".local/generated")

    def test_region_and_zone(self):
        """Apply the selected region across generated templates."""

        self.env.update(region="us-west-2", availability_zone="us-west-2b")

        files = self.render()

        self.assertIn('"region": "us-west-2"', files["team-01-runtime.json"])
        self.assertIn('"us-west-2b"', files["ui-host.tfvars.json"])
        self.assertIn("pets.tfvars.json", files)
        self.assertIn("team-01-agent.tfvars.json", files)
        self.assertTrue(all("us-east-1" not in content for content in files.values()))

    def test_invalid_region_or_zone(self):
        """Reject unsupported regions and mismatched zones."""

        for region, zone in (("invalid", "invalid-a"), ("us-east-1", "us-west-2a")):
            with self.assertRaises(ValueError):
                self.env.update(region=region, availability_zone=zone)
                self.render()

    def test_shared_names_and_memberships(self):
        """Keep resource names and assignments consistent across consumers."""

        self.teams["team-01"].update(resource_name="custom-pet", identity_center_user_ids=["user-1"], cognito_subjects=["subject-1"])

        files = {name: json.loads(content) for name, content in self.render().items()}

        self.assertEqual(files["pets.tfvars.json"]["workload"]["teams"]["team-01"], "custom-pet")
        self.assertEqual(files["team-01-runtime.json"]["function_name"], "custom-pet")

        agent = files["team-01-agent.tfvars.json"]["agent"]

        self.assertEqual(agent["function_name"], "custom-pet-agent")
        self.assertEqual(agent["runtime_config_path"], str(ROOT / ".local/generated/team-01-runtime.json"))
        self.assertEqual(files["control.tfvars.json"]["participant_memberships"], {"user-1": "workshop/team-01"})
        self.assertFalse(agent["function_url_enabled"])
        self.assertNotIn("access.json", files)
        self.assertNotIn("shared-card.json", files)
        self.assertTrue(all("backend" not in name and "secret" not in name for name in files))

    def test_selected_assignment_teams(self):
        """Limit pilot assignments to known teams and retain the global switch."""

        self.env["identity_center"].update(assignments_enabled=False, assignment_teams=["team-01"])
        control = json.loads(self.render()["control.tfvars.json"])
        environment = control["participant_access"]["environments"][self.env["name"]]
        self.assertEqual(environment["assignment_teams"], ["team-01"])
        self.assertFalse(environment["assignments_enabled"])

        for selected in (None, "team-01", ["team-99"], ["team-01", "team-01"], [{}]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.env["identity_center"]["assignment_teams"] = selected
                self.render()

    def test_duplicate_identity_and_resource(self):
        """Reject duplicated identities and resource names."""

        for key, value in (("identity_center_user_ids", ["same"]), ("cognito_subjects", ["same"]), ("resource_name", "same-pet")):
            with self.subTest(key=key):
                teams = {team: data | {key: value} for team, data in self.teams.items()}

                with self.assertRaises(ValueError):
                    render(self.env, teams, "/tmp/generated")

    def test_unknown_fields_and_invalid_runtime(self):
        """Reject typos and unsupported runtime limits."""

        self.env["model"]["max_tool_calls"] = 99

        with self.assertRaises(ValueError):
            self.render()

        self.env["model"].pop("max_tool_calls")

        self.env["regoin"] = "us-west-2"

        with self.assertRaises(ValueError):
            self.render()

    def test_post_deploy_contracts(self):
        """Load generated deployment outputs with the existing runtime readers."""

        from app.access import load_policy
        from app.shared_card import load_targets
        from scripts.initialize_login_secret import validate_config
        from scripts.deploy_proxy import commands

        self.env["web"].update(cards_enabled=True, chat_enabled=True)
        self.env["access"]["max_session_seconds"] = 14400

        self.env["deployment"] = {
            "instance_id": "i-0123456789abcdef0", "user_pool_id": "us-east-1_EXAMPLE",
            "client_id": "exampleclient123",
            "secret_arn": "arn:aws:secretsmanager:us-east-1:444455556666:secret:workshop/login-AbCdEf",
        }

        for team, data in self.teams.items():
            data["function_url"] = "https://" + ("a" if team == "team-01" else "b") * 32 + ".lambda-url.us-east-1.on.aws/"

        self.teams["team-01"]["cognito_subjects"] = ["subject-1"]

        with tempfile.TemporaryDirectory() as parent:
            directory = Path(parent) / "generated"

            write_new(directory, render(self.env, self.teams, directory))

            self.assertEqual(load_policy(directory / "access.json").members["subject-1"], "team-01")
            self.assertEqual(load_policy(directory / "access.json").max_session_seconds, 14400)
            auth = json.loads((directory / "ui-auth.tfvars.json").read_text())["auth"]
            self.assertEqual(auth["max_session_seconds"], 14400)

            targets = load_targets(directory / "shared-card.json")

            self.assertIsNotNone(targets)

            validate_config(json.loads((directory / "login-bootstrap.json").read_text()))

            self.assertTrue(commands(json.loads((directory / "proxy.json").read_text())))

            runtime = json.loads((directory / "team-01-runtime.json").read_text())

            self.assertEqual(runtime["account_id"], "444455556666")

    def test_incomplete_deployment(self):
        """Require complete login deployment metadata."""

        self.env["deployment"]["client_id"] = "exampleclient123"

        with self.assertRaises(ValueError):
            self.render()

    def test_identity_region_exception(self):
        """Preserve a separate Identity Center region."""

        self.env["identity_center"]["region"] = "us-west-2"
        files = self.render()

        self.assertEqual(json.loads(files["control.tfvars.json"])["region"], "us-west-2")
        self.assertEqual(json.loads(files["pets.tfvars.json"])["workload"]["region"], "us-east-1")

    def test_no_overwrite_or_public_output(self):
        """Keep existing files and the public repository untouched."""

        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "private"

            write_new(target, {"sample.json": "{}"})

            with self.assertRaises(FileExistsError):
                write_new(target, {"sample.json": "changed"})

            self.assertEqual((target / "sample.json").read_text(), "{}")

        with self.assertRaises(ValueError):
            write_new(ROOT / "generated-config", {})

    def test_local_output(self):
        """Allow ignored local configuration without replacing existing files."""

        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)

            with patch("scripts.configure_environment.ROOT", root):
                write_new(root / ".local", {"sample.json": "{}"})
                write_new(root / ".local" / "event", {"sample.json": "{}"})

                with self.assertRaises(ValueError):
                    write_new(root / "config", {})

                with self.assertRaises(FileExistsError):
                    write_new(root / ".local", {})
