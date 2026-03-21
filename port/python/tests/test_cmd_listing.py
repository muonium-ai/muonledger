"""Tests for the listing commands: accounts, payees, tags, commodities."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.commodity import CommodityPool
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.listing import (
    accounts_command,
    payees_command,
    tags_command,
    commodities_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global commodity pool between tests."""
    CommodityPool.reset_current()
    yield
    CommodityPool.reset_current()


def _make_journal_with_xacts() -> Journal:
    """Create a journal with several transactions for testing."""
    j = Journal()

    # Transaction 1: Grocery Store
    xact1 = Transaction(payee="Grocery Store")
    xact1.date = date(2024, 1, 15)
    acct_food = j.find_account("Expenses:Food")
    acct_checking = j.find_account("Assets:Bank:Checking")
    post1a = Post(account=acct_food, amount=Amount("$42.50"))
    post1b = Post(account=acct_checking)
    xact1.add_post(post1a)
    xact1.add_post(post1b)
    j.add_xact(xact1)

    # Transaction 2: Electric Company
    xact2 = Transaction(payee="Electric Company")
    xact2.date = date(2024, 1, 20)
    acct_util = j.find_account("Expenses:Utilities")
    post2a = Post(account=acct_util, amount=Amount("$85.00"))
    post2b = Post(account=acct_checking)
    xact2.add_post(post2a)
    xact2.add_post(post2b)
    j.add_xact(xact2)

    # Transaction 3: Salary
    xact3 = Transaction(payee="Acme Corp")
    xact3.date = date(2024, 1, 31)
    acct_income = j.find_account("Income:Salary")
    post3a = Post(account=acct_checking, amount=Amount("$3000.00"))
    post3b = Post(account=acct_income)
    xact3.add_post(post3a)
    xact3.add_post(post3b)
    j.add_xact(xact3)

    return j


def _make_journal_with_tags() -> Journal:
    """Create a journal with metadata tags on transactions and postings."""
    j = Journal()

    xact1 = Transaction(payee="Restaurant")
    xact1.date = date(2024, 2, 1)
    xact1.set_tag("Category", "dining")
    xact1.set_tag("Receipt")
    acct_food = j.find_account("Expenses:Food:Dining")
    acct_checking = j.find_account("Assets:Checking")
    post1a = Post(account=acct_food, amount=Amount("$25.00"))
    post1a.set_tag("Tip", "$5.00")
    post1b = Post(account=acct_checking)
    xact1.add_post(post1a)
    xact1.add_post(post1b)
    j.add_xact(xact1)

    xact2 = Transaction(payee="Gas Station")
    xact2.date = date(2024, 2, 5)
    xact2.set_tag("Category", "transport")
    acct_gas = j.find_account("Expenses:Transport:Gas")
    post2a = Post(account=acct_gas, amount=Amount("$40.00"))
    post2a.set_tag("Mileage", "150")
    post2b = Post(account=acct_checking)
    xact2.add_post(post2a)
    xact2.add_post(post2b)
    j.add_xact(xact2)

    return j


def _make_journal_with_commodities() -> Journal:
    """Create a journal with multiple commodities including costs."""
    j = Journal()

    # Buy stock: 10 AAPL @ $150
    xact1 = Transaction(payee="Stock Purchase")
    xact1.date = date(2024, 3, 1)
    acct_invest = j.find_account("Assets:Investment")
    acct_checking = j.find_account("Assets:Checking")
    post1a = Post(account=acct_invest, amount=Amount("10 AAPL"))
    post1a.cost = Amount("$1500.00")
    post1b = Post(account=acct_checking, amount=Amount("$-1500.00"))
    xact1.add_post(post1a)
    xact1.add_post(post1b)
    j.add_xact(xact1)

    # EUR transaction
    xact2 = Transaction(payee="European Purchase")
    xact2.date = date(2024, 3, 5)
    acct_food = j.find_account("Expenses:Food")
    acct_euro = j.find_account("Assets:EuroAccount")
    post2a = Post(account=acct_food, amount=Amount("50 EUR"))
    post2b = Post(account=acct_euro, amount=Amount("-50 EUR"))
    xact2.add_post(post2a)
    xact2.add_post(post2b)
    j.add_xact(xact2)

    return j


# ===========================================================================
# accounts_command tests
# ===========================================================================

class TestAccountsCommand:
    def test_basic_listing(self):
        j = _make_journal_with_xacts()
        result = accounts_command(j)
        lines = result.strip().split("\n")
        assert "Assets:Bank:Checking" in lines
        assert "Expenses:Food" in lines
        assert "Expenses:Utilities" in lines
        assert "Income:Salary" in lines

    def test_sorted_output(self):
        j = _make_journal_with_xacts()
        result = accounts_command(j)
        lines = result.strip().split("\n")
        assert lines == sorted(lines)

    def test_hierarchical_accounts(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        acct_deep = j.find_account("A:B:C:D")
        acct_shallow = j.find_account("X")
        post1 = Post(account=acct_deep, amount=Amount("$10.00"))
        post2 = Post(account=acct_shallow)
        xact.add_post(post1)
        xact.add_post(post2)
        j.add_xact(xact)
        result = accounts_command(j)
        lines = result.strip().split("\n")
        assert "A:B:C:D" in lines
        assert "X" in lines

    def test_empty_journal(self):
        j = Journal()
        result = accounts_command(j)
        assert result == ""

    def test_count_mode(self):
        j = _make_journal_with_xacts()
        result = accounts_command(j, ["--count"])
        lines = result.strip().split("\n")
        # Assets:Bank:Checking appears in all 3 transactions
        assert "3 Assets:Bank:Checking" in lines

    def test_filter_pattern(self):
        j = _make_journal_with_xacts()
        result = accounts_command(j, ["Grocery"])
        lines = result.strip().split("\n")
        # Only accounts from the Grocery Store transaction
        assert "Expenses:Food" in lines
        assert "Assets:Bank:Checking" in lines
        # Utilities should not appear
        assert "Expenses:Utilities" not in lines

    def test_deduplication(self):
        """Accounts appearing in multiple transactions are listed once."""
        j = _make_journal_with_xacts()
        result = accounts_command(j)
        lines = result.strip().split("\n")
        # Assets:Bank:Checking appears in all 3 xacts but should be listed once
        assert lines.count("Assets:Bank:Checking") == 1


# ===========================================================================
# payees_command tests
# ===========================================================================

class TestPayeesCommand:
    def test_basic_listing(self):
        j = _make_journal_with_xacts()
        result = payees_command(j)
        lines = result.strip().split("\n")
        assert "Acme Corp" in lines
        assert "Electric Company" in lines
        assert "Grocery Store" in lines

    def test_sorted_output(self):
        j = _make_journal_with_xacts()
        result = payees_command(j)
        lines = result.strip().split("\n")
        assert lines == sorted(lines)

    def test_unique_payees(self):
        """Duplicate payees are listed only once."""
        j = Journal()
        for _ in range(3):
            xact = Transaction(payee="Same Payee")
            xact.date = date(2024, 1, 1)
            acct_a = j.find_account("A")
            acct_b = j.find_account("B")
            post1 = Post(account=acct_a, amount=Amount("$10.00"))
            post2 = Post(account=acct_b)
            xact.add_post(post1)
            xact.add_post(post2)
            j.add_xact(xact)

        result = payees_command(j)
        lines = result.strip().split("\n")
        assert lines == ["Same Payee"]

    def test_empty_journal(self):
        j = Journal()
        result = payees_command(j)
        assert result == ""

    def test_count_mode(self):
        j = Journal()
        for _ in range(3):
            xact = Transaction(payee="Repeated Payee")
            xact.date = date(2024, 1, 1)
            acct_a = j.find_account("A")
            acct_b = j.find_account("B")
            post1 = Post(account=acct_a, amount=Amount("$10.00"))
            post2 = Post(account=acct_b)
            xact.add_post(post1)
            xact.add_post(post2)
            j.add_xact(xact)

        result = payees_command(j, ["--count"])
        lines = result.strip().split("\n")
        assert "3 Repeated Payee" in lines

    def test_filter_pattern(self):
        j = _make_journal_with_xacts()
        # Filter by account name in postings
        result = payees_command(j, ["Food"])
        lines = result.strip().split("\n")
        assert "Grocery Store" in lines
        assert "Electric Company" not in lines

    def test_empty_payee_excluded(self):
        """Transactions with empty payees are not listed."""
        j = Journal()
        xact = Transaction(payee="")
        xact.date = date(2024, 1, 1)
        acct_a = j.find_account("A")
        acct_b = j.find_account("B")
        post1 = Post(account=acct_a, amount=Amount("$10.00"))
        post2 = Post(account=acct_b)
        xact.add_post(post1)
        xact.add_post(post2)
        j.add_xact(xact)

        result = payees_command(j)
        assert result == ""


# ===========================================================================
# tags_command tests
# ===========================================================================

class TestTagsCommand:
    def test_basic_listing(self):
        j = _make_journal_with_tags()
        result = tags_command(j)
        lines = result.strip().split("\n")
        assert "Category" in lines
        assert "Receipt" in lines
        assert "Tip" in lines
        assert "Mileage" in lines

    def test_sorted_output(self):
        j = _make_journal_with_tags()
        result = tags_command(j)
        lines = result.strip().split("\n")
        assert lines == sorted(lines)

    def test_deduplication(self):
        """Tags appearing on multiple items are listed once (without --count)."""
        j = _make_journal_with_tags()
        result = tags_command(j)
        lines = result.strip().split("\n")
        # "Category" appears on 2 transactions
        assert lines.count("Category") == 1

    def test_tags_from_transactions_and_postings(self):
        """Tags are collected from both transaction and posting metadata."""
        j = _make_journal_with_tags()
        result = tags_command(j)
        lines = result.strip().split("\n")
        # Transaction-level tags
        assert "Category" in lines
        assert "Receipt" in lines
        # Posting-level tags
        assert "Tip" in lines
        assert "Mileage" in lines

    def test_empty_journal(self):
        j = Journal()
        result = tags_command(j)
        assert result == ""

    def test_no_tags(self):
        """Journal with transactions but no tags."""
        j = _make_journal_with_xacts()
        result = tags_command(j)
        assert result == ""

    def test_count_mode(self):
        j = _make_journal_with_tags()
        result = tags_command(j, ["--count"])
        lines = result.strip().split("\n")
        # "Category" appears on 2 transactions
        assert "2 Category" in lines
        # "Receipt" appears on 1 transaction
        assert "1 Receipt" in lines
        # "Tip" appears on 1 posting
        assert "1 Tip" in lines

    def test_filter_pattern(self):
        j = _make_journal_with_tags()
        result = tags_command(j, ["Restaurant"])
        lines = result.strip().split("\n")
        assert "Category" in lines
        assert "Receipt" in lines
        assert "Tip" in lines
        # Mileage is on the Gas Station transaction, not Restaurant
        assert "Mileage" not in lines


# ===========================================================================
# commodities_command tests
# ===========================================================================

class TestCommoditiesCommand:
    def test_basic_listing(self):
        j = _make_journal_with_xacts()
        result = commodities_command(j)
        lines = result.strip().split("\n")
        assert "$" in lines

    def test_multiple_commodities(self):
        j = _make_journal_with_commodities()
        result = commodities_command(j)
        lines = result.strip().split("\n")
        assert "$" in lines
        assert "AAPL" in lines
        assert "EUR" in lines

    def test_sorted_output(self):
        j = _make_journal_with_commodities()
        result = commodities_command(j)
        lines = result.strip().split("\n")
        assert lines == sorted(lines)

    def test_commodities_from_costs(self):
        """Commodities in cost amounts are included."""
        j = _make_journal_with_commodities()
        result = commodities_command(j)
        # $ appears as the cost commodity of the AAPL purchase
        assert "$" in result

    def test_empty_journal(self):
        j = Journal()
        result = commodities_command(j)
        assert result == ""

    def test_no_commodity(self):
        """Amounts without commodities don't produce output."""
        j = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        acct_a = j.find_account("A")
        acct_b = j.find_account("B")
        post1 = Post(account=acct_a, amount=Amount(100))
        post2 = Post(account=acct_b, amount=Amount(-100))
        xact.add_post(post1)
        xact.add_post(post2)
        j.add_xact(xact)

        result = commodities_command(j)
        assert result == ""

    def test_count_mode(self):
        j = _make_journal_with_commodities()
        result = commodities_command(j, ["--count"])
        lines = result.strip().split("\n")
        # $ appears in multiple postings (cost + direct amounts)
        # Find the $ line
        dollar_line = [l for l in lines if l.endswith("$")][0]
        count = int(dollar_line.split()[0])
        assert count >= 2  # At least in the cost and the direct $-1500

    def test_filter_pattern(self):
        j = _make_journal_with_commodities()
        result = commodities_command(j, ["European"])
        lines = result.strip().split("\n")
        assert "EUR" in lines
        # AAPL is from Stock Purchase, not European Purchase
        assert "AAPL" not in lines

    def test_deduplication(self):
        """Same commodity from multiple postings listed only once."""
        j = _make_journal_with_xacts()
        result = commodities_command(j)
        lines = result.strip().split("\n")
        assert lines.count("$") == 1
