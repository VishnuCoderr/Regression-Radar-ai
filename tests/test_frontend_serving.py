"""
test_frontend_serving.py — Tests for production frontend serving and SPA fallback routing.

Verifies:
- GET / serves index.html (React frontend entrypoint)
- GET /assets/... static mounting and assets presence
- SPA client-side fallback routes (/dashboard, /history, /analysis/123) return index.html
- Unknown API and health routes return HTTP 404 JSON (not HTML fallback)
- Direct static assets (favicon.svg, icons.svg) serve appropriate files
- Directory traversal attacks are prevented
- Health and readiness endpoints remain functional
- resolve_project_root and resolve_ui_dist resolution logic across environments
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.routing import Mount, Route

from regression_radar import __version__
from regression_radar.api import (
    app,
    health_check,
    readiness_check,
    resolve_project_root,
    resolve_ui_dist,
    serve_root,
    serve_spa,
)


class TestFrontendPathResolution:
    """Test environment-based and filesystem path resolution."""

    def test_resolve_project_root_default(self) -> None:
        root = resolve_project_root()
        assert root.is_dir()
        assert (root / "configs").is_dir() or (root / "src").is_dir()

    def test_resolve_project_root_env_override(self, tmp_path: Path) -> None:
        fake_root = tmp_path / "fake-root"
        fake_root.mkdir()
        with patch.dict("os.environ", {"RR_PROJECT_ROOT": str(fake_root)}):
            assert resolve_project_root() == fake_root

    def test_resolve_ui_dist_default(self) -> None:
        dist = resolve_ui_dist()
        assert dist is not None
        assert dist.is_dir()
        assert (dist / "index.html").is_file()

    def test_resolve_ui_dist_env_override(self, tmp_path: Path) -> None:
        custom_dist = tmp_path / "custom-dist"
        custom_dist.mkdir()
        index = custom_dist / "index.html"
        index.write_text("<!doctype html><html>Custom</html>", encoding="utf-8")
        with patch.dict("os.environ", {"UI_DIST_PATH": str(custom_dist)}):
            assert resolve_ui_dist() == custom_dist


class TestFrontendRouteServing:
    """Test root and SPA route serving behavior."""

    def test_serve_root_returns_index_html(self) -> None:
        response = serve_root()
        assert isinstance(response, FileResponse)
        assert Path(response.path).name == "index.html"
        assert response.status_code == 200

        content = Path(response.path).read_text(encoding="utf-8")
        assert "<!doctype html>" in content.lower()
        assert 'id="root"' in content

    def test_serve_spa_client_routes_fallback_to_index(self) -> None:
        for client_route in ["dashboard", "history", "pr/123", "repos/analysis/detail"]:
            response = serve_spa(client_route)
            assert isinstance(response, FileResponse)
            assert Path(response.path).name == "index.html"
            assert response.status_code == 200

    def test_serve_spa_direct_static_assets(self) -> None:
        dist = resolve_ui_dist()
        assert dist is not None

        if (dist / "favicon.svg").is_file():
            response = serve_spa("favicon.svg")
            assert isinstance(response, FileResponse)
            assert Path(response.path).name == "favicon.svg"

        if (dist / "icons.svg").is_file():
            response = serve_spa("icons.svg")
            assert isinstance(response, FileResponse)
            assert Path(response.path).name == "icons.svg"

    def test_serve_spa_api_routes_raise_404(self) -> None:
        """API routes must NOT be swallowed by the SPA fallback."""
        for api_route in ["api", "api/", "api/unknown", "api/v1/invalid", "api/v1/demo/unknown"]:
            with pytest.raises(HTTPException) as exc_info:
                serve_spa(api_route)
            assert exc_info.value.status_code == 404
            assert "API route not found" in exc_info.value.detail

    def test_serve_spa_health_routes_raise_404(self) -> None:
        """Unknown health subroutes must NOT return index.html."""
        for health_route in ["health/unknown", "health/probe/99"]:
            with pytest.raises(HTTPException) as exc_info:
                serve_spa(health_route)
            assert exc_info.value.status_code == 404
            assert "API route not found" in exc_info.value.detail

    def test_serve_spa_path_traversal_protection(self) -> None:
        """Path traversal attempts should fallback safely to index.html or raise 404, never leak."""
        response = serve_spa("../../../etc/passwd")
        assert isinstance(response, FileResponse)
        assert Path(response.path).name == "index.html"


class TestAppRouteRegistration:
    """Verify route registration on the FastAPI app instance."""

    def test_routes_include_root_and_spa(self) -> None:
        route_paths = [r.path for r in app.routes if isinstance(r, Route)]
        assert "/" in route_paths
        assert "/{full_path:path}" in route_paths

    def test_assets_mount_exists(self) -> None:
        mounts = [r for r in app.routes if isinstance(r, Mount)]
        asset_mounts = [m for m in mounts if m.path == "/assets"]
        assert len(asset_mounts) == 1

        dist = resolve_ui_dist()
        assert dist is not None
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            files = list(assets_dir.glob("*.js")) + list(assets_dir.glob("*.css"))
            assert len(files) > 0, "Expected compiled JS/CSS in assets directory"


class TestHealthEndpointsParity:
    """Ensure existing health checks remain untouched and working."""

    def test_health_live(self) -> None:
        res = health_check()
        assert res.status == "healthy"
        assert res.version == __version__

    def test_readiness_probe(self) -> None:
        res = readiness_check()
        assert res.status == "ready"
        assert res.git_available is True
        assert res.storage_writable is True
