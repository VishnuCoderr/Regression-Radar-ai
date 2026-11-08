"""
git_history.py — Extract commit metadata and diffs from a local Git repository.

Design decisions:
- Uses subprocess + git CLI (not pure GitPython) for reliable, stable output.
  See DECISIONS.md D-001.
- Merge commits are excluded from bug-fix signal by default (D-006).
- Shallow clone detection emits DataQuality warnings (D-007).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class DataQuality(StrEnum):
    """Confidence in signal quality given available history."""

    HIGH = "high"  # >= 30 commits; full confidence
    MEDIUM = "medium"  # 10–29 commits; reduced confidence
    LOW = "low"  # < 10 commits or shallow clone


@dataclass(frozen=True)
class CommitInfo:
    """Structured metadata for a single Git commit."""

    sha: str
    short_sha: str
    author_name: str
    author_email: str
    timestamp: datetime
    subject: str  # First line of commit message
    body: str  # Remaining lines (may be empty)
    is_merge: bool  # True if commit has > 1 parent
    changed_files: list[str] = field(default_factory=list)
    is_bugfix_candidate: bool = False


@dataclass(frozen=True)
class RepositoryStats:
    """High-level stats about a Git repository."""

    path: Path
    total_commits: int
    is_shallow: bool
    data_quality: DataQuality
    head_sha: str | None
    default_branch: str | None


# ---------------------------------------------------------------------------
# Repository validation
# ---------------------------------------------------------------------------


def validate_repo(repo_path: Path) -> Path:
    """
    Validate that *repo_path* is a Git repository root.

    Raises
    ------
    ValueError
        If the path does not exist or is not a Git repository.
    """
    repo_path = repo_path.resolve()
    if not repo_path.exists():
        raise ValueError(f"Path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise ValueError(f"Path is not a directory: {repo_path}")

    has_git = (repo_path / ".git").exists()
    is_bare = False
    if not has_git:
        bare_check = _git(["rev-parse", "--is-bare-repository"], cwd=repo_path, check=False)
        if bare_check.returncode == 0 and bare_check.stdout.strip() == "true":
            git_dir = _git(["rev-parse", "--git-dir"], cwd=repo_path, check=False)
            if git_dir.returncode == 0 and git_dir.stdout.strip() == ".":
                is_bare = True

    if not has_git and not is_bare:
        raise ValueError(f"Not a Git repository: {repo_path}")

    result = _git(["rev-parse", "--git-dir"], cwd=repo_path, check=False)
    if result.returncode != 0:
        raise ValueError(f"Not a Git repository: {repo_path}")

    # Resolve to actual worktree root
    root_result = _git(["rev-parse", "--show-toplevel"], cwd=repo_path, check=False)
    if root_result.returncode == 0 and root_result.stdout.strip():
        return Path(root_result.stdout.strip())
    return repo_path


def get_repo_stats(repo_path: Path) -> RepositoryStats:
    """Return high-level statistics about a repository."""
    repo_path = validate_repo(repo_path)

    is_shallow = _is_shallow(repo_path)

    # Count commits reachable from HEAD
    count_result = _git(["rev-list", "--count", "HEAD"], cwd=repo_path, check=False)
    if count_result.returncode != 0:
        # Empty repository — no commits yet
        return RepositoryStats(
            path=repo_path,
            total_commits=0,
            is_shallow=False,
            data_quality=DataQuality.LOW,
            head_sha=None,
            default_branch=_guess_default_branch(repo_path),
        )

    total_commits = int(count_result.stdout.strip())

    head_result = _git(["rev-parse", "HEAD"], cwd=repo_path, check=False)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else None

    if is_shallow or total_commits < 10:
        quality = DataQuality.LOW
    elif total_commits < 30:
        quality = DataQuality.MEDIUM
    else:
        quality = DataQuality.HIGH

    return RepositoryStats(
        path=repo_path,
        total_commits=total_commits,
        is_shallow=is_shallow,
        data_quality=quality,
        head_sha=head_sha,
        default_branch=_guess_default_branch(repo_path),
    )


# ---------------------------------------------------------------------------
# Commit extraction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Commit extraction constants
# ---------------------------------------------------------------------------

_COMMIT_START = "---RR_COMMIT_START---"
_BODY_START = "---RR_BODY_START---"
_BODY_END = "---RR_BODY_END---"

_GIT_LOG_FORMAT = f"{_COMMIT_START}%n%H%n%h%n%an%n%ae%n%aI%n%P%n%s%n{_BODY_START}%n%b%n{_BODY_END}"


def get_commits(
    repo_path: Path,
    *,
    max_commits: int = 2000,
    base_ref: str | None = None,
    bugfix_patterns: list[str] | None = None,
    exclude_merges: bool = True,
) -> list[CommitInfo]:
    """
    Return a list of CommitInfo objects from the repository history.

    Parameters
    ----------
    repo_path:
        Root of the Git repository.
    max_commits:
        Hard cap on commits read (guards against huge histories).
    base_ref:
        If provided, only return commits reachable from HEAD but not from
        *base_ref* (i.e. the range ``base_ref..HEAD``).
    bugfix_patterns:
        List of regex patterns. A commit whose subject line matches any
        pattern (case-insensitive) is marked ``is_bugfix_candidate=True``.
        Defaults to the patterns from ``configs/weights.toml`` if not
        supplied; uses a built-in fallback if that file is not found.
    exclude_merges:
        When True (default), merge commits are skipped (they are still
        analysed for file co-change purposes elsewhere but not counted
        as direct bug-fix activity — see DECISIONS.md D-006).
    """
    repo_path = validate_repo(repo_path)

    if bugfix_patterns is None:
        bugfix_patterns = _default_bugfix_patterns()

    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in bugfix_patterns]

    # Build git log command
    rev_range = f"{base_ref}..HEAD" if base_ref else "HEAD"
    cmd: list[str] = [
        "log",
        f"--format={_GIT_LOG_FORMAT}",
        f"--max-count={max_commits}",
        "--name-only",  # list changed file paths after the record
        rev_range,
    ]

    result = _git(cmd, cwd=repo_path, check=False)
    if result.returncode != 0:
        if "unknown revision" in result.stderr or "bad revision" in result.stderr:
            logger.warning(
                "Reference %r not found in %s; returning empty commit list.",
                base_ref or "HEAD",
                repo_path,
            )
            return []
        logger.error("git log failed: %s", result.stderr)
        raise RuntimeError(f"git log failed: {result.stderr}")

    commits = _parse_log_output(result.stdout, compiled_patterns, exclude_merges)
    logger.info(
        "Extracted %d commits from %s (range: %s)",
        len(commits),
        repo_path,
        rev_range,
    )
    return commits


def _parse_log_output(
    raw: str,
    compiled_patterns: list[re.Pattern[str]],
    exclude_merges: bool,
) -> list[CommitInfo]:
    """Parse raw ``git log --format=... --name-only`` output."""
    commits: list[CommitInfo] = []

    # Split by commit sentinel marker
    chunks = raw.split(_COMMIT_START)

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if _BODY_START not in chunk or _BODY_END not in chunk:
            continue

        header_part, rest = chunk.split(_BODY_START, 1)
        body_part, files_part = rest.split(_BODY_END, 1)

        meta_lines = [line.strip() for line in header_part.splitlines() if line != ""]
        if len(meta_lines) < 6:
            # Need at least sha, short_sha, author_name, author_email, date_iso, and subject
            logger.debug("Skipping malformed commit chunk: %r", chunk[:100])
            continue

        sha = meta_lines[0]
        short_sha = meta_lines[1]
        author_name = meta_lines[2]
        author_email = meta_lines[3]
        date_str = meta_lines[4]
        # In git format: %P is parents (may be empty).
        # If parents was empty, meta_lines has 6 items.
        # If parents was non-empty, meta_lines has 7 items.
        if len(meta_lines) == 6:
            parents_raw = ""
            subject = meta_lines[5]
        else:
            parents_raw = meta_lines[5]
            subject = meta_lines[6]

        parent_shas = parents_raw.split() if parents_raw else []
        is_merge = len(parent_shas) > 1

        if exclude_merges and is_merge:
            continue

        try:
            timestamp = datetime.fromisoformat(date_str)
        except ValueError:
            logger.debug("Could not parse date %r for commit %s", date_str, short_sha)
            timestamp = datetime.now(tz=UTC)

        is_bugfix = any(p.search(subject) for p in compiled_patterns)
        changed_files = [f.strip() for f in files_part.splitlines() if f.strip()]

        commits.append(
            CommitInfo(
                sha=sha,
                short_sha=short_sha,
                author_name=author_name,
                author_email=author_email,
                timestamp=timestamp,
                subject=subject,
                body=body_part.strip(),
                is_merge=is_merge,
                changed_files=changed_files,
                is_bugfix_candidate=is_bugfix,
            )
        )

    return commits


# ---------------------------------------------------------------------------
# Diff extraction (between refs or against working tree)
# ---------------------------------------------------------------------------


@dataclass
class RawDiff:
    """Raw diff text between two Git refs plus the list of changed paths."""

    base_ref: str
    head_ref: str
    text: str  # Full unified diff text
    changed_paths: list[str]  # Paths that changed (source paths for renames)


def get_diff(
    repo_path: Path,
    *,
    base_ref: str = "HEAD",
    head_ref: str | None = None,
) -> RawDiff:
    """
    Return the unified diff between *base_ref* and *head_ref*.

    If *head_ref* is None, diff is against the current working tree (useful
    for local analysis before committing).
    """
    repo_path = validate_repo(repo_path)

    refs: list[str]
    if head_ref is None:
        # Diff staged + unstaged changes against base
        refs = [base_ref]
        display_head = "WORKING_TREE"
    else:
        refs = [base_ref, head_ref]
        display_head = head_ref

    diff_cmd = [
        "diff",
        "--unified=3",
        "--find-renames",
        "--diff-filter=ACDMRT",  # Added, Copied, Deleted, Modified, Renamed, Type-changed
        *refs,
    ]
    diff_result = _git(diff_cmd, cwd=repo_path, check=False)

    if diff_result.returncode not in (0, 1):
        # git diff returns 1 when there are differences (not an error)
        raise RuntimeError(f"git diff failed: {diff_result.stderr}")

    # Get changed file list (more reliable than parsing diff headers)
    name_cmd = [
        "diff",
        "--name-only",
        "--find-renames",
        "--diff-filter=ACDMRT",
        *refs,
    ]
    name_result = _git(name_cmd, cwd=repo_path, check=False)
    changed_paths = [p.strip() for p in name_result.stdout.splitlines() if p.strip()]

    logger.info(
        "Diff %s..%s: %d changed paths",
        base_ref,
        display_head,
        len(changed_paths),
    )

    return RawDiff(
        base_ref=base_ref,
        head_ref=display_head,
        text=diff_result.stdout,
        changed_paths=changed_paths,
    )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _git(
    args: list[str],
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand and return the CompletedProcess."""
    cmd = ["git", *args]
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _is_shallow(repo_path: Path) -> bool:
    """Return True if the repository is a shallow clone."""
    shallow_file = repo_path / ".git" / "shallow"
    if shallow_file.exists() and shallow_file.stat().st_size > 0:
        return True
    # Worktrees and bare repos
    result = _git(["rev-parse", "--git-dir"], cwd=repo_path, check=False)
    if result.returncode == 0:
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = repo_path / git_dir
        alt = git_dir / "shallow"
        if alt.exists() and alt.stat().st_size > 0:
            return True
    return False


def _guess_default_branch(repo_path: Path) -> str | None:
    """Guess the default branch name (main / master / trunk / develop)."""
    for candidate in ("main", "master", "trunk", "develop"):
        result = _git(
            ["rev-parse", "--verify", f"refs/heads/{candidate}"],
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    # Try remote HEAD if present
    result = _git(
        ["symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo_path,
        check=False,
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        if "/" in ref:
            return ref.rsplit("/", 1)[-1]
    return None


def _default_bugfix_patterns() -> list[str]:
    """Return built-in bug-fix commit subject patterns."""
    return [
        r"^fix",
        r"\bfix\b",
        r"\bbug\b",
        r"\bdefect\b",
        r"^revert",
        r"\brevert\b",
        r"\bhotfix\b",
        r"\bpatch\b",
        r"\bregression\b",
    ]
