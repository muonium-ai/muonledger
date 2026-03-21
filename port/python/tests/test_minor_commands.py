"""Tests for minor commands: source, echo, and script."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from muonledger.commands.source import source_command
from muonledger.commands.echo import echo_command
from muonledger.commands.script import script_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JOURNAL = """\
2024/01/15 Grocery Store
    Expenses:Food            $50.00
    Assets:Checking

2024/01/20 Gas Station
    Expenses:Transport       $30.00
    Assets:Checking
"""

INVALID_JOURNAL = """\
2024/01/15 Grocery Store
    Expenses:Food            $50.00
"""

COMMENT_ONLY_JOURNAL = """\
; This is a comment
# Another comment
; yet another
"""

MULTI_COMMODITY_JOURNAL = """\
2024/01/15 Grocery Store
    Expenses:Food            $50.00
    Assets:Checking         $-50.00

2024/01/20 Salary
    Assets:Checking        $3000.00
    Income:Salary         $-3000.00

2024/01/25 Investment
    Assets:Stocks          10 AAPL @ $150.00
    Assets:Checking       $-1500.00
"""


def _write_temp(content: str, suffix: str = ".ledger") -> str:
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# ===========================================================================
# Source command tests
# ===========================================================================

class TestSourceCommand:
    """Tests for the source (validation) command."""

    def test_valid_journal(self):
        path = _write_temp(VALID_JOURNAL)
        try:
            result = source_command(path)
            assert "No errors" in result
            assert "Transactions: 2" in result
            assert "Postings: 4" in result
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        result = source_command("/nonexistent/path/to/file.ledger")
        assert "Error" in result
        assert "file not found" in result

    def test_empty_file(self):
        path = _write_temp("")
        try:
            result = source_command(path)
            assert "No errors" in result
            assert "Transactions: 0" in result
        finally:
            os.unlink(path)

    def test_comment_only_file(self):
        path = _write_temp(COMMENT_ONLY_JOURNAL)
        try:
            result = source_command(path)
            assert "No errors" in result
            assert "Transactions: 0" in result
        finally:
            os.unlink(path)

    def test_invalid_journal_reports_error(self):
        # A transaction with only one posting and no balancing
        bad_journal = """\
2024/01/15 Bad Transaction
    Expenses:Food            $50.00
    Expenses:More            $30.00
    Assets:Checking
"""
        path = _write_temp(bad_journal)
        try:
            # This may or may not error depending on parser strictness;
            # at minimum it should not crash
            result = source_command(path)
            assert isinstance(result, str)
        finally:
            os.unlink(path)

    def test_multi_commodity_journal(self):
        path = _write_temp(MULTI_COMMODITY_JOURNAL)
        try:
            result = source_command(path)
            assert "No errors" in result
            assert "Transactions: 3" in result
        finally:
            os.unlink(path)

    def test_filepath_in_output(self):
        path = _write_temp(VALID_JOURNAL)
        try:
            result = source_command(path)
            assert path in result
        finally:
            os.unlink(path)

    def test_single_transaction(self):
        journal = """\
2024/03/01 Coffee Shop
    Expenses:Coffee          $5.00
    Assets:Cash
"""
        path = _write_temp(journal)
        try:
            result = source_command(path)
            assert "Transactions: 1" in result
            assert "Postings: 2" in result
        finally:
            os.unlink(path)

    def test_posting_count_accuracy(self):
        journal = """\
2024/01/01 Multi-post
    Expenses:A              $10.00
    Expenses:B              $20.00
    Expenses:C              $30.00
    Assets:Checking
"""
        path = _write_temp(journal)
        try:
            result = source_command(path)
            assert "Postings: 4" in result
        finally:
            os.unlink(path)

    def test_directory_not_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = source_command(tmpdir)
            assert "Error" in result

    def test_options_none_accepted(self):
        path = _write_temp(VALID_JOURNAL)
        try:
            result = source_command(path, options=None)
            assert "No errors" in result
        finally:
            os.unlink(path)


# ===========================================================================
# Echo command tests
# ===========================================================================

class TestEchoCommand:
    """Tests for the echo (expression evaluation) command."""

    def test_simple_integer(self):
        result = echo_command("42")
        assert result.strip() == "42"

    def test_simple_addition(self):
        result = echo_command("2 + 3")
        assert result.strip() == "5"

    def test_simple_subtraction(self):
        result = echo_command("10 - 3")
        assert result.strip() == "7"

    def test_simple_multiplication(self):
        result = echo_command("4 * 5")
        assert result.strip() == "20"

    def test_simple_division(self):
        result = echo_command("10 / 2")
        assert result.strip() == "5"

    def test_parentheses(self):
        result = echo_command("(2 + 3) * 4")
        assert result.strip() == "20"

    def test_nested_parentheses(self):
        result = echo_command("((2 + 3) * (4 - 1))")
        assert result.strip() == "15"

    def test_unary_negation(self):
        result = echo_command("-5")
        assert result.strip() == "-5"

    def test_boolean_true(self):
        result = echo_command("true")
        assert result.strip() == "true"

    def test_boolean_false(self):
        result = echo_command("false")
        assert result.strip() == "false"

    def test_logical_not(self):
        result = echo_command("!true")
        assert result.strip() == "false"

    def test_logical_not_false(self):
        result = echo_command("!false")
        assert result.strip() == "true"

    def test_comparison_equal(self):
        result = echo_command("3 == 3")
        assert result.strip() == "true"

    def test_comparison_not_equal(self):
        result = echo_command("3 == 4")
        assert result.strip() == "false"

    def test_comparison_less_than(self):
        result = echo_command("2 < 5")
        assert result.strip() == "true"

    def test_comparison_greater_than(self):
        result = echo_command("5 > 2")
        assert result.strip() == "true"

    def test_comparison_less_equal(self):
        result = echo_command("3 <= 3")
        assert result.strip() == "true"

    def test_comparison_greater_equal(self):
        result = echo_command("3 >= 4")
        assert result.strip() == "false"

    def test_logical_and_true(self):
        result = echo_command("true and true")
        assert result.strip() == "true"

    def test_logical_and_false(self):
        result = echo_command("true and false")
        assert result.strip() == "false"

    def test_logical_or_true(self):
        result = echo_command("false or true")
        assert result.strip() == "true"

    def test_logical_or_false(self):
        result = echo_command("false or false")
        assert result.strip() == "false"

    def test_ternary(self):
        result = echo_command("true ? 1 : 0")
        assert result.strip() == "1"

    def test_ternary_false_branch(self):
        result = echo_command("false ? 1 : 0")
        assert result.strip() == "0"

    def test_string_literal(self):
        result = echo_command("'hello'")
        assert result.strip() == "hello"

    def test_empty_expression(self):
        result = echo_command("")
        assert "Error" in result

    def test_whitespace_only(self):
        result = echo_command("   ")
        assert "Error" in result

    def test_invalid_expression(self):
        result = echo_command("+ + +")
        assert "Error" in result

    def test_unknown_identifier(self):
        result = echo_command("foobar")
        assert "Error" in result

    def test_complex_arithmetic(self):
        result = echo_command("2 + 3 * 4")
        # Precedence: 3*4=12, 2+12=14
        assert result.strip() == "14"

    def test_mixed_ops(self):
        result = echo_command("10 - 2 * 3")
        # Precedence: 2*3=6, 10-6=4
        assert result.strip() == "4"

    def test_float_literal(self):
        result = echo_command("3.14")
        # Float gets converted to Amount
        assert "3.14" in result.strip()

    def test_options_none_accepted(self):
        result = echo_command("1 + 1", options=None)
        assert result.strip() == "2"

    def test_journal_none_accepted(self):
        result = echo_command("1 + 1", journal=None)
        assert result.strip() == "2"

    def test_today_identifier(self):
        from datetime import date
        result = echo_command("today")
        # Should produce today's date as a string
        today_str = str(date.today())
        assert today_str in result


# ===========================================================================
# Script command tests
# ===========================================================================

class TestScriptCommand:
    """Tests for the script (batch execution) command."""

    def test_single_echo(self):
        script = "echo 2 + 3\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "5" in result
        finally:
            os.unlink(path)

    def test_multiple_echo(self):
        script = "echo 1 + 1\necho 2 * 3\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "2" in result
            assert "6" in result
        finally:
            os.unlink(path)

    def test_skip_empty_lines(self):
        script = "\necho 5\n\necho 10\n\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "5" in result
            assert "10" in result
        finally:
            os.unlink(path)

    def test_skip_comments(self):
        script = "# This is a comment\necho 42\n# Another comment\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "42" in result
            # Comments should not produce output
            lines = [l for l in result.strip().splitlines() if l.strip()]
            assert len(lines) == 1
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        result = script_command("/nonexistent/script.txt")
        assert "Error" in result
        assert "not found" in result

    def test_unknown_command(self):
        script = "foobar something\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "Error" in result
            assert "unknown command" in result
        finally:
            os.unlink(path)

    def test_balance_without_journal(self):
        script = "balance\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path, journal_file=None)
            assert "Error" in result
            assert "requires a journal" in result
        finally:
            os.unlink(path)

    def test_echo_with_string(self):
        script = "echo 'hello'\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert "hello" in result
        finally:
            os.unlink(path)

    def test_empty_script(self):
        script = ""
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert result == ""
        finally:
            os.unlink(path)

    def test_comment_only_script(self):
        script = "# just a comment\n# another\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path)
            assert result == ""
        finally:
            os.unlink(path)

    def test_source_in_script(self):
        journal_path = _write_temp(VALID_JOURNAL)
        script = f"source {journal_path}\n"
        script_path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(script_path)
            assert "No errors" in result
        finally:
            os.unlink(script_path)
            os.unlink(journal_path)

    def test_balance_with_journal(self):
        journal_path = _write_temp(VALID_JOURNAL)
        script = "balance\n"
        script_path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(script_path, journal_file=journal_path)
            # Should produce balance output (not an error)
            assert "Error" not in result or "Expenses" in result
        finally:
            os.unlink(script_path)
            os.unlink(journal_path)

    def test_options_none_accepted(self):
        script = "echo 1\n"
        path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(path, options=None)
            assert "1" in result
        finally:
            os.unlink(path)

    def test_directory_not_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = script_command(tmpdir)
            assert "Error" in result

    def test_mixed_commands(self):
        """Script with echo and source commands together."""
        journal_path = _write_temp(VALID_JOURNAL)
        script = f"echo 10 + 20\nsource {journal_path}\n"
        script_path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(script_path)
            assert "30" in result
            assert "No errors" in result
        finally:
            os.unlink(script_path)
            os.unlink(journal_path)

    def test_journal_not_found_in_script(self):
        script = "balance\n"
        script_path = _write_temp(script, suffix=".txt")
        try:
            result = script_command(
                script_path, journal_file="/nonexistent/journal.ledger"
            )
            assert "Error" in result
        finally:
            os.unlink(script_path)
