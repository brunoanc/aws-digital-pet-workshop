"""Limit agent tools and record actions without exposing internal reasoning."""

from copy import deepcopy
import time
from uuid import uuid4


class ToolGateway:
    """Apply per-message limits and bind all actions to one backend."""

    def __init__(self, backend, enabled, settings):
        """Validate enabled tools and prepare an empty activity log."""

        self.backend = backend
        self.enabled = frozenset(enabled)
        self.settings = settings

        if self.enabled - {"inspect_pet", "care_for_pet", "custom_action"}:
            raise ValueError("The configuration contains an unknown tool.")

        if self.enabled & {"care_for_pet", "custom_action"} and (
            not settings.allow_mutations or "inspect_pet" not in self.enabled
        ):
            raise ValueError(
                "Enable inspection and authorize mutations before enabling care."
            )

        self.begin()

    def begin(self):
        """Reset limits and deduplication for a new user message."""

        self.events = []
        self.calls = 0
        self.inspected = False
        self.mutation = None
        self.deadline = time.monotonic() + self.settings.timeout_seconds

    def execute(self, name, action="inspect", parameters=None):
        """Validate tools and permit at most one care action per message."""

        parameters = {} if parameters is None else parameters

        if name not in self.enabled:
            return {"success": False, "reason": "TOOL_DISABLED"}

        if (
            time.monotonic() >= self.deadline
            or self.calls >= self.settings.max_tool_calls
        ):
            return {"success": False, "reason": "TOOL_LIMIT"}

        self.calls += 1
        allowed = {"feed": {"food"}, "play": set(), "rest": set()}

        if name == "inspect_pet":
            action, parameters = "inspect", {}
        elif name == "custom_action":
            if parameters:
                return {"success": False, "reason": "INVALID_PARAMETERS"}

            action, parameters = "custom", {}
        elif (
            action not in allowed
            or not isinstance(parameters, dict)
            or set(parameters) - allowed[action]
            or (
                action == "feed"
                and parameters.get("food") not in ("healthy_meal", "cake")
            )
        ):
            return {"success": False, "reason": "INVALID_PARAMETERS"}

        if name != "inspect_pet" and not self.inspected:
            return {"success": False, "reason": "INSPECT_FIRST"}

        signature = (action, tuple(sorted(parameters.items())))

        if name != "inspect_pet" and self.mutation is not None:
            previous, result = self.mutation

            return (
                deepcopy(result)
                if previous == signature
                else {"success": False, "reason": "ONE_ACTION_PER_MESSAGE"}
            )

        operation_id = str(uuid4())

        try:
            result = self.backend.invoke(action, parameters, operation_id)
        except Exception:
            result = {
                "success": False,
                "reason": "OUTCOME_UNKNOWN",
                "message": "No se pudo confirmar el resultado; consulta el estado antes de intentar otra acción.",
            }

        if name == "inspect_pet":
            self.inspected = result.get("success") is True
        else:
            self.mutation = (signature, deepcopy(result))

        self.events.append(
            {
                "tool": name,
                "action": action,
                "parameters": deepcopy(parameters),
                "operation_id": operation_id,
                "result": deepcopy(result),
            }
        )

        return result


def tool_catalog(gateway):
    """Create the team's tool adapters without registering them yet."""

    from strands import tool

    @tool
    def inspect_pet() -> dict:
        """Lee el estado real de tu mascota sin cambiarlo."""

        return gateway.execute("inspect_pet")

    @tool
    def care_for_pet(action: str, food: str = "") -> dict:
        """Cuida la mascota tras consultarla y ejecuta solo una acción por mensaje.

        Args:
            action: Acción feed, play o rest.
            food: Para feed, healthy_meal o cake; vacío para otras acciones.
        """

        parameters = {}

        if food:
            parameters["food"] = food

        return gateway.execute("care_for_pet", action, parameters)

    @tool
    def custom_action() -> dict:
        """Ejecuta tu acción personalizada después de consultar la mascota."""

        return gateway.execute("custom_action", "custom")

    return {
        "inspect_pet": inspect_pet,
        "care_for_pet": care_for_pet,
        "custom_action": custom_action,
    }


def registered_tools(gateway):
    """Register only enabled tools without exposing targets to the model."""

    tools = tool_catalog(gateway)

    return [tools[name] for name in sorted(gateway.enabled)]
