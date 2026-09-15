"""Fill the empty login secret without printing credentials or saving them locally."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets

import boto3
from botocore.config import Config


def validate_config(config):
    """Check the account, secret, login provider and origin before calling AWS."""

    patterns = {
        "account_id": r"[0-9]{12}",
        "profile": r"[A-Za-z0-9_-]+",
        "region": r"us-[a-z]+-[0-9]+",
        "secret_arn": r"arn:aws:secretsmanager:us-[a-z]+-[0-9]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+-[A-Za-z0-9]{6}",
        "user_pool_id": r"us-[a-z]+-[0-9]+_[A-Za-z0-9]+",
        "client_id": r"[a-z0-9]{1,128}",
        "app_origin": r"https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}",
        "provider_name": r"[A-Za-z][A-Za-z0-9]{0,31}",
    }

    if not isinstance(config, dict) or set(config) != set(patterns):
        raise ValueError("Check the login bootstrap configuration fields.")

    for key, pattern in patterns.items():
        if not isinstance(config[key], str) or not re.fullmatch(pattern, config[key]):
            raise ValueError(f"Check the login bootstrap field {key}.")

    if (
        config["secret_arn"].split(":")[3:5] != [config["region"], config["account_id"]]
        or not config["user_pool_id"].startswith(config["region"] + "_")
        or config["provider_name"] == "COGNITO"
    ):
        raise ValueError(
            "The secret, user pool, and provider must match the configured environment."
        )


def initialize(config, apply=False):
    """Check the account and Cognito client before filling an empty secret."""

    validate_config(config)

    if not apply:
        return {
            "status": "preview",
            "secret_arn": config["secret_arn"],
            "app_origin": config["app_origin"],
        }

    session = boto3.Session(
        profile_name=config["profile"], region_name=config["region"]
    )
    options = Config(
        connect_timeout=3, read_timeout=15, retries={"total_max_attempts": 1}
    )

    if (
        session.client("sts", config=options).get_caller_identity()["Account"]
        != config["account_id"]
    ):
        raise ValueError("The session belongs to another AWS account.")

    storage = session.client("secretsmanager", config=options)
    metadata = storage.describe_secret(SecretId=config["secret_arn"])
    tags = {tag["Key"]: tag["Value"] for tag in metadata.get("Tags", [])}

    if (
        metadata.get("ARN") != config["secret_arn"]
        or tags.get("ManagedBy") != "Terraform"
        or metadata.get("DeletedDate")
        or metadata.get("VersionIdsToStages")
    ):
        raise ValueError(
            "The target must be an empty, active Terraform-managed secret."
        )

    client = session.client("cognito-idp", config=options).describe_user_pool_client(
        UserPoolId=config["user_pool_id"], ClientId=config["client_id"]
    )["UserPoolClient"]

    if (
        client.get("UserPoolId") != config["user_pool_id"]
        or client.get("ClientId") != config["client_id"]
        or client.get("CallbackURLs") != [config["app_origin"] + "/oauth2callback"]
        or client.get("LogoutURLs") != [config["app_origin"]]
        or client.get("SupportedIdentityProviders") != [config["provider_name"]]
        or client.get("AllowedOAuthFlows") != ["code"]
        or client.get("AllowedOAuthFlowsUserPoolClient") is not True
        or set(client.get("AllowedOAuthScopes", [])) != {"openid", "email", "profile"}
        or not isinstance(client.get("ClientSecret"), str)
        or not 16 <= len(client["ClientSecret"]) <= 256
    ):
        raise ValueError(
            "The Cognito client does not match the expected confidential federation setup."
        )

    payload = {
        "auth": {
            "redirect_uri": config["app_origin"] + "/oauth2callback",
            "cookie_secret": secrets.token_urlsafe(48),
            "client_id": config["client_id"],
            "client_secret": client["ClientSecret"],
            "server_metadata_url": f"https://cognito-idp.{config['region']}.amazonaws.com/{config['user_pool_id']}/.well-known/openid-configuration",
            "client_kwargs": {
                "scope": "openid email profile",
                "identity_provider": config["provider_name"],
                "prompt": "login",
            },
        }
    }
    version = hashlib.sha256(
        (config["secret_arn"] + ":initial-login-v1").encode()
    ).hexdigest()
    result = storage.put_secret_value(
        SecretId=config["secret_arn"],
        ClientRequestToken=version,
        SecretString=json.dumps(payload),
    )
    confirmed = storage.describe_secret(SecretId=config["secret_arn"])

    if result.get("VersionId") != version or "AWSCURRENT" not in confirmed.get(
        "VersionIdsToStages", {}
    ).get(version, []):
        raise RuntimeError(
            "Secret initialization is unconfirmed, so inspect version metadata before retrying."
        )

    return {
        "status": "initialized",
        "secret_arn": config["secret_arn"],
        "version_id": version,
    }


def main():
    """Preview or create the login secret value without exposing error details."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        result = initialize(config, args.apply)
    except Exception:
        raise SystemExit(
            "Login setup failed; check SSO, settings and secret versions before retrying."
        ) from None

    print(json.dumps(result))


if __name__ == "__main__":
    main()
