"""
config.py — Centralized production configuration and environment management.

Loads and validates settings from environment variables with sensible defaults:
- Server settings (HOST, PORT, WORKERS)
- Security & CORS (CORS_ORIGINS, ALLOWED_HOSTS)
- External API credentials (GITHUB_TOKEN, GEMINI_API_KEY)
- Storage & Scratch directories (STORAGE_PATH, SCRATCH_DIR)
- Logging & Observability (LOG_LEVEL, LOG_FORMAT)
- Production UI serving (SERVE_STATIC_UI)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    """Production application settings."""

    # Server settings
    host: str = field(default_factory=lambda: os.environ.get("RR_HOST", "0.0.0.0"))
    port: int = field(
        default_factory=lambda: int(os.environ.get("PORT", os.environ.get("RR_PORT", "8000")))
    )

    # Security & CORS
    cors_origins: list[str] = field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.environ.get(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
            ).split(",")
            if origin.strip()
        ]
    )

    # API Keys & Secrets
    github_token: str | None = field(
        default_factory=lambda: os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY")
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper()
    )
    log_format: str = field(
        default_factory=lambda: os.environ.get("LOG_FORMAT", "text").lower()  # "text" | "json"
    )

    # Storage & Persistence
    storage_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("STORAGE_PATH", os.environ.get("RR_STORAGE_PATH", "data"))
        )
    )

    # Static UI Serving
    serve_static_ui: bool = field(
        default_factory=lambda: os.environ.get("SERVE_STATIC_UI", "true").lower()
        in ("1", "true", "yes")
    )

    # Scoring configuration path override
    weights_config: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["WEIGHTS_CONFIG"]) if "WEIGHTS_CONFIG" in os.environ else None
        )
    )

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token)

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key)


# Global singleton settings instance
settings = Settings()
