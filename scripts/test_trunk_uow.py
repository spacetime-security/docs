#!/usr/bin/env python3
"""Focused tests for scripts/trunk-uow."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
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
    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

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

    def test_isolated_start_verify_finish_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = (root / "repo").resolve()
            remote = (root / "remote.git").resolve()
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                           capture_output=True)
            self.git(repo, "config", "user.name", "Trunk Test")
            self.git(repo, "config", "user.email", "trunk-test@example.invalid")
            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           capture_output=True)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"],
                           cwd=remote, check=True, capture_output=True)
            goals = repo / "docs" / "goals"
            goals.mkdir(parents=True)
            source_goals = TOOL.parent.parent / "docs" / "goals"
            shutil.copy2(source_goals / "schema.json", goals / "schema.json")
            shutil.copy2(source_goals / "validate_goal_manifest.py",
                         goals / "validate_goal_manifest.py")
            manifest_path = repo / "docs" / "verification" / "SCRUM-9999" / "goal-manifest.yaml"
            manifest_path.parent.mkdir(parents=True)
            manifest = {
                "schema": "spacetime.goal_manifest/v1",
                "goal_id": "scrum-9999-test", "title": "Lifecycle test",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "repository": str(repo.resolve()), "branch": "main",
                "head": "0" * 40, "state": "DISCOVERED",
                "objective": "Test the lifecycle",
                "acceptance_criteria": ["Lifecycle completes"],
                "plan": {"waves": [], "units_of_work": [{
                    "jira": "SCRUM-9999", "branch": "uow/SCRUM-9999",
                    "authorized_files": ["work.txt"],
                    "evidence_paths": ["evidence/**"],
                    "focused_tests": ["git diff --check"],
                    "broader_tests": ["git status --porcelain"],
                    "integrated_gates": ["git diff --check"],
                }]},
                "coordination": {"contract_version": "1",
                                 "coordinator_task_identity": "test-coordinator"},
                "evidence": [], "jira": {"issues": ["SCRUM-9999"]},
                "release": {"version": None, "tag": None},
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", "test: seed repository")
            self.git(repo, "remote", "add", "origin", str(remote))
            self.git(repo, "push", "-u", "origin", "main")
            self.git(repo, "remote", "set-head", "origin", "-a")
            self.assertIn("origin/HEAD", MODULE.tracking_branches(repo))
            with self.assertRaises(MODULE.UowError):
                MODULE.require_main_topology(repo)
            self.git(repo, "config", "remote.origin.followRemoteHEAD", "never")
            self.git(repo, "remote", "set-head", "origin", "-d")
            with self.assertRaises(MODULE.UowError):
                MODULE.validate_manifest(repo, manifest_path, "SCRUM-9999", start=True)
            manifest["head"] = self.git(repo, "rev-parse", "HEAD")
            manifest_path = (repo / ".git" / "spacetime-goals" / "SCRUM-9999" /
                             "goal-manifest.yaml")
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            old_current = MODULE.require_jira_current_sprint
            old_status = MODULE.jira_status
            old_finish = MODULE.jira_finish
            MODULE.require_jira_current_sprint = lambda jira: None
            MODULE.jira_status = lambda jira: "To Do"
            MODULE.jira_finish = lambda jira, comment: None
            try:
                MODULE.start(repo, "SCRUM-9999", str(manifest_path))
                (repo / "work.txt").write_text("bounded change\n")
                self.git(repo, "add", "work.txt")
                self.git(repo, "commit", "-m", "SCRUM-9999: bounded change")
                lease = MODULE.load_lease(repo)
                head = self.git(repo, "rev-parse", "HEAD")
                admission = {
                    "jira": lease["jira"], "branch": lease["branch"],
                    "base": lease["base"], "head": head,
                    "tree": self.git(repo, "rev-parse", f"{head}^{{tree}}"),
                    "goal_manifest": lease["goal_manifest"], "result": "PASS",
                    "disposition": "CANDIDATE_ADMITTED",
                    "coordinator_task_identity": "test-coordinator",
                    "recorded_at": "2099-01-01T00:00:00Z",
                }
                MODULE.admission_path(repo).write_text(json.dumps(admission))
                MODULE.verify(repo, lease)
                MODULE.jira_status = lambda jira: "Done"
                MODULE.finish(repo)
                self.assertEqual(self.git(repo, "branch", "--show-current"), "main")
                self.assertEqual(MODULE.local_branches(repo), ["main"])
                self.assertFalse(MODULE.lease_path(repo).exists())
                self.assertFalse(MODULE.admission_path(repo).exists())
                self.assertEqual(self.git(repo, "rev-parse", "main"),
                                 self.git(repo, "rev-parse", "origin/main"))
            finally:
                MODULE.require_jira_current_sprint = old_current
                MODULE.jira_status = old_status
                MODULE.jira_finish = old_finish


if __name__ == "__main__":
    unittest.main()
