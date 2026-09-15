"""Prepare isolated capacity destinations without contacting AWS."""

import argparse
import json
from pathlib import Path
import re

from app.config import settings_from_dict


def build_plan(config):
    """Validate the rehearsal scope and build separate runtime and state entries."""

    if (
        not re.fullmatch(r"[0-9]{12}", config["account_id"])
        or not re.fullmatch(r"[0-9]{12}", config["management_account_id"])
        or config["account_id"] == config["management_account_id"]
        or config["prefix"] != "dp-capacity"
        or config["team_numbers"] != list(range(81, 96))
        or not re.fullmatch(r"capacity/[a-z0-9/-]+", config["state_prefix"])
        or ".." in config["state_prefix"]
    ):
        raise ValueError("Use a member account and the isolated capacity destinations.")

    if (
        config["batches"] != [2, 5, 10, 15]
        or type(config["pause_seconds"]) is not int
        or config["pause_seconds"] < 60
        or not isinstance(config["message"], str)
        or not config["message"].strip()
        or len(config["message"]) > config["max_input_chars"]
        or config["max_model_turns"] > 4
        or config["max_output_tokens"] > 512
        or config["max_tool_calls"] > 3
    ):
        raise ValueError("Keep the reviewed batch sizes, token limits and cooldown.")

    teams = {}

    for number in config["team_numbers"]:
        team = f"team-{number:02d}"
        name = f"{config['prefix']}-{team}"
        runtime = {
            key: config[key]
            for key in (
                "account_id",
                "profile",
                "region",
                "model_id",
                "personality",
                "max_output_tokens",
                "max_model_turns",
                "max_tool_calls",
                "max_input_chars",
                "max_personality_chars",
                "timeout_seconds",
                "temperature",
            )
        }

        runtime.update(
            team_id=team,
            function_name=name,
            title="Prueba de capacidad",
            max_messages=1,
            allow_mutations=False,
        )

        settings_from_dict(runtime)

        teams[team] = {
            "runtime": runtime,
            "agent_function": name + "-agent",
            "agent_state_key": f"{config['state_prefix']}/{team}/agent.tfstate",
        }

    return {
        "mode": "plan",
        "account_id": config["account_id"],
        "region": config["region"],
        "pet_state_key": config["state_prefix"] + "/pets.tfstate",
        "builder_source": "tests/capacity/agent_builder.py",
        "read_only": True,
        "max_requests": sum(config["batches"]),
        "batches": [list(teams)[:size] for size in config["batches"]],
        "pause_seconds": config["pause_seconds"],
        "message": config["message"],
        "teams": teams,
    }


def main():
    """Print the capacity manifest without creating files or invoking agents."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)

    args = parser.parse_args()
    plan = build_plan(json.loads(Path(args.config).read_text()))

    print(json.dumps(plan, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
