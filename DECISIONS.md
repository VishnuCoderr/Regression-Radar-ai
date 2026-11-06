# DECISIONS.md — Technical decisions

---

## D-001: Python subprocess over pure GitPython for log extraction

**Date:** 2026-11-06  
**Decision:** Use `subprocess` to call `git log` / `git diff` with `--format` flags for primary
history extraction. Use GitPython only for path validation and repo detection.  
**Rationale:** `git log --format=...` output is stable, documented, and faster than GitPython's
object traversal for large repos. Subprocess also works in environments where the C extension
is unavailable.  
**Trade-off:** More manual parsing; mitigated by well-unit-tested parsers.

---

## D-002: Pydantic v2 for all data contracts

**Date:** 2026-11-06  
**Decision:** Every inter-module data structure uses a `pydantic.BaseModel`.  
**Rationale:** Provides automatic validation, clear schemas, and free JSON serialisation.
Catches integration bugs early.  
**Trade-off:** Minor overhead; acceptable for a CLI tool that isn't hot-path bound.

---

## D-003: Bug-fix commit heuristics — keyword-based, configurable

**Date:** 2026-11-06  
**Decision:** A commit is a "bug-fix candidate" if its message matches configurable regex
patterns (default: `fix`, `bug`, `defect`, `revert`, `hotfix`, `patch`, `regression`).
Case-insensitive. Matching is done on the first line (subject) only to avoid false positives
from body/footer text.  
**Rationale:** Conventional commit subject lines are the most reliable signal. Full-body
matching generates too many false positives (e.g. commit messages that mention "fix" in a
feature description).  
**Limitations:** Teams that don't use keywords in subject lines will produce low signal.
Document this prominently.

---

## D-004: Risk score is a prioritisation score, not a failure probability

**Date:** 2026-11-06  
**Decision:** All user-facing copy calls the output a "risk-prioritisation score". The
documentation explicitly states it is not a calibrated probability of production failure.  
**Rationale:** Miscalibrated probability claims are misleading and potentially harmful.

---

## D-005: Default scoring weights are hypotheses, not empirically validated

**Date:** 2026-11-06  
**Decision:** Default weights (hotspot 35 %, co-change 30 %, test-gap 25 %, ownership 10 %)
are engineering judgement starting points. Document this everywhere they appear.  
**Future:** Phase 6 evaluation will measure whether the weights correlate with actual
regression outcomes on the demo repository.

---

## D-006: Merge commits excluded from bug-fix signal by default

**Date:** 2026-11-06  
**Decision:** Merge commits (commits with more than one parent) are excluded from the
bug-fix frequency count by default. They are still used for co-change analysis (files
touched together in a merge are related).  
**Rationale:** Merge commit messages (e.g. "Merge pull request #123") frequently contain
keywords like "fix" but do not represent direct bug-fix activity on specific files.

---

## D-007: Shallow clone detection

**Date:** 2026-11-06  
**Decision:** Detect shallow clones by checking for `shallow` file in `.git/` or by counting
commits. Emit a `DataQuality.LOW` warning on all signals when fewer than 30 commits are
available.  
**Rationale:** Hotspot and co-change analysis require sufficient history to be meaningful.
Silently returning results on 3-commit histories is misleading.
