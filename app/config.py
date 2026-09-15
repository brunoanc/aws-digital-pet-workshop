"""Validate local configuration before creating clients or making AWS calls."""

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Settings:
    """Group rehearsal targets and limits for each local conversation."""

    account_id: str
    profile: str
    region: str
    team_id: str
    function_name: str
    model_id: str
    title: str
    personality: str
    max_output_tokens: int
    max_model_turns: int
    max_tool_calls: int
    max_messages: int
    max_input_chars: int
    max_personality_chars: int
    timeout_seconds: int
    temperature: float
    allow_mutations: bool


def load_settings(path):
    """Read the JSON config and check destinations and limits."""

    return settings_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def settings_from_dict(data):
    """Check settings from local config or Lambda environment variables."""

    if not isinstance(data, dict) or set(data) != set(Settings.__dataclass_fields__):
        raise ValueError("Check the application configuration fields.")

    patterns = {
        "account_id": r"[0-9]{12}",
        "region": r"[a-z]{2}(-[a-z]+)+-[0-9]+",
        "team_id": r"[a-z0-9][a-z0-9-]{0,31}",
        "function_name": r"[A-Za-z0-9][A-Za-z0-9_-]{2,53}",
        "model_id": r"amazon\.nova-[a-z0-9-]+-v[0-9]+:[0-9]+",
    }

    for key, pattern in patterns.items():
        if not isinstance(data[key], str) or not re.fullmatch(pattern, data[key]):
            raise ValueError(f"Check the configured value of {key}.")

    for key in ("profile", "title", "personality"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"Specify a value for {key}.")

    limits = {
        "max_output_tokens": (128, 2048),
        "max_model_turns": (1, 6),
        "max_tool_calls": (1, 6),
        "max_messages": (1, 30),
        "max_input_chars": (1, 4000),
        "max_personality_chars": (1, 4000),
        "timeout_seconds": (10, 120),
    }

    for key, (minimum, maximum) in limits.items():
        if type(data[key]) is not int or not minimum <= data[key] <= maximum:
            raise ValueError(
                f"{key} must be an integer between {minimum} and {maximum}."
            )

    if type(data["allow_mutations"]) is not bool:
        raise ValueError("allow_mutations must be true or false.")

    if (
        type(data["temperature"]) not in (int, float)
        or not 0 <= data["temperature"] <= 1
    ):
        raise ValueError("temperature must be between 0 and 1.")

    if len(data["personality"]) > data["max_personality_chars"]:
        raise ValueError("The personality exceeds the configured limit.")

    return Settings(**data)
