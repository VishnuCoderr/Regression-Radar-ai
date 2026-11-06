"""
tests/test_hotspot.py — Unit tests for hotspot.py
"""

from __future__ import annotations

from datetime import UTC, datetime

from regression_radar.git_history import CommitInfo, DataQuality
from regression_radar.hotspot import calculate_hotspot_signal


def _make_commit(
    sha: str,
    subject: str,
    files: list[str],
    is_bugfix: bool = False,
) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        author_name="Dev",
        author_email="dev@example.com",
        timestamp=datetime.now(tz=UTC),
        subject=subject,
        body="",
        is_merge=False,
        changed_files=files,
        is_bugfix_candidate=is_bugfix,
    )


class TestHotspotSignal:
    def test_empty_changed_files_returns_zero(self) -> None:
        commits = [_make_commit("111111", "fix: something", ["app.py"], is_bugfix=True)]
        result = calculate_hotspot_signal([], commits)
        assert result.score == 0.0
        assert result.is_available is True
        assert "No files changed" in result.explanation

    def test_no_commits_returns_unavailable(self) -> None:
        result = calculate_hotspot_signal(["app.py"], [])
        assert result.score == 0.0
        assert result.is_available is False
        assert result.data_quality == DataQuality.LOW

    def test_file_with_high_bugfix_frequency_has_high_score(self) -> None:
        commits = [
            _make_commit("1111", "feat: initial", ["fragile.py"]),
            _make_commit("2222", "fix: bug 1", ["fragile.py"], is_bugfix=True),
            _make_commit("3333", "fix: bug 2", ["fragile.py"], is_bugfix=True),
            _make_commit("4444", "revert: rollback", ["fragile.py"], is_bugfix=True),
            _make_commit("5555", "fix: bug 3", ["fragile.py"], is_bugfix=True),
        ]
        result = calculate_hotspot_signal(["fragile.py"], commits)
        assert result.score >= 50.0
        assert len(result.recommendations) > 0
        assert "fragile.py" in result.explanation

    def test_file_with_no_bugfixes_has_low_score(self) -> None:
        commits = [
            _make_commit("1111", "feat: one", ["stable.py"]),
            _make_commit("2222", "feat: two", ["stable.py"]),
            _make_commit("3333", "refactor: three", ["stable.py"]),
            _make_commit("4444", "docs: four", ["stable.py"]),
        ]
        result = calculate_hotspot_signal(["stable.py"], commits)
        assert result.score < 25.0

    def test_brand_new_file_scores_zero(self) -> None:
        commits = [
            _make_commit("1111", "fix: unrelated", ["old.py"], is_bugfix=True),
        ]
        result = calculate_hotspot_signal(["brand_new.py"], commits)
        assert result.score == 0.0

    def test_multiple_files_aggregation(self) -> None:
        commits = [
            _make_commit("1111", "fix: bug in fragile", ["fragile.py"], is_bugfix=True),
            _make_commit("2222", "fix: another bug", ["fragile.py"], is_bugfix=True),
            _make_commit("3333", "feat: stable update", ["stable.py"], is_bugfix=False),
        ]
        result = calculate_hotspot_signal(["fragile.py", "stable.py"], commits)
        # Score is bounded and reflects the presence of the fragile file
        assert result.score > 20.0
        assert len(result.evidence["files"]) == 2
