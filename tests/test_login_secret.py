"""Test login secret initialization without AWS calls or credential output."""

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts.initialize_login_secret import initialize, validate_config


class LoginSecretTests(unittest.TestCase):
    """Verify fixed targets, one-time initialization, and credential-free reports."""

    def setUp(self):
        """Prepare a fake empty secret and a matching federated Cognito client."""

        self.config = json.loads(
            Path("scripts/config_defaults/login-bootstrap.json").read_text()
        )
        self.storage = Mock()
        self.identity = Mock()
        self.cognito = Mock()
        self.identity.get_caller_identity.return_value = {
            "Account": self.config["account_id"]
        }
        self.metadata = {
            "ARN": self.config["secret_arn"],
            "Tags": [{"Key": "ManagedBy", "Value": "Terraform"}],
            "VersionIdsToStages": {},
        }
        self.storage.describe_secret.return_value = self.metadata
        self.client = {
            "UserPoolId": self.config["user_pool_id"],
            "ClientId": self.config["client_id"],
            "ClientSecret": "fake-client-secret-for-tests",
            "CallbackURLs": [self.config["app_origin"] + "/oauth2callback"],
            "LogoutURLs": [self.config["app_origin"]],
            "SupportedIdentityProviders": ["IdentityCenter"],
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthScopes": ["openid", "email", "profile"],
        }
        self.cognito.describe_user_pool_client.return_value = {
            "UserPoolClient": self.client
        }
        self.session = Mock()
        self.session.client.side_effect = lambda service, **kwargs: {
            "sts": self.identity,
            "secretsmanager": self.storage,
            "cognito-idp": self.cognito,
        }[service]

    def test_preview_is_offline(self):
        """Keep previews local without reading credentials or creating AWS clients."""

        with patch("scripts.initialize_login_secret.boto3.Session") as session:
            self.assertEqual(initialize(self.config)["status"], "preview")
            session.assert_not_called()

    def test_account_mismatch_stops_before_secret_access(self):
        """Reject another account before inspecting or writing secret storage."""

        self.identity.get_caller_identity.return_value = {"Account": "999999999999"}

        with patch(
            "scripts.initialize_login_secret.boto3.Session", return_value=self.session
        ):
            with self.assertRaises(ValueError):
                initialize(self.config, apply=True)

        self.storage.describe_secret.assert_not_called()
        self.storage.put_secret_value.assert_not_called()

    def test_existing_or_unmanaged_secret_is_preserved(self):
        """Reject initialized, unmanaged, and deletion-pending secrets without reading Cognito credentials."""

        for changes in (
            {"VersionIdsToStages": {"old": ["AWSCURRENT"]}},
            {"Tags": []},
            {"DeletedDate": "pending"},
        ):
            self.storage.describe_secret.return_value = self.metadata | changes

            with patch(
                "scripts.initialize_login_secret.boto3.Session",
                return_value=self.session,
            ):
                with self.assertRaises(ValueError):
                    initialize(self.config, apply=True)

        self.cognito.describe_user_pool_client.assert_not_called()
        self.storage.put_secret_value.assert_not_called()

    def test_unexpected_client_is_rejected(self):
        """Reject another callback or local login provider before writing credentials."""

        for changes in (
            {"CallbackURLs": ["https://other.example/oauth2callback"]},
            {"SupportedIdentityProviders": ["COGNITO"]},
            {"ClientSecret": ""},
        ):
            self.cognito.describe_user_pool_client.return_value = {
                "UserPoolClient": self.client | changes
            }

            with patch(
                "scripts.initialize_login_secret.boto3.Session",
                return_value=self.session,
            ):
                with self.assertRaises(ValueError):
                    initialize(self.config, apply=True)

        self.storage.put_secret_value.assert_not_called()

    def test_initialize_reports_only_metadata(self):
        """Store credentials once and verify the current version without returning secret values."""

        version = hashlib.sha256(
            (self.config["secret_arn"] + ":initial-login-v1").encode()
        ).hexdigest()
        self.storage.put_secret_value.return_value = {"VersionId": version}
        self.storage.describe_secret.side_effect = [
            self.metadata,
            self.metadata | {"VersionIdsToStages": {version: ["AWSCURRENT"]}},
        ]

        with patch(
            "scripts.initialize_login_secret.boto3.Session", return_value=self.session
        ):
            result = initialize(self.config, apply=True)

        payload = json.loads(
            self.storage.put_secret_value.call_args.kwargs["SecretString"]
        )

        self.assertEqual(payload["auth"]["client_secret"], self.client["ClientSecret"])
        self.assertGreaterEqual(len(payload["auth"]["cookie_secret"]), 64)
        self.assertNotIn(self.client["ClientSecret"], json.dumps(result))
        self.assertNotIn(payload["auth"]["cookie_secret"], json.dumps(result))
        self.assertEqual(result["version_id"], version)
        self.storage.put_secret_value.assert_called_once()

    def test_config_rejects_cross_environment_targets(self):
        """Reject secret accounts, user pool regions, and origins outside the configured environment."""

        for changes in (
            {"account_id": "999999999999"},
            {"user_pool_id": "us-west-2_OTHER"},
            {"app_origin": "https://example.com/extra"},
        ):
            with self.assertRaises(ValueError):
                validate_config(self.config | changes)
