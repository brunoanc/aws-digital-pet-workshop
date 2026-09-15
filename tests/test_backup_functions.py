"""Test backup verification without real calls or overwrites."""

import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.backup_functions import backup


class BackupTests(unittest.TestCase):
    """Validate the account, hash, and revision before reporting a completed backup."""

    def test_verified_backup_and_no_overwrite(self):
        """Save a matching package and reject reuse of the same directory."""

        payload = b"test-package"
        configuration = {
            "FunctionArn": "arn:aws:lambda:us-east-1:111122223333:function:pet-test",
            "PackageType": "Zip",
            "RevisionId": "revision-1",
            "CodeSha256": base64.b64encode(hashlib.sha256(payload).digest()).decode(),
        }

        with (
            tempfile.TemporaryDirectory() as root,
            patch("scripts.backup_functions.boto3.Session") as session,
            patch("scripts.backup_functions.urlopen") as download,
        ):
            client = session.return_value.client.return_value
            session.return_value.get_partition_for_region.return_value = "aws"
            client.get_caller_identity.return_value = {"Account": "111122223333"}
            client.get_function.return_value = {
                "Configuration": configuration,
                "Code": {"Location": "https://example.invalid/signed"},
            }
            client.get_function_configuration.return_value = configuration
            download.return_value.__enter__.return_value.read.return_value = payload
            output = Path(root) / "backup"
            manifest = backup("111122223333", "test", "us-east-1", ["pet-test"], output)

            self.assertEqual((output / "pet-test.zip").read_bytes(), payload)
            self.assertNotIn("Location", str(manifest))

            with self.assertRaises(FileExistsError):
                backup("111122223333", "test", "us-east-1", ["pet-test"], output)

            client.get_function.assert_called_once()

    def test_wrong_account_never_creates_directory(self):
        """Stop before creating files when credentials belong to a different account."""

        with (
            tempfile.TemporaryDirectory() as root,
            patch("scripts.backup_functions.boto3.Session") as session,
        ):
            session.return_value.client.return_value.get_caller_identity.return_value = {
                "Account": "999999999999"
            }
            output = Path(root) / "backup"

            with self.assertRaises(ValueError):
                backup("111122223333", "test", "us-east-1", ["pet-test"], output)

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
