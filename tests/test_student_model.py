"""Validate explicit model selection and operational controls without AWS calls."""

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock

import boto3
from strands import Agent
from strands.models import BedrockModel

from app.agent import PetConversation
from app.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


class StudentModelTests(unittest.TestCase):
    """Verify that student model choices remain within workshop limits."""

    def setUp(self):
        """Prepare a fake session and configuration without invoking services."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")
        self.backend = Mock()
        self.backend.session = boto3.Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            region_name="us-east-1",
        )

    def build(self, selection, connection=True, settings=None):
        """Build an agent with student options to test validation."""

        def factory(model_options, runtime_options, **tools):
            """Select a model and leave the agent without tools for this test."""

            options = (
                model_options if connection else {"boto_session": self.backend.session}
            )
            model = BedrockModel(**selection, **options)

            return Agent(
                model=model,
                tools=[],
                system_prompt="Mi prompt propio.",
                **runtime_options,
            )

        return PetConversation(
            settings or self.settings,
            self.backend,
            "Ignorado",
            [],
            agent_factory=factory,
        )

    def test_student_settings_are_not_replaced(self):
        """Preserve authored parameters and accept another model ID when authorized."""

        for identifier in (self.settings.model_id, "amazon.nova-micro-v1:0"):
            selection = {"model_id": identifier, "temperature": 0.7, "max_tokens": 128}
            conversation = self.build(
                selection, settings=replace(self.settings, model_id=identifier)
            )
            config = conversation.agent.model.get_config()

            self.assertEqual({key: config[key] for key in selection}, selection)
            self.assertEqual(conversation.agent.system_prompt, "Mi prompt propio.")
            self.backend.invoke.assert_not_called()

    def test_invalid_selection_is_rejected_before_inference(self):
        """Reject unauthorized models and missing or excessive limits before inference."""

        valid = {
            "model_id": self.settings.model_id,
            "temperature": 0.3,
            "max_tokens": 512,
        }

        for change in (
            {"model_id": "amazon.nova-pro-v1:0"},
            {"max_tokens": 513},
            {"max_tokens": True},
            {"temperature": -1},
            {"temperature": float("nan")},
            {"additional_request_fields": {"max_tokens": 9999}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.build(valid | change)

        with self.assertRaises(ValueError):
            self.build(valid, connection=False)

        self.backend.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
