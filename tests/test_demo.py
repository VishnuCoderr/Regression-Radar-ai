"""
tests/test_demo.py — Tests for pre-configured demo scenarios and 1-click evaluation endpoints.

Verifies:
- GET /api/v1/demo/scenarios returns available scenarios
- POST /api/v1/demo/run executes the high-risk payment scenario and yields HIGH risk
- POST /api/v1/demo/run executes the safe-pr scenario and yields LOW risk
- POST /api/v1/demo/run rejects unknown scenario IDs with HTTP 404
"""

from __future__ import annotations

import pytest
from fastapi.exceptions import HTTPException

from regression_radar.api import DemoRunRequest, list_demo_scenarios, run_demo_scenario


class TestDemoScenarios:
    """Test demo scenario listing and direct execution."""

    def test_list_demo_scenarios(self) -> None:
        scenarios = list_demo_scenarios()
        assert len(scenarios) >= 3
        ids = [s.id for s in scenarios]
        assert "high-risk-payment" in ids
        assert "safe-pr" in ids
        assert "sample-github-pr" in ids

    def test_run_high_risk_demo_scenario(self) -> None:
        req = DemoRunRequest(scenario_id="high-risk-payment")
        result = run_demo_scenario(req)

        assert result.risk_category.value == "high"
        assert 55.0 <= result.overall_score <= 65.0
        assert "payments/transaction.py" in result.signals["historical_hotspot"].explanation

    def test_run_safe_demo_scenario(self) -> None:
        req = DemoRunRequest(scenario_id="safe-pr")
        result = run_demo_scenario(req)

        assert result.risk_category.value == "low"
        assert result.overall_score < 30.0

    def test_run_unknown_demo_scenario_raises_404(self) -> None:
        req = DemoRunRequest(scenario_id="non-existent-scenario")
        with pytest.raises(HTTPException) as exc_info:
            run_demo_scenario(req)
        assert exc_info.value.status_code == 404
        assert "Unknown demo scenario" in exc_info.value.detail
