"""
conftest.py — Shared pytest fixtures for Regression Radar tests.

The core fixture is `git_repo`, which creates a real Git repository in a
temporary directory and provides helper methods for building test scenarios.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


class GitRepoFixture:
    """
    A real Git repository created in a temporary directory.

    Usage::

        repo = GitRepoFixture(tmp_path)
        repo.write("src/app.py", "x = 1")
        repo.commit("initial commit")
        repo.write("src/app.py", "x = 2  # fix bug")
        repo.commit("fix: correct x value")
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._setup()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        """Initialise a bare-minimum Git repository."""
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test User")

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def write(self, relative_path: str, content: str) -> Path:
        """Write *content* to *relative_path*, creating directories as needed."""
        full = self.path / relative_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(textwrap.dedent(content), encoding="utf-8")
        return full

    def delete(self, relative_path: str) -> None:
        """Delete a file and stage the deletion."""
        full = self.path / relative_path
        if full.exists():
            full.unlink()
        self._git("rm", "--cached", relative_path)

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def add_all(self) -> None:
        self._git("add", "-A")

    def commit(
        self,
        message: str,
        *,
        author: str = "Test User <test@example.com>",
        add_all: bool = True,
    ) -> str:
        """Stage all changes and create a commit. Returns the commit SHA."""
        if add_all:
            self._git("add", "-A")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        result = subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git commit failed: {result.stderr}")
        # Return short SHA
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        ).stdout.strip()
        return sha

    def branch(self, name: str, checkout: bool = True) -> None:
        """Create (and optionally checkout) a branch."""
        self._git("branch", name)
        if checkout:
            self._git("checkout", name)

    def checkout(self, ref: str) -> None:
        self._git("checkout", ref)

    def head_sha(self) -> str:
        return self._git_output("rev-parse", "HEAD")

    def short_sha(self) -> str:
        return self._git_output("rev-parse", "--short", "HEAD")

    # ------------------------------------------------------------------
    # Scenario builders
    # ------------------------------------------------------------------

    def build_basic_history(self) -> None:
        """
        Create a small but realistic commit history with a mix of features,
        bug-fixes, and reverts for testing hotspot / co-change signals.
        """
        # Initial commit
        self.write("src/app.py", "def main(): pass\n")
        self.write("src/utils.py", "def helper(): pass\n")
        self.write("tests/test_app.py", "def test_main(): pass\n")
        self.commit("feat: initial application scaffold")

        # Feature
        self.write("src/app.py", "def main():\n    return 'hello'\n")
        self.write("src/utils.py", "def helper():\n    return True\n")
        self.commit("feat: implement main and helper")

        # Bug fix on app.py
        self.write("src/app.py", "def main():\n    return 'Hello, World!'\n")
        self.commit("fix: correct greeting capitalisation")

        # Another bug fix on app.py + utils.py together
        self.write("src/app.py", "def main():\n    return 'Hello'\n")
        self.write("src/utils.py", "def helper():\n    return False\n")
        self.commit("bug: fix helper returning wrong value")

        # Feature — adds new file
        self.write("src/api.py", "def api(): pass\n")
        self.commit("feat: add api module")

        # Revert
        self.write("src/app.py", "def main(): pass\n")
        self.commit("revert: undo hello change")

        # Bug fix on api.py
        self.write("src/api.py", "def api():\n    return {}\n")
        self.commit("fix: api should return dict")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _git(self, *args: str) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")

    def _git_output(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
        return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepoFixture:
    """Return an empty GitRepoFixture backed by a real temporary Git repo."""
    return GitRepoFixture(tmp_path)


@pytest.fixture
def git_repo_with_history(tmp_path: Path) -> GitRepoFixture:
    """Return a GitRepoFixture pre-loaded with realistic commit history."""
    fixture = GitRepoFixture(tmp_path)
    fixture.build_basic_history()
    return fixture
