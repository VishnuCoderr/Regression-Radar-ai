"""
tests/test_github_service.py — Unit tests for the GitHub integration service.

All tests mock urllib calls so no real network access is required.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from regression_radar.git_history import DataQuality
from regression_radar.github_service import (
    GitHubAPIError,
    GitHubPR,
    _fetch_pr_changed_files,
    _fetch_pr_metadata,
    _fetch_repo_commits,
    fetch_github_pr_data,
    parse_pr_url,
)

# ---------------------------------------------------------------------------
# parse_pr_url
# ---------------------------------------------------------------------------


class TestParsePrUrl:
    def test_valid_https_url(self) -> None:
        owner, repo, number = parse_pr_url("https://github.com/owner/repo/pull/42")
        assert owner == "owner"
        assert repo == "repo"
        assert number == 42

    def test_valid_url_with_trailing_slash(self) -> None:
        owner, repo, number = parse_pr_url("https://github.com/octocat/Hello-World/pull/1/")
        assert owner == "octocat"
        assert repo == "Hello-World"
        assert number == 1

    def test_valid_url_with_query_string(self) -> None:
        owner, repo, number = parse_pr_url(
            "https://github.com/org/project/pull/99?diff=split"
        )
        assert number == 99

    def test_invalid_not_a_pr_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://github.com/owner/repo/issues/42")

    def test_invalid_bare_repo_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://github.com/owner/repo")

    def test_invalid_non_github_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://gitlab.com/owner/repo/merge_requests/1")

    def test_invalid_local_path(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("C:\\Users\\user\\my-repo")

    def test_invalid_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("")

    def test_strips_whitespace(self) -> None:
        owner, repo, number = parse_pr_url("  https://github.com/a/b/pull/5  ")
        assert owner == "a"
        assert number == 5


# ---------------------------------------------------------------------------
# GitHub API error handling
# ---------------------------------------------------------------------------


def _make_mock_response(data: object, status: int = 200) -> MagicMock:
    """Create a mock urllib response context manager."""
    body = json.dumps(data).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.status = status
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _make_http_error(code: int, message: str = "error") -> urllib.error.HTTPError:
    err = urllib.error.HTTPError(
        url="https://api.github.com/test",
        code=code,
        msg=message,
        hdrs=MagicMock(),  # type: ignore[arg-type]
        fp=MagicMock(),
    )
    err.read = MagicMock(return_value=json.dumps({"message": message}).encode())
    return err


class TestFetchPrMetadata:
    _PR_PAYLOAD = {
        "number": 42,
        "title": "Fix payment validation",
        "state": "open",
        "draft": False,
        "html_url": "https://github.com/acme/payments/pull/42",
        "additions": 7,
        "deletions": 2,
        "changed_files": 1,
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/fix", "sha": "abc1234567890"},
    }

    def test_parses_metadata_correctly(self) -> None:
        with patch("urllib.request.urlopen", return_value=_make_mock_response(self._PR_PAYLOAD)):
            pr = _fetch_pr_metadata("acme", "payments", 42)
        assert pr.number == 42
        assert pr.title == "Fix payment validation"
        assert pr.base_ref == "main"
        assert pr.head_ref == "feature/fix"
        assert pr.author_login == "alice"
        assert pr.additions == 7
        assert pr.deletions == 2

    def test_raises_on_404(self) -> None:
        with patch("urllib.request.urlopen", side_effect=_make_http_error(404, "Not Found")):
            with pytest.raises(GitHubAPIError) as exc_info:
                _fetch_pr_metadata("acme", "payments", 9999)
        assert exc_info.value.status_code == 404

    def test_raises_on_401(self) -> None:
        with patch("urllib.request.urlopen", side_effect=_make_http_error(401, "Bad credentials")):
            with pytest.raises(GitHubAPIError) as exc_info:
                _fetch_pr_metadata("acme", "private-repo", 1)
        assert exc_info.value.status_code == 401

    def test_raises_on_403_rate_limit(self) -> None:
        err = _make_http_error(403, "API rate limit exceeded")
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(GitHubAPIError) as exc_info:
                _fetch_pr_metadata("acme", "payments", 1)
        assert exc_info.value.status_code == 403
        assert "rate limit" in str(exc_info.value).lower()

    def test_raises_on_network_error(self) -> None:
        import urllib.error
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(GitHubAPIError, match="Network error"):
                _fetch_pr_metadata("acme", "payments", 1)


class TestFetchPrChangedFiles:
    def test_returns_file_list(self) -> None:
        files_payload = [
            {"filename": "src/payments.py", "status": "modified"},
            {"filename": "tests/test_payments.py", "status": "modified"},
        ]
        with patch("urllib.request.urlopen", return_value=_make_mock_response(files_payload)):
            files = _fetch_pr_changed_files("acme", "payments", 42)
        assert files == ["src/payments.py", "tests/test_payments.py"]

    def test_handles_empty_file_list(self) -> None:
        with patch("urllib.request.urlopen", return_value=_make_mock_response([])):
            files = _fetch_pr_changed_files("acme", "payments", 42)
        assert files == []


class TestFetchRepoCommits:
    _AUTHOR = {"name": "Alice", "email": "alice@example.com", "date": "2024-01-15T10:00:00Z"}
    _COMMIT = {
        "sha": "abc" * 13 + "ab",  # 40 chars
        "commit": {"message": "fix: correct validation logic", "author": _AUTHOR},
        "author": {"login": "alice"},
    }

    def test_builds_commit_info_list(self) -> None:
        payload = [self._COMMIT] * 5
        with patch("urllib.request.urlopen", return_value=_make_mock_response(payload)):
            commits = _fetch_repo_commits("acme", "payments", "main")
        assert len(commits) == 5
        assert commits[0].author_name == "Alice"
        assert commits[0].is_bugfix_candidate is True  # "fix:" prefix

    def test_non_bugfix_commit(self) -> None:
        inner = {**self._COMMIT["commit"], "message": "chore: update deps"}  # type: ignore[index]
        commit = {**self._COMMIT, "commit": inner}
        with patch("urllib.request.urlopen", return_value=_make_mock_response([commit])):
            commits = _fetch_repo_commits("acme", "payments", "main")
        assert commits[0].is_bugfix_candidate is False

    def test_handles_empty_history(self) -> None:
        with patch("urllib.request.urlopen", return_value=_make_mock_response([])):
            commits = _fetch_repo_commits("acme", "payments", "main")
        assert commits == []


# ---------------------------------------------------------------------------
# fetch_github_pr_data — integration of all fetchers
# ---------------------------------------------------------------------------


class TestFetchGitHubPrData:
    _PR_PAYLOAD = {
        "number": 42,
        "title": "Fix payment validation",
        "state": "open",
        "draft": False,
        "html_url": "https://github.com/acme/payments/pull/42",
        "additions": 7,
        "deletions": 2,
        "changed_files": 1,
        "user": {"login": "new-dev"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/fix", "sha": "abc1234567890"},
    }
    _FILES_PAYLOAD = [{"filename": "payments/transaction.py"}]
    _COMMITS_PAYLOAD = [
        {
            "sha": f"{'a' * 39}{i}",
            "commit": {
                "message": f"fix: bug {i}",
                "author": {"name": "Alice", "email": "alice@example.com",
                            "date": "2024-01-10T10:00:00Z"},
            },
            "author": {"login": "alice"},
        }
        for i in range(5)
    ]

    def _make_sequence(self, *payloads: object) -> MagicMock:
        """Return a urlopen side_effect that yields each payload in turn."""
        responses = [_make_mock_response(p) for p in payloads]
        return MagicMock(side_effect=responses)

    def test_full_fetch_returns_data(self) -> None:
        # Calls: PR metadata, diff (text), PR files, repo commits (page 1)
        # enrich_commits=False to skip per-commit file fetch
        diff_text = "diff --git a/payments/transaction.py b/payments/transaction.py\n"

        # We mock both JSON api and diff request; easier to patch _api_request / _diff_request
        with (
            patch(
                "regression_radar.github_service._api_request",
                side_effect=[self._PR_PAYLOAD, self._FILES_PAYLOAD, self._COMMITS_PAYLOAD],
            ),
            patch(
                "regression_radar.github_service._diff_request",
                return_value=diff_text,
            ),
        ):
            data = fetch_github_pr_data("acme", "payments", 42, enrich_commits=False)

        assert data.pr.number == 42
        assert data.pr.base_ref == "main"
        assert data.diff.text == diff_text
        assert "payments/transaction.py" in data.diff.changed_paths
        assert len(data.commits) == 5
        assert data.data_quality == DataQuality.LOW  # < 10 commits

    def test_data_quality_high_with_many_commits(self) -> None:
        big_commits = [
            {
                "sha": f"{'b' * 39}{i % 10}",
                "commit": {
                    "message": "chore: update",
                    "author": {"name": "Dev", "email": "dev@example.com",
                                "date": "2024-01-01T00:00:00Z"},
                },
                "author": {"login": "dev"},
            }
            for i in range(35)
        ]
        with (
            patch(
                "regression_radar.github_service._api_request",
                side_effect=[self._PR_PAYLOAD, self._FILES_PAYLOAD, big_commits],
            ),
            patch("regression_radar.github_service._diff_request", return_value=""),
        ):
            data = fetch_github_pr_data("acme", "payments", 42, enrich_commits=False)
        assert data.data_quality == DataQuality.HIGH

    def test_github_api_error_propagates(self) -> None:
        with (
            patch(
                "regression_radar.github_service._api_request",
                side_effect=GitHubAPIError("Not Found", status_code=404),
            ),
        ):
            with pytest.raises(GitHubAPIError) as exc_info:
                fetch_github_pr_data("acme", "payments", 9999, enrich_commits=False)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# API endpoint integration (direct function calls, no HTTP client)
# ---------------------------------------------------------------------------


class TestAnalyzeGitHubPrEndpoint:
    """Test the FastAPI endpoint function directly (no TestClient)."""

    _PR_PAYLOAD = {
        "number": 10,
        "title": "Demo PR",
        "state": "open",
        "draft": False,
        "html_url": "https://github.com/demo/repo/pull/10",
        "additions": 3,
        "deletions": 1,
        "changed_files": 1,
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/x", "sha": "deadbeef1234"},
    }
    _FILES_PAYLOAD = [{"filename": "src/app.py"}]

    def test_invalid_url_raises_422(self) -> None:
        from fastapi import HTTPException

        from regression_radar.api import GitHubPRRequest, analyze_github_pr_endpoint

        req = GitHubPRRequest(pr_url="not-a-url")
        with pytest.raises(HTTPException) as exc_info:
            analyze_github_pr_endpoint(req)
        assert exc_info.value.status_code == 422

    def test_github_404_raises_404(self) -> None:
        from fastapi import HTTPException

        from regression_radar.api import GitHubPRRequest, analyze_github_pr_endpoint

        req = GitHubPRRequest(pr_url="https://github.com/no/repo/pull/1")
        with patch(
            "regression_radar.api.fetch_github_pr_data",
            side_effect=GitHubAPIError("Not found", status_code=404),
        ):
            with pytest.raises(HTTPException) as exc_info:
                analyze_github_pr_endpoint(req)
        assert exc_info.value.status_code == 404

    def test_github_rate_limit_raises_502(self) -> None:
        from fastapi import HTTPException

        from regression_radar.api import GitHubPRRequest, analyze_github_pr_endpoint

        req = GitHubPRRequest(pr_url="https://github.com/acme/repo/pull/5")
        with patch(
            "regression_radar.api.fetch_github_pr_data",
            side_effect=GitHubAPIError("Rate limit", status_code=429),
        ):
            with pytest.raises(HTTPException) as exc_info:
                analyze_github_pr_endpoint(req)
        assert exc_info.value.status_code == 502

    def test_valid_pr_runs_analysis(self, git_repo_with_history: GitRepoFixture) -> None:  # noqa: F821
        """End-to-end: mock GitHub data, verify AnalysisResult is returned."""
        from regression_radar.api import GitHubPRRequest, analyze_github_pr_endpoint
        from regression_radar.git_history import DataQuality, RawDiff, get_commits
        from regression_radar.github_service import GitHubAnalysisData

        history = get_commits(git_repo_with_history.path)
        pr = GitHubPR(
            owner="acme", repo="repo", number=10, title="Test PR", state="open",
            base_ref="main", head_ref="feature/x", head_sha="abc1234",
            author_login="alice", author_email="alice@example.com",
            additions=3, deletions=1, changed_files=1, is_draft=False,
            html_url="https://github.com/acme/repo/pull/10",
        )
        diff_text = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n+++ b/src/app.py\n"
            "@@ -1 +1 @@\n-def main(): pass\n+def main(): return 'hello'\n"
        )
        gh_data = GitHubAnalysisData(
            pr=pr,
            diff=RawDiff(base_ref="main", head_ref="feature/x", text=diff_text,
                         changed_paths=["src/app.py"]),
            commits=history,
            data_quality=DataQuality.HIGH,
        )

        req = GitHubPRRequest(pr_url="https://github.com/acme/repo/pull/10")
        with patch("regression_radar.api.fetch_github_pr_data", return_value=gh_data):
            result = analyze_github_pr_endpoint(req)

        assert result.overall_score >= 0
        assert result.risk_category in ("low", "medium", "high", "critical")
        assert "historical_hotspot" in result.signals
        assert result.total_files_changed == 1


class TestTokenStatusEndpoint:
    def test_no_token(self) -> None:
        from regression_radar.api import github_token_status

        with patch.dict("os.environ", {}, clear=True):
            # Ensure both token vars are absent
            import os
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_TOKEN", None)
            result = github_token_status()
        assert result["has_token"] is False

    def test_with_token(self) -> None:
        from regression_radar.api import github_token_status

        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_fake"}):
            result = github_token_status()
        assert result["has_token"] is True
