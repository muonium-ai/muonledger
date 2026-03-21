"""Tests for the stats command."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.item import ItemState, Position
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.stats import stats_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_journal() -> Journal:
    """Create a journal with three transactions spanning several days.

    2024/01/10 Opening Balance
        Assets:Bank:Checking     $5000.00
        Equity:Opening

    2024/01/15 * Grocery Store
        Expenses:Food              $42.50
        Assets:Bank:Checking

    2024/01/20 Gas Station
        Expenses:Auto:Gas          $35.00
        Assets:Bank:Checking
    """
    j = Journal()

    # Transaction 1 -- uncleared
    xact1 = Transaction(payee="Opening Balance")
    xact1.date = date(2024, 1, 10)
    xact1.position = Position(pathname="/tmp/test.dat", beg_line=1)

    acct_checking = j.find_account("Assets:Bank:Checking")
    acct_equity = j.find_account("Equity:Opening")

    p1 = Post(account=acct_checking, amount=Amount("$5000.00"))
    acct_checking.add_post(p1)
    p2 = Post(account=acct_equity)
    acct_equity.add_post(p2)

    xact1.add_post(p1)
    xact1.add_post(p2)
    j.add_xact(xact1)

    # Transaction 2 -- cleared
    xact2 = Transaction(payee="Grocery Store")
    xact2.date = date(2024, 1, 15)
    xact2.state = ItemState.CLEARED
    xact2.position = Position(pathname="/tmp/test.dat", beg_line=5)

    acct_food = j.find_account("Expenses:Food")

    p3 = Post(account=acct_food, amount=Amount("$42.50"))
    acct_food.add_post(p3)
    p4 = Post(account=acct_checking)
    acct_checking.add_post(p4)

    xact2.add_post(p3)
    xact2.add_post(p4)
    j.add_xact(xact2)

    # Transaction 3 -- uncleared
    xact3 = Transaction(payee="Gas Station")
    xact3.date = date(2024, 1, 20)
    xact3.position = Position(pathname="/tmp/test.dat", beg_line=9)

    acct_gas = j.find_account("Expenses:Auto:Gas")

    p5 = Post(account=acct_gas, amount=Amount("$35.00"))
    acct_gas.add_post(p5)
    p6 = Post(account=acct_checking)
    acct_checking.add_post(p6)

    xact3.add_post(p5)
    xact3.add_post(p6)
    j.add_xact(xact3)

    return j


def _make_multi_commodity_journal() -> Journal:
    """Journal with multiple commodities."""
    j = Journal()

    xact1 = Transaction(payee="Currency Exchange")
    xact1.date = date(2024, 3, 1)

    acct_usd = j.find_account("Assets:USD")
    acct_eur = j.find_account("Assets:EUR")

    p1 = Post(account=acct_usd, amount=Amount("$100.00"))
    acct_usd.add_post(p1)
    p2 = Post(account=acct_eur, amount=Amount("EUR -85.00"))
    acct_eur.add_post(p2)

    xact1.add_post(p1)
    xact1.add_post(p2)
    # Don't finalize -- commodities differ so balance check would fail.
    # Directly append instead.
    j.xacts.append(xact1)

    return j


# ---------------------------------------------------------------------------
# Tests: basic stats
# ---------------------------------------------------------------------------


class TestStatsBasic:
    """Test basic statistics computation."""

    def test_empty_journal(self):
        """Empty journal should produce empty output."""
        j = Journal()
        result = stats_command(j)
        assert result == ""

    def test_transaction_count_in_output(self):
        """Output should contain the number of postings."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # 3 xacts x 2 posts each = 6 postings
        assert "Number of postings:          6" in result

    def test_payee_count(self):
        """Should count unique payees."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # 3 unique payees
        assert "Unique payees:               3" in result

    def test_account_count(self):
        """Should count unique accounts referenced in postings."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # Accounts: Assets:Bank:Checking, Equity:Opening,
        #   Expenses:Food, Expenses:Auto:Gas = 4 unique
        assert "Unique accounts:             4" in result

    def test_uncleared_count(self):
        """Should count uncleared postings."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # xact1 (2 posts) + xact3 (2 posts) are uncleared = 4
        assert "Uncleared postings:          4" in result


# ---------------------------------------------------------------------------
# Tests: date range
# ---------------------------------------------------------------------------


class TestStatsDateRange:
    """Test date range calculations."""

    def test_time_period(self):
        """Should show correct date range."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        assert "Time period: 2024/01/10 to 2024/01/20 (10 days)" in result

    def test_days_since_last_post(self):
        """Should calculate days since last transaction."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # 2024/02/01 - 2024/01/20 = 12 days
        assert "Days since last post:       12" in result

    def test_single_day_span(self):
        """Journal with all transactions on same day should show 0 days span."""
        j = Journal()

        xact1 = Transaction(payee="Store A")
        xact1.date = date(2024, 5, 15)
        acct_a = j.find_account("Expenses:A")
        acct_b = j.find_account("Assets:B")
        p1 = Post(account=acct_a, amount=Amount("$10.00"))
        p2 = Post(account=acct_b, amount=Amount("$-10.00"))
        acct_a.add_post(p1)
        acct_b.add_post(p2)
        xact1.add_post(p1)
        xact1.add_post(p2)
        j.add_xact(xact1)

        result = stats_command(j, today=date(2024, 5, 15))
        assert "(0 days)" in result

    def test_per_day_rate(self):
        """Posts per day should be calculated correctly."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # 6 posts / 10 days = 0.60 per day
        assert "(0.60 per day)" in result


# ---------------------------------------------------------------------------
# Tests: commodity counting
# ---------------------------------------------------------------------------


class TestStatsCommodities:
    """Test commodity-related statistics."""

    def test_multi_commodity(self):
        """Should count unique commodities."""
        j = _make_multi_commodity_journal()
        result = stats_command(j, today=date(2024, 4, 1))
        # $ and EUR
        # The stats output doesn't have a dedicated "commodities" line in
        # ledger's C++ code, but we test what we do output.
        assert "Unique payees:               1" in result
        assert "Unique accounts:             2" in result


# ---------------------------------------------------------------------------
# Tests: file tracking
# ---------------------------------------------------------------------------


class TestStatsFiles:
    """Test source file tracking."""

    def test_files_listed(self):
        """Source files should appear in output."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        assert "/tmp/test.dat" in result
        assert "Files these postings came from:" in result

    def test_journal_sources(self):
        """Files from journal.sources should be included."""
        j = Journal()
        j.sources.append("/path/to/ledger.dat")

        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        acct_a = j.find_account("A")
        acct_b = j.find_account("B")
        p1 = Post(account=acct_a, amount=Amount("$10.00"))
        p2 = Post(account=acct_b, amount=Amount("$-10.00"))
        acct_a.add_post(p1)
        acct_b.add_post(p2)
        xact.add_post(p1)
        xact.add_post(p2)
        j.add_xact(xact)

        result = stats_command(j, today=date(2024, 2, 1))
        assert "/path/to/ledger.dat" in result

    def test_no_file_info(self):
        """When no file info exists, should show placeholder."""
        j = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        acct_a = j.find_account("A")
        acct_b = j.find_account("B")
        p1 = Post(account=acct_a, amount=Amount("$10.00"))
        p2 = Post(account=acct_b, amount=Amount("$-10.00"))
        acct_a.add_post(p1)
        acct_b.add_post(p2)
        xact.add_post(p1)
        xact.add_post(p2)
        j.add_xact(xact)

        result = stats_command(j, today=date(2024, 2, 1))
        assert "(no file information)" in result


# ---------------------------------------------------------------------------
# Tests: time-window counts
# ---------------------------------------------------------------------------


class TestStatsTimeWindows:
    """Test posts-in-last-N-days and this-month counts."""

    def test_posts_last_7_days(self):
        """Should count posts in last 7 days."""
        j = _make_journal()
        # today = 2024/01/22, so last 7 days = 2024/01/16..2024/01/22
        # xact3 on 2024/01/20 has 2 posts -> 2 posts in last 7 days
        result = stats_command(j, today=date(2024, 1, 22))
        assert "Posts in last 7 days:        2" in result

    def test_posts_last_30_days(self):
        """Should count posts in last 30 days."""
        j = _make_journal()
        # today = 2024/01/22, last 30 days includes all 3 xacts (6 posts)
        result = stats_command(j, today=date(2024, 1, 22))
        assert "Posts in last 30 days:       6" in result

    def test_posts_this_month(self):
        """Should count posts in the current month."""
        j = _make_journal()
        # today = 2024/01/22, all 3 xacts are in January -> 6 posts
        result = stats_command(j, today=date(2024, 1, 22))
        assert "Posts seen this month:       6" in result

    def test_posts_this_month_different_month(self):
        """Posts from a different month shouldn't count."""
        j = _make_journal()
        # today = 2024/02/15, no xacts in February -> 0 this month
        result = stats_command(j, today=date(2024, 2, 15))
        assert "Posts seen this month:       0" in result


# ---------------------------------------------------------------------------
# Tests: output formatting
# ---------------------------------------------------------------------------


class TestStatsFormatting:
    """Test overall output formatting."""

    def test_output_ends_with_newline(self):
        """Output should end with a newline."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        assert result.endswith("\n")

    def test_output_has_blank_separator_lines(self):
        """Output should have blank lines separating sections."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        lines = result.split("\n")
        # After time period line there should be a blank line
        assert lines[1] == ""

    def test_full_output_structure(self):
        """Verify the complete output structure."""
        j = _make_journal()
        result = stats_command(j, today=date(2024, 2, 1))
        # Check key sections exist in order
        sections = [
            "Time period:",
            "Files these postings came from:",
            "Unique payees:",
            "Unique accounts:",
            "Number of postings:",
            "Uncleared postings:",
            "Days since last post:",
            "Posts in last 7 days:",
            "Posts in last 30 days:",
            "Posts seen this month:",
        ]
        last_pos = -1
        for section in sections:
            pos = result.find(section)
            assert pos > last_pos, f"Section '{section}' not found or out of order"
            last_pos = pos
