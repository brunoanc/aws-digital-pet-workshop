"""Read the team's pet with a temporary role limited to its item."""

from decimal import Decimal
import json
from pathlib import Path
import re

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.config import Config

from app.access import authorize, load_policy
from app.card import validated_snapshot
from app.card_limits import card_read_slot


def load_targets(path):
    """Check team destinations from the server config, not browser input."""

    data = json.loads(Path(path).read_text())

    if not isinstance(data, dict) or set(data) != {"account_id", "region", "teams"}:
        raise ValueError("Check the shared card configuration fields.")

    if (
        not isinstance(data["account_id"], str)
        or not re.fullmatch(r"[0-9]{12}", data["account_id"])
        or not isinstance(data["region"], str)
        or not re.fullmatch(r"us-[a-z]+-[0-9]+", data["region"])
        or not isinstance(data["teams"], dict)
        or not data["teams"]
    ):
        raise ValueError("Check the shared card account, region, and teams.")

    for team, target in data["teams"].items():
        if (
            not re.fullmatch(r"team-[0-9]{2}", team)
            or not isinstance(target, dict)
            or set(target) - {"agent"} != {"role_arn", "table_name"}
            or not isinstance(target["role_arn"], str)
            or not re.fullmatch(
                r"arn:aws:iam::"
                + data["account_id"]
                + r":role/[A-Za-z0-9+=,.@_-]{1,64}",
                target["role_arn"],
            )
            or not isinstance(target["table_name"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", target["table_name"])
        ):
            raise ValueError("Check the registered team role and table.")

        if "agent" in target:
            from app.shared_agent import validate_agent

            validate_agent(target["agent"], data["region"])

    return data


def plain_numbers(value):
    """Convert whole-number DynamoDB decimals and reject fractional stats."""

    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)

    if isinstance(value, dict):
        return {key: plain_numbers(item) for key, item in value.items()}

    return value


def read_card(access_path, targets_path, claims):
    """Check access before each AWS call and return the assigned pet."""

    team = authorize(load_policy(access_path), claims)
    targets = load_targets(targets_path)
    target = targets["teams"].get(team)

    if target is None:
        raise PermissionError("La ficha de tu equipo todavía no está habilitada.")

    with card_read_slot(team):
        return read_scoped_card(access_path, claims, team, targets, target)


def read_scoped_card(access_path, claims, team, targets, target):
    """Read the fixed pet destination while the caller holds its team slot."""

    if authorize(load_policy(access_path), claims) != team:
        raise PermissionError("Tu asignación cambió; vuelve a cargar la página.")

    options = Config(
        connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}
    )
    session = boto3.Session(region_name=targets["region"])
    sts = session.client("sts", config=options)

    if sts.get_caller_identity()["Account"] != targets["account_id"]:
        raise ValueError("The host session belongs to another account.")

    if authorize(load_policy(access_path), claims) != team:
        raise PermissionError("Tu asignación cambió; vuelve a cargar la página.")

    credentials = sts.assume_role(
        RoleArn=target["role_arn"],
        RoleSessionName="pet-card-" + team,
        DurationSeconds=900,
    )["Credentials"]
    scoped = boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name=targets["region"],
    )

    if authorize(load_policy(access_path), claims) != team:
        raise PermissionError("Tu asignación cambió; vuelve a cargar la página.")

    response = scoped.client("dynamodb", config=options).get_item(
        TableName=f"arn:aws:dynamodb:{targets['region']}:{targets['account_id']}:table/{target['table_name']}",
        Key={"pet_id": {"S": team}},
        ConsistentRead=True,
    )
    deserialize = TypeDeserializer().deserialize
    pet = {
        key: plain_numbers(deserialize(value))
        for key, value in response.get("Item", {}).items()
    }

    if authorize(load_policy(access_path), claims) != team:
        raise PermissionError("Tu asignación cambió; vuelve a cargar la página.")

    return team, validated_snapshot(pet, team)
