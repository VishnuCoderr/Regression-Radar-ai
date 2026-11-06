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
    get_commits,
    get_diff,
    get_repo_stats,
    validate_repo,
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


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(description="Local repository filesystem path")
    base_ref: str = Field(default="main", description="Base branch or ref")
    head_ref: str = Field(default="HEAD", description="PR head branch or ref")
    pr_author_email: str | None = Field(default=None, description="PR author email")
    use_ai: bool = Field(default=False, description="Enrich recommendations with AI")


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Service health and version check."""
    return HealthResponse(status="healthy", version=__version__)


@app.get("/api/v1/config")
def get_config() -> dict:
    """Return default scoring weights and category thresholds."""
    return load_scoring_config()


def _run_analysis(req: AnalyzeRequest) -> AnalysisResult:
    path = Path(req.repo_path)
    try:
        validated_path = validate_repo(path)
        stats = get_repo_stats(validated_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        raw_diff = get_diff(validated_path, base_ref=req.base_ref, head_ref=req.head_ref)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"Git diff failed: {exc}") from exc

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    history_commits = get_commits(validated_path, max_commits=2000, exclude_merges=True)

    hotspot_signal = calculate_hotspot_signal(
        changed_files, history_commits, data_quality=stats.data_quality
    )
    cochange_signal = calculate_cochange_signal(
        changed_files, history_commits, data_quality=stats.data_quality
    )
    test_gap_signal = calculate_test_gap_signal(
        changed_files, history_commits, data_quality=stats.data_quality
    )
    ownership_signal = calculate_ownership_signal(
        changed_files,
        history_commits,
        pr_author_email=req.pr_author_email,
        data_quality=stats.data_quality,
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
        base_ref=req.base_ref,
        head_ref=req.head_ref,
        total_files_changed=len(parsed_diff.files),
        additions=parsed_diff.total_additions,
        deletions=parsed_diff.total_deletions,
        data_quality=stats.data_quality,
        custom_weights=effective_weights,
        custom_thresholds=cfg["thresholds"],
        recommended_actions=actions,
    )

    if req.use_ai:
        enhanced_actions = generate_ai_explanation(result)
        result.recommended_actions = enhanced_actions

    return result


@app.post("/api/v1/analyze", response_model=AnalysisResult)
def analyze_endpoint(req: AnalyzeRequest) -> AnalysisResult:
    """Analyze a pull request and return complete structured risk assessment."""
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
