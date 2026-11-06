"""
tests/test_cochange.py — Unit tests for cochange.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from regression_radar.cochange import calculate_cochange_signal
from regression_radar.git_history import CommitInfo


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


class TestCochangeSignal:
    def test_empty_changed_files_returns_zero(self) -> None:
        commits = [_make_commit("1111", ["a.py", "b.py"])]
        res = calculate_cochange_signal([], commits)
        assert res.score == 0.0

    def test_missing_strong_partner_triggers_anomaly(self) -> None:
        # a.py and b.py always change together in 4 commits
        commits = [
            _make_commit("c1", ["a.py", "b.py"]),
            _make_commit("c2", ["a.py", "b.py"]),
            _make_commit("c3", ["a.py", "b.py"]),
            _make_commit("c4", ["a.py", "b.py"]),
            _make_commit("c5", ["other.py"]),
        ]
        # PR changes a.py ONLY; b.py is missing!
        res = calculate_cochange_signal(
            ["a.py"],
            commits,
            min_support=3,
            min_confidence=0.5,
        )
        assert res.score >= 50.0
        missing = res.evidence["missing_partners"]
        assert len(missing) == 1
        assert missing[0]["missing_partner"] == "b.py"
        assert len(res.recommendations) > 0

    def test_both_partners_included_in_pr_gives_zero_score(self) -> None:
        commits = [
            _make_commit("c1", ["a.py", "b.py"]),
            _make_commit("c2", ["a.py", "b.py"]),
            _make_commit("c3", ["a.py", "b.py"]),
            _make_commit("c4", ["a.py", "b.py"]),
            _make_commit("c5", ["other.py"]),
        ]
        # Both a.py and b.py are included in PR!
        res = calculate_cochange_signal(
            ["a.py", "b.py"],
            commits,
            min_support=3,
            min_confidence=0.5,
        )
        assert res.score == 0.0
        assert len(res.evidence["satisfied_partners"]) >= 1

    def test_below_support_threshold_ignored(self) -> None:
        # Changed together only 2 times, below min_support=3
        commits = [
            _make_commit("c1", ["a.py", "b.py"]),
            _make_commit("c2", ["a.py", "b.py"]),
            _make_commit("c3", ["a.py"]),
            _make_commit("c4", ["a.py"]),
            _make_commit("c5", ["other.py"]),
        ]
        res = calculate_cochange_signal(
            ["a.py"],
            commits,
            min_support=3,
            min_confidence=0.5,
        )
        assert res.score == 0.0
        assert len(res.evidence["missing_partners"]) == 0

    def test_insufficient_history_returns_unavailable(self) -> None:
        commits = [
            _make_commit("c1", ["a.py", "b.py"]),
            _make_commit("c2", ["a.py", "b.py"]),
        ]
        res = calculate_cochange_signal(["a.py"], commits)
        assert res.is_available is False
        assert res.score == 0.0
