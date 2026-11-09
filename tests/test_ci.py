"""
test_ci.py — Comprehensive tests for CI/CD automation, gate evaluation, and PR comment bot.

Validates:
1. CI Gate threshold evaluation across low, medium, and high-risk outcomes.
2. Blocking vs non-blocking gate enforcement.
3. Test-gap remediation requirements.
4. PR comment formatting, sticky marker, and remediation checklist.
5. GitHub Actions event payload parsing and fallback handling.
6. PR comment creation vs updating (duplicate prevention via PATCH).
7. Missing secrets, API error handling, and token security.
8. CLI command execution and exit code behavior under gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from regression_radar.ci import (
    PR_COMMENT_MARKER,
    CIGateConfig,
    evaluate_ci_gates,
    find_bot_comment,
    format_ci_comment,
    load_ci_gate_config,
    parse_github_actions_context,
    post_or_update_pr_comment,
)
from regression_radar.cli import app
from regression_radar.git_history import DataQuality
from regression_radar.models import (
    AnalysisResult,
    RecommendedActions,
    RiskCategory,
    SignalResult,
)
from tests.conftest import GitRepoFixture


def _make_dummy_result(
    score: float,
    category: RiskCategory = RiskCategory.MEDIUM,
    test_gap_score: float = 0.0,
    why_flagged: list[str] | None = None,
) -> AnalysisResult:
    """Helper to construct an AnalysisResult for gate and report testing."""
    signals = {
        "historical_hotspot": SignalResult(
            name="historical_hotspot",
            score=score,
            explanation="Hotspot test explanation",
            is_available=True,
        ),
        "cochange_anomaly": SignalResult(
            name="cochange_anomaly",
            score=0.0,
            explanation="Co-change test explanation",
            is_available=True,
        ),
        "test_gap": SignalResult(
            name="test_gap",
            score=test_gap_score,
            explanation="Test gap explanation",
            is_available=True,
            evidence={
                "files": [
                    {"source": "src/app.py", "test_modified_in_pr": test_gap_score == 0}
                ]
            },
        ),
        "ownership": SignalResult(
            name="ownership",
            score=0.0,
            explanation="Ownership explanation",
            is_available=True,
        ),
    }
    return AnalysisResult(
        overall_score=score,
        risk_category=category,
        data_quality=DataQuality.HIGH,
        base_ref="main",
        head_ref="feature/test",
        total_files_changed=2,
        additions=20,
        deletions=5,
        signals=signals,
        weights={
            "historical_hotspot": 0.35,
            "cochange_anomaly": 0.30,
            "test_gap": 0.25,
            "ownership": 0.10,
        },
        why_flagged=why_flagged or ["High bug-fix frequency in modified file"],
        recommended_actions=RecommendedActions(
            tests_to_run=["pytest tests/test_app.py"],
            suggested_reviewers=["alice@example.com"],
            summary="Review carefully before merge.",
        ),
    )


class TestCIGates:
    def test_low_risk_passes_gate(self) -> None:
        result = _make_dummy_result(score=22.0, category=RiskCategory.LOW)
        config = CIGateConfig(max_risk_score=60.0, blocking=True)
        evaluation = evaluate_ci_gates(result, config)

        assert evaluation.passed is True
        assert evaluation.gate_failed is False
        assert evaluation.status_label == "PASSED"
        assert "within allowed threshold" in evaluation.reasons[0]

    def test_high_risk_fails_gate_non_blocking_default(self) -> None:
        result = _make_dummy_result(score=68.0, category=RiskCategory.HIGH)
        # Default non-blocking mode: gate fails check, but passed is True so CI does not abort
        config = CIGateConfig(max_risk_score=60.0, blocking=False)
        evaluation = evaluate_ci_gates(result, config)

        assert evaluation.gate_failed is True
        assert evaluation.passed is True  # Non-blocking passes execution
        assert evaluation.status_label == "WARNING (NON-BLOCKING)"
        assert "meets or exceeds configured gate threshold" in evaluation.reasons[0]

    def test_high_risk_fails_gate_blocking_mode(self) -> None:
        result = _make_dummy_result(score=75.0, category=RiskCategory.HIGH)
        config = CIGateConfig(max_risk_score=60.0, blocking=True)
        evaluation = evaluate_ci_gates(result, config)

        assert evaluation.gate_failed is True
        assert evaluation.passed is False  # Blocking fails execution
        assert evaluation.status_label == "FAILED (BLOCKING)"

    def test_test_gap_remediation_gate(self) -> None:
        # Case 1: unaddressed test gap
        result_with_gap = _make_dummy_result(score=40.0, test_gap_score=80.0)
        config_req_tests = CIGateConfig(require_test_coverage=True, blocking=True)
        eval_with_gap = evaluate_ci_gates(result_with_gap, config_req_tests)
        assert eval_with_gap.gate_failed is True
        assert eval_with_gap.passed is False
        assert any("Test gap gate failed" in r for r in eval_with_gap.reasons)

        # Case 2: no test gap
        result_no_gap = _make_dummy_result(score=40.0, test_gap_score=0.0)
        eval_no_gap = evaluate_ci_gates(result_no_gap, config_req_tests)
        assert eval_no_gap.gate_failed is False
        assert eval_no_gap.passed is True

    def test_scoring_weights_and_thresholds_untouched(self) -> None:
        result = _make_dummy_result(score=55.0)
        orig_weights = dict(result.weights)
        config = CIGateConfig(max_risk_score=50.0, blocking=True)
        evaluate_ci_gates(result, config)
        assert result.weights == orig_weights
        assert result.overall_score == 55.0

    def test_load_ci_gate_config_overrides(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "test_config.toml"
        cfg_file.write_text(
            """
[ci_gates]
max_risk_score = 50.0
require_test_coverage = true
blocking = true
""",
            encoding="utf-8",
        )
        loaded = load_ci_gate_config(cfg_file)
        assert loaded.max_risk_score == 50.0
        assert loaded.require_test_coverage is True
        assert loaded.blocking is True

        # Override via CLI flag arguments
        overridden = load_ci_gate_config(cfg_file, max_risk=70.0, blocking=False)
        assert overridden.max_risk_score == 70.0
        assert overridden.blocking is False


class TestPRCommentBot:
    def test_format_ci_comment_structure(self) -> None:
        result = _make_dummy_result(score=65.0, category=RiskCategory.HIGH)
        gate = evaluate_ci_gates(result, CIGateConfig(max_risk_score=60.0, blocking=False))
        comment = format_ci_comment(result, gate)

        # 1. Contains sticky marker
        assert comment.startswith(PR_COMMENT_MARKER)

        # 2. Risk classification and score
        assert "Regression Risk: High (65 / 100)" in comment

        # 3. CI Gate banner
        assert "CI Gate Status:" in comment
        assert "Warning (Non-blocking)" in comment

        # 4. Sections
        assert "**Why was this flagged?**" in comment
        assert "**Recommended Actions**" in comment
        assert "**Remediation Checklist**" in comment
        assert "<details>" in comment
        assert "<summary><b>📊 Detailed Signal Breakdown</b></summary>" in comment
        assert "| Historical Hotspot |" in comment

    def test_find_bot_comment_locates_marker(self) -> None:
        comments = [
            {"id": 1, "body": "LGTM!"},
            {"id": 2, "body": f"{PR_COMMENT_MARKER}\n### Old Report"},
            {"id": 3, "body": "Please add tests."},
        ]
        bot_comment = find_bot_comment(comments)
        assert bot_comment is not None
        assert bot_comment["id"] == 2

    def test_find_bot_comment_returns_none_when_absent(self) -> None:
        comments = [{"id": 10, "body": "Hello world"}]
        assert find_bot_comment(comments) is None

    @patch("regression_radar.ci.get_pr_comments")
    @patch("urllib.request.urlopen")
    def test_post_or_update_pr_comment_creates_new_when_absent(
        self, mock_urlopen: MagicMock, mock_list_comments: MagicMock
    ) -> None:
        mock_list_comments.return_value = [{"id": 1, "body": "Nice code"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": 100, "html_url": "https://github.com/..."}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = post_or_update_pr_comment(
            owner="acme",
            repo="widgets",
            pr_number=42,
            body=f"{PR_COMMENT_MARKER}\nNew Report",
            token="ghp_dummy_token",
        )

        assert res["status"] == "created"
        assert res["comment_id"] == 100

        # Verify request method was POST
        sent_req = mock_urlopen.call_args[0][0]
        assert sent_req.method == "POST"
        assert "/issues/42/comments" in sent_req.full_url

    @patch("regression_radar.ci.get_pr_comments")
    @patch("urllib.request.urlopen")
    def test_post_or_update_pr_comment_updates_via_patch_preventing_duplicate(
        self, mock_urlopen: MagicMock, mock_list_comments: MagicMock
    ) -> None:
        # Existing comment with marker
        mock_list_comments.return_value = [
            {"id": 200, "body": f"{PR_COMMENT_MARKER}\nPrevious report"},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": 200, "html_url": "https://github.com/..."}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = post_or_update_pr_comment(
            owner="acme",
            repo="widgets",
            pr_number=42,
            body=f"{PR_COMMENT_MARKER}\nUpdated Report",
            token="ghp_dummy_token",
        )

        assert res["status"] == "updated"
        assert res["comment_id"] == 200

        # Verify request method was PATCH to the existing comment ID
        sent_req = mock_urlopen.call_args[0][0]
        assert sent_req.method == "PATCH"
        assert "/issues/comments/200" in sent_req.full_url

    def test_post_comment_skips_cleanly_without_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            res = post_or_update_pr_comment(
                owner="acme", repo="widgets", pr_number=1, body="Report", token=None
            )
            assert res["status"] == "skipped"
            assert "No GITHUB_TOKEN" in res["reason"]


class TestGitHubActionsContext:
    def test_parse_from_event_payload_json(self, tmp_path: Path) -> None:
        payload = {
            "number": 88,
            "pull_request": {
                "number": 88,
                "base": {"ref": "main"},
                "head": {"ref": "feature/payment"},
            },
            "repository": {
                "full_name": "octocat/hello-world",
            },
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(payload), encoding="utf-8")

        ctx = parse_github_actions_context(event_file)
        assert ctx["pr_number"] == 88
        assert ctx["owner"] == "octocat"
        assert ctx["repo"] == "hello-world"
        assert ctx["base_ref"] == "main"
        assert ctx["head_ref"] == "feature/payment"

    def test_parse_fallback_to_env_vars(self) -> None:
        env = {
            "GITHUB_REPOSITORY": "testorg/testrepo",
            "GITHUB_BASE_REF": "main",
            "GITHUB_HEAD_REF": "dev-branch",
        }
        with patch.dict("os.environ", env, clear=True):
            ctx = parse_github_actions_context(event_path=None)
            assert ctx["owner"] == "testorg"
            assert ctx["repo"] == "testrepo"
            assert ctx["base_ref"] == "main"
            assert ctx["head_ref"] == "dev-branch"


class TestCLICIRunner:
    def test_cli_ci_executes_and_passes(
        self, git_repo_with_history: GitRepoFixture, tmp_path: Path
    ) -> None:
        git_repo_with_history.branch("feature/ci-test-branch", checkout=True)
        git_repo_with_history.write("src/app.py", "def main(): return 'ci-test'\n")
        git_repo_with_history.commit("feat: update app for ci test")

        report_out = tmp_path / "ci_report.md"

        # Run ci command via runner
        from typer.testing import CliRunner

        runner = CliRunner()
        res = runner.invoke(
            app,
            [
                "ci",
                "--repo",
                str(git_repo_with_history.path),
                "--base",
                "main",
                "--head",
                "HEAD",
                "--max-risk",
                "90",
                "--non-blocking",
                "--no-post-comment",
                "--output",
                str(report_out),
            ],
        )

        assert res.exit_code == 0
        assert report_out.exists()
        content = report_out.read_text(encoding="utf-8")
        assert PR_COMMENT_MARKER in content
        assert "Regression Risk:" in content

    def test_cli_ci_blocks_on_strict_gate_failure(
        self, git_repo_with_history: GitRepoFixture
    ) -> None:
        git_repo_with_history.branch("feature/ci-fail-branch", checkout=True)
        git_repo_with_history.write("src/app.py", "def main(): return 'risk'\n")
        git_repo_with_history.commit("fix: bug in app")

        from typer.testing import CliRunner

        runner = CliRunner()
        # Set max_risk to 0 so any risk score >= 0 triggers gate failure with blocking mode
        res = runner.invoke(
            app,
            [
                "ci",
                "--repo",
                str(git_repo_with_history.path),
                "--base",
                "main",
                "--head",
                "HEAD",
                "--max-risk",
                "0",
                "--blocking",
                "--no-post-comment",
            ],
        )

        assert res.exit_code == 1
        assert "GATE BLOCKED" in res.output or "CI Gate Failed" in res.output
