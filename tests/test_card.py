"""Test pet card updates with simulated reads and no AWS calls."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app.card import load_snapshot
from app.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


class CardTests(unittest.TestCase):
    """Check independent reads, labels, and pet card failure recovery."""

    def setUp(self):
        """Prepare a fake pet and public configuration for each test."""

        self.settings = load_settings(ROOT / "scripts/config_defaults/app.json")

        self.pet = {
            "pet_id": "team-01",
            "name": "Dragón Ñu",
            "species": "Dragón de la nube",
            "health": 87,
            "fullness": 60,
            "energy": 23,
            "happiness": 84,
            "experience": 25,
            "version": 3,
            "inventory": {"healthy_meal": 1, "cake": 1},
        }
        self.snapshot = {"pet": self.pet, "read_at": "12:00:00 UTC"}

    def test_read_only_snapshot(self):
        """Verify account and function before invoking only inspect with empty parameters."""

        with patch("app.card.boto3.Session"), patch("app.card.PetBackend") as backend:
            backend.return_value.invoke.return_value = {
                "success": True,
                "pet": self.pet,
            }
            snapshot = load_snapshot(self.settings)

            backend.return_value.preflight.assert_called_once()
            self.assertEqual(
                backend.return_value.invoke.call_args.args[:2], ("inspect", {})
            )
            self.assertEqual(snapshot["pet"], self.pet)
            self.assertTrue(snapshot["read_at"].endswith("UTC"))

    def test_invalid_data_rejected(self):
        """Reject other teams' pets, invalid metrics, and malformed inventories."""

        for field, value in (
            ("pet_id", "team-02"),
            ("health", 101),
            ("energy", True),
            ("inventory", {}),
            ("experience", -1),
            ("version", 0),
            ("name", ""),
        ):
            pet = deepcopy(self.pet)
            pet[field] = value

            with (
                patch("app.card.boto3.Session"),
                patch("app.card.PetBackend") as backend,
            ):
                backend.return_value.invoke.return_value = {"success": True, "pet": pet}

                with self.assertRaises(ValueError):
                    load_snapshot(self.settings)

    def test_failed_read_rejected(self):
        """Prevent unsuccessful tool responses from being displayed as current state."""

        with patch("app.card.boto3.Session"), patch("app.card.PetBackend") as backend:
            backend.return_value.invoke.return_value = {
                "success": False,
                "pet": self.pet,
            }

            with self.assertRaises(ValueError):
                load_snapshot(self.settings)




if __name__ == "__main__":
    unittest.main()
