"""Send only the new message to the configured Lambda agent."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from botocore.config import Config

from app.function_url import post_signed, validate_url


class RequestLimitError(PermissionError):
    """Carry a safe limit notice for a request rejected before invocation."""


@dataclass(frozen=True)
class RemoteSettings:
    """Define the remote agent's fixed target and transport limits."""

    function_name: str
    read_timeout_seconds: int
    max_response_bytes: int
    function_url: str | None = None


def load_remote_settings(path):
    """Read the agent destination and check its limits."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))

    required = {"function_name", "read_timeout_seconds", "max_response_bytes"}

    if (
        not isinstance(data, dict)
        or not required <= set(data)
        or set(data) - (required | {"function_url"})
    ):
        raise ValueError("Check the remote agent configuration fields.")

    if "function_url" in data and (
        not isinstance(data["function_url"], str) or not data["function_url"]
    ):
        raise ValueError("Configure a complete Function URL or remove the field.")

    if not isinstance(data["function_name"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{2,53}", data["function_name"]
    ):
        raise ValueError("Specify a valid agent Lambda name.")

    for key, minimum, maximum in (
        ("read_timeout_seconds", 40, 180),
        ("max_response_bytes", 4096, 262144),
    ):
        if type(data[key]) is not int or not minimum <= data[key] <= maximum:
            raise ValueError(f"Check the remote agent limit {key}.")

    return RemoteSettings(**data)


class RemoteAgent:
    """Verify account and target before sending one invocation without retries."""

    def __init__(self, settings, remote, session, before_invoke=None):
        """Build a client whose timeout exceeds the Lambda timeout."""

        if remote.function_name == settings.function_name:
            raise ValueError("The agent and pet must use distinct functions.")

        self.settings, self.remote, self.session = settings, remote, session
        self.before_invoke = before_invoke
        self.client_config = Config(
            connect_timeout=3,
            read_timeout=remote.read_timeout_seconds,
            retries={"total_max_attempts": 1},
        )
        self.client = session.client(
            "lambda", region_name=settings.region, config=self.client_config
        )
        partition = session.get_partition_for_region(settings.region)
        self.arn = f"arn:{partition}:lambda:{settings.region}:{settings.account_id}:function:{remote.function_name}"

        if remote.function_url is not None:
            validate_url(remote.function_url, settings.region)

    def preflight(self):
        """Check the Lambda's state, team and model before invoking it."""

        sts = self.session.client(
            "sts", region_name=self.settings.region, config=self.client_config
        )

        if sts.get_caller_identity()["Account"] != self.settings.account_id:
            raise ValueError("The AWS session belongs to another account.")

        function = self.client.get_function_configuration(FunctionName=self.arn)
        runtime = json.loads(
            function.get("Environment", {})
            .get("Variables", {})
            .get("APP_SETTINGS", "{}")
        )

        if (
            function.get("FunctionArn") != self.arn
            or function.get("State") != "Active"
            or function.get("LastUpdateStatus") != "Successful"
            or type(function.get("Timeout")) is not int
            or function["Timeout"] + 5 > self.remote.read_timeout_seconds
            or not isinstance(runtime, dict)
            or any(
                runtime.get(key) != getattr(self.settings, key)
                for key in (
                    "account_id",
                    "region",
                    "team_id",
                    "function_name",
                    "model_id",
                )
            )
        ):
            raise ValueError(
                "The agent does not match the configured team, is not ready, or requires a longer timeout."
            )

        if self.remote.function_url is not None:
            endpoint = self.client.get_function_url_config(FunctionName=self.arn)

            if (
                endpoint.get("FunctionUrl") != self.remote.function_url
                or endpoint.get("FunctionArn") != self.arn
                or endpoint.get("AuthType") != "AWS_IAM"
            ):
                raise ValueError(
                    "The URL does not match the authorized agent or lacks IAM authentication."
                )

    def connect(self, submitted_url):
        """Check the pasted URL against the team's endpoint without running the agent."""

        if (
            not isinstance(submitted_url, str)
            or submitted_url.strip() != self.remote.function_url
        ):
            raise ValueError("Use the Function URL of the team's assigned agent.")

        self.preflight()

        return self.remote.function_url

    def send(self, message):
        """Send the message and check the response without automatic retries."""

        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > self.settings.max_input_chars
        ):
            raise ValueError("Provide a message within the configured limit.")

        self.preflight()

        if self.before_invoke is not None:
            self.before_invoke()

        if self.remote.function_url is not None:
            body = post_signed(
                self.remote.function_url,
                message,
                self.session,
                self.settings.region,
                self.remote.read_timeout_seconds,
                self.remote.max_response_bytes,
            )
        else:
            body = self.invoke_direct(message)

        return self.validate_result(body)

    def invoke_direct(self, message):
        """Invoke Lambda directly for rehearsals without a Function URL."""

        response = self.client.invoke(
            FunctionName=self.arn,
            InvocationType="RequestResponse",
            Payload=json.dumps({"message": message}).encode("utf-8"),
        )
        stream = response["Payload"]

        try:
            body = stream.read(self.remote.max_response_bytes + 1)
        finally:
            stream.close()

        if (
            response.get("FunctionError")
            or response.get("StatusCode") != 200
            or len(body) > self.remote.max_response_bytes
        ):
            raise ValueError(
                "A valid response could not be confirmed, so inspect the pet before repeating care."
            )

        return body

    def validate_result(self, body):
        """Check the response format and reject data from another team."""

        result = json.loads(body)

        if (
            not isinstance(result, dict)
            or type(result.get("success")) is not bool
            or not isinstance(result.get("message"), str)
        ):
            raise ValueError("The agent response does not match the expected format.")

        registered, activity = (
            result.get("registered_tools", []),
            result.get("activity", []),
        )
        known = {"inspect_pet", "care_for_pet", "custom_action"}

        if (
            not isinstance(registered, list)
            or any(
                not isinstance(name, str) or name not in known for name in registered
            )
            or len(registered) != len(set(registered))
            or not isinstance(activity, list)
            or len(activity) > self.settings.max_tool_calls
        ):
            raise ValueError("The agent returned unexpected tools or activity.")

        for event in activity:
            if (
                not isinstance(event, dict)
                or event.get("tool") not in registered
                or not isinstance(event.get("result"), dict)
                or type(event["result"].get("success")) is not bool
            ):
                raise ValueError("The agent activity has an unexpected format.")

            pet = event["result"].get("pet")

            if pet is not None and (
                not isinstance(pet, dict) or pet.get("pet_id") != self.settings.team_id
            ):
                raise ValueError("The agent returned another team's data.")

        return {
            "success": result["success"],
            "message": result["message"],
            "registered_tools": registered,
            "activity": activity,
        }
