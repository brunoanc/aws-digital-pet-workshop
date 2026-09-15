"""Check that imported tools do not share team context across executions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import Mock

from agent_lambda.tools import care_for_pet, custom_action, gateway_for, inspect_pet
from app.config import load_settings
from app.tools import ToolGateway


ROOT = Path(__file__).resolve().parents[1]


class ImportedToolsTests(unittest.TestCase):
    """Validate isolated tool context and schemas without operational details."""

    def test_context_is_not_a_model_parameter(self):
        """Exclude internal context from the model-facing schema."""

        for function in (inspect_pet, care_for_pet, custom_action):
            schema = function.tool_spec["inputSchema"]["json"]

            self.assertNotIn("tool_context", schema.get("properties", {}))
            self.assertNotIn("pet_gateway", str(schema))

    def test_two_contexts_keep_separate_backends(self):
        """Run the same imported tool for two teams without mixing targets."""

        settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        contexts = []

        for team in ("team-01", "team-02"):
            backend = Mock()
            backend.invoke.return_value = {"success": True, "pet": {"pet_id": team}}

            contexts.append(
                Mock(
                    invocation_state={
                        "pet_gateway": ToolGateway(backend, ["inspect_pet"], settings)
                    }
                )
            )

        def inspect(context):
            """Invoke the adapter with this request's independent context."""

            return inspect_pet(tool_context=context)["pet"]["pet_id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(inspect, contexts))

        self.assertEqual(results, ["team-01", "team-02"])

        for context in contexts:
            gateway_for(context).backend.invoke.assert_called_once()

    def test_missing_context_fails_closed(self):
        """Reject unbound tools instead of reusing the last team's context."""

        with self.assertRaises(ValueError):
            inspect_pet(tool_context=Mock(invocation_state={}))


if __name__ == "__main__":
    unittest.main()
