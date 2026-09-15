"""Run checked AWS CLI commands and convert DynamoDB data for setup and tests."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def encode(value):
    """Convert Python values, including nested data, to DynamoDB format."""

    if isinstance(value, str):
        return {"S": value}

    if type(value) is bool:
        return {"BOOL": value}

    if type(value) is int:
        return {"N": str(value)}

    if isinstance(value, dict):
        return {"M": {key: encode(item) for key, item in value.items()}}

    if isinstance(value, list):
        return {"L": [encode(item) for item in value]}

    raise ValueError("Initial data contains an unsupported type.")


def decode(value):
    """Convert DynamoDB data to Python values using integers for numbers."""

    if "S" in value:
        return value["S"]

    if "N" in value:
        return int(value["N"])

    if "BOOL" in value:
        return value["BOOL"]

    if "M" in value:
        return {key: decode(item) for key, item in value["M"].items()}

    if "L" in value:
        return [decode(item) for item in value["L"]]

    raise ValueError("The DynamoDB attribute type is unsupported.")


def load_config(path):
    """Check targets and resolve fixture paths from the config directory."""

    path = Path(path).resolve()
    config = json.loads(path.read_text())

    if not re.fullmatch(r"[0-9]{12}", config["account_id"]):
        raise ValueError("account_id must be a 12-digit string.")

    if not config["profile"].strip() or not re.fullmatch(
        r"[a-z]{2}(-[a-z]+)+-[0-9]+", config["region"]
    ):
        raise ValueError("The profile or region is invalid.")

    teams = config["teams"]

    if (
        not isinstance(teams, dict)
        or not 1 <= len(teams) <= 20
        or len(set(teams.values())) != len(teams)
    ):
        raise ValueError("Configure 1–20 teams with distinct resources.")

    for team, resource in teams.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", team) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{2,53}", resource
        ):
            raise ValueError("The team or resource name is invalid.")

    config["pet_fixture"] = (path.parent / config["pet_fixture"]).resolve()

    return config


class AWS:
    """Run AWS CLI commands for the configured environment."""

    def __init__(self, config):
        """Store CLI settings without checking AWS credentials yet."""

        self.config = config

    def raw(self, *args):
        """Run one CLI command with the configured profile, region and timeout."""

        return subprocess.run(
            [
                "aws",
                *args,
                "--profile",
                self.config["profile"],
                "--region",
                self.config["region"],
                "--output",
                "json",
                "--no-cli-pager",
            ],
            env=dict(os.environ, AWS_MAX_ATTEMPTS="1", AWS_PAGER=""),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def call(self, *args):
        """Read the CLI result as JSON or raise its error."""

        result = self.raw(*args)

        if result.returncode:
            raise RuntimeError(result.stderr.strip())

        return json.loads(result.stdout) if result.stdout.strip() else {}

    def preflight(self):
        """Check the account and every target before writing data."""

        if (
            self.call("sts", "get-caller-identity")["Account"]
            != self.config["account_id"]
        ):
            raise RuntimeError("Wrong AWS account; stopping before any writes.")

        # Check every target before writing anything.
        for team, name in self.config["teams"].items():
            table = self.call("dynamodb", "describe-table", "--table-name", name)[
                "Table"
            ]
            function = self.call(
                "lambda", "get-function-configuration", "--function-name", name
            )
            expected = function["Environment"]["Variables"]

            if (
                table["TableStatus"] != "ACTIVE"
                or table["TableArn"].split(":")[4] != self.config["account_id"]
                or function["FunctionArn"].split(":")[4] != self.config["account_id"]
                or function["State"] != "Active"
                or expected.get("TEAM_ID") != team
                or expected.get("TABLE_NAME") != name
            ):
                raise RuntimeError(
                    "Configured targets do not match the team's active resources."
                )

    def get(self, table, key):
        """Read an item by pet_id with strong consistency or return None."""

        response = self.call(
            "dynamodb",
            "get-item",
            "--table-name",
            table,
            "--key",
            json.dumps({"pet_id": {"S": key}}),
            "--consistent-read",
        )

        return (
            {key: decode(value) for key, value in response["Item"].items()}
            if "Item" in response
            else None
        )

    def put_if_absent(self, table, item):
        """Create a missing item without replacing existing data."""

        result = self.raw(
            "dynamodb",
            "put-item",
            "--table-name",
            table,
            "--item",
            json.dumps({key: encode(value) for key, value in item.items()}),
            "--condition-expression",
            "attribute_not_exists(pet_id)",
        )

        if result.returncode and "ConditionalCheckFailedException" in result.stderr:
            return "preservado"

        if result.returncode:
            raise RuntimeError(result.stderr.strip())

        return "creado"

    def invoke(self, name, event):
        """Wait for Lambda and return its JSON result, including rejected actions."""

        with tempfile.TemporaryDirectory(prefix="pet-invoke-") as directory:
            output = Path(directory) / "response.json"
            metadata = self.call(
                "lambda",
                "invoke",
                "--function-name",
                name,
                "--cli-binary-format",
                "raw-in-base64-out",
                "--payload",
                json.dumps(event),
                str(output),
            )

            if metadata.get("FunctionError") or metadata.get("StatusCode") != 200:
                raise RuntimeError(
                    "The Lambda invocation did not complete successfully."
                )

            return json.loads(output.read_text())
