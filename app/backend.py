"""Invoke only the configured team's Lambda using AWS session credentials."""

import json


class PetBackend:
    """Keep a fixed Lambda destination that model inputs cannot change."""

    def __init__(self, settings, session):
        """Create AWS clients with timeouts and no retries."""

        from botocore.config import Config

        self.settings = settings
        self.session = session
        self.client_config = Config(
            connect_timeout=3,
            read_timeout=settings.timeout_seconds,
            retries={"total_max_attempts": 1},
        )
        self.client = session.client(
            "lambda", region_name=settings.region, config=self.client_config
        )
        partition = session.get_partition_for_region(settings.region)
        self.function_arn = f"arn:{partition}:lambda:{settings.region}:{settings.account_id}:function:{settings.function_name}"

    def preflight(self):
        """Verify the account, team, and function state without invoking it."""

        sts = self.session.client(
            "sts", region_name=self.settings.region, config=self.client_config
        )

        if sts.get_caller_identity()["Account"] != self.settings.account_id:
            raise ValueError(
                "The AWS session belongs to another account, so execution cannot continue."
            )

        function = self.client.get_function_configuration(
            FunctionName=self.function_arn
        )
        variables = function.get("Environment", {}).get("Variables", {})

        if (
            function.get("FunctionArn") != self.function_arn
            or function.get("State") != "Active"
            or function.get("LastUpdateStatus") != "Successful"
            or variables.get("TEAM_ID") != self.settings.team_id
            or variables.get("TABLE_NAME") != self.settings.function_name
        ):
            raise ValueError(
                "The function does not match the configured team or is not ready."
            )

    def invoke(self, action, parameters, operation_id):
        """Send one action to the configured Lambda and check its response."""

        payload = {
            "pet_id": self.settings.team_id,
            "action": action,
            "parameters": parameters,
            "operation_id": operation_id,
        }
        response = self.client.invoke(
            FunctionName=self.function_arn,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        stream = response["Payload"]

        try:
            body = stream.read()
        finally:
            stream.close()

        if response.get("FunctionError") or response.get("StatusCode") != 200:
            raise RuntimeError("The function could not complete the request.")

        result = json.loads(body)

        if not isinstance(result, dict) or type(result.get("success")) is not bool:
            raise RuntimeError("The function returned an unexpected response.")

        if "pet" in result and result["pet"].get("pet_id") != self.settings.team_id:
            raise RuntimeError("The response does not match the assigned pet.")

        return result
