"""
github_service.py — GitHub REST API integration for Regression Radar.

Fetches PR metadata, diff text, and commit history from the GitHub API and
maps them to the internal CommitInfo / RawDiff types consumed by the existing
analysis engines.

Design decisions:
- Uses only stdlib urllib (no new runtime deps).
- Token is read from GITHUB_TOKEN env-var; unauthenticated access is allowed
  with a reduced rate limit (60 req/hour) for public repos.
- Never sends source code or file contents to external APIs.
- Returns CommitInfo objects synthesised from GitHub commit data so the
  existing hotspot / cochange / ownership / test-gap engines work unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from regression_radar.git_history import CommitInfo, DataQuality, RawDiff

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_MAX_COMMITS = 250  # GitHub lists up to 250 commits per PR


# ---------------------------------------------------------------------------
# Public data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitHubPR:
    """Minimal PR metadata returned by the GitHub API."""

    owner: str
    repo: str
    number: int
    title: str
    state: str  # "open" | "closed" | "merged"
    base_ref: str
    head_ref: str
    head_sha: str
    author_login: str
    author_email: str  # May be empty — GitHub doesn't always expose this
    additions: int
    deletions: int
    changed_files: int
    is_draft: bool
    html_url: str


@dataclass
class GitHubAnalysisData:
    """All data fetched from GitHub needed to run the four analysis engines."""

    pr: GitHubPR
    diff: RawDiff
    commits: list[CommitInfo]
    data_quality: DataQuality


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?$",
    re.IGNORECASE,
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """
    Parse a GitHub PR URL and return (owner, repo, pr_number).

    Raises
    ------
    ValueError
        If the URL does not match the expected GitHub PR pattern.
    """
    url = url.strip().rstrip("/")
    # Strip query string / fragment
    url = url.split("?")[0].split("#")[0]
    m = _PR_URL_RE.match(url)
    if not m:
        raise ValueError(
            f"Invalid GitHub PR URL: {url!r}. "
            "Expected format: https://github.com/<owner>/<repo>/pull/<number>"
        )
    return m.group("owner"), m.group("repo"), int(m.group("number"))


# ---------------------------------------------------------------------------
# GitHub API client
# ---------------------------------------------------------------------------


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error response."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_token() -> str | None:
    """Return the GitHub token from environment, or None for unauthenticated access."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _api_request(path: str, *, accept: str = "application/vnd.github+json") -> object:
    """
    Make an authenticated GET request to the GitHub API.

    Returns the parsed JSON body.

    Raises
    ------
    GitHubAPIError
        On HTTP 4xx/5xx responses with a clear message.
    """
    url = f"{_GITHUB_API_BASE}{path}"
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "regression-radar/0.1",
    }
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.warning(
            "GITHUB_TOKEN not set — using unauthenticated API (60 req/hour limit). "
            "Private repositories will not be accessible."
        )

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            detail = json.loads(body).get("message", body)
        except Exception:
            detail = body[:200]

        if exc.code == 401:
            raise GitHubAPIError(
                "GitHub API authentication failed. "
                "Set GITHUB_TOKEN to a valid personal access token.",
                status_code=401,
            ) from exc
        if exc.code == 403:
            if "rate limit" in detail.lower():
                msg = "GitHub API rate limit exceeded"
            else:
                msg = (
                    "GitHub API access forbidden — repository may be private "
                    "or token lacks repo scope"
                )
            raise GitHubAPIError(msg, status_code=403) from exc
        if exc.code == 404:
            raise GitHubAPIError(
                "Pull request not found. Verify the URL is correct and the "
                f"repository is accessible. (HTTP 404 — {detail})",
                status_code=404,
            ) from exc
        if exc.code == 422:
            raise GitHubAPIError(
                f"GitHub API validation error: {detail}", status_code=422
            ) from exc
        raise GitHubAPIError(
            f"GitHub API error {exc.code}: {detail}", status_code=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAPIError(
            f"Network error reaching GitHub API: {exc.reason}. "
            "Check your internet connection."
        ) from exc
    except TimeoutError as exc:
        raise GitHubAPIError(
            "GitHub API request timed out after 30 s. Try again later."
        ) from exc


def _diff_request(path: str) -> str:
    """Fetch a unified diff from GitHub (uses application/vnd.github.diff accept header)."""
    url = f"{_GITHUB_API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github.diff",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "regression-radar/0.1",
    }
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise GitHubAPIError(
            f"Failed to fetch PR diff (HTTP {exc.code}).", status_code=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAPIError(
            f"Network error fetching PR diff: {exc.reason}"
        ) from exc


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def _fetch_pr_metadata(owner: str, repo: str, number: int) -> GitHubPR:
    """Fetch PR metadata from /repos/{owner}/{repo}/pulls/{number}."""
    data = _api_request(f"/repos/{owner}/{repo}/pulls/{number}")
    assert isinstance(data, dict)

    # Author email: GitHub doesn't expose it in PR payload, but we can use login
    # as the identifier for ownership scoring (we store it in author_email field)
    author = data.get("user") or {}
    author_login = author.get("login") or ""

    base = data.get("base") or {}
    head = data.get("head") or {}

    return GitHubPR(
        owner=owner,
        repo=repo,
        number=number,
        title=data.get("title") or "",
        state=data.get("state") or "open",
        base_ref=base.get("ref") or "main",
        head_ref=head.get("ref") or "HEAD",
        head_sha=(head.get("sha") or "")[:7],
        author_login=author_login,
        author_email=f"{author_login}@users.noreply.github.com" if author_login else "",
        additions=data.get("additions") or 0,
        deletions=data.get("deletions") or 0,
        changed_files=data.get("changed_files") or 0,
        is_draft=bool(data.get("draft", False)),
        html_url=data.get("html_url") or "",
    )


def _fetch_pr_diff(owner: str, repo: str, number: int) -> str:
    """Fetch the unified diff for a PR."""
    return _diff_request(f"/repos/{owner}/{repo}/pulls/{number}")


def _fetch_pr_changed_files(owner: str, repo: str, number: int) -> list[str]:
    """Return the list of changed file paths in the PR (up to 300 files)."""
    # GitHub paginates at 30 per page; 300 files = 10 pages max (practical limit)
    paths: list[str] = []
    page = 1
    while page <= 10:
        data = _api_request(
            f"/repos/{owner}/{repo}/pulls/{number}/files?per_page=100&page={page}"
        )
        assert isinstance(data, list)
        if not data:
            break
        for f in data:
            assert isinstance(f, dict)
            filename = f.get("filename", "")
            if filename:
                paths.append(filename)
        if len(data) < 100:
            break
        page += 1
    return paths


def _fetch_repo_commits(owner: str, repo: str, base_ref: str) -> list[CommitInfo]:
    """
    Fetch recent commit history for the base branch to build hotspot/cochange signals.

    Uses /repos/{owner}/{repo}/commits — returns up to _MAX_COMMITS commits,
    each with changed files from /commits/{sha}.
    """
    # Step 1: Get list of recent commit SHAs
    data = _api_request(
        f"/repos/{owner}/{repo}/commits?sha={base_ref}&per_page=100"
    )
    assert isinstance(data, list)
    # Also fetch a second page if available (up to 200 commits for history quality)
    if len(data) == 100:
        page2 = _api_request(
            f"/repos/{owner}/{repo}/commits?sha={base_ref}&per_page=100&page=2"
        )
        if isinstance(page2, list):
            data = data + page2  # type: ignore[operator]

    bugfix_re = re.compile(
        r"^fix|\\bfix\\b|\\bbug\\b|\\bdefect\\b|^revert|\\brevert\\b|\\bhotfix\\b|\\bpatch\\b|\\bregression\\b",
        re.IGNORECASE,
    )

    commits: list[CommitInfo] = []
    for item in data[:_MAX_COMMITS]:
        assert isinstance(item, dict)
        sha = item.get("sha", "")
        c = item.get("commit") or {}
        author_data = c.get("author") or {}
        gh_author = item.get("author") or {}

        subject = c.get("message", "").split("\n")[0].strip()
        body = "\n".join(c.get("message", "").split("\n")[1:]).strip()
        date_str = author_data.get("date", "")
        try:
            timestamp = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now(tz=UTC)

        author_name = author_data.get("name", gh_author.get("login", "unknown"))
        # Use GitHub login as email fallback for ownership scoring
        login = gh_author.get("login", "")
        author_email = author_data.get("email") or (
            f"{login}@users.noreply.github.com" if login else "unknown@unknown"
        )

        is_bugfix = bool(bugfix_re.search(subject))

        # Note: we do NOT fetch individual commit files here to avoid
        # N+1 API calls that would exhaust rate limits quickly.
        # The changed_files list will be empty for history commits — this means
        # cochange scoring works on PR-file data only (reduced signal).
        # We fetch file lists for the first 30 commits to get cochange signal.
        commits.append(
            CommitInfo(
                sha=sha,
                short_sha=sha[:7],
                author_name=author_name,
                author_email=author_email,
                timestamp=timestamp,
                subject=subject,
                body=body,
                is_merge=False,
                changed_files=[],  # populated selectively below
                is_bugfix_candidate=is_bugfix,
            )
        )

    return commits


def _enrich_commits_with_files(
    owner: str,
    repo: str,
    commits: list[CommitInfo],
    *,
    max_enriched: int = 50,
) -> list[CommitInfo]:
    """
    Fetch changed-file lists for the most recent commits to enable cochange scoring.

    Fetches at most *max_enriched* commits to avoid exhausting the rate limit.
    Returns a new list with enriched CommitInfo objects where possible.
    """
    enriched: list[CommitInfo] = []
    for i, commit in enumerate(commits):
        if i >= max_enriched:
            enriched.append(commit)
            continue
        try:
            detail = _api_request(f"/repos/{owner}/{repo}/commits/{commit.sha}")
            assert isinstance(detail, dict)
            files = detail.get("files") or []
            changed = [
                f.get("filename", "")
                for f in files
                if isinstance(f, dict) and f.get("filename")
            ]
            # CommitInfo is frozen — replace with enriched version
            enriched.append(
                CommitInfo(
                    sha=commit.sha,
                    short_sha=commit.short_sha,
                    author_name=commit.author_name,
                    author_email=commit.author_email,
                    timestamp=commit.timestamp,
                    subject=commit.subject,
                    body=commit.body,
                    is_merge=commit.is_merge,
                    changed_files=changed,
                    is_bugfix_candidate=commit.is_bugfix_candidate,
                )
            )
        except GitHubAPIError as exc:
            logger.warning("Could not fetch files for commit %s: %s", commit.short_sha, exc)
            enriched.append(commit)
    return enriched


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_github_pr_data(
    owner: str,
    repo: str,
    number: int,
    *,
    enrich_commits: bool = True,
) -> GitHubAnalysisData:
    """
    Fetch all data required to run the four Regression Radar analysis engines
    for the given GitHub pull request.

    Parameters
    ----------
    owner, repo, number:
        GitHub repository owner, repo name, and PR number.
    enrich_commits:
        If True, fetch individual commit file lists for the first 50 commits
        to enable cochange signal. Set False in tests to avoid extra API calls.

    Returns
    -------
    GitHubAnalysisData
        Contains the GitHubPR metadata, a RawDiff, a list of CommitInfo objects
        (history of the base branch), and inferred DataQuality.
    """
    logger.info("Fetching GitHub PR %s/%s#%d", owner, repo, number)

    # 1. PR metadata
    pr = _fetch_pr_metadata(owner, repo, number)

    # 2. Diff text
    diff_text = _fetch_pr_diff(owner, repo, number)

    # 3. Changed file paths (more reliable than parsing the diff)
    changed_paths = _fetch_pr_changed_files(owner, repo, number)

    raw_diff = RawDiff(
        base_ref=pr.base_ref,
        head_ref=pr.head_ref,
        text=diff_text,
        changed_paths=changed_paths,
    )

    # 4. Repo commit history (base branch) for hotspot / cochange / ownership
    commits = _fetch_repo_commits(owner, repo, pr.base_ref)

    if enrich_commits and commits:
        commits = _enrich_commits_with_files(owner, repo, commits)

    # 5. Data quality based on how much history we could fetch
    if len(commits) >= 30:
        quality = DataQuality.HIGH
    elif len(commits) >= 10:
        quality = DataQuality.MEDIUM
    else:
        quality = DataQuality.LOW

    logger.info(
        "GitHub PR data fetched: %d changed files, %d history commits, quality=%s",
        len(changed_paths),
        len(commits),
        quality,
    )
    return GitHubAnalysisData(pr=pr, diff=raw_diff, commits=commits, data_quality=quality)
