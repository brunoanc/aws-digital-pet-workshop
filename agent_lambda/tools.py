"""Define las tools que cada equipo puede importar en su agente."""

from strands import tool
from strands.types.tools import ToolContext

from app.tools import ToolGateway


def gateway_for(tool_context):
    """Busca el gateway del mensaje sin compartirlo entre equipos."""

    gateway = tool_context.invocation_state.get("pet_gateway")

    if not isinstance(gateway, ToolGateway):
        raise ValueError("Falta el gateway del equipo en el contexto de la tool.")

    return gateway


@tool(context=True)
def inspect_pet(tool_context: ToolContext) -> dict:
    """Lee el estado real de tu mascota sin cambiarlo."""

    return gateway_for(tool_context).execute("inspect_pet")


@tool(context=True)
def care_for_pet(
    tool_context: ToolContext, action: str, food: str = ""
) -> dict:
    """Cuida la mascota tras consultarla y ejecuta solo una acción por mensaje.

    Args:
        action: Acción feed, play o rest.
        food: Para feed, healthy_meal o cake; vacío para otras acciones.
    """

    parameters = {}

    if food:
        parameters["food"] = food

    return gateway_for(tool_context).execute("care_for_pet", action, parameters)


@tool(context=True)
def custom_action(tool_context: ToolContext) -> dict:
    """Ejecuta tu acción personalizada después de consultar la mascota."""

    return gateway_for(tool_context).execute("custom_action", "custom")
