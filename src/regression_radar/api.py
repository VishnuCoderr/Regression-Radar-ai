"""
api.py — FastAPI backend service for Regression Radar.

Provides REST endpoints for triggering PR risk analysis, webhook consumption,
and retrieving structured analysis results.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import Response

from regression_radar import __version__
from regression_radar.cache import (
    cached_fetch_github_pr_data,
    cached_get_commits,
    cached_get_diff,
    clear_all_caches,
    get_all_cache_stats,
)
from regression_radar.cochange import calculate_cochange_signal
from regression_radar.config import settings
from regression_radar.diff_parser import parse_diff
from regression_radar.git_history import (
    CommitInfo,
    DataQuality,
    get_repo_stats,
    validate_repo,
)
from regression_radar.github_service import (
    GitHubAnalysisData,
    GitHubAPIError,
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

logger = logging.getLogger(__name__)
_APP_START_TIME = time.time()

app = FastAPI(
    title="Regression Radar API",
    description="Backend service for Pull Request Risk Analysis",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_request_id(incoming_id: str | None = None) -> str:
    """Return incoming request ID or generate a new UUID4 string."""
    return incoming_id if incoming_id and incoming_id.strip() else str(uuid.uuid4())


def apply_response_headers(
    request_id: str, start_time: float, response: Response
) -> None:
    """Attach correlation X-Request-ID and response timing headers."""
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"


@app.middleware("http")
async def request_id_and_logging_middleware(
    request: Request, call_next
) -> Response:
    """Attach correlation X-Request-ID and response timing headers."""
    t0 = time.perf_counter()
    request_id = resolve_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id

    response: Response = await call_next(request)
    apply_response_headers(request_id, t0, response)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safe production exception handler preventing internal stack trace leaks."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("Unhandled error on %s [request_id=%s]: %s", request.url.path, request_id, exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
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
    bypass_cache: bool = Field(default=False, description="Bypass in-memory cache")


class GitHubPRRequest(BaseModel):
    pr_url: str = Field(description="Full GitHub PR URL, e.g. https://github.com/owner/repo/pull/123")
    use_ai: bool = Field(default=False, description="Enrich recommendations with AI")
    bypass_cache: bool = Field(default=False, description="Bypass in-memory cache")


class DemoScenario(BaseModel):
    id: str
    title: str
    description: str
    category: str
    expected_score: float | None = None
    pr_url: str | None = None
    repo_path: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    author: str | None = None


class DemoRunRequest(BaseModel):
    scenario_id: str
    use_ai: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    version: str
    git_available: bool
    git_version: str | None
    storage_writable: bool
    cache_entries: int
    uptime_seconds: float


# ---------------------------------------------------------------------------
# Shared health / config endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
@app.get("/health/live", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Liveness probe: verifies process is alive and responsive."""
    return HealthResponse(status="healthy", version=__version__)


@app.get("/health/ready", response_model=ReadinessResponse)
def readiness_check() -> ReadinessResponse:
    """Readiness probe: validates critical dependencies (git, storage, cache)."""
    git_bin = shutil.which("git")
    git_available = False
    git_version = None

    if git_bin:
        try:
            res = subprocess.run(
                ["git", "--version"], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                git_available = True
                git_version = res.stdout.strip()
        except Exception:
            pass

    # Validate storage directory write permissions
    storage_writable = False
    try:
        settings.storage_path.mkdir(parents=True, exist_ok=True)
        probe = settings.storage_path / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        storage_writable = True
    except Exception:
        storage_writable = False

    all_stats = get_all_cache_stats()
    total_cache_entries = sum(c.get("size", 0) for c in all_stats.values())
    uptime = time.time() - _APP_START_TIME

    if not git_available:
        raise HTTPException(
            status_code=503,
            detail="Git executable not found or not responding on system PATH.",
        )

    return ReadinessResponse(
        status="ready",
        version=__version__,
        git_available=git_available,
        git_version=git_version,
        storage_writable=storage_writable,
        cache_entries=total_cache_entries,
        uptime_seconds=round(uptime, 2),
    )


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
        raw_diff = cached_get_diff(
            validated_path,
            base_ref=req.base_ref,
            head_ref=req.head_ref,
            bypass_cache=req.bypass_cache,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"Git diff failed: {exc}") from exc

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    history_commits = cached_get_commits(
        validated_path,
        max_commits=2000,
        exclude_merges=True,
        bypass_cache=req.bypass_cache,
    )
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


def fetch_github_pr_data(
    owner: str,
    repo: str,
    number: int,
    *,
    bypass_cache: bool = False,
) -> GitHubAnalysisData:
    """Fetch GitHub PR data with in-memory caching."""
    return cached_fetch_github_pr_data(owner, repo, number, bypass_cache=bypass_cache)


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

    # Fetch all data from GitHub (uses cached PR data if head_sha unchanged)
    try:
        gh_data = fetch_github_pr_data(
            owner, repo, number, bypass_cache=req.bypass_cache
        )
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
    has_token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    return {"has_token": has_token}


@app.get("/api/v1/cache/stats")
def cache_stats_endpoint() -> dict:
    """Return diagnostic hit/miss/eviction statistics for all in-memory caches."""
    return get_all_cache_stats()


@app.post("/api/v1/cache/clear")
def cache_clear_endpoint() -> dict:
    """Clear all in-memory caches."""
    clear_all_caches()
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Path resolution helpers (for containerized and local execution)
# ---------------------------------------------------------------------------


def resolve_project_root() -> Path:
    """
    Locate project root directory containing configs, examples, and ui.

    Checks in priority order:
    1. settings.project_root or RR_PROJECT_ROOT environment variable.
    2. Path relative to source file (__file__ -> src/regression_radar/api.py -> root).
    3. Current working directory (standard in Docker container where WORKDIR=/app).
    4. /app fallback for container environments.
    """
    if settings.project_root and settings.project_root.is_dir():
        return settings.project_root.resolve()

    env_root = os.environ.get("RR_PROJECT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir():
            return p

    # 1. Source layout: src/regression_radar/api.py -> root
    source_root = Path(__file__).resolve().parent.parent.parent
    if (
        (source_root / "configs").is_dir()
        or (source_root / "examples").is_dir()
        or (source_root / "ui").is_dir()
    ):
        return source_root

    # 2. Current working directory (e.g. /app in Docker)
    cwd = Path.cwd().resolve()
    if (cwd / "examples").is_dir() or (cwd / "ui").is_dir() or (cwd / "configs").is_dir():
        return cwd

    # 3. Standard container directory
    container_app = Path("/app")
    if container_app.is_dir() and (container_app / "examples").is_dir():
        return container_app

    return source_root


def resolve_ui_dist() -> Path | None:
    """
    Locate the directory containing compiled React frontend assets (index.html).

    Checks in priority order:
    1. settings.ui_dist_path or UI_DIST_PATH / RR_UI_DIST environment variables.
    2. /app/ui/dist (standard Docker container path).
    3. Path.cwd() / "ui" / "dist" (working directory in container or local root).
    4. _PROJECT_ROOT / "ui" / "dist" (resolved project root).
    5. Relative to this module file (when running from local source tree).
    """
    # 1. Explicit configuration or environment override
    if settings.ui_dist_path:
        p = settings.ui_dist_path.resolve()
        if (p / "index.html").is_file():
            return p

    env_path = os.environ.get("UI_DIST_PATH") or os.environ.get("RR_UI_DIST")
    if env_path:
        p = Path(env_path).resolve()
        if (p / "index.html").is_file():
            return p

    # 2. Check /app/ui/dist (Docker runtime)
    container_dist = Path("/app/ui/dist")
    if (container_dist / "index.html").is_file():
        return container_dist

    # 3. Check cwd / ui / dist
    cwd_dist = (Path.cwd() / "ui" / "dist").resolve()
    if (cwd_dist / "index.html").is_file():
        return cwd_dist

    # 4. Check project root / ui / dist
    root = resolve_project_root()
    root_dist = (root / "ui" / "dist").resolve()
    if (root_dist / "index.html").is_file():
        return root_dist

    # 5. Check relative to source module
    module_dist = (Path(__file__).resolve().parent.parent.parent / "ui" / "dist").resolve()
    if (module_dist / "index.html").is_file():
        return module_dist

    # Fallback to any directory that exists even if index.html is missing
    for candidate in [cwd_dist, root_dist, container_dist, module_dist]:
        if candidate.is_dir():
            return candidate

    return None


_PROJECT_ROOT = resolve_project_root()
_ui_dist = resolve_ui_dist()


# ---------------------------------------------------------------------------
# Demo Scenarios API (for 1-click evaluation & interactive testing)
# ---------------------------------------------------------------------------


@app.get("/api/v1/demo/scenarios", response_model=list[DemoScenario])
def list_demo_scenarios() -> list[DemoScenario]:
    """Return available pre-configured demo scenarios for one-click evaluation."""
    high_risk_path = _PROJECT_ROOT / "examples" / "high-risk-demo"
    safe_demo_path = _PROJECT_ROOT / "examples" / "demo-repo"

    return [
        DemoScenario(
            id="high-risk-payment",
            title="High-Risk Payment Regression",
            description=(
                "Critical transaction validation change omitting required ledger co-change "
                "and test updates by an unfamiliar author."
            ),
            category="high",
            expected_score=60.2,
            repo_path=str(high_risk_path),
            base_ref="main",
            head_ref="HEAD",
            author="new@example.com",
        ),
        DemoScenario(
            id="safe-pr",
            title="Safe User Model & Test Update",
            description=(
                "Additive change adding user model flags with accompanying unit tests "
                "and non-fragile history."
            ),
            category="low",
            expected_score=18.8,
            repo_path=str(safe_demo_path),
            base_ref="main",
            head_ref="feature/safe-user-update",
            author="ananya@example.com",
        ),
        DemoScenario(
            id="sample-github-pr",
            title="Sample GitHub Pull Request",
            description="Public pull request analyzed via GitHub REST API without local checkout.",
            category="github",
            expected_score=None,
            pr_url="https://github.com/octocat/Hello-World/pull/1",
        ),
    ]


@app.post("/api/v1/demo/run", response_model=AnalysisResult)
def run_demo_scenario(req: DemoRunRequest) -> AnalysisResult:
    """Execute a pre-configured demo scenario and return full analysis results."""
    scenario_id = req.scenario_id.lower().strip()
    high_risk_path = _PROJECT_ROOT / "examples" / "high-risk-demo"
    demo_repo_path = _PROJECT_ROOT / "examples" / "demo-repo"

    if scenario_id == "high-risk-payment":
        if not (high_risk_path / ".git").is_dir():
            import sys

            examples_dir = str(_PROJECT_ROOT / "examples")
            if examples_dir not in sys.path:
                sys.path.insert(0, examples_dir)
            from build_high_risk_demo import create_high_risk_demo

            create_high_risk_demo(high_risk_path)

        return _run_analysis(
            AnalyzeRequest(
                repo_path=str(high_risk_path),
                base_ref="main",
                head_ref="HEAD",
                pr_author_email="new@example.com",
                use_ai=req.use_ai,
            )
        )

    if scenario_id == "safe-pr":
        if not (demo_repo_path / ".git").is_dir():
            import sys

            examples_dir = str(_PROJECT_ROOT / "examples")
            if examples_dir not in sys.path:
                sys.path.insert(0, examples_dir)
            from build_demo_repo import create_demo_repository

            create_demo_repository(demo_repo_path)

        return _run_analysis(
            AnalyzeRequest(
                repo_path=str(demo_repo_path),
                base_ref="main",
                head_ref="feature/safe-user-update",
                pr_author_email="ananya@example.com",
                use_ai=req.use_ai,
            )
        )

    if scenario_id == "sample-github-pr":
        return analyze_github_pr_endpoint(
            GitHubPRRequest(
                pr_url="https://github.com/octocat/Hello-World/pull/1",
                use_ai=req.use_ai,
            )
        )

    raise HTTPException(status_code=404, detail=f"Unknown demo scenario '{req.scenario_id}'")


# ---------------------------------------------------------------------------
# Production Static UI Serving (SPA fallback)
# ---------------------------------------------------------------------------


def serve_root() -> Response:
    """Serve index.html at root path."""
    if not _ui_dist:
        raise HTTPException(status_code=404, detail="SPA distribution directory not found")
    index_file = _ui_dist / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="SPA index file not found")


def serve_spa(full_path: str) -> Response:
    """Serve compiled React SPA assets with index.html fallback for client-side routing."""
    if not _ui_dist:
        raise HTTPException(status_code=404, detail="SPA distribution directory not found")

    clean_path = full_path.strip("/")
    # Prevent static handler from hijacking API or health routes
    if (
        clean_path == "api"
        or clean_path.startswith("api/")
        or clean_path == "health"
        or clean_path.startswith("health/")
    ):
        raise HTTPException(status_code=404, detail="API route not found")

    # Check for direct static file match (e.g. favicon.svg, icons.svg, robots.txt)
    if full_path:
        try:
            requested = (_ui_dist / full_path).resolve()
            if requested.is_file() and _ui_dist.resolve() in requested.parents:
                return FileResponse(requested)
        except Exception:
            pass

    # SPA client-side route fallback
    index_file = _ui_dist / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="SPA index file not found")


if settings.serve_static_ui and _ui_dist and _ui_dist.is_dir():
    _assets_dir = _ui_dist / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    app.add_api_route("/", serve_root, methods=["GET"], include_in_schema=False)
    app.add_api_route("/{full_path:path}", serve_spa, methods=["GET"], include_in_schema=False)
