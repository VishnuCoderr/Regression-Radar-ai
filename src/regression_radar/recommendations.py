"""
recommendations.py — Actionable recommendation generator.

Synthesizes findings across signals into a prioritized action checklist:
tests to run, reviewers to tag, and an executive summary.
"""

from __future__ import annotations

from regression_radar.models import RecommendedActions, RiskCategory, SignalResult


def build_recommendations(
    signals: dict[str, SignalResult],
    overall_score: float,
    category: RiskCategory,
) -> RecommendedActions:
    """Build structured recommended actions from analysis findings."""
    tests_to_run: list[str] = []
    suggested_reviewers: list[str] = []

    # 1. Tests to run from test_gap signal
    if "test_gap" in signals:
        tg = signals["test_gap"]
        ev = tg.evidence.get("files", [])
        for f in ev:
            matched = f.get("matched_test_file")
            src = f.get("source_file")
            if matched and not f.get("test_modified_in_pr"):
                tests_to_run.append(f"{matched} (covers modified '{src}')")
            elif not matched:
                tests_to_run.append(f"Add new unit tests for '{src}' (no test file exists)")

    # 2. Suggested reviewers from ownership signal
    if "ownership" in signals:
        own = signals["ownership"]
        reviewers = own.evidence.get("suggested_reviewers", [])
        for r in reviewers:
            name = r.get("author_name")
            email = r.get("author_email")
            commits = r.get("commit_count", 0)
            suggested_reviewers.append(f"{name} ({email}) — {commits} prior commit(s)")

    # 3. Formulate concise summary
    fragile_files = []
    if "historical_hotspot" in signals:
        hot = signals["historical_hotspot"]
        for f in hot.evidence.get("files", []):
            if f.get("bugfix_commits", 0) > 0:
                fragile_files.append(f.get("path"))

    absent_partners = []
    if "cochange_anomaly" in signals:
        co = signals["cochange_anomaly"]
        for p in co.evidence.get("missing_partners", []):
            absent_partners.append(p.get("missing_partner"))

    unavailable_signals = [s.name for s in signals.values() if not s.is_available]

    summary_parts = []
    if category in (RiskCategory.CRITICAL, RiskCategory.HIGH):
        summary_parts.append(
            f"This pull request carries an elevated risk score ({overall_score}/100)."
        )
    elif category == RiskCategory.MEDIUM:
        summary_parts.append(f"This change has moderate risk ({overall_score}/100).")
    else:
        summary_parts.append(f"This change has low risk ({overall_score}/100).")

    if unavailable_signals:
        summary_parts.append(
            f"Note: Limited commit history; {len(unavailable_signals)} signal(s) were unavailable."
        )

    if fragile_files:
        summary_parts.append(
            f"Modifies fragile files with past bug-fixes ({', '.join(fragile_files[:2])})."
        )
    if absent_partners:
        summary_parts.append(
            f"Frequently coupled files were omitted ({', '.join(absent_partners[:2])})."
        )

    summary_parts.append("Verify relevant tests and consult recommended reviewers before merging.")
    summary = " ".join(summary_parts)

    return RecommendedActions(
        tests_to_run=tests_to_run[:4],
        suggested_reviewers=suggested_reviewers[:3],
        summary=summary,
    )
