"""
tests/test_reliability_validation.py — Milestone 3: Reliability & Validation tests.

Targeted test suite covering:
1. Empty repositories.
2. Missing Git history and low data quality.
3. Unknown PR authors and unfamiliar authors.
4. New files without historical data.
5. Missing matching tests vs untouched tests.
6. Renamed and deleted files.
7. Missing co-change history.
8. Unavailable or incomplete GitHub metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from regression_radar.api import AnalyzeRequest, analyze_endpoint
from regression_radar.cochange import calculate_cochange_signal
from regression_radar.git_history import (
    CommitInfo,
    DataQuality,
    get_commits,
    get_repo_stats,
)
from regression_radar.github_service import _fetch_pr_metadata
from regression_radar.hotspot import calculate_hotspot_signal
from regression_radar.models import RiskCategory
from regression_radar.ownership import calculate_ownership_signal
from regression_radar.recommendations import build_recommendations
from regression_radar.scoring import build_analysis_result
from regression_radar.test_gap import calculate_test_gap_signal


def _make_commit(
    sha: str,
    files: list[str],
    author_email: str = "dev@example.com",
    is_bugfix: bool = False,
    subject: str = "commit",
) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        author_name="Dev",
        author_email=author_email,
        timestamp=datetime.now(tz=UTC),
        subject=subject,
        body="",
        is_merge=False,
        changed_files=files,
        is_bugfix_candidate=is_bugfix,
    )


# ---------------------------------------------------------------------------
# 1. Empty Repositories
# ---------------------------------------------------------------------------


class TestEmptyRepository:
    def test_empty_repo_stats(self, tmp_path: Path) -> None:
        import subprocess

        # Initialize an empty repo without commits
        empty_dir = tmp_path / "empty_repo"
        empty_dir.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=empty_dir, check=True, capture_output=True
        )

        stats = get_repo_stats(empty_dir)
        assert stats.total_commits == 0
        assert stats.head_sha is None
        assert stats.data_quality == DataQuality.LOW

    def test_empty_repo_get_commits_returns_empty_list(self, tmp_path: Path) -> None:
        import subprocess

        empty_dir = tmp_path / "empty_repo_commits"
        empty_dir.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=empty_dir, check=True, capture_output=True
        )

        commits = get_commits(empty_dir)
        assert commits == []

    def test_empty_repo_api_endpoint_raises_400(self, tmp_path: Path) -> None:
        import subprocess

        empty_dir = tmp_path / "empty_repo_api"
        empty_dir.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=empty_dir, check=True, capture_output=True
        )

        req = AnalyzeRequest(repo_path=str(empty_dir))
        with pytest.raises(HTTPException) as exc_info:
            analyze_endpoint(req)
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 2. Missing Git History & Unavailable Signal Handling
# ---------------------------------------------------------------------------


class TestMissingGitHistory:
    def test_cochange_unavailable_with_under_5_commits(self) -> None:
        commits = [_make_commit(f"c{i}", ["src/a.py", "src/b.py"]) for i in range(4)]
        res = calculate_cochange_signal(["src/a.py"], commits)
        assert res.is_available is False
        assert "Insufficient commit history" in res.explanation

    def test_hotspot_unavailable_with_zero_commits(self) -> None:
        res = calculate_hotspot_signal(["src/a.py"], [])
        assert res.is_available is False
        assert "No historical commits available" in res.explanation

    def test_ownership_unavailable_with_zero_commits(self) -> None:
        res = calculate_ownership_signal(["src/a.py"], [])
        assert res.is_available is False
        assert "No commit history available" in res.explanation

    def test_unavailable_signals_do_not_silently_claim_safe(self) -> None:
        # All history signals unavailable, test gap is available
        hotspot = calculate_hotspot_signal(["src/a.py"], [])
        cochange = calculate_cochange_signal(["src/a.py"], [])
        ownership = calculate_ownership_signal(["src/a.py"], [])
        test_gap = calculate_test_gap_signal(["src/a.py"], [])

        signals = {
            "historical_hotspot": hotspot,
            "cochange_anomaly": cochange,
            "test_gap": test_gap,
            "ownership": ownership,
        }

        actions = build_recommendations(
            signals, overall_score=test_gap.score, category=RiskCategory.HIGH
        )
        assert "Limited commit history" in actions.summary
        assert "3 signal(s) were unavailable" in actions.summary

        # build_analysis_result should note the unavailable signals in why_flagged
        res = build_analysis_result(
            signals=signals,
            base_ref="main",
            head_ref="HEAD",
            total_files_changed=1,
            additions=10,
            deletions=0,
            data_quality=DataQuality.LOW,
            recommended_actions=actions,
        )
        has_warning = any(
            "unavailable" in b.lower() or "insufficient" in b.lower() for b in res.why_flagged
        )
        assert has_warning


# ---------------------------------------------------------------------------
# 3. Unknown PR Authors
# ---------------------------------------------------------------------------


class TestUnknownPRAuthors:
    def test_unfamiliar_author_gets_high_ownership_risk(self) -> None:
        commits = [
            _make_commit(f"c{i}", ["src/core.py"], author_email="veteran@example.com")
            for i in range(20)
        ]
        # New author has 0% historical commit share
        res = calculate_ownership_signal(
            ["src/core.py"], commits, pr_author_email="newbie@example.com"
        )
        assert res.score >= 80.0
        assert "few prior changes" in res.explanation
        assert "veteran@example.com" in res.recommendations[0]

    def test_author_not_provided_falls_back_to_maintenance_distribution(self) -> None:
        commits = [
            _make_commit("c1", ["src/core.py"], author_email="alice@example.com"),
            _make_commit("c2", ["src/core.py"], author_email="bob@example.com"),
        ]
        res = calculate_ownership_signal(
            ["src/core.py"], commits, pr_author_email=None
        )
        assert res.score == 25.0
        assert "distributed maintenance" in res.explanation

    def test_empty_string_author_treated_as_none(self) -> None:
        commits = [
            _make_commit("c1", ["src/core.py"], author_email="alice@example.com"),
        ]
        res = calculate_ownership_signal(
            ["src/core.py"], commits, pr_author_email="   "
        )
        # Single maintainer -> 50.0
        assert res.score == 50.0


# ---------------------------------------------------------------------------
# 4. New Files Without Historical Data
# ---------------------------------------------------------------------------


class TestNewFiles:
    def test_new_source_file_without_tests_flags_high_test_gap(self) -> None:
        commits = [_make_commit("c1", ["src/existing.py"])]
        test_gap = calculate_test_gap_signal(
            ["src/new_feature.py"], commits, repo_files=["src/existing.py"]
        )
        assert test_gap.score >= 70.0
        assert "no matching test file" in test_gap.explanation

    def test_new_source_file_with_new_test_in_pr_gives_zero_gap(self) -> None:
        commits = [_make_commit("c1", ["src/existing.py"])]
        test_gap = calculate_test_gap_signal(
            ["src/new_feature.py", "tests/test_new_feature.py"],
            commits,
            repo_files=["src/existing.py"],
        )
        assert test_gap.score == 0.0

    def test_new_file_ownership_explains_new_status(self) -> None:
        commits = [_make_commit("c1", ["src/other.py"])]
        res = calculate_ownership_signal(["src/brand_new.py"], commits)
        assert res.score == 20.0
        assert "new files" in res.explanation


# ---------------------------------------------------------------------------
# 5. Missing Matching Tests vs Untouched Tests
# ---------------------------------------------------------------------------


class TestMissingVsUntouchedTests:
    def test_missing_matching_test_demands_creation(self) -> None:
        commits = [_make_commit("c1", ["src/service.py"])]
        res = calculate_test_gap_signal(["src/service.py"], commits, repo_files=["src/service.py"])
        assert res.score == 75.0
        assert any("Add test coverage" in r for r in res.recommendations)

    def test_untouched_test_recommends_verification(self) -> None:
        commits = [_make_commit("c1", ["src/service.py", "tests/test_service.py"])]
        res = calculate_test_gap_signal(
            ["src/service.py"],
            commits,
            repo_files=["src/service.py", "tests/test_service.py"],
        )
        assert res.score == 40.0
        assert any("Verify or run" in r for r in res.recommendations)


# ---------------------------------------------------------------------------
# 6. Renamed and Deleted Files
# ---------------------------------------------------------------------------


class TestRenamedAndDeletedFiles:
    def test_renamed_file_inherits_hotspot_history(self) -> None:
        # History has 5 bugfix commits on src/legacy.py
        commits = [
            _make_commit(f"c{i}", ["src/legacy.py"], is_bugfix=True, subject=f"fix: bug {i}")
            for i in range(5)
        ] + [
            _make_commit("c10", ["src/legacy.py"], is_bugfix=False, subject="feat: init")
        ]

        # File is renamed to src/modern.py in the PR
        renames = {"src/modern.py": "src/legacy.py"}
        res = calculate_hotspot_signal(["src/modern.py"], commits, renames=renames)
        assert res.score > 40.0
        assert res.evidence["files"][0]["bugfix_commits"] == 5

    def test_renamed_file_finds_test_under_old_name(self) -> None:
        commits = [_make_commit("c1", ["src/legacy.py", "tests/test_legacy.py"])]
        renames = {"src/modern.py": "src/legacy.py"}
        res = calculate_test_gap_signal(
            ["src/modern.py"],
            commits,
            repo_files=["src/legacy.py", "tests/test_legacy.py"],
            renames=renames,
        )
        # Finds tests/test_legacy.py under old name, but it was untouched in PR -> penalty 40.0
        assert res.score == 40.0
        assert res.evidence["files"][0]["matched_test_file"] == "tests/test_legacy.py"

    def test_deleted_file_without_test_not_penalized(self) -> None:
        commits = [_make_commit("c1", ["src/legacy.py"])]
        res = calculate_test_gap_signal(
            ["src/legacy.py"],
            commits,
            repo_files=["src/legacy.py"],
            deleted_files=["src/legacy.py"],
        )
        # Deleting code should not trigger a demand to write tests
        assert res.score == 0.0

    def test_deleted_file_with_untouched_test_flags_alert(self) -> None:
        commits = [_make_commit("c1", ["src/legacy.py", "tests/test_legacy.py"])]
        res = calculate_test_gap_signal(
            ["src/legacy.py"],
            commits,
            repo_files=["src/legacy.py", "tests/test_legacy.py"],
            deleted_files=["src/legacy.py"],
        )
        # Old test remains in the repo -> penalty 40.0 alert
        assert res.score == 40.0


# ---------------------------------------------------------------------------
# 7. Missing Co-change History
# ---------------------------------------------------------------------------


class TestMissingCochangeHistory:
    def test_no_cochange_rules_gives_clean_zero(self) -> None:
        commits = [
            _make_commit(f"c{i}", [f"src/file_{i}.py"])
            for i in range(10)
        ]
        res = calculate_cochange_signal(["src/file_0.py"], commits)
        assert res.score == 0.0
        assert res.is_available is True
        assert "No strong historical co-change relationships" in res.explanation


# ---------------------------------------------------------------------------
# 8. Unavailable or Incomplete GitHub Metadata
# ---------------------------------------------------------------------------


class TestGitHubMetadataResilience:
    def test_pr_metadata_with_none_values(self) -> None:
        payload = {
            "number": 1,
            "title": None,
            "state": None,
            "draft": None,
            "html_url": None,
            "additions": None,
            "deletions": None,
            "changed_files": None,
            "user": None,
            "base": None,
            "head": None,
        }
        with patch("regression_radar.github_service._api_request", return_value=payload):
            pr = _fetch_pr_metadata("owner", "repo", 1)

        assert pr.number == 1
        assert pr.title == ""
        assert pr.state == "open"
        assert pr.base_ref == "main"
        assert pr.head_ref == "HEAD"
        assert pr.author_login == ""
        assert pr.author_email == ""
        assert pr.additions == 0
        assert pr.deletions == 0
        assert pr.changed_files == 0
        assert pr.is_draft is False
