"""
test_gap.py — Test-gap detection.

Identifies source files modified without corresponding test coverage, using
naming conventions, directory mirroring, and historical co-change patterns.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import PurePosixPath

from regression_radar.git_history import CommitInfo, DataQuality
from regression_radar.models import SignalResult, TestGapEvidence

logger = logging.getLogger(__name__)

NON_SOURCE_EXTS = {
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
    ".ico",
    ".lock",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
}


def is_test_file(path_str: str) -> bool:
    """Return True if *path_str* points to a test file."""
    p = PurePosixPath(path_str)
    stem = p.stem.lower()
    name = p.name.lower()
    parts = [part.lower() for part in p.parts]

    test_dirs = ("test", "tests", "__tests__", "testing", "spec", "specs")
    in_test_dir = any(d in parts for d in test_dirs)

    has_test_prefix = stem.startswith("test_") or stem.startswith("test-")
    has_test_suffix = (
        stem.endswith("_test") or stem.endswith("-test") or ".test." in name or ".spec." in name
    )

    return in_test_dir or has_test_prefix or has_test_suffix


def is_source_file(path_str: str) -> bool:
    """Return True if *path_str* is a substantive source file."""
    p = PurePosixPath(path_str)
    if is_test_file(path_str):
        return False
    if p.suffix.lower() in NON_SOURCE_EXTS:
        return False
    if p.name.startswith("."):
        return False
    return p.suffix.lower() in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
    }


def find_candidate_test_paths(source_path_str: str) -> list[str]:
    """Generate likely candidate test paths for a source file based on conventions."""
    p = PurePosixPath(source_path_str)
    stem = p.stem
    ext = p.suffix
    candidates: list[str] = []

    parent = p.parent
    candidates.append(str(parent / f"test_{stem}{ext}"))
    candidates.append(str(parent / f"{stem}_test{ext}"))
    candidates.append(str(parent / f"{stem}.test{ext}"))
    candidates.append(str(parent / f"{stem}.spec{ext}"))

    parts = list(p.parts)
    if parts and parts[0] in ("src", "lib", "app"):
        mirror_parts = ["tests"] + parts[1:-1] + [f"test_{stem}{ext}"]
        candidates.append("/".join(mirror_parts))
        direct_tests = ["tests", f"test_{stem}{ext}"]
        candidates.append("/".join(direct_tests))
    else:
        candidates.append(f"tests/test_{stem}{ext}")
        candidates.append(f"test/test_{stem}{ext}")

    return candidates


def calculate_test_gap_signal(
    changed_files: Sequence[str],
    commits: Sequence[CommitInfo],
    repo_files: Sequence[str] | None = None,
    data_quality: DataQuality = DataQuality.HIGH,
    renames: dict[str, str] | None = None,
    deleted_files: Sequence[str] | None = None,
) -> SignalResult:
    """Evaluate test coverage gaps in a proposed change set."""
    changed_set = set(changed_files)
    changed_sources = [f for f in changed_files if is_source_file(f)]
    changed_tests = [f for f in changed_files if is_test_file(f)]
    deleted_set = set(deleted_files or [])

    if not changed_sources:
        return SignalResult(
            name="test_gap",
            score=0.0,
            explanation="No primary source files were modified in this PR; test gap is zero.",
            data_quality=data_quality,
            is_available=True,
            evidence={
                "changed_sources": [],
                "changed_tests": changed_tests,
                "untested_files": [],
            },
        )

    all_known_files = set(repo_files or [])
    if not all_known_files:
        for c in commits:
            all_known_files.update(c.changed_files)
    all_known_files.update(changed_set)

    source_to_cochange_tests: dict[str, dict[str, int]] = {}
    for c in commits:
        c_tests = [f for f in c.changed_files if is_test_file(f)]
        c_sources = [f for f in c.changed_files if is_source_file(f)]
        for s in c_sources:
            if s not in source_to_cochange_tests:
                source_to_cochange_tests[s] = {}
            for t in c_tests:
                source_to_cochange_tests[s][t] = source_to_cochange_tests[s].get(t, 0) + 1

    evidences: list[TestGapEvidence] = []
    file_penalties: list[float] = []

    for src in changed_sources:
        matched_test: str | None = None
        strategy = "none"

        candidates = find_candidate_test_paths(src)
        if renames and src in renames:
            candidates.extend(find_candidate_test_paths(renames[src]))

        for cand in candidates:
            norm_cand = cand.replace("\\", "/")
            matching_in_repo = [k for k in all_known_files if k.replace("\\", "/") == norm_cand]
            if matching_in_repo:
                matched_test = matching_in_repo[0]
                strategy = "name_convention"
                break

        if matched_test is None:
            old_src = renames.get(src) if renames else None
            lookup_sources = [src] + ([old_src] if old_src else [])
            for s_key in lookup_sources:
                if s_key in source_to_cochange_tests:
                    cochange_tests = source_to_cochange_tests[s_key]
                    if cochange_tests:
                        best_test = max(cochange_tests.items(), key=lambda kv: kv[1])[0]
                        matched_test = best_test
                        strategy = "cochange"
                        break

        is_test_in_pr = matched_test is not None and matched_test in changed_set
        is_deleted = src in deleted_set

        if matched_test is None:
            penalty = 0.0 if is_deleted else 75.0
        elif is_test_in_pr:
            penalty = 0.0
        else:
            penalty = 40.0

        file_penalties.append(penalty)
        evidences.append(
            TestGapEvidence(
                source_file=src,
                matched_test_file=matched_test,
                test_modified_in_pr=is_test_in_pr,
                match_strategy=strategy,
            )
        )

    max_penalty = max(file_penalties) if file_penalties else 0.0
    avg_penalty = sum(file_penalties) / len(file_penalties) if file_penalties else 0.0
    score = min(100.0, round(0.60 * max_penalty + 0.40 * avg_penalty, 1))

    recommendations: list[str] = []
    missing_tests = [e for e in evidences if e.matched_test_file is None]
    untouched_tests = [e for e in evidences if e.matched_test_file and not e.test_modified_in_pr]

    if score == 0.0:
        explanation = (
            f"All {len(changed_sources)} modified source file(s) have matching test updates in PR."
        )
    elif missing_tests:
        explanation = (
            f"Test-gap score {score}/100. Found {len(missing_tests)} source file(s) "
            "with no matching test file in the repository."
        )
        for m in missing_tests[:3]:
            recommendations.append(f"Add test coverage for '{m.source_file}' (no test file found).")
    elif untouched_tests:
        explanation = (
            f"Test-gap score {score}/100. Matching tests exist for all changed sources, "
            f"but {len(untouched_tests)} test file(s) were not updated in this PR."
        )
        for u in untouched_tests[:3]:
            recommendations.append(
                f"Verify or run '{u.matched_test_file}', which covers '{u.source_file}' "
                "but was not modified."
            )
    else:
        explanation = f"Test-gap score {score}/100 across {len(changed_sources)} modified file(s)."

    return SignalResult(
        name="test_gap",
        score=score,
        explanation=explanation,
        data_quality=data_quality,
        is_available=True,
        evidence={
            "changed_sources_count": len(changed_sources),
            "changed_tests_count": len(changed_tests),
            "files": [e.model_dump() for e in evidences],
        },
        recommendations=recommendations,
    )
