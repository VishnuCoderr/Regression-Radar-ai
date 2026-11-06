"""
tests/test_report.py — Unit tests for report.py
"""

from __future__ import annotations

import json

from regression_radar.git_history import DataQuality
from regression_radar.models import (
    AnalysisResult,
    RecommendedActions,
    RiskCategory,
    SignalResult,
)
from regression_radar.report import format_json_report, format_markdown_report


def _make_dummy_result(score: float, category: RiskCategory) -> AnalysisResult:
    return AnalysisResult(
        overall_score=score,
        risk_category=category,
        data_quality=DataQuality.HIGH,
        base_ref="main",
        head_ref="feature",
        total_files_changed=3,
        additions=45,
        deletions=12,
        signals={
            "historical_hotspot": SignalResult(
                name="historical_hotspot",
                score=78.0,
                explanation="payments.ts is a historical hotspot (5 bug fixes, 2 reverts).",
                is_available=True,
            ),
        },
        weights={"historical_hotspot": 1.0},
        why_flagged=[
            "payments.ts is a historical hotspot (5 bug fixes, 2 reverts).",
            "Typically changes with payments.test.ts which is not modified in this PR.",
        ],
        recommended_actions=RecommendedActions(
            tests_to_run=["PaymentIntegrationTest", "RefundFlowTest"],
            suggested_reviewers=["@ananya (payments module expert)"],
            summary="This change modifies payment logic, an area with a history of regressions.",
        ),
    )


class TestReportFormatting:
    def test_markdown_format_structure(self) -> None:
        res = _make_dummy_result(78.0, RiskCategory.HIGH)
        md = format_markdown_report(res)
        assert "Regression Risk: High (78 / 100)" in md
        assert "**Why was this flagged?**" in md
        assert "payments.ts is a historical hotspot" in md
        assert "**Recommended Actions**" in md
        assert "**Run:** PaymentIntegrationTest, RefundFlowTest" in md
        assert "**Suggested Reviewer:** @ananya" in md
        assert "Detailed Signal Breakdown" in md

    def test_json_format_validity(self) -> None:
        res = _make_dummy_result(45.0, RiskCategory.MEDIUM)
        raw_json = format_json_report(res)
        parsed = json.loads(raw_json)
        assert parsed["overall_score"] == 45.0
        assert parsed["risk_category"] == "medium"
        assert parsed["total_files_changed"] == 3
        assert "historical_hotspot" in parsed["signals"]
