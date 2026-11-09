// src/api/client.ts — Thin axios wrapper around the Regression Radar FastAPI backend
import axios from "axios";
import type {
  AnalysisResult,
  AnalyzeRequest,
  GitHubPRRequest,
  HealthResponse,
  ScoringConfig,
  TokenStatus,
} from "../types/api";

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/",
  timeout: 120_000,
  headers: { "Content-Type": "application/json" },
});

export async function checkHealth(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>("/health");
  return data;
}

export async function getConfig(): Promise<ScoringConfig> {
  const { data } = await http.get<ScoringConfig>("/api/v1/config");
  return data;
}

export async function runAnalysis(req: AnalyzeRequest): Promise<AnalysisResult> {
  const { data } = await http.post<AnalysisResult>("/api/v1/analyze", req);
  return data;
}

export async function runAnalysisMarkdown(
  req: AnalyzeRequest,
): Promise<{ markdown: string; overall_score: string; category: string }> {
  const { data } = await http.post("/api/v1/analyze/markdown", req);
  return data;
}

export async function runGitHubAnalysis(req: GitHubPRRequest): Promise<AnalysisResult> {
  const { data } = await http.post<AnalysisResult>("/api/v1/analyze/github-pr", req);
  return data;
}

export async function getTokenStatus(): Promise<TokenStatus> {
  const { data } = await http.get<TokenStatus>("/api/v1/github/token-status");
  return data;
}
