"""
test_cache.py — Comprehensive tests for in-memory caching and cache invalidation.

Validates:
1. TTLCache unit mechanics (get, set, LRU eviction, TTL expiration, invalidation, concurrency).
2. Content-addressed Git history caching and invalidation on new commits.
3. Working tree diff non-caching safety and commit-to-commit diff caching.
4. GitHub PR metadata and diff caching with head_sha invalidation.
5. Cache isolation across different repositories and pull requests.
6. Cache stats and clear API endpoints.
"""

from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock, patch

import pytest

from regression_radar.api import (
    AnalyzeRequest,
    analyze_endpoint,
    cache_clear_endpoint,
    cache_stats_endpoint,
)
from regression_radar.cache import (
    TTLCache,
    cached_fetch_github_pr_data,
    cached_get_commits,
    cached_get_diff,
    clear_all_caches,
    git_commits_cache,
    git_diff_cache,
    github_pr_cache,
)
from regression_radar.github_service import GitHubPR
from tests.conftest import GitRepoFixture


class TestTTLCache:
    def setup_method(self) -> None:
        clear_all_caches()

    def test_get_set_hit_miss(self) -> None:
        cache: TTLCache[str] = TTLCache(max_size=10, default_ttl=60.0)
        assert cache.get("missing") is None
        assert cache.misses == 1
        assert cache.hits == 0

        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"
        assert cache.hits == 1
        assert cache.misses == 1

    def test_lru_eviction(self) -> None:
        cache: TTLCache[int] = TTLCache(max_size=3, default_ttl=60.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)

        # Access 'a' so 'b' becomes the oldest (LRU)
        assert cache.get("a") == 1

        # Insert 'd' -> 'b' should be evicted
        cache.set("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4
        assert cache.evictions == 1

    def test_expiration(self) -> None:
        cache: TTLCache[str] = TTLCache(max_size=10, default_ttl=0.05)
        cache.set("temp", "val")
        assert cache.get("temp") == "val"

        time.sleep(0.06)
        assert cache.get("temp") is None
        assert cache.stats()["size"] == 0

    def test_invalidate_and_clear(self) -> None:
        cache: TTLCache[str] = TTLCache(max_size=10, default_ttl=60.0)
        cache.set("k1", "v1")
        cache.set("k2", "v2")

        assert cache.invalidate("k1") is True
        assert cache.invalidate("nonexistent") is False
        assert cache.get("k1") is None
        assert cache.get("k2") == "v2"

        cache.clear()
        assert cache.get("k2") is None
        assert cache.hits == 0
        assert cache.misses == 1
        assert cache.evictions == 0
        assert cache.stats()["size"] == 0

    def test_concurrent_access(self) -> None:
        cache: TTLCache[int] = TTLCache(max_size=50, default_ttl=60.0)

        def worker(w_id: int) -> None:
            for i in range(50):
                key = f"key_{w_id}_{i % 10}"
                cache.set(key, i)
                val = cache.get(key)
                assert val is not None
                if i % 15 == 0:
                    cache.invalidate(key)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(8)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        stats = cache.stats()
        assert stats["size"] <= 50
        assert stats["hits"] > 0


class TestCachedGitOperations:
    def setup_method(self) -> None:
        clear_all_caches()

    def test_cached_get_commits_hit_and_invalidate_on_new_commit(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        repo_path = git_repo_with_history.path

        # 1. First fetch -> cache miss
        commits1 = cached_get_commits(repo_path)
        assert len(commits1) > 0
        stats1 = git_commits_cache.stats()
        assert stats1["misses"] == 1
        assert stats1["hits"] == 0

        # 2. Second fetch -> cache hit
        commits2 = cached_get_commits(repo_path)
        assert len(commits2) == len(commits1)
        stats2 = git_commits_cache.stats()
        assert stats2["hits"] == 1

        # 3. Add a new commit -> HEAD SHA changes -> cache miss with fresh data
        git_repo_with_history.write("new_file.py", "x = 100\n")
        git_repo_with_history.commit("feat: brand new commit")

        commits3 = cached_get_commits(repo_path)
        assert len(commits3) == len(commits1) + 1
        assert commits3[0].subject == "feat: brand new commit"
        stats3 = git_commits_cache.stats()
        assert stats3["misses"] == 2  # New commit caused cache miss

    def test_cached_get_commits_bypass(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        repo_path = git_repo_with_history.path

        # Populate cache
        cached_get_commits(repo_path)
        assert git_commits_cache.stats()["hits"] == 0

        # Bypass cache
        commits = cached_get_commits(repo_path, bypass_cache=True)
        assert len(commits) > 0
        assert git_commits_cache.stats()["hits"] == 0

    def test_cached_get_commits_repo_isolation(
        self, git_repo_with_history: GitRepoFixture, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        repo1_path = git_repo_with_history.path
        dir2 = tmp_path_factory.mktemp("second_repo")
        repo2 = GitRepoFixture(dir2)
        repo2.write("hello.py", "print('hello')\n")
        repo2.commit("init second repo")

        c1 = cached_get_commits(repo1_path)
        c2 = cached_get_commits(repo2.path)

        assert len(c1) != len(c2)
        assert c2[0].subject == "init second repo"
        assert git_commits_cache.stats()["size"] == 2

    def test_cached_get_diff_commit_range(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        repo_path = git_repo_with_history.path
        git_repo_with_history.branch("feature/diff-cache-test", checkout=True)
        git_repo_with_history.write("src/service.py", "def service(): pass\n")
        git_repo_with_history.commit("feat: add service")

        # First diff call -> cache miss
        d1 = cached_get_diff(repo_path, base_ref="main", head_ref="HEAD")
        assert "src/service.py" in d1.changed_paths
        assert git_diff_cache.stats()["misses"] == 1
        assert git_diff_cache.stats()["hits"] == 0

        # Second diff call -> cache hit
        d2 = cached_get_diff(repo_path, base_ref="main", head_ref="HEAD")
        assert d2.text == d1.text
        assert git_diff_cache.stats()["hits"] == 1

    def test_cached_get_diff_working_tree_never_cached(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        repo_path = git_repo_with_history.path

        # When head_ref is None, diffing working tree
        git_repo_with_history.write("src/app.py", "x = 999\n")
        d1 = cached_get_diff(repo_path, base_ref="HEAD", head_ref=None)
        assert "src/app.py" in d1.changed_paths
        # Working tree diffs should NOT be stored in cache
        assert git_diff_cache.stats()["size"] == 0

        # Change file again in working tree
        git_repo_with_history.write("src/app.py", "x = 1000\n")
        d2 = cached_get_diff(repo_path, base_ref="HEAD", head_ref=None)
        assert "1000" in d2.text
        assert git_diff_cache.stats()["size"] == 0


class TestCachedGitHubPR:
    def setup_method(self) -> None:
        clear_all_caches()

    @patch(
        "regression_radar.github_service._enrich_commits_with_files",
        side_effect=lambda o, r, c: c,
    )
    @patch("regression_radar.github_service._fetch_repo_commits", return_value=[])
    @patch("regression_radar.github_service._fetch_pr_changed_files", return_value=["src/main.py"])
    @patch(
        "regression_radar.github_service._fetch_pr_diff",
        return_value="diff --git a/src/main.py b/src/main.py",
    )
    @patch("regression_radar.github_service._fetch_pr_metadata")
    def test_cached_fetch_pr_data_hit_and_head_sha_invalidation(
        self,
        mock_meta: MagicMock,
        mock_diff: MagicMock,
        mock_files: MagicMock,
        mock_commits: MagicMock,
        mock_enrich: MagicMock,
    ) -> None:
        mock_meta.return_value = GitHubPR(
            owner="octocat",
            repo="hello-world",
            number=42,
            title="Update main",
            state="open",
            base_ref="main",
            head_ref="feature",
            head_sha="head_sha_aaa",
            author_login="octocat",
            author_email="",
            additions=10,
            deletions=2,
            changed_files=1,
            is_draft=False,
            html_url="https://github.com/octocat/hello-world/pull/42",
        )

        # 1. First fetch -> cache miss -> full fetch
        data1 = cached_fetch_github_pr_data("octocat", "hello-world", 42)
        assert data1.pr.head_sha == "head_sha_aaa"
        assert mock_diff.call_count == 1
        assert github_pr_cache.stats()["misses"] == 1
        assert github_pr_cache.stats()["hits"] == 0

        # 2. Second fetch with identical head_sha -> cache hit!
        data2 = cached_fetch_github_pr_data("octocat", "hello-world", 42)
        assert data2.pr.head_sha == "head_sha_aaa"
        # Only metadata was fetched to verify head_sha; diff was NOT fetched again
        assert mock_diff.call_count == 1
        assert mock_meta.call_count == 2
        assert github_pr_cache.stats()["hits"] == 1

        # 3. PR author pushes new commit to PR branch -> head_sha changes
        mock_meta.return_value = GitHubPR(
            owner="octocat",
            repo="hello-world",
            number=42,
            title="Update main",
            state="open",
            base_ref="main",
            head_ref="feature",
            head_sha="head_sha_bbb",  # New commit SHA
            author_login="octocat",
            author_email="",
            additions=15,
            deletions=2,
            changed_files=1,
            is_draft=False,
            html_url="https://github.com/octocat/hello-world/pull/42",
        )

        data3 = cached_fetch_github_pr_data("octocat", "hello-world", 42)
        assert data3.pr.head_sha == "head_sha_bbb"
        assert mock_diff.call_count == 2  # Re-fetched fresh diff!
        assert github_pr_cache.stats()["misses"] == 2

    @patch("regression_radar.github_service.fetch_github_pr_data")
    def test_cached_fetch_pr_data_bypass(self, mock_direct_fetch: MagicMock) -> None:
        mock_direct_fetch.return_value = MagicMock()
        cached_fetch_github_pr_data("owner", "repo", 99, bypass_cache=True)
        assert mock_direct_fetch.call_count == 1
        assert github_pr_cache.stats()["hits"] == 0
        assert github_pr_cache.stats()["misses"] == 0


class TestCacheEndpoints:
    def setup_method(self) -> None:
        clear_all_caches()

    def test_cache_stats_and_clear_endpoints(self) -> None:
        stats_resp = cache_stats_endpoint()
        assert isinstance(stats_resp, dict)
        assert "git_commits" in stats_resp
        assert "git_diff" in stats_resp
        assert "github_pr" in stats_resp

        # Put an item into cache
        git_commits_cache.set("dummy", [])
        assert git_commits_cache.stats()["size"] == 1

        clear_resp = cache_clear_endpoint()
        assert clear_resp["status"] == "cleared"
        assert git_commits_cache.stats()["size"] == 0

    def test_api_analyze_with_bypass_cache(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        git_repo_with_history.branch("feature/api-cache-test", checkout=True)
        git_repo_with_history.write("src/app.py", "def main(): return 'api test'\n")
        git_repo_with_history.commit("feat: update app for api test")

        req = AnalyzeRequest(
            repo_path=str(git_repo_with_history.path),
            base_ref="main",
            head_ref="HEAD",
            bypass_cache=True,
        )
        res = analyze_endpoint(req)
        assert res.total_files_changed == 1
        assert "historical_hotspot" in res.signals
