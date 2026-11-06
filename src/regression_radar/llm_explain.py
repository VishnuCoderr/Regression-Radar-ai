"""
llm_explain.py — Optional AI explanation layer.

Enriches PR comments with natural-language executive summaries using the Gemini API.
Safety constraints (per AGENTS.md):
- Never sends source code or secrets to external APIs (only structured findings).
- Cannot modify the risk score or invent evidence.
- Provides a 100% functional fallback when GEMINI_API_KEY is not configured.
"""

from __future__ import annotations

import logging
import os

from regression_radar.models import AnalysisResult, RecommendedActions

logger = logging.getLogger(__name__)


def generate_ai_explanation(
    result: AnalysisResult,
    api_key: str | None = None,
) -> RecommendedActions:
    """Generate an enhanced executive summary using Gemini if configured."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        logger.debug("GEMINI_API_KEY not set; using deterministic recommendations.")
        return result.recommended_actions

    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Prepare ONLY structured metadata (NEVER source code)
        prompt_payload = {
            "score": result.overall_score,
            "category": result.risk_category.value,
            "changed_files_count": result.total_files_changed,
            "why_flagged": result.why_flagged,
            "signals": {
                k: {"score": s.score, "explanation": s.explanation}
                for k, s in result.signals.items()
                if s.is_available
            },
            "current_tests_to_run": result.recommended_actions.tests_to_run,
            "current_reviewers": result.recommended_actions.suggested_reviewers,
        }

        prompt = (
            "You are the AI explanation engine for Regression Radar, a PR risk analyzer.\n"
            "Analyze the structured PR risk findings and provide a concise executive summary.\n\n"
            "CONSTRAINTS:\n"
            "1. Do NOT alter the risk score or category.\n"
            "2. Do NOT invent bugs or evidence not in findings.\n"
            "3. Be pragmatic and directly actionable.\n"
            "4. Keep to 2-3 sentences explaining why it is risky and what to verify.\n\n"
            f"FINDINGS:\n{prompt_payload}\n\n"
            "Respond with ONLY the executive summary text. Do not include markdown headers."
        )

        response = model.generate_content(prompt)
        text = response.text.strip() if response and response.text else ""

        if text:
            return RecommendedActions(
                tests_to_run=result.recommended_actions.tests_to_run,
                suggested_reviewers=result.recommended_actions.suggested_reviewers,
                summary=text,
            )

    except Exception as exc:
        logger.warning("LLM explanation failed: %s; using deterministic fallback.", exc)

    return result.recommended_actions
