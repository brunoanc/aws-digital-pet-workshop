"""Check shared card throttling without AWS calls."""

import tempfile
import unittest
from unittest.mock import patch

from app.card_limits import CardReadLimitError, card_read_slot


class CardLimitTests(unittest.TestCase):
    """Check isolation, cooldown and lock recovery across separate callers."""

    def test_overlapping_sessions_and_separate_teams(self):
        """Block a second caller for one team while allowing another team."""

        with tempfile.TemporaryDirectory() as directory:
            with card_read_slot("team-01", directory, 2):
                with self.assertRaises(CardReadLimitError):
                    with card_read_slot("team-01", directory, 2):
                        self.fail("An overlapping read was allowed.")

                with card_read_slot("team-02", directory, 2):
                    pass

    def test_failure_keeps_cooldown_and_releases_lock(self):
        """Keep failed attempts counted and allow a fresh read at the boundary."""

        with tempfile.TemporaryDirectory() as directory:
            with patch("app.card_limits.time.time", return_value=100):
                with self.assertRaises(RuntimeError):
                    with card_read_slot("team-01", directory, 2):
                        raise RuntimeError("Simulated AWS failure.")

            with patch("app.card_limits.time.time", return_value=101):
                with self.assertRaises(CardReadLimitError):
                    with card_read_slot("team-01", directory, 2):
                        self.fail("The cooldown was bypassed.")

            with patch("app.card_limits.time.time", return_value=102):
                with card_read_slot("team-01", directory, 2):
                    pass

    def test_invalid_configuration(self):
        """Reject unsafe team paths and invalid interval values."""

        with tempfile.TemporaryDirectory() as directory:
            for interval in (0, 61, float("nan"), float("inf")):
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    with card_read_slot("team-01", directory, interval):
                        self.fail("An invalid interval was allowed.")

            with self.assertRaises(ValueError):
                with card_read_slot("../team-01", directory, 2):
                    self.fail("An unsafe team path was allowed.")
