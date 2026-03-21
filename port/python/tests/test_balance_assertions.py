"""Tests for balance assertions and assignments.

Balance assertions (``= AMOUNT`` after a posting) verify that the running
balance of an account equals the expected amount after the posting is applied.

Balance assignments (``= AMOUNT`` on a null-amount posting) compute the
posting amount needed to bring the account to the asserted balance.
"""

import pytest

from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.xact import BalanceAssertionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(text: str) -> Journal:
    """Parse journal text and return the journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _parse_expect_error(text: str):
    """Parse journal text expecting a BalanceAssertionError."""
    journal = Journal()
    parser = TextualParser()
    with pytest.raises(BalanceAssertionError):
        parser.parse_string(text, journal)


# ---------------------------------------------------------------------------
# Basic balance assertion tests
# ---------------------------------------------------------------------------


class TestBasicBalanceAssertion:
    """Basic balance assertion parsing and verification."""

    def test_simple_assertion_passes(self):
        """A correct balance assertion should not raise."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Purchase
    Expenses:Food  $50
    Assets:Checking  $-50 = $450
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_simple_assertion_fails(self):
        """An incorrect balance assertion should raise BalanceAssertionError."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Purchase
    Expenses:Food  $50
    Assets:Checking  $-50 = $999
"""
        _parse_expect_error(text)

    def test_assertion_on_first_posting(self):
        """Assertion on the very first posting to an account."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_on_first_posting_fails(self):
        """First posting assertion with wrong value."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $100
    Equity:Opening
"""
        _parse_expect_error(text)

    def test_assertion_zero_balance(self):
        """Assertion that balance is zero."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Close
    Expenses:Misc  $500
    Assets:Checking  $-500 = $0
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_assertion_negative_balance(self):
        """Assertion with negative balance (overdraft)."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $100
    Equity:Opening

2024/01/02 Big Purchase
    Expenses:Food  $200
    Assets:Checking  $-200 = $-100
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_assertion_negative_balance_fails(self):
        """Assertion with wrong negative balance."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $100
    Equity:Opening

2024/01/02 Big Purchase
    Expenses:Food  $200
    Assets:Checking  $-200 = $-50
"""
        _parse_expect_error(text)

    def test_assigned_amount_field_set(self):
        """The parser should set assigned_amount on the post."""
        text = """\
2024/01/01 Test
    Assets:Checking  $500 = $500
    Equity:Opening
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        checking_post = xact.posts[0]
        assert checking_post.assigned_amount is not None
        assert checking_post.assigned_amount.quantity == 500

    def test_no_assertion_field_is_none(self):
        """Posts without assertion should have assigned_amount = None."""
        text = """\
2024/01/01 Test
    Assets:Checking  $500
    Equity:Opening
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        for post in xact.posts:
            assert post.assigned_amount is None


# ---------------------------------------------------------------------------
# Multiple assertions
# ---------------------------------------------------------------------------


class TestMultipleAssertions:
    """Multiple balance assertions in one or across transactions."""

    def test_multiple_assertions_one_xact(self):
        """Multiple assertions in a single transaction."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $1000 = $1000
    Assets:Savings   $2000 = $2000
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_multiple_assertions_across_xacts(self):
        """Assertions across multiple transactions track running balance."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $1000 = $1000
    Equity:Opening

2024/01/02 Deposit
    Assets:Checking  $500 = $1500
    Income:Salary

2024/01/03 Purchase
    Expenses:Food  $50
    Assets:Checking  $-50 = $1450
"""
        journal = _parse(text)
        assert len(journal.xacts) == 3

    def test_assertion_chain_fails_midway(self):
        """Third assertion fails because balance is wrong."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $1000 = $1000
    Equity:Opening

2024/01/02 Deposit
    Assets:Checking  $500 = $1500
    Income:Salary

2024/01/03 Purchase
    Expenses:Food  $50
    Assets:Checking  $-50 = $9999
"""
        _parse_expect_error(text)

    def test_both_sides_asserted(self):
        """Both sides of a transaction have assertions."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Transfer
    Assets:Checking  $-100 = $400
    Assets:Savings   $100 = $100
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2


# ---------------------------------------------------------------------------
# Different commodities
# ---------------------------------------------------------------------------


class TestCommodityAssertions:
    """Balance assertions with different commodities."""

    def test_eur_assertion(self):
        """Assertion with EUR commodity."""
        text = """\
2024/01/01 Opening
    Assets:Euro  100 EUR = 100 EUR
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_eur_assertion_fails(self):
        """EUR assertion with wrong value."""
        text = """\
2024/01/01 Opening
    Assets:Euro  100 EUR = 50 EUR
    Equity:Opening
"""
        _parse_expect_error(text)

    def test_suffix_commodity(self):
        """Assertion with suffix commodity notation."""
        text = """\
2024/01/01 Opening
    Assets:Euro  100 EUR
    Equity:Opening

2024/01/02 Spend
    Expenses:Food  25 EUR
    Assets:Euro  -25 EUR = 75 EUR
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_prefix_symbol(self):
        """Assertion with prefix symbol like $."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $1000
    Equity:Opening

2024/01/02 Withdraw
    Expenses:Cash  $200
    Assets:Checking  $-200 = $800
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2


# ---------------------------------------------------------------------------
# Cost (@) with assertions
# ---------------------------------------------------------------------------


class TestCostWithAssertion:
    """Balance assertions combined with cost notation."""

    def test_assertion_after_per_unit_cost(self):
        """Assertion after @ per-unit cost."""
        text = """\
2024/01/01 Buy Stock
    Assets:Brokerage  10 AAPL @ $150
    Assets:Checking  $-1500 = $-1500
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_after_total_cost(self):
        """Assertion after @@ total cost."""
        text = """\
2024/01/01 Buy Stock
    Assets:Brokerage  10 AAPL @@ $1500
    Assets:Checking  $-1500 = $-1500
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_on_commodity_with_cost(self):
        """Assertion on the commodity side (not the cost side)."""
        text = """\
2024/01/01 Buy Stock
    Assets:Brokerage  10 AAPL @ $150 = 10 AAPL
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        brokerage_post = journal.xacts[0].posts[0]
        assert brokerage_post.assigned_amount is not None


# ---------------------------------------------------------------------------
# Balance assignments (null-amount posting with assertion)
# ---------------------------------------------------------------------------


class TestBalanceAssignment:
    """Balance assignment: null-amount posting with = AMOUNT."""

    def test_basic_assignment(self):
        """Null amount with assertion computes the needed amount."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Adjust
    Assets:Checking  = $600
    Income:Adjustment
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2
        # The assignment should have set the amount to $100
        adjust_xact = journal.xacts[1]
        checking_post = adjust_xact.posts[0]
        assert checking_post.amount is not None
        assert checking_post.amount.quantity == 100

    def test_assignment_from_zero(self):
        """Assignment on first posting to an account (balance starts at 0)."""
        text = """\
2024/01/01 Opening
    Assets:Checking  = $500
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        checking_post = journal.xacts[0].posts[0]
        assert checking_post.amount is not None
        assert checking_post.amount.quantity == 500

    def test_assignment_reduces_balance(self):
        """Assignment that reduces balance (negative amount inferred)."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Adjust Down
    Assets:Checking  = $300
    Expenses:Adjustment
"""
        journal = _parse(text)
        adjust_xact = journal.xacts[1]
        checking_post = adjust_xact.posts[0]
        assert checking_post.amount is not None
        assert checking_post.amount.quantity == -200

    def test_assignment_to_zero(self):
        """Assignment that brings balance to zero."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Close
    Assets:Checking  = $0
    Expenses:Close
"""
        journal = _parse(text)
        adjust_xact = journal.xacts[1]
        checking_post = adjust_xact.posts[0]
        assert checking_post.amount is not None
        assert checking_post.amount.quantity == -500

    def test_assignment_negative_target(self):
        """Assignment with a negative target balance."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $100
    Equity:Opening

2024/01/02 Overdraft
    Assets:Checking  = $-50
    Expenses:Overdraft
"""
        journal = _parse(text)
        adjust_xact = journal.xacts[1]
        checking_post = adjust_xact.posts[0]
        assert checking_post.amount is not None
        assert checking_post.amount.quantity == -150


# ---------------------------------------------------------------------------
# Inline comment with assertion
# ---------------------------------------------------------------------------


class TestAssertionWithComments:
    """Balance assertions combined with inline comments."""

    def test_assertion_before_comment(self):
        """Assertion appears before the inline comment."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500 ; opening balance
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        post = journal.xacts[0].posts[0]
        assert post.assigned_amount is not None
        assert post.assigned_amount.quantity == 500

    def test_no_assertion_plain_comment(self):
        """Plain comment without assertion."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500  ; just a comment
    Equity:Opening
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.assigned_amount is None


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------


class TestErrorMessages:
    """BalanceAssertionError contains useful information."""

    def test_error_includes_expected_and_actual(self):
        """Error message should mention expected and actual values."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $999
    Equity:Opening
"""
        with pytest.raises(BalanceAssertionError, match="assertion failed"):
            _parse(text)

    def test_error_includes_account(self):
        """Error message should mention the account name."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $999
    Equity:Opening
"""
        with pytest.raises(BalanceAssertionError, match="Checking"):
            _parse(text)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for balance assertions."""

    def test_assertion_with_decimal(self):
        """Assertion with decimal amounts."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $100.50 = $100.50
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_decimal_fails(self):
        """Decimal assertion with wrong value."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $100.50 = $100.51
    Equity:Opening
"""
        _parse_expect_error(text)

    def test_assertion_large_amount(self):
        """Assertion with large amounts."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $1000000 = $1000000
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_does_not_affect_balancing(self):
        """Balance assertion should not affect transaction balancing."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500
    Equity:Opening  $-500
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_with_auto_balanced_posting(self):
        """Assertion on a posting where the other side is auto-balanced."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500
    Equity:Opening
"""
        journal = _parse(text)
        # Equity:Opening should have been auto-balanced to -$500
        equity_post = journal.xacts[0].posts[1]
        assert equity_post.amount is not None
        assert equity_post.amount.quantity == -500

    def test_virtual_posting_with_assertion(self):
        """Balance assertion on a virtual posting."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening  $-500
    (Budget:Checking)  $500 = $500
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_assertion_only_on_some_postings(self):
        """Only some postings have assertions; others do not."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Transfer
    Assets:Checking  $-100 = $400
    Assets:Savings   $100
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_multiple_xacts_same_account_tracking(self):
        """Running balance is correctly tracked across many transactions."""
        text = """\
2024/01/01 Open
    Assets:Checking  $1000
    Equity:Opening

2024/01/02 Pay rent
    Expenses:Rent  $800
    Assets:Checking  $-800 = $200

2024/01/03 Salary
    Assets:Checking  $3000 = $3200
    Income:Salary

2024/01/04 Groceries
    Expenses:Food  $150
    Assets:Checking  $-150 = $3050
"""
        journal = _parse(text)
        assert len(journal.xacts) == 4

    def test_running_balance_tracking_fails_later(self):
        """A later assertion fails while earlier ones pass."""
        text = """\
2024/01/01 Open
    Assets:Checking  $1000
    Equity:Opening

2024/01/02 Pay rent
    Expenses:Rent  $800
    Assets:Checking  $-800 = $200

2024/01/03 Salary
    Assets:Checking  $3000 = $3200
    Income:Salary

2024/01/04 Groceries
    Expenses:Food  $150
    Assets:Checking  $-150 = $9999
"""
        _parse_expect_error(text)

    def test_assertion_with_zero_amount_posting(self):
        """Assertion on a $0 posting."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500
    Equity:Opening

2024/01/02 Noop
    Assets:Checking  $0 = $500
    Expenses:Nothing  $0
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2

    def test_assertion_equals_sign_not_confused_with_auto_xact(self):
        """The = in a posting should not be confused with automated transaction."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500
    Equity:Opening
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert len(journal.auto_xacts) == 0

    def test_parse_assertion_amount_preserved(self):
        """The assigned_amount should preserve commodity info."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500 = $500
    Equity:Opening
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.assigned_amount is not None
        # Should be $500 with $ commodity
        assert str(post.assigned_amount) in ("$500", "$500.00", "$500.0")
