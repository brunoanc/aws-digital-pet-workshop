"""Build a fixed read-only agent for capacity tests."""

import json
import os

from strands import Agent
from strands.models import BedrockModel

from agent_lambda.tools import inspect_pet
from app.config import settings_from_dict


def create_agent(model_options, runtime_options):
    """Use the reviewed runtime settings and register only pet inspection."""

    settings = settings_from_dict(json.loads(os.environ["APP_SETTINGS"]))

    if settings.allow_mutations:
        raise ValueError("Capacity agents must disable mutations.")

    model = BedrockModel(
        model_id=settings.model_id,
        temperature=settings.temperature,
        max_tokens=settings.max_output_tokens,
        **model_options,
    )

    return Agent(
        model=model,
        system_prompt=settings.personality,
        tools=[inspect_pet],
        **runtime_options,
    )
