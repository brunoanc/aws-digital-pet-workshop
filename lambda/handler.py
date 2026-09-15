"""Procesa las acciones de la mascota y guarda sus cambios en DynamoDB."""

import hashlib
import json
import os
import re
import traceback
import uuid
from decimal import Decimal

from rules import act, reject


def plain(value):
    """Convierte Decimal a int o float, también dentro de listas y diccionarios."""

    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)

    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}

    if isinstance(value, list):
        return [plain(item) for item in value]

    return value


def process(event, team_id, store):
    """Valida la acción y guarda los cambios de la mascota del equipo."""

    if not isinstance(event, dict) or set(event) - {
        "pet_id",
        "action",
        "parameters",
        "operation_id",
    }:
        return reject("INVALID_REQUEST", "Revisa los campos permitidos en el evento.")

    if event.get("pet_id") != team_id:
        return reject("WRONG_TEAM", "Solo puedes cuidar la mascota de tu equipo.")

    action = event.get("action")

    if not isinstance(action, str):
        return reject("INVALID_REQUEST", "Indica una acción.")

    parameters = event.get("parameters", {})

    if not isinstance(parameters, dict):
        return reject("INVALID_PARAMETERS", "Los parámetros deben ser un objeto.")

    operation_id = event.get("operation_id")

    if operation_id is not None and (
        not isinstance(operation_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation_id)
    ):
        return reject(
            "INVALID_OPERATION_ID", "El operation_id no es válido."
        )

    operation_id = operation_id or str(uuid.uuid4())
    fingerprint = hashlib.sha256(
        json.dumps(
            {"action": action, "parameters": parameters}, sort_keys=True
        ).encode()
    ).hexdigest()

    def replay(record):
        """Recupera el resultado guardado si la acción y los parámetros coinciden."""

        if record["fingerprint"] != fingerprint:
            return reject(
                "OPERATION_CONFLICT", "No reutilices el ID para una acción diferente."
            )

        return record["result"]

    if action != "inspect":
        previous = store.get("_op#" + operation_id)

        if previous:
            return replay(previous)

    pet = store.get(team_id)

    if pet is None:
        return reject("NOT_INITIALIZED", "La mascota todavía no está lista.")

    result = act(pet, team_id, action, parameters)

    if not result["success"] or action == "inspect":
        return result

    record = {
        "pet_id": "_op#" + operation_id,
        "fingerprint": fingerprint,
        "result": result,
    }

    if not store.commit(result["pet"], pet["version"], record):
        previous = store.get(record["pet_id"])

        if previous:
            return replay(previous)

        return reject(
            "CONCURRENT_UPDATE",
            "El estado cambió; consulta de nuevo antes de reintentar con el mismo ID.",
        )

    return result


class DynamoStore:
    """Lee la mascota y guarda su estado junto con el registro de cada operación."""

    def __init__(self, table_name):
        """Prepara el cliente y los conversores de DynamoDB para esta tabla."""

        import boto3
        from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
        from botocore.config import Config

        self.client = boto3.client(
            "dynamodb",
            config=Config(
                connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1}
            ),
        )
        self.table_name = table_name
        self.serialize = TypeSerializer().serialize
        self.deserialize = TypeDeserializer().deserialize

    def get(self, key):
        """Lee un item por pet_id con consistencia fuerte."""

        item = self.client.get_item(
            TableName=self.table_name, Key={"pet_id": {"S": key}}, ConsistentRead=True
        ).get("Item")

        return (
            None
            if item is None
            else plain({key: self.deserialize(value) for key, value in item.items()})
        )

    def commit(self, pet, version, record):
        """Guarda la mascota y su operación en una sola transacción."""

        from botocore.exceptions import ClientError

        def item(value):
            """Convierte un diccionario al formato de DynamoDB."""

            return {key: self.serialize(data) for key, data in value.items()}

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": item(pet),
                            "ConditionExpression": "#version = :previous",
                            "ExpressionAttributeNames": {"#version": "version"},
                            "ExpressionAttributeValues": {
                                ":previous": {"N": str(version)}
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": item(record),
                            "ConditionExpression": "attribute_not_exists(pet_id)",
                        }
                    },
                ]
            )

            return True
        except ClientError as error:
            if error.response["Error"]["Code"] == "TransactionCanceledException":
                codes = {
                    reason.get("Code")
                    for reason in error.response.get("CancellationReasons", [])
                }

                if codes <= {"None", "ConditionalCheckFailed", "TransactionConflict"}:
                    return False

            raise


def lambda_handler(event, context):
    """Ejecuta la acción y registra éxito o rechazo en logs."""

    team_id = os.environ["TEAM_ID"]

    try:
        result = process(event, team_id, DynamoStore(os.environ["TABLE_NAME"]))
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "PET_BACKEND_ERROR",
                    "team": team_id,
                    "request_id": context.aws_request_id,
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
            )
        )

        result = reject(
            "BACKEND_ERROR",
            "La operación tuvo un error. Revisa los logs y el estado antes de reintentar.",
        )
        result["request_id"] = context.aws_request_id

        return result

    print(
        json.dumps(
            {
                "event": "PET_ACTION_ACCEPTED"
                if result["success"]
                else "PET_ACTION_REJECTED",
                "team": team_id,
                "reason": result.get("reason"),
                "request_id": context.aws_request_id,
            }
        )
    )

    return result
