"""
scoring.py — Deterministic risk scoring engine.

Combines signal scores using configurable weights into a final 0–100
risk-prioritisation score with category classification.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from regression_radar.git_history import DataQuality
from regression_radar.models import AnalysisResult, RecommendedActions, RiskCategory, SignalResult

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "historical_hotspot": 0.35,
    "cochange_anomaly": 0.30,
    "test_gap": 0.25,
    "ownership": 0.10,
}

DEFAULT_THRESHOLDS = {
    "low": 0,
    "medium": 30,
    "high": 60,
    "critical": 80,
}


def load_scoring_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load scoring configuration from TOML file, falling back to defaults."""
    if config_path is None:
        # Default location: configs/weights.toml relative to workspace or package
        possible_paths = [
            Path("configs/weights.toml"),
            Path(__file__).resolve().parent.parent.parent / "configs" / "weights.toml",
        ]
        for p in possible_paths:
            if p.exists():
                config_path = p
                break

    if config_path and config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            weights = {
                "historical_hotspot": float(data.get("weights", {}).get("hotspot", 0.35)),
                "cochange_anomaly": float(data.get("weights", {}).get("cochange", 0.30)),
                "test_gap": float(data.get("weights", {}).get("testgap", 0.25)),
                "ownership": float(data.get("weights", {}).get("ownership", 0.10)),
            }
            thresholds = {
                "low": int(data.get("thresholds", {}).get("low", 0)),
                "medium": int(data.get("thresholds", {}).get("medium", 30)),
                "high": int(data.get("thresholds", {}).get("high", 60)),
                "critical": int(data.get("thresholds", {}).get("critical", 80)),
            }
            ci_gates = data.get("ci_gates", data.get("gates", {}))
            return {"weights": weights, "thresholds": thresholds, "ci_gates": ci_gates}
        except Exception as exc:
            logger.warning("Failed to load weights config from %s: %s", config_path, exc)

    return {
        "weights": DEFAULT_WEIGHTS.copy(),
        "thresholds": DEFAULT_THRESHOLDS.copy(),
        "ci_gates": {},
    }


def classify_risk(score: float, thresholds: dict[str, int] | None = None) -> RiskCategory:
    """Classify a 0–100 score into a RiskCategory."""
    th = thresholds or DEFAULT_THRESHOLDS
    if score >= th.get("critical", 80):
        return RiskCategory.CRITICAL
    if score >= th.get("high", 60):
        return RiskCategory.HIGH
    if score >= th.get("medium", 30):
        return RiskCategory.MEDIUM
    return RiskCategory.LOW


def compute_risk_score(
    signals: dict[str, SignalResult],
    weights: dict[str, float] | None = None,
    thresholds: dict[str, int] | None = None,
) -> tuple[float, RiskCategory, dict[str, float]]:
    """
    Compute normalized weighted score from available signals.

    If certain signals are marked unavailable (e.g. insufficient history),
    weights are re-proportioned across the remaining available signals.
    """
    w = (weights or DEFAULT_WEIGHTS).copy()

    available_signals = {k: s for k, s in signals.items() if s.is_available}

    if not available_signals:
        return 0.0, RiskCategory.LOW, {}

    # Sum of weights for available signals
    total_active_weight = sum(w.get(k, 0.0) for k in available_signals)
    if total_active_weight <= 0.0:
        total_active_weight = 1.0

    normalized_weights: dict[str, float] = {}
    weighted_sum = 0.0

    for k, s in available_signals.items():
        weight = w.get(k, 0.0) / total_active_weight
        normalized_weights[k] = round(weight, 3)
        weighted_sum += s.score * weight

    final_score = min(100.0, max(0.0, round(weighted_sum, 1)))
    category = classify_risk(final_score, thresholds)

    return final_score, category, normalized_weights


def build_analysis_result(
    signals: dict[str, SignalResult],
    base_ref: str,
    head_ref: str,
    total_files_changed: int,
    additions: int,
    deletions: int,
    data_quality: DataQuality = DataQuality.HIGH,
    custom_weights: dict[str, float] | None = None,
    custom_thresholds: dict[str, int] | None = None,
    why_flagged: list[str] | None = None,
    recommended_actions: RecommendedActions | None = None,
) -> AnalysisResult:
    """Assemble a complete AnalysisResult from signal outputs."""
    score, category, effective_weights = compute_risk_score(
        signals, weights=custom_weights, thresholds=custom_thresholds
    )

    # If why_flagged is not supplied, extract top findings from signals
    bullets = why_flagged or []
    if not bullets:
        # Sort signals by score descending
        sorted_signals = sorted(
            [s for s in signals.values() if s.is_available and s.score > 20.0],
            key=lambda s: s.score,
            reverse=True,
        )
        for s in sorted_signals:
            bullets.append(s.explanation)

        unavailable = [s for s in signals.values() if not s.is_available]
        for s in unavailable:
            bullets.append(f"{s.name.replace('_', ' ').title()}: {s.explanation}")

        if not bullets:
            if data_quality == DataQuality.LOW:
                bullets.append(
                    "Low repository history/quality available; "
                    "risk assessment has reduced confidence."
                )
            else:
                bullets.append("No elevated risk indicators detected in this change set.")

    actions = recommended_actions or RecommendedActions()
    if not actions.tests_to_run and "test_gap" in signals:
        tg = signals["test_gap"]
        for rec in tg.recommendations:
            actions.tests_to_run.append(rec)

    if not actions.suggested_reviewers and "ownership" in signals:
        own = signals["ownership"]
        for rec in own.recommendations:
            actions.suggested_reviewers.append(rec)

    if not actions.summary:
        if category in (RiskCategory.CRITICAL, RiskCategory.HIGH):
            actions.summary = (
                f"This pull request carries a {category.value.upper()} risk score ({score}/100). "
                "Careful review of fragile files and running suggested tests is recommended."
            )
        elif category == RiskCategory.MEDIUM:
            actions.summary = (
                f"This pull request has MEDIUM risk ({score}/100). "
                "Review the identified areas and ensure tests pass."
            )
        else:
            actions.summary = (
                f"This change has LOW risk ({score}/100) with minimal regression patterns."
            )

    return AnalysisResult(
        overall_score=score,
        risk_category=category,
        data_quality=data_quality,
        base_ref=base_ref,
        head_ref=head_ref,
        total_files_changed=total_files_changed,
        additions=additions,
        deletions=deletions,
        signals=signals,
        weights=effective_weights,
        why_flagged=bullets,
        recommended_actions=actions,
    )
