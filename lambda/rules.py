"""Define y valida las reglas de cuidado de la mascota."""

from copy import deepcopy

from custom_action import perform

STATS = ("health", "fullness", "energy", "happiness")


def reject(reason, message, pet=None):
    """Devuelve un rechazo con su código y mensaje."""

    result = {"success": False, "reason": reason, "message": message}

    if pet is not None:
        result["pet"] = deepcopy(pet)

    return result


def valid_pet(pet, team_id):
    """Comprueba el equipo, los campos obligatorios y los límites de la mascota."""

    if not isinstance(pet, dict) or pet.get("pet_id") != team_id:
        return False

    for field in STATS:
        if type(pet.get(field)) is not int or not 0 <= pet[field] <= 100:
            return False

    for field, minimum in (("version", 1), ("experience", 0)):
        if type(pet.get(field)) is not int or not minimum <= pet[field] <= 10**9:
            return False

    if any(
        not isinstance(pet.get(field), str) or not 1 <= len(pet[field]) <= 100
        for field in ("name", "species")
    ):
        return False

    inventory = pet.get("inventory")

    return isinstance(inventory, dict) and all(
        type(inventory.get(food)) is int and 0 <= inventory[food] <= 1000
        for food in ("healthy_meal", "cake")
    )


def act(pet, team_id, action, parameters):
    """Valida la acción y calcula sus cambios sin guardarlos en DynamoDB."""

    if not valid_pet(pet, team_id):
        return reject(
            "INVALID_STATE",
            "Los datos de la mascota no son válidos; pide ayuda al organizador.",
        )

    if not isinstance(parameters, dict):
        return reject("INVALID_PARAMETERS", "Los parámetros deben ser un objeto.")

    allowed = {
        "inspect": set(),
        "feed": {"food"},
        "play": set(),
        "rest": set(),
        "custom": set(),
    }

    if action not in allowed:
        return reject("UNKNOWN_ACTION", "Esa acción no está disponible.")

    if set(parameters) - allowed[action]:
        return reject(
            "INVALID_PARAMETERS", "La acción recibió parámetros desconocidos."
        )

    result = deepcopy(pet)

    if action == "inspect":
        return {
            "success": True,
            "message": "Este es el estado actual de tu mascota.",
            "pet": result,
        }

    if action == "custom":
        outcome = perform(deepcopy(pet))

        if not isinstance(outcome, dict) or type(outcome.get("success")) is not bool:
            return reject(
                "INVALID_RULE",
                "La acción debe devolver success, message y changes o reason.",
                pet,
            )

        message = outcome.get("message")

        if not isinstance(message, str) or not 1 <= len(message) <= 500:
            return reject(
                "INVALID_RULE",
                "La acción necesita un mensaje de entre 1 y 500 caracteres.",
                pet,
            )

        if not outcome["success"]:
            reason = outcome.get("reason")

            if (
                set(outcome) != {"success", "reason", "message"}
                or not isinstance(reason, str)
                or not 1 <= len(reason) <= 64
            ):
                return reject(
                    "INVALID_RULE",
                    "El rechazo necesita success, reason y message.",
                    pet,
                )

            return reject(reason, message, pet)

        changes = outcome.get("changes")

        if (
            set(outcome) != {"success", "changes", "message"}
            or not isinstance(changes, dict)
            or not changes
            or set(changes) - set(STATS + ("experience",))
            or any(
                type(delta) is not int or not -35 <= delta <= 35
                for delta in changes.values()
            )
        ):
            return reject(
                "INVALID_RULE",
                "Usa cambios enteros entre -35 y 35 solo en estadísticas o experiencia.",
                pet,
            )

    elif action == "feed":
        food = parameters.get("food")

        if food not in ("healthy_meal", "cake"):
            return reject("UNKNOWN_FOOD", "Elige healthy_meal o cake.", pet)

        if pet["inventory"][food] < 1:
            return reject("NO_FOOD", "No queda esa comida en el inventario.", pet)

        if pet["fullness"] >= 90:
            return reject("ALREADY_FULL", "Tu mascota ya está llena.", pet)

        result["inventory"][food] -= 1
        changes = (
            {"fullness": 35, "health": 5, "happiness": 3}
            if food == "healthy_meal"
            else {"fullness": 15, "health": -3, "happiness": 12}
        )
        message = "Tu mascota disfrutó su comida."
    elif action == "rest":
        if pet["energy"] >= 90:
            return reject(
                "ALREADY_RESTED", "Tu mascota ya tiene suficiente energía.", pet
            )

        changes, message = (
            {"energy": 35, "fullness": -10},
            "Tu mascota descansó y recuperó energía.",
        )
    elif action == "play":
        if pet["energy"] < 20:
            return reject(
                "INSUFFICIENT_ENERGY", "Tu mascota necesita descansar primero.", pet
            )

        changes = {"energy": -20, "happiness": 20, "fullness": -10, "experience": 10}
        message = "Tu mascota jugó contigo."

    for field, delta in changes.items():
        result[field] += delta

    for field in STATS:
        result[field] = max(0, min(100, result[field]))

    result["version"] += 1

    if not valid_pet(result, team_id):
        return reject(
            "INVALID_RULE",
            "La acción generó datos inválidos; revisa los cambios con el organizador.",
        )

    return {"success": True, "message": message, "pet": result}
