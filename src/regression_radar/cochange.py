"""
cochange.py — Co-change pattern detection.

Mines historical commit association rules between files that frequently change together.
Flags when a file is modified in a PR but its customary co-change partners are absent.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

from regression_radar.git_history import CommitInfo, DataQuality
from regression_radar.models import SignalResult

logger = logging.getLogger(__name__)


def calculate_cochange_signal(
    changed_files: Sequence[str],
    commits: Sequence[CommitInfo],
    *,
    min_support: int = 3,
    min_confidence: float = 0.50,
    data_quality: DataQuality = DataQuality.HIGH,
) -> SignalResult:
    """Mine historical co-change patterns and detect missing related files."""
    changed_set = set(changed_files)

    if not changed_files:
        return SignalResult(
            name="cochange_anomaly",
            score=0.0,
            explanation="No files changed; co-change anomaly is zero.",
            data_quality=data_quality,
            is_available=True,
            evidence={"missing_partners": [], "rules_evaluated": 0},
        )

    if len(commits) < 5:
        return SignalResult(
            name="cochange_anomaly",
            score=0.0,
            explanation="Insufficient commit history (< 5 commits) to infer rules.",
            data_quality=DataQuality.LOW,
            is_available=False,
            evidence={"missing_partners": [], "rules_evaluated": 0},
        )

    # 1. Count individual file frequencies and pairwise co-occurrences
    file_frequencies: dict[str, int] = defaultdict(int)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    pair_commits: dict[tuple[str, str], list[str]] = defaultdict(list)

    for c in commits:
        files = set(c.changed_files)
        # Exclude massive bulk commits (e.g. license changes touching 50+ files)
        if len(files) > 30:
            continue

        for f in files:
            file_frequencies[f] += 1

        file_list = sorted(files)
        for i, fa in enumerate(file_list):
            for fb in file_list[i + 1 :]:
                pair_counts[(fa, fb)] += 1
                if len(pair_commits[(fa, fb)]) < 5:
                    pair_commits[(fa, fb)].append(c.short_sha)

    # 2. Mine rules: for each changed file A, find partners B meeting thresholds
    missing_partners: list[dict[str, object]] = []
    satisfied_partners: list[dict[str, object]] = []
    anomaly_scores: list[float] = []

    for fa in changed_set:
        freq_a = file_frequencies.get(fa, 0)
        if freq_a < min_support:
            continue

        for (f1, f2), support in pair_counts.items():
            if f1 != fa and f2 != fa:
                continue

            fb = f2 if f1 == fa else f1
            confidence = support / freq_a

            if support >= min_support and confidence >= min_confidence:
                shas = pair_commits.get((min(f1, f2), max(f1, f2)), [])

                if fb not in changed_set:
                    missing_score = round(confidence * 100.0, 1)
                    anomaly_scores.append(missing_score)
                    missing_partners.append(
                        {
                            "changed_file": fa,
                            "missing_partner": fb,
                            "support": support,
                            "confidence": round(confidence, 3),
                            "example_shas": shas,
                        }
                    )
                else:
                    satisfied_partners.append(
                        {
                            "changed_file": fa,
                            "cochanged_partner": fb,
                            "support": support,
                            "confidence": round(confidence, 3),
                        }
                    )

    # Sort missing partners by confidence descending
    missing_partners.sort(key=lambda x: (float(x["confidence"]), int(x["support"])), reverse=True)

    # 3. Compute deterministic score
    if not missing_partners:
        score = 0.0
        if satisfied_partners:
            explanation = (
                f"No missing co-change anomalies. Found {len(satisfied_partners)} historical "
                "co-change relationship(s), and all related files are in the PR."
            )
        else:
            explanation = (
                "No strong historical co-change relationships were identified for modified files."
            )
        recommendations = []
    else:
        max_missing = max(anomaly_scores)
        count_bonus = min(len(missing_partners) * 7.5, 30.0)
        score = min(100.0, round(0.70 * max_missing + count_bonus, 1))

        top = missing_partners[0]
        conf_pct = f"{float(top['confidence']):.0%}"
        explanation = (
            f"Co-change anomaly score {score}/100. "
            f"'{top['changed_file']}' historically changes alongside '{top['missing_partner']}' "
            f"in {top['support']} commits ({conf_pct} confidence), but '{top['missing_partner']}' "
            "was not modified in this PR."
        )

        recommendations = [
            f"Check if '{p['missing_partner']}' requires updates "
            f"(frequently co-changed with '{p['changed_file']}')."
            for p in missing_partners[:3]
        ]

    return SignalResult(
        name="cochange_anomaly",
        score=score,
        explanation=explanation,
        data_quality=data_quality,
        is_available=True,
        evidence={
            "missing_partners": missing_partners,
            "satisfied_partners": satisfied_partners,
            "rules_evaluated": len(missing_partners) + len(satisfied_partners),
        },
        recommendations=recommendations,
    )
