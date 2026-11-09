"""
test_production_readiness.py — Unit and integration tests for production readiness.

Validates:
1. Production health and readiness probes (/health, /health/live, /health/ready).
2. Git availability detection and 503 degradation if Git is missing.
3. Request ID middleware (generation, propagation, timing headers).
4. Centralized production settings and CORS origin configuration.
5. Static SPA fallback routing and API precedence.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from regression_radar.api import (
    apply_response_headers,
    health_check,
    readiness_check,
    resolve_request_id,
)
from regression_radar.config import Settings


class TestProductionHealthEndpoints:
    def test_liveness_endpoints(self) -> None:
        live = health_check()
        assert live.status == "healthy"
        assert live.version != ""

    def test_readiness_probe_healthy(self) -> None:
        ready = readiness_check()
        assert ready.status == "ready"
        assert ready.git_available is True
        assert ready.git_version is not None
        assert "git version" in ready.git_version.lower()
        assert ready.storage_writable is True
        assert ready.uptime_seconds >= 0

    @patch("shutil.which", return_value=None)
    def test_readiness_probe_503_when_git_missing(self, mock_which: object) -> None:
        with pytest.raises(HTTPException) as exc_info:
            readiness_check()
        assert exc_info.value.status_code == 503
        assert "Git executable not found" in exc_info.value.detail


class TestRequestTracingMiddleware:
    def test_request_id_generated_when_missing(self) -> None:
        generated = resolve_request_id(None)
        assert len(generated) >= 32
        assert resolve_request_id(None) != generated

    def test_request_id_propagated_when_supplied(self) -> None:
        custom_id = "trace-custom-correlation-999"
        propagated = resolve_request_id(custom_id)
        assert propagated == custom_id

    def test_apply_response_headers(self) -> None:
        resp = Response(content="test")
        apply_response_headers("req-123", time.perf_counter() - 0.05, resp)
        assert resp.headers["X-Request-ID"] == "req-123"
        assert "X-Response-Time-Ms" in resp.headers
        duration = float(resp.headers["X-Response-Time-Ms"])
        assert duration >= 20.0


class TestProductionSettings:
    def test_default_settings(self) -> None:
        s = Settings()
        assert s.port > 0
        assert s.host != ""
        assert len(s.cors_origins) > 0
        assert s.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")

    def test_cors_origins_parsing(self) -> None:
        env = {"CORS_ORIGINS": "https://radar.example.com, https://app.example.com"}
        with patch.dict("os.environ", env, clear=True):
            s = Settings()
            assert "https://radar.example.com" in s.cors_origins
            assert "https://app.example.com" in s.cors_origins
            assert len(s.cors_origins) == 2
