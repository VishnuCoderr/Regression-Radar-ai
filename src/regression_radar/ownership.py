"""
ownership.py — Contributor ownership intelligence.

Identifies domain experts and recent contributors for modified files to suggest
knowledgeable reviewers, assessing unfamiliar-code risk based strictly on Git history.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from regression_radar.git_history import CommitInfo, DataQuality
from regression_radar.models import ContributorStats, SignalResult

logger = logging.getLogger(__name__)


def calculate_ownership_signal(
    changed_files: Sequence[str],
    commits: Sequence[CommitInfo],
    *,
    pr_author_email: str | None = None,
    recency_days: int = 180,
    data_quality: DataQuality = DataQuality.HIGH,
) -> SignalResult:
    """Analyse module ownership and suggest candidate reviewers from Git history."""
    if not changed_files:
        return SignalResult(
            name="ownership",
            score=0.0,
            explanation="No files changed; ownership risk is zero.",
            data_quality=data_quality,
            is_available=True,
            evidence={"reviewers": [], "file_ownership": {}},
        )

    if not commits:
        return SignalResult(
            name="ownership",
            score=30.0,
            explanation="No commit history available to evaluate contributor familiarity.",
            data_quality=DataQuality.LOW,
            is_available=False,
            evidence={"reviewers": [], "file_ownership": {}},
        )

    changed_set = set(changed_files)
    now = datetime.now(tz=UTC)

    # 1. Tally commits and recency for changed files
    author_commits: dict[str, int] = defaultdict(int)
    author_recent_commits: dict[str, int] = defaultdict(int)
    author_last_seen: dict[str, datetime] = {}
    author_names: dict[str, str] = {}
    file_authors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    total_relevant_commits = 0

    for c in commits:
        touched_pr_files = [f for f in c.changed_files if f in changed_set]
        if not touched_pr_files:
            continue

        total_relevant_commits += 1
        email = c.author_email.lower().strip()
        author_names[email] = c.author_name
        author_commits[email] += 1

        for f in touched_pr_files:
            file_authors[f][email] += 1

        commit_dt = c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=UTC)
        age_days = (now - commit_dt).total_seconds() / 86400.0

        if age_days <= recency_days:
            author_recent_commits[email] += 1

        if email not in author_last_seen or commit_dt > author_last_seen[email]:
            author_last_seen[email] = commit_dt

    # 2. Build contributor stats
    contributors: list[ContributorStats] = []
    for email, total_count in author_commits.items():
        recent_count = author_recent_commits.get(email, 0)
        last_dt = author_last_seen[email]
        age_days = max(0.0, (now - last_dt).total_seconds() / 86400.0)

        decay = 1.0 / (1.0 + (age_days / 90.0))
        recency_score = round(total_count * 0.4 + recent_count * 0.6 * decay, 2)

        contributors.append(
            ContributorStats(
                author_name=author_names.get(email, email),
                author_email=email,
                commit_count=total_count,
                recent_commit_count=recent_count,
                last_commit_date=last_dt.date().isoformat(),
                recency_score=recency_score,
            )
        )

    contributors.sort(key=lambda c: c.recency_score, reverse=True)

    # 3. Candidate reviewers (excluding PR author if known)
    candidate_reviewers: list[ContributorStats] = []
    normalized_pr_email = pr_author_email.lower().strip() if pr_author_email else None

    for c in contributors:
        if normalized_pr_email and c.author_email == normalized_pr_email:
            continue
        candidate_reviewers.append(c)

    # 4. Risk scoring
    if normalized_pr_email and total_relevant_commits > 0:
        author_share = author_commits.get(normalized_pr_email, 0) / total_relevant_commits
        score = round(max(5.0, (1.0 - author_share) * 85.0), 1)
        if author_share > 0.5:
            explanation = (
                f"Ownership risk is low ({score}/100): PR author '{normalized_pr_email}' authored "
                f"{author_share:.0%} of historical changes to these files."
            )
        else:
            explanation = (
                f"Ownership risk is elevated ({score}/100): PR author '{normalized_pr_email}' "
                f"has few prior changes to these files ({author_share:.0%} share)."
            )
    else:
        if not contributors:
            score = 20.0
            explanation = "No historical contributors found for modified files (new files)."
        elif len(contributors) == 1:
            score = 50.0
            explanation = (
                f"Ownership score 50/100: Modified files have only one historical contributor "
                f"('{contributors[0].author_name}'). Knowledge is highly concentrated."
            )
        else:
            score = 25.0
            explanation = (
                f"Ownership score 25/100: Modified files have active distributed maintenance "
                f"across {len(contributors)} contributors."
            )

    recommendations: list[str] = []
    if candidate_reviewers:
        top_names = [f"{r.author_name} ({r.author_email})" for r in candidate_reviewers[:2]]
        recommendations.append(
            f"Suggested reviewers based on commit history: {', '.join(top_names)}."
        )

    return SignalResult(
        name="ownership",
        score=score,
        explanation=explanation,
        data_quality=data_quality,
        is_available=True,
        evidence={
            "total_relevant_commits": total_relevant_commits,
            "contributors_count": len(contributors),
            "top_contributors": [c.model_dump() for c in contributors[:5]],
            "suggested_reviewers": [c.model_dump() for c in candidate_reviewers[:3]],
        },
        recommendations=recommendations,
    )
