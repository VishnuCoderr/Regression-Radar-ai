# Regression Radar

**AI-powered Pull Request risk analyser** — predicts which code changes deserve extra scrutiny before merging.

---

## What it does

Regression Radar analyses a proposed PR using **repository history** and generates an explainable **risk-prioritisation score** (0–100), supporting evidence, and recommended actions.

It is **not**:
- A generic code-quality checker
- A replacement for CI or human code review
- An LLM that guesses whether code is buggy
- A system that guarantees production safety

Its differentiator: **PR-time, history-aware risk analysis with actionable recommendations.**

---

## Four analysis signals

| Signal | What it detects |
|---|---|
| **Historical Hotspot** | Files with disproportionate bug-fix and revert history |
| **Co-change Pattern** | Files that always move together — missing ones are a warning |
| **Test Gap** | Source files changed without matching test coverage |
| **Ownership** | Who knows this code best, suggested as potential reviewers |

---

## Risk-prioritisation score

| Score | Category |
|---|---|
| 0–29 | 🟢 Low |
| 30–59 | 🟡 Medium |
| 60–79 | 🟠 High |
| 80–100 | 🔴 Critical |

> ⚠️ A score of 80 is a **risk-prioritisation score**, not an 80 % probability of production failure.

---

## Quick start

### Prerequisites

- Python 3.11+
- Git (must be on PATH)

### Install

```bash
cd regression-radar
pip install -e ".[dev]"
```

### Analyse a local repository

```bash
# Diagnostic inspect: view repo statistics, commit history, and diff
python -m regression_radar.cli inspect /path/to/repo --base main

# Or run via installed command
rr inspect /path/to/repo
```

### Run tests

```bash
pytest
```

---

## Configuration

Copy `.env.example` to `.env` and set any optional keys:

```bash
cp .env.example .env
```

A `configs/weights.toml` file controls signal weights and score thresholds.

---

## Project layout

```
src/regression_radar/
├── cli.py           — Typer CLI entry point
├── git_history.py   — Git log extraction and diff parsing
├── diff_parser.py   — Parse unified diffs into structured changes
├── hotspot.py       — Historical hotspot detection
├── cochange.py      — Co-change pattern analysis
├── test_gap.py      — Test-gap detection
├── ownership.py     — Contributor ownership signals
├── scoring.py       — Deterministic risk engine
├── recommendations.py — Actionable recommendation builder
└── report.py        — Terminal and Markdown/JSON reporter
```

---

## Status

- [x] Phase 0 — Project foundation
- [x] Phase 1 — Git history extraction + diff parsing
- [ ] Phase 2 — Intelligence engine (hotspot, co-change, test gap, ownership)
- [ ] Phase 3 — Scoring engine + CLI reports
- [ ] Phase 4 — GitHub Actions integration
- [ ] Phase 5 — Optional LLM explanations
- [ ] Phase 6 — Hackathon validation + evaluation report
