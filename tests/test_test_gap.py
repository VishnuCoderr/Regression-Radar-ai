"""
tests/test_test_gap.py — Unit tests for test_gap.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from regression_radar.git_history import CommitInfo
from regression_radar.test_gap import (
    calculate_test_gap_signal,
    find_candidate_test_paths,
    is_source_file,
    is_test_file,
)


def _make_commit(sha: str, files: list[str]) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        author_name="Dev",
        author_email="dev@example.com",
        timestamp=datetime.now(tz=UTC),
        subject="commit",
        body="",
        is_merge=False,
        changed_files=files,
        is_bugfix_candidate=False,
    )


class TestFileClassification:
    def test_test_file_patterns(self) -> None:
        assert is_test_file("tests/test_app.py") is True
        assert is_test_file("src/test/java/AppTest.java") is True
        assert is_test_file("app_test.go") is True
        assert is_test_file("components/button.test.tsx") is True
        assert is_test_file("src/app.py") is False

    def test_source_file_patterns(self) -> None:
        assert is_source_file("src/app.py") is True
        assert is_source_file("lib/utils.ts") is True
        assert is_source_file("README.md") is False
        assert is_source_file("pyproject.toml") is False
        assert is_source_file("tests/test_app.py") is False

    def test_candidate_test_paths(self) -> None:
        candidates = find_candidate_test_paths("src/auth/service.py")
        assert any("test_service.py" in c for c in candidates)
        assert any("tests/auth/test_service.py" in c.replace("\\", "/") for c in candidates)


class TestTestGapSignal:
    def test_non_source_files_give_zero_score(self) -> None:
        commits = [_make_commit("c1", ["README.md"])]
        res = calculate_test_gap_signal(["README.md", "docs/index.md"], commits)
        assert res.score == 0.0

    def test_source_with_updated_test_gives_zero_score(self) -> None:
        # Both source and its test were modified in PR!
        commits = [_make_commit("c1", ["src/app.py", "tests/test_app.py"])]
        res = calculate_test_gap_signal(
            ["src/app.py", "tests/test_app.py"],
            commits,
            repo_files=["src/app.py", "tests/test_app.py"],
        )
        assert res.score == 0.0
        assert "All 1 modified source file(s) have matching test updates" in res.explanation

    def test_source_with_existing_but_untouched_test_gives_moderate_score(self) -> None:
        # Test exists in repo, but was NOT touched in this PR
        commits = [_make_commit("c1", ["src/app.py", "tests/test_app.py"])]
        res = calculate_test_gap_signal(
            ["src/app.py"],
            commits,
            repo_files=["src/app.py", "tests/test_app.py"],
        )
        assert 30.0 <= res.score <= 50.0
        assert len(res.recommendations) > 0
        assert "tests/test_app.py" in res.recommendations[0]

    def test_source_with_no_test_found_gives_high_score(self) -> None:
        # Source has never had any test anywhere
        commits = [_make_commit("c1", ["src/orphan.py"])]
        res = calculate_test_gap_signal(
            ["src/orphan.py"],
            commits,
            repo_files=["src/orphan.py"],
        )
        assert res.score >= 60.0
        assert "no matching test file" in res.explanation
