"""
cli.py — Typer CLI entry point for Regression Radar.

Provides:
- rr version: Print version.
- rr inspect: Diagnostic repo statistics and diff breakdown.
- rr analyse: Full multi-engine risk analysis with terminal, Markdown, and JSON reports.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from regression_radar import __version__
from regression_radar.cache import cached_get_commits, cached_get_diff
from regression_radar.ci import (
    evaluate_ci_gates,
    format_ci_comment,
    load_ci_gate_config,
    parse_github_actions_context,
    post_or_update_pr_comment,
)
from regression_radar.cochange import calculate_cochange_signal
from regression_radar.config import settings
from regression_radar.diff_parser import parse_diff
from regression_radar.git_history import (
    DataQuality,
    get_repo_stats,
)
from regression_radar.hotspot import calculate_hotspot_signal
from regression_radar.llm_explain import generate_ai_explanation
from regression_radar.ownership import calculate_ownership_signal
from regression_radar.recommendations import build_recommendations
from regression_radar.report import (
    format_json_report,
    format_markdown_report,
    render_terminal_report,
)
from regression_radar.scoring import (
    build_analysis_result,
    compute_risk_score,
    load_scoring_config,
)
from regression_radar.test_gap import calculate_test_gap_signal

# Ensure standard output handles UTF-8 on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = typer.Typer(
    name="rr",
    help="Regression Radar — AI-powered Pull Request risk analyser.",
    add_completion=False,
)

console = Console(legacy_windows=False)
err_console = Console(stderr=True, legacy_windows=False)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command("version")
def version_cmd() -> None:
    """Print the installed version."""
    console.print(f"[bold]Regression Radar[/bold] v{__version__}")


@app.command("inspect")
def inspect_cmd(
    repo: Path = typer.Argument(
        ...,
        help="Path to a local Git repository.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    base: str | None = typer.Option(
        None,
        "--base",
        "-b",
        help="Base branch or ref to diff against (e.g. main). Defaults to HEAD~1.",
    ),
    max_commits: int = typer.Option(
        500,
        "--max-commits",
        help="Maximum commits to load from history.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Inspect a repository: show stats, changed files, and commit summary."""
    _setup_logging(verbose)

    try:
        stats = get_repo_stats(repo)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    console.rule("[bold blue]Regression Radar — Repository Inspection[/bold blue]")
    console.print(f"[bold]Repository:[/bold]  {stats.path}")
    console.print(f"[bold]Total commits:[/bold] {stats.total_commits}")
    console.print(f"[bold]Shallow clone:[/bold] {'Yes [!] ' if stats.is_shallow else 'No'}")
    _quality_badge(stats.data_quality)
    if stats.default_branch:
        console.print(f"[bold]Default branch:[/bold] {stats.default_branch}")

    if stats.total_commits == 0:
        console.print("\n[yellow][!] Empty repository -- no commits yet.[/yellow]")
        raise typer.Exit(0)

    if stats.data_quality == DataQuality.LOW:
        console.print(
            "\n[yellow][!] Low data quality: fewer than 10 commits or shallow clone.[/yellow]"
            "\n   Analysis signals will be weak or unavailable."
        )

    effective_base = base or (stats.default_branch or "HEAD~1")
    console.print(f"\n[bold]Diff base:[/bold] {effective_base} -> HEAD\n")

    try:
        raw_diff = cached_get_diff(repo, base_ref=effective_base, head_ref="HEAD")
    except RuntimeError as exc:
        err_console.print(f"[red]Diff error:[/red] {exc}")
        raise typer.Exit(1)

    parsed = parse_diff(raw_diff.text)

    if not parsed.files:
        console.print("[dim]No file changes detected in this range.[/dim]")
    else:
        table = Table(title="Changed Files", show_lines=False)
        table.add_column("File", style="cyan", no_wrap=False)
        table.add_column("Type", style="magenta", justify="center")
        table.add_column("+Lines", style="green", justify="right")
        table.add_column("-Lines", style="red", justify="right")
        table.add_column("Hunks", justify="right")

        for fd in parsed.files:
            old = f" (was {fd.old_path})" if fd.old_path else ""
            table.add_row(
                f"{fd.path}{old}",
                fd.change_type.value,
                str(fd.total_additions) if not fd.is_binary else "—",
                str(fd.total_deletions) if not fd.is_binary else "—",
                str(len(fd.hunks)),
            )

        console.print(table)
        console.print(
            f"\n[bold]Summary:[/bold] {len(parsed.files)} file(s) changed, "
            f"[green]+{parsed.total_additions}[/green] "
            f"[red]-{parsed.total_deletions}[/red] lines"
        )

    console.print()
    commits = cached_get_commits(
        repo,
        max_commits=max_commits,
        base_ref=effective_base,
    )
    bugfix_count = sum(1 for c in commits if c.is_bugfix_candidate)

    console.print(
        f"[bold]Commits in range:[/bold] {len(commits)} ({bugfix_count} bug-fix candidates)"
    )
    if commits:
        console.print("\n[bold]Recent commits (up to 10):[/bold]")
        for c in commits[:10]:
            tag = " [yellow][bugfix][/yellow]" if c.is_bugfix_candidate else ""
            console.print(f"  [dim]{c.short_sha}[/dim] {c.timestamp.date()}  {c.subject[:72]}{tag}")


@app.command("analyse")
def analyse_cmd(
    repo: Path = typer.Argument(
        ...,
        help="Path to a local Git repository.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    base: str | None = typer.Option(None, "--base", "-b", help="Base branch or ref (e.g. main)."),
    head: str | None = typer.Option(
        None, "--head", "-h", help="Head commit or ref (defaults to HEAD)."
    ),
    format: str = typer.Option(
        "terminal",
        "--format",
        "-f",
        help="Output format: terminal, markdown, json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write report output to a file instead of stdout.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Custom path to weights configuration TOML file.",
    ),
    author: str | None = typer.Option(
        None,
        "--author",
        help="Email of the PR author (used to calculate ownership familiarity).",
    ),
    max_commits: int = typer.Option(2000, "--max-commits"),
    ai: bool = typer.Option(
        True,
        "--ai/--no-ai",
        help="Enable AI summary enrichment if GEMINI_API_KEY is configured.",
    ),
    cache: bool = typer.Option(
        True,
        "--cache/--no-cache",
        help="Enable in-memory caching for Git history and diffs.",
    ),
    max_risk: float | None = typer.Option(
        None, "--max-risk", help="Fail CI gate if risk meets/exceeds this score."
    ),
    require_tests: bool = typer.Option(
        False, "--require-tests", help="Fail CI gate if modified source files lack tests."
    ),
    blocking: bool = typer.Option(
        False, "--blocking/--non-blocking", help="Block execution (exit 1) if gate fails."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyse a pull request or ref comparison and produce an explainable risk report."""
    _setup_logging(verbose)

    try:
        stats = get_repo_stats(repo)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if stats.total_commits == 0:
        console.print("[yellow]Repository is empty (no commits yet).[/yellow]")
        raise typer.Exit(0)

    effective_base = base or (stats.default_branch or "HEAD~1")
    effective_head = head or "HEAD"

    # 1. Extract diff
    try:
        raw_diff = cached_get_diff(
            repo,
            base_ref=effective_base,
            head_ref=effective_head,
            bypass_cache=not cache,
        )
    except RuntimeError as exc:
        err_console.print(f"[red]Diff error:[/red] {exc}")
        raise typer.Exit(1)

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    renames = {f.path: f.old_path for f in parsed_diff.files if f.old_path and f.old_path != f.path}
    deleted_files = [f.path for f in parsed_diff.files if f.change_type.value == "deleted"]

    # 2. Extract commit history (prior to PR or on base branch)
    history_commits = cached_get_commits(
        repo,
        max_commits=max_commits,
        exclude_merges=True,
        bypass_cache=not cache,
    )

    # 3. Execute all 4 analysis signals
    hotspot_signal = calculate_hotspot_signal(
        changed_files, history_commits, data_quality=stats.data_quality, renames=renames
    )
    cochange_signal = calculate_cochange_signal(
        changed_files, history_commits, data_quality=stats.data_quality, renames=renames
    )
    test_gap_signal = calculate_test_gap_signal(
        changed_files,
        history_commits,
        data_quality=stats.data_quality,
        renames=renames,
        deleted_files=deleted_files,
    )
    ownership_signal = calculate_ownership_signal(
        changed_files,
        history_commits,
        pr_author_email=author,
        data_quality=stats.data_quality,
        renames=renames,
    )

    signals = {
        "historical_hotspot": hotspot_signal,
        "cochange_anomaly": cochange_signal,
        "test_gap": test_gap_signal,
        "ownership": ownership_signal,
    }

    # 4. Load config and compute deterministic score
    cfg = load_scoring_config(config)
    score, category, effective_weights = compute_risk_score(
        signals, weights=cfg["weights"], thresholds=cfg["thresholds"]
    )

    # 5. Build recommendations
    actions = build_recommendations(signals, score, category)

    # 6. Build initial analysis result
    result = build_analysis_result(
        signals=signals,
        base_ref=effective_base,
        head_ref=effective_head,
        total_files_changed=len(parsed_diff.files),
        additions=parsed_diff.total_additions,
        deletions=parsed_diff.total_deletions,
        data_quality=stats.data_quality,
        custom_weights=effective_weights,
        custom_thresholds=cfg["thresholds"],
        recommended_actions=actions,
    )

    # Optional AI enrichment
    if ai:
        enhanced_actions = generate_ai_explanation(result)
        result.recommended_actions = enhanced_actions

    # 7. Render output
    fmt = format.lower().strip()
    if fmt == "json":
        out_text = format_json_report(result)
        if output:
            output.write_text(out_text, encoding="utf-8")
            console.print(f"[green]Report saved to {output}[/green]")
        else:
            print(out_text)
    elif fmt == "markdown" or output:
        out_text = format_markdown_report(result)
        if output:
            output.write_text(out_text, encoding="utf-8")
            console.print(f"[green]Markdown report written to {output}[/green]")
        else:
            print(out_text)
    else:
        render_terminal_report(result, console)

    # 8. Evaluate CI gates if configured
    gate_cfg = load_ci_gate_config(
        config,
        max_risk=max_risk,
        require_tests=require_tests,
        blocking=blocking,
    )
    gate_eval = evaluate_ci_gates(result, gate_cfg)
    if gate_eval.gate_failed:
        if gate_eval.blocking:
            err_console.print(f"\n[bold red]CI Gate Failed:[/bold red] {gate_eval.reasons[0]}")
            raise typer.Exit(1)
        else:
            reason = gate_eval.reasons[0]
            console.print(f"\n[bold yellow]CI Gate Warning (Non-blocking):[/bold yellow] {reason}")


@app.command("analyze")
def analyze_cmd(
    repo: Path = typer.Argument(
        ...,
        help="Path to a local Git repository.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    base: str | None = typer.Option(None, "--base", "-b", help="Base branch or ref (e.g. main)."),
    head: str | None = typer.Option(
        None, "--head", "-h", help="Head commit or ref (defaults to HEAD)."
    ),
    format: str = typer.Option(
        "terminal",
        "--format",
        "-f",
        help="Output format: terminal, markdown, json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write report output to a file instead of stdout.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Custom path to weights configuration TOML file.",
    ),
    author: str | None = typer.Option(
        None,
        "--author",
        help="Email of the PR author (used to calculate ownership familiarity).",
    ),
    max_commits: int = typer.Option(2000, "--max-commits"),
    ai: bool = typer.Option(
        True,
        "--ai/--no-ai",
        help="Enable AI summary enrichment if GEMINI_API_KEY is configured.",
    ),
    cache: bool = typer.Option(
        True,
        "--cache/--no-cache",
        help="Enable in-memory caching for Git history and diffs.",
    ),
    max_risk: float | None = typer.Option(
        None, "--max-risk", help="Fail CI gate if risk meets/exceeds this score."
    ),
    require_tests: bool = typer.Option(
        False, "--require-tests", help="Fail CI gate if modified source files lack tests."
    ),
    blocking: bool = typer.Option(
        False, "--blocking/--non-blocking", help="Block execution (exit 1) if gate fails."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyse a pull request or ref comparison (US English alias for 'analyse')."""
    analyse_cmd(
        repo=repo,
        base=base,
        head=head,
        format=format,
        output=output,
        config=config,
        author=author,
        max_commits=max_commits,
        ai=ai,
        cache=cache,
        max_risk=max_risk,
        require_tests=require_tests,
        blocking=blocking,
        verbose=verbose,
    )


@app.command("ci")
def ci_cmd(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to local repository.",
        file_okay=False,
        resolve_path=True,
    ),
    base: str | None = typer.Option(None, "--base", "-b", help="Base branch/ref."),
    head: str | None = typer.Option(None, "--head", "-h", help="Head commit/ref."),
    pr_number: int | None = typer.Option(None, "--pr", help="Pull request number."),
    repo_slug: str | None = typer.Option(None, "--repo-slug", help="GitHub repo 'owner/repo'."),
    max_risk: float | None = typer.Option(None, "--max-risk", help="Fail if risk >= threshold."),
    require_tests: bool = typer.Option(False, "--require-tests", help="Fail if tests missing."),
    blocking: bool = typer.Option(
        False, "--blocking/--non-blocking", help="Block CI (exit 1) on gate failure."
    ),
    post_comment: bool = typer.Option(
        True, "--post-comment/--no-post-comment", help="Publish/update sticky PR comment."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write report to file."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config TOML path."),
    author: str | None = typer.Option(None, "--author", help="PR author email."),
    ai: bool = typer.Option(False, "--ai/--no-ai", help="Enable AI explanation if configured."),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Use in-memory cache."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run automated CI risk analysis, evaluate gates, and publish/update PR comment."""
    _setup_logging(verbose)
    actions_ctx = parse_github_actions_context()

    try:
        stats = get_repo_stats(repo)
    except ValueError as exc:
        err_console.print(f"[red]Repository Error:[/red] {exc}")
        raise typer.Exit(1)

    effective_base = base or actions_ctx.get("base_ref") or stats.default_branch or "main"
    effective_head = head or actions_ctx.get("head_ref") or "HEAD"

    # 1. Extract diff
    try:
        raw_diff = cached_get_diff(
            repo,
            base_ref=effective_base,
            head_ref=effective_head,
            bypass_cache=not cache,
        )
    except RuntimeError as exc:
        err_console.print(f"[red]Diff error:[/red] {exc}")
        raise typer.Exit(1)

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    renames = {f.path: f.old_path for f in parsed_diff.files if f.old_path and f.old_path != f.path}
    deleted_files = [f.path for f in parsed_diff.files if f.change_type.value == "deleted"]

    # 2. Extract commit history
    history_commits = cached_get_commits(
        repo,
        max_commits=2000,
        exclude_merges=True,
        bypass_cache=not cache,
    )

    # 3. Execute all 4 analysis signals
    hotspot_signal = calculate_hotspot_signal(
        changed_files, history_commits, data_quality=stats.data_quality, renames=renames
    )
    cochange_signal = calculate_cochange_signal(
        changed_files, history_commits, data_quality=stats.data_quality, renames=renames
    )
    test_gap_signal = calculate_test_gap_signal(
        changed_files,
        history_commits,
        data_quality=stats.data_quality,
        renames=renames,
        deleted_files=deleted_files,
    )
    ownership_signal = calculate_ownership_signal(
        changed_files,
        history_commits,
        pr_author_email=author,
        data_quality=stats.data_quality,
        renames=renames,
    )

    signals = {
        "historical_hotspot": hotspot_signal,
        "cochange_anomaly": cochange_signal,
        "test_gap": test_gap_signal,
        "ownership": ownership_signal,
    }

    # 4. Load scoring config and compute deterministic score
    cfg = load_scoring_config(config)
    score, category, effective_weights = compute_risk_score(
        signals, weights=cfg["weights"], thresholds=cfg["thresholds"]
    )
    actions = build_recommendations(signals, score, category)

    result = build_analysis_result(
        signals=signals,
        base_ref=effective_base,
        head_ref=effective_head,
        total_files_changed=len(parsed_diff.files),
        additions=parsed_diff.total_additions,
        deletions=parsed_diff.total_deletions,
        data_quality=stats.data_quality,
        custom_weights=effective_weights,
        custom_thresholds=cfg["thresholds"],
        recommended_actions=actions,
    )

    if ai:
        enhanced_actions = generate_ai_explanation(result)
        result.recommended_actions = enhanced_actions

    # 5. Evaluate CI gates
    gate_cfg = load_ci_gate_config(
        config,
        max_risk=max_risk,
        require_tests=require_tests,
        blocking=blocking,
    )
    gate_eval = evaluate_ci_gates(result, gate_cfg)

    # 6. Format Markdown comment
    comment_body = format_ci_comment(result, gate_eval)

    if output:
        output.write_text(comment_body, encoding="utf-8")
        console.print(f"[green]Report written to {output}[/green]")

    # 7. Post or update PR comment if in PR context
    effective_pr = pr_number or actions_ctx.get("pr_number")
    effective_owner = actions_ctx.get("owner")
    effective_repo_name = actions_ctx.get("repo")
    if repo_slug and "/" in repo_slug:
        effective_owner, effective_repo_name = repo_slug.split("/", 1)

    if post_comment and effective_owner and effective_repo_name and effective_pr:
        console.print(
            f"[bold blue]Updating PR #{effective_pr} comment on "
            f"{effective_owner}/{effective_repo_name}...[/bold blue]"
        )
        comment_res = post_or_update_pr_comment(
            owner=effective_owner,
            repo=effective_repo_name,
            pr_number=effective_pr,
            body=comment_body,
        )
        console.print(f"[green]Comment result:[/green] {comment_res.get('status')}")

    # 8. Render terminal summary & gate decision
    render_terminal_report(result, console)
    console.rule("[bold]CI Gate Decision[/bold]")
    gate_msg = gate_eval.reasons[0] if gate_eval.reasons else "Evaluated"
    if not gate_eval.gate_failed:
        console.print(f"[bold green]✓ GATE PASSED[/bold green]: {gate_msg}")
    elif gate_eval.blocking:
        err_console.print(f"[bold red]✗ GATE BLOCKED (Strict Mode)[/bold red]: {gate_msg}")
        raise typer.Exit(1)
    else:
        console.print(f"[bold yellow]! GATE WARNING (Non-blocking)[/bold yellow]: {gate_msg}")


@app.command("serve")
def serve_cmd(
    host: str | None = typer.Option(
        None,
        "--host",
        "-h",
        help="Host interface to bind the server to (defaults to RR_HOST or 0.0.0.0).",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port number to bind the server to (defaults to PORT/RR_PORT or 8000).",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Enable auto-reload on code changes (recommended for development).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug logging."),
) -> None:
    """Launch the Regression Radar FastAPI backend and web application."""
    _setup_logging(verbose)
    effective_host = host or settings.host
    effective_port = port if port is not None else settings.port

    console.print(
        f"[bold blue]Starting Regression Radar v{__version__}[/bold blue] on "
        f"[green]http://{effective_host}:{effective_port}[/green]"
    )
    if reload:
        console.print("[dim yellow]Auto-reload enabled[/dim yellow]")

    try:
        import uvicorn
    except ImportError:
        err_console.print(
            "[bold red]Error:[/bold red] uvicorn is not installed. "
            "Install with 'pip install regression-radar[api]'."
        )
        raise typer.Exit(1)

    uvicorn.run(
        "regression_radar.api:app",
        host=effective_host,
        port=effective_port,
        reload=reload,
        log_level="debug" if verbose else settings.log_level.lower(),
    )


def _quality_badge(quality: DataQuality) -> None:
    badges = {
        DataQuality.HIGH: "[green][High][/green]",
        DataQuality.MEDIUM: "[yellow][Medium][/yellow]",
        DataQuality.LOW: "[red][Low][/red]",
    }
    console.print(f"[bold]History quality:[/bold] {badges[quality]}")


if __name__ == "__main__":
    app()
