"""Test shared runtime controls and the Strands loop without AWS requests."""

from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import boto3
from strands.models import BedrockModel

from app.agent import PetConversation, system_prompt, visible_answer
from app.backend import PetBackend
from app.config import load_settings
from app.tools import ToolGateway, registered_tools


ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    """Check limits, isolation, visible output, and action tracking."""

    def setUp(self):
        """Prepare public settings and a simulated backend without real credentials."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")

        self.backend = Mock()
        self.backend.invoke.return_value = {
            "success": True,
            "pet": {"pet_id": "team-01", "name": "Chispa"},
        }
        self.backend.session = boto3.Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            region_name="us-east-1",
        )

    def gateway(self, enabled=("inspect_pet", "care_for_pet")):
        """Create a mutation-authorized adapter for simulated tests."""

        return ToolGateway(
            self.backend, enabled, replace(self.settings, allow_mutations=True)
        )

    def test_config_defaults_and_rejections(self):
        """Check read-only mode and reject invalid limits or targets."""

        self.assertFalse(self.settings.allow_mutations)

        original = (ROOT / "scripts/config_defaults/app.json").read_text()

        for key, value in (
            ("account_id", 123),
            ("max_messages", True),
            ("temperature", float("nan")),
            ("model_id", "us.amazon.nova-lite-v1:0"),
            ("allow_mutations", "false"),
        ):
            data = json.loads(original)
            data[key] = value

            with patch("app.config.Path.read_text", return_value=json.dumps(data)):
                with self.assertRaises(ValueError):
                    load_settings("unused")

    def test_disabled_tools_and_mutation_consent(self):
        """Prevent unauthorized care registration and disabled tool execution."""

        gateway = self.gateway(())

        self.assertEqual(registered_tools(gateway), [])
        self.assertEqual(gateway.execute("inspect_pet")["reason"], "TOOL_DISABLED")
        self.backend.invoke.assert_not_called()

        with self.assertRaises(ValueError):
            ToolGateway(self.backend, ["inspect_pet", "care_for_pet"], self.settings)

    def test_prompts_match_registered_capabilities(self):
        """Include the supplied personality and only the available tool names."""

        personality = "Sé amable."
        offline = system_prompt(personality, [])
        read_only = system_prompt(personality, ["inspect_pet"])
        care = system_prompt(personality, ["inspect_pet", "care_for_pet"])

        self.assertNotIn("inspect_pet", offline)
        self.assertNotIn("care_for_pet", offline)
        self.assertIn("inspect_pet", read_only)
        self.assertNotIn("care_for_pet", read_only)
        self.assertIn("inspect_pet", care)
        self.assertIn("care_for_pet", care)

        for prompt in (offline, read_only, care):
            self.assertIn(personality, prompt)

    def test_inspection_required(self):
        """Reject care before a successful inspection in the same message."""

        gateway = self.gateway()

        self.assertEqual(
            gateway.execute("care_for_pet", "rest")["reason"], "INSPECT_FIRST"
        )
        self.backend.invoke.assert_not_called()

    def test_one_mutation_and_replay(self):
        """Return the previous care result without invoking Lambda again."""

        gateway = self.gateway()

        gateway.execute("inspect_pet")

        first = gateway.execute("care_for_pet", "rest")

        self.assertEqual(gateway.execute("care_for_pet", "rest"), first)
        self.assertEqual(self.backend.invoke.call_count, 2)
        self.assertEqual(gateway.execute("inspect_pet")["reason"], "TOOL_LIMIT")

    def test_different_second_mutation_rejected(self):
        """Reject a different second action even when tool budget remains."""

        gateway = self.gateway()

        gateway.execute("inspect_pet")
        gateway.execute("care_for_pet", "rest")

        self.assertEqual(
            gateway.execute("care_for_pet", "play")["reason"], "ONE_ACTION_PER_MESSAGE"
        )

    def test_cross_team_and_invalid_actions(self):
        """Reject target parameters and actions outside the care contract."""

        gateway = self.gateway()

        for action, parameters in (
            ("rest", {"pet_id": "team-02"}),
            ("unsupported_action", {}),
            ("unsupported_action", {"unexpected_parameter": "value"}),
            ("rest", {"unexpected_parameter": "value"}),
        ):
            with self.subTest(action=action, parameters=parameters):
                gateway.begin()

                self.assertEqual(
                    gateway.execute("care_for_pet", action, parameters)["reason"],
                    "INVALID_PARAMETERS",
                )

        self.backend.invoke.assert_not_called()

    def test_unknown_outcome_is_not_retried(self):
        """Preserve unknown outcomes without repeating a possibly applied mutation."""

        gateway = self.gateway()

        gateway.execute("inspect_pet")

        self.backend.invoke.side_effect = TimeoutError("private backend details")
        first = gateway.execute("care_for_pet", "rest")

        self.assertEqual(first["reason"], "OUTCOME_UNKNOWN")
        self.assertEqual(gateway.execute("care_for_pet", "rest"), first)
        self.assertNotIn("private", str(gateway.events))
        self.assertEqual(self.backend.invoke.call_count, 2)

    def test_expired_deadline(self):
        """Prevent further invocations when the message deadline expires."""

        gateway = self.gateway()
        gateway.deadline = 0

        self.assertEqual(gateway.execute("inspect_pet")["reason"], "TOOL_LIMIT")
        self.backend.invoke.assert_not_called()

    def test_output_filter(self):
        """Show only complete final answers and hide internal or truncated content."""

        self.assertEqual(
            visible_answer(
                {
                    "content": [
                        {"reasoningContent": {"text": "hidden"}},
                        {
                            "text": "<thinking>hidden</thinking><response>¡Hola, Chispa!</response>"
                        },
                    ]
                }
            ),
            "¡Hola, Chispa!",
        )

        for text in (
            "<thinking>hidden",
            "<response>unfinished",
            "hidden",
            "<response><thinking>hidden</response>",
        ):
            self.assertNotIn("hidden", visible_answer({"content": [{"text": text}]}))

    def test_conversation_limits(self):
        """Verify cycle and message limits without retries."""

        with patch("strands.Agent") as agent_class:
            agent_class.return_value.return_value = Mock(
                stop_reason="end_turn",
                message={"content": [{"text": "<response>Hola.</response>"}]},
            )
            conversation = PetConversation(
                replace(self.settings, max_messages=1),
                self.backend,
                self.settings.personality,
                [],
            )

            self.assertEqual(conversation.send("Hola"), "Hola.")
            self.assertEqual(
                agent_class.return_value.call_args.kwargs["limits"], {"turns": 4}
            )
            self.assertIsNone(agent_class.call_args.kwargs["retry_strategy"])

            with self.assertRaises(ValueError):
                conversation.send("Otra vez")

            self.assertEqual(agent_class.return_value.call_count, 1)

    def test_limit_stop_preserves_activity(self):
        """Mark incomplete conversations to prevent continuation with ambiguous history."""

        with patch("strands.Agent") as agent_class:
            agent_class.return_value.return_value = Mock(stop_reason="limit_turns")
            conversation = PetConversation(
                self.settings, self.backend, self.settings.personality, []
            )

            self.assertIn("límite", conversation.send("Hola"))
            self.assertTrue(conversation.failed)

            with self.assertRaises(ValueError):
                conversation.send("Continúa")

    def test_fixed_backend_target(self):
        """Verify that invocation ARNs and pet IDs come from local configuration."""

        session = Mock()
        session.get_partition_for_region.return_value = "aws"
        client = session.client.return_value
        client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": io.BytesIO(
                json.dumps(self.backend.invoke.return_value).encode()
            ),
        }
        backend = PetBackend(self.settings, session)

        backend.invoke("inspect", {}, "test-operation")

        arguments = client.invoke.call_args.kwargs

        self.assertEqual(
            arguments["FunctionName"],
            "arn:aws:lambda:us-east-1:111122223333:function:dp-rehearsal-team-01",
        )
        self.assertEqual(json.loads(arguments["Payload"])["pet_id"], "team-01")

    def test_preflight_wrong_account(self):
        """Stop before querying Lambda if STS reports a different account."""

        session = Mock()
        session.get_partition_for_region.return_value = "aws"
        session.client.return_value.get_caller_identity.return_value = {
            "Account": "999999999999"
        }
        backend = PetBackend(self.settings, session)

        with self.assertRaises(ValueError):
            backend.preflight()

        session.client.return_value.get_function_configuration.assert_not_called()

    def test_real_strands_loop_with_simulated_model(self):
        """Run the real SDK with simulated inspection, care, and final responses."""

        steps = iter([("inspect_pet", {}), ("care_for_pet", {"action": "rest"}), None])

        async def stream(model, *args, **kwargs):
            """Emit simulated model events without contacting Bedrock."""

            step = next(steps)

            yield {"messageStart": {"role": "assistant"}}

            if step:
                tool_name, arguments = step

                yield {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {"toolUseId": tool_name, "name": tool_name}
                        }
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "delta": {"toolUse": {"input": json.dumps(arguments)}}
                    }
                }
            else:
                yield {"contentBlockStart": {"start": {}}}
                yield {
                    "contentBlockDelta": {
                        "delta": {
                            "text": "<thinking>hidden</thinking><response>Chispa descansó.</response>"
                        }
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

        with patch.object(BedrockModel, "stream", stream):
            conversation = PetConversation(
                replace(self.settings, allow_mutations=True),
                self.backend,
                self.settings.personality,
                ["inspect_pet", "care_for_pet"],
            )

            self.assertEqual(
                conversation.send("Consulta y descansa."), "Chispa descansó."
            )

        self.assertEqual(
            [call.args[0] for call in self.backend.invoke.call_args_list],
            ["inspect", "rest"],
        )
        self.assertEqual(len(conversation.gateway.events), 2)



if __name__ == "__main__":
    unittest.main()
