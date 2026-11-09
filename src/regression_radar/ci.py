"""
ci.py — CI/CD automation, gate evaluation, and PR comment bot for Regression Radar.

Provides:
1. CIGateConfig and GateEvaluation for configurable threshold checking.
2. evaluate_ci_gates: evaluates risk score and test gaps without altering scoring weights.
3. format_ci_comment: formats a sticky GitHub PR comment in Markdown.
4. post_or_update_pr_comment: publishes or updates a single bot comment per PR.
5. parse_github_actions_context: extracts PR metadata safely from GitHub Actions event payloads.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from regression_radar.models import AnalysisResult, RiskCategory
from regression_radar.scoring import load_scoring_config

logger = logging.getLogger(__name__)

PR_COMMENT_MARKER = "<!-- regression-radar-comment -->"
_GITHUB_API_BASE = "https://api.github.com"


# ---------------------------------------------------------------------------
# CI Gate Configuration and Evaluation
# ---------------------------------------------------------------------------


@dataclass
class CIGateConfig:
    """Configuration for CI risk gates."""

    max_risk_score: float | None = None
    require_test_coverage: bool = False
    blocking: bool = False  # Default to non-blocking mode


@dataclass
class GateEvaluation:
    """Result of evaluating CI risk gates against an AnalysisResult."""

    passed: bool
    blocking: bool
    overall_score: float
    max_risk_score: float | None
    gate_failed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        if not self.gate_failed:
            return "PASSED"
        return "FAILED (BLOCKING)" if self.blocking else "WARNING (NON-BLOCKING)"


def load_ci_gate_config(
    config_path: Path | None = None,
    *,
    max_risk: float | None = None,
    require_tests: bool | None = None,
    blocking: bool | None = None,
) -> CIGateConfig:
    """
    Load CI gate configuration from TOML file, with optional CLI flag overrides.

    Preserves non-blocking mode by default unless explicitly configured.
    """
    raw_cfg = load_scoring_config(config_path)
    ci_section = raw_cfg.get("ci_gates", raw_cfg.get("gates", {}))

    # Read from file or fallback
    cfg_max_risk = ci_section.get("max_risk_score", ci_section.get("max_risk", None))
    if cfg_max_risk is not None:
        cfg_max_risk = float(cfg_max_risk)

    cfg_require_tests = bool(
        ci_section.get("require_test_coverage", ci_section.get("require_tests", False))
    )
    cfg_blocking = bool(ci_section.get("blocking", False))

    # Apply overrides if provided
    final_max_risk = max_risk if max_risk is not None else cfg_max_risk
    final_require_tests = require_tests if require_tests is not None else cfg_require_tests
    final_blocking = blocking if blocking is not None else cfg_blocking

    return CIGateConfig(
        max_risk_score=final_max_risk,
        require_test_coverage=final_require_tests,
        blocking=final_blocking,
    )


def evaluate_ci_gates(result: AnalysisResult, config: CIGateConfig) -> GateEvaluation:
    """
    Evaluate whether an analysis result satisfies repository CI risk gates.

    Never modifies scoring weights, thresholds, or underlying risk signals.
    """
    reasons: list[str] = []
    gate_failed = False

    # 1. Max risk score gate
    if config.max_risk_score is not None:
        if result.overall_score >= config.max_risk_score:
            gate_failed = True
            reasons.append(
                f"Risk score ({result.overall_score:.1f}/100) meets or exceeds "
                f"configured gate threshold of {config.max_risk_score:.1f}/100"
            )
        else:
            reasons.append(
                f"Risk score ({result.overall_score:.1f}/100) is within allowed "
                f"threshold ({config.max_risk_score:.1f}/100)"
            )

    # 2. Test gap remediation gate
    if config.require_test_coverage:
        test_gap_signal = result.signals.get("test_gap")
        unaddressed_tests = False
        if test_gap_signal and test_gap_signal.is_available:
            if test_gap_signal.score > 0:
                unaddressed_tests = True
            # Also check evidence for unaddressed source files
            gap_evidence = test_gap_signal.evidence.get("files", [])
            for item in gap_evidence:
                if isinstance(item, dict) and not item.get("test_modified_in_pr", False):
                    unaddressed_tests = True
                    break

        if unaddressed_tests:
            gate_failed = True
            reasons.append(
                "Test gap gate failed: modified source files lack corresponding tests in this PR"
            )
        else:
            reasons.append("Test gap gate passed: all modified source files have associated tests")

    # If no gate rules configured, default pass
    if config.max_risk_score is None and not config.require_test_coverage:
        reasons.append("No active CI risk gates configured (informational mode)")

    passed = not (gate_failed and config.blocking)

    return GateEvaluation(
        passed=passed,
        blocking=config.blocking,
        overall_score=result.overall_score,
        max_risk_score=config.max_risk_score,
        gate_failed=gate_failed,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# PR Comment Markdown Formatting
# ---------------------------------------------------------------------------


def format_ci_comment(
    result: AnalysisResult,
    gate: GateEvaluation | None = None,
    *,
    marker: str = PR_COMMENT_MARKER,
) -> str:
    """
    Format a comprehensive, sticky GitHub PR comment in Markdown.

    Includes risk classification, gate outcome, why-flagged reasons,
    recommended actions, remediation guidance, and signal details.
    """
    category_icons = {
        RiskCategory.LOW: "🟢",
        RiskCategory.MEDIUM: "🟡",
        RiskCategory.HIGH: "⚠️",
        RiskCategory.CRITICAL: "🚨",
    }
    icon = category_icons.get(result.risk_category, "⚠️")
    category_label = result.risk_category.value.capitalize()

    lines = [
        marker,
        f"### {icon} Regression Risk: {category_label} ({result.overall_score:.0f} / 100)",
        "",
    ]

    # CI Gate Banner
    if gate is not None:
        if not gate.gate_failed:
            lines.extend(
                [
                    "> **CI Gate Status:** 🟢 **Passed**",
                    f"> *{gate.reasons[0]}*" if gate.reasons else "",
                    "",
                ]
            )
        elif gate.blocking:
            lines.extend(
                [
                    "> **CI Gate Status:** 🛑 **Blocked**",
                    f"> *{gate.reasons[0]}*",
                    "> *Merge is blocked until risk is remediated.*",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "> **CI Gate Status:** ⚠️ **Warning (Non-blocking)**",
                    f"> *{gate.reasons[0]}*",
                    "> *Informational warning — merge not blocked.*",
                    "",
                ]
            )

    # Why flagged
    lines.append("**Why was this flagged?**")
    if result.why_flagged:
        for bullet in result.why_flagged:
            lines.append(f"- {bullet}")
    else:
        lines.append("- No high-risk factors detected.")

    # Recommended Actions
    lines.extend(["", "**Recommended Actions**"])
    rec = result.recommended_actions
    if rec.tests_to_run:
        lines.append(f"- **Run:** `{', '.join(rec.tests_to_run)}`")
    if rec.suggested_reviewers:
        lines.append(f"- **Suggested Reviewers:** {', '.join(rec.suggested_reviewers)}")
    if rec.summary:
        lines.append(f"- **Summary:** {rec.summary}")

    # Remediation guidance for high risk or test gaps
    remediations: list[str] = []
    if result.overall_score >= 60:
        remediations.append("High overall risk: schedule peer review with a primary code owner.")
    test_gap_signal = result.signals.get("test_gap")
    if test_gap_signal and test_gap_signal.score >= 50:
        remediations.append("Add unit or integration tests targeting the modified components.")
    cochange_signal = result.signals.get("cochange_anomaly")
    if cochange_signal and cochange_signal.score >= 50:
        remediations.append("Verify omitted co-change partner files to ensure system consistency.")

    if remediations:
        lines.extend(["", "**Remediation Checklist**"])
        for rem in remediations:
            lines.append(f"- [ ] {rem}")

    # Collapsible Detailed Signal Breakdown Table
    lines.extend(
        [
            "",
            "<details>",
            "<summary><b>📊 Detailed Signal Breakdown</b></summary>",
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
            "*Regression Radar — Automated PR Risk Analysis & CI Gates*",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub PR Comment Bot (Publish / Update Single Sticky Comment)
# ---------------------------------------------------------------------------


def get_pr_comments(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
) -> list[dict[str, Any]]:
    """Retrieve existing comments on a GitHub PR issue."""
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments?per_page=100"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "regression-radar-bot/0.1",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
            return []
    except urllib.error.HTTPError as exc:
        logger.error("Failed to list PR comments (HTTP %d)", exc.code)
        raise


def find_bot_comment(
    comments: list[dict[str, Any]],
    marker: str = PR_COMMENT_MARKER,
) -> dict[str, Any] | None:
    """Find an existing Regression Radar comment containing the sticky marker."""
    for comment in comments:
        body = comment.get("body", "")
        if marker in body:
            return comment
    return None


def post_or_update_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    token: str | None = None,
    marker: str = PR_COMMENT_MARKER,
) -> dict[str, Any]:
    """
    Publish or update a single sticky PR comment on GitHub.

    Prevents duplicate comments across multiple commits/pushes by searching
    for the marker and updating the existing comment via PATCH.
    """
    effective_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not effective_token:
        logger.warning(
            "GITHUB_TOKEN not configured; skipping PR comment creation/update."
        )
        return {"status": "skipped", "reason": "No GITHUB_TOKEN configured"}

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {effective_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "regression-radar-bot/0.1",
        "Content-Type": "application/json",
    }

    # 1. Check for existing comment
    try:
        comments = get_pr_comments(owner, repo, pr_number, effective_token)
    except Exception as exc:
        logger.error("Error retrieving PR comments: %s", exc)
        return {"status": "error", "reason": f"Could not list comments: {exc}"}

    existing = find_bot_comment(comments, marker=marker)

    # 2. Update existing comment via PATCH or create new via POST
    if existing and "id" in existing:
        comment_id = existing["id"]
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues/comments/{comment_id}"
        req = urllib.request.Request(
            url,
            data=json.dumps({"body": body}).encode("utf-8"),
            headers=headers,
            method="PATCH",
        )
        action = "updated"
    else:
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        req = urllib.request.Request(
            url,
            data=json.dumps({"body": body}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        action = "created"

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            logger.info("Successfully %s PR comment #%s on %s/%s", action, pr_number, owner, repo)
            return {"status": action, "comment_id": data.get("id"), "url": data.get("html_url")}
    except urllib.error.HTTPError as exc:
        logger.error("GitHub API error during comment %s (HTTP %d)", action, exc.code)
        return {"status": "error", "code": exc.code, "reason": f"HTTP {exc.code}"}
    except Exception as exc:
        logger.error("Unexpected error during comment %s: %s", action, exc)
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# GitHub Actions Context Parser
# ---------------------------------------------------------------------------


def parse_github_actions_context(
    event_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Safely extract PR number, owner, repo, base_ref, and head_ref from GitHub Actions.

    Reads GITHUB_EVENT_PATH payload when running in a GitHub Actions workflow.
    """
    path_str = event_path or os.environ.get("GITHUB_EVENT_PATH")
    context: dict[str, Any] = {
        "is_github_actions": bool(os.environ.get("GITHUB_ACTIONS")),
        "pr_number": None,
        "owner": None,
        "repo": None,
        "base_ref": os.environ.get("GITHUB_BASE_REF"),
        "head_ref": os.environ.get("GITHUB_HEAD_REF"),
        "event_name": os.environ.get("GITHUB_EVENT_NAME"),
    }

    # Extract repository from GITHUB_REPOSITORY (owner/repo)
    repo_env = os.environ.get("GITHUB_REPOSITORY")
    if repo_env and "/" in repo_env:
        owner_part, repo_part = repo_env.split("/", 1)
        context["owner"] = owner_part
        context["repo"] = repo_part

    if not path_str:
        return context

    event_file = Path(path_str)
    if not event_file.is_file():
        return context

    try:
        payload = json.loads(event_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read GITHUB_EVENT_PATH JSON: %s", exc)
        return context

    # Pull Request payload inspection
    pr_data = payload.get("pull_request")
    if isinstance(pr_data, dict):
        context["pr_number"] = pr_data.get("number")
        if not context["base_ref"]:
            base = pr_data.get("base", {})
            context["base_ref"] = base.get("ref")
        if not context["head_ref"]:
            head = pr_data.get("head", {})
            context["head_ref"] = head.get("ref")

    if not context["pr_number"]:
        context["pr_number"] = payload.get("number")

    repo_data = payload.get("repository")
    if isinstance(repo_data, dict):
        full_name = repo_data.get("full_name", "")
        if "/" in full_name:
            owner_part, repo_part = full_name.split("/", 1)
            context["owner"] = owner_part
            context["repo"] = repo_part

    return context
