#!/usr/bin/env python3
"""Focused tests for the deterministic trunk-state validators."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result


class TrunkStateValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.remote = root / "remote.git"
        seed = root / "seed"
        self.repo = root / "checkout"

        run("git", "init", "--bare", str(self.remote), cwd=root)
        run("git", "init", "-b", "main", str(seed), cwd=root)
        run("git", "config", "user.name", "Validator Test", cwd=seed)
        run("git", "config", "user.email", "validator@example.invalid", cwd=seed)
        run("git", "commit", "--allow-empty", "-m", "test: initialize trunk", cwd=seed)
        run("git", "remote", "add", "origin", str(self.remote), cwd=seed)
        run("git", "push", "-u", "origin", "main", cwd=seed)
        run("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=self.remote)
        run("git", "clone", "--branch", "main", str(self.remote), str(self.repo), cwd=root)
        run("git", "remote", "set-head", "origin", "-d", cwd=self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self) -> subprocess.CompletedProcess[str]:
        if sys.platform == "win32":
            return run(
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(SCRIPTS / "Validate-TrunkState.ps1"), cwd=self.repo, check=False,
            )
        return run("bash", str(SCRIPTS / "validate-trunk-state.sh"), cwd=self.repo, check=False)

    def test_accepts_canonical_topology(self) -> None:
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: canonical trunk state", result.stdout)

    def test_rejects_dirty_tree(self) -> None:
        (self.repo / "untracked.txt").write_text("evidence\n", encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("working tree must be clean", result.stderr)

    def test_rejects_extra_local_branch(self) -> None:
        run("git", "branch", "extra", cwd=self.repo)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local branches must be exactly [main]", result.stderr)

    def test_rejects_active_lease(self) -> None:
        git_dir = Path(run("git", "rev-parse", "--git-common-dir", cwd=self.repo).stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.repo / git_dir
        (git_dir / "spacetime-uow.json").write_text("{}\n", encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no active UOW lease may exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
