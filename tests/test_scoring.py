"""
tests/test_scoring.py — Unit tests for scoring.py and recommendations.py
"""

from __future__ import annotations

from regression_radar.git_history import DataQuality
from regression_radar.models import RiskCategory, SignalResult
from regression_radar.recommendations import build_recommendations
from regression_radar.scoring import (
    build_analysis_result,
    classify_risk,
    compute_risk_score,
)


def _make_signal(name: str, score: float, available: bool = True) -> SignalResult:
    return SignalResult(
        name=name,
        score=score,
        explanation=f"Signal {name} scored {score}",
        data_quality=DataQuality.HIGH,
        is_available=available,
    )


class TestScoringEngine:
    def test_classify_risk_thresholds(self) -> None:
        assert classify_risk(15.0) == RiskCategory.LOW
        assert classify_risk(29.9) == RiskCategory.LOW
        assert classify_risk(30.0) == RiskCategory.MEDIUM
        assert classify_risk(59.9) == RiskCategory.MEDIUM
        assert classify_risk(60.0) == RiskCategory.HIGH
        assert classify_risk(79.9) == RiskCategory.HIGH
        assert classify_risk(80.0) == RiskCategory.CRITICAL
        assert classify_risk(100.0) == RiskCategory.CRITICAL

    def test_compute_risk_score_weighted_sum(self) -> None:
        signals = {
            "historical_hotspot": _make_signal("historical_hotspot", 80.0),
            "cochange_anomaly": _make_signal("cochange_anomaly", 50.0),
            "test_gap": _make_signal("test_gap", 40.0),
            "ownership": _make_signal("ownership", 20.0),
        }
        weights = {
            "historical_hotspot": 0.35,
            "cochange_anomaly": 0.30,
            "test_gap": 0.25,
            "ownership": 0.10,
        }
        # Expected: 80*0.35 + 50*0.30 + 40*0.25 + 20*0.10 = 28 + 15 + 10 + 2 = 55.0
        score, category, norm_w = compute_risk_score(signals, weights)
        assert score == 55.0
        assert category == RiskCategory.MEDIUM
        assert norm_w["historical_hotspot"] == 0.35

    def test_unavailable_signal_reweights_proportionately(self) -> None:
        # If test_gap is unavailable, remaining weights should re-normalize to 1.0
        signals = {
            "historical_hotspot": _make_signal("historical_hotspot", 100.0),
            "cochange_anomaly": _make_signal("cochange_anomaly", 100.0),
            "test_gap": _make_signal("test_gap", 0.0, available=False),
        }
        weights = {
            "historical_hotspot": 0.50,
            "cochange_anomaly": 0.50,
            "test_gap": 0.25,
        }
        score, category, norm_w = compute_risk_score(signals, weights)
        assert score == 100.0
        assert category == RiskCategory.CRITICAL
        assert "test_gap" not in norm_w
        assert round(norm_w["historical_hotspot"] + norm_w["cochange_anomaly"], 2) == 1.0

    def test_all_unavailable_signals_return_zero(self) -> None:
        signals = {
            "historical_hotspot": _make_signal("historical_hotspot", 50.0, available=False),
        }
        score, category, _ = compute_risk_score(signals)
        assert score == 0.0
        assert category == RiskCategory.LOW

    def test_build_analysis_result(self) -> None:
        signals = {
            "historical_hotspot": _make_signal("historical_hotspot", 75.0),
        }
        res = build_analysis_result(
            signals=signals,
            base_ref="main",
            head_ref="feature-1",
            total_files_changed=2,
            additions=10,
            deletions=5,
        )
        assert res.overall_score == 75.0
        assert res.risk_category == RiskCategory.HIGH
        assert len(res.why_flagged) > 0


class TestRecommendations:
    def test_build_recommendations_summary(self) -> None:
        signals = {
            "test_gap": SignalResult(
                name="test_gap",
                score=60.0,
                explanation="Missing test file",
                evidence={"files": [{"source_file": "app.py", "matched_test_file": None}]},
            ),
        }
        actions = build_recommendations(signals, 65.0, RiskCategory.HIGH)
        assert len(actions.tests_to_run) >= 1
        assert "app.py" in actions.tests_to_run[0]
        assert "elevated risk score" in actions.summary.lower()
