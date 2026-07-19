#!/usr/bin/env python3
"""Focused tests for scripts/trunk-uow."""

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).with_name("trunk-uow")
LOADER = importlib.machinery.SourceFileLoader("trunk_uow", str(TOOL))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class TrunkUowTests(unittest.TestCase):
    def test_authorized_scope_is_bounded(self):
        self.assertTrue(MODULE.path_allowed("src/main.rs", ["src/**"]))
        self.assertTrue(MODULE.path_allowed("evidence/run/log.txt", ["evidence"]))
        self.assertFalse(MODULE.path_allowed("Cargo.toml", ["src/**"]))

    def test_lease_creation_is_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spacetime-uow.json"
            lease = {
                "jira": "SCRUM-1", "branch": "uow/SCRUM-1",
                "base": "a" * 40, "started_at": "2026-01-01T00:00:00Z",
                "goal_manifest": "/tmp/goal-manifest.yaml",
            }
            MODULE.write_lease(path, lease)
            self.assertEqual(json.loads(path.read_text()), lease)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(MODULE.UowError):
                MODULE.write_lease(path, lease)

    def test_cli_exposes_only_three_operations(self):
        result = subprocess.run(
            [sys.executable, str(TOOL), "unsupported"],
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)
        for operation in ("start", "verify", "finish"):
            help_result = subprocess.run(
                [sys.executable, str(TOOL), operation, "--help"],
                text=True, capture_output=True,
            )
            self.assertEqual(help_result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
