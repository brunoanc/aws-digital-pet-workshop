"""Check capacity planning and batch execution without AWS."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts.capacity_plan import build_plan
from scripts.capacity_runner import run_batches


class CapacityTests(unittest.TestCase):
    """Keep rehearsal destinations isolated and prevent retries after failures."""

    def setUp(self):
        """Load the public capacity example for each test."""

        self.config = json.loads(Path("config/capacity.example.json").read_text())

    def response(self, team, message):
        """Return synthetic inspection evidence for the requested team."""

        return {
            "success": True,
            "registered_tools": ["inspect_pet"],
            "activity": [
                {
                    "tool": "inspect_pet",
                    "action": "inspect",
                    "result": {
                        "success": True,
                        "pet": {"pet_id": team},
                    },
                }
            ],
        }

    def test_plan_is_isolated(self):
        """Generate fifteen mutation-disabled runtimes with distinct state keys."""

        plan = build_plan(self.config)

        self.assertEqual(len(plan["teams"]), 15)
        self.assertEqual(plan["max_requests"], 32)
        self.assertNotIn("team-01", plan["teams"])
        self.assertEqual(
            len({target["agent_state_key"] for target in plan["teams"].values()}), 15
        )
        self.assertTrue(
            all(
                not target["runtime"]["allow_mutations"]
                for target in plan["teams"].values()
            )
        )

    def test_rejects_scope_and_budget_changes(self):
        """Reject unsafe destinations and expanded request budgets."""

        for key, value in (
            ("account_id", self.config["management_account_id"]),
            ("team_numbers", [1, 2]),
            ("state_prefix", "rehearsal"),
            ("batches", [15, 15, 15]),
            ("pause_seconds", 0),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_plan(self.config | {key: value})

    def test_success_sends_exact_budget(self):
        """Send 32 calls with three cooldowns and no automatic retries."""

        invoke = Mock(side_effect=self.response)
        wait = Mock()
        result = run_batches(build_plan(self.config), invoke, wait)

        self.assertEqual(len(result), 4)
        self.assertEqual(invoke.call_count, 32)
        self.assertEqual(wait.call_count, 3)

    def test_failure_stops_next_batch(self):
        """Finish active calls but stop escalation after missing evidence."""

        invoke = Mock(return_value={"success": False})
        wait = Mock()
        result = run_batches(build_plan(self.config), invoke, wait)

        self.assertEqual(len(result), 1)
        self.assertEqual(invoke.call_count, 2)
        wait.assert_not_called()

    def test_cross_team_evidence_is_rejected(self):
        """Reject a successful response that reports another team's pet."""

        invoke = Mock(return_value=self.response("team-01", ""))
        result = run_batches(build_plan(self.config), invoke, Mock())

        self.assertFalse(result[0]["results"][0]["success"])
