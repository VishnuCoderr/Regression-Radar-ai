"""
build_high_risk_demo.py — Creates a HIGH-RISK reproducible demonstration repository.

Scenario: payment-service monorepo with a critical transaction-processing engine.

What makes this HIGH risk:
1. Historical Hotspot: payments/transaction.py has 9 bug-fix / revert commits
   out of ~25 total touches (~36% fix rate) — well above the repo baseline.
2. Co-change Anomaly: transaction.py historically changes alongside
   payments/ledger.py and payments/audit.py in >80% of commits,
   but the PR modifies only transaction.py.
3. Test Gap: tests/test_transaction.py and tests/test_ledger.py are both
   matched test files, neither is touched in the PR.
4. Ownership: The PR is authored by a developer (new@example.com) with zero
   prior commits on this module.

The PR itself simulates a realistic regression-prone change: switching a
> comparison to >= in amount validation, which silently allows zero-value
transactions to pass — a real class of payment-processing regression.

Nothing in this scenario manipulates the scoring engine or thresholds.
The score emerges from the actual Git history.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _handle_remove_readonly(func, path, exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def create_high_risk_demo(target_dir: Path) -> None:
    if target_dir.exists():
        import shutil
        shutil.rmtree(target_dir, onerror=_handle_remove_readonly)

    target_dir.mkdir(parents=True, exist_ok=True)

    def git(*args: str, env: dict[str, str] | None = None) -> None:
        full_env = {**os.environ, **(env or {})}
        res = subprocess.run(
            ["git", *args],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            env=full_env,
        )
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr}")

    def write(rel: str, content: str) -> None:
        p = target_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def commit(msg: str, name: str = "Priya Kapoor", email: str = "priya@example.com") -> None:
        git("add", "-A")
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        git("commit", "-m", msg, env=env)

    git("init", "-b", "main")
    git("config", "user.name", "Priya Kapoor")
    git("config", "user.email", "priya@example.com")

    # -------------------------------------------------------------------------
    # Stage 1: Initial scaffold — transaction engine + ledger + audit + tests
    # -------------------------------------------------------------------------
    write("payments/transaction.py", """\
\"\"\"Core transaction processing engine.\"\"\"


def process_transaction(amount: float, currency: str) -> dict:
    \"\"\"Process a payment transaction and return a result dict.\"\"\"
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return {"status": "ok", "amount": amount, "currency": currency}
""")
    write("payments/ledger.py", """\
\"\"\"Double-entry ledger for recording transactions.\"\"\"


def record_entry(txn_id: str, amount: float, account: str) -> bool:
    \"\"\"Write a ledger entry. Returns True on success.\"\"\"
    return bool(txn_id and amount and account)
""")
    write("payments/audit.py", """\
\"\"\"Audit log for all payment events.\"\"\"


def log_event(event_type: str, payload: dict) -> None:
    \"\"\"Append a structured audit event.\"\"\"
    _ = (event_type, payload)  # Persist to audit store
""")
    write("payments/__init__.py", "")
    write("tests/__init__.py", "")
    write("tests/test_transaction.py", """\
\"\"\"Tests for the transaction processing engine.\"\"\"
import pytest
from payments.transaction import process_transaction


def test_positive_amount_succeeds():
    result = process_transaction(100.0, "USD")
    assert result["status"] == "ok"


def test_zero_amount_raises():
    with pytest.raises(ValueError):
        process_transaction(0, "USD")


def test_negative_amount_raises():
    with pytest.raises(ValueError):
        process_transaction(-50.0, "USD")
""")
    write("tests/test_ledger.py", """\
\"\"\"Tests for the double-entry ledger.\"\"\"
from payments.ledger import record_entry


def test_valid_entry_returns_true():
    assert record_entry("TXN-001", 100.0, "acc-A") is True
""")
    write("tests/test_audit.py", """\
\"\"\"Tests for the audit log.\"\"\"
from payments.audit import log_event


def test_log_event_does_not_raise():
    log_event("PAYMENT", {"amount": 100})
""")
    write("README.md", "# Payment Service\n")
    commit("feat: initial payment transaction engine scaffold")

    # -------------------------------------------------------------------------
    # Stage 2: Build co-change relationship — transaction + ledger + audit
    # always change together across 12 commits (~80% confidence target)
    # -------------------------------------------------------------------------
    for i in range(1, 13):
        write("payments/transaction.py", f"""\
\"\"\"Core transaction processing engine — v{i}.\"\"\"


def process_transaction(amount: float, currency: str) -> dict:
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return {{"status": "ok", "amount": amount, "currency": currency, "version": {i}}}
""")
        write("payments/ledger.py", f"""\
\"\"\"Double-entry ledger — v{i}.\"\"\"


def record_entry(txn_id: str, amount: float, account: str) -> bool:
    return bool(txn_id and amount > 0 and account)  # v{i}
""")
        write("payments/audit.py", f"""\
\"\"\"Audit log — v{i}.\"\"\"


def log_event(event_type: str, payload: dict) -> None:
    _ = (event_type, payload)  # v{i}
""")
        write("tests/test_transaction.py", f"""\
\"\"\"Tests for transaction engine v{i}.\"\"\"
import pytest
from payments.transaction import process_transaction


def test_positive_amount_succeeds():
    result = process_transaction(100.0, "USD")
    assert result["status"] == "ok"
    assert result["version"] == {i}


def test_zero_amount_raises():
    with pytest.raises(ValueError):
        process_transaction(0, "USD")
""")
        commit(f"feat: transaction-ledger-audit pipeline iteration {i}")

    # Restore clean test (no version assertion) so main branch tests are stable
    write("tests/test_transaction.py", """\
\"\"\"Tests for the transaction processing engine.\"\"\"
import pytest
from payments.transaction import process_transaction


def test_positive_amount_succeeds():
    result = process_transaction(100.0, "USD")
    assert result["status"] == "ok"


def test_zero_amount_raises():
    with pytest.raises(ValueError):
        process_transaction(0, "USD")


def test_negative_amount_raises():
    with pytest.raises(ValueError):
        process_transaction(-50.0, "USD")
""")
    commit("chore: restore stable test suite after pipeline iterations")

    # -------------------------------------------------------------------------
    # Stage 3: Accumulate hotspot history on transaction.py
    # 9 bug-fix / revert commits — creates a dense hotspot signal
    # -------------------------------------------------------------------------
    hotspot_commits = [
        ("fix: prevent double-charge on idempotency key collision",
         "# guard: idempotency"),
        ("fix: resolve off-by-one in partial refund amount calculation",
         "# guard: partial refund"),
        ("revert: roll back experimental async transaction handler",
         "# guard: revert async"),
        ("fix: currency precision loss on EUR/GBP cross-border settlements",
         "# guard: currency precision"),
        ("fix: race condition in concurrent transaction locks",
         "# guard: concurrent locks"),
        ("bug: incorrect VAT rounding causes settlement mismatch",
         "# guard: vat rounding"),
        ("fix: timeout retry causes duplicate charges under high load",
         "# guard: timeout retry"),
        ("revert: undo experimental fee calculation changes",
         "# guard: revert fees"),
        ("fix: webhook callback fires before ledger commit completes",
         "# guard: webhook ordering"),
    ]
    for i, (msg, guard) in enumerate(hotspot_commits, start=13):
        write("payments/transaction.py", f"""\
\"\"\"Core transaction processing engine.\"\"\"
{guard}


def process_transaction(amount: float, currency: str) -> dict:
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return {{"status": "ok", "amount": amount, "currency": currency}}
""")
        # Every other hotfix also touches ledger (maintains co-change signal)
        if i % 2 == 0:
            write("payments/ledger.py", f"""\
\"\"\"Double-entry ledger.\"\"\"
{guard}


def record_entry(txn_id: str, amount: float, account: str) -> bool:
    return bool(txn_id and amount > 0 and account)
""")
        commit(msg)

    # -------------------------------------------------------------------------
    # Stage 4: Unrelated activity on other modules (raises total commit count,
    # lowers the repo-wide bugfix baseline, making transaction.py stand out)
    # -------------------------------------------------------------------------
    for i in range(1, 9):
        write("payments/config.py", f"""\
\"\"\"Payment configuration — v{i}.\"\"\"
TIMEOUT_MS = {1000 + i * 100}
""")
        commit(
            f"chore: update payment service config {i}",
            name="Dev Bot",
            email="bot@example.com",
        )

    # -------------------------------------------------------------------------
    # Stage 5: Create the HIGH-RISK feature branch
    # Developer modifies transaction.py only:
    #   - Changes `amount <= 0` to `amount < 0` (allows zero-value charges!)
    #   - Omits ledger.py, audit.py, test_transaction.py, test_ledger.py
    # -------------------------------------------------------------------------
    git("checkout", "-b", "feature/zero-amount-fix")

    write("payments/transaction.py", """\
\"\"\"Core transaction processing engine.\"\"\"


def process_transaction(amount: float, currency: str) -> dict:
    \"\"\"Process a payment transaction and return a result dict.

    CHANGED: Switched amount <= 0 to amount < 0 to 'allow free trials'.
    This silently passes zero-value transactions to the payment gateway,
    which can trigger settlement errors and duplicate-charge reconciliation.
    \"\"\"
    if amount < 0:  # BUG: was `<= 0` — zero amounts now pass through!
        raise ValueError("Amount must be positive")
    return {"status": "ok", "amount": amount, "currency": currency}
""")
    commit(
        "feat: allow zero-amount transactions for free-trial support",
        name="New Developer",
        email="new@example.com",
    )

    print(f"\nHigh-risk demo repository created at: {target_dir}")
    print("Branch: feature/zero-amount-fix  |  Base: main")
    print("\nReproduce analysis with:")
    print(f"  python -m regression_radar.cli analyse {target_dir} \\")
    print("    --base main --author new@example.com --format terminal")
    print(f"  python -m regression_radar.cli analyse {target_dir} \\")
    print("    --base main --author new@example.com --format markdown")


if __name__ == "__main__":
    demo_path = Path(__file__).resolve().parent / "high-risk-demo"
    create_high_risk_demo(demo_path)
