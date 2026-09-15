"""Create missing pets from the starter without overwriting progress."""

import argparse
import json
from pathlib import Path
import sys

from pet_ops import AWS, load_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

from rules import valid_pet


def seed(aws, config, apply=False):
    """Check fixtures and targets, then preview or create missing items."""

    pet_fixture = json.loads(config["pet_fixture"].read_text())

    if "pet_id" in pet_fixture:
        raise ValueError("Fixtures must not specify pet_id.")

    items = []

    for team, table in config["teams"].items():
        pet = dict(pet_fixture, pet_id=team)

        if not valid_pet(pet, team):
            raise ValueError("The pet fixture is invalid.")

        items.append((table, pet))

    aws.preflight()

    results = []

    for table, item in items:
        status = (
            aws.put_if_absent(table, item)
            if apply
            else (
                "existe" if aws.get(table, item["pet_id"]) is not None else "pendiente"
            )
        )

        results.append({"table": table, "pet_id": item["pet_id"], "status": status})

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    try:
        config = load_config(args.config)

        print(
            json.dumps(
                seed(AWS(config), config, args.apply), ensure_ascii=False, indent=2
            )
        )
    except Exception as error:
        sys.exit(f"Initialization stopped: {error}")
