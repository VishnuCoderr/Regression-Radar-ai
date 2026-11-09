"""
tests/test_cli.py — Comprehensive tests for the Typer CLI application.

Verifies:
- Command registration and --help diagnostics
- Identical behaviour between 'analyse' and 'analyze' (US English alias)
- Server launcher command ('serve') with configurable host, port, reload, and error handling
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from regression_radar import __version__
from regression_radar.cli import app
from regression_radar.config import settings

runner = CliRunner()


def _init_test_git_repo(repo_dir: Path) -> None:
    """Helper to initialize a minimal git repository with two commits."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test Dev"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@example.com"], cwd=str(repo_dir), check=True
    )

    f1 = repo_dir / "service.py"
    f1.write_text("def run(): return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "feat: initial commit"], cwd=str(repo_dir), check=True)

    f1.write_text("def run(): return 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: resolve return bug"], cwd=str(repo_dir), check=True
    )


class TestCLIBasics:
    """Basic command tests."""

    def test_version_command(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert f"v{__version__}" in result.output

    def test_app_help_lists_all_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "analyse" in result.output
        assert "analyze" in result.output
        assert "serve" in result.output
        assert "inspect" in result.output
        assert "ci" in result.output


class TestAnalyzeAliasParity:
    """Verify that 'analyse' and 'analyze' behave 100% identically."""

    def test_analyze_help_matches_analyse_help(self) -> None:
        res_analyse = runner.invoke(app, ["analyse", "--help"])
        res_analyze = runner.invoke(app, ["analyze", "--help"])

        assert res_analyse.exit_code == 0
        assert res_analyze.exit_code == 0

        # Both commands must document the same essential options
        options_to_check = [
            "--base",
            "--head",
            "--format",
            "--output",
            "--config",
            "--author",
            "--max-risk",
            "--blocking",
        ]
        for opt in options_to_check:
            assert opt in res_analyse.output
            assert opt in res_analyze.output

    def test_analyze_and_analyse_produce_identical_json_results(self, tmp_path: Path) -> None:
        repo = tmp_path / "test_repo"
        _init_test_git_repo(repo)

        # Run with 'analyse'
        res_british = runner.invoke(
            app,
            ["analyse", str(repo), "--base", "HEAD~1", "--format", "json"],
        )
        assert res_british.exit_code == 0

        # Run with 'analyze'
        res_american = runner.invoke(
            app,
            ["analyze", str(repo), "--base", "HEAD~1", "--format", "json"],
        )
        assert res_american.exit_code == 0

        # Parse outputs and compare score and structure
        import json
        data_british = json.loads(res_british.output)
        data_american = json.loads(res_american.output)

        assert data_british["overall_score"] == data_american["overall_score"]
        assert data_british["risk_category"] == data_american["risk_category"]
        assert data_british["total_files_changed"] == data_american["total_files_changed"]


class TestServeCommand:
    """Verify 'rr serve' command options and server startup."""

    def test_serve_help(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--reload" in result.output

    @patch("uvicorn.run")
    def test_serve_defaults_use_centralized_settings(self, mock_uvicorn_run) -> None:
        result = runner.invoke(app, ["serve"])
        assert result.exit_code == 0
        mock_uvicorn_run.assert_called_once_with(
            "regression_radar.api:app",
            host=settings.host,
            port=settings.port,
            reload=False,
            log_level="info",
        )

    @patch("uvicorn.run")
    def test_serve_custom_host_port_and_reload(self, mock_uvicorn_run) -> None:
        result = runner.invoke(
            app,
            ["serve", "--host", "127.0.0.1", "--port", "9090", "--reload", "--verbose"],
        )
        assert result.exit_code == 0
        mock_uvicorn_run.assert_called_once_with(
            "regression_radar.api:app",
            host="127.0.0.1",
            port=9090,
            reload=True,
            log_level="debug",
        )

    def test_serve_missing_uvicorn_handles_import_error(self) -> None:
        with patch.dict("sys.modules", {"uvicorn": None}):
            result = runner.invoke(app, ["serve"])
            assert result.exit_code == 1
            assert "uvicorn is not installed" in result.output
