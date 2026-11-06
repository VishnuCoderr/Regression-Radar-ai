"""
tests/test_ownership.py — Unit tests for ownership.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from regression_radar.git_history import CommitInfo
from regression_radar.ownership import calculate_ownership_signal


def _make_commit(
    sha: str,
    author: str,
    email: str,
    files: list[str],
) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        author_name=author,
        author_email=email,
        timestamp=datetime.now(tz=UTC),
        subject="commit",
        body="",
        is_merge=False,
        changed_files=files,
        is_bugfix_candidate=False,
    )


class TestOwnershipSignal:
    def test_empty_files_returns_zero(self) -> None:
        res = calculate_ownership_signal([], [])
        assert res.score == 0.0

    def test_no_commits_returns_unavailable(self) -> None:
        res = calculate_ownership_signal(["app.py"], [])
        assert res.is_available is False

    def test_author_with_primary_ownership_scores_low_risk(self) -> None:
        # alice@example.com authored all commits on app.py
        commits = [
            _make_commit("c1", "Alice", "alice@example.com", ["app.py"]),
            _make_commit("c2", "Alice", "alice@example.com", ["app.py"]),
            _make_commit("c3", "Alice", "alice@example.com", ["app.py"]),
        ]
        res = calculate_ownership_signal(
            ["app.py"],
            commits,
            pr_author_email="alice@example.com",
        )
        assert res.score <= 20.0
        assert "low" in res.explanation.lower()

    def test_author_with_zero_prior_commits_scores_higher_risk(self) -> None:
        # Bob created all commits; Alice is making the PR now
        commits = [
            _make_commit("c1", "Bob", "bob@example.com", ["app.py"]),
            _make_commit("c2", "Bob", "bob@example.com", ["app.py"]),
            _make_commit("c3", "Bob", "bob@example.com", ["app.py"]),
        ]
        res = calculate_ownership_signal(
            ["app.py"],
            commits,
            pr_author_email="alice@example.com",
        )
        assert res.score >= 60.0
        assert len(res.recommendations) > 0
        assert "Bob" in res.recommendations[0]

    def test_suggests_reviewers_excluding_pr_author(self) -> None:
        commits = [
            _make_commit("c1", "Alice", "alice@example.com", ["app.py"]),
            _make_commit("c2", "Bob", "bob@example.com", ["app.py"]),
            _make_commit("c3", "Charlie", "charlie@example.com", ["app.py"]),
        ]
        res = calculate_ownership_signal(
            ["app.py"],
            commits,
            pr_author_email="alice@example.com",
        )
        suggested = res.evidence["suggested_reviewers"]
        # Alice (the PR author) should NOT be in suggested reviewers
        suggested_emails = [r["author_email"] for r in suggested]
        assert "alice@example.com" not in suggested_emails
        assert "bob@example.com" in suggested_emails or "charlie@example.com" in suggested_emails
