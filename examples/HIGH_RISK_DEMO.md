# High-Risk Demo — Payment Transaction Regression

A reproducible scenario that scores **HIGH (60/100)** on Regression Radar
without any score manipulation or threshold changes.

## What the scenario models

A payment-service monorepo where `payments/transaction.py` is modified by a
new developer (`new@example.com`) in a one-line change that silently allows
zero-value transactions — a classic off-by-one validation regression:

```python
# Before (safe):   if amount <= 0: raise ValueError(...)
# After  (buggy):  if amount < 0:  raise ValueError(...)
```

Zero amounts now pass through to the payment gateway, causing settlement errors
and potential duplicate-charge reconciliation failures.

## Why all four signals fire

| Signal | Score | Evidence |
|---|---|---|
| Historical Hotspot | 56/100 | `payments/transaction.py` has 9 bug-fix / revert commits out of 23 total (39% fix rate) |
| Co-change Anomaly | 74/100 | `transaction.py` historically changes alongside `ledger.py` in 17 commits (74% confidence) — but `ledger.py` was **not** touched in this PR |
| Test Gap | 40/100 | `tests/test_transaction.py` exists and covers the changed file, but was not updated in the PR |
| Ownership | 81/100 | `new@example.com` authored only 4% of prior commits to this module |

**Weighted score:** `0.35×56 + 0.30×74 + 0.25×40 + 0.10×81 ≈ 60.2`

## The genuine regression

Running the demo's own test suite on the PR branch **exposes the bug**:

```
FAILED tests/test_transaction.py::test_zero_amount_raises
  Failed: DID NOT RAISE ValueError
```

Regression Radar recommends running `tests/test_transaction.py` — the exact
test that catches the fault.

## Reproduction commands

```powershell
# 1. Build the demo repository (safe, isolated — does not touch main project)
cd "C:\Users\VISHNU KULKARNI\.gemini\antigravity\scratch\regression-radar"
python examples/build_high_risk_demo.py

# 2. Run Regression Radar analysis
python -m regression_radar.cli analyse examples/high-risk-demo `
    --base main --author "new@example.com" --format terminal

# 3. Generate Markdown report
python -m regression_radar.cli analyse examples/high-risk-demo `
    --base main --author "new@example.com" --format markdown

# 4. Run the demo's own test suite to surface the regression
cd examples/high-risk-demo
python -m pytest tests/ -v
# Expected: 4 passed, 1 FAILED (test_zero_amount_raises)

# 5. Return to project root and run full test suite (must still be 96/96)
cd ..\..
python -m pytest -v
```

## Actual output (recorded)

```
╭──────────────────────────────────────────────────────────────────────────╮
│ Regression Risk: HIGH (60 / 100)                                         │
│ Diff: main..HEAD | 1 files (+7 -2)                                       │
╰──────────────────────────────────────────────────────────────────────────╯

Why was this flagged?
  • Ownership risk is elevated (81.3/100): PR author 'new@example.com' has
    few prior changes to these files (4% share).
  • Co-change anomaly score 74.2/100. 'payments/transaction.py' historically
    changes alongside 'payments/ledger.py' in 17 commits (74% confidence),
    but 'payments/ledger.py' was not modified in this PR.
  • Historical hotspot score 56.5/100. Top fragile file is
    'payments/transaction.py' with 9 bug-fix/revert commit(s) out of 23
    total changes (39% fix rate).
  • Test-gap score 40.0/100. Matching tests exist for all changed sources,
    but 1 test file(s) were not updated in this PR.

Recommended Actions
  • Run Tests: tests/test_transaction.py (covers modified
    'payments/transaction.py')
  • Reviewers: Priya Kapoor (priya@example.com) — 22 prior commit(s)
```

## Files changed

| File | Purpose |
|---|---|
| `examples/build_high_risk_demo.py` | Builds the isolated demo Git repository |
| `examples/high-risk-report.json` | Recorded JSON analysis output |
| `examples/high-risk-report.md` | Recorded Markdown analysis output |
| `examples/HIGH_RISK_DEMO.md` | This document |

> **Note:** `examples/high-risk-demo/` is excluded from version control via
> `.gitignore`. Rebuild it at any time with the command above.
