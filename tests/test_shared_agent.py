"""Test reuse of the workshop chat with authorized destinations and persistent per-team limits."""

import json
import multiprocessing
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from app.remote import RemoteSettings, RequestLimitError
from app.shared_agent import SharedAgent, request_slot, validate_agent


def hold_request_slot(directory, ready, release):
    """Hold one team's request in another process until the test releases it."""

    limits = {"max_requests": 3, "min_interval_seconds": 1}

    with request_slot("team-01", limits, directory):
        ready.set()

        if not release.wait(10):
            raise TimeoutError("The test did not release the request lock.")


class SharedAgentTests(unittest.TestCase):
    """Reject unauthorized transport and ensure the original chat remains functional."""

    def test_budget_serializes_and_persists_attempts(self):
        """Reject parallel requests and retain charged attempts after failed transport."""

        limits = {"max_requests": 1, "min_interval_seconds": 1}

        with tempfile.TemporaryDirectory() as directory:
            with request_slot("team-01", limits, directory):
                with self.assertRaises(PermissionError):
                    with request_slot("team-01", limits, directory):
                        self.fail("A concurrent request was allowed.")

            with self.assertRaises(PermissionError):
                with request_slot("team-01", limits, directory):
                    self.fail("The quota was not retained.")

            with request_slot("team-02", limits, directory):
                self.assertEqual(
                    json.loads((Path(directory) / "team-01-requests.json").read_text())[
                        "count"
                    ],
                    1,
                )

    def test_separate_process_blocks_only_its_own_team(self):
        """Reject another process for the same team while allowing another team to proceed."""

        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        limits = {"max_requests": 3, "min_interval_seconds": 1}

        with tempfile.TemporaryDirectory() as directory:
            process = context.Process(
                target=hold_request_slot, args=(directory, ready, release)
            )

            process.start()

            try:
                self.assertTrue(ready.wait(10))

                with self.assertRaisesRegex(PermissionError, "esperando una respuesta"):
                    with request_slot("team-01", limits, directory):
                        self.fail("A second process entered the active team's slot.")

                with request_slot("team-02", limits, directory):
                    self.assertTrue(process.is_alive())
            finally:
                release.set()
                process.join(10)

                if process.is_alive():
                    process.terminate()
                    process.join(5)

            self.assertEqual(process.exitcode, 0)

            for team in ("team-01", "team-02"):
                usage = json.loads(
                    (Path(directory) / (team + "-requests.json")).read_text()
                )

                self.assertEqual(usage["count"], 1)

    def test_interval_rejects_without_charging_another_attempt(self):
        """Keep the counter unchanged during cooldown and allow the exact next boundary."""

        limits = {"max_requests": 3, "min_interval_seconds": 5}

        with tempfile.TemporaryDirectory() as directory:
            with patch("app.shared_agent.time.time", return_value=100):
                with request_slot("team-01", limits, directory):
                    pass

            with patch("app.shared_agent.time.time", return_value=104.9):
                with self.assertRaisesRegex(PermissionError, "Espera unos segundos"):
                    with request_slot("team-01", limits, directory):
                        self.fail("A request bypassed the cooldown.")

            path = Path(directory) / "team-01-requests.json"

            self.assertEqual(json.loads(path.read_text())["count"], 1)

            with patch("app.shared_agent.time.time", return_value=105):
                with request_slot("team-01", limits, directory):
                    pass

            self.assertEqual(json.loads(path.read_text())["count"], 2)

    def test_failed_transport_retains_the_charged_attempt(self):
        """Retain the exhausted budget after an uncertain transport failure releases its lock."""

        limits = {"max_requests": 1, "min_interval_seconds": 1}

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TimeoutError):
                with request_slot("team-01", limits, directory):
                    raise TimeoutError("The simulated response was not received.")

            with self.assertRaisesRegex(PermissionError, "límite de mensajes"):
                with request_slot("team-01", limits, directory):
                    self.fail("The failed attempt was refunded.")

    def test_corrupt_counter_does_not_reset_the_budget(self):
        """Reject malformed stored usage without overwriting it or entering the request body."""

        limits = {"max_requests": 3, "min_interval_seconds": 1}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "team-01-requests.json"

            path.write_text("{broken")

            with self.assertRaises(json.JSONDecodeError):
                with request_slot("team-01", limits, directory):
                    self.fail("A corrupt counter granted a fresh budget.")

            self.assertEqual(path.read_text(), "{broken")

    def test_wrong_url_does_not_obtain_credentials(self):
        """Reject an unregistered pasted URL before using the server role."""

        adapter = object.__new__(SharedAgent)
        adapter.remote = RemoteSettings(
            "test-agent",
            100,
            65536,
            "https://" + "a" * 32 + ".lambda-url.us-east-1.on.aws/",
        )

        with patch.object(adapter, "session") as session:
            with self.assertRaises(ValueError):
                adapter.connect("https://example.com/")

            session.assert_not_called()

    def test_existing_chat_connects_and_renders_markdown(self):
        """Keep the original URL form, two-column layout, and chat rendering with an injected adapter."""

        remote = RemoteSettings(
            "test-agent",
            100,
            65536,
            "https://" + "a" * 32 + ".lambda-url.us-east-1.on.aws/",
        )
        agent = Mock()
        agent.connect.return_value = remote.function_url
        agent.send.return_value = {
            "message": "**Hola**",
            "registered_tools": [],
            "activity": [],
        }

        with (
            patch("app.remote_ui.make_agent", return_value=agent),
            patch("app.remote_ui.remember_url", return_value=None),
        ):
            app = AppTest.from_string(
                "from types import SimpleNamespace\n"
                "from app.remote import RemoteSettings\n"
                "from app.remote_ui import render_remote\n"
                "import streamlit as st\n"
                "def card():\n"
                '    """Render the test habitat."""\n'
                '    st.text("Mascota")\n'
                'settings = SimpleNamespace(max_input_chars=100, max_messages=3, account_id="111122223333", region="us-east-1", team_id="team-01")\n'
                'remote = RemoteSettings("test-agent", 100, 65536, "https://" + "a" * 32 + ".lambda-url.us-east-1.on.aws/")\n'
                "render_remote(settings, remote_settings=remote, card_renderer=card)\n"
            ).run()

            self.assertTrue(app.chat_input[0].disabled)

            app.text_input[0].input(remote.function_url)
            app.button[0].click().run()

            self.assertFalse(app.exception)
            self.assertFalse(app.chat_input[0].disabled)

            app.chat_input[0].set_value("Hola").run()

            self.assertFalse(app.exception)
            self.assertTrue(any(item.value == "**Hola**" for item in app.markdown))
            agent.send.assert_called_once_with("Hola")

    def test_chat_shows_only_trusted_limit_notices(self):
        """Show known pre-invocation notices while hiding arbitrary execution errors without retrying."""

        notices = (
            "Tu equipo ya está esperando una respuesta; dale un momento.",
            "Tu equipo alcanzó el límite de mensajes; avisa al organizador.",
            "Espera unos segundos antes de enviar otro mensaje.",
        )
        generic = "No se pudo confirmar el resultado; revisa la ficha y los logs antes de repetir un cuidado."
        cases = [(RequestLimitError(text), text) for text in notices]

        cases.extend(
            (error, generic)
            for error in (PermissionError("internal detail"), TimeoutError("internal detail"))
        )

        for error, expected in cases:
            with self.subTest(error=type(error).__name__, expected=expected):
                agent = Mock()
                agent.send.side_effect = error

                with patch("app.remote_ui.make_agent", return_value=agent):
                    app = AppTest.from_string(
                        "import streamlit as st\n"
                        "from types import SimpleNamespace\n"
                        "from app.remote_ui import render_chat\n"
                        "if 'remote_history' not in st.session_state:\n"
                        "    st.session_state.remote_history = []\n"
                        "    st.session_state.remote_tools = ['inspect_pet']\n"
                        "render_chat(SimpleNamespace(max_input_chars=100, max_messages=3), None, True)\n"
                    ).run()

                    app.chat_input[0].set_value("Consulta mi mascota").run()

                self.assertFalse(app.exception)
                self.assertTrue(any(item.value == expected for item in app.markdown))
                self.assertFalse(any("internal detail" in item.value for item in app.markdown))
                self.assertEqual(app.session_state.scene_pending, [])
                agent.send.assert_called_once_with("Consulta mi mascota")

                if isinstance(error, RequestLimitError):
                    self.assertEqual(app.session_state.remote_tools, ["inspect_pet"])
