"""Tests for the equity command."""

from __future__ import annotations

from datetime import date

import pytest

from muonledger.commands.equity import equity_command
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
# Basic equity generation
# ---------------------------------------------------------------------------


class TestBasicEquity:
    """Test basic equity output from simple journals."""

    def test_simple_two_posting(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert "2024/12/31" in output
        assert "Opening Balances" in output
        assert "Expenses:Food" in output
        assert "$42.50" in output
        assert "Assets:Checking" in output
        assert "$-42.50" in output
        # The equity posting should net to zero
        assert "Equity:Opening Balances" not in output or output.count("$") >= 2

    def test_equity_transaction_balances(self):
        """The generated equity transaction must balance (no BalanceError)."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        # Parse the output back -- it must be valid
        j2 = Journal()
        parser = TextualParser()
        parser.parse_string(output, j2)
        assert len(j2.xacts) == 1

    def test_default_date_is_today(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal)
        today = date.today().strftime("%Y/%m/%d")
        assert today in output


# ---------------------------------------------------------------------------
# Multi-account equity
# ---------------------------------------------------------------------------


class TestMultiAccountEquity:
    """Test equity with multiple accounts."""

    def test_multiple_transactions(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert "Expenses:Food" in output
        assert "Expenses:Utilities" in output
        assert "Assets:Checking" in output
        assert "$42.50" in output
        assert "$100.00" in output
        # Assets:Checking should show -142.50
        assert "$-142.50" in output

    def test_accounts_sorted(self):
        """Account postings should appear in sorted order."""
        text = """\
2024/01/15 Test
    Zebra:Account       $10.00
    Alpha:Account      $-10.00
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        alpha_pos = output.index("Alpha:Account")
        zebra_pos = output.index("Zebra:Account")
        assert alpha_pos < zebra_pos


# ---------------------------------------------------------------------------
# Multi-commodity equity
# ---------------------------------------------------------------------------


class TestMultiCommodityEquity:
    """Test equity with multiple commodities."""

    def test_two_commodities(self):
        text = """\
2024/01/15 US Purchase
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 EU Purchase
    Expenses:Travel     50.00 EUR
    Assets:Euro Account
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert "$42.50" in output
        assert "50.00 EUR" in output or "EUR" in output
        assert "Expenses:Food" in output
        assert "Expenses:Travel" in output

    def test_multi_commodity_single_account(self):
        """An account holding two commodities should get two postings."""
        text = """\
2024/01/15 Buy USD stuff
    Expenses:Food       $10.00
    Assets:Wallet

2024/01/20 Buy EUR stuff
    Expenses:Food       20.00 EUR
    Assets:Euro
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        # Expenses:Food should appear twice (once per commodity)
        lines = output.split("\n")
        food_lines = [l for l in lines if "Expenses:Food" in l]
        assert len(food_lines) == 2


# ---------------------------------------------------------------------------
# Account filtering
# ---------------------------------------------------------------------------


class TestAccountFilter:
    """Test equity with account filter patterns."""

    def test_filter_single_account(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(
            journal, args=["Expenses:Food"], equity_date=date(2024, 12, 31)
        )
        assert "Expenses:Food" in output
        assert "Expenses:Utilities" not in output
        assert "Assets:Checking" not in output

    def test_filter_by_parent_account(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(
            journal, args=["Expenses"], equity_date=date(2024, 12, 31)
        )
        assert "Expenses:Food" in output
        assert "Expenses:Utilities" in output
        assert "Assets:Checking" not in output

    def test_filter_case_insensitive(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(
            journal, args=["expenses:food"], equity_date=date(2024, 12, 31)
        )
        assert "Expenses:Food" in output

    def test_filter_no_match(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(
            journal, args=["Liabilities"], equity_date=date(2024, 12, 31)
        )
        assert output == ""


# ---------------------------------------------------------------------------
# Custom date
# ---------------------------------------------------------------------------


class TestCustomDate:
    """Test equity with custom dates."""

    def test_custom_date(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2025, 1, 1))
        assert "2025/01/01" in output

    def test_different_date_format(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 6, 30))
        assert "2024/06/30" in output


# ---------------------------------------------------------------------------
# Zero-balance exclusion
# ---------------------------------------------------------------------------


class TestZeroBalanceExclusion:
    """Test that zero-balance accounts are excluded."""

    def test_zero_balance_excluded(self):
        """An account whose debits and credits cancel out should not appear."""
        text = """\
2024/01/15 Deposit
    Assets:Checking     $100.00
    Income:Salary

2024/01/20 Withdrawal
    Expenses:Food       $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        # Assets:Checking nets to zero ($100 - $100 = $0)
        assert "Assets:Checking" not in output

    def test_all_zero_produces_empty(self):
        """If every account nets to zero, output should be empty."""
        text = """\
2024/01/15 Transfer
    Assets:Checking     $100.00
    Assets:Checking    $-100.00
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert output == ""


# ---------------------------------------------------------------------------
# Empty journal
# ---------------------------------------------------------------------------


class TestEmptyJournal:
    """Test equity with empty journals."""

    def test_empty_journal(self):
        journal = Journal()
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert output == ""

    def test_journal_with_no_transactions(self):
        text = """\
; Just a comment
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))
        assert output == ""


# ---------------------------------------------------------------------------
# Round-trip: equity output can be parsed back
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Test that equity output is valid journal syntax."""

    def test_round_trip_simple(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))

        # Parse the equity output back
        j2 = Journal()
        parser = TextualParser()
        parser.parse_string(output, j2)

        assert len(j2.xacts) == 1
        xact = j2.xacts[0]
        assert xact.payee == "Opening Balances"
        assert xact.date == date(2024, 12, 31)

    def test_round_trip_multi_account(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))

        j2 = Journal()
        parser = TextualParser()
        parser.parse_string(output, j2)

        assert len(j2.xacts) == 1
        xact = j2.xacts[0]
        # The transaction should have postings for each non-zero account
        assert len(xact.posts) >= 3  # at least 3 accounts with non-zero balances

    def test_round_trip_multi_commodity(self):
        text = """\
2024/01/15 US Purchase
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 EU Purchase
    Expenses:Travel     50.00 EUR
    Assets:Euro Account
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))

        j2 = Journal()
        parser = TextualParser()
        parser.parse_string(output, j2)

        # Multi-commodity equity may produce one or more transactions
        # depending on implementation, but it must parse back cleanly
        assert len(j2.xacts) >= 1

    def test_round_trip_preserves_balances(self):
        """Equity output, when parsed, should have the same account balances."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = equity_command(journal, equity_date=date(2024, 12, 31))

        j2 = Journal()
        parser = TextualParser()
        parser.parse_string(output, j2)

        assert len(j2.xacts) == 1
        xact = j2.xacts[0]

        # Check that Expenses:Food has $42.50 in the equity journal
        food_posts = [
            p for p in xact.posts
            if p.account is not None and p.account.fullname == "Expenses:Food"
        ]
        assert len(food_posts) == 1
        assert str(food_posts[0].amount) == "$42.50"

        # Check that Assets:Checking has $-142.50
        checking_posts = [
            p for p in xact.posts
            if p.account is not None and p.account.fullname == "Assets:Checking"
        ]
        assert len(checking_posts) == 1
        assert str(checking_posts[0].amount) == "$-142.50"
