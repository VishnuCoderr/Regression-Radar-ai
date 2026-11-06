"""
hotspot.py — Historical hotspot detection.

Identifies fragile files in a proposed PR by analysing past bug-fix and revert
frequency in the repository history, accounting for total file activity.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

from regression_radar.git_history import CommitInfo, DataQuality
from regression_radar.models import FileHotspotEvidence, SignalResult

logger = logging.getLogger(__name__)


def calculate_hotspot_signal(
    changed_files: Sequence[str],
    commits: Sequence[CommitInfo],
    data_quality: DataQuality = DataQuality.HIGH,
) -> SignalResult:
    """Calculate the Historical Hotspot risk signal for a set of changed files."""
    if not changed_files:
        return SignalResult(
            name="historical_hotspot",
            score=0.0,
            explanation="No files changed in this comparison; hotspot risk is zero.",
            data_quality=data_quality,
            is_available=True,
            evidence={"files": [], "repo_bugfix_rate": 0.0},
        )

    if not commits:
        return SignalResult(
            name="historical_hotspot",
            score=0.0,
            explanation="No historical commits available to assess file fragility.",
            data_quality=DataQuality.LOW,
            is_available=False,
            evidence={"files": [], "repo_bugfix_rate": 0.0},
        )

    # 1. Tally commit activity across history
    file_total_commits: dict[str, int] = defaultdict(int)
    file_bugfix_commits: dict[str, int] = defaultdict(int)
    file_bugfix_shas: dict[str, list[str]] = defaultdict(list)

    total_bugfix_commits = 0
    for c in commits:
        if c.is_bugfix_candidate:
            total_bugfix_commits += 1

        for f in c.changed_files:
            file_total_commits[f] += 1
            if c.is_bugfix_candidate:
                file_bugfix_commits[f] += 1
                if len(file_bugfix_shas[f]) < 5:
                    file_bugfix_shas[f].append(c.short_sha)

    repo_bugfix_rate = total_bugfix_commits / max(len(commits), 1)

    # 2. Evaluate each changed file
    file_evidences: list[FileHotspotEvidence] = []
    file_scores: list[float] = []

    for path in changed_files:
        total_f = file_total_commits.get(path, 0)
        bugs_f = file_bugfix_commits.get(path, 0)

        if total_f == 0:
            ev = FileHotspotEvidence(
                path=path,
                total_commits=0,
                bugfix_commits=0,
                bugfix_ratio=0.0,
                risk_score=0.0,
                bugfix_shas=[],
            )
            file_evidences.append(ev)
            file_scores.append(0.0)
            continue

        raw_ratio = bugs_f / total_f

        # Bayesian smoothing with repo average as prior
        prior_weight = 3.0
        smoothed_ratio = (bugs_f + prior_weight * repo_bugfix_rate) / (total_f + prior_weight)

        volume_component = min(bugs_f * 6.0, 30.0)
        ratio_component = smoothed_ratio * 70.0
        file_risk = min(100.0, round(ratio_component + volume_component, 1))

        ev = FileHotspotEvidence(
            path=path,
            total_commits=total_f,
            bugfix_commits=bugs_f,
            bugfix_ratio=round(raw_ratio, 3),
            risk_score=file_risk,
            bugfix_shas=file_bugfix_shas.get(path, []),
        )
        file_evidences.append(ev)
        file_scores.append(file_risk)

    # 3. Aggregate score across changed files
    max_risk = max(file_scores) if file_scores else 0.0
    avg_risk = sum(file_scores) / len(file_scores) if file_scores else 0.0
    overall_score = min(100.0, round(0.70 * max_risk + 0.30 * avg_risk, 1))

    file_evidences.sort(key=lambda e: e.risk_score, reverse=True)

    recommendations: list[str] = []
    top_hotspots = [e for e in file_evidences if e.bugfix_commits > 0]

    if not top_hotspots:
        explanation = (
            f"None of the {len(changed_files)} changed file(s) have a history of bug fixes/reverts."
        )
    else:
        top = top_hotspots[0]
        explanation = (
            f"Historical hotspot score {overall_score}/100. "
            f"Top fragile file is '{top.path}' with {top.bugfix_commits} bug-fix/revert commit(s) "
            f"out of {top.total_commits} total changes ({top.bugfix_ratio:.0%} fix rate)."
        )
        for h in top_hotspots[:3]:
            recommendations.append(
                f"Review changes in '{h.path}' carefully; "
                f"it has been amended {h.bugfix_commits} times for bug fixes."
            )

    return SignalResult(
        name="historical_hotspot",
        score=overall_score,
        explanation=explanation,
        data_quality=data_quality,
        is_available=True,
        evidence={
            "files": [e.model_dump() for e in file_evidences],
            "repo_bugfix_rate": round(repo_bugfix_rate, 3),
            "max_file_risk": max_risk,
        },
        recommendations=recommendations,
    )
