"""Check the starter exercise against the local agent dependencies."""

from pathlib import Path
import tomllib
import unittest

from agent_lambda import agent_builder
from agent_lambda.tools import care_for_pet
from app.tools import tool_catalog


ROOT = Path(__file__).resolve().parents[1]


class AgentBuilderTests(unittest.TestCase):
    """Verify that the starter registers no tools and does not invoke the model."""

    def test_care_schema_parameters(self):
        """Expose only the supported care parameters to the model."""

        for tool in (care_for_pet, tool_catalog(None)["care_for_pet"]):
            schema = tool.tool_spec["inputSchema"]["json"]

            self.assertEqual(set(schema["properties"]), {"action", "food"})
            self.assertEqual(schema["required"], ["action"])

    def test_starter_is_unfinished(self):
        """Leave the agent factory for the participant to implement."""

        self.assertFalse(hasattr(agent_builder, "create_agent"))

    def test_layer_versions_match_local_app(self):
        """Prevent direct dependency versions from diverging between the local agent and its layer."""

        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        requirements = (
            (ROOT / "agent_lambda/layer/requirements.in").read_text().splitlines()
        )
        dependencies = {
            line for line in requirements if line and not line.startswith("#")
        }
        expected = {
            line
            for line in project["project"]["dependencies"]
            if line.startswith(("strands-agents==", "boto3=="))
        }

        self.assertEqual(dependencies, expected)


if __name__ == "__main__":
    unittest.main()
