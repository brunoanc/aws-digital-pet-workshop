"""Connect each signed-in team to its configured agent."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace

import boto3
from botocore.config import Config

from app.access import authorize, load_policy
from app.function_url import validate_url
from app.remote import RemoteAgent, RemoteSettings, RequestLimitError
from app.shared_card import load_targets


def validate_agent(data, region):
    """Check the agent destination and usage limits."""

    fields = {
        "function_name",
        "function_url",
        "model_id",
        "read_timeout_seconds",
        "max_response_bytes",
        "max_input_chars",
        "max_messages",
        "max_tool_calls",
        "max_requests",
        "min_interval_seconds",
    }

    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Check the shared agent configuration fields.")

    for key, pattern in {
        "function_name": r"[A-Za-z0-9][A-Za-z0-9_-]{2,53}",
        "model_id": r"amazon\.nova-[a-z0-9-]+-v[0-9]+:[0-9]+",
    }.items():
        if not isinstance(data[key], str) or not re.fullmatch(pattern, data[key]):
            raise ValueError("Check the shared agent name and model.")

    validate_url(data["function_url"], region)

    for key, low, high in (
        ("read_timeout_seconds", 40, 180),
        ("max_response_bytes", 4096, 262144),
        ("max_input_chars", 1, 4000),
        ("max_messages", 1, 30),
        ("max_tool_calls", 1, 6),
        ("max_requests", 1, 1000),
        ("min_interval_seconds", 1, 60),
    ):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError("Check the shared agent usage limits.")


@contextmanager
def request_slot(team, limits, directory="/var/lib/workshop-login"):
    """Allow one active request per team and keep its usage count across restarts."""

    if not re.fullmatch(r"team-[0-9]{2}", team):
        raise ValueError("Specify a valid team for the request counter.")

    path = Path(directory) / (team + "-requests.json")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)

    with os.fdopen(descriptor, "r+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RequestLimitError(
                "Tu equipo ya está esperando una respuesta; dale un momento."
            ) from None

        raw = stream.read()
        usage = json.loads(raw) if raw else {"count": 0, "last": 0}
        now = time.time()

        if usage["count"] >= limits["max_requests"]:
            raise RequestLimitError(
                "Tu equipo alcanzó el límite de mensajes; avisa al organizador."
            )

        if now - usage["last"] < limits["min_interval_seconds"]:
            raise RequestLimitError("Espera unos segundos antes de enviar otro mensaje.")

        stream.seek(0)
        json.dump({"count": usage["count"] + 1, "last": now}, stream)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())

        yield


class SharedAgent:
    """Connect the chat to the signed-in team's agent."""

    def __init__(self, access, targets, claims):
        """Load the team's destination before requesting AWS credentials."""

        self.access, self.targets_path, self.claims = access, targets, claims
        self.team = authorize(load_policy(access), claims)
        self.targets = load_targets(targets)
        self.target = self.targets["teams"].get(self.team, {})
        self.agent = self.target.get("agent")

        if self.agent is None:
            raise PermissionError("El agente de tu equipo todavía no está habilitado.")

        self.settings = SimpleNamespace(
            account_id=self.targets["account_id"],
            region=self.targets["region"],
            team_id=self.team,
            function_name=self.target["table_name"],
            **{
                key: self.agent[key]
                for key in (
                    "model_id",
                    "max_input_chars",
                    "max_messages",
                    "max_tool_calls",
                )
            },
        )
        self.remote = RemoteSettings(
            **{
                key: self.agent[key]
                for key in (
                    "function_name",
                    "function_url",
                    "read_timeout_seconds",
                    "max_response_bytes",
                )
            }
        )

    def check(self):
        """Check that access is valid and the destination has not changed."""

        if (
            authorize(load_policy(self.access), self.claims) != self.team
            or load_targets(self.targets_path) != self.targets
        ):
            raise PermissionError("Tu acceso cambió; vuelve a cargar la página.")

    def session(self):
        """Get temporary AWS credentials for this team's role."""

        self.check()

        options = Config(
            connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}
        )
        host = boto3.Session(region_name=self.settings.region)
        sts = host.client("sts", config=options)

        if sts.get_caller_identity()["Account"] != self.settings.account_id:
            raise ValueError("The host session belongs to another account.")

        self.check()

        credentials = sts.assume_role(
            RoleArn=self.target["role_arn"],
            RoleSessionName="pet-agent-" + self.team,
            DurationSeconds=900,
        )["Credentials"]

        return boto3.Session(
            region_name=self.settings.region,
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )

    def connect(self, submitted_url):
        """Check the pasted URL before calling AWS."""

        if (
            not isinstance(submitted_url, str)
            or submitted_url.strip() != self.remote.function_url
        ):
            raise ValueError("Use the Function URL assigned to this team.")

        result = RemoteAgent(self.settings, self.remote, self.session()).connect(
            submitted_url
        )

        self.check()

        return result

    def send(self, message):
        """Count the attempt and check access before sending the message."""

        self.check()

        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > self.settings.max_input_chars
        ):
            raise ValueError("Provide a message within the configured limit.")

        with request_slot(self.team, self.agent):
            result = RemoteAgent(
                self.settings, self.remote, self.session(), before_invoke=self.check
            ).send(message)

            self.check()

            return result
