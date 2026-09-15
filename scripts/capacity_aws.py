"""Verify isolated capacity resources and call their IAM-protected Function URLs."""

import json

import boto3
from botocore.config import Config

from app.function_url import post_signed, validate_url


class CapacityAWS:
    """Keep the real transport separate from planning and simulated batch tests."""

    def __init__(self, config, plan, expected):
        """Create bounded clients without invoking AWS until preflight is requested."""

        self.config, self.plan, self.expected = config, plan, expected

        if set(expected) != set(plan["teams"]):
            raise ValueError(
                "Provide reviewed code hashes for all fifteen capacity teams."
            )

        self.session = boto3.Session(
            profile_name=config["profile"], region_name=config["region"]
        )
        options = Config(
            connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}
        )
        self.clients = {
            service: self.session.client(service, config=options)
            for service in ("sts", "lambda", "iam", "dynamodb", "service-quotas")
        }
        self.endpoints = {}

    def preflight(self):
        """Check account, quotas and every target before allowing any inference."""

        if (
            self.clients["sts"].get_caller_identity()["Account"]
            != self.plan["account_id"]
        ):
            raise ValueError("The active session belongs to another account.")

        for service, code, minimum in (
            ("lambda", "L-B99A9384", 50),
            ("bedrock", "L-E386A278", 100),
            ("bedrock", "L-70423BF8", 4000000),
        ):
            value = self.clients["service-quotas"].get_service_quota(
                ServiceCode=service, QuotaCode=code
            )["Quota"]["Value"]

            if value < minimum:
                raise ValueError(
                    "The applied quota is below the reviewed capacity requirement."
                )

        for team in self.plan["teams"]:
            self.check_team(team)

    def check_team(self, team):
        """Match deployed code and runtime to reviewed hashes and require a read-only pet role."""

        target = self.plan["teams"][team]
        prefix = (
            f"arn:aws:lambda:{self.plan['region']}:{self.plan['account_id']}:function:"
        )
        client = self.clients["lambda"]
        pet_name = target["runtime"]["function_name"]
        agent_name = target["agent_function"]
        expected = self.expected[team]

        for kind, name in (("pet", pet_name), ("agent", agent_name)):
            function = client.get_function_configuration(FunctionName=prefix + name)

            if (
                function.get("FunctionArn") != prefix + name
                or function.get("State") != "Active"
                or function.get("LastUpdateStatus") != "Successful"
                or function.get("CodeSha256") != expected[kind + "_code_sha256"]
                or function.get("Role")
                != f"arn:aws:iam::{self.plan['account_id']}:role/{name}-execution"
                or function.get("Timeout") != expected[kind + "_timeout_seconds"]
                or function.get("MemorySize") != expected[kind + "_memory_mb"]
            ):
                raise ValueError(
                    "A capacity function differs from its reviewed deployment."
                )

            environment = function.get("Environment", {}).get("Variables", {})

            if kind == "agent":
                if (
                    json.loads(environment.get("APP_SETTINGS", "{}"))
                    != target["runtime"]
                ):
                    raise ValueError("The capacity agent runtime changed after review.")

                layers = function.get("Layers", [])

                if len(layers) != 1:
                    raise ValueError(
                        "The capacity agent must use one reviewed dependency layer."
                    )

                layer = client.get_layer_version_by_arn(Arn=layers[0]["Arn"])

                if layer["Content"]["CodeSha256"] != expected["layer_code_sha256"]:
                    raise ValueError("The dependency layer changed after review.")
            elif environment != {"TEAM_ID": team, "TABLE_NAME": pet_name}:
                raise ValueError("The pet backend points to an unexpected destination.")

        self.check_pet_policy(pet_name)
        self.check_agent_policy(agent_name, pet_name)

        endpoint = client.get_function_url_config(FunctionName=prefix + agent_name)

        if (
            endpoint.get("FunctionArn") != prefix + agent_name
            or endpoint.get("AuthType") != "AWS_IAM"
        ):
            raise ValueError(
                "The capacity URL must belong to the agent and require IAM."
            )

        self.endpoints[team] = validate_url(
            endpoint["FunctionUrl"], self.plan["region"]
        )

    def check_agent_policy(self, name, pet):
        """Reject extra agent permissions beyond its own backend, model and logs."""

        iam = self.clients["iam"]
        role = name + "-execution"
        inline = iam.list_role_policies(RoleName=role)
        attached = iam.list_attached_role_policies(RoleName=role)

        if (
            inline.get("IsTruncated")
            or attached.get("IsTruncated")
            or inline.get("PolicyNames") != ["own-pet-and-model"]
            or attached.get("AttachedPolicies")
        ):
            raise ValueError("The agent role has unexpected policies.")

        region, account = self.plan["region"], self.plan["account_id"]
        condition = {"StringEquals": {"aws:RequestedRegion": region}}
        expected = [
            {
                "Effect": "Allow",
                "Action": ["lambda:GetFunctionConfiguration", "lambda:InvokeFunction"],
                "Resource": [f"arn:aws:lambda:{region}:{account}:function:{pet}"],
                "Condition": condition,
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}::foundation-model/{self.config['model_id']}"
                ],
                "Condition": condition,
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{name}:*"
                ],
                "Condition": condition,
            },
        ]
        actual = iam.get_role_policy(RoleName=role, PolicyName="own-pet-and-model")[
            "PolicyDocument"
        ].get("Statement", [])

        if len(actual) != len(expected) or any(
            statement not in actual for statement in expected
        ):
            raise ValueError(
                "The agent role differs from the reviewed permission scope."
            )

    def check_pet_policy(self, name):
        """Require the reviewed pet policy without extra inline or managed policies."""

        iam = self.clients["iam"]
        role = name + "-execution"
        inline = iam.list_role_policies(RoleName=role)
        attached = iam.list_attached_role_policies(RoleName=role)

        if (
            inline.get("IsTruncated")
            or attached.get("IsTruncated")
            or inline.get("PolicyNames") != ["pet-data-and-logs"]
            or attached.get("AttachedPolicies")
        ):
            raise ValueError("The pet role has unexpected policies.")

        policy = iam.get_role_policy(RoleName=role, PolicyName="pet-data-and-logs")[
            "PolicyDocument"
        ]
        table = f"arn:aws:dynamodb:{self.plan['region']}:{self.plan['account_id']}:table/{name}"
        statements = policy.get("Statement", [])
        read = {"Effect": "Allow", "Action": ["dynamodb:GetItem"], "Resource": table}
        deny = {"Effect": "Deny", "NotAction": "dynamodb:GetItem", "Resource": table}

        if len(statements) != 3 or read not in statements or deny not in statements:
            raise ValueError(
                "The pet role must explicitly deny non-read table actions."
            )

        logs = next(item for item in statements if item not in (read, deny))
        log_arn = f"arn:aws:logs:{self.plan['region']}:{self.plan['account_id']}:log-group:/aws/lambda/{name}:*"

        if logs != {
            "Effect": "Allow",
            "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": log_arn,
        }:
            raise ValueError(
                "The pet role logging permissions differ from the reviewed scope."
            )

    def snapshot(self):
        """Read complete synthetic pet items for comparison without changing them."""

        result = {}

        for team, target in self.plan["teams"].items():
            table = target["runtime"]["function_name"]
            arn = f"arn:aws:dynamodb:{self.plan['region']}:{self.plan['account_id']}:table/{table}"
            item = (
                self.clients["dynamodb"]
                .get_item(
                    TableName=arn, Key={"pet_id": {"S": team}}, ConsistentRead=True
                )
                .get("Item")
            )

            if not item or item.get("pet_id") != {"S": team}:
                raise ValueError(
                    "Seed every synthetic pet before running capacity tests."
                )

            result[team] = item

        return result

    def invoke(self, team, message):
        """Recheck one destination and send one signed request without retries."""

        self.check_team(team)

        timeout = self.expected[team]["agent_timeout_seconds"] + 10
        body = post_signed(
            self.endpoints[team],
            message,
            self.session,
            self.plan["region"],
            timeout,
            65536,
        )

        return json.loads(body)
