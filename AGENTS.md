# AGENTS.md — Regression Radar

Concise, persistent instructions for any AI coding agent working on this project.

---

## Project purpose

Regression Radar is a **history-aware PR risk analyser**. It reads a local Git repository, analyses
commit history, and produces a deterministic risk-prioritisation score (0–100) with supporting
evidence for a proposed set of changes.

It is a developer tool, not an LLM-driven code critic.

---

## Critical constraints

1. **Never invent evidence.** Every finding must trace back to real Git data.
2. **Keep the score deterministic.** Same inputs → same score. No randomness in core scoring.
3. **Call it a risk-prioritisation score**, not a probability of failure.
4. **Never auto-merge, approve, or block PRs** — even in GitHub Actions.
5. **Never send repository source code to external APIs** without explicit opt-in configuration.
6. **Handle missing/sparse data gracefully** — return explicit "unavailable" states, not crashes.
7. **Do not silently swallow exceptions.** Log and re-raise or return structured error signals.

---

## Code conventions

- Python 3.11+ type hints everywhere.
- Pydantic v2 models for all inter-module data contracts.
- Structured logging via `logging` stdlib — no `print()` in library code.
- All Git interactions go through `git_history.py` (subprocess or GitPython).
- CLI logic lives only in `cli.py`.
- Tests live in `tests/`; fixtures in `tests/fixtures/`.
- Run `pytest` to verify; run `ruff check src tests` for lint.

---

## Module responsibilities (one-liner each)

| Module | Responsibility |
|---|---|
| `git_history.py` | Extract commits, diffs, and file-change metadata from a local Git repo |
| `diff_parser.py` | Parse unified diffs into structured `FileDiff` objects |
| `hotspot.py` | Score files by bug-fix / revert frequency in history |
| `cochange.py` | Mine co-change rules and flag absent co-change partners |
| `test_gap.py` | Identify source files changed without related test coverage |
| `ownership.py` | Identify recent contributors per file; suggest reviewers |
| `scoring.py` | Combine signals into a final 0–100 score with configurable weights |
| `recommendations.py` | Build human-readable recommended actions from signal findings |
| `report.py` | Render terminal (Rich), Markdown, and JSON output |
| `cli.py` | Typer entry-point; wire everything together |

---

## Scoring weights (configurable in `configs/weights.toml`)

| Signal | Default weight |
|---|---|
| Historical hotspot | 35 % |
| Co-change anomaly | 30 % |
| Test-gap | 25 % |
| Ownership | 10 % |

These are **starting hypotheses**. Document changes in `DECISIONS.md`.

---

## Edge cases to always handle

- Empty repositories (zero commits).
- Shallow clones (limited history).
- Renamed files (track through renames).
- Merge commits (treat files in merge commits carefully).
- Binary files (skip diff content; flag path only).
- Files with no test counterparts (explicit "no test mapping found" state).
- PRs with zero changed files.
- Repositories with fewer than 10 commits (emit low-data warning).

---

## Development commands

```bash
pip install -e ".[dev]"   # Install with dev extras
pytest                     # Run all tests
ruff check src tests       # Lint
mypy src                   # Type-check
rr analyse /path/to/repo  # Run the CLI
```
