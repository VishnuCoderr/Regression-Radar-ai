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
from regression_radar.cochange import calculate_cochange_signal
from regression_radar.diff_parser import parse_diff
from regression_radar.git_history import (
    DataQuality,
    get_commits,
    get_diff,
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
        raw_diff = get_diff(repo, base_ref=effective_base, head_ref="HEAD")
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
    commits = get_commits(
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
        raw_diff = get_diff(repo, base_ref=effective_base, head_ref=effective_head)
    except RuntimeError as exc:
        err_console.print(f"[red]Diff error:[/red] {exc}")
        raise typer.Exit(1)

    parsed_diff = parse_diff(raw_diff.text)
    changed_files = parsed_diff.changed_paths
    renames = {f.path: f.old_path for f in parsed_diff.files if f.old_path and f.old_path != f.path}
    deleted_files = [f.path for f in parsed_diff.files if f.change_type.value == "deleted"]

    # 2. Extract commit history (prior to PR or on base branch)
    history_commits = get_commits(repo, max_commits=max_commits, exclude_merges=True)

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


def _quality_badge(quality: DataQuality) -> None:
    badges = {
        DataQuality.HIGH: "[green][High][/green]",
        DataQuality.MEDIUM: "[yellow][Medium][/yellow]",
        DataQuality.LOW: "[red][Low][/red]",
    }
    console.print(f"[bold]History quality:[/bold] {badges[quality]}")


if __name__ == "__main__":
    app()
