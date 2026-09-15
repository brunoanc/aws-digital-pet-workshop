"""Test pet rules and action processing with simulated storage rather than real IAM or DynamoDB transactions."""

import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "lambda"))

from rules import act, valid_pet
from handler import lambda_handler, process, plain
from decimal import Decimal


def starter():
    """Load a fresh pet fixture and assign it to team-01."""

    return dict(
        json.loads((ROOT / "fixtures/starter.json").read_text()), pet_id="team-01"
    )


class MemoryStore:
    """Simulate conditional pet and operation reads and writes in memory."""

    def __init__(self):
        """Create an in-memory pet store without forced conflicts."""

        self.items = {"team-01": starter()}
        self.conflict = False

    def get(self, key):
        """Return a copy of the stored record or None when absent."""

        return copy.deepcopy(self.items.get(key))

    def commit(self, pet, version, record):
        """Save pet and operation copies only when the version matches and the operation ID is available."""

        if (
            self.conflict
            or self.items[pet["pet_id"]]["version"] != version
            or record["pet_id"] in self.items
        ):
            return False

        self.items[pet["pet_id"]] = copy.deepcopy(pet)
        self.items[record["pet_id"]] = copy.deepcopy(record)

        return True


class RulesTests(unittest.TestCase):
    """Check rule effects and rejections without external persistence."""

    def test_actions_and_no_input_mutation(self):
        """Verify each action's result without modifying the input pet."""

        for action, params, field, expected in [
            ("inspect", {}, "version", 1),
            ("feed", {"food": "healthy_meal"}, "fullness", 60),
            ("feed", {"food": "cake"}, "health", 79),
            ("play", {}, "energy", 18),
            ("rest", {}, "energy", 73),
        ]:
            with self.subTest(action=action, params=params):
                pet = starter()
                result = act(pet, "team-01", action, params)

                self.assertTrue(result["success"])
                self.assertEqual(result["pet"][field], expected)
                self.assertEqual(pet, starter())

    def test_rejections(self):
        """Check rejection of invalid actions, parameters, and insufficient energy or food."""

        for action, params, reason in [
            ("unsupported_action", {}, "UNKNOWN_ACTION"),
            ("unsupported_action", {"unexpected_parameter": "value"}, "UNKNOWN_ACTION"),
            ("feed", {"food": "pizza"}, "UNKNOWN_FOOD"),
            ("play", {"team": "team-02"}, "INVALID_PARAMETERS"),
        ]:
            with self.subTest(action=action, params=params):
                pet = starter()
                result = act(pet, "team-01", action, params)

                self.assertFalse(result["success"])
                self.assertEqual(result["reason"], reason)
                self.assertEqual(pet, starter())

        pet = starter()
        pet["energy"] = 0

        self.assertEqual(
            act(pet, "team-01", "play", {})["reason"], "INSUFFICIENT_ENERGY"
        )

        pet["inventory"]["cake"] = 0

        self.assertEqual(
            act(pet, "team-01", "feed", {"food": "cake"})["reason"], "NO_FOOD"
        )

    def test_bounds_and_invalid_state(self):
        """Check rest bounds and rejection of invalid health values."""

        pet = starter()

        pet.update(energy=89, fullness=1)

        result = act(pet, "team-01", "rest", {})["pet"]

        self.assertEqual((result["energy"], result["fullness"]), (100, 0))

        for bad in [True, -1, 101, "5", 1.5]:
            pet["health"] = bad

            self.assertFalse(valid_pet(pet, "team-01"))

    def test_decimal_conversion(self):
        """Verify Decimal conversion to int or float according to its fractional part."""

        self.assertEqual(
            plain({"energy": Decimal("8"), "fraction": Decimal("1.5")}),
            {"energy": 8, "fraction": 1.5},
        )


class HandlerTests(unittest.TestCase):
    """Check handler event validation, deduplication, and conflicts."""

    def setUp(self):
        """Prepare a fresh store and feeding event for each handler test."""

        self.store = MemoryStore()
        self.event = {
            "pet_id": "team-01",
            "action": "feed",
            "parameters": {"food": "cake"},
            "operation_id": "test-1",
        }

    def test_duplicate_is_not_charged_twice(self):
        """Verify that repeated IDs return the same result without consuming another cake."""

        first = process(self.event, "team-01", self.store)

        self.assertTrue(first["success"])
        self.assertEqual(first, process(self.event, "team-01", self.store))
        self.assertEqual(self.store.get("team-01")["inventory"]["cake"], 0)
        self.assertEqual(self.store.get("team-01")["version"], 2)

    def test_reused_id_different_action(self):
        """Prevent a feeding operation ID from being reused for rest."""

        process(self.event, "team-01", self.store)
        self.event.update(action="rest", parameters={})

        self.assertEqual(
            process(self.event, "team-01", self.store)["reason"], "OPERATION_CONFLICT"
        )

    def test_concurrent_write(self):
        """Simulate a write conflict and verify that the pet remains unchanged."""

        self.store.conflict = True

        self.assertEqual(
            process(self.event, "team-01", self.store)["reason"], "CONCURRENT_UPDATE"
        )
        self.assertEqual(self.store.get("team-01"), starter())

    def test_wrong_team_and_reserved_items(self):
        """Verify rejection of other teams and reserved record keys."""

        for key in ["team-02", "_config", "_op#test"]:
            self.event["pet_id"] = key

            self.assertEqual(
                process(self.event, "team-01", self.store)["reason"], "WRONG_TEAM"
            )

    def test_bad_requests(self):
        """Reject malformed events without processing an action."""

        for event in [
            None,
            [],
            {},
            {**self.event, "table": "other"},
            {**self.event, "operation_id": []},
            {**self.event, "parameters": []},
        ]:
            self.assertFalse(process(event, "team-01", self.store)["success"])

    def test_inspection_does_not_write(self):
        """Verify that inspection succeeds without adding stored records."""

        self.assertTrue(
            process({"pet_id": "team-01", "action": "inspect"}, "team-01", self.store)[
                "success"
            ]
        )
        self.assertEqual(len(self.store.items), 1)

    def test_missing_seed(self):
        """Verify the NOT_INITIALIZED response when the pet is absent."""

        self.store.items.clear()

        self.assertEqual(
            process(self.event, "team-01", self.store)["reason"], "NOT_INITIALIZED"
        )

    def test_starter_error_has_diagnostics_without_writes(self):
        """Correlate the safe response with the failing starter frame."""

        output = StringIO()
        self.event.update(action="custom", parameters={})
        before = copy.deepcopy(self.store.items)

        with (
            patch.dict("os.environ", TEAM_ID="team-01", TABLE_NAME="test"),
            patch("handler.DynamoStore", return_value=self.store),
            patch.object(self.store, "commit", wraps=self.store.commit) as commit,
            redirect_stdout(output),
        ):
            result = lambda_handler(
                self.event, SimpleNamespace(aws_request_id="request-test")
            )

        log = json.loads(output.getvalue())
        self.assertEqual(result["reason"], "BACKEND_ERROR")
        self.assertFalse(result["success"])
        self.assertEqual(result["request_id"], log["request_id"])
        self.assertEqual(log["request_id"], "request-test")
        self.assertEqual(log["event"], "PET_BACKEND_ERROR")
        self.assertEqual(log["team"], "team-01")
        self.assertEqual(log["exception_type"], "NotImplementedError")
        frame = log["frames"][-1]
        self.assertEqual(frame["file"], "custom_action.py")
        self.assertEqual(frame["function"], "perform")
        source = (ROOT / "lambda/custom_action.py").read_text().splitlines()
        self.assertIn("raise NotImplementedError", source[frame["line"] - 1])
        self.assertNotIn("exception_type", result)
        self.assertNotIn("frames", result)
        self.assertEqual(self.store.items, before)
        commit.assert_not_called()

    def test_error_logs_exclude_exception_message_and_payload(self):
        """Keep diagnostic locations without logging sensitive values."""

        output = StringIO()

        with (
            patch.dict("os.environ", TEAM_ID="team-01", TABLE_NAME="test"),
            patch("handler.DynamoStore", side_effect=RuntimeError("secret-token")),
            redirect_stdout(output),
        ):
            result = lambda_handler(
                {"private": "secret-payload"}, SimpleNamespace(aws_request_id="safe-id")
            )

        log = json.loads(output.getvalue())
        self.assertEqual(log["exception_type"], "RuntimeError")
        self.assertTrue(log["frames"])
        for secret in ("secret-token", "secret-payload"):
            self.assertNotIn(secret, output.getvalue() + json.dumps(result))

    def test_expected_rejection_remains_a_business_result(self):
        """Keep a rule rejection separate from backend failures."""

        self.store.items["team-01"]["energy"] = 100
        self.event.update(action="rest", parameters={})
        output = StringIO()

        with (
            patch.dict("os.environ", TEAM_ID="team-01", TABLE_NAME="test"),
            patch("handler.DynamoStore", return_value=self.store),
            redirect_stdout(output),
        ):
            result = lambda_handler(
                self.event, SimpleNamespace(aws_request_id="rest-id")
            )

        self.assertEqual(result["reason"], "ALREADY_RESTED")
        log = json.loads(output.getvalue())
        self.assertEqual(log["event"], "PET_ACTION_REJECTED")
        self.assertNotIn("exception_type", log)


if __name__ == "__main__":
    unittest.main()
