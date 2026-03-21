"""Tests for the print command."""

from __future__ import annotations

import pytest

from muonledger.commands.print_cmd import (
    format_posting,
    format_transaction,
    print_command,
)
from muonledger.journal import Journal
from muonledger.parser import TextualParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(text: str) -> Journal:
    """Parse *text* and return the populated journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


# ---------------------------------------------------------------------------
# Basic transaction printing
# ---------------------------------------------------------------------------


class TestBasicPrint:
    """Test basic transaction output in journal format."""

    def test_simple_two_posting(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "2024/01/15" in output
        assert "Grocery Store" in output
        assert "Expenses:Food" in output
        assert "$42.50" in output
        assert "Assets:Checking" in output

    def test_date_format(self):
        text = """\
2024/01/15 Payee
    Expenses:Food       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = print_command(journal)
        # Date should be YYYY/MM/DD
        assert output.startswith("2024/01/15")

    def test_amount_elision_same_commodity(self):
        """In a 2-posting transaction with same commodity, second amount is elided."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking    $-42.50
"""
        journal = _parse(text)
        output = print_command(journal)
        lines = output.strip().split("\n")
        # The second posting should not have an amount (elided)
        assert "$42.50" in lines[1]
        # Second posting line should just have account name, no amount
        assert "$-42.50" not in lines[2]
        assert "Assets:Checking" in lines[2]

    def test_no_elision_different_commodity(self):
        """When commodities differ, no elision occurs."""
        text = """\
2024/01/15 Currency Exchange
    Assets:EUR       100 EUR @ $1.10
    Assets:USD
"""
        journal = _parse(text)
        output = print_command(journal)
        # Both postings should appear; the EUR posting has an amount
        assert "100 EUR" in output
        assert "Assets:USD" in output


# ---------------------------------------------------------------------------
# Cleared / Pending states
# ---------------------------------------------------------------------------


class TestClearingState:
    """Test cleared (*) and pending (!) state markers."""

    def test_cleared_transaction(self):
        text = """\
2024/01/15 * Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "2024/01/15 * Grocery Store" in output

    def test_pending_transaction(self):
        text = """\
2024/01/15 ! Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "2024/01/15 ! Grocery Store" in output

    def test_uncleared_transaction(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        # No state marker between date and payee
        assert "2024/01/15 Grocery Store" in output


# ---------------------------------------------------------------------------
# Transaction codes
# ---------------------------------------------------------------------------


class TestCodes:
    """Test transaction code display."""

    def test_code_present(self):
        text = """\
2024/01/15 * (1042) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "(1042)" in output

    def test_code_without_state(self):
        text = """\
2024/01/15 (CHK-100) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "(CHK-100)" in output
        assert "Grocery Store" in output


# ---------------------------------------------------------------------------
# Multi-posting transactions
# ---------------------------------------------------------------------------


class TestMultiPosting:
    """Test transactions with more than two postings."""

    def test_three_postings(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $30.00
    Expenses:Drinks     $12.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "Expenses:Food" in output
        assert "$30.00" in output
        assert "Expenses:Drinks" in output
        assert "$12.50" in output
        assert "Assets:Checking" in output

    def test_three_postings_no_elision(self):
        """With >2 postings, no amounts should be elided."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $30.00
    Expenses:Drinks     $12.50
    Assets:Checking    $-42.50
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "$30.00" in output
        assert "$12.50" in output
        assert "$-42.50" in output


# ---------------------------------------------------------------------------
# Virtual postings
# ---------------------------------------------------------------------------


class TestVirtualPostings:
    """Test virtual posting notation."""

    def test_virtual_posting_parens(self):
        """Non-balancing virtual postings use ()."""
        text = """\
2024/01/15 Paycheck
    Assets:Checking     $1,000.00
    Income:Salary
    (Budget:Food)        $200.00
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "(Budget:Food)" in output
        assert "$200.00" in output

    def test_virtual_posting_brackets(self):
        """Balanced virtual postings use []."""
        text = """\
2024/01/15 Transfer
    Assets:Checking     $500.00
    Assets:Savings     $-500.00
    [Budget:Emergency]   $500.00
    [Budget:General]    $-500.00
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "[Budget:Emergency]" in output
        assert "[Budget:General]" in output


# ---------------------------------------------------------------------------
# Cost expressions
# ---------------------------------------------------------------------------


class TestCostExpressions:
    """Test cost annotation output (@ and @@)."""

    def test_per_unit_cost(self):
        text = """\
2024/01/15 Buy Stock
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "10 AAPL" in output
        assert "@ $150.00" in output

    def test_total_cost(self):
        text = """\
2024/01/15 Buy Stock
    Assets:Brokerage    10 AAPL @@ $1,500.00
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "10 AAPL" in output
        assert "@@ $1,500.00" in output


# ---------------------------------------------------------------------------
# Notes and metadata
# ---------------------------------------------------------------------------


class TestNotesAndMetadata:
    """Test preservation of notes and metadata tags."""

    def test_transaction_note(self):
        text = """\
2024/01/15 Grocery Store  ; Weekly groceries
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "Weekly groceries" in output
        assert ";" in output

    def test_posting_note(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50  ; organic produce
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "organic produce" in output

    def test_metadata_tags(self):
        text = """\
2024/01/15 Grocery Store
    ; :receipt:
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert ":receipt:" in output

    def test_metadata_key_value(self):
        text = """\
2024/01/15 Grocery Store
    ; Payee: Whole Foods
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "Payee:" in output
        assert "Whole Foods" in output


# ---------------------------------------------------------------------------
# Multiple transactions
# ---------------------------------------------------------------------------


class TestMultipleTransactions:
    """Test output with multiple transactions."""

    def test_two_transactions(self):
        text = """\
2024/01/01 Opening Balance
    Assets:Checking     $1,000.00
    Equity:Opening

2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert "Opening Balance" in output
        assert "Grocery Store" in output
        # Transactions should be separated by a blank line
        assert "\n\n" in output

    def test_three_transactions_ordering(self):
        text = """\
2024/01/01 First
    Assets:A  $100.00
    Assets:B

2024/01/02 Second
    Assets:B  $200.00
    Assets:C

2024/01/03 Third
    Assets:C  $300.00
    Assets:D
"""
        journal = _parse(text)
        output = print_command(journal)
        first_pos = output.index("First")
        second_pos = output.index("Second")
        third_pos = output.index("Third")
        assert first_pos < second_pos < third_pos


# ---------------------------------------------------------------------------
# Empty journal
# ---------------------------------------------------------------------------


class TestEmptyJournal:
    """Test printing an empty journal."""

    def test_empty_journal(self):
        journal = Journal()
        output = print_command(journal)
        assert output == ""

    def test_journal_with_no_xacts(self):
        text = """\
; Just a comment
account Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal)
        assert output == ""


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    """Test transaction filtering by payee pattern."""

    def test_filter_by_payee(self):
        text = """\
2024/01/01 Opening Balance
    Assets:Checking     $1,000.00
    Equity:Opening

2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal, args=["Grocery"])
        assert "Grocery Store" in output
        assert "Opening Balance" not in output

    def test_filter_case_insensitive(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal, args=["grocery"])
        assert "Grocery Store" in output

    def test_filter_no_match(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = print_command(journal, args=["Restaurant"])
        assert output == ""


# ---------------------------------------------------------------------------
# Round-trip: parse -> print -> parse
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Test that parse -> print -> parse produces equivalent journals."""

    def test_simple_round_trip(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal1 = _parse(text)
        printed = print_command(journal1)
        journal2 = _parse(printed)

        assert len(journal2.xacts) == len(journal1.xacts)
        for x1, x2 in zip(journal1.xacts, journal2.xacts):
            assert x1.date == x2.date
            assert x1.payee == x2.payee
            assert x1.state == x2.state
            assert len(x1.posts) == len(x2.posts)

    def test_complex_round_trip(self):
        text = """\
2024/01/15 * (1042) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal1 = _parse(text)
        printed = print_command(journal1)
        journal2 = _parse(printed)

        x1 = journal1.xacts[0]
        x2 = journal2.xacts[0]
        assert x1.date == x2.date
        assert x1.payee == x2.payee
        assert x1.state == x2.state
        assert x1.code == x2.code

    def test_multi_transaction_round_trip(self):
        text = """\
2024/01/01 Opening Balance
    Assets:Checking     $1,000.00
    Equity:Opening

2024/01/15 * Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 ! (CHK) Electric Company
    Expenses:Utilities  $85.00
    Assets:Checking
"""
        journal1 = _parse(text)
        printed = print_command(journal1)
        journal2 = _parse(printed)

        assert len(journal2.xacts) == 3
        assert journal2.xacts[0].payee == "Opening Balance"
        assert journal2.xacts[1].payee == "Grocery Store"
        assert journal2.xacts[1].state == journal1.xacts[1].state
        assert journal2.xacts[2].payee == "Electric Company"
        assert journal2.xacts[2].code == "CHK"

    def test_cost_round_trip(self):
        """Per-unit cost should survive a round trip."""
        text = """\
2024/01/15 Buy Stock
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
"""
        journal1 = _parse(text)
        printed = print_command(journal1)
        journal2 = _parse(printed)

        assert len(journal2.xacts) == 1
        x = journal2.xacts[0]
        assert x.payee == "Buy Stock"
        # The AAPL posting should exist
        aapl_post = [p for p in x.posts if "Brokerage" in p.account.fullname]
        assert len(aapl_post) == 1
        assert "AAPL" in str(aapl_post[0].amount)


# ---------------------------------------------------------------------------
# format_transaction and format_posting helpers
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    """Test the format_transaction and format_posting helper functions."""

    def test_format_transaction_returns_string(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        result = format_transaction(journal.xacts[0])
        assert isinstance(result, str)
        assert "Grocery Store" in result
        assert result.endswith("\n")

    def test_format_posting_returns_string(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        result = format_posting(xact, xact.posts[0])
        assert isinstance(result, str)
        assert result.startswith("    ")
        assert "Expenses:Food" in result
        assert "$42.50" in result
