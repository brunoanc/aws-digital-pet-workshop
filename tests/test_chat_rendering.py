"""Check remote chat Markdown rendering without enabling arbitrary HTML."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.remote_ui import render_chat


class ChatRenderingTests(unittest.TestCase):
    """Verify safe message formatting."""

    def test_markdown_messages(self):
        """Pass chat history content to the Markdown renderer with HTML disabled."""

        settings = SimpleNamespace(max_input_chars=500)
        content = "¡Listo!\n\n- **Salud:** 87\n- **Energía:** 63"

        with patch("app.remote_ui.st") as ui:
            ui.session_state.remote_history = [{"role": "assistant", "text": content}]
            ui.chat_input.return_value = None

            render_chat(settings, None, True)

            ui.markdown.assert_called_once_with(content, unsafe_allow_html=False)
            ui.text.assert_not_called()
