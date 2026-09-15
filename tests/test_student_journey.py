"""Test checkpoints and custom actions with the real SDK and simulated services."""

from copy import deepcopy
from contextlib import redirect_stdout
from dataclasses import replace
from io import BytesIO, StringIO
import json
from pathlib import Path
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import boto3
from strands import Agent
from strands.models import BedrockModel

from app.agent import PetConversation, visible_answer
from app.backend import PetBackend
from app.config import load_settings
from app.tools import ToolGateway
from test_pet import MemoryStore, act, lambda_handler, process, starter


ROOT = Path(__file__).resolve().parents[1]


class StudentJourneyTests(unittest.TestCase):
    """Verify prompt authorship, limits, and simulated persistence without AWS resources."""

    def setUp(self):
        """Prepare a model without real credentials and a custom action solution."""

        self.settings = replace(
            load_settings(ROOT / "scripts/config_defaults/app.json"), allow_mutations=True
        )
        self.backend = Mock()
        self.backend.session = boto3.Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            region_name="us-east-1",
        )
        self.perform = runpy.run_path(str(ROOT / "checkpoints/custom_action.py"))[
            "perform"
        ]

    def test_every_checkpoint_builds_and_preserves_prompt(self):
        """Build every solution and verify that the runtime preserves its prompt."""

        stages = [
            ("01_conversation.py", []),
            ("02_prompt.py", []),
            ("03_inspect.py", ["inspect_pet"]),
            ("04_care.py", ["inspect_pet", "care_for_pet"]),
            ("05_custom.py", ["inspect_pet", "care_for_pet", "custom_action"]),
        ]

        for filename, expected in stages:
            factory = runpy.run_path(str(ROOT / "checkpoints" / filename))[
                "create_agent"
            ]
            conversation = PetConversation(
                self.settings,
                self.backend,
                "ESTO NO DEBE SER EL PROMPT",
                expected,
                agent_factory=factory,
            )

            self.assertEqual(conversation.gateway.enabled, frozenset(expected))
            self.assertNotIn("ESTO NO DEBE", conversation.agent.system_prompt or "")

    def test_constructor_requires_operational_options(self):
        """Reject constructors that enable default callbacks or retries."""

        def incomplete(model_options, **helpers):
            """Simulate a constructor that omits the prepared operational controls."""

            model = BedrockModel(
                model_id=self.settings.model_id,
                max_tokens=512,
                temperature=0.3,
                **model_options,
            )

            return Agent(model=model, tools=[])

        with self.assertRaises(ValueError):
            PetConversation(
                self.settings, self.backend, "No usar", [], agent_factory=incomplete
            )

    def test_plain_output_without_secret_envelope(self):
        """Accept ordinary final text while excluding recognizable reasoning fields and blocks."""

        self.assertEqual(
            visible_answer(
                {
                    "content": [
                        {"reasoningContent": {"text": "oculto"}},
                        {"text": "Hola, Chispa."},
                    ]
                },
                False,
            ),
            "Hola, Chispa.",
        )
        self.assertEqual(
            visible_answer(
                {"content": [{"text": "<thinking>oculto</thinking>Hola."}]}, False
            ),
            "Hola.",
        )

        for text in ("<thinking>oculto", "<response>incompleto", "<otro>oculto</otro>"):
            self.assertNotIn(
                "oculto", visible_answer({"content": [{"text": text}]}, False)
            )

    def test_custom_rule_success_rejection_and_replay(self):
        """Apply effects once, preserve inventory, and reject insufficient energy without writes."""

        store = MemoryStore()
        event = {
            "pet_id": "team-01",
            "action": "custom",
            "parameters": {},
            "operation_id": "custom-test",
        }

        with patch("rules.perform", self.perform):
            first = process(event, "team-01", store)
            replay = process(event, "team-01", store)

            self.assertEqual(first, replay)
            self.assertEqual(first["pet"]["energy"], starter()["energy"] - 10)
            self.assertEqual(first["pet"]["experience"], starter()["experience"] + 20)
            self.assertEqual(first["pet"]["version"], 2)
            self.assertEqual(first["pet"]["inventory"], starter()["inventory"])

            store.items["team-01"]["energy"] = 0
            before = deepcopy(store.items)
            rejected = process(dict(event, operation_id="low-energy"), "team-01", store)

            self.assertEqual(rejected["reason"], "NEEDS_REST")
            self.assertEqual(store.items, before)

    def test_clean_starter_progresses_from_exception_to_authored_action(self):
        """Complete the pending implementation without resetting stored progress."""

        store = MemoryStore()
        initial = deepcopy(store.items)
        pending = runpy.run_path(str(ROOT / "lambda/custom_action.py"))["perform"]
        event = {
            "pet_id": "team-01",
            "action": "custom",
            "parameters": {},
            "operation_id": "pending-custom",
        }

        with patch("rules.perform", pending):
            with self.assertRaises(NotImplementedError):
                process(event, "team-01", store)

        self.assertEqual(store.items, initial)

        with patch("rules.perform", self.perform):
            completed = process(
                dict(event, operation_id="implemented-custom"), "team-01", store
            )

        self.assertTrue(completed["success"])
        self.assertEqual(completed["pet"]["version"], starter()["version"] + 1)
        self.assertEqual(completed["pet"]["energy"], starter()["energy"] - 10)
        self.assertEqual(completed["pet"]["experience"], starter()["experience"] + 20)
        self.assertEqual(completed["pet"]["inventory"], starter()["inventory"])
        self.assertNotIn("_op#pending-custom", store.items)
        self.assertIn("_op#implemented-custom", store.items)

    def test_custom_contract_prevents_arbitrary_state_changes(self):
        """Reject changes outside the contract without modifying the input pet."""

        for changes in (
            {"pet_id": 1},
            {"version": 1},
            {"inventory": 1},
            {"energy": True},
            {"energy": 36},
            {"energy": -36},
            {},
            {"experience": -1},
        ):
            pet = starter()

            with patch(
                "rules.perform",
                return_value={"success": True, "changes": changes, "message": "Prueba"},
            ):
                self.assertEqual(
                    act(pet, "team-01", "custom", {})["reason"], "INVALID_RULE"
                )

            self.assertEqual(pet, starter())

        with self.assertRaises(NotImplementedError):
            act(starter(), "team-01", "custom", {})

    def test_custom_shares_mutation_budget_with_care(self):
        """Require inspection and share a single mutation budget across writing tools."""

        self.backend.invoke.return_value = {"success": True}
        gateway = ToolGateway(
            self.backend,
            ["inspect_pet", "care_for_pet", "custom_action"],
            self.settings,
        )

        self.assertEqual(gateway.execute("custom_action")["reason"], "INSPECT_FIRST")

        gateway.begin()
        gateway.execute("inspect_pet")
        gateway.execute("custom_action")

        self.assertEqual(
            gateway.execute("care_for_pet", "rest")["reason"], "ONE_ACTION_PER_MESSAGE"
        )
        self.assertEqual(self.backend.invoke.call_count, 2)

    def test_backend_error_reaches_tool_activity_with_request_id(self):
        """Preserve the Lambda diagnostic ID through the backend and tool activity."""

        store = MemoryStore()
        output = StringIO()
        session = Mock()
        session.get_partition_for_region.return_value = "aws"
        backend = PetBackend(self.settings, session)

        def invoke(**kwargs):
            event = json.loads(kwargs["Payload"])
            result = lambda_handler(event, SimpleNamespace(aws_request_id="pet-request"))
            return {"StatusCode": 200, "Payload": BytesIO(json.dumps(result).encode())}

        backend.client.invoke.side_effect = invoke
        gateway = ToolGateway(backend, ["inspect_pet", "custom_action"], self.settings)

        with (
            patch.dict("os.environ", TEAM_ID="team-01", TABLE_NAME="test"),
            patch("handler.DynamoStore", return_value=store),
            redirect_stdout(output),
        ):
            gateway.execute("inspect_pet")
            result = gateway.execute("custom_action")
            repeated = gateway.execute("custom_action")

        self.assertEqual(result["reason"], "BACKEND_ERROR")
        self.assertEqual(result["request_id"], "pet-request")
        self.assertEqual(gateway.events[-1]["result"], result)
        self.assertNotEqual(gateway.events[-1]["operation_id"], result["request_id"])
        self.assertEqual(result, repeated)
        self.assertEqual(backend.client.invoke.call_count, 2)
        self.assertEqual(store.items, {"team-01": starter()})
        error_log = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(error_log["request_id"], result["request_id"])

    def test_real_sdk_selects_custom_action_and_persists_once(self):
        """Exercise the simulated model, real SDK, gateway, rules, and store without external calls."""

        store = MemoryStore()

        def invoke(action, parameters, operation_id):
            """Route tools to the real handler with in-memory storage."""

            return process(
                {
                    "pet_id": "team-01",
                    "action": action,
                    "parameters": parameters,
                    "operation_id": operation_id,
                },
                "team-01",
                store,
            )

        self.backend.invoke.side_effect = invoke
        steps = iter(["inspect_pet", "custom_action", None])

        async def stream(model, *args, **kwargs):
            """Emit inspection, custom action, and final text as simulated Bedrock events."""

            step = next(steps)

            yield {"messageStart": {"role": "assistant"}}

            if step:
                yield {
                    "contentBlockStart": {
                        "start": {"toolUse": {"toolUseId": step, "name": step}}
                    }
                }
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            else:
                yield {"contentBlockStart": {"start": {}}}
                yield {
                    "contentBlockDelta": {
                        "delta": {"text": "Tu mascota practicó su hechizo."}
                    }
                }

            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use" if step else "end_turn"}}
            yield {
                "metadata": {
                    "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                    "metrics": {"latencyMs": 1},
                }
            }

        factory = runpy.run_path(str(ROOT / "checkpoints/05_custom.py"))["create_agent"]

        with (
            patch.object(BedrockModel, "stream", stream),
            patch("rules.perform", self.perform),
        ):
            conversation = PetConversation(
                self.settings,
                self.backend,
                "Ignorado",
                ["inspect_pet", "care_for_pet", "custom_action"],
                agent_factory=factory,
            )

            self.assertEqual(
                conversation.send("Practica tu hechizo"),
                "Tu mascota practicó su hechizo.",
            )
            self.assertEqual(
                [event["action"] for event in conversation.gateway.events],
                ["inspect", "custom"],
            )
            self.assertEqual(store.items["team-01"]["version"], 2)
            self.assertFalse(conversation.failed)


if __name__ == "__main__":
    unittest.main()
