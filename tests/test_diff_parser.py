"""
tests/test_diff_parser.py — Unit tests for diff_parser.py

Tests operate purely on diff strings — no Git subprocess calls needed.
"""

from __future__ import annotations

from regression_radar.diff_parser import (
    ChangeType,
    DiffHunk,
    FileDiff,
    ParsedDiff,
    parse_diff,
)

# ---------------------------------------------------------------------------
# Helpers — canned diff strings
# ---------------------------------------------------------------------------

SIMPLE_MODIFY = """\
diff --git a/src/app.py b/src/app.py
index abc1234..def5678 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 def main():
-    return 'hello'
+    return 'Hello, World!'
 
"""

TWO_FILE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index abc..def 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
 y = 3
diff --git a/src/utils.py b/src/utils.py
index 111..222 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,1 +1,2 @@
 def helper():
+    return True
"""

NEW_FILE_DIFF = """\
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,3 @@
+def new_func():
+    pass
+
"""

DELETED_FILE_DIFF = """\
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
index abc..000 100644
--- a/src/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old():
-    pass
"""

RENAME_DIFF = """\
diff --git a/src/legacy.py b/src/modern.py
similarity index 90%
rename from src/legacy.py
rename to src/modern.py
index abc..def 100644
--- a/src/legacy.py
+++ b/src/modern.py
@@ -1,2 +1,2 @@
-def legacy():
+def modern():
     pass
"""

BINARY_DIFF = """\
diff --git a/assets/logo.png b/assets/logo.png
index abc..def 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""

MULTI_HUNK_DIFF = """\
diff --git a/src/large.py b/src/large.py
index abc..def 100644
--- a/src/large.py
+++ b/src/large.py
@@ -1,4 +1,4 @@
 line1
-line2_old
+line2_new
 line3
 line4
@@ -10,4 +10,4 @@
 line10
-line11_old
+line11_new
 line12
 line13
"""

EMPTY_DIFF = ""


# ---------------------------------------------------------------------------
# parse_diff — basic behaviour
# ---------------------------------------------------------------------------


class TestParseDiff:
    def test_empty_string_returns_empty(self) -> None:
        result = parse_diff(EMPTY_DIFF)
        assert isinstance(result, ParsedDiff)
        assert result.files == []

    def test_whitespace_only_returns_empty(self) -> None:
        result = parse_diff("   \n\n  ")
        assert result.files == []

    def test_single_modified_file(self) -> None:
        result = parse_diff(SIMPLE_MODIFY)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.path == "src/app.py"
        assert f.change_type == ChangeType.MODIFIED
        assert not f.is_binary
        assert f.old_path is None  # same path — no rename

    def test_single_modified_file_hunk_counts(self) -> None:
        result = parse_diff(SIMPLE_MODIFY)
        f = result.files[0]
        assert len(f.hunks) == 1
        assert f.total_additions == 1
        assert f.total_deletions == 1

    def test_two_file_diff(self) -> None:
        result = parse_diff(TWO_FILE_DIFF)
        assert len(result.files) == 2
        paths = {f.path for f in result.files}
        assert paths == {"src/app.py", "src/utils.py"}

    def test_two_file_changed_paths_property(self) -> None:
        result = parse_diff(TWO_FILE_DIFF)
        assert "src/app.py" in result.changed_paths
        assert "src/utils.py" in result.changed_paths

    def test_new_file_change_type(self) -> None:
        result = parse_diff(NEW_FILE_DIFF)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.change_type == ChangeType.ADDED
        assert f.path == "src/new_module.py"

    def test_new_file_additions(self) -> None:
        result = parse_diff(NEW_FILE_DIFF)
        f = result.files[0]
        assert f.total_additions == 3
        assert f.total_deletions == 0

    def test_deleted_file_change_type(self) -> None:
        result = parse_diff(DELETED_FILE_DIFF)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.change_type == ChangeType.DELETED

    def test_deleted_file_deletions(self) -> None:
        result = parse_diff(DELETED_FILE_DIFF)
        f = result.files[0]
        assert f.total_additions == 0
        assert f.total_deletions == 2

    def test_renamed_file_change_type(self) -> None:
        result = parse_diff(RENAME_DIFF)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.change_type == ChangeType.RENAMED

    def test_renamed_file_paths(self) -> None:
        result = parse_diff(RENAME_DIFF)
        f = result.files[0]
        assert f.path == "src/modern.py"
        assert f.old_path == "src/legacy.py"

    def test_binary_file(self) -> None:
        result = parse_diff(BINARY_DIFF)
        assert len(result.files) == 1
        f = result.files[0]
        assert f.is_binary is True
        assert f.change_type == ChangeType.BINARY
        assert f.path == "assets/logo.png"

    def test_binary_file_no_hunks(self) -> None:
        result = parse_diff(BINARY_DIFF)
        f = result.files[0]
        assert f.hunks == []
        assert f.total_additions == 0
        assert f.total_deletions == 0

    def test_multi_hunk_file(self) -> None:
        result = parse_diff(MULTI_HUNK_DIFF)
        assert len(result.files) == 1
        f = result.files[0]
        assert len(f.hunks) == 2

    def test_multi_hunk_totals(self) -> None:
        result = parse_diff(MULTI_HUNK_DIFF)
        f = result.files[0]
        # Each hunk has 1 addition and 1 deletion
        assert f.total_additions == 2
        assert f.total_deletions == 2
        assert f.total_changes == 4

    def test_aggregate_totals(self) -> None:
        result = parse_diff(TWO_FILE_DIFF)
        # app.py: +1 -1; utils.py: +1 -0
        assert result.total_additions == 2
        assert result.total_deletions == 1


# ---------------------------------------------------------------------------
# DiffHunk
# ---------------------------------------------------------------------------


class TestDiffHunk:
    def test_hunk_addition_count(self) -> None:
        hunk = DiffHunk(
            old_start=1,
            old_count=2,
            new_start=1,
            new_count=3,
            header="@@ -1,2 +1,3 @@",
            lines=[" context", "-removed", "+added1", "+added2"],
        )
        assert hunk.additions == 2
        assert hunk.deletions == 1

    def test_hunk_empty_lines(self) -> None:
        hunk = DiffHunk(
            old_start=1,
            old_count=0,
            new_start=1,
            new_count=0,
            header="@@ -1 +1 @@",
            lines=[],
        )
        assert hunk.additions == 0
        assert hunk.deletions == 0


# ---------------------------------------------------------------------------
# FileDiff.summary()
# ---------------------------------------------------------------------------


class TestFileDiffSummary:
    def test_summary_normal_file(self) -> None:
        fd = FileDiff(
            path="src/app.py",
            old_path=None,
            change_type=ChangeType.MODIFIED,
            hunks=[DiffHunk(1, 2, 1, 3, "@@ @@", ["-old", "+new1", "+new2"])],
        )
        s = fd.summary()
        assert "src/app.py" in s
        assert "+2" in s
        assert "-1" in s

    def test_summary_binary(self) -> None:
        fd = FileDiff(
            path="img.png",
            old_path=None,
            change_type=ChangeType.BINARY,
            is_binary=True,
        )
        assert "[binary]" in fd.summary()

    def test_summary_renamed(self) -> None:
        fd = FileDiff(
            path="src/new.py",
            old_path="src/old.py",
            change_type=ChangeType.RENAMED,
        )
        s = fd.summary()
        assert "src/old.py" in s
        assert "src/new.py" in s


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_diff_with_no_hunk_lines_produces_zero_counts(self) -> None:
        diff = """\
diff --git a/f.py b/f.py
index abc..def 100644
--- a/f.py
+++ b/f.py
@@ -1 +1 @@
"""
        result = parse_diff(diff)
        assert len(result.files) == 1
        f = result.files[0]
        # Hunk header found but no actual +/- lines
        assert f.total_additions == 0
        assert f.total_deletions == 0

    def test_large_number_of_files(self) -> None:
        """Parser should handle many files without crashing."""
        blocks = []
        for i in range(50):
            blocks.append(f"""\
diff --git a/file_{i}.py b/file_{i}.py
index abc..def 100644
--- a/file_{i}.py
+++ b/file_{i}.py
@@ -1,1 +1,1 @@
-old_{i}
+new_{i}
""")
        result = parse_diff("\n".join(blocks))
        assert len(result.files) == 50
