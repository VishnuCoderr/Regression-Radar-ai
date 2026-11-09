### ΓÜá∩╕Å Regression Risk: High (60 / 100)

**Why was this flagged?**
- Ownership risk is elevated (81.3/100): PR author 'new@example.com' has few prior changes to these files (4% share).
- Co-change anomaly score 74.2/100. 'payments/transaction.py' historically changes alongside 'payments/ledger.py' in 17 commits (74% confidence), but 'payments/ledger.py' was not modified in this PR.
- Historical hotspot score 56.5/100. Top fragile file is 'payments/transaction.py' with 9 bug-fix/revert commit(s) out of 23 total changes (39% fix rate).
- Test-gap score 40.0/100. Matching tests exist for all changed sources, but 1 test file(s) were not updated in this PR.

**Recommended Actions**
- **Run:** tests/test_transaction.py (covers modified 'payments/transaction.py')
- **Suggested Reviewer:** Priya Kapoor (priya@example.com) ΓÇö 22 prior commit(s)
- **Summary:** This pull request carries an elevated risk score (60.2/100). Modifies fragile files with past bug-fixes (payments/transaction.py). Frequently coupled files were omitted (payments/ledger.py, payments/audit.py). Verify relevant tests and consult recommended reviewers before merging.

<details>
<summary><b>Detailed Signal Breakdown</b></summary>

| Signal | Risk Score | Weight | Finding |
|---|---|---|---|
| Historical Hotspot | 56/100 | 35% | Historical hotspot score 56.5/100. Top fragile file is 'payments/transaction.py' with 9 bug-fix/revert commit(s) out of 23 total changes (39% fix rate). |
| Cochange Anomaly | 74/100 | 30% | Co-change anomaly score 74.2/100. 'payments/transaction.py' historically changes alongside 'payments/ledger.py' in 17 commits (74% confidence), but 'payments/ledger.py' was not modified in this PR. |
| Test Gap | 40/100 | 25% | Test-gap score 40.0/100. Matching tests exist for all changed sources, but 1 test file(s) were not updated in this PR. |
| Ownership | 81/100 | 10% | Ownership risk is elevated (81.3/100): PR author 'new@example.com' has few prior changes to these files (4% share). |

*Diff: `main..HEAD` ΓÇö 1 file(s) changed (+7 -2)*
</details>

---
*Regression Radar ΓÇö PR-time, history-aware risk analysis*
