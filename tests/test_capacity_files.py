"""Check isolated capacity files without provisioning AWS resources."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.capacity_files import render_files, write_new_files, ROOT


class CapacityFileTests(unittest.TestCase):
    """Keep states separate and reject overwrites before replacing any files."""

    def setUp(self):
        """Load public fixtures without opening private account configuration."""

        self.config = json.loads(Path("config/capacity.example.json").read_text())
        self.deployment = json.loads(
            Path("config/capacity-deployment.example.json").read_text()
        )

    def test_separate_states_and_builder_paths(self):
        """Render sixteen unique states and resolve the builder from the Terraform root."""

        with patch("scripts.capacity_files.Path.is_file", return_value=True):
            files = render_files(self.config, self.deployment, "/tmp/capacity-test")

        stacks = json.loads(files["manifest.json"])["stacks"]
        agent = json.loads(files["team-81.tfvars.json"])["agent"]

        self.assertEqual(len(files), 48)
        self.assertEqual(len({stack["state_key"] for stack in stacks}), 16)
        self.assertEqual(len({stack["tf_data_dir"] for stack in stacks}), 16)
        self.assertEqual(
            (ROOT / "infra/agent" / agent["builder_source_path"]).resolve(),
            ROOT / "tests/capacity/agent_builder.py",
        )
        self.assertTrue(json.loads(files["pets.tfvars.json"])["workload"]["read_only"])
        self.assertNotIn("team-01", files)

    def test_refuses_existing_directory(self):
        """Preserve existing files when the destination already exists."""

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                write_new_files({"new.json": "{}"}, directory)

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_private_file_permissions(self):
        """Create private files only inside a new directory."""

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new"

            write_new_files({"manifest.json": "{}"}, target)

            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual((target / "manifest.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_existing_backend_key(self):
        """Reject a supplied state key instead of reusing an existing stack."""

        self.deployment["backend"]["key"] = "rehearsal.tfstate"

        with self.assertRaises(ValueError):
            render_files(self.config, self.deployment, "/tmp/unused-capacity")
