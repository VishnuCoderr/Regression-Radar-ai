"""
tests/test_git_history.py — Unit and integration tests for git_history.py

All tests use real in-process Git repositories (via GitRepoFixture) so
there is no mocking of subprocess — results are always real Git output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regression_radar.git_history import (
    DataQuality,
    _default_bugfix_patterns,
    _is_shallow,
    get_commits,
    get_diff,
    get_repo_stats,
    validate_repo,
)
from tests.conftest import GitRepoFixture

# ---------------------------------------------------------------------------
# validate_repo
# ---------------------------------------------------------------------------


class TestValidateRepo:
    def test_valid_repo(self, git_repo: GitRepoFixture) -> None:
        result = validate_repo(git_repo.path)
        assert result.is_dir()

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            validate_repo(tmp_path / "ghost")

    def test_non_git_dir_raises(self, tmp_path: Path) -> None:
        plain_dir = tmp_path / "plain"
        plain_dir.mkdir()
        with pytest.raises(ValueError, match="Not a Git repository"):
            validate_repo(plain_dir)

    def test_file_path_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="not a directory"):
            validate_repo(f)

    def test_non_git_subdir_inside_repo_raises(self, git_repo: GitRepoFixture) -> None:
        sub_dir = git_repo.path / "subdir"
        sub_dir.mkdir()
        with pytest.raises(ValueError, match="Not a Git repository"):
            validate_repo(sub_dir)


# ---------------------------------------------------------------------------
# get_repo_stats
# ---------------------------------------------------------------------------


class TestGetRepoStats:
    def test_empty_repo_has_zero_commits(self, git_repo: GitRepoFixture) -> None:
        stats = get_repo_stats(git_repo.path)
        assert stats.total_commits == 0
        assert stats.data_quality == DataQuality.LOW
        assert stats.head_sha is None

    def test_repo_with_one_commit(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("file.txt", "hello")
        git_repo.commit("initial")
        stats = get_repo_stats(git_repo.path)
        assert stats.total_commits == 1
        assert stats.data_quality == DataQuality.LOW  # < 10 commits

    def test_shallow_detection_no_shallow_file(self, git_repo: GitRepoFixture) -> None:
        # Normal repos should not be shallow
        assert not _is_shallow(git_repo.path)

    def test_medium_quality_requires_10_to_29_commits(self, git_repo: GitRepoFixture) -> None:
        # Create exactly 10 commits
        for i in range(10):
            git_repo.write(f"file_{i}.txt", f"content {i}")
            git_repo.commit(f"commit {i}")
        stats = get_repo_stats(git_repo.path)
        assert stats.total_commits == 10
        assert stats.data_quality == DataQuality.MEDIUM

    def test_high_quality_requires_30_plus_commits(self, git_repo: GitRepoFixture) -> None:
        for i in range(30):
            git_repo.write(f"file_{i}.txt", f"content {i}")
            git_repo.commit(f"commit {i}")
        stats = get_repo_stats(git_repo.path)
        assert stats.total_commits == 30
        assert stats.data_quality == DataQuality.HIGH

    def test_default_branch_detected(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "x")
        git_repo.commit("init")
        stats = get_repo_stats(git_repo.path)
        assert stats.default_branch == "main"


# ---------------------------------------------------------------------------
# get_commits
# ---------------------------------------------------------------------------


class TestGetCommits:
    def test_empty_repo_returns_empty(self, git_repo: GitRepoFixture) -> None:
        commits = get_commits(git_repo.path)
        assert commits == []

    def test_single_commit(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("hello.py", "print('hi')")
        git_repo.commit("feat: add hello")
        commits = get_commits(git_repo.path)
        assert len(commits) == 1
        assert commits[0].subject == "feat: add hello"

    def test_commit_has_changed_files(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("src/app.py", "x = 1")
        git_repo.write("src/utils.py", "y = 2")
        git_repo.commit("add two files")
        commits = get_commits(git_repo.path)
        assert len(commits) == 1
        paths = commits[0].changed_files
        assert any("app.py" in p for p in paths)
        assert any("utils.py" in p for p in paths)

    def test_bugfix_candidate_detected_by_fix_prefix(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "v1")
        git_repo.commit("fix: resolve null pointer")
        commits = get_commits(git_repo.path)
        assert commits[0].is_bugfix_candidate is True

    def test_bugfix_candidate_detected_by_bug_keyword(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "v1")
        git_repo.commit("bug: wrong calculation")
        commits = get_commits(git_repo.path)
        assert commits[0].is_bugfix_candidate is True

    def test_bugfix_candidate_detected_by_revert(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "v1")
        git_repo.commit("revert: undo last change")
        commits = get_commits(git_repo.path)
        assert commits[0].is_bugfix_candidate is True

    def test_non_bugfix_commit_not_flagged(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "v1")
        git_repo.commit("feat: add awesome feature")
        commits = get_commits(git_repo.path)
        assert commits[0].is_bugfix_candidate is False

    def test_multiple_commits_ordered_newest_first(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("a.txt", "1")
        git_repo.commit("first")
        git_repo.write("b.txt", "2")
        git_repo.commit("second")
        commits = get_commits(git_repo.path)
        assert len(commits) == 2
        assert commits[0].subject == "second"
        assert commits[1].subject == "first"

    def test_max_commits_cap_respected(self, git_repo: GitRepoFixture) -> None:
        for i in range(5):
            git_repo.write(f"f{i}.txt", str(i))
            git_repo.commit(f"commit {i}")
        commits = get_commits(git_repo.path, max_commits=3)
        assert len(commits) == 3

    def test_base_ref_range(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("a.txt", "1")
        git_repo.commit("base commit")  # will be the base
        git_repo.write("b.txt", "2")
        git_repo.commit("range commit 1")
        git_repo.write("c.txt", "3")
        git_repo.commit("range commit 2")

        # Only commits after the first (HEAD~2) should be returned
        commits = get_commits(git_repo.path, base_ref="HEAD~2")
        assert len(commits) == 2
        subjects = {c.subject for c in commits}
        assert "range commit 1" in subjects
        assert "range commit 2" in subjects
        assert "base commit" not in subjects

    def test_unknown_base_ref_returns_empty(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "x")
        git_repo.commit("init")
        result = get_commits(git_repo.path, base_ref="nonexistent-branch")
        assert result == []

    def test_full_history_scenario(self, git_repo_with_history: GitRepoFixture) -> None:
        """Integration test using the realistic history fixture."""
        commits = get_commits(git_repo_with_history.path)
        assert len(commits) >= 6

        bugfix_commits = [c for c in commits if c.is_bugfix_candidate]
        assert len(bugfix_commits) >= 3  # fix, bug, fix, revert patterns

    def test_bugfix_patterns_configurable(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "v1")
        git_repo.commit("TICKET-42: resolve alignment issue")
        # With default patterns, this is NOT a bugfix
        commits_default = get_commits(git_repo.path)
        assert commits_default[0].is_bugfix_candidate is False
        # With custom patterns including 'ticket', it should be
        commits_custom = get_commits(git_repo.path, bugfix_patterns=[r"\bticket\b"])
        assert commits_custom[0].is_bugfix_candidate is True

    def test_commit_timestamp_parsed(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "x")
        git_repo.commit("init")
        commits = get_commits(git_repo.path)
        assert commits[0].timestamp is not None
        assert commits[0].timestamp.year >= 2024

    def test_commit_author_captured(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.txt", "x")
        git_repo.commit("init")
        commits = get_commits(git_repo.path)
        assert commits[0].author_name == "Test User"
        assert commits[0].author_email == "test@example.com"


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------


class TestGetDiff:
    def test_diff_between_two_commits(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("hello.py", "x = 1")
        git_repo.commit("init")
        git_repo.write("hello.py", "x = 2")
        git_repo.commit("change x")

        diff = get_diff(git_repo.path, base_ref="HEAD~1", head_ref="HEAD")
        assert "hello.py" in diff.changed_paths
        assert diff.base_ref == "HEAD~1"
        assert diff.head_ref == "HEAD"

    def test_diff_text_contains_unified_format(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.py", "a = 1")
        git_repo.commit("init")
        git_repo.write("f.py", "a = 2")
        git_repo.commit("update")

        diff = get_diff(git_repo.path, base_ref="HEAD~1", head_ref="HEAD")
        assert "@@" in diff.text
        assert "+a = 2" in diff.text
        assert "-a = 1" in diff.text

    def test_no_changes_produces_empty_diff(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("f.py", "a = 1")
        git_repo.commit("init")

        # Diff HEAD against itself
        diff = get_diff(git_repo.path, base_ref="HEAD", head_ref="HEAD")
        assert diff.changed_paths == []
        assert diff.text.strip() == ""

    def test_diff_captures_new_file(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("existing.py", "x = 1")
        git_repo.commit("init")
        git_repo.write("new_file.py", "y = 2")
        git_repo.commit("add new file")

        diff = get_diff(git_repo.path, base_ref="HEAD~1", head_ref="HEAD")
        assert "new_file.py" in diff.changed_paths

    def test_diff_captures_deleted_file(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("to_delete.py", "x = 1")
        git_repo.write("keep.py", "y = 2")
        git_repo.commit("init")
        (git_repo.path / "to_delete.py").unlink()
        git_repo.commit("remove file")

        diff = get_diff(git_repo.path, base_ref="HEAD~1", head_ref="HEAD")
        assert "to_delete.py" in diff.changed_paths

    def test_diff_multiple_files(self, git_repo: GitRepoFixture) -> None:
        git_repo.write("a.py", "a = 1")
        git_repo.write("b.py", "b = 1")
        git_repo.commit("init")
        git_repo.write("a.py", "a = 2")
        git_repo.write("b.py", "b = 2")
        git_repo.commit("update both")

        diff = get_diff(git_repo.path, base_ref="HEAD~1", head_ref="HEAD")
        assert "a.py" in diff.changed_paths
        assert "b.py" in diff.changed_paths
        assert len(diff.changed_paths) == 2


# ---------------------------------------------------------------------------
# Default bugfix patterns smoke test
# ---------------------------------------------------------------------------


class TestDefaultBugfixPatterns:
    def test_returns_non_empty_list(self) -> None:
        patterns = _default_bugfix_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_all_patterns_are_strings(self) -> None:
        for p in _default_bugfix_patterns():
            assert isinstance(p, str)

    def test_fix_prefix_matches(self) -> None:
        import re

        patterns = [re.compile(p, re.IGNORECASE) for p in _default_bugfix_patterns()]
        subject = "fix: null pointer in auth module"
        assert any(p.search(subject) for p in patterns)

    def test_feature_commit_does_not_match(self) -> None:
        import re

        patterns = [re.compile(p, re.IGNORECASE) for p in _default_bugfix_patterns()]
        subject = "feat: add dark mode toggle"
        assert not any(p.search(subject) for p in patterns)
