"""Tests for the textual journal parser."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from muonledger.amount import Amount
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.parser import ParseError, TextualParser
from muonledger.post import POST_COST_IN_FULL, POST_MUST_BALANCE, POST_VIRTUAL


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
# Basic transaction parsing
# ---------------------------------------------------------------------------


class TestSimpleTransaction:
    """Test parsing a minimal 2-posting transaction."""

    def test_two_postings(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.payee == "Grocery Store"
        assert xact.date == date(2024, 1, 15)
        assert len(xact.posts) == 2
        assert xact.posts[0].account.fullname == "Expenses:Food"
        assert str(xact.posts[0].amount) == "$42.50"
        # Second posting auto-balanced
        assert xact.posts[1].account.fullname == "Assets:Checking"
        assert xact.posts[1].amount is not None
        assert xact.posts[1].amount.is_negative()

    def test_parse_string_returns_count(self):
        text = """\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        count = parser.parse_string(text, journal)
        assert count == 1


class TestMultipleTransactions:
    """Test parsing multiple transactions."""

    def test_three_transactions(self):
        text = """\
2024/01/01 Opening Balance
    Assets:Checking     $1000.00
    Equity:Opening

2024/01/05 Coffee Shop
    Expenses:Dining     $4.50
    Assets:Checking

2024/01/10 Salary
    Assets:Checking     $3000.00
    Income:Salary
"""
        journal = _parse(text)
        assert len(journal.xacts) == 3
        assert journal.xacts[0].payee == "Opening Balance"
        assert journal.xacts[1].payee == "Coffee Shop"
        assert journal.xacts[2].payee == "Salary"

    def test_transactions_without_blank_lines(self):
        """Transactions separated by non-indented date lines."""
        text = """\
2024/01/01 First
    Expenses:A     $10.00
    Assets:B
2024/01/02 Second
    Expenses:C     $20.00
    Assets:D
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    def test_slash_date(self):
        text = """\
2024/03/15 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].date == date(2024, 3, 15)

    def test_dash_date(self):
        text = """\
2024-03-15 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].date == date(2024, 3, 15)

    def test_aux_date(self):
        text = """\
2024/03/15=2024/03/10 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 3, 15)
        assert xact.date_aux == date(2024, 3, 10)

    def test_aux_date_dash(self):
        text = """\
2024-03-15=2024-03-10 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 3, 15)
        assert xact.date_aux == date(2024, 3, 10)


# ---------------------------------------------------------------------------
# State markers
# ---------------------------------------------------------------------------


class TestStateMarkers:
    def test_cleared(self):
        text = """\
2024/01/01 * Cleared Transaction
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].state == ItemState.CLEARED

    def test_pending(self):
        text = """\
2024/01/01 ! Pending Transaction
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].state == ItemState.PENDING

    def test_uncleared(self):
        text = """\
2024/01/01 Uncleared Transaction
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].state == ItemState.UNCLEARED

    def test_posting_state(self):
        text = """\
2024/01/01 Test
    * Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].state == ItemState.CLEARED


# ---------------------------------------------------------------------------
# Code parsing
# ---------------------------------------------------------------------------


class TestCodeParsing:
    def test_code(self):
        text = """\
2024/01/01 (1042) Grocery Store
    Expenses:Food     $10.00
    Assets:Checking
"""
        journal = _parse(text)
        assert journal.xacts[0].code == "1042"

    def test_code_with_state(self):
        text = """\
2024/01/01 * (CHK#100) Payee
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.state == ItemState.CLEARED
        assert xact.code == "CHK#100"
        assert xact.payee == "Payee"

    def test_no_code(self):
        text = """\
2024/01/01 Payee
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].code is None


# ---------------------------------------------------------------------------
# Amount formats
# ---------------------------------------------------------------------------


class TestAmountFormats:
    def test_prefix_commodity(self):
        text = """\
2024/01/01 Test
    Expenses:A     $100.00
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert amt.commodity == "$"
        assert float(amt) == 100.00

    def test_suffix_commodity(self):
        text = """\
2024/01/01 Test
    Expenses:A     100.00 EUR
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert amt.commodity == "EUR"
        assert float(amt) == 100.00

    def test_suffix_commodity_symbol(self):
        """Test euro symbol suffix like in the sample file."""
        text = """\
2024/01/01 Test
    Expenses:A     500.00\u20ac
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == 500.00

    def test_negative_amount(self):
        text = """\
2024/01/01 Test
    Expenses:A     $100.00
    Assets:B       -$100.00
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[1].amount
        assert float(amt) == -100.00


# ---------------------------------------------------------------------------
# Auto-balance
# ---------------------------------------------------------------------------


class TestAutoBalance:
    def test_single_null_posting(self):
        text = """\
2024/01/01 Test
    Expenses:Food     $42.50
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 2
        balanced_post = xact.posts[1]
        assert balanced_post.amount is not None
        # Should be the negative of the first posting
        assert float(balanced_post.amount) == pytest.approx(-42.50)

    def test_multiple_postings_one_null(self):
        text = """\
2024/01/01 Test
    Expenses:Food     $20.00
    Expenses:Drink    $10.00
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 3
        assert float(xact.posts[2].amount) == pytest.approx(-30.00)


# ---------------------------------------------------------------------------
# Virtual accounts
# ---------------------------------------------------------------------------


class TestVirtualAccounts:
    def test_virtual_parenthesized(self):
        """Virtual posting with parentheses does not need to balance."""
        text = """\
2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Checking   -$10.00
    (Budget:Food)     $-10.00
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 3
        vpost = xact.posts[2]
        assert vpost.is_virtual()
        assert not vpost.must_balance()
        assert vpost.account.fullname == "Budget:Food"

    def test_virtual_bracketed(self):
        """Balanced virtual posting with brackets must balance."""
        text = """\
2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Checking   -$10.00
    [Budget:Food]     $0.00
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        vpost = xact.posts[2]
        assert vpost.is_virtual()
        assert vpost.must_balance()
        assert vpost.account.fullname == "Budget:Food"


# ---------------------------------------------------------------------------
# Cost (@ and @@)
# ---------------------------------------------------------------------------


class TestCost:
    def test_per_unit_cost(self):
        text = """\
2024/01/01 Investment
    Assets:Brokerage     50 AAPL @ $30.00
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        post = xact.posts[0]
        assert float(post.amount) == 50.0
        assert post.amount.commodity == "AAPL"
        # Cost should be total = 50 * $30 = $1500
        assert post.cost is not None
        assert float(post.cost) == pytest.approx(1500.0)
        assert post.cost.commodity == "$"

    def test_total_cost(self):
        text = """\
2024/01/01 Investment
    Assets:Brokerage     50 AAPL @@ $1500.00
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        post = xact.posts[0]
        assert float(post.amount) == 50.0
        assert post.amount.commodity == "AAPL"
        assert post.cost is not None
        assert float(post.cost) == pytest.approx(1500.0)
        assert post.has_flags(POST_COST_IN_FULL)


# ---------------------------------------------------------------------------
# Comments and metadata
# ---------------------------------------------------------------------------


class TestCommentsAndMetadata:
    def test_comment_lines_skipped(self):
        text = """\
; This is a comment
# Another comment
2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_inline_xact_note(self):
        text = """\
2024/01/01 Test ; transaction note
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].note is not None
        assert "transaction note" in journal.xacts[0].note

    def test_posting_inline_comment(self):
        text = """\
2024/01/01 Test
    Expenses:A     $10.00 ; posting note
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.note is not None
        assert "posting note" in post.note

    def test_metadata_key_value(self):
        text = """\
2024/01/01 Test
    ; Sample: Value
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.get_tag("Sample") == "Value"

    def test_metadata_tags(self):
        text = """\
2024/01/01 Test
    Expenses:A     $10.00
    ; :MyTag:AnotherTag:
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.has_tag("MyTag")
        assert post.has_tag("AnotherTag")

    def test_posting_metadata(self):
        text = """\
2024/01/01 Test
    Expenses:A     $10.00
    ; Sample: Another Value
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.get_tag("Sample") == "Another Value"


# ---------------------------------------------------------------------------
# Parsing from file
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_parse_from_file(self, tmp_path):
        journal_file = tmp_path / "test.dat"
        journal_file.write_text("""\
2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
""")
        journal = Journal()
        parser = TextualParser()
        count = parser.parse(journal_file, journal)
        assert count == 1
        assert str(journal_file) in journal.sources

    def test_parse_from_string(self):
        text = """\
2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = Journal()
        parser = TextualParser()
        count = parser.parse_string(text, journal)
        assert count == 1


# ---------------------------------------------------------------------------
# Realistic multi-transaction journal
# ---------------------------------------------------------------------------


class TestRealisticJournal:
    """Parse a journal similar to sample.dat."""

    JOURNAL_TEXT = """\
; Sample ledger file

2024/05/01 * Opening Balance
    Assets:Bank:Checking                           $1,000.00
    Equity:Opening Balances

2024/05/03=2024/05/01 * Investment purchase
    Assets:Brokerage                                 50 AAPL @ $30.00
    Equity:Opening Balances

2024/05/14 * Payday
    Assets:Bank:Checking                             $500.00
    Income:Salary

2024/05/27 (100) Credit card company
    ; This is an xact note!
    ; Sample: Value
    Liabilities:MasterCard                            $20.00
    ; This is a posting note!
    ; Sample: Another Value
    ; :MyTag:
    Assets:Bank:Checking
    ; :AnotherTag:
"""

    def test_parse_all_transactions(self):
        journal = _parse(self.JOURNAL_TEXT)
        assert len(journal.xacts) == 4

    def test_first_transaction(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 5, 1)
        assert xact.state == ItemState.CLEARED
        assert xact.payee == "Opening Balance"
        assert len(xact.posts) == 2

    def test_investment_transaction(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[1]
        assert xact.date == date(2024, 5, 3)
        assert xact.date_aux == date(2024, 5, 1)
        post = xact.posts[0]
        assert post.account.fullname == "Assets:Brokerage"
        assert post.amount.commodity == "AAPL"
        assert post.cost is not None

    def test_code_transaction(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[3]
        assert xact.code == "100"
        assert xact.payee == "Credit card company"

    def test_metadata_on_transaction(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[3]
        assert xact.get_tag("Sample") == "Value"

    def test_metadata_on_posting(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[3]
        # First posting (Liabilities:MasterCard) has metadata attached
        post0 = xact.posts[0]
        assert post0.get_tag("Sample") == "Another Value"
        assert post0.has_tag("MyTag")

    def test_second_posting_tag(self):
        journal = _parse(self.JOURNAL_TEXT)
        xact = journal.xacts[3]
        post1 = xact.posts[1]
        assert post1.has_tag("AnotherTag")

    def test_account_tree(self):
        journal = _parse(self.JOURNAL_TEXT)
        # Check that the account tree was built
        checking = journal.find_account(
            "Assets:Bank:Checking", auto_create=False
        )
        assert checking is not None
        assert checking.fullname == "Assets:Bank:Checking"

    def test_all_balances(self):
        """Verify all transactions balance (no BalanceError raised)."""
        # This is implicitly tested by _parse succeeding, but be explicit
        journal = _parse(self.JOURNAL_TEXT)
        assert all(len(x.posts) >= 2 for x in journal.xacts)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self):
        journal = _parse("")
        assert len(journal.xacts) == 0

    def test_only_comments(self):
        journal = _parse("; comment\n# another\n")
        assert len(journal.xacts) == 0

    def test_account_with_spaces(self):
        """Account names can contain single spaces."""
        text = """\
2024/01/01 Test
    Expenses:Food and Drink  $10.00
    Assets:Bank Account
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Food and Drink"

    def test_tab_separated(self):
        """Tab separates account from amount."""
        text = "2024/01/01 Test\n\tExpenses:Food\t$10.00\n\tAssets:Cash\n"
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Food"

    def test_thousands_separator(self):
        text = """\
2024/01/01 Test
    Assets:Checking     $1,000.00
    Equity:Opening
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(1000.00)

    def test_was_loaded_flag(self):
        journal = _parse("2024/01/01 T\n    E:A  $1\n    A:B\n")
        assert journal.was_loaded is True

    def test_skip_automated_transactions(self):
        text = """\
= /^Expenses:Books/
    (Liabilities:Taxes)  -0.10

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_skip_periodic_transactions(self):
        text = """\
~ Monthly
    Assets:Bank:Checking  $500.00
    Income:Salary

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
