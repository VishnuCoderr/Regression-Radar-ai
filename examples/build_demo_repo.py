"""
build_demo_repo.py — Creates a controlled, reproducible demo repository.

Recreates the exact hackathon scenario shown in the Regression Radar architecture:
- payments.ts (hotspot with multiple bug fixes and reverts)
- payments.test.ts & refunds.ts (frequent co-change partners)
- PR modifies payments.ts only, omitting tests and refunds
- Demonstrates hotspot detection, co-change anomaly, test gap, and ownership intelligence.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _handle_remove_readonly(func, path, exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def create_demo_repository(target_dir: Path) -> None:
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

    def write_file(rel_path: str, content: str) -> None:
        f = target_dir / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")

    def commit(
        msg: str,
        author_name: str = "Ananya Sharma",
        author_email: str = "ananya@example.com",
    ) -> None:
        git("add", "-A")
        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
        git("commit", "-m", msg, env=env)

    # Initialize repository on main
    git("init", "-b", "main")
    git("config", "user.name", "Ananya Sharma")
    git("config", "user.email", "ananya@example.com")

    # 1. Initial Scaffold
    write_file(
        "src/payments.ts",
        "export function processPayment(amount: number): boolean {\n  return amount > 0;\n}\n",
    )
    write_file(
        "src/refunds.ts",
        "export function processRefund(id: string): boolean {\n  return true;\n}\n",
    )
    write_file(
        "tests/payments.test.ts",
        "import { processPayment } from '../src/payments';\n"
        "test('pays', () => expect(processPayment(10)).toBe(true));\n",
    )
    write_file("src/users.ts", "export const user = {};\n")
    commit("feat: initial payment and refund engine scaffold")

    # 2. Add features to payments, refunds, and tests together (building co-change)
    for i in range(1, 9):
        write_file(
            "src/payments.ts",
            f"export function processPayment(amount: number): boolean {{\n"
            f"  // v{i}\n  return amount > 0;\n}}\n",
        )
        write_file(
            "src/refunds.ts",
            f"export function processRefund(id: string): boolean {{\n"
            f"  // v{i}\n  return true;\n}}\n",
        )
        write_file("tests/payments.test.ts", f"test('v{i}', () => true);\n")
        commit(f"feat: payment and refund integration pipeline update {i}")

    # 3. Multiple bug fixes on payments.ts (building hotspot)
    write_file(
        "src/payments.ts",
        "// fix: timeout retry\nexport function processPayment(amount: number) { return true; }\n",
    )
    commit("fix: payment gateway timeout and retry backoff")

    write_file(
        "src/payments.ts",
        "// fix: duplicate\nexport function processPayment(amount: number) { return true; }\n",
    )
    commit("fix: resolve duplicate charge race condition")

    write_file(
        "src/payments.ts",
        "// revert: webhook\nexport function processPayment(amount: number) { return true; }\n",
    )
    commit("revert: roll back experimental webhook handler")

    write_file(
        "src/payments.ts",
        "// fix: rounding\nexport function processPayment(amount: number) { return true; }\n",
    )
    commit("fix: precision rounding error on multicurrency settlements")

    write_file(
        "src/payments.ts",
        "// bug: idempotency\nexport function processPayment(amount: number) { return true; }\n",
    )
    commit("bug: resolve idempotency key verification defect")

    # Add other commit activity
    for i in range(5):
        write_file("src/users.ts", f"export const user{i} = {{ id: {i} }};\n")
        commit(
            f"chore: update user models {i}",
            author_name="Dev",
            author_email="dev@example.com",
        )

    # 4. Now create feature branch 'feature/payment-v2' (the proposed PR)
    git("checkout", "-b", "feature/payment-v2")

    # In this PR, a new developer modifies payments.ts, but forgets refunds.ts and tests!
    write_file(
        "src/payments.ts",
        "// PR change: refactor payment gateway routing\n"
        "export function processPayment(amount: number) {\n  return amount > 10;\n}\n",
    )
    commit(
        "refactor: update payment routing logic",
        author_name="Junior Dev",
        author_email="junior@example.com",
    )

    print(f"Demo repository created successfully at {target_dir}")
    print("Branch 'feature/payment-v2' is checked out and ready for analysis against 'main'.")


if __name__ == "__main__":
    demo_path = Path(__file__).resolve().parent / "demo-repo"
    create_demo_repository(demo_path)
