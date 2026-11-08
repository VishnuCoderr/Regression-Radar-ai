"""
api.py — FastAPI backend service for Regression Radar.

Provides REST endpoints for triggering PR risk analysis, webhook consumption,
and retrieving structured analysis results.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from regression_radar import __version__
from regression_radar.cochange import calculate_cochange_signal
from regression_radar.diff_parser import parse_diff
from regression_radar.git_history import (
    CommitInfo,
    DataQuality,
    get_commits,
    get_diff,
    get_repo_stats,
    validate_repo,
)
from regression_radar.github_service import (
    GitHubAPIError,
    fetch_github_pr_data,
    parse_pr_url,
)
from regression_radar.hotspot import calculate_hotspot_signal
from regression_radar.llm_explain import generate_ai_explanation
from regression_radar.models import AnalysisResult
from regression_radar.ownership import calculate_ownership_signal
from regression_radar.recommendations import build_recommendations
from regression_radar.report import format_markdown_report
from regression_radar.scoring import (
    build_analysis_result,
    compute_risk_score,
    load_scoring_config,
)
from regression_radar.test_gap import calculate_test_gap_signal

app = FastAPI(
    title="Regression Radar API",
    description="Backend service for Pull Request Risk Analysis",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(description="Local repository filesystem path")
    base_ref: str = Field(default="main", description="Base branch or ref")
    head_ref: str = Field(default="HEAD", description="PR head branch or ref")
    pr_author_email: str | None = Field(default=None, description="PR author email")
    use_ai: bool = Field(default=False, description="Enrich recommendations with AI")


class GitHubPRRequest(BaseModel):
    pr_url: str = Field(description="Full GitHub PR URL, e.g. https://github.com/owner/repo/pull/123")
    use_ai: bool = Field(default=False, description="Enrich recommendations with AI")


class HealthResponse(BaseModel):
    status: str
    version: str


# ---------------------------------------------------------------------------
# Shared health / config endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Service health and version check."""
    return HealthResponse(status="healthy", version=__version__)


@app.get("/api/v1/config")
def get_config() -> dict:
    """Return default scoring weights and category thresholds."""
    return load_scoring_config()


# ---------------------------------------------------------------------------
# Core analysis engine (shared by both endpoints)
# ---------------------------------------------------------------------------


def _run_analysis_from_data(
    *,
    changed_files: list[str],
    history_commits: list[CommitInfo],
    pr_author_email: str | None,
    data_quality: DataQuality,
    base_ref: str,
    head_ref: str,
    total_files_changed: int,
    additions: int,
    deletions: int,
    use_ai: bool = False,
    renames: dict[str, str] | None = None,
    deleted_files: list[str] | None = None,
) -> AnalysisResult:
    """
    Run all four analysis engines and return a structured AnalysisResult.

    This is the single internal entry point for scoring logic, shared by
    the local-repo endpoint and the GitHub PR endpoint.
    """
    hotspot_signal = calculate_hotspot_signal(
        changed_files, history_commits, data_quality=data_quality, renames=renames
    )
    cochange_signal = calculate_cochange_signal(
        changed_files, history_commits, data_quality=data_quality, renames=renames
    )
    test_gap_signal = calculate_test_gap_signal(
        changed_files,
        history_commits,
        data_quality=data_quality,
        renames=renames,
        deleted_files=deleted_files,
    )
    ownership_signal = calculate_ownership_signal(
        changed_files,
        history_commits,
        pr_author_email=pr_author_email,
        data_quality=data_quality,
        renames=renames,
    )

    signals = {
        "historical_hotspot": hotspot_signal,
        "cochange_anomaly": cochange_signal,
        "test_gap": test_gap_signal,
        "ownership": ownership_signal,
    }

    cfg = load_scoring_config()
    score, category, effective_weights = compute_risk_score(
        signals, weights=cfg["weights"], thresholds=cfg["thresholds"]
    )
    actions = build_recommendations(signals, score, category)

    result = build_analysis_result(
        signals=signals,
        base_ref=base_ref,
        head_ref=head_ref,
        total_files_changed=total_files_changed,
        additions=additions,
        deletions=deletions,
        data_quality=data_quality,
        custom_weights=effective_weights,
        custom_thresholds=cfg["thresholds"],
        recommended_actions=actions,
    )

    if use_ai:
        enhanced_actions = generate_ai_explanation(result)
        result.recommended_actions = enhanced_actions

    return result


# ---------------------------------------------------------------------------
# Local repository endpoint (unchanged behaviour)
# ---------------------------------------------------------------------------


def _run_analysis(req: AnalyzeRequest) -> AnalysisResult:
    path = Path(req.repo_path)
    try:
        validated_path = validate_repo(path)
        stats = get_repo_stats(validated_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if stats.total_commits == 0:
        raise HTTPException(
            status_code=400,
            detail="Repository is empty (0 commits). Cannot analyze diff without commits.",
        )

    try:
        raw_diff = get_diff(validated_path, base_ref=req.base_ref, head_ref=req.head_ref)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"Git diff failed: {exc}") from exc

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    history_commits = get_commits(validated_path, max_commits=2000, exclude_merges=True)
    renames = {f.path: f.old_path for f in parsed_diff.files if f.old_path and f.old_path != f.path}
    deleted_files = [f.path for f in parsed_diff.files if f.change_type.value == "deleted"]

    return _run_analysis_from_data(
        changed_files=changed_files,
        history_commits=history_commits,
        pr_author_email=req.pr_author_email,
        data_quality=stats.data_quality,
        base_ref=req.base_ref,
        head_ref=req.head_ref,
        total_files_changed=len(parsed_diff.files),
        additions=parsed_diff.total_additions,
        deletions=parsed_diff.total_deletions,
        use_ai=req.use_ai,
        renames=renames,
        deleted_files=deleted_files,
    )


@app.post("/api/v1/analyze", response_model=AnalysisResult)
def analyze_endpoint(req: AnalyzeRequest) -> AnalysisResult:
    """Analyze a local Git repository PR and return complete structured risk assessment."""
    return _run_analysis(req)


@app.post("/api/v1/analyze/markdown")
def analyze_markdown_endpoint(req: AnalyzeRequest) -> dict[str, str]:
    """Analyze a pull request and return a pre-formatted GitHub PR comment."""
    result = _run_analysis(req)
    return {
        "markdown": format_markdown_report(result),
        "overall_score": str(result.overall_score),
        "category": result.risk_category.value,
    }


# ---------------------------------------------------------------------------
# GitHub PR endpoint (new)
# ---------------------------------------------------------------------------


@app.post("/api/v1/analyze/github-pr", response_model=AnalysisResult)
def analyze_github_pr_endpoint(req: GitHubPRRequest) -> AnalysisResult:
    """
    Fetch a GitHub Pull Request by URL and run the full four-signal risk analysis.

    The GitHub token is read from the GITHUB_TOKEN environment variable on the
    server — it is never sent to or from the frontend.

    Public repositories work without a token (rate limit: 60 req/hour).
    Private repositories require a token with the ``repo`` scope.
    """
    # Parse and validate URL first (fast, no network)
    try:
        owner, repo, number = parse_pr_url(req.pr_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Fetch all data from GitHub
    try:
        gh_data = fetch_github_pr_data(owner, repo, number)
    except GitHubAPIError as exc:
        status = exc.status_code or 502
        # Map GitHub 404 → our 404; auth errors → 401/403; others → 502
        if status == 404:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if status in (401, 403):
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=f"GitHub API error: {exc}") from exc

    # Parse the diff
    parsed_diff = parse_diff(gh_data.diff.text)
    # Prefer the file list from the API (more reliable) over parsed diff headers
    changed_files = gh_data.diff.changed_paths or parsed_diff.changed_paths
    renames = {f.path: f.old_path for f in parsed_diff.files if f.old_path and f.old_path != f.path}
    deleted_files = [f.path for f in parsed_diff.files if f.change_type.value == "deleted"]

    return _run_analysis_from_data(
        changed_files=changed_files,
        history_commits=gh_data.commits,
        pr_author_email=gh_data.pr.author_email,
        data_quality=gh_data.data_quality,
        base_ref=gh_data.pr.base_ref,
        head_ref=gh_data.pr.head_ref,
        total_files_changed=gh_data.pr.changed_files or len(parsed_diff.files),
        additions=gh_data.pr.additions,
        deletions=gh_data.pr.deletions,
        use_ai=req.use_ai,
        renames=renames,
        deleted_files=deleted_files,
    )


@app.get("/api/v1/github/token-status")
def github_token_status() -> dict:
    """
    Report whether a GitHub token is configured on the server.
    Returns the token presence only — never the token value itself.
    """
    import os
    has_token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    return {"has_token": has_token}
