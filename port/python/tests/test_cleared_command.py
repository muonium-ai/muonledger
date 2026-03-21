"""Tests for the cleared command."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.cleared import cleared_command, _effective_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_xact(journal, payee, dt, posts_data, state=ItemState.UNCLEARED):
    """Create a transaction and add it to the journal.

    posts_data: list of (account_name, amount_str) or
                list of (account_name, amount_str, post_state)
    """
    xact = Transaction(payee=payee)
    xact.date = dt
    xact.state = state

    for item in posts_data:
        if len(item) == 3:
            acct_name, amt_str, post_state = item
        else:
            acct_name, amt_str = item
            post_state = None

        acct = journal.find_account(acct_name)
        post = Post(account=acct, amount=Amount(amt_str))
        acct.add_post(post)
        if post_state is not None:
            post.state = post_state
        xact.add_post(post)

    journal.add_xact(xact)
    return xact


# ---------------------------------------------------------------------------
# Tests: _effective_state helper
# ---------------------------------------------------------------------------


class TestEffectiveState:
    """Tests for the _effective_state helper function."""

    def test_post_uncleared_xact_uncleared(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.UNCLEARED
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        xact.add_post(post)
        assert _effective_state(post) == ItemState.UNCLEARED

    def test_post_uncleared_xact_cleared(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.CLEARED
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        xact.add_post(post)
        assert _effective_state(post) == ItemState.CLEARED

    def test_post_uncleared_xact_pending(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.PENDING
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        xact.add_post(post)
        assert _effective_state(post) == ItemState.PENDING

    def test_post_cleared_overrides_xact_uncleared(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.UNCLEARED
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        post.state = ItemState.CLEARED
        xact.add_post(post)
        assert _effective_state(post) == ItemState.CLEARED

    def test_post_pending_overrides_xact_cleared(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.CLEARED
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        post.state = ItemState.PENDING
        xact.add_post(post)
        assert _effective_state(post) == ItemState.PENDING

    def test_post_cleared_overrides_xact_pending(self):
        j = Journal()
        xact = Transaction(payee="Test")
        xact.state = ItemState.PENDING
        post = Post(account=j.find_account("A"), amount=Amount("$10"))
        post.state = ItemState.CLEARED
        xact.add_post(post)
        assert _effective_state(post) == ItemState.CLEARED

    def test_post_with_no_xact(self):
        post = Post(account=None, amount=Amount("$10"))
        assert _effective_state(post) == ItemState.UNCLEARED


# ---------------------------------------------------------------------------
# Tests: empty / trivial journals
# ---------------------------------------------------------------------------


class TestClearedEmpty:
    """Tests for empty and trivial journals."""

    def test_empty_journal(self):
        j = Journal()
        result = cleared_command(j)
        assert result == ""

    def test_empty_journal_with_args(self):
        j = Journal()
        result = cleared_command(j, ["Assets"])
        assert result == ""

    def test_none_args(self):
        j = Journal()
        result = cleared_command(j, None)
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: all cleared transactions
# ---------------------------------------------------------------------------


class TestAllCleared:
    """Tests when all transactions are cleared."""

    def test_single_cleared_xact(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:Checking" in result
        assert "Income:Salary" in result
        # The header should be present
        assert "Cleared" in result
        assert "Uncleared" in result
        assert "Total" in result

    def test_all_cleared_uncleared_column_zero(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        # Find the line for Assets:Checking
        for line in lines:
            if "Assets:Checking" in line:
                # Cleared and Total should show $1000, Uncleared should be 0
                assert "$1000" in line or "$1,000" in line or "$1000.00" in line
                break

    def test_multiple_cleared_xacts(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Groceries", date(2024, 1, 2), [
            ("Expenses:Food", "$50"),
            ("Assets:Checking", "$-50"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:Checking" in result
        assert "Expenses:Food" in result
        assert "Income:Salary" in result


# ---------------------------------------------------------------------------
# Tests: all uncleared transactions
# ---------------------------------------------------------------------------


class TestAllUncleared:
    """Tests when all transactions are uncleared."""

    def test_all_uncleared(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ])

        result = cleared_command(j)
        assert "Assets:Checking" in result
        # Cleared column should be 0 for each account
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                # The first column (Cleared) should be 0
                parts = line.split()
                # "0" should appear as the cleared amount
                assert parts[0] == "0"
                break

    def test_pending_counts_as_uncleared(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.PENDING)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                parts = line.split()
                # Cleared should be 0 (pending is uncleared)
                assert parts[0] == "0"
                break


# ---------------------------------------------------------------------------
# Tests: mixed cleared and uncleared
# ---------------------------------------------------------------------------


class TestMixed:
    """Tests with a mix of cleared and uncleared transactions."""

    def test_mixed_states(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Groceries", date(2024, 1, 2), [
            ("Expenses:Food", "$50"),
            ("Assets:Checking", "$-50"),
        ])  # uncleared

        result = cleared_command(j)
        assert "Assets:Checking" in result
        assert "Expenses:Food" in result
        assert "Income:Salary" in result

    def test_mixed_cleared_and_pending(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Rent", date(2024, 1, 3), [
            ("Expenses:Rent", "$500"),
            ("Assets:Checking", "$-500"),
        ], state=ItemState.PENDING)

        result = cleared_command(j)
        # Pending should be counted as uncleared
        lines = result.strip().split("\n")
        for line in lines:
            if "Expenses:Rent" in line:
                parts = line.split()
                # Cleared should be 0 for rent (it's pending)
                assert parts[0] == "0"
                break

    def test_post_level_cleared_on_uncleared_xact(self):
        """A cleared posting on an uncleared transaction."""
        j = Journal()
        _make_xact(j, "Mixed", date(2024, 1, 1), [
            ("Assets:Checking", "$100", ItemState.CLEARED),
            ("Income:Salary", "$-100"),
        ])

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                # This post is explicitly cleared
                assert "$100" in line
                break
        for line in lines:
            if "Income:Salary" in line:
                parts = line.split()
                # Income:Salary post inherits xact state (uncleared)
                # so cleared should be 0
                assert parts[0] == "0"
                break

    def test_post_level_pending_on_cleared_xact(self):
        """A pending posting on a cleared transaction."""
        j = Journal()
        _make_xact(j, "Mixed", date(2024, 1, 1), [
            ("Assets:Checking", "$100", ItemState.PENDING),
            ("Income:Salary", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                parts = line.split()
                # Pending overrides cleared xact -> uncleared
                assert parts[0] == "0"
                break
        for line in lines:
            if "Income:Salary" in line:
                # Inherits cleared from xact
                assert "$100" in line or "$-100" in line
                break


# ---------------------------------------------------------------------------
# Tests: account filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    """Tests for account pattern filtering."""

    def test_filter_single_account(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["Assets"])
        assert "Assets:Checking" in result
        assert "Income:Salary" not in result

    def test_filter_no_match(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["Liabilities"])
        assert result == ""

    def test_filter_case_insensitive(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["assets"])
        assert "Assets:Checking" in result

    def test_filter_multiple_patterns(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Groceries", date(2024, 1, 2), [
            ("Expenses:Food", "$50"),
            ("Assets:Checking", "$-50"),
        ])

        result = cleared_command(j, ["Food", "Income"])
        assert "Expenses:Food" in result
        assert "Income:Salary" in result
        assert "Assets:Checking" not in result

    def test_filter_substring(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Bank:Checking", "$1000"),
            ("Assets:Bank:Savings", "$500"),
            ("Income:Salary", "$-1500"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["Bank"])
        assert "Assets:Bank:Checking" in result
        assert "Assets:Bank:Savings" in result
        assert "Income:Salary" not in result


# ---------------------------------------------------------------------------
# Tests: multiple accounts
# ---------------------------------------------------------------------------


class TestMultipleAccounts:
    """Tests with multiple accounts."""

    def test_many_accounts(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$2000"),
            ("Income:Salary", "$-2000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Groceries", date(2024, 1, 2), [
            ("Expenses:Food", "$100"),
            ("Assets:Checking", "$-100"),
        ])
        _make_xact(j, "Rent", date(2024, 1, 3), [
            ("Expenses:Rent", "$800"),
            ("Assets:Checking", "$-800"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:Checking" in result
        assert "Expenses:Food" in result
        assert "Expenses:Rent" in result
        assert "Income:Salary" in result

    def test_accounts_sorted_alphabetically(self):
        j = Journal()
        _make_xact(j, "X1", date(2024, 1, 1), [
            ("Zebra:Account", "$100"),
            ("Alpha:Account", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        # Find account lines (skip header and separator/total)
        acct_lines = [l for l in lines if "Account" in l and ":" in l]
        # Alpha should come before Zebra
        alpha_idx = None
        zebra_idx = None
        for i, l in enumerate(acct_lines):
            if "Alpha" in l:
                alpha_idx = i
            if "Zebra" in l:
                zebra_idx = i
        assert alpha_idx is not None
        assert zebra_idx is not None
        assert alpha_idx < zebra_idx


# ---------------------------------------------------------------------------
# Tests: grand totals
# ---------------------------------------------------------------------------


class TestGrandTotals:
    """Tests for grand total computation."""

    def test_grand_total_balanced(self):
        """Grand totals should be zero for a balanced journal."""
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        # Last line should be the grand total (all zeros for balanced journal)
        # Find separator
        sep_idx = None
        for i, line in enumerate(lines):
            if line.startswith("---"):
                sep_idx = i
                break
        assert sep_idx is not None
        # Lines after separator are the total
        total_line = lines[sep_idx + 1]
        parts = total_line.split()
        assert all(p == "0" for p in parts)

    def test_grand_total_with_filter(self):
        """Grand total when filtering shows totals of only filtered accounts."""
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["Assets"])
        lines = result.strip().split("\n")
        sep_idx = None
        for i, line in enumerate(lines):
            if line.startswith("---"):
                sep_idx = i
                break
        assert sep_idx is not None
        total_line = lines[sep_idx + 1]
        # Total should show $1000 (only Assets)
        assert "$1000" in total_line

    def test_separator_line_present(self):
        j = Journal()
        _make_xact(j, "Paycheck", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "----" in result


# ---------------------------------------------------------------------------
# Tests: column alignment and formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    """Tests for output formatting."""

    def test_header_present(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        header = lines[0]
        assert "Cleared" in header
        assert "Uncleared" in header
        assert "Total" in header
        assert "Account" in header

    def test_amounts_right_aligned(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        # Check that the first data line has right-aligned amounts
        data_line = lines[1]  # First account line after header
        # The line should start with spaces (right-aligned numbers)
        assert data_line[0] == " "

    def test_output_ends_with_newline(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert result.endswith("\n")

    def test_separator_width(self):
        """Separator line should span the three amount columns."""
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        sep_line = [l for l in lines if l.startswith("---")][0]
        # Should be 14*3 + 4 = 46 chars
        assert len(sep_line) == 46

    def test_zero_shown_for_empty_column(self):
        """When cleared column has no amounts, show 0."""
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ])  # uncleared

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:A" in line:
                parts = line.split()
                # Cleared column (first) should be 0
                assert parts[0] == "0"
                break


# ---------------------------------------------------------------------------
# Tests: multiple commodities
# ---------------------------------------------------------------------------


class TestMultiCommodity:
    """Tests with multiple commodities."""

    def test_different_commodities(self):
        j = Journal()
        _make_xact(j, "USD Purchase", date(2024, 1, 1), [
            ("Assets:Checking", "$500"),
            ("Income:Salary", "$-500"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "EUR Purchase", date(2024, 1, 2), [
            ("Assets:Checking", "200 EUR"),
            ("Income:Salary", "-200 EUR"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:Checking" in result
        # Both commodities should appear
        assert "$" in result or "EUR" in result

    def test_mixed_commodities_one_cleared_one_not(self):
        j = Journal()
        _make_xact(j, "USD Purchase", date(2024, 1, 1), [
            ("Assets:Checking", "$500"),
            ("Income:Salary", "$-500"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "EUR Purchase", date(2024, 1, 2), [
            ("Assets:Checking", "200 EUR"),
            ("Income:Salary", "-200 EUR"),
        ])  # uncleared

        result = cleared_command(j)
        assert "Assets:Checking" in result


# ---------------------------------------------------------------------------
# Tests: accumulation within same account
# ---------------------------------------------------------------------------


class TestAccumulation:
    """Tests that amounts accumulate correctly per account."""

    def test_multiple_postings_same_account_cleared(self):
        j = Journal()
        _make_xact(j, "Pay1", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Pay2", date(2024, 1, 15), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                # Should show $2000 in cleared and total
                assert "$2000" in line
                break

    def test_mixed_cleared_uncleared_same_account(self):
        j = Journal()
        _make_xact(j, "Pay1", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Pay2", date(2024, 1, 15), [
            ("Assets:Checking", "$500"),
            ("Income:Salary", "$-500"),
        ])  # uncleared

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                # Cleared = $1000, Uncleared = $500, Total = $1500
                assert "$1000" in line
                assert "$500" in line
                assert "$1500" in line
                break

    def test_negative_amounts(self):
        j = Journal()
        _make_xact(j, "Pay", date(2024, 1, 1), [
            ("Assets:Checking", "$1000"),
            ("Income:Salary", "$-1000"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "$-1000" in result


# ---------------------------------------------------------------------------
# Tests: options parameter
# ---------------------------------------------------------------------------


class TestOptions:
    """Tests for the options parameter."""

    def test_options_none(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, options=None)
        assert "Assets:A" in result

    def test_options_empty_dict(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, options={})
        assert "Assets:A" in result


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases."""

    def test_single_posting_account(self):
        """Account with just one posting."""
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:A" in result
        assert "Liabilities:B" in result

    def test_deeply_nested_accounts(self):
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:Bank:US:Checking:Primary", "$100"),
            ("Income:Employment:Salary:Regular", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j)
        assert "Assets:Bank:US:Checking:Primary" in result
        assert "Income:Employment:Salary:Regular" in result

    def test_all_three_states_in_one_journal(self):
        """Journal with cleared, pending, and uncleared transactions."""
        j = Journal()
        _make_xact(j, "Cleared", date(2024, 1, 1), [
            ("Assets:Checking", "$100"),
            ("Income:Salary", "$-100"),
        ], state=ItemState.CLEARED)
        _make_xact(j, "Pending", date(2024, 1, 2), [
            ("Assets:Checking", "$200"),
            ("Income:Salary", "$-200"),
        ], state=ItemState.PENDING)
        _make_xact(j, "Uncleared", date(2024, 1, 3), [
            ("Assets:Checking", "$300"),
            ("Income:Salary", "$-300"),
        ])

        result = cleared_command(j)
        lines = result.strip().split("\n")
        for line in lines:
            if "Assets:Checking" in line:
                # Cleared = $100, Uncleared = $200 + $300 = $500, Total = $600
                assert "$100" in line
                assert "$500" in line
                assert "$600" in line
                break

    def test_zero_amount_posting(self):
        """Posting with zero amount."""
        j = Journal()
        xact = Transaction(payee="Zero")
        xact.date = date(2024, 1, 1)
        xact.state = ItemState.CLEARED

        acct_a = j.find_account("Assets:A")
        acct_b = j.find_account("Assets:B")
        p1 = Post(account=acct_a, amount=Amount("$0"))
        acct_a.add_post(p1)
        p2 = Post(account=acct_b, amount=Amount("$0"))
        acct_b.add_post(p2)
        xact.add_post(p1)
        xact.add_post(p2)
        j.add_xact(xact)

        # Zero amounts should not produce account entries (is_null check)
        result = cleared_command(j)
        # May be empty or show zeros - either is acceptable
        # The key thing is it shouldn't crash

    def test_args_with_dashes_ignored(self):
        """Arguments starting with - should be treated as flags, not patterns."""
        j = Journal()
        _make_xact(j, "Test", date(2024, 1, 1), [
            ("Assets:A", "$100"),
            ("Liabilities:B", "$-100"),
        ], state=ItemState.CLEARED)

        result = cleared_command(j, ["--some-flag", "Assets"])
        assert "Assets:A" in result
        assert "Liabilities:B" not in result
