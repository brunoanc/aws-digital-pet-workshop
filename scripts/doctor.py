"""Check a team without changing its pet or calling the model unless requested."""

import argparse
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import tomllib
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


class Report:
    """Collect check results without credentials or service error details."""

    def __init__(self):
        """Start an empty report for one diagnostic run."""

        self.checks = []

    def check(self, name, operation):
        """Record the check result without exposing error details."""

        try:
            result = operation()
        except Exception as error:
            self.checks.append(
                {"check": name, "status": "FAIL", "detail": type(error).__name__}
            )

            return None

        self.checks.append({"check": name, "status": "PASS"})

        return result

    def skip(self, name, reason):
        """Record why a check was skipped instead of marking it as passed."""

        self.checks.append({"check": name, "status": "SKIP", "detail": reason})

    def result(self):
        """Return the checks and whether any of them failed."""

        return {
            "success": not any(check["status"] == "FAIL" for check in self.checks),
            "checks": self.checks,
            "scope": "This team diagnostic does not certify isolation, load capacity, public access, or full workshop readiness.",
        }


def require(condition):
    """Stop the check if its condition is false."""

    if not condition:
        raise ValueError("The check failed.")


def local_environment():
    """Check Python, pinned dependencies and imports without calling AWS."""

    require(sys.version_info[:2] == (3, 13))

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    for dependency in project["project"]["dependencies"]:
        package, expected = dependency.split("==")

        require(version(package) == expected)

    for module in ("boto3", "strands", "streamlit", "app.backend", "app.remote"):
        importlib.import_module(module)

    for filename in (
        "agent_lambda/agent_builder.py",
        "lambda/handler.py",
        "lambda/rules.py",
        "lambda/custom_action.py",
    ):
        require((ROOT / filename).is_file())

    return True


def cloud_checks(report, settings, remote, session, inference=False):
    """Check the account, resources and pet without running the student's agent."""

    from boto3.dynamodb.types import TypeDeserializer
    from botocore.config import Config

    from app.backend import PetBackend
    from app.remote import RemoteAgent

    client_config = Config(
        connect_timeout=3,
        read_timeout=settings.timeout_seconds,
        retries={"total_max_attempts": 1},
    )

    def identity():
        """Require the configured account before reading workshop resources."""

        account = session.client(
            "sts", region_name=settings.region, config=client_config
        ).get_caller_identity()["Account"]

        require(account == settings.account_id)

        return True

    if report.check("AWS identity and account", identity) is None:
        report.skip(
            "AWS resources", "Identity is unverified, so check SSO and the profile."
        )

        return

    backend = PetBackend(settings, session)

    def pet_ready():
        """Verify the pet Lambda region, team, table, and active state."""

        backend.preflight()

        return True

    ready = report.check("Pet Lambda configuration", pet_ready)

    def pet_record():
        """Read the team's item with strong consistency without changing it."""

        partition = session.get_partition_for_region(settings.region)
        table = f"arn:{partition}:dynamodb:{settings.region}:{settings.account_id}:table/{settings.function_name}"
        response = session.client(
            "dynamodb", region_name=settings.region, config=client_config
        ).get_item(
            TableName=table,
            Key={"pet_id": {"S": settings.team_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")

        require(isinstance(item, dict) and bool(item))

        deserialize = TypeDeserializer().deserialize
        pet = {key: deserialize(value) for key, value in item.items()}

        require(pet.get("pet_id") == settings.team_id)

        return pet

    stored = report.check("DynamoDB record", pet_record)

    if ready and stored is not None:

        def inspect():
            """Compare the inspection result with DynamoDB without requesting care."""

            result = backend.invoke("inspect", {}, str(uuid4()))

            require(result.get("success") is True and result.get("pet") == stored)

            return True

        report.check("Lambda inspection matches DynamoDB", inspect)
    else:
        report.skip(
            "Lambda inspection", "The function or record has not been validated."
        )

    if remote is not None:

        def agent_ready():
            """Check the agent target and timeout without running it."""

            RemoteAgent(settings, remote, session).preflight()

            return True

        report.check("Agent Lambda configuration", agent_ready)
    else:
        report.skip("Agent Lambda configuration", "No --agent-config was provided.")

    if inference:

        def infer():
            """Call the model once without tools or pet data."""

            response = session.client(
                "bedrock-runtime", region_name=settings.region, config=client_config
            ).converse(
                modelId=settings.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": "Responde únicamente: listo"}],
                    }
                ],
                inferenceConfig={"maxTokens": 32, "temperature": 0},
            )

            require(response.get("stopReason") == "end_turn")
            require(bool(response.get("output", {}).get("message", {}).get("content")))

            return True

        report.check("Bedrock inference (billable)", infer)
    else:
        report.skip(
            "Bedrock inference",
            "Inference was not requested, so use --inference to authorize consumption.",
        )


def diagnose(app_path, remote_path=None, offline=False, inference=False):
    """Run the selected checks and return a report without secrets."""

    report = Report()

    if report.check("Python, dependencies, and files", local_environment) is None:
        report.skip(
            "Configuration and AWS", "Fix the local environment before continuing."
        )

        return report.result()

    from app.config import load_settings
    from app.remote import load_remote_settings

    settings = report.check("App configuration", lambda: load_settings(app_path))
    remote = (
        report.check(
            "Local remote-agent configuration",
            lambda: load_remote_settings(remote_path),
        )
        if remote_path
        else None
    )

    if settings is None or (remote_path and remote is None):
        report.skip("AWS", "Configuration is invalid.")

        return report.result()

    if offline:
        report.skip("AWS and inference", "Offline mode did not create AWS clients.")

        return report.result()

    import boto3

    session = report.check(
        "Configured session",
        lambda: boto3.Session(
            profile_name=settings.profile, region_name=settings.region
        ),
    )

    if session is not None:
        try:
            cloud_checks(report, settings, remote, session, inference)
        except Exception as error:
            report.checks.append(
                {
                    "check": "AWS clients",
                    "status": "FAIL",
                    "detail": type(error).__name__,
                }
            )

    return report.result()


def main():
    """Run checks from CLI options and return a failure code if needed."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--app-config", required=True)
    parser.add_argument("--agent-config")

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--inference", action="store_true")

    args = parser.parse_args()
    result = diagnose(args.app_config, args.agent_config, args.offline, args.inference)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
