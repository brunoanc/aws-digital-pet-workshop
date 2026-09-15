"""Test pet reads and one real feeding with permission, without undoing changes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import sys

from pet_ops import AWS, load_config


def require(condition, message):
    """Stop the test if a required check fails."""

    if not condition:
        raise RuntimeError(message)


def verify(aws, config, team, operation_id):
    """Check that overlapping requests save one feeding without resetting the pet."""

    require(team in config["teams"], "The team is absent from the configuration.")
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation_id),
        "The test operation ID is invalid.",
    )
    aws.preflight()

    names = config["teams"]
    target = names[team]

    require(
        aws.get(target, "_op#" + operation_id) is None,
        "The operation ID already exists, so inspect its record instead of repeating the test.",
    )

    before = {key: aws.get(name, key) for key, name in names.items()}
    pet = before[team]

    require(
        pet is not None
        and pet["fullness"] < 90
        and pet["inventory"]["healthy_meal"] > 0,
        "The pet is not ready for the feeding test.",
    )

    inspection = aws.invoke(target, {"pet_id": team, "action": "inspect"})

    require(
        inspection.get("success") and inspection.get("pet") == pet,
        "The Lambda read differs from DynamoDB.",
    )

    event = {
        "pet_id": team,
        "action": "feed",
        "parameters": {"food": "healthy_meal"},
        "operation_id": operation_id,
    }

    # Send two requests together; this does not guarantee a race on the server.
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: aws.invoke(target, event), range(2)))

    require(
        all(
            r.get("success") or r.get("reason") == "CONCURRENT_UPDATE"
            for r in responses
        ),
        "An invocation failed, so inspect logs and the operation record before retrying.",
    )

    repeated = aws.invoke(target, event)

    require(repeated.get("success"), "The retry did not confirm the outcome.")

    expected = json.loads(json.dumps(pet))
    expected["inventory"]["healthy_meal"] -= 1

    for field, amount in {"fullness": 35, "health": 5, "happiness": 3}.items():
        expected[field] = min(100, expected[field] + amount)

    expected["version"] += 1

    require(repeated["pet"] == expected, "The result does not match a single feeding.")
    require(
        all(not r.get("success") or r["pet"] == expected for r in responses),
        "Concurrent results differ.",
    )

    record = aws.get(target, "_op#" + operation_id)

    require(
        record is not None and record["result"] == repeated,
        "The persisted operation result is missing.",
    )

    conflict = aws.invoke(target, dict(event, action="rest", parameters={}))

    require(
        conflict.get("reason") == "OPERATION_CONFLICT",
        "An operation ID was incorrectly accepted for another action.",
    )

    other = next((key for key in names if key != team), None)

    if other:
        cross = aws.invoke(target, {"pet_id": other, "action": "inspect"})

        require(
            cross.get("reason") == "WRONG_TEAM",
            "The function did not reject the other team.",
        )

    after = {key: aws.get(name, key) for key, name in names.items()}

    require(
        after[team] == expected, "The final state does not match the expected result."
    )
    require(
        all(after[key] == value for key, value in before.items() if key != team),
        "Another pet changed.",
    )

    return {
        "status": "PASS",
        "account_id": config["account_id"],
        "team": team,
        "operation_id": operation_id,
        "before": pet,
        "after": after[team],
        "other_pets_unchanged": True,
        "note": "This tests the handler and saved state with admin credentials, not student IAM isolation.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--allow-mutation", action="store_true", required=True)

    args = parser.parse_args()

    try:
        config = load_config(args.config)

        print(
            json.dumps(
                verify(AWS(config), config, args.team, args.operation_id),
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as error:
        sys.exit(f"Verification stopped without reverting changes: {error}")
