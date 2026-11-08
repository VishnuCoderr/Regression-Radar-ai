// src/pages/AnalyzePR.tsx â€” PR Intelligence / Analysis page (flagship)
import React, { useState } from "react";
import {
  Zap, Folder, GitBranch, User, AlertTriangle, ChevronDown, ChevronUp,
  CheckCircle2, Users, TestTube2, FileText, Sparkles, Info, GitPullRequest, Lock,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Path validation â€” runs entirely client-side, before hitting the API
// ---------------------------------------------------------------------------
function validateRepoPath(raw: string): string | null {
  const v = raw.trim();

  if (!v) return "Repository path is required.";

  // GitPullRequest / HTTP URLs
  if (/^https?:\/\//i.test(v) || /^git@/i.test(v) || /^github\.com/i.test(v)) {
    return "GitPullRequest URL analysis is not supported here yet. Use a local clone.";
  }

  // Must look like an absolute path (Windows C:\ / D:\ or Unix /)
  const isWindowsAbsolute = /^[A-Za-z]:[/\\]/.test(v);
  const isUnixAbsolute = v.startsWith("/");
  if (!isWindowsAbsolute && !isUnixAbsolute) {
    return "Please enter an absolute path (e.g. C:\\Users\\you\\my-repo or /home/you/my-repo).";
  }

  // Reject obviously wrong suffixes
  if (v.endsWith(".git") && !v.includes("/") && !v.includes("\\")) {
    return "Enter the directory path to the repository, not a .git URL.";
  }

  return null; // valid
}

// ---------------------------------------------------------------------------
// GitPullRequest PR URL validation â€” client-side, before hitting the API
// ---------------------------------------------------------------------------
function validateGitHubUrl(raw: string): string | null {
  const v = raw.trim();
  if (!v) return "GitPullRequest PR URL is required.";
  const pattern = /^https?:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+\/?$/i;
  if (!pattern.test(v.split("?")[0].split("#")[0])) {
    return "Enter a valid GitPullRequest PR URL: https://github.com/<owner>/<repo>/pull/<number>";
  }
  return null;
}
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { RiskBadge } from "../components/ui/Badge";
import { ScoreGauge } from "../components/ui/ScoreGauge";
import { SignalBar } from "../components/ui/SignalBar";
import { runAnalysis, runGitHubAnalysis } from "../api/client";
import { useAnalysisStore } from "../store/analysisStore";
import type { AnalysisResult, AnalyzeRequest } from "../types/api";

type AnalysisMode = "local" | "github";

const SIGNAL_LABELS: Record<string, string> = {
  historical_hotspot: "Historical Hotspot",
  cochange_anomaly: "Co-change Anomaly",
  test_gap: "Test Gap",
  ownership: "Ownership Risk",
};

function InputField({
  label, id, value, onChange, placeholder, type = "text",
}: {
  label: string; id: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-zinc-400 mb-1.5">
        {label}
      </label>
      <input
        id={id} type={type} value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-[#18181f] border border-[#2a2a38] rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/20 transition-colors"
      />
    </div>
  );
}

// Dedicated repo-path field with inline validation feedback
function RepoPathField({
  value,
  onChange,
  pathError,
}: {
  value: string;
  onChange: (v: string) => void;
  pathError: string | null;
}) {
  const isGitHubError =
    pathError?.startsWith("GitPullRequest URL") ?? false;

  const borderClass = pathError
    ? "border-red-500/60 focus:border-red-500/80 focus:ring-red-500/20"
    : value.trim()
    ? "border-emerald-500/40 focus:border-emerald-500/60 focus:ring-emerald-500/15"
    : "border-[#2a2a38] focus:border-blue-500/60 focus:ring-blue-500/20";

  return (
    <div>
      {/* Label row */}
      <div className="flex items-center justify-between mb-1.5">
        <label htmlFor="repo_path" className="text-xs font-medium text-zinc-400">
          Local Git Repository Path
        </label>
        <span className="text-[10px] text-zinc-600 uppercase tracking-wide font-medium">
          required
        </span>
      </div>

      {/* Input */}
      <div className="relative">
        <Folder className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-600 pointer-events-none" />
        <input
          id="repo_path"
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="C:\Users\you\my-repo"
          autoComplete="off"
          spellCheck={false}
          className={`w-full bg-[#18181f] border rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-zinc-700 focus:outline-none focus:ring-1 transition-colors font-mono ${borderClass}`}
        />
      </div>

      {/* Inline validation message */}
      {pathError ? (
        <div className={`mt-2 flex items-start gap-2 rounded-md px-3 py-2 ${
          isGitHubError
            ? "bg-violet-500/10 border border-violet-500/20"
            : "bg-red-500/10 border border-red-500/20"
        }`}>
          <AlertTriangle className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${isGitHubError ? "text-violet-400" : "text-red-400"}`} />
          <p className={`text-xs leading-relaxed ${isGitHubError ? "text-violet-300" : "text-red-400"}`}>
            {pathError}
          </p>
        </div>
      ) : (
        /* Helper text â€” always visible when field is empty */
        !value.trim() && (
          <div className="mt-1.5 flex items-start gap-1.5">
            <Info className="w-3 h-3 text-zinc-700 flex-shrink-0 mt-0.5" />
            <p className="text-[11px] text-zinc-600 leading-relaxed">
              Enter the absolute path to a Git repository on your machine.{" "}
              <span className="font-mono text-zinc-700">
                e.g. C:\Users\you\my-repo
              </span>
            </p>
          </div>
        )
      )}
    </div>
  );
}

export function AnalyzePR() {
  const { addRecord } = useAnalysisStore();
  const [mode, setMode] = useState<AnalysisMode>("local");

  // Local repo form state
  const [form, setForm] = useState<AnalyzeRequest>({
    repo_path: "",
    base_ref: "main",
    head_ref: "HEAD",
    pr_author_email: "",
    use_ai: false,
  });
  const [pathError, setPathError] = useState<string | null>(null);

  // GitPullRequest PR form state
  const [ghUrl, setGhUrl] = useState("");
  const [ghUrlError, setGhUrlError] = useState<string | null>(null);
  const [ghUseAi, setGhUseAi] = useState(false);

  // Shared state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const set = (key: keyof AnalyzeRequest) => (val: string | boolean) =>
    setForm((f) => ({ ...f, [key]: val }));

  function handlePathChange(v: string) {
    set("repo_path")(v);
    setPathError(v.trim() ? validateRepoPath(v) : null);
    setError(null);
  }

  function handleGhUrlChange(v: string) {
    setGhUrl(v);
    setGhUrlError(v.trim() ? validateGitHubUrl(v) : null);
    setError(null);
  }

  function switchMode(m: AnalysisMode) {
    setMode(m);
    setError(null);
    setResult(null);
  }

  function friendlyError(err: unknown): string {
    const detail =
      (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "";
    const raw = (err as Error)?.message ?? "";
    if (detail.toLowerCase().includes("not a git repository") || detail.toLowerCase().includes("does not exist"))
      return "Path not found or is not a Git repository. Check the path and try again.";
    if (detail.toLowerCase().includes("permission") || detail.toLowerCase().includes("access denied"))
      return "Cannot read the repository â€” check folder permissions.";
    if (detail.toLowerCase().includes("not found") || detail.toLowerCase().includes("404"))
      return "Pull request not found. Verify the URL is correct and the repository is accessible.";
    if (detail.toLowerCase().includes("rate limit"))
      return "GitPullRequest API rate limit exceeded. Set GITHUB_TOKEN on the server or wait before retrying.";
    if (detail.toLowerCase().includes("authentication") || detail.toLowerCase().includes("401"))
      return "GitPullRequest authentication failed. Ask the server administrator to set GITHUB_TOKEN.";
    if (detail.toLowerCase().includes("forbidden") || detail.toLowerCase().includes("403"))
      return "Access denied. The repository may be private â€” set GITHUB_TOKEN with repo scope.";
    if (detail) return detail;
    if (raw.includes("Network Error") || raw.includes("ECONNREFUSED"))
      return "Cannot reach the analysis API. Make sure the backend is running on port 8000.";
    return "Analysis failed. Check your inputs and try again.";
  }

  async function handleLocalSubmit(e: React.FormEvent) {
    e.preventDefault();
    const clientError = validateRepoPath(form.repo_path);
    if (clientError) { setPathError(clientError); return; }

    setLoading(true); setError(null); setResult(null);
    try {
      const req: AnalyzeRequest = { ...form, pr_author_email: form.pr_author_email?.trim() || undefined };
      const data = await runAnalysis(req);
      setResult(data);
      addRecord({
        id: crypto.randomUUID(),
        repo_path: form.repo_path,
        base_ref: form.base_ref,
        head_ref: form.head_ref,
        timestamp: new Date().toISOString(),
        result: data,
      });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleGitHubSubmit(e: React.FormEvent) {
    e.preventDefault();
    const clientError = validateGitHubUrl(ghUrl);
    if (clientError) { setGhUrlError(clientError); return; }

    setLoading(true); setError(null); setResult(null);
    try {
      const data = await runGitHubAnalysis({ pr_url: ghUrl.trim(), use_ai: ghUseAi });
      setResult(data);
      addRecord({
        id: crypto.randomUUID(),
        repo_path: ghUrl.trim(),
        base_ref: data.base_ref,
        head_ref: data.head_ref,
        timestamp: new Date().toISOString(),
        result: data,
      });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white mb-1">PR Intelligence</h1>
        <p className="text-zinc-500 text-sm">
          Analyse a pull request from a local Git repository or directly from GitHub.
        </p>
      </div>

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Form panel */}
        <Card className="lg:col-span-2 h-fit">
          {/* Mode tabs */}
          <div className="flex border-b border-[#2a2a38]">
            <button
              onClick={() => switchMode("local")}
              className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors ${
                mode === "local"
                  ? "text-white border-b-2 border-blue-500 -mb-px"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <Folder className="w-3.5 h-3.5" />
              Local Repo
            </button>
            <button
              onClick={() => switchMode("github")}
              className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors ${
                mode === "github"
                  ? "text-white border-b-2 border-blue-500 -mb-px"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <GitPullRequest className="w-3.5 h-3.5" />
              GitPullRequest PR
            </button>
          </div>

          <CardBody>
            {mode === "local" ? (
              <form onSubmit={handleLocalSubmit} className="space-y-4">
                <RepoPathField value={form.repo_path} onChange={handlePathChange} pathError={pathError} />
                <div className="grid grid-cols-2 gap-3">
                  <InputField label="Base Ref" id="base_ref" value={form.base_ref} onChange={set("base_ref")} placeholder="main" />
                  <InputField label="Head Ref" id="head_ref" value={form.head_ref} onChange={set("head_ref")} placeholder="HEAD" />
                </div>
                <InputField
                  label="PR Author Email (optional)" id="pr_author_email"
                  value={form.pr_author_email ?? ""} onChange={set("pr_author_email")}
                  placeholder="dev@company.com" type="email"
                />
                <AiToggle enabled={form.use_ai ?? false} onChange={(v) => set("use_ai")(v)} />
                <SubmitButton loading={loading} disabled={!!pathError} />
                {error && <ErrorBanner message={error} />}
              </form>
            ) : (
              <form onSubmit={handleGitHubSubmit} className="space-y-4">
                <GitHubUrlField value={ghUrl} onChange={handleGhUrlChange} urlError={ghUrlError} />
                <div className="rounded-lg bg-[#18181f] border border-[#2a2a38] px-3 py-2.5 flex items-start gap-2.5">
                  <Lock className="w-3.5 h-3.5 text-zinc-600 flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] text-zinc-600 leading-relaxed">
                    Your GitPullRequest token is kept on the server. Public repos work without a token.
                    Private repos require{" "}
                    <span className="font-mono text-zinc-500">GITHUB_TOKEN</span> with{" "}
                    <span className="font-mono text-zinc-500">repo</span> scope.
                  </p>
                </div>
                <AiToggle enabled={ghUseAi} onChange={setGhUseAi} />
                <SubmitButton loading={loading} disabled={!!ghUrlError} label="Analyse PR" />
                {error && <ErrorBanner message={error} />}
              </form>
            )}
          </CardBody>
        </Card>

        {/* Result panel */}
        <div className="lg:col-span-3">
          {!result && !loading && <EmptyAnalysis mode={mode} />}
          {loading && <LoadingAnalysis />}
          {result && (
            <ResultPanel
              result={result}
              repoPath={mode === "local" ? form.repo_path : ghUrl}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared helper sub-components
// ---------------------------------------------------------------------------

function AiToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer select-none">
      <div className="relative">
        <input type="checkbox" className="sr-only" checked={enabled} onChange={(e) => onChange(e.target.checked)} />
        <div className={`w-9 h-5 rounded-full transition-colors ${enabled ? "bg-blue-600" : "bg-zinc-700"}`} />
        <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-4" : ""}`} />
      </div>
      <div>
        <span className="text-sm text-zinc-300">AI explanations</span>
        <span className="ml-1.5 text-xs text-zinc-600">(requires GEMINI_API_KEY)</span>
      </div>
    </label>
  );
}

function SubmitButton({
  loading, disabled, label = "Run Analysis",
}: { loading: boolean; disabled: boolean; label?: string }) {
  return (
    <button
      type="submit"
      disabled={loading || disabled}
      className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-white text-sm font-medium rounded-lg transition-colors"
    >
      {loading ? (
        <>
          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          Analysingâ€¦
        </>
      ) : (
        <>
          <Zap className="w-4 h-4" />
          {label}
        </>
      )}
    </button>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
      <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
      <p className="text-xs text-red-400 leading-relaxed">{message}</p>
    </div>
  );
}

function GitHubUrlField({
  value, onChange, urlError,
}: { value: string; onChange: (v: string) => void; urlError: string | null }) {
  const borderClass = urlError
    ? "border-red-500/60 focus:border-red-500/80 focus:ring-red-500/20"
    : value.trim()
    ? "border-emerald-500/40 focus:border-emerald-500/60 focus:ring-emerald-500/15"
    : "border-[#2a2a38] focus:border-blue-500/60 focus:ring-blue-500/20";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label htmlFor="gh_url" className="text-xs font-medium text-zinc-400">GitPullRequest PR URL</label>
        <span className="text-[10px] text-zinc-600 uppercase tracking-wide font-medium">required</span>
      </div>
      <div className="relative">
        <GitPullRequest className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-600 pointer-events-none" />
        <input
          id="gh_url" type="url" value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="https://github.com/owner/repo/pull/123"
          autoComplete="off" spellCheck={false}
          className={`w-full bg-[#18181f] border rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-zinc-700 focus:outline-none focus:ring-1 transition-colors font-mono ${borderClass}`}
        />
      </div>
      {urlError ? (
        <div className="mt-2 flex items-start gap-2 rounded-md px-3 py-2 bg-red-500/10 border border-red-500/20">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-red-400" />
          <p className="text-xs leading-relaxed text-red-400">{urlError}</p>
        </div>
      ) : !value.trim() && (
        <div className="mt-1.5 flex items-start gap-1.5">
          <Info className="w-3 h-3 text-zinc-700 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-zinc-600 leading-relaxed">
            Paste the full URL to any public GitPullRequest PR.{" "}
            <span className="font-mono text-zinc-700">e.g. https://github.com/facebook/react/pull/1</span>
          </p>
        </div>
      )}
    </div>
  );
}

function EmptyAnalysis({ mode }: { mode?: AnalysisMode }) {
  return (
    <div className="h-full flex items-center justify-center text-center py-20">
      <div>
        <div className="w-14 h-14 rounded-xl bg-[#18181f] border border-[#2a2a38] flex items-center justify-center mx-auto mb-4">
          {mode === "github" ? <GitPullRequest className="w-7 h-7 text-zinc-600" /> : <FileText className="w-7 h-7 text-zinc-600" />}
        </div>
        <p className="text-zinc-500 text-sm max-w-xs">
          {mode === "github"
            ? <>Paste a GitPullRequest PR URL and click <strong className="text-zinc-300">Analyse PR</strong>.</>
            : <>Fill in the repository path and refs, then click <strong className="text-zinc-300">Run Analysis</strong>.</>}
        </p>
        {mode !== "github" && (
          <div className="mt-6 text-xs text-zinc-700 space-y-1">
            <p>Quick start with the demo repo:</p>
            <code className="text-zinc-600 font-mono">examples/demo-repo</code>
            <p>Base: <code className="text-zinc-600 font-mono">main</code> Â· Head: <code className="text-zinc-600 font-mono">HEAD</code></p>
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingAnalysis() {
  return (
    <Card className="p-8">
      <div className="flex flex-col items-center text-center py-8">
        <div className="w-12 h-12 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mb-4" />
        <p className="text-sm text-zinc-300 font-medium mb-1">Analysing repositoryâ€¦</p>
        <p className="text-xs text-zinc-600">Reading Git history, scoring signals, detecting patterns</p>
      </div>
    </Card>
  );
}

function ResultPanel({ result, repoPath }: { result: AnalysisResult; repoPath: string }) {
  const [expanded, setExpanded] = useState(false);
  const repoName = repoPath.split(/[\\/]/).pop() ?? repoPath;

  return (
    <div className="space-y-5">
      {/* Score hero */}
      <Card>
        <CardBody className="flex items-center gap-6">
          <ScoreGauge score={result.overall_score} category={result.risk_category} />
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <RiskBadge category={result.risk_category} className="text-sm px-3 py-1" />
              <span className="text-xs text-zinc-600">{result.data_quality} data quality</span>
            </div>
            <div className="text-xs text-zinc-600 space-y-0.5">
              <div className="flex items-center gap-1.5">
                <Folder className="w-3.5 h-3.5" />
                <span className="font-mono text-zinc-500">{repoName}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <GitBranch className="w-3.5 h-3.5" />
                <span className="font-mono text-zinc-500">
                  {result.base_ref} â†’ {result.head_ref}
                </span>
              </div>
            </div>
            <div className="mt-3 flex gap-4 text-xs text-zinc-500">
              <span><strong className="text-white">{result.total_files_changed}</strong> files</span>
              <span><strong className="text-emerald-400">+{result.additions}</strong></span>
              <span><strong className="text-red-400">-{result.deletions}</strong></span>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Why flagged */}
      {result.why_flagged.length > 0 && (
        <Card>
          <CardHeader>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              Why was this flagged?
            </h3>
          </CardHeader>
          <CardBody className="py-3">
            <ul className="space-y-2">
              {result.why_flagged.map((item, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-zinc-400">
                  <span className="w-1 h-1 rounded-full bg-zinc-600 flex-shrink-0 mt-2" />
                  {item}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}

      {/* Signal breakdown */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Signal Breakdown</h3>
            <button
              onClick={() => setExpanded((x) => !x)}
              className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
            >
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {expanded ? "Less" : "Details"}
            </button>
          </div>
        </CardHeader>
        <CardBody className="py-2">
          {Object.entries(result.signals).map(([key, sig]) => (
            <SignalBar
              key={key}
              label={SIGNAL_LABELS[key] ?? key}
              score={sig.score}
              weight={result.weights[key] ?? 0}
              available={sig.is_available}
              explanation={sig.explanation}
            />
          ))}

          {expanded && (
            <div className="mt-4 space-y-3">
              {Object.entries(result.signals).filter(([, s]) => s.is_available && s.recommendations.length > 0).map(([key, sig]) => (
                <div key={key}>
                  <p className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1">
                    {SIGNAL_LABELS[key] ?? key} recommendations
                  </p>
                  <ul className="space-y-1">
                    {sig.recommendations.map((r, i) => (
                      <li key={i} className="text-xs text-zinc-400 flex items-start gap-1.5">
                        <span className="text-zinc-700 mt-0.5">â†’</span>
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Recommended actions */}
      <div className="grid grid-cols-2 gap-4">
        {result.recommended_actions.tests_to_run.length > 0 && (
          <Card>
            <CardHeader>
              <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wide flex items-center gap-1.5">
                <TestTube2 className="w-3.5 h-3.5 text-blue-500" />
                Tests to run
              </h3>
            </CardHeader>
            <CardBody className="py-3">
              <ul className="space-y-1.5">
                {result.recommended_actions.tests_to_run.map((t, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                    <CheckCircle2 className="w-3.5 h-3.5 text-blue-500 flex-shrink-0 mt-0.5" />
                    <code className="font-mono text-zinc-300 break-all">{t}</code>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        )}

        {result.recommended_actions.suggested_reviewers.length > 0 && (
          <Card>
            <CardHeader>
              <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wide flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-violet-500" />
                Suggested reviewers
              </h3>
            </CardHeader>
            <CardBody className="py-3">
              <ul className="space-y-1.5">
                {result.recommended_actions.suggested_reviewers.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                    <User className="w-3.5 h-3.5 text-violet-500 flex-shrink-0 mt-0.5" />
                    {r}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        )}
      </div>

      {/* AI summary */}
      {result.recommended_actions.summary && (
        <Card className="border-blue-500/20 bg-blue-500/5">
          <CardBody className="flex items-start gap-3">
            <Sparkles className="w-4 h-4 text-blue-400 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-zinc-300 leading-relaxed">
              {result.recommended_actions.summary}
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

