"""
report.py — Multi-format reporting engine.

Generates:
- Terminal (Rich console): gauges, colored badges, and structured breakdown.
- Markdown: Exact GitHub PR comment format shown in system architecture.
- JSON: Fully structured output for API and CI integrations.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from regression_radar.models import AnalysisResult, RiskCategory


def format_markdown_report(result: AnalysisResult) -> str:
    """Format analysis result as a GitHub PR comment in Markdown."""
    category_icons = {
        RiskCategory.LOW: "🟢",
        RiskCategory.MEDIUM: "🟡",
        RiskCategory.HIGH: "⚠️",
        RiskCategory.CRITICAL: "🚨",
    }
    icon = category_icons.get(result.risk_category, "⚠️")
    category_label = result.risk_category.value.capitalize()

    lines = [
        f"### {icon} Regression Risk: {category_label} ({result.overall_score:.0f} / 100)",
        "",
        "**Why was this flagged?**",
    ]

    for bullet in result.why_flagged:
        lines.append(f"- {bullet}")

    lines.extend(
        [
            "",
            "**Recommended Actions**",
        ]
    )

    rec = result.recommended_actions
    if rec.tests_to_run:
        lines.append(f"- **Run:** {', '.join(rec.tests_to_run)}")
    if rec.suggested_reviewers:
        lines.append(f"- **Suggested Reviewer:** {', '.join(rec.suggested_reviewers)}")
    if rec.summary:
        lines.append(f"- **Summary:** {rec.summary}")

    # Add signal score table
    lines.extend(
        [
            "",
            "<details>",
            "<summary><b>Detailed Signal Breakdown</b></summary>",
            "",
            "| Signal | Risk Score | Weight | Finding |",
            "|---|---|---|---|",
        ]
    )

    for name, s in result.signals.items():
        weight = result.weights.get(name, 0.0)
        clean_name = name.replace("_", " ").title()
        status = f"{s.score:.0f}/100" if s.is_available else "N/A"
        lines.append(f"| {clean_name} | {status} | {weight:.0%} | {s.explanation} |")

    diff_summary = (
        f"Diff: `{result.base_ref}..{result.head_ref}` — "
        f"{result.total_files_changed} file(s) changed (+{result.additions} -{result.deletions})"
    )
    lines.extend(
        [
            "",
            f"*{diff_summary}*",
            "</details>",
            "",
            "---",
            "*Regression Radar — PR-time, history-aware risk analysis*",
        ]
    )

    return "\n".join(lines)


def format_json_report(result: AnalysisResult) -> str:
    """Format analysis result as JSON."""
    return result.model_dump_json(indent=2)


def render_terminal_report(result: AnalysisResult, console: Console | None = None) -> None:
    """Render structured terminal report using Rich."""
    con = console or Console(legacy_windows=False)

    colors = {
        RiskCategory.LOW: "green",
        RiskCategory.MEDIUM: "yellow",
        RiskCategory.HIGH: "bright_red",
        RiskCategory.CRITICAL: "bold red",
    }
    color = colors.get(result.risk_category, "white")
    cat_label = result.risk_category.value.upper()

    header = f"[{color}]Regression Risk: {cat_label} ({result.overall_score:.0f} / 100)[/{color}]"
    sub = (
        f"Diff: {result.base_ref}..{result.head_ref} | "
        f"{result.total_files_changed} files (+{result.additions} -{result.deletions})"
    )
    con.print(Panel(f"[bold]{header}[/bold]\n[dim]{sub}[/dim]", border_style=color))

    # Why was this flagged?
    con.print("\n[bold]Why was this flagged?[/bold]")
    for b in result.why_flagged:
        con.print(f"  • {b}")

    # Recommended Actions
    con.print("\n[bold cyan]Recommended Actions[/bold cyan]")
    rec = result.recommended_actions
    if rec.tests_to_run:
        con.print(f"  [bold]• Run Tests:[/bold] {', '.join(rec.tests_to_run)}")
    if rec.suggested_reviewers:
        con.print(f"  [bold]• Reviewers:[/bold] {', '.join(rec.suggested_reviewers)}")
    if rec.summary:
        con.print(f"  [bold]• Summary:[/bold] {rec.summary}")

    # Signals Table
    con.print()
    table = Table(title="Signal Breakdown", show_lines=False)
    table.add_column("Signal", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Weight", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Explanation")

    for name, s in result.signals.items():
        w = result.weights.get(name, 0.0)
        clean_name = name.replace("_", " ").title()
        if s.is_available:
            sc_color = "red" if s.score >= 60 else ("yellow" if s.score >= 30 else "green")
            score_str = f"[{sc_color}]{s.score:.0f}/100[/{sc_color}]"
            status_str = "[green]Active[/green]"
        else:
            score_str = "[dim]—[/dim]"
            status_str = "[dim]Unavailable[/dim]"

        table.add_row(
            clean_name,
            score_str,
            f"{w:.0%}",
            status_str,
            s.explanation,
        )

    con.print(table)
