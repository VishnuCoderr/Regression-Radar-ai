"""
cli.py — Typer CLI entry point for Regression Radar.

Currently wires up the Phase 1 git-history and diff-parser pipeline.
Full scoring, reporting and GitHub integration are added in later phases.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from regression_radar import __version__
from regression_radar.diff_parser import parse_diff
from regression_radar.git_history import (
    DataQuality,
    get_commits,
    get_diff,
    get_repo_stats,
)

# Ensure standard output can handle UTF-8 symbols on Windows terminals if supported,
# but use safe ASCII characters in Rich output for broad cross-platform safety.
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
    help="Regression Radar — history-aware PR risk analyser.",
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


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """Print the installed version."""
    console.print(f"[bold]Regression Radar[/bold] v{__version__}")


# ---------------------------------------------------------------------------
# inspect command (Phase 1 — repo stats + diff summary)
# ---------------------------------------------------------------------------


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
    """
    Inspect a repository: show stats, changed files, and commit summary.

    This is the Phase 1 diagnostic command. Full analysis (scores, signals,
    recommendations) will be available via the 'analyse' command in Phase 3.
    """
    _setup_logging(verbose)

    try:
        stats = get_repo_stats(repo)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    # --- Repository overview ---
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

    # --- Diff ---
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

    # --- Commit summary ---
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

    console.print(
        "\n[dim]Phase 1 complete. Run 'rr analyse' (Phase 3) for full risk scoring.[/dim]"
    )


# ---------------------------------------------------------------------------
# analyse command (Phase 3 placeholder — wired to inspect for now)
# ---------------------------------------------------------------------------


@app.command("analyse")
def analyse_cmd(
    repo: Path = typer.Argument(
        ...,
        help="Path to a local Git repository.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    base: str | None = typer.Option(None, "--base", "-b", help="Base branch or ref."),
    max_commits: int = typer.Option(500, "--max-commits"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """
    Analyse a repository and produce a risk-prioritisation report.

    [Phase 3 — full scoring and signals not yet implemented.
     Runs 'inspect' as a preview.]
    """
    console.print(
        "[yellow]ℹ[/yellow]  Full analysis (Phase 3) not yet implemented. "
        "Running 'inspect' instead.\n"
    )
    # Delegate to inspect for now
    inspect_cmd(
        repo=repo,
        base=base,
        max_commits=max_commits,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quality_badge(quality: DataQuality) -> None:
    badges = {
        DataQuality.HIGH: "[green][High][/green]",
        DataQuality.MEDIUM: "[yellow][Medium][/yellow]",
        DataQuality.LOW: "[red][Low][/red]",
    }
    console.print(f"[bold]History quality:[/bold] {badges[quality]}")


if __name__ == "__main__":
    app()
