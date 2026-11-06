# PLAN.md — Regression Radar Milestones

---

## Phase 0 — Foundation ✅

**Goal:** Establish project structure and development environment.

Acceptance criteria:
- [x] `pyproject.toml` with correct dependencies
- [x] Source package scaffolded under `src/regression_radar/`
- [x] `AGENTS.md`, `README.md`, `PLAN.md`, `DECISIONS.md` created
- [x] `configs/weights.toml` with default scoring configuration
- [x] `.gitignore`, `.env.example` created
- [x] `pip install -e ".[dev]"` succeeds

---

## Phase 1 — Git history extraction + diff parsing ✅

**Goal:** Reliably read a local Git repository and extract structured analysis data.

Acceptance criteria:
- [x] `git_history.py` extracts commit list with metadata (hash, author, date, message, changed files)
- [x] Bug-fix and revert commits identified via configurable keyword heuristics
- [x] Diff between two refs (or HEAD vs base branch) parsed correctly
- [x] `diff_parser.py` produces `FileDiff` objects (path, additions, deletions, hunks)
- [x] Handles empty repos, shallow clones, renames, merge commits safely
- [x] Automated tests with real in-process Git fixture repositories (59 tests passing)
- [x] Tests pass: `pytest tests/test_git_history.py tests/test_diff_parser.py`
- [x] Ruff lint checks pass cleanly with 0 errors

---

## Phase 2 — Intelligence engine ✅

**Goal:** Implement all four analysis signals with evidence.

Acceptance criteria:
- [x] `hotspot.py` returns per-file risk indicators with supporting commit evidence and Bayesian smoothing
- [x] `cochange.py` returns co-change rules above configurable support/confidence thresholds
- [x] `cochange.py` identifies absent partner files in current PR diff
- [x] `test_gap.py` maps source → test files via naming + co-change fallback
- [x] `ownership.py` returns recent contributor list per file with recency weighting and suggests candidate reviewers
- [x] Every signal returns structured `SignalResult` (score, evidence, explanation, data_quality, recommendations)
- [x] Comprehensive test coverage with 23 new unit tests (82 tests total across suite)
- [x] Ruff lint checks pass cleanly with 0 errors

---

## Phase 3 — Scoring engine + CLI reports [ ]

**Goal:** Wire signals into a readable, deterministic risk report.

Acceptance criteria:
- [ ] `scoring.py` combines signals with configurable weights → 0–100 score + category
- [ ] Weights loaded from `configs/weights.toml` (overridable via CLI)
- [ ] `report.py` renders terminal (Rich table + panel), Markdown, and JSON
- [ ] CLI command `rr analyse` accepts repo path, base branch, format, output file
- [ ] JSON schema documented and stable
- [ ] Scoring unit tests cover boundary conditions (all zeros, all max, missing signals)

---

## Phase 4 — GitHub Actions integration [ ]

**Goal:** Analyse PRs automatically and post a structured comment.

Acceptance criteria:
- [ ] `.github/workflows/regression-radar.yml` runs on `pull_request`
- [ ] Action checks out PR head + base, runs `rr analyse`
- [ ] Posts/updates a PR comment with Markdown report (no duplicate comments on rerun)
- [ ] Uses `contents: read` + `pull-requests: write` only
- [ ] Never auto-merges, approves, or blocks PRs

---

## Phase 5 — Optional LLM explanations [ ]

**Goal:** Optionally enrich reports with natural-language summaries.

Acceptance criteria:
- [ ] `llm_explain.py` accepts structured `AnalysisResult`, returns prose explanation
- [ ] LLM cannot modify risk score or invent evidence
- [ ] Fully functional fallback when `GEMINI_API_KEY` not set
- [ ] No repository source code sent to API
- [ ] Gemini API used (google-generativeai SDK)

---

## Phase 6 — Hackathon validation [ ]

**Goal:** Demonstrate measurable correctness on a controlled scenario.

Acceptance criteria:
- [ ] `examples/demo-repo/` is a reproducible Git repo with known bug-fix history
- [ ] Evaluation script runs historical replay (no future-data leakage)
- [ ] `docs/EVALUATION.md` reports detection rate, precision, false-positive rate
- [ ] Comparison against trivial baseline (random score) documented
- [ ] Honest limitations section included
