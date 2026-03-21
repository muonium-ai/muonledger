"""Tests for the CLOC report script."""

import json
import os
import sys
import tempfile
import textwrap

import pytest

# Add scripts directory to path so we can import the module
# tests/ -> python/ -> port/ then into scripts/
SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
)
sys.path.insert(0, SCRIPTS_DIR)

import cloc_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(directory: str, name: str, content: str) -> str:
    """Write a file with the given content and return its path."""
    filepath = os.path.join(directory, name)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


# ---------------------------------------------------------------------------
# Python line counting
# ---------------------------------------------------------------------------

class TestPythonLineCounting:
    """Test line counting for Python files."""

    def test_simple_python_code(self, tmp_path):
        fp = _write_file(str(tmp_path), "simple.py", textwrap.dedent("""\
            x = 1
            y = 2
            z = x + y
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 3
        assert result["comments"] == 0
        assert result["blanks"] == 0
        assert result["total"] == 3

    def test_python_line_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "comments.py", textwrap.dedent("""\
            # This is a comment
            x = 1
            # Another comment
            y = 2
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 2
        assert result["comments"] == 2
        assert result["blanks"] == 0
        assert result["total"] == 4

    def test_python_blank_lines(self, tmp_path):
        fp = _write_file(str(tmp_path), "blanks.py", "x = 1\n\ny = 2\n\n\nz = 3\n")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 3
        assert result["blanks"] == 3
        assert result["total"] == 6

    def test_python_docstring_multiline(self, tmp_path):
        fp = _write_file(str(tmp_path), "docstring.py", textwrap.dedent('''\
            """
            This is a docstring.
            It spans multiple lines.
            """
            x = 1
        '''))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 4
        assert result["code"] == 1
        assert result["total"] == 5

    def test_python_single_line_docstring(self, tmp_path):
        fp = _write_file(str(tmp_path), "sldoc.py", textwrap.dedent('''\
            """Single line docstring."""
            x = 1
        '''))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 1

    def test_python_single_quote_docstring(self, tmp_path):
        fp = _write_file(str(tmp_path), "sqdoc.py", "'''docstring'''\nx = 1\n")
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 1

    def test_python_mixed(self, tmp_path):
        fp = _write_file(str(tmp_path), "mixed.py", textwrap.dedent('''\
            # Header comment

            """Module docstring."""

            def foo():
                # inline comment
                return 42
        '''))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 3  # # comment, docstring, # inline
        assert result["blanks"] == 2
        assert result["code"] == 2  # def foo(): and return 42
        assert result["total"] == 7


# ---------------------------------------------------------------------------
# Rust line counting
# ---------------------------------------------------------------------------

class TestRustLineCounting:
    """Test line counting for Rust files."""

    def test_simple_rust_code(self, tmp_path):
        fp = _write_file(str(tmp_path), "simple.rs", textwrap.dedent("""\
            fn main() {
                let x = 1;
                let y = 2;
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 4
        assert result["comments"] == 0
        assert result["blanks"] == 0

    def test_rust_line_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "comments.rs", textwrap.dedent("""\
            // This is a comment
            fn main() {
                // Another comment
                let x = 1;
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 3
        assert result["comments"] == 2

    def test_rust_block_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "block.rs", textwrap.dedent("""\
            /* Block comment
               spanning lines */
            fn main() {
                let x = 1;
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 2
        assert result["code"] == 3

    def test_rust_single_line_block_comment(self, tmp_path):
        fp = _write_file(str(tmp_path), "slblock.rs", "/* single */ \nfn main() {}\n")
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 1

    def test_rust_doc_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "doc.rs", textwrap.dedent("""\
            /// Documentation comment
            fn foo() {}
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 1

    def test_rust_blank_lines(self, tmp_path):
        fp = _write_file(str(tmp_path), "blanks.rs", "fn main() {\n\n    let x = 1;\n\n}\n")
        result = cloc_report.count_lines(fp)
        assert result["blanks"] == 2
        assert result["code"] == 3


# ---------------------------------------------------------------------------
# Kotlin line counting
# ---------------------------------------------------------------------------

class TestKotlinLineCounting:
    """Test line counting for Kotlin files."""

    def test_simple_kotlin(self, tmp_path):
        fp = _write_file(str(tmp_path), "Main.kt", textwrap.dedent("""\
            fun main() {
                val x = 1
                println(x)
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 4
        assert result["comments"] == 0

    def test_kotlin_line_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "Comments.kt", textwrap.dedent("""\
            // Comment
            fun main() {
                val x = 1
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 3

    def test_kotlin_block_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "Block.kt", textwrap.dedent("""\
            /* Block
               comment */
            fun main() {}
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 2
        assert result["code"] == 1


# ---------------------------------------------------------------------------
# Swift line counting
# ---------------------------------------------------------------------------

class TestSwiftLineCounting:
    """Test line counting for Swift files."""

    def test_simple_swift(self, tmp_path):
        fp = _write_file(str(tmp_path), "main.swift", textwrap.dedent("""\
            func main() {
                let x = 1
                print(x)
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 4
        assert result["comments"] == 0

    def test_swift_line_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "comments.swift", textwrap.dedent("""\
            // Comment
            func main() {
                let x = 1
            }
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 1
        assert result["code"] == 3

    def test_swift_block_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "block.swift", textwrap.dedent("""\
            /* Block
               comment */
            func main() {}
        """))
        result = cloc_report.count_lines(fp)
        assert result["comments"] == 2
        assert result["code"] == 1


# ---------------------------------------------------------------------------
# Directory walking and file filtering
# ---------------------------------------------------------------------------

class TestDirectoryWalking:
    """Test file discovery and directory traversal."""

    def test_find_python_files(self, tmp_path):
        _write_file(str(tmp_path), "a.py", "x = 1\n")
        _write_file(str(tmp_path), "b.py", "y = 2\n")
        _write_file(str(tmp_path), "c.txt", "not python\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 2
        assert all(f.endswith(".py") for f in files)

    def test_find_rust_files(self, tmp_path):
        _write_file(str(tmp_path), "lib.rs", "fn foo() {}\n")
        _write_file(str(tmp_path), "main.rs", "fn main() {}\n")
        files = cloc_report.find_files(str(tmp_path), ".rs")
        assert len(files) == 2

    def test_find_nested_files(self, tmp_path):
        _write_file(str(tmp_path / "sub"), "nested.py", "x = 1\n")
        _write_file(str(tmp_path), "top.py", "y = 2\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 2

    def test_skip_pycache(self, tmp_path):
        _write_file(str(tmp_path), "good.py", "x = 1\n")
        _write_file(str(tmp_path / "__pycache__"), "cached.py", "bad\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 1
        assert "good.py" in files[0]

    def test_skip_git_directory(self, tmp_path):
        _write_file(str(tmp_path), "good.py", "x = 1\n")
        _write_file(str(tmp_path / ".git"), "hidden.py", "bad\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 1

    def test_skip_target_directory(self, tmp_path):
        _write_file(str(tmp_path), "good.rs", "fn foo() {}\n")
        _write_file(str(tmp_path / "target"), "built.rs", "bad\n")
        files = cloc_report.find_files(str(tmp_path), ".rs")
        assert len(files) == 1

    def test_skip_hidden_files(self, tmp_path):
        _write_file(str(tmp_path), "good.py", "x = 1\n")
        _write_file(str(tmp_path), ".hidden.py", "bad\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 1

    def test_nonexistent_directory(self):
        files = cloc_report.find_files("/nonexistent/path", ".py")
        assert files == []

    def test_empty_directory(self, tmp_path):
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert files == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases for line counting."""

    def test_empty_file(self, tmp_path):
        fp = _write_file(str(tmp_path), "empty.py", "")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 0
        assert result["comments"] == 0
        assert result["blanks"] == 0
        assert result["total"] == 0

    def test_file_with_only_comments(self, tmp_path):
        fp = _write_file(str(tmp_path), "comments_only.py", textwrap.dedent("""\
            # Comment 1
            # Comment 2
            # Comment 3
        """))
        result = cloc_report.count_lines(fp)
        assert result["code"] == 0
        assert result["comments"] == 3
        assert result["blanks"] == 0

    def test_file_with_only_blanks(self, tmp_path):
        fp = _write_file(str(tmp_path), "blanks_only.py", "\n\n\n")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 0
        assert result["comments"] == 0
        assert result["blanks"] == 3
        assert result["total"] == 3

    def test_unknown_extension(self, tmp_path):
        fp = _write_file(str(tmp_path), "data.csv", "a,b,c\n1,2,3\n")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 0
        assert result["total"] == 0

    def test_file_with_trailing_newline(self, tmp_path):
        fp = _write_file(str(tmp_path), "trailing.py", "x = 1\n")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 1
        assert result["total"] == 1

    def test_file_without_trailing_newline(self, tmp_path):
        fp = _write_file(str(tmp_path), "notrailing.py", "x = 1")
        result = cloc_report.count_lines(fp)
        assert result["code"] == 1
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# count_directory
# ---------------------------------------------------------------------------

class TestCountDirectory:
    """Test directory-level counting."""

    def test_count_directory_basic(self, tmp_path):
        _write_file(str(tmp_path), "a.py", "x = 1\n# comment\n\n")
        _write_file(str(tmp_path), "b.py", "y = 2\n")
        result = cloc_report.count_directory(str(tmp_path), ".py")
        assert result["files"] == 2
        # a.py: code=1, comments=1, blanks=1. b.py: code=1. Total code=2
        assert result["code"] == 2
        assert result["comments"] == 1
        assert result["blanks"] == 1

    def test_count_directory_empty(self, tmp_path):
        result = cloc_report.count_directory(str(tmp_path), ".py")
        assert result["files"] == 0
        assert result["code"] == 0

    def test_count_directory_filters_extension(self, tmp_path):
        _write_file(str(tmp_path), "a.py", "x = 1\n")
        _write_file(str(tmp_path), "b.rs", "fn foo() {}\n")
        result = cloc_report.count_directory(str(tmp_path), ".py")
        assert result["files"] == 1


# ---------------------------------------------------------------------------
# JSON report format
# ---------------------------------------------------------------------------

class TestJSONReport:
    """Test JSON report generation and saving."""

    def test_report_structure(self, tmp_path):
        # Create a minimal project structure
        src = tmp_path / "port" / "python" / "src" / "muonledger"
        tests = tmp_path / "port" / "python" / "tests"
        src.mkdir(parents=True)
        tests.mkdir(parents=True)
        _write_file(str(src), "main.py", "x = 1\n")
        _write_file(str(tests), "test_main.py", "def test_x(): pass\n")

        # Create empty dirs for other ports
        for d in ["rust/src", "rust/tests", "kotlin/src", "kotlin/tests",
                   "swift/src", "swift/tests"]:
            (tmp_path / "port" / d).mkdir(parents=True, exist_ok=True)

        report = cloc_report.generate_report(str(tmp_path))
        assert "timestamp" in report
        assert "implementations" in report
        assert "python" in report["implementations"]
        assert "rust" in report["implementations"]
        assert "kotlin" in report["implementations"]
        assert "swift" in report["implementations"]

    def test_report_has_source_and_tests(self, tmp_path):
        src = tmp_path / "port" / "python" / "src" / "muonledger"
        tests = tmp_path / "port" / "python" / "tests"
        src.mkdir(parents=True)
        tests.mkdir(parents=True)
        _write_file(str(src), "mod.py", "x = 1\ny = 2\n")
        _write_file(str(tests), "test_mod.py", "def test(): pass\n")

        for d in ["rust/src", "rust/tests", "kotlin/src", "kotlin/tests",
                   "swift/src", "swift/tests"]:
            (tmp_path / "port" / d).mkdir(parents=True, exist_ok=True)

        report = cloc_report.generate_report(str(tmp_path))
        py = report["implementations"]["python"]
        assert "source" in py
        assert "tests" in py
        assert "total" in py
        assert py["source"]["files"] == 1
        assert py["source"]["code"] == 2
        assert py["tests"]["files"] == 1
        assert py["total"]["code"] == 3

    def test_save_report(self, tmp_path):
        report = {
            "timestamp": "2026-03-21T16:30:00",
            "implementations": {
                "python": {
                    "source": {"files": 1, "code": 10, "comments": 2, "blanks": 1, "total": 13},
                    "tests": {"files": 1, "code": 5, "comments": 0, "blanks": 0, "total": 5},
                    "total": {"files": 2, "code": 15, "comments": 2, "blanks": 1, "total": 18},
                },
            },
        }
        output_dir = str(tmp_path / "reports")
        filepath = cloc_report.save_report(report, output_dir)
        assert os.path.exists(filepath)
        assert filepath.endswith(".json")

        with open(filepath) as f:
            saved = json.load(f)
        assert saved["timestamp"] == "2026-03-21T16:30:00"
        assert "python" in saved["implementations"]

    def test_save_report_creates_directory(self, tmp_path):
        report = {
            "timestamp": "2026-03-21T16:30:00",
            "implementations": {},
        }
        output_dir = str(tmp_path / "new" / "dir")
        filepath = cloc_report.save_report(report, output_dir)
        assert os.path.exists(filepath)


# ---------------------------------------------------------------------------
# Table formatting
# ---------------------------------------------------------------------------

class TestTableFormatting:
    """Test table output formatting."""

    def test_format_table_basic(self):
        report = {
            "timestamp": "2026-03-21T16:30:00",
            "implementations": {
                "python": {
                    "source": {"files": 5, "code": 100, "comments": 20, "blanks": 10, "total": 130},
                    "tests": {"files": 3, "code": 50, "comments": 5, "blanks": 5, "total": 60},
                    "total": {"files": 8, "code": 150, "comments": 25, "blanks": 15, "total": 190},
                },
                "rust": {
                    "source": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "tests": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "total": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                },
                "kotlin": {
                    "source": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "tests": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "total": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                },
                "swift": {
                    "source": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "tests": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                    "total": {"files": 0, "code": 0, "comments": 0, "blanks": 0, "total": 0},
                },
            },
        }
        table = cloc_report.format_table(report)
        assert "Python" in table
        assert "Rust" in table
        assert "100" in table
        assert "50" in table

    def test_format_table_has_header(self):
        report = {
            "implementations": {
                "python": {
                    "source": {"files": 1, "code": 10},
                    "tests": {"files": 1, "code": 5},
                    "total": {"files": 2, "code": 15},
                },
            },
        }
        table = cloc_report.format_table(report)
        assert "Implementation" in table
        assert "Source Files" in table
        assert "Source LOC" in table
        assert "Test LOC" in table

    def test_format_table_ratio(self):
        report = {
            "implementations": {
                "python": {
                    "source": {"files": 5, "code": 100},
                    "tests": {"files": 3, "code": 100},
                    "total": {"files": 8, "code": 200},
                },
                "rust": {
                    "source": {"files": 3, "code": 50},
                    "tests": {"files": 1, "code": 50},
                    "total": {"files": 4, "code": 100},
                },
                "kotlin": {
                    "source": {"files": 0, "code": 0},
                    "tests": {"files": 0, "code": 0},
                    "total": {"files": 0, "code": 0},
                },
                "swift": {
                    "source": {"files": 0, "code": 0},
                    "tests": {"files": 0, "code": 0},
                    "total": {"files": 0, "code": 0},
                },
            },
        }
        table = cloc_report.format_table(report)
        assert "1.0x" in table
        assert "0.5x" in table


# ---------------------------------------------------------------------------
# Historical comparison
# ---------------------------------------------------------------------------

class TestHistoricalComparison:
    """Test comparison with previous reports."""

    def test_load_latest_report(self, tmp_path):
        # Create two reports
        r1 = {"timestamp": "2026-03-20T10:00:00", "implementations": {}}
        r2 = {"timestamp": "2026-03-21T10:00:00", "implementations": {}}

        with open(tmp_path / "cloc_2026-03-20T100000.json", "w") as f:
            json.dump(r1, f)
        with open(tmp_path / "cloc_2026-03-21T100000.json", "w") as f:
            json.dump(r2, f)

        latest = cloc_report.load_latest_report(str(tmp_path))
        assert latest["timestamp"] == "2026-03-21T10:00:00"

    def test_load_latest_report_empty_dir(self, tmp_path):
        result = cloc_report.load_latest_report(str(tmp_path))
        assert result is None

    def test_load_latest_report_nonexistent_dir(self):
        result = cloc_report.load_latest_report("/nonexistent/dir")
        assert result is None

    def test_format_comparison(self):
        current = {
            "implementations": {
                "python": {
                    "source": {"code": 110},
                    "tests": {"code": 55},
                    "total": {"code": 165},
                },
            },
        }
        previous = {
            "timestamp": "2026-03-20T10:00:00",
            "implementations": {
                "python": {
                    "source": {"code": 100},
                    "tests": {"code": 50},
                    "total": {"code": 150},
                },
            },
        }
        output = cloc_report.format_comparison(current, previous)
        assert "Python source" in output
        assert "100" in output
        assert "110" in output
        assert "+10" in output

    def test_format_comparison_new_port(self):
        current = {
            "implementations": {
                "rust": {
                    "source": {"code": 50},
                    "tests": {"code": 10},
                    "total": {"code": 60},
                },
            },
        }
        previous = {
            "timestamp": "2026-03-20T10:00:00",
            "implementations": {
                "rust": {
                    "source": {"code": 0},
                    "tests": {"code": 0},
                    "total": {"code": 0},
                },
            },
        }
        output = cloc_report.format_comparison(current, previous)
        assert "Rust source" in output
        assert "new" in output


# ---------------------------------------------------------------------------
# should_skip_dir
# ---------------------------------------------------------------------------

class TestShouldSkipDir:
    """Test directory skip logic."""

    def test_skip_pycache(self):
        assert cloc_report.should_skip_dir("__pycache__") is True

    def test_skip_git(self):
        assert cloc_report.should_skip_dir(".git") is True

    def test_skip_target(self):
        assert cloc_report.should_skip_dir("target") is True

    def test_skip_hidden(self):
        assert cloc_report.should_skip_dir(".hidden") is True

    def test_skip_egg_info(self):
        assert cloc_report.should_skip_dir("foo.egg-info") is True

    def test_no_skip_normal(self):
        assert cloc_report.should_skip_dir("src") is False

    def test_no_skip_commands(self):
        assert cloc_report.should_skip_dir("commands") is False


# ---------------------------------------------------------------------------
# Real codebase tests
# ---------------------------------------------------------------------------

class TestRealCodebase:
    """Test against the actual muonledger codebase."""

    @pytest.fixture
    def project_root(self):
        """Find the real project root."""
        here = os.path.dirname(os.path.abspath(__file__))
        # Go up from port/python/tests/ to project root
        root = os.path.normpath(os.path.join(here, "..", "..", ".."))
        if os.path.isdir(os.path.join(root, "port")):
            return root
        pytest.skip("Cannot find project root")

    def test_finds_real_python_source_files(self, project_root):
        src_dir = os.path.join(project_root, "port", "python", "src", "muonledger")
        files = cloc_report.find_files(src_dir, ".py")
        assert len(files) > 10, f"Expected >10 Python source files, got {len(files)}"

    def test_finds_real_python_test_files(self, project_root):
        test_dir = os.path.join(project_root, "port", "python", "tests")
        files = cloc_report.find_files(test_dir, ".py")
        assert len(files) > 20, f"Expected >20 Python test files, got {len(files)}"

    def test_finds_real_rust_source_files(self, project_root):
        src_dir = os.path.join(project_root, "port", "rust", "src")
        files = cloc_report.find_files(src_dir, ".rs")
        assert len(files) > 10, f"Expected >10 Rust source files, got {len(files)}"

    def test_finds_real_rust_test_files(self, project_root):
        test_dir = os.path.join(project_root, "port", "rust", "tests")
        files = cloc_report.find_files(test_dir, ".rs")
        assert len(files) > 3, f"Expected >3 Rust test files, got {len(files)}"

    def test_kotlin_empty(self, project_root):
        src_dir = os.path.join(project_root, "port", "kotlin", "src")
        files = cloc_report.find_files(src_dir, ".kt")
        assert len(files) == 0

    def test_swift_empty(self, project_root):
        src_dir = os.path.join(project_root, "port", "swift", "src")
        files = cloc_report.find_files(src_dir, ".swift")
        assert len(files) == 0

    def test_real_python_source_has_code(self, project_root):
        src_dir = os.path.join(project_root, "port", "python", "src", "muonledger")
        result = cloc_report.count_directory(src_dir, ".py")
        assert result["code"] > 500, f"Expected >500 Python source LOC, got {result['code']}"
        assert result["files"] > 10

    def test_real_rust_source_has_code(self, project_root):
        src_dir = os.path.join(project_root, "port", "rust", "src")
        result = cloc_report.count_directory(src_dir, ".rs")
        assert result["code"] > 500, f"Expected >500 Rust source LOC, got {result['code']}"
        assert result["files"] > 10

    def test_generate_full_report(self, project_root):
        report = cloc_report.generate_report(project_root)
        assert "timestamp" in report
        py = report["implementations"]["python"]
        assert py["source"]["files"] > 10
        assert py["source"]["code"] > 500
        assert py["tests"]["files"] > 20
        assert py["total"]["code"] > py["source"]["code"]

        rs = report["implementations"]["rust"]
        assert rs["source"]["files"] > 10
        assert rs["source"]["code"] > 500

    def test_format_table_with_real_data(self, project_root):
        report = cloc_report.generate_report(project_root)
        table = cloc_report.format_table(report)
        assert "Python" in table
        assert "Rust" in table
        assert "Kotlin" in table
        assert "Swift" in table
        # Table should have lines
        lines = table.strip().split("\n")
        assert len(lines) >= 6  # header + separator + 4 ports


# ---------------------------------------------------------------------------
# File extension filtering
# ---------------------------------------------------------------------------

class TestFileExtensionFiltering:
    """Test that only correct file extensions are matched."""

    def test_py_not_rs(self, tmp_path):
        _write_file(str(tmp_path), "a.py", "x = 1\n")
        _write_file(str(tmp_path), "b.rs", "fn foo() {}\n")
        _write_file(str(tmp_path), "c.kt", "fun main() {}\n")
        _write_file(str(tmp_path), "d.swift", "func main() {}\n")
        files = cloc_report.find_files(str(tmp_path), ".py")
        assert len(files) == 1
        assert files[0].endswith(".py")

    def test_rs_not_py(self, tmp_path):
        _write_file(str(tmp_path), "a.py", "x = 1\n")
        _write_file(str(tmp_path), "b.rs", "fn foo() {}\n")
        files = cloc_report.find_files(str(tmp_path), ".rs")
        assert len(files) == 1
        assert files[0].endswith(".rs")

    def test_kt_only(self, tmp_path):
        _write_file(str(tmp_path), "a.kt", "fun main() {}\n")
        _write_file(str(tmp_path), "b.py", "x = 1\n")
        files = cloc_report.find_files(str(tmp_path), ".kt")
        assert len(files) == 1

    def test_swift_only(self, tmp_path):
        _write_file(str(tmp_path), "a.swift", "func main() {}\n")
        _write_file(str(tmp_path), "b.py", "x = 1\n")
        files = cloc_report.find_files(str(tmp_path), ".swift")
        assert len(files) == 1
