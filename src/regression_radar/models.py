"""
models.py — Core data contracts and schemas for Regression Radar.

Follows DECISIONS.md D-002: Pydantic v2 models for all contracts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from regression_radar.git_history import DataQuality


class RiskCategory(StrEnum):
    LOW = "low"  # 0–29
    MEDIUM = "medium"  # 30–59
    HIGH = "high"  # 60–79
    CRITICAL = "critical"  # 80–100


class SignalResult(BaseModel):
    """Structured output from an individual analysis signal."""

    name: str = Field(description="Signal identifier (e.g. historical_hotspot)")
    score: float = Field(ge=0.0, le=100.0, description="Risk-prioritisation score (0–100)")
    explanation: str = Field(description="Clear human-readable justification for the score")
    data_quality: DataQuality = Field(default=DataQuality.HIGH)
    is_available: bool = Field(
        default=True, description="False if data was unavailable/insufficient"
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Structured metrics and data points"
    )
    recommendations: list[str] = Field(default_factory=list, description="Actionable suggestions")


class FileHotspotEvidence(BaseModel):
    path: str
    total_commits: int
    bugfix_commits: int
    bugfix_ratio: float
    risk_score: float
    bugfix_shas: list[str] = Field(default_factory=list)


class CochangeRule(BaseModel):
    file_a: str
    file_b: str
    support: int  # Number of commits where both changed
    confidence: float  # support / total_commits(file_a)
    common_commits: list[str] = Field(default_factory=list)


class TestGapEvidence(BaseModel):
    source_file: str
    matched_test_file: str | None = None
    test_modified_in_pr: bool = False
    match_strategy: str = "none"  # "name_convention", "cochange", or "none"


class ContributorStats(BaseModel):
    author_name: str
    author_email: str
    commit_count: int
    recent_commit_count: int
    last_commit_date: str
    recency_score: float


class RecommendedActions(BaseModel):
    tests_to_run: list[str] = Field(default_factory=list)
    suggested_reviewers: list[str] = Field(default_factory=list)
    summary: str = ""


class AnalysisResult(BaseModel):
    """Overall PR analysis and risk assessment."""

    overall_score: float = Field(ge=0.0, le=100.0)
    risk_category: RiskCategory
    data_quality: DataQuality
    base_ref: str
    head_ref: str
    total_files_changed: int
    additions: int
    deletions: int
    signals: dict[str, SignalResult] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    why_flagged: list[str] = Field(default_factory=list)
    recommended_actions: RecommendedActions = Field(default_factory=RecommendedActions)
