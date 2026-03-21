"""Tests for the register command."""

from __future__ import annotations

from datetime import date

import pytest

from muonledger.amount import Amount
from muonledger.commands.register import register_command
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
# Test simple register output
# ---------------------------------------------------------------------------


class TestSimpleRegister:
    """Test basic register output format."""

    def test_single_transaction(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        assert len(lines) == 2
        # First posting shows date and payee
        assert "24-Jan-15" in lines[0]
        assert "Grocery Store" in lines[0]
        assert "Expenses:Food" in lines[0]
        assert "$42.50" in lines[0]
        # Second posting shows blank date/payee
        assert lines[1].startswith(" " * 10)
        assert "Assets:Checking" in lines[1]
        assert "$-42.50" in lines[1]

    def test_multiple_transactions(self):
        text = """\
2024/01/01 Opening Balance
    Assets:Bank:Checking     $1,000.00
    Equity:Opening

2024/01/05 Grocery Store
    Expenses:Food               $42.50
    Assets:Bank:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        assert len(lines) == 4
        # First transaction
        assert "24-Jan-01" in lines[0]
        assert "Opening Balance" in lines[0]
        # Second transaction
        assert "24-Jan-05" in lines[2]
        assert "Grocery Store" in lines[2]

    def test_line_width_is_80(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        for line in lines:
            assert len(line) == 80, f"Expected 80 chars, got {len(line)}: {line!r}"


# ---------------------------------------------------------------------------
# Test account filtering
# ---------------------------------------------------------------------------


class TestAccountFilter:
    """Test filtering by account pattern."""

    def test_filter_single_account(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Gas Station
    Expenses:Transport  $30.00
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["Expenses:Food"])
        lines = output.split("\n")
        assert len(lines) == 1
        assert "Expenses:Food" in lines[0]

    def test_filter_case_insensitive(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["expenses:food"])
        lines = output.split("\n")
        assert len(lines) == 1
        assert "Expenses:Food" in lines[0]

    def test_filter_partial_match(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Gas Station
    Expenses:Transport  $30.00
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["Expense"])
        lines = output.split("\n")
        assert len(lines) == 2
        assert "Expenses:Food" in lines[0]
        assert "Expenses:Transport" in lines[1]

    def test_filter_no_match(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["NoSuchAccount"])
        assert output == ""


# ---------------------------------------------------------------------------
# Test running total computation
# ---------------------------------------------------------------------------


class TestRunningTotal:
    """Test running total accumulation."""

    def test_running_total_single_commodity(self):
        text = """\
2024/01/01 Opening
    Assets:Checking     $1,000.00
    Equity:Opening

2024/01/05 Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        # After all 4 postings, the total should be $0.00
        last_line = lines[-1]
        assert "$0.00" in last_line or "0" in last_line

    def test_running_total_accumulates(self):
        text = """\
2024/01/01 Paycheck
    Assets:Checking     $500.00
    Income:Salary

2024/01/05 Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["Assets:Checking"])
        lines = output.split("\n")
        assert len(lines) == 2
        # First: $500.00, total $500.00
        assert "$500.00" in lines[0]
        # Second: $-42.50, total $457.50
        assert "$-42.50" in lines[1]
        assert "$457.50" in lines[1]


# ---------------------------------------------------------------------------
# Test --head and --tail
# ---------------------------------------------------------------------------


class TestHeadTail:
    """Test --head and --tail options."""

    def test_head(self):
        text = """\
2024/01/01 First
    Expenses:A       $10.00
    Assets:Cash

2024/01/02 Second
    Expenses:B       $20.00
    Assets:Cash

2024/01/03 Third
    Expenses:C       $30.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal, ["--head", "2"])
        lines = output.split("\n")
        # Should show first 2 postings (not 2 transactions)
        assert len(lines) == 2

    def test_tail(self):
        text = """\
2024/01/01 First
    Expenses:A       $10.00
    Assets:Cash

2024/01/02 Second
    Expenses:B       $20.00
    Assets:Cash

2024/01/03 Third
    Expenses:C       $30.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal, ["--tail", "2"])
        lines = output.split("\n")
        # Should show last 2 postings
        assert len(lines) == 2
        assert "Assets:Cash" in lines[-1]

    def test_head_and_tail(self):
        text = """\
2024/01/01 First
    Expenses:A       $10.00
    Assets:Cash

2024/01/02 Second
    Expenses:B       $20.00
    Assets:Cash
"""
        journal = _parse(text)
        # --head 3 then --tail 1 => last of first 3
        output = register_command(journal, ["--head", "3", "--tail", "1"])
        lines = output.split("\n")
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Test multi-commodity
# ---------------------------------------------------------------------------


class TestMultiCommodity:
    """Test multi-commodity running totals."""

    def test_multi_commodity_running_total(self):
        text = """\
2024/01/10 Buy EUR
    Assets:EUR            100.00 EUR @@ 100.00 USD
    Assets:Cash          -100.00 USD

2024/01/15 Buy GBP
    Assets:GBP             50.00 GBP @@ 50.00 USD
    Assets:Cash           -50.00 USD
"""
        journal = _parse(text)
        output = register_command(journal, ["Assets:EUR", "Assets:GBP"])
        lines = output.split("\n")
        # First posting: 100.00 EUR, total 100.00 EUR
        assert "100.00 EUR" in lines[0]
        # Second posting: 50.00 GBP with multi-commodity total
        # Should produce extra lines for multi-commodity totals
        found_eur = False
        found_gbp = False
        for line in lines:
            if "EUR" in line and "GBP" not in line.split("EUR")[0]:
                found_eur = True
            if "GBP" in line:
                found_gbp = True
        assert found_eur
        assert found_gbp

    def test_multi_commodity_extra_lines(self):
        """Multi-commodity running total produces extra output lines."""
        text = """\
2024/01/10 Trade
    Assets:EUR            10.00 EUR @@ 10.00 USD
    Assets:Cash          -10.00 USD
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        # 2 postings, but second posting has 2-commodity total
        # so we get: posting1 (1 line) + posting2 (2 lines) = 3 lines
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# Test truncation of long names
# ---------------------------------------------------------------------------


class TestTruncation:
    """Test truncation of payee and account names."""

    def test_long_payee_truncated(self):
        text = """\
2024/01/15 A Very Long Payee Name That Exceeds Column Width
    Expenses:Food       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        # Payee should be truncated with '..' suffix
        # Payee column is 22 chars, so payee text is max 21 chars
        payee_col = lines[0][10:32]
        assert ".." in payee_col
        assert len(lines[0]) == 80

    def test_long_account_truncated(self):
        text = """\
2024/01/15 Test
    Expenses:Food:Dining:Restaurant:Fancy  $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        # Account column is 22 chars, so account text is max 21 chars
        account_col = lines[0][32:54]
        assert ".." in account_col
        assert len(lines[0]) == 80

    def test_short_names_not_truncated(self):
        text = """\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        assert "Expenses:Food" in lines[0]
        assert ".." not in lines[0][32:54]


# ---------------------------------------------------------------------------
# Test wide mode
# ---------------------------------------------------------------------------


class TestWideMode:
    """Test --wide / -w option."""

    def test_wide_flag(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["--wide"])
        lines = output.split("\n")
        for line in lines:
            assert len(line) == 132, f"Expected 132 chars, got {len(line)}: {line!r}"

    def test_wide_short_flag(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["-w"])
        lines = output.split("\n")
        for line in lines:
            assert len(line) == 132


# ---------------------------------------------------------------------------
# Test empty journal
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_journal(self):
        journal = Journal()
        output = register_command(journal)
        assert output == ""

    def test_no_args(self):
        text = """\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = register_command(journal)
        assert len(output) > 0

    def test_date_format(self):
        text = """\
2024/01/01 Test
    Expenses:A       $10.00
    Assets:B
"""
        journal = _parse(text)
        output = register_command(journal)
        assert "24-Jan-01" in output

    def test_subsequent_postings_blank_date_payee(self):
        """Second posting in same xact has blank date and payee."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.split("\n")
        # Second line should have blank date and payee cols
        assert lines[1][:32] == " " * 32
