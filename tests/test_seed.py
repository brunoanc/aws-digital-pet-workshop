"""Test safe initialization and data conversion with simulated storage and account identity."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))

from pet_ops import encode, decode, AWS
from seed import seed


class FakeAWS:
    """Simulate records and preflight checks used during initialization."""

    def __init__(self):
        """Prepare an empty store with preflight marked as incomplete."""

        self.items = {}
        self.checked = False

    def preflight(self):
        """Record the preflight check without querying AWS."""

        self.checked = True

    def get(self, table, key):
        """Return the in-memory record for the table and key or None when absent."""

        return self.items.get((table, key))

    def put_if_absent(self, table, item):
        """Simulate conditional creation after preflight while preserving existing records."""

        assert self.checked

        key = (table, item["pet_id"])

        if key in self.items:
            return "preservado"

        self.items[key] = item

        return "creado"


class SeedTests(unittest.TestCase):
    """Verify that initialization preserves data and enforces the expected account."""

    def setUp(self):
        """Prepare the simulated client and two-team fixtures for each test."""

        self.aws = FakeAWS()
        self.config = {
            "teams": {"team-01": "table-one", "team-02": "table-two"},
            "pet_fixture": ROOT / "fixtures/starter.json",
        }

    def test_preview_never_writes(self):
        """Verify that preview reports one pet per team without creating records."""

        self.assertEqual(len(seed(self.aws, self.config)), 2)
        self.assertFalse(self.aws.items)

    def test_rerun_preserves_progress(self):
        """Verify that repeated initialization preserves records and a customized name."""

        seed(self.aws, self.config, True)

        self.assertEqual(len(self.aws.items), 2)
        self.assertFalse(any(key == "_config" for _, key in self.aws.items))

        self.aws.items[("table-one", "team-01")]["name"] = "Dragón Ñandú"

        self.assertTrue(
            all(
                row["status"] == "preservado"
                for row in seed(self.aws, self.config, True)
            )
        )
        self.assertEqual(
            self.aws.items[("table-one", "team-01")]["name"], "Dragón Ñandú"
        )

    def test_serialization(self):
        """Verify that nested data survives encoding and decoding."""

        value = {
            "name": "Dragón",
            "energy": 8,
            "enabled": False,
            "tools": [],
            "inventory": {"cake": 1},
        }

        self.assertEqual(decode(encode(value)), value)

    def test_wrong_account_aborts(self):
        """Simulate another account and verify that preflight stops."""

        aws = AWS({"account_id": "111122223333"})
        aws.call = lambda *args: {"Account": "444455556666"}

        with self.assertRaisesRegex(RuntimeError, "Wrong AWS account"):
            aws.preflight()
