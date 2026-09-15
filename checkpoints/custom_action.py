"""Muestra una acción propia que devuelve cambios sin llamar a AWS."""


def perform(pet):
    """Devuelve los efectos del hechizo o lo rechaza si falta energía."""

    if pet["energy"] < 10:
        return {
            "success": False,
            "reason": "NEEDS_REST",
            "message": "Necesito descansar antes de practicar mi hechizo.",
        }

    return {
        "success": True,
        "changes": {"energy": -10, "experience": 20},
        "message": "Tu mascota practicó su hechizo y ganó experiencia.",
    }
