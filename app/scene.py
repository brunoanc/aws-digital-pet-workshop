"""Display the pet and verify persisted operations before animating actions."""

import hashlib
from html import escape
import json
from pathlib import Path
import re

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.config import Config
import streamlit as st

from app.species import species_art, species_key


ASSETS = Path(__file__).resolve().parent / "assets"
ACTIONS = {
    "feed": ("🍎", "¡Qué rico!"),
    "rest": ("z Z", "Un descanso merecido"),
    "play": ("⚽", "¡A jugar!"),
    "custom": ("✦", "¡Una habilidad especial!"),
}


def verified_action(settings, event, pet, session_factory=None):
    """Check the action against its saved receipt and the current pet state."""

    if not isinstance(event, dict):
        return None

    action, operation = event.get("action"), event.get("operation_id")
    result, parameters = event.get("result"), event.get("parameters")

    if (
        action not in ACTIONS
        or not isinstance(operation, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation)
        or not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("pet") != pet
        or pet.get("pet_id") != settings.team_id
        or not isinstance(parameters, dict)
    ):
        return None

    session = (
        session_factory()
        if session_factory
        else boto3.Session(profile_name=settings.profile, region_name=settings.region)
    )
    config = Config(
        connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}
    )

    if (
        session.client("sts", config=config).get_caller_identity()["Account"]
        != settings.account_id
    ):
        return None

    partition = session.get_partition_for_region(settings.region)
    table = f"arn:{partition}:dynamodb:{settings.region}:{settings.account_id}:table/{settings.function_name}"
    item = (
        session.client("dynamodb", config=config)
        .get_item(
            TableName=table,
            Key={"pet_id": {"S": "_op#" + operation}},
            ConsistentRead=True,
        )
        .get("Item")
    )

    if not item:
        return None

    deserialize = TypeDeserializer().deserialize
    record = {key: deserialize(value) for key, value in item.items()}
    fingerprint = hashlib.sha256(
        json.dumps(
            {"action": action, "parameters": parameters}, sort_keys=True
        ).encode()
    ).hexdigest()

    if record.get("fingerprint") != fingerprint or record.get("result") != result:
        return None

    return {"action": action, "operation_id": operation}


def scene_html(pet, action=None, scope="preview"):
    """Build the scene from local assets and escaped text, not model HTML."""

    kind = action["action"] if action and action.get("action") in ACTIONS else "idle"
    operation = action.get("operation_id", "") if kind != "idle" else ""
    symbol, label = ACTIONS.get(kind, ("", ""))
    replacements = {
        "STYLE": (ASSETS / "scene.css").read_text(),
        "ART": species_art(pet.get("species")),
        "NAME": escape(pet["name"]),
        "SPECIES": escape(pet["species"]),
        "ACTION": kind,
        "SYMBOL": symbol,
        "LABEL": label,
        "EVENT": escape(str(operation), quote=True),
        "SCOPE": escape(scope, quote=True),
    }
    template = (ASSETS / "scene.html").read_text()

    return re.sub(r"\{\{([A-Z]+)\}\}", lambda match: replacements[match[1]], template)


def render_scene(settings, snapshot, fresh, verifier=None):
    """Animate each new event once only if its verification passes."""

    scope = f"{settings.account_id}:{settings.region}:{settings.team_id}"

    if st.session_state.get("scene_scope") != scope:
        st.session_state["scene_scope"] = scope
        st.session_state["scene_seen"] = []

    pending = st.session_state.pop("scene_pending", [])
    action = None

    for event in pending[: settings.max_tool_calls]:
        operation = event.get("operation_id") if isinstance(event, dict) else None

        if (
            not isinstance(operation, str)
            or operation in st.session_state["scene_seen"]
        ):
            continue

        st.session_state["scene_seen"] = (st.session_state["scene_seen"] + [operation])[
            -100:
        ]

        if fresh:
            try:
                candidate = (verifier or verified_action)(
                    settings, event, snapshot["pet"]
                )
            except Exception:
                candidate = None

            if candidate:
                action = candidate

    st.iframe(scene_html(snapshot["pet"], action, scope), height=400)

    if species_key(snapshot["pet"].get("species")) is None:
        st.caption(
            "Especie no reconocida. Usa Dragón, Gato, Zorro o Ajolote en DynamoDB."
        )
