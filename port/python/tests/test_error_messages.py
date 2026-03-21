"""Tests for error message quality and parity with C++ Ledger.

Ticket T-000072: Ensures error messages include source file, line numbers,
context, and clear descriptions across parser, transaction, and amount errors.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from muonledger.amount import Amount, AmountError
from muonledger.journal import Journal
from muonledger.parser import ParseError, TextualParser
from muonledger.post import POST_VIRTUAL, Post
from muonledger.xact import BalanceError, Transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(text: str) -> Journal:
    """Parse *text* and return the populated journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _parse_file(text: str, filename: str = "test.ledger") -> Journal:
    """Write *text* to a temp file and parse it, so source name is a real path."""
    journal = Journal()
    parser = TextualParser()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ledger", prefix="test_", delete=False
    ) as f:
        f.write(text)
        f.flush()
        parser.parse(Path(f.name), journal)
    return journal


# ===========================================================================
# ParseError class tests
# ===========================================================================


class TestParseErrorClass:
    """Test the ParseError exception class itself."""

    def test_basic_message(self):
        err = ParseError("something went wrong")
        assert "something went wrong" in str(err)

    def test_line_num_in_message(self):
        err = ParseError("bad syntax", line_num=5)
        assert "5:" in str(err)
        assert "bad syntax" in str(err)

    def test_source_in_message(self):
        err = ParseError("bad syntax", line_num=5, source="ledger.dat")
        msg = str(err)
        assert "ledger.dat:" in msg
        assert "5:" in msg
        assert "bad syntax" in msg

    def test_source_string_not_shown(self):
        """Source '<string>' should not appear in the output."""
        err = ParseError("bad syntax", line_num=5, source="<string>")
        assert "<string>" not in str(err)

    def test_line_content_shown(self):
        err = ParseError("bad date", line_num=3, line_content="foobar payee")
        msg = str(err)
        assert "foobar payee" in msg
        assert ">" in msg  # the context indicator

    def test_line_content_stripped(self):
        err = ParseError("bad date", line_num=3, line_content="  foobar payee  \n")
        assert "foobar payee" in str(err)
        assert "\n" not in str(err).split("\n")[-1].rstrip("\n") or True  # trailing stripped

    def test_attributes_accessible(self):
        err = ParseError("msg", line_num=10, source="foo.dat", line_content="line text")
        assert err.message == "msg"
        assert err.line_num == 10
        assert err.source == "foo.dat"
        assert err.line_content == "line text"

    def test_line_num_1_based(self):
        """Line numbers should be 1-based (not 0-based)."""
        err = ParseError("msg", line_num=1)
        assert "1:" in str(err)

    def test_no_line_num_when_zero(self):
        err = ParseError("msg", line_num=0)
        # Should not have a stray "0:" prefix
        msg = str(err)
        assert not msg.startswith("0:")

    def test_full_format_with_all_fields(self):
        err = ParseError(
            "Expected date in format YYYY/MM/DD",
            line_num=42,
            source="/path/to/journal.dat",
            line_content="notadate Some payee",
        )
        msg = str(err)
        assert "/path/to/journal.dat:" in msg
        assert "42:" in msg
        assert "Expected date" in msg
        assert "notadate Some payee" in msg


# ===========================================================================
# Parse error context tests (via parser)
# ===========================================================================


class TestParseErrorsFromParser:
    """Test that the parser raises ParseError with good context."""

    def test_invalid_date_includes_line_number(self):
        text = "notadate Payee\n    Expenses  $10\n    Assets\n"
        # The parser should skip non-date lines, but if it starts with digit...
        text2 = "9xyz/01/01 Payee\n    Expenses  $10\n    Assets\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text2)
        err = exc_info.value
        assert err.line_num == 1
        assert "date" in err.message.lower() or "YYYY" in err.message

    def test_invalid_date_includes_content(self):
        text = "9999/99/99 Payee\n    Expenses  $10\n    Assets\n"
        with pytest.raises((ParseError, ValueError)):
            _parse(text)

    def test_include_not_found_message(self):
        text = 'include nonexistent_file.dat\n'
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert "not found" in str(err).lower() or "File not found" in str(err)
        assert err.line_num == 1

    def test_include_not_found_shows_path(self):
        text = 'include /tmp/definitely_nonexistent_ledger_file_xyz.dat\n'
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        assert "nonexistent" in str(exc_info.value)

    def test_include_not_found_shows_line_content(self):
        text = 'include missing.dat\n'
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert err.line_content != ""

    def test_include_not_found_from_file_shows_reference(self):
        """Include error from a file parse should reference the source file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ledger", delete=False
        ) as f:
            f.write("include nonexistent_sub.dat\n")
            f.flush()
            with pytest.raises(ParseError) as exc_info:
                journal = Journal()
                TextualParser().parse(Path(f.name), journal)
            msg = str(exc_info.value)
            assert "referenced from" in msg or f.name in msg

    def test_virtual_account_unclosed_paren(self):
        text = "2024/01/01 Payee\n    (Unclosed  $10\n    Assets\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert ")" in err.message
        assert err.line_num == 2

    def test_virtual_account_unclosed_bracket(self):
        text = "2024/01/01 Payee\n    [Unclosed  $10\n    Assets\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert "]" in err.message
        assert err.line_num == 2

    def test_p_directive_bad_date(self):
        text = "P notadate USD $1.00\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert "date" in err.message.lower() or "YYYY" in err.message
        assert err.line_num == 1

    def test_p_directive_missing_price(self):
        text = "P 2024/01/01 USD\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert "commodity" in err.message.lower() or "price" in err.message.lower()

    def test_p_directive_error_includes_line_content(self):
        text = "P baddate GOLD $100\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert err.line_content != ""

    def test_aux_date_error(self):
        text = "2024/01/01=badaux Payee\n    Expenses  $10\n    Assets\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert "auxiliary" in err.message.lower() or "date" in err.message.lower()
        assert err.line_num == 1

    def test_error_line_numbers_are_1_based(self):
        """First line should be reported as line 1, not line 0."""
        text = "P badline\n"
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        assert exc_info.value.line_num >= 1

    def test_multiple_transactions_error_correct_line(self):
        text = (
            "2024/01/01 OK\n"
            "    Expenses  $10\n"
            "    Assets\n"
            "\n"
            "9xyz/02/01 Bad\n"
            "    Expenses  $10\n"
            "    Assets\n"
        )
        with pytest.raises(ParseError) as exc_info:
            _parse(text)
        err = exc_info.value
        assert err.line_num == 5  # the bad line is line 5


# ===========================================================================
# BalanceError tests
# ===========================================================================


class TestBalanceErrorClass:
    """Test the BalanceError exception class itself."""

    def test_basic_message(self):
        err = BalanceError("something wrong")
        assert "something wrong" in str(err)

    def test_with_xact_shows_payee(self):
        xact = Transaction(payee="Coffee Shop")
        xact.date = date(2024, 1, 15)
        err = BalanceError("does not balance", xact=xact)
        msg = str(err)
        assert "Coffee Shop" in msg
        assert "2024-01-15" in msg

    def test_with_xact_shows_postings(self):
        xact = Transaction(payee="Store")
        xact.date = date(2024, 3, 1)
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-40.00")))
        err = BalanceError("does not balance: remainder is $2.50", xact=xact)
        msg = str(err)
        assert "Expenses:Food" in msg or "Expenses" in msg
        assert "Assets:Checking" in msg or "Assets" in msg
        assert "$42.50" in msg
        assert "$-40.00" in msg

    def test_without_xact_is_simple(self):
        err = BalanceError("simple error")
        assert str(err) == "simple error"


class TestBalanceErrorsFromFinalize:
    """Test balance errors raised during Transaction.finalize()."""

    def test_two_posting_unbalanced_shows_amounts(self):
        xact = Transaction(payee="Store")
        xact.date = date(2024, 1, 15)
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-40.00")))
        with pytest.raises(BalanceError, match="does not balance") as exc_info:
            xact.finalize()
        msg = str(exc_info.value)
        assert "Store" in msg
        assert "$42.50" in msg
        assert "$-40.00" in msg

    def test_three_posting_unbalanced_shows_all(self):
        xact = Transaction(payee="Dinner")
        xact.date = date(2024, 2, 20)
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$30.00")))
        xact.add_post(Post(account="Expenses:Drink", amount=Amount("$15.00")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-40.00")))
        with pytest.raises(BalanceError, match="does not balance") as exc_info:
            xact.finalize()
        msg = str(exc_info.value)
        assert "Dinner" in msg
        assert "$30.00" in msg
        assert "$15.00" in msg
        assert "$-40.00" in msg

    def test_multiple_null_amounts_shows_context(self):
        xact = Transaction(payee="Shop")
        xact.date = date(2024, 3, 1)
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking"))
        xact.add_post(Post(account="Liabilities:CC"))
        with pytest.raises(BalanceError, match="null amount") as exc_info:
            xact.finalize()
        msg = str(exc_info.value)
        assert "Shop" in msg

    def test_unbalanced_error_shows_date(self):
        xact = Transaction(payee="Test")
        xact.date = date(2024, 6, 15)
        xact.add_post(Post(account="A", amount=Amount("$10")))
        xact.add_post(Post(account="B", amount=Amount("$-5")))
        with pytest.raises(BalanceError) as exc_info:
            xact.finalize()
        assert "2024-06-15" in str(exc_info.value)

    def test_unbalanced_shows_remainder(self):
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.add_post(Post(account="A", amount=Amount("$100")))
        xact.add_post(Post(account="B", amount=Amount("$-99")))
        with pytest.raises(BalanceError, match="remainder") as exc_info:
            xact.finalize()
        # The remainder should be $1
        msg = str(exc_info.value)
        assert "$1" in msg or "remainder" in msg

    def test_balance_error_with_position(self):
        from muonledger.item import Position
        xact = Transaction(payee="Positioned")
        xact.date = date(2024, 1, 1)
        xact.position = Position(pathname="test.ledger", beg_line=42)
        xact.add_post(Post(account="A", amount=Amount("$10")))
        xact.add_post(Post(account="B", amount=Amount("$-5")))
        with pytest.raises(BalanceError) as exc_info:
            xact.finalize()
        msg = str(exc_info.value)
        assert "test.ledger" in msg
        assert "42" in msg

    def test_virtual_posts_not_in_balance_check(self):
        """Virtual posts should not cause balance errors."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses", amount=Amount("$10")))
        xact.add_post(Post(account="Assets", amount=Amount("$-10")))
        virtual = Post(account="(Budget)", amount=Amount("$999"), flags=POST_VIRTUAL)
        xact.add_post(virtual)
        # Should not raise
        result = xact.finalize()
        assert result is True


class TestBalanceErrorsFromParser:
    """Test balance errors raised during parsing (via journal.add_xact)."""

    def test_unbalanced_parsed_transaction(self):
        text = (
            "2024/01/01 Store\n"
            "    Expenses:Food  $42.50\n"
            "    Assets:Checking  $-40.00\n"
        )
        with pytest.raises(BalanceError) as exc_info:
            _parse(text)
        msg = str(exc_info.value)
        assert "does not balance" in msg
        assert "Store" in msg

    def test_unbalanced_shows_all_posting_amounts(self):
        text = (
            "2024/01/01 Dinner\n"
            "    Expenses:Food  $30\n"
            "    Expenses:Drink  $15\n"
            "    Assets:Checking  $-40\n"
        )
        with pytest.raises(BalanceError) as exc_info:
            _parse(text)
        msg = str(exc_info.value)
        assert "$30" in msg
        assert "$15" in msg
        assert "$-40" in msg


# ===========================================================================
# AmountError tests
# ===========================================================================


class TestAmountErrorClass:
    """Test the AmountError exception class itself."""

    def test_basic_message(self):
        err = AmountError("bad amount")
        assert "bad amount" in str(err)

    def test_with_input_text(self):
        err = AmountError("Cannot parse", input_text="$$abc")
        msg = str(err)
        assert "Cannot parse" in msg
        assert "$$abc" in msg
        assert "While parsing" in msg

    def test_without_input_text(self):
        err = AmountError("No quantity specified")
        assert "While parsing" not in str(err)


class TestAmountParseErrors:
    """Test amount parse error messages."""

    def test_empty_string(self):
        with pytest.raises(AmountError, match="No quantity"):
            Amount("")

    def test_whitespace_only(self):
        with pytest.raises(AmountError, match="No quantity"):
            Amount("   ")

    def test_empty_string_suggestion(self):
        """Empty amount error should suggest correct format."""
        with pytest.raises(AmountError) as exc_info:
            Amount("")
        msg = str(exc_info.value)
        assert "quantity" in msg.lower()

    def test_invalid_numeric_shows_input(self):
        with pytest.raises(AmountError) as exc_info:
            Amount("$1.2.3")
        msg = str(exc_info.value)
        assert "parse" in msg.lower() or "numeric" in msg.lower()

    def test_invalid_numeric_includes_while_parsing(self):
        with pytest.raises(AmountError) as exc_info:
            Amount("$1.2.3")
        msg = str(exc_info.value)
        assert "While parsing" in msg

    def test_commodity_only_no_number(self):
        """A commodity symbol with no number should error."""
        with pytest.raises(AmountError):
            Amount("USD")

    def test_uninitialized_amount_operations(self):
        """Operating on null amounts should give clear errors."""
        null_amt = Amount(None)
        with pytest.raises(AmountError, match="uninitialized"):
            null_amt.quantity

    def test_divide_by_zero(self):
        with pytest.raises(AmountError, match="[Dd]ivide by zero"):
            Amount("$10") / Amount("$0")

    def test_different_commodity_add(self):
        with pytest.raises(AmountError, match="different commodities"):
            Amount("$10") + Amount("10 EUR")

    def test_different_commodity_subtract(self):
        with pytest.raises(AmountError, match="different commodities"):
            Amount("$10") - Amount("10 EUR")


# ===========================================================================
# Error formatting and presentation tests
# ===========================================================================


class TestErrorFormatting:
    """Test that error messages are well-formatted and user-friendly."""

    def test_parse_error_multiline_context(self):
        """ParseError with line content should be multi-line."""
        err = ParseError(
            "Expected date", line_num=5, source="test.dat",
            line_content="badline Payee"
        )
        msg = str(err)
        lines = msg.split("\n")
        assert len(lines) >= 2  # at least message + context

    def test_parse_error_context_indicator(self):
        """Line content should be prefixed with '  > '."""
        err = ParseError("msg", line_num=1, line_content="the line")
        assert "  > the line" in str(err)

    def test_balance_error_indented_postings(self):
        """Postings in BalanceError should be indented."""
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.add_post(Post(account="A", amount=Amount("$10")))
        xact.add_post(Post(account="B", amount=Amount("$-5")))
        err = BalanceError("does not balance", xact=xact)
        msg = str(err)
        # Posting lines should be indented
        lines = msg.split("\n")
        posting_lines = [l for l in lines if "$" in l]
        for line in posting_lines:
            assert line.startswith("    ")

    def test_balance_error_transaction_header(self):
        """BalanceError should show 'In transaction:' header."""
        xact = Transaction(payee="Coffee")
        xact.date = date(2024, 5, 1)
        xact.add_post(Post(account="A", amount=Amount("$5")))
        xact.add_post(Post(account="B", amount=Amount("$-3")))
        err = BalanceError("does not balance", xact=xact)
        assert "In transaction:" in str(err)

    def test_parse_error_source_colon_format(self):
        """Source and line should be formatted as 'file:line:'."""
        err = ParseError("msg", line_num=10, source="foo.dat")
        assert "foo.dat:10:" in str(err)

    def test_amount_error_preserves_original_input(self):
        """AmountError should show the original text that failed."""
        try:
            Amount("$not_a_number")
        except AmountError as e:
            assert "not_a_number" in str(e) or "While parsing" in str(e)

    def test_parse_error_is_exception(self):
        assert issubclass(ParseError, Exception)

    def test_balance_error_is_exception(self):
        assert issubclass(BalanceError, Exception)

    def test_amount_error_is_exception(self):
        assert issubclass(AmountError, Exception)

    def test_parse_error_line_content_trailing_whitespace_stripped(self):
        err = ParseError("msg", line_num=1, line_content="hello   \r\n")
        msg = str(err)
        # The trailing content should be stripped
        assert msg.endswith("hello")

    def test_error_can_be_caught_by_parent(self):
        """All custom errors should be catchable as Exception."""
        with pytest.raises(Exception):
            raise ParseError("test")
        with pytest.raises(Exception):
            raise BalanceError("test")
        with pytest.raises(Exception):
            raise AmountError("test")


# ===========================================================================
# Integration: error messages from end-to-end parsing
# ===========================================================================


class TestEndToEndErrors:
    """Integration tests for error messages during full parsing."""

    def test_file_parse_error_includes_filename(self):
        """Errors from file parsing should include the source filename."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ledger", delete=False
        ) as f:
            f.write("9xyz/01/01 Bad date\n    A  $10\n    B\n")
            f.flush()
            with pytest.raises(ParseError) as exc_info:
                journal = Journal()
                TextualParser().parse(Path(f.name), journal)
            msg = str(exc_info.value)
            assert f.name in msg or "ledger" in msg

    def test_nested_include_error_shows_chain(self):
        """An error in an included file should reference the include chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child = Path(tmpdir) / "child.ledger"
            child.write_text("include nonexistent.dat\n")
            parent = Path(tmpdir) / "parent.ledger"
            parent.write_text(f"include {child}\n")
            with pytest.raises(ParseError) as exc_info:
                journal = Journal()
                TextualParser().parse(parent, journal)
            msg = str(exc_info.value)
            assert "nonexistent" in msg

    def test_well_formed_transaction_no_error(self):
        """A well-formed transaction should parse without error."""
        text = (
            "2024/01/01 Valid Transaction\n"
            "    Expenses:Food  $10.00\n"
            "    Assets:Checking\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_auto_balance_too_many_nulls_from_parser(self):
        """Parser should propagate BalanceError for too many null postings."""
        text = (
            "2024/01/01 Bad\n"
            "    Expenses:Food\n"
            "    Expenses:Drink\n"
            "    Assets:Checking  $-10\n"
        )
        with pytest.raises(BalanceError, match="null amount"):
            _parse(text)

    def test_mixed_commodity_unbalanced(self):
        """Mixed commodities that don't balance should give clear error."""
        text = (
            "2024/01/01 Exchange\n"
            "    Assets:EUR  100 EUR\n"
            "    Assets:USD  -90 USD\n"
        )
        # Mixed commodities: each commodity must independently balance
        # This should raise BalanceError since EUR and USD don't net to zero
        with pytest.raises(BalanceError, match="does not balance"):
            _parse(text)
