// src/types/api.ts — Mirror of Python Pydantic models

export type DataQuality = "low" | "medium" | "high";
export type RiskCategory = "low" | "medium" | "high" | "critical";

export interface SignalResult {
  name: string;
  score: number;
  explanation: string;
  data_quality: DataQuality;
  is_available: boolean;
  evidence: Record<string, unknown>;
  recommendations: string[];
}

export interface RecommendedActions {
  tests_to_run: string[];
  suggested_reviewers: string[];
  summary: string;
}

export interface AnalysisResult {
  overall_score: number;
  risk_category: RiskCategory;
  data_quality: DataQuality;
  base_ref: string;
  head_ref: string;
  total_files_changed: number;
  additions: number;
  deletions: number;
  signals: Record<string, SignalResult>;
  weights: Record<string, number>;
  why_flagged: string[];
  recommended_actions: RecommendedActions;
}

export interface AnalyzeRequest {
  repo_path: string;
  base_ref: string;
  head_ref: string;
  pr_author_email?: string;
  use_ai?: boolean;
}

export interface GitHubPRRequest {
  pr_url: string;
  use_ai?: boolean;
}

export interface TokenStatus {
  has_token: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ScoringConfig {
  weights: Record<string, number>;
  thresholds: Record<string, number>;
}

// App-internal types
export interface AnalysisRecord {
  id: string;
  repo_path: string;
  base_ref: string;
  head_ref: string;
  timestamp: string;
  result: AnalysisResult;
}
