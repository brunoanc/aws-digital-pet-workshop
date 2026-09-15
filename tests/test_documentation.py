"""Check public guide links and the current workshop entry points."""

from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    """Keep public instructions connected after repository cleanup."""

    def test_local_links(self):
        """Require relative Markdown links to resolve inside the public repository."""

        files = [ROOT / "README.md"]

        for folder in ("docs", "organizer-guide", "participant-guide", "config", "slides", "infra"):
            files.extend(path for path in (ROOT / folder).rglob("*.md") if not any(part in ("node_modules", "dist", ".terraform") for part in path.parts))

        for path in files:
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                target = target.strip().split(' "', 1)[0].strip("<>")
                parsed = urlsplit(target)

                if parsed.scheme or not parsed.path:
                    continue

                destination = (path.parent / unquote(parsed.path)).resolve()

                with self.subTest(file=str(path.relative_to(ROOT)), link=target):
                    self.assertTrue(destination.is_relative_to(ROOT))
                    self.assertTrue(destination.exists())

                    if parsed.fragment and destination.name in (
                        "infrastructure.md", "deployment.md", "architecture.md", "testing.md"
                    ):
                        anchors = re.findall(r'<a id="([^"]+)"></a>', destination.read_text())

                        self.assertIn(unquote(parsed.fragment), anchors)
