"""
diff_parser.py — Parse unified diff text into structured FileDiff objects.

Handles:
- Standard unified diff format (--- / +++ / @@ headers)
- Renames and copies (diff --find-renames output)
- Binary files
- New / deleted files
- Multiple hunks per file
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ChangeType(StrEnum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"
    COPIED = "copied"
    BINARY = "binary"
    TYPE_CHANGED = "type_changed"


@dataclass
class DiffHunk:
    """A single @@ hunk within a file diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str  # The raw @@ line (may contain function context)
    lines: list[str] = field(default_factory=list)  # Raw diff lines (+/-/ )

    @property
    def additions(self) -> int:
        return sum(1 for ln in self.lines if ln.startswith("+"))

    @property
    def deletions(self) -> int:
        return sum(1 for ln in self.lines if ln.startswith("-"))


@dataclass
class FileDiff:
    """Structured diff for a single file."""

    path: str  # Current path of the file
    old_path: str | None  # Previous path (for renames/copies)
    change_type: ChangeType
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False

    @property
    def total_additions(self) -> int:
        return sum(h.additions for h in self.hunks)

    @property
    def total_deletions(self) -> int:
        return sum(h.deletions for h in self.hunks)

    @property
    def total_changes(self) -> int:
        return self.total_additions + self.total_deletions

    def summary(self) -> str:
        if self.is_binary:
            return f"{self.path} [binary]"
        parts = []
        if self.old_path and self.old_path != self.path:
            parts.append(f"{self.old_path} → {self.path}")
        else:
            parts.append(self.path)
        parts.append(
            f"+{self.total_additions} -{self.total_deletions} "
            f"({len(self.hunks)} hunk{'s' if len(self.hunks) != 1 else ''})"
        )
        return "  ".join(parts)


@dataclass
class ParsedDiff:
    """Collection of FileDiff objects from a full diff."""

    files: list[FileDiff] = field(default_factory=list)

    @property
    def changed_paths(self) -> list[str]:
        return [f.path for f in self.files]

    @property
    def total_additions(self) -> int:
        return sum(f.total_additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.total_deletions for f in self.files)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Matches: diff --git a/path b/path
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")

# Matches: similarity index NN%
_SIMILARITY_RE = re.compile(r"^similarity index (\d+)%")

# Matches: rename from path / rename to path
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (.+)$")

# Matches: copy from / copy to
_COPY_FROM_RE = re.compile(r"^copy from (.+)$")
_COPY_TO_RE = re.compile(r"^copy to (.+)$")

# Matches: new file mode / deleted file mode
_NEW_FILE_RE = re.compile(r"^new file mode")
_DELETED_FILE_RE = re.compile(r"^deleted file mode")

# Matches: Binary files ... differ
_BINARY_RE = re.compile(r"^Binary files")

# Matches: @@ -old_start[,old_count] +new_start[,new_count] @@[ context]
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")


def parse_diff(diff_text: str) -> ParsedDiff:
    """
    Parse a unified diff string into a ParsedDiff.

    Parameters
    ----------
    diff_text:
        Output of ``git diff --unified=3 --find-renames ...``.

    Returns
    -------
    ParsedDiff
        Structured representation; empty if *diff_text* is blank.
    """
    if not diff_text or not diff_text.strip():
        return ParsedDiff()

    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None

    lines = diff_text.splitlines()
    i = 0

    def _save_hunk() -> None:
        if current_hunk is not None and current_file is not None:
            current_file.hunks.append(current_hunk)

    while i < len(lines):
        line = lines[i]

        # --- New file block ---
        m = _DIFF_HEADER_RE.match(line)
        if m:
            _save_hunk()
            if current_file is not None:
                files.append(current_file)

            # Start a new FileDiff with defaults
            path_a = m.group(1)
            path_b = m.group(2)
            current_file = FileDiff(
                path=path_b,
                old_path=path_a if path_a != path_b else None,
                change_type=ChangeType.MODIFIED,
            )
            current_hunk = None
            i += 1
            continue

        if current_file is None:
            i += 1
            continue

        # --- File-level metadata lines ---
        if _NEW_FILE_RE.match(line):
            current_file.change_type = ChangeType.ADDED
        elif _DELETED_FILE_RE.match(line):
            current_file.change_type = ChangeType.DELETED
        elif _BINARY_RE.match(line):
            current_file.is_binary = True
            current_file.change_type = ChangeType.BINARY
        elif _RENAME_FROM_RE.match(line):
            m2 = _RENAME_FROM_RE.match(line)
            if m2:
                current_file.old_path = m2.group(1)
                current_file.change_type = ChangeType.RENAMED
        elif _RENAME_TO_RE.match(line):
            m2 = _RENAME_TO_RE.match(line)
            if m2:
                current_file.path = m2.group(1)
                current_file.change_type = ChangeType.RENAMED
        elif _COPY_FROM_RE.match(line):
            m2 = _COPY_FROM_RE.match(line)
            if m2:
                current_file.old_path = m2.group(1)
                current_file.change_type = ChangeType.COPIED
        elif _COPY_TO_RE.match(line):
            m2 = _COPY_TO_RE.match(line)
            if m2:
                current_file.path = m2.group(1)
                current_file.change_type = ChangeType.COPIED

        # --- Hunk header ---
        elif m3 := _HUNK_HEADER_RE.match(line):
            _save_hunk()
            old_start = int(m3.group(1))
            old_count = int(m3.group(2)) if m3.group(2) is not None else 1
            new_start = int(m3.group(3))
            new_count = int(m3.group(4)) if m3.group(4) is not None else 1
            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                header=line,
                lines=[],
            )

        # --- Diff content lines ---
        elif current_hunk is not None and (
            line.startswith("+")
            or line.startswith("-")
            or line.startswith(" ")
            or line == "\\ No newline at end of file"
        ):
            # Skip +++ / --- file headers (they start with +++ or ---)
            if not (line.startswith("+++") or line.startswith("---")):
                current_hunk.lines.append(line)

        i += 1

    # Flush last records
    _save_hunk()
    if current_file is not None:
        files.append(current_file)

    return ParsedDiff(files=files)
