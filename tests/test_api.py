"""
tests/test_api.py — Unit tests for FastAPI endpoints.

Tests route functions directly to avoid anyio event-loop deadlocks on Python 3.14.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from regression_radar.api import (
    AnalyzeRequest,
    analyze_endpoint,
    analyze_markdown_endpoint,
    get_config,
    health_check,
)
from tests.conftest import GitRepoFixture


class TestApiFunctions:
    def test_health_check(self) -> None:
        res = health_check()
        assert res.status == "healthy"
        assert res.version != ""

    def test_get_config(self) -> None:
        cfg = get_config()
        assert "weights" in cfg
        assert "thresholds" in cfg
        assert "historical_hotspot" in cfg["weights"]

    def test_analyze_invalid_path(self) -> None:
        req = AnalyzeRequest(repo_path="/path/that/does/not/exist")
        with pytest.raises(HTTPException) as exc_info:
            analyze_endpoint(req)
        assert exc_info.value.status_code == 400

    def test_analyze_valid_repo(self, git_repo_with_history: GitRepoFixture) -> None:
        git_repo_with_history.branch("feature/test-branch", checkout=True)
        git_repo_with_history.write("src/app.py", "def main(): return 'modified'\n")
        git_repo_with_history.commit("feat: update app in feature branch")

        req = AnalyzeRequest(
            repo_path=str(git_repo_with_history.path),
            base_ref="main",
            head_ref="HEAD",
        )
        res = analyze_endpoint(req)
        assert res.total_files_changed == 1
        assert "historical_hotspot" in res.signals
        assert len(res.why_flagged) > 0

    def test_analyze_markdown(self, git_repo_with_history: GitRepoFixture) -> None:
        git_repo_with_history.branch("feature/test-branch-2", checkout=True)
        git_repo_with_history.write("src/app.py", "def main(): return 'modified 2'\n")
        git_repo_with_history.commit("feat: another update")

        req = AnalyzeRequest(
            repo_path=str(git_repo_with_history.path),
            base_ref="main",
            head_ref="HEAD",
        )
        res = analyze_markdown_endpoint(req)
        assert "markdown" in res
        assert "Regression Risk:" in res["markdown"]
