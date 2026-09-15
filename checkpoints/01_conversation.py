"""Muestra una solución de rescate para la etapa 1 del agente."""

from strands import Agent
from strands.models import BedrockModel


def create_agent(model_options, runtime_options):
    """Construye un agente sin prompt propio ni tools."""

    model = BedrockModel(
        model_id="amazon.nova-lite-v1:0",
        temperature=0.3,
        max_tokens=512,
        **model_options,
    )

    agent = Agent(
        model=model,
        tools=[],
        **runtime_options,
    )

    return agent
