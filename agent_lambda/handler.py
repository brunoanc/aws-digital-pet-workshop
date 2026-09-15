"""Ejecuta el agente del equipo con un mensaje nuevo en cada llamada."""

from dataclasses import replace
import json
import os
import traceback

import boto3

from app.agent import PetConversation
from app.backend import PetBackend
from app.config import settings_from_dict


def handle(event, context):
    """Valida el mensaje y ejecuta el agente que escribió el equipo."""

    settings = settings_from_dict(json.loads(os.environ["APP_SETTINGS"]))

    if (
        not isinstance(event, dict)
        or set(event) != {"message"}
        or not isinstance(event["message"], str)
        or not event["message"].strip()
        or len(event["message"]) > settings.max_input_chars
    ):
        return {
            "success": False,
            "reason": "INVALID_REQUEST",
            "message": "Envía solo el campo message con texto no vacío y dentro del límite.",
        }

    remaining = int(context.get_remaining_time_in_millis() / 1000) - 10

    if remaining < 10:
        return {
            "success": False,
            "reason": "TIME_LIMIT",
            "message": "No queda tiempo para iniciar otra consulta.",
        }

    settings = replace(
        settings, timeout_seconds=min(settings.timeout_seconds, remaining)
    )
    session = boto3.Session(region_name=settings.region)
    backend = PetBackend(settings, session)

    backend.preflight()

    allowed = (
        ["inspect_pet", "care_for_pet", "custom_action"]
        if settings.allow_mutations
        else ["inspect_pet"]
    )

    from agent_lambda import agent_builder

    factory = getattr(agent_builder, "create_agent", None)

    if not callable(factory):
        raise NotImplementedError("Escribe la función create_agent antes de continuar.")

    conversation = PetConversation(
        settings, backend, settings.personality, allowed, agent_factory=factory
    )
    answer = conversation.send(event["message"])

    return {
        "success": not conversation.failed,
        "message": answer,
        "registered_tools": sorted(conversation.gateway.enabled),
        "activity": conversation.gateway.events,
    }


def lambda_handler(event, context):
    """Recibe el mensaje y registra éxito o error sin guardar el prompt en logs."""

    is_http = (
        isinstance(event, dict)
        and event.get("version") == "2.0"
        and "requestContext" in event
    )

    if is_http:
        try:
            if (
                event.get("requestContext", {}).get("http", {}).get("method") != "POST"
                or event.get("rawPath") != "/"
                or event.get("rawQueryString", "")
                or event.get("isBase64Encoded", False) is not False
                or not isinstance(event.get("body"), str)
                or len(event["body"].encode("utf-8")) > 131072
            ):
                raise ValueError("Ese formato HTTP no está permitido.")

            event = json.loads(event["body"])
        except (ValueError, TypeError, AttributeError):
            return http_response(
                {
                    "success": False,
                    "reason": "INVALID_REQUEST",
                    "message": "Envía un mensaje JSON mediante POST.",
                },
                400,
            )

    try:
        result = handle(event, context)
    except NotImplementedError:
        result = {
            "success": False,
            "reason": "AGENT_NOT_READY",
            "message": "Completa create_agent y pulsa Deploy antes de probar tu agente.",
        }
    except Exception as error:
        log_error(error, context.aws_request_id)

        result = {
            "success": False,
            "reason": "AGENT_ERROR",
            "message": "El agente falló; revisa el código y el estado antes de repetir un cuidado.",
        }

    print(
        json.dumps(
            {
                "event": "TEAM_AGENT_RESULT",
                "success": result["success"],
                "reason": result.get("reason"),
                "request_id": context.aws_request_id,
            }
        )
    )

    return http_response(result) if is_http else result


def log_error(error, request_id):
    """Registra el tipo de error y su ubicación sin incluir mensajes ni datos del usuario."""

    from botocore.exceptions import ClientError

    details = {
        "event": "TEAM_AGENT_EXCEPTION",
        "request_id": request_id,
        "exception_type": type(error).__name__,
        "frames": [
            {
                "file": os.path.basename(frame.filename),
                "function": frame.name,
                "line": frame.lineno,
            }
            for frame in traceback.extract_tb(error.__traceback__)
        ],
    }

    if isinstance(error, ClientError):
        details["aws_code"] = error.response.get("Error", {}).get("Code")
        details["aws_request_id"] = error.response.get("ResponseMetadata", {}).get(
            "RequestId"
        )
        details["aws_operation"] = error.operation_name

    print(json.dumps(details))


def http_response(result, status=200):
    """Devuelve el resultado como JSON por HTTP, sin caché ni CORS público."""

    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": json.dumps(result, ensure_ascii=False),
        "isBase64Encoded": False,
    }
