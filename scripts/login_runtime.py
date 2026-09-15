"""Start the app with login secrets fetched through the instance role."""

import json
import logging
import os
from pathlib import Path
import re
import sys

import boto3
from botocore.config import Config


def render_secrets(payload, config):
    """Check the OIDC settings and convert supported fields to TOML."""

    fields = {
        "redirect_uri",
        "cookie_secret",
        "client_id",
        "client_secret",
        "server_metadata_url",
        "client_kwargs",
    }

    if not isinstance(payload, dict) or set(payload) != {"auth"}:
        raise ValueError("The login secret has an unsupported structure.")

    auth = payload["auth"]

    if not isinstance(auth, dict) or set(auth) != fields:
        raise ValueError("The login secret contains unsupported authentication fields.")

    issuer = (
        f"https://cognito-idp.{config['region']}.amazonaws.com/{config['user_pool_id']}"
    )
    kwargs = {
        "scope": "openid email profile",
        "identity_provider": config["provider_name"],
        "prompt": "login",
    }

    if (
        auth["redirect_uri"] != config["app_origin"] + "/oauth2callback"
        or auth["client_id"] != config["client_id"]
        or auth["server_metadata_url"] != issuer + "/.well-known/openid-configuration"
        or auth["client_kwargs"] != kwargs
        or not isinstance(auth["cookie_secret"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{64,128}", auth["cookie_secret"])
        or not isinstance(auth["client_secret"], str)
        or not re.fullmatch(r"[A-Za-z0-9_+=/-]{16,256}", auth["client_secret"])
    ):
        raise ValueError(
            "The login secret does not match the expected identity provider and origin."
        )

    lines = ["[auth]"] + [
        f"{key} = {json.dumps(auth[key])}" for key in sorted(fields - {"client_kwargs"})
    ]
    lines += ["[auth.client_kwargs]"] + [
        f"{key} = {json.dumps(value)}" for key, value in kwargs.items()
    ]

    return "\n".join(lines) + "\n"


def prepare(config, target):
    """Fetch the configured secret and save it privately in the runtime directory."""

    session = boto3.Session(region_name=config["region"])
    options = Config(
        connect_timeout=3, read_timeout=15, retries={"total_max_attempts": 1}
    )

    if (
        session.client("sts", config=options).get_caller_identity()["Account"]
        != config["account_id"]
    ):
        raise ValueError("The instance role belongs to another account.")

    response = session.client("secretsmanager", config=options).get_secret_value(
        SecretId=config["secret_arn"], VersionStage="AWSCURRENT"
    )

    if response.get("ARN") != config["secret_arn"]:
        raise ValueError("The retrieved secret does not match the configured ARN.")

    content = render_secrets(json.loads(response["SecretString"]), config)
    descriptor = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )

    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def main():
    """Prepare login secrets and start Streamlit on loopback only."""

    logging.getLogger("botocore").setLevel(logging.CRITICAL)

    config = json.loads(Path("/etc/workshop-login/runtime.json").read_text())
    target = Path("/run/workshop-login/secrets.toml")

    if target.exists() or target.is_symlink():
        target.unlink()

    prepare(config, target)

    entry = os.environ.get("PET_UI_ENTRY", "app/login_ui.py")

    if entry not in ("app/login_ui.py", "app/shared_ui.py"):
        raise ValueError("Choose a supported application entry point.")

    args = [sys.executable, "-m", "streamlit", "run", entry]

    os.execv(sys.executable, args)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Login startup failed before serving requests; check settings and role permissions."
        ) from None
