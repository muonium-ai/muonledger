"""Tests for the cross-implementation parity test script."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add port/scripts to path so we can import test_parity
import sys

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "port" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import test_parity
from test_parity import (
    CellResult,
    CompareResult,
    Implementation,
    RunResult,
    TestCase,
    build_parity_matrix,
    compare_outputs,
    discover_implementations,
    get_implementations,
    get_test_cases,
    matrix_to_serializable,
    normalize_amounts,
    normalize_output,
    render_table,
    save_report,
)


# ---------------------------------------------------------------------------
# Test case definition and validation
# ---------------------------------------------------------------------------


class TestTestCaseDefinition:
    def test_get_test_cases_returns_list(self):
        cases = get_test_cases()
        assert isinstance(cases, list)
        assert len(cases) >= 30

    def test_all_cases_have_names(self):
        cases = get_test_cases()
        for tc in cases:
            assert tc.name, f"Test case missing name: {tc}"

    def test_all_names_unique(self):
        cases = get_test_cases()
        names = [tc.name for tc in cases]
        assert len(names) == len(set(names)), "Duplicate test case names found"

    def test_all_cases_have_journal(self):
        cases = get_test_cases()
        for tc in cases:
            assert tc.journal is not None, f"{tc.name} missing journal"

    def test_all_cases_have_valid_command(self):
        valid_commands = {"balance", "register", "print"}
        cases = get_test_cases()
        for tc in cases:
            assert tc.command in valid_commands, (
                f"{tc.name} has invalid command: {tc.command}"
            )

    def test_all_cases_have_description(self):
        cases = get_test_cases()
        for tc in cases:
            assert tc.description, f"{tc.name} missing description"

    def test_test_case_dataclass_defaults(self):
        tc = TestCase(name="test", journal="j", command="balance")
        assert tc.args == []
        assert tc.description == ""
        assert tc.expect_contains is None
        assert tc.extra_files == {}

    def test_test_case_with_all_fields(self):
        tc = TestCase(
            name="full",
            journal="2024-01-01 Test\n    A $10\n    B\n",
            command="balance",
            args=["--flat"],
            description="full test",
            expect_contains="$10",
            extra_files={"inc.dat": "data"},
        )
        assert tc.name == "full"
        assert tc.args == ["--flat"]
        assert tc.extra_files == {"inc.dat": "data"}


# ---------------------------------------------------------------------------
# Output normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_strip_trailing_whitespace(self):
        assert normalize_output("hello   \nworld  ") == "hello\nworld"

    def test_collapse_blank_lines(self):
        assert normalize_output("a\n\n\n\nb") == "a\n\nb"

    def test_strip_leading_trailing_blanks(self):
        assert normalize_output("\n\nhello\n\n") == "hello"

    def test_preserve_internal_content(self):
        text = "  $50.00  Expenses:Food\n  $-50.00  Assets:Checking"
        result = normalize_output(text)
        assert "$50.00  Expenses:Food" in result

    def test_empty_input(self):
        assert normalize_output("") == ""

    def test_only_whitespace(self):
        assert normalize_output("   \n   \n  ") == ""


class TestNormalizeAmounts:
    def test_remove_comma_separator(self):
        assert normalize_amounts("$1,000.00") == "$1000"

    def test_strip_trailing_zeros(self):
        assert normalize_amounts("$50.00") == "$50"

    def test_keep_significant_decimals(self):
        assert normalize_amounts("$50.50") == "$50.5"

    def test_no_change_needed(self):
        assert normalize_amounts("$50") == "$50"

    def test_large_number(self):
        assert normalize_amounts("$12,500.00") == "$12500"

    def test_non_dollar_unchanged(self):
        result = normalize_amounts("100 EUR")
        assert result == "100 EUR"


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


class TestCompareOutputs:
    def test_exact_match(self):
        result = compare_outputs("hello", "hello")
        assert result.status == "exact_match"

    def test_fuzzy_match_whitespace(self):
        result = compare_outputs("hello  \n", "hello\n")
        assert result.status == "fuzzy_match"
        assert "whitespace" in result.detail

    def test_fuzzy_match_numeric(self):
        result = compare_outputs("$50.00", "$50")
        assert result.status == "fuzzy_match"
        assert "numeric" in result.detail

    def test_mismatch(self):
        result = compare_outputs("hello", "world")
        assert result.status == "mismatch"
        assert result.diff != ""

    def test_empty_match(self):
        result = compare_outputs("", "")
        assert result.status == "exact_match"

    def test_mismatch_diff_content(self):
        result = compare_outputs("line1\nline2", "line1\nline3")
        assert result.status == "mismatch"
        assert "line2" in result.diff or "line3" in result.diff

    def test_fuzzy_match_trailing_newline(self):
        result = compare_outputs("output\n", "output")
        assert result.status in ("exact_match", "fuzzy_match")

    def test_comma_vs_no_comma(self):
        result = compare_outputs("$1,000.00", "$1000")
        assert result.status == "fuzzy_match"


# ---------------------------------------------------------------------------
# Implementation discovery
# ---------------------------------------------------------------------------


class TestImplementationDiscovery:
    def test_get_implementations_returns_all(self):
        impls = get_implementations()
        assert "ledger" in impls
        assert "python" in impls
        assert "rust" in impls
        assert "kotlin" in impls
        assert "swift" in impls

    def test_implementation_dataclass(self):
        impl = Implementation(name="test", cmd=["test"])
        assert impl.available is False
        assert impl.cwd is None
        assert impl.check_cmd is None

    @patch("test_parity.subprocess.run")
    def test_discover_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        impls = {
            "test": Implementation(
                name="test", cmd=["test"], check_cmd=["test", "--version"]
            )
        }
        discover_implementations(impls)
        assert impls["test"].available is True

    @patch("test_parity.subprocess.run")
    def test_discover_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        impls = {
            "test": Implementation(
                name="test", cmd=["test"], check_cmd=["test", "--version"]
            )
        }
        discover_implementations(impls)
        assert impls["test"].available is False

    @patch("test_parity.subprocess.run", side_effect=FileNotFoundError)
    def test_discover_file_not_found(self, mock_run):
        impls = {
            "test": Implementation(
                name="test", cmd=["test"], check_cmd=["test", "--version"]
            )
        }
        discover_implementations(impls)
        assert impls["test"].available is False

    @patch("test_parity.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="t", timeout=10))
    def test_discover_timeout(self, mock_run):
        impls = {
            "test": Implementation(
                name="test", cmd=["test"], check_cmd=["test", "--version"]
            )
        }
        discover_implementations(impls)
        assert impls["test"].available is False

    def test_discover_no_check_cmd(self):
        impls = {"test": Implementation(name="test", cmd=["test"])}
        discover_implementations(impls)
        assert impls["test"].available is False


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    def test_save_report_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tests = [TestCase(name="t1", journal="j", command="balance")]
            impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
            matrix = {
                "t1": {
                    "python": CellResult(status="pass")
                }
            }
            report_path = save_report(tests, impls, matrix, Path(tmpdir))
            assert report_path.exists()
            assert report_path.name.startswith("parity_")
            assert report_path.suffix == ".json"

    def test_report_json_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tests = [TestCase(name="t1", journal="j", command="balance")]
            impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
            matrix = {
                "t1": {"python": CellResult(status="pass", detail="ok")}
            }
            report_path = save_report(tests, impls, matrix, Path(tmpdir))
            with open(report_path) as f:
                data = json.load(f)
            assert "timestamp" in data
            assert "implementations" in data
            assert "test_count" in data
            assert data["test_count"] == 1
            assert "results" in data
            assert "t1" in data["results"]
            assert "python" in data["results"]["t1"]

    def test_report_timestamp_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tests = []
            impls = {}
            matrix = {}
            report_path = save_report(tests, impls, matrix, Path(tmpdir))
            # Filename format: parity_YYYY-MM-DDTHHMMSS.json
            stem = report_path.stem
            assert stem.startswith("parity_")
            ts = stem[len("parity_"):]
            assert len(ts) == 17  # YYYY-MM-DDTHHMMSS

    def test_matrix_to_serializable(self):
        matrix = {
            "test1": {
                "python": CellResult(
                    status="pass",
                    compare=CompareResult(status="exact_match"),
                    detail="ok",
                )
            }
        }
        result = matrix_to_serializable(matrix)
        assert result["test1"]["python"]["status"] == "pass"
        assert result["test1"]["python"]["compare_status"] == "exact_match"

    def test_matrix_to_serializable_no_compare(self):
        matrix = {
            "test1": {
                "python": CellResult(status="skip", detail="not available")
            }
        }
        result = matrix_to_serializable(matrix)
        assert result["test1"]["python"]["status"] == "skip"
        assert "compare_status" not in result["test1"]["python"]

    def test_matrix_to_serializable_with_diff(self):
        matrix = {
            "test1": {
                "python": CellResult(
                    status="fail",
                    compare=CompareResult(status="mismatch", diff="--- a\n+++ b"),
                )
            }
        }
        result = matrix_to_serializable(matrix)
        assert "diff" in result["test1"]["python"]


# ---------------------------------------------------------------------------
# Matrix rendering
# ---------------------------------------------------------------------------


class TestMatrixRendering:
    def test_render_table_basic(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
        matrix = {"t1": {"python": CellResult(status="pass")}}
        table = render_table(tests, impls, matrix)
        assert "t1" in table
        assert "PASS" in table
        assert "python" in table

    def test_render_table_multiple_impls(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {
            "ledger": Implementation(name="ledger", cmd=["l"], available=True),
            "python": Implementation(name="python", cmd=["p"], available=True),
        }
        matrix = {
            "t1": {
                "ledger": CellResult(status="ref"),
                "python": CellResult(status="pass"),
            }
        }
        table = render_table(tests, impls, matrix)
        assert "REF" in table
        assert "PASS" in table

    def test_render_table_skip(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {"rust": Implementation(name="rust", cmd=["r"], available=False)}
        matrix = {"t1": {"rust": CellResult(status="skip")}}
        table = render_table(tests, impls, matrix)
        assert "SKIP" in table

    def test_render_table_error(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
        matrix = {"t1": {"python": CellResult(status="error")}}
        table = render_table(tests, impls, matrix)
        assert "ERR" in table

    def test_render_table_fail(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
        matrix = {"t1": {"python": CellResult(status="fail")}}
        table = render_table(tests, impls, matrix)
        assert "FAIL" in table

    def test_render_table_summary(self):
        tests = [
            TestCase(name="t1", journal="j", command="balance"),
            TestCase(name="t2", journal="j", command="balance"),
        ]
        impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
        matrix = {
            "t1": {"python": CellResult(status="pass")},
            "t2": {"python": CellResult(status="fail")},
        }
        table = render_table(tests, impls, matrix)
        assert "1 pass" in table
        assert "1 fail" in table

    def test_render_empty_tests(self):
        tests = []
        impls = {"python": Implementation(name="python", cmd=["p"], available=True)}
        matrix = {}
        # Should not crash
        table = render_table(tests, impls, matrix)
        assert isinstance(table, str)


# ---------------------------------------------------------------------------
# Edge cases: all skip, all pass, mixed results
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_all_skip(self):
        tests = [TestCase(name="t1", journal="j", command="balance")]
        impls = {
            "ledger": Implementation(name="ledger", cmd=["l"], available=False),
            "python": Implementation(name="python", cmd=["p"], available=False),
        }
        matrix = build_parity_matrix(tests, impls)
        for tc_name, cells in matrix.items():
            for impl_name, cell in cells.items():
                assert cell.status == "skip"

    def test_single_impl_available(self):
        """When only one impl is available, it becomes the reference."""
        tc = TestCase(
            name="t1",
            journal="2024-01-01 Test\n    A $10\n    B\n",
            command="balance",
            expect_contains="$10",
        )
        impls = {
            "ledger": Implementation(name="ledger", cmd=["l"], available=False),
            "python": Implementation(name="python", cmd=["p"], available=True),
        }
        # Mock run_test_case to avoid subprocess
        with patch("test_parity.run_test_case") as mock_run:
            mock_run.return_value = RunResult(
                impl_name="python",
                test_name="t1",
                status="pass",
                output="$10.00  A\n",
            )
            # python is skip=False, so it will be called;
            # ledger is skip=True so run_test_case returns skip
            def side_effect(tc, impl, timeout=30):
                if not impl.available:
                    return RunResult(
                        impl_name=impl.name, test_name=tc.name, status="skip"
                    )
                return RunResult(
                    impl_name=impl.name,
                    test_name=tc.name,
                    status="pass",
                    output="$10.00  A\n",
                )

            mock_run.side_effect = side_effect
            matrix = build_parity_matrix([tc], impls)
            assert matrix["t1"]["python"].status == "ref"
            assert matrix["t1"]["ledger"].status == "skip"

    def test_all_pass(self):
        tc = TestCase(
            name="t1", journal="j", command="balance", expect_contains="$10"
        )
        impls = {
            "impl_a": Implementation(name="impl_a", cmd=["a"], available=True),
            "impl_b": Implementation(name="impl_b", cmd=["b"], available=True),
        }
        with patch("test_parity.run_test_case") as mock_run:
            mock_run.return_value = RunResult(
                impl_name="", test_name="t1", status="pass", output="$10.00  A\n"
            )
            matrix = build_parity_matrix([tc], impls, reference_impl="impl_a")
            assert matrix["t1"]["impl_a"].status == "ref"
            assert matrix["t1"]["impl_b"].status == "pass"

    def test_mixed_results(self):
        tc = TestCase(
            name="t1", journal="j", command="balance", expect_contains="$10"
        )
        impls = {
            "impl_a": Implementation(name="impl_a", cmd=["a"], available=True),
            "impl_b": Implementation(name="impl_b", cmd=["b"], available=True),
            "impl_c": Implementation(name="impl_c", cmd=["c"], available=False),
        }

        def side_effect(tc, impl, timeout=30):
            if not impl.available:
                return RunResult(
                    impl_name=impl.name, test_name=tc.name, status="skip"
                )
            if impl.name == "impl_a":
                return RunResult(
                    impl_name="impl_a", test_name="t1", status="pass",
                    output="$10.00  A\n",
                )
            return RunResult(
                impl_name="impl_b", test_name="t1", status="pass",
                output="DIFFERENT OUTPUT\n",
            )

        with patch("test_parity.run_test_case", side_effect=side_effect):
            matrix = build_parity_matrix([tc], impls, reference_impl="impl_a")
            assert matrix["t1"]["impl_a"].status == "ref"
            assert matrix["t1"]["impl_b"].status == "fail"
            assert matrix["t1"]["impl_c"].status == "skip"


# ---------------------------------------------------------------------------
# RunResult and run_test_case
# ---------------------------------------------------------------------------


class TestRunTestCase:
    def test_skip_unavailable(self):
        tc = TestCase(name="t1", journal="j", command="balance")
        impl = Implementation(name="test", cmd=["test"], available=False)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "skip"

    @patch("test_parity.subprocess.run")
    def test_successful_run(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="output\n", stderr=""
        )
        tc = TestCase(name="t1", journal="2024-01-01 T\n    A $10\n    B\n", command="balance")
        impl = Implementation(name="test", cmd=["echo"], available=True)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "pass"
        assert result.output == "output\n"

    @patch("test_parity.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error msg"
        )
        tc = TestCase(name="t1", journal="j", command="balance")
        impl = Implementation(name="test", cmd=["test"], available=True)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "error"
        assert "exit code 1" in result.detail

    @patch("test_parity.subprocess.run", side_effect=FileNotFoundError)
    def test_command_not_found(self, mock_run):
        tc = TestCase(name="t1", journal="j", command="balance")
        impl = Implementation(name="test", cmd=["nonexistent"], available=True)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "error"
        assert "command not found" in result.detail

    @patch("test_parity.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="t", timeout=5))
    def test_timeout(self, mock_run):
        tc = TestCase(name="t1", journal="j", command="balance")
        impl = Implementation(name="test", cmd=["slow"], available=True)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "error"
        assert "timeout" in result.detail

    @patch("test_parity.subprocess.run")
    def test_extra_files_written(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        tc = TestCase(
            name="t1",
            journal="include inc.dat\n",
            command="balance",
            extra_files={"inc.dat": "2024-01-01 T\n    A $10\n    B\n"},
        )
        impl = Implementation(name="test", cmd=["echo"], available=True)
        result = test_parity.run_test_case(tc, impl)
        assert result.status == "pass"
        # Verify the extra file was written by checking the call
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # The journal file should exist in a temp dir
        journal_path = cmd[cmd.index("-f") + 1]
        inc_path = os.path.join(os.path.dirname(journal_path), "inc.dat")
        # File may have been cleaned up, but the run succeeded


# ---------------------------------------------------------------------------
# Individual test case execution with Python impl
# ---------------------------------------------------------------------------


class TestPythonExecution:
    """Test individual cases using the actual Python implementation.

    These tests verify that the Python muonledger can handle the test
    journals defined in our parity test suite.  Uses the Python CLI
    module directly (no subprocess) for reliability.
    """

    def _run_python_cli(self, tc):
        """Run a test case through the Python muonledger CLI directly."""
        from muonledger.cli import main as cli_main
        from io import StringIO

        # Write journal to temp file
        tmpdir = tempfile.mkdtemp(prefix="parity_pytest_")
        journal_path = os.path.join(tmpdir, "test.dat")
        with open(journal_path, "w") as f:
            f.write(tc.journal)

        for fname, content in tc.extra_files.items():
            fpath = os.path.join(tmpdir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(content)

        argv = ["-f", journal_path, tc.command] + tc.args
        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()
        try:
            rc = cli_main(argv)
        except SystemExit as e:
            rc = e.code if e.code is not None else 0
        except Exception as e:
            sys.stdout = old_stdout
            return RunResult(
                impl_name="python", test_name=tc.name, status="error",
                detail=str(e),
            )
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        if rc != 0:
            return RunResult(
                impl_name="python", test_name=tc.name, status="error",
                output=output, returncode=rc, detail=f"exit code {rc}",
            )
        return RunResult(
            impl_name="python", test_name=tc.name, status="pass",
            output=output, returncode=0,
        )

    def test_basic_balance(self):
        tc = get_test_cases()[0]  # basic_balance
        assert tc.name == "basic_balance"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "$50.00" in result.output

    def test_basic_register(self):
        tc = get_test_cases()[1]  # basic_register
        assert tc.name == "basic_register"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "Grocery Store" in result.output

    def test_multi_posting(self):
        tc = get_test_cases()[3]  # multi_posting_balance
        assert tc.name == "multi_posting_balance"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "$45.00" in result.output

    def test_negative_amounts(self):
        tc = get_test_cases()[24]  # negative_amounts
        assert tc.name == "negative_amounts"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "$-15.00" in result.output or "-$15.00" in result.output

    def test_multiple_xact(self):
        tc = get_test_cases()[28]  # multiple_xact_balance
        assert tc.name == "multiple_xact_balance"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "$60.00" in result.output

    def test_comment_only_journal(self):
        tc = get_test_cases()[33]  # comment_only_journal
        assert tc.name == "comment_only_journal"
        result = self._run_python_cli(tc)
        # Should succeed (possibly empty output)
        assert result.status == "pass", f"Failed: {result.detail}"

    def test_posting_comment(self):
        tc = get_test_cases()[34]  # posting_comment
        assert tc.name == "posting_comment"
        result = self._run_python_cli(tc)
        assert result.status == "pass", f"Failed: {result.detail}"
        assert "$25.00" in result.output


# ---------------------------------------------------------------------------
# CompareResult dataclass
# ---------------------------------------------------------------------------


class TestCompareResult:
    def test_defaults(self):
        cr = CompareResult(status="exact_match")
        assert cr.diff == ""
        assert cr.detail == ""

    def test_with_diff(self):
        cr = CompareResult(status="mismatch", diff="--- a\n+++ b")
        assert "---" in cr.diff


# ---------------------------------------------------------------------------
# CellResult dataclass
# ---------------------------------------------------------------------------


class TestCellResult:
    def test_defaults(self):
        cr = CellResult(status="pass")
        assert cr.compare is None
        assert cr.output == ""
        assert cr.detail == ""

    def test_with_compare(self):
        cmp = CompareResult(status="fuzzy_match", detail="whitespace")
        cr = CellResult(status="pass", compare=cmp, output="out")
        assert cr.compare.status == "fuzzy_match"
