"""
cache.py — Thread-safe in-memory caching for Git operations and GitHub API calls.

Provides TTL-based and content-addressed LRU caching for:
1. Git commit history (keyed by repo path + HEAD commit SHA + filters).
2. Git diffs between specific commit SHAs (working tree diffs are never cached).
3. GitHub Pull Request data (keyed by owner + repo + PR number + head_sha).

Design invariants:
- Zero external dependencies (uses standard library threading, collections.OrderedDict, time).
- Thread-safe for concurrent FastAPI requests using re-entrant locks (RLock).
- Content-addressed: commit SHAs guarantee immutable inputs; new commits automatically invalidate.
- Working tree diffs are never cached to avoid stale results during active editing.
- Configurable TTL and max size with LRU eviction.
- Cache bypass option supported for debugging and test isolation.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from regression_radar.git_history import (
    CommitInfo,
    DataQuality,
    RawDiff,
    _git,
    get_commits,
    get_diff,
    validate_repo,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic Thread-safe TTL + LRU Cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float  # monotonic timestamp


class TTLCache(Generic[T]):
    """Thread-safe In-Memory Cache with LRU eviction and TTL expiration."""

    def __init__(self, max_size: int = 256, default_ttl: float = 300.0) -> None:
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, _CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> T | None:
        """Retrieve a value if present and not expired; moves entry to MRU end."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.misses += 1
                return None

            now = time.monotonic()
            if now > entry.expires_at:
                # Expired
                del self._cache[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self.hits += 1
            return entry.value

    def set(self, key: str, value: T, ttl: float | None = None) -> None:
        """Store a value with TTL; evicts oldest item if capacity is exceeded."""
        effective_ttl = self.default_ttl if ttl is None else ttl
        expires_at = time.monotonic() + effective_ttl

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = _CacheEntry(value=value, expires_at=expires_at)
                return

            # Check capacity
            while len(self._cache) >= self.max_size and self._cache:
                self._cache.popitem(last=False)
                self.evictions += 1

            self._cache[key] = _CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key from the cache. Returns True if removed."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries and reset counters."""
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    def stats(self) -> dict[str, int]:
        """Return diagnostic statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
            }


# ---------------------------------------------------------------------------
# Global Cache Instances
# ---------------------------------------------------------------------------

# Git commits cache: 10 minute default TTL
git_commits_cache: TTLCache[list[CommitInfo]] = TTLCache(max_size=128, default_ttl=600.0)

# Git diff cache: 10 minute default TTL
git_diff_cache: TTLCache[RawDiff] = TTLCache(max_size=128, default_ttl=600.0)

# GitHub PR analysis data cache: 5 minute default TTL
github_pr_cache: TTLCache[Any] = TTLCache(max_size=128, default_ttl=300.0)


# ---------------------------------------------------------------------------
# Helper: Resolve Git commit SHAs
# ---------------------------------------------------------------------------


def resolve_ref_sha(repo_path: Path, ref: str) -> str | None:
    """Resolve a Git reference (e.g. branch, tag, HEAD) to a full commit SHA."""
    res = _git(["rev-parse", ref], cwd=repo_path, check=False)
    if res.returncode == 0:
        sha = res.stdout.strip()
        if len(sha) >= 7:
            return sha
    return None


# ---------------------------------------------------------------------------
# Cached Git History
# ---------------------------------------------------------------------------


def cached_get_commits(
    repo_path: Path,
    *,
    max_commits: int = 2000,
    base_ref: str | None = None,
    bugfix_patterns: list[str] | None = None,
    exclude_merges: bool = True,
    bypass_cache: bool = False,
    ttl: float | None = None,
) -> list[CommitInfo]:
    """
    Return commit history, using in-memory caching keyed by repo path + HEAD SHA.

    If new commits are added to the repo, HEAD SHA changes, automatically
    causing a cache miss and extracting fresh history without stale results.
    """
    if bypass_cache:
        return get_commits(
            repo_path,
            max_commits=max_commits,
            base_ref=base_ref,
            bugfix_patterns=bugfix_patterns,
            exclude_merges=exclude_merges,
        )

    try:
        validated = validate_repo(repo_path)
    except Exception:
        # Fallback to direct call on validation failure
        return get_commits(
            repo_path,
            max_commits=max_commits,
            base_ref=base_ref,
            bugfix_patterns=bugfix_patterns,
            exclude_merges=exclude_merges,
        )

    head_sha = resolve_ref_sha(validated, "HEAD")
    if not head_sha:
        # No commits or unborn branch; fallback
        return get_commits(
            validated,
            max_commits=max_commits,
            base_ref=base_ref,
            bugfix_patterns=bugfix_patterns,
            exclude_merges=exclude_merges,
        )

    base_sha = resolve_ref_sha(validated, base_ref) if base_ref else ""

    cache_key = (
        f"commits:{validated.resolve()}:{head_sha}:{base_sha}:{max_commits}:{exclude_merges}"
    )

    cached = git_commits_cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for git commits: %s", cache_key)
        return cached

    logger.debug("Cache miss for git commits: %s", cache_key)
    commits = get_commits(
        validated,
        max_commits=max_commits,
        base_ref=base_ref,
        bugfix_patterns=bugfix_patterns,
        exclude_merges=exclude_merges,
    )
    git_commits_cache.set(cache_key, commits, ttl=ttl)
    return commits


# ---------------------------------------------------------------------------
# Cached Git Diff
# ---------------------------------------------------------------------------


def cached_get_diff(
    repo_path: Path,
    *,
    base_ref: str = "HEAD",
    head_ref: str | None = None,
    bypass_cache: bool = False,
    ttl: float | None = None,
) -> RawDiff:
    """
    Return unified diff between base_ref and head_ref with in-memory caching.

    Safety:
    - If head_ref is None (diffing working tree changes), cache is ALWAYS bypassed.
    - If head_ref and base_ref resolve to commit SHAs, the diff is immutable and safely cached.
    """
    # Working tree diffs can change at any millisecond without a commit SHA — never cache them
    if head_ref is None or bypass_cache:
        return get_diff(repo_path, base_ref=base_ref, head_ref=head_ref)

    try:
        validated = validate_repo(repo_path)
    except Exception:
        return get_diff(repo_path, base_ref=base_ref, head_ref=head_ref)

    base_sha = resolve_ref_sha(validated, base_ref)
    head_sha = resolve_ref_sha(validated, head_ref)

    # If refs cannot be resolved to commit SHAs, do not cache
    if not base_sha or not head_sha:
        return get_diff(validated, base_ref=base_ref, head_ref=head_ref)

    cache_key = f"diff:{validated.resolve()}:{base_sha}:{head_sha}"

    cached = git_diff_cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for git diff: %s", cache_key)
        return cached

    logger.debug("Cache miss for git diff: %s", cache_key)
    diff = get_diff(validated, base_ref=base_ref, head_ref=head_ref)
    git_diff_cache.set(cache_key, diff, ttl=ttl)
    return diff


# ---------------------------------------------------------------------------
# Cached GitHub PR Data
# ---------------------------------------------------------------------------


def cached_fetch_github_pr_data(
    owner: str,
    repo: str,
    number: int,
    *,
    enrich_commits: bool = True,
    bypass_cache: bool = False,
    ttl: float | None = None,
) -> Any:
    """
    Fetch GitHub PR data, caching the result by (owner, repo, pr_number, head_sha).

    Fetches PR metadata first (1 lightweight API request) to check the current head_sha.
    If head_sha matches the cached entry, the entire diff, changed files list, and
    commit history are returned immediately from cache, saving up to ~50 API round-trips.
    """
    from regression_radar.github_service import (
        GitHubAnalysisData,
        _fetch_pr_changed_files,
        _fetch_pr_diff,
        _fetch_pr_metadata,
        _fetch_repo_commits,
    )

    if bypass_cache:
        from regression_radar.github_service import fetch_github_pr_data

        return fetch_github_pr_data(owner, repo, number, enrich_commits=enrich_commits)

    # 1. Fetch metadata (cheap, 1 API call) to get the authoritative head_sha
    pr = _fetch_pr_metadata(owner, repo, number)
    cache_key = f"gh_pr:{owner.lower()}:{repo.lower()}:{number}:{pr.head_sha}"

    cached = github_pr_cache.get(cache_key)
    if cached is not None:
        logger.info("Cache hit for GitHub PR %s/%s#%d at SHA %s", owner, repo, number, pr.head_sha)
        return cached

    logger.info("Cache miss for GitHub PR %s/%s#%d at SHA %s", owner, repo, number, pr.head_sha)

    # 2. Fetch full PR data
    diff_text = _fetch_pr_diff(owner, repo, number)
    changed_paths = _fetch_pr_changed_files(owner, repo, number)
    raw_diff = RawDiff(
        base_ref=pr.base_ref,
        head_ref=pr.head_ref,
        text=diff_text,
        changed_paths=changed_paths,
    )
    commits = _fetch_repo_commits(owner, repo, pr.base_ref)

    if enrich_commits and commits:
        from regression_radar.github_service import _enrich_commits_with_files

        commits = _enrich_commits_with_files(owner, repo, commits)

    if len(commits) >= 30:
        quality = DataQuality.HIGH
    elif len(commits) >= 10:
        quality = DataQuality.MEDIUM
    else:
        quality = DataQuality.LOW

    data = GitHubAnalysisData(pr=pr, diff=raw_diff, commits=commits, data_quality=quality)
    github_pr_cache.set(cache_key, data, ttl=ttl)
    return data


# ---------------------------------------------------------------------------
# Management & Diagnostics
# ---------------------------------------------------------------------------


def clear_all_caches() -> None:
    """Clear all in-memory caches across Git and GitHub services."""
    git_commits_cache.clear()
    git_diff_cache.clear()
    github_pr_cache.clear()


def get_all_cache_stats() -> dict[str, dict[str, int]]:
    """Return cache statistics for all registered caches."""
    return {
        "git_commits": git_commits_cache.stats(),
        "git_diff": git_diff_cache.stats(),
        "github_pr": github_pr_cache.stats(),
    }
