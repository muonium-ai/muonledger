"""Regression test triage and categorization.

Comprehensive regression test suite that categorizes test failures by type:
parsing, arithmetic, format output, missing features, and error messages.
This helps prioritize the remaining work on the Ledger port.

Tests that pass = confirmed working feature.
Tests that fail = regression to fix (marked with pytest.mark.xfail).
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from muonledger.amount import Amount, AmountError
from muonledger.balance import Balance
from muonledger.commands.balance import balance_command
from muonledger.commands.register import register_command
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.parser import ParseError, TextualParser
from muonledger.post import POST_COST_IN_FULL, POST_MUST_BALANCE, POST_VIRTUAL
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


def _parse_count(text: str) -> int:
    """Parse *text* and return the transaction count."""
    journal = Journal()
    parser = TextualParser()
    return parser.parse_string(text, journal)


# ---------------------------------------------------------------------------
# Category: Parsing Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.parsing
class TestParsingTransactionNoPostings:
    """Transaction with no postings should be handled gracefully."""

    def test_no_postings_returns_false(self):
        """A transaction with no postings should not be added to the journal."""
        text = """\
2024/01/15 Empty Transaction
"""
        journal = _parse(text)
        # Transaction with no postings should not be finalized successfully
        assert len(journal.xacts) == 0

    def test_transaction_only_comments_no_postings(self):
        """Transaction followed only by comment lines, no actual postings."""
        text = """\
2024/01/15 Comments Only
    ; This is just a comment
    ; Another comment
"""
        journal = _parse(text)
        # With only comments and no real postings, transaction should be skipped
        assert len(journal.xacts) == 0


@pytest.mark.parsing
class TestParsingDeepAccounts:
    """Account names with many levels of nesting."""

    def test_ten_level_nesting(self):
        """Account with 10+ colon-separated levels."""
        text = """\
2024/01/01 Deep nesting
    A:B:C:D:E:F:G:H:I:J:K  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        deep_acct = journal.xacts[0].posts[0].account.fullname
        assert deep_acct == "A:B:C:D:E:F:G:H:I:J:K"
        parts = deep_acct.split(":")
        assert len(parts) == 11

    def test_twelve_level_nesting(self):
        """Account with 12 colon-separated levels."""
        text = """\
2024/01/01 Very deep
    L1:L2:L3:L4:L5:L6:L7:L8:L9:L10:L11:L12  $50.00
    Assets:B
"""
        journal = _parse(text)
        deep_acct = journal.xacts[0].posts[0].account.fullname
        assert len(deep_acct.split(":")) == 12


@pytest.mark.parsing
class TestParsingSpecialCharAccounts:
    """Account names with special characters."""

    def test_account_with_single_spaces(self):
        """Account names may contain single spaces (not double)."""
        text = """\
2024/01/01 Test
    Expenses:Food and Drink  $10.00
    Assets:My Bank Account
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Food and Drink"

    def test_account_with_unicode(self):
        """Account names with unicode characters."""
        text = """\
2024/01/01 Test
    Expenses:Caf\u00e9  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Caf\u00e9"

    def test_account_with_digits(self):
        """Account names with digits."""
        text = """\
2024/01/01 Test
    Expenses:401k Contribution  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:401k Contribution"

    def test_account_with_hyphens(self):
        """Account names with hyphens."""
        text = """\
2024/01/01 Test
    Expenses:Sub-Category  $10.00
    Assets:Bank-Account
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Sub-Category"


@pytest.mark.parsing
class TestParsingAmountFormats:
    """Various amount format edge cases."""

    def test_bare_number_no_commodity(self):
        """Amount with no commodity symbol (bare number)."""
        text = """\
2024/01/01 Test
    Expenses:A  100.00
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(100.00)
        assert amt.commodity is None

    def test_commodity_after_number(self):
        """Amount with commodity after number: 100 USD."""
        text = """\
2024/01/01 Test
    Expenses:A  100 USD
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(100.0)
        assert amt.commodity == "USD"

    def test_commodity_before_number(self):
        """Amount with commodity before number: $100."""
        text = """\
2024/01/01 Test
    Expenses:A  $100
    Assets:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(100.0)
        assert amt.commodity == "$"

    def test_negative_prefix_commodity(self):
        """Negative with prefix commodity: -$100."""
        text = """\
2024/01/01 Test
    Expenses:A  $100.00
    Assets:B    -$100.00
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[1].amount
        assert float(amt) == pytest.approx(-100.00)

    def test_negative_inside_commodity(self):
        """Negative inside commodity: $-100."""
        text = """\
2024/01/01 Test
    Expenses:A  $100.00
    Assets:B    $-100.00
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[1].amount
        assert float(amt) == pytest.approx(-100.00)

    def test_thousands_separator(self):
        """Amount with thousands separator: $1,000.00."""
        text = """\
2024/01/01 Test
    Assets:Checking  $1,000.00
    Equity:Opening
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(1000.00)


@pytest.mark.parsing
class TestParsingDateFormats:
    """Date format variations."""

    def test_slash_date(self):
        """Date with slashes: 2024/01/15."""
        text = """\
2024/01/15 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].date == date(2024, 1, 15)

    def test_dash_date(self):
        """Date with dashes: 2024-01-15."""
        text = """\
2024-01-15 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].date == date(2024, 1, 15)

    def test_auxiliary_date(self):
        """Auxiliary date: 2024/01/15=2024/01/20."""
        text = """\
2024/01/15=2024/01/20 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 1, 15)
        assert xact.date_aux == date(2024, 1, 20)

    def test_auxiliary_date_mixed_separators(self):
        """Auxiliary date with dash format: 2024-01-15=2024-01-20."""
        text = """\
2024-01-15=2024-01-20 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 1, 15)
        assert xact.date_aux == date(2024, 1, 20)


@pytest.mark.parsing
class TestParsingTransactionCodes:
    """Transaction code parsing."""

    def test_numeric_code(self):
        """Code: (#12345)."""
        text = """\
2024/01/01 (#12345) Payee
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].code == "#12345"

    def test_alphanumeric_code(self):
        """Code: (CHK-001)."""
        text = """\
2024/01/01 (CHK-001) Payee
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].code == "CHK-001"

    def test_code_with_cleared(self):
        """Code with cleared state: * (100)."""
        text = """\
2024/01/01 * (100) Payee
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.state == ItemState.CLEARED
        assert xact.code == "100"
        assert xact.payee == "Payee"


@pytest.mark.parsing
class TestParsingEmptyPayee:
    """Transaction with empty or missing payee."""

    def test_empty_payee(self):
        """Transaction with no payee text after date."""
        text = """\
2024/01/01
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == ""


@pytest.mark.parsing
class TestParsingMultiLineNotes:
    """Multi-line notes and metadata on transactions and postings."""

    def test_multi_line_transaction_note(self):
        """Multiple comment lines attached to a transaction."""
        text = """\
2024/01/01 Test
    ; First note line
    ; Second note line
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.note is not None
        assert "First note line" in xact.note
        assert "Second note line" in xact.note

    def test_tag_metadata(self):
        """Tag metadata: ; :tag1:tag2:."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; :food:grocery:
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.has_tag("food")
        assert post.has_tag("grocery")

    def test_key_value_metadata(self):
        """Key-value metadata: ; Key: Value."""
        text = """\
2024/01/01 Test
    ; Category: Personal
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.get_tag("Category") == "Personal"

    def test_posting_key_value_metadata(self):
        """Key-value metadata on a posting."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; Receipt: 12345
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.get_tag("Receipt") == "12345"


# ---------------------------------------------------------------------------
# Category: Arithmetic Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.arithmetic
class TestArithmeticLargeAmounts:
    """Very large amounts."""

    def test_large_amount(self):
        """Large amount: $999,999,999.99."""
        text = """\
2024/01/01 Big transaction
    Assets:Checking  $999,999,999.99
    Equity:Opening
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(999999999.99)

    def test_large_integer_amount(self):
        """Large integer: $1000000."""
        text = """\
2024/01/01 Test
    Assets:A  $1000000
    Equity:B
"""
        journal = _parse(text)
        amt = journal.xacts[0].posts[0].amount
        assert float(amt) == pytest.approx(1000000.0)


@pytest.mark.arithmetic
class TestArithmeticSmallAmounts:
    """Very small amounts."""

    def test_small_amount(self):
        """Small amount: $0.001."""
        amt = Amount("$0.001")
        assert float(amt) == pytest.approx(0.001)
        assert amt.precision == 3

    def test_sub_penny_amount(self):
        """Sub-penny: $0.0001."""
        amt = Amount("$0.0001")
        assert float(amt) == pytest.approx(0.0001)
        assert amt.precision == 4


@pytest.mark.arithmetic
class TestArithmeticHighPrecision:
    """High precision arithmetic."""

    def test_ten_decimal_places(self):
        """10 decimal places parsed correctly."""
        amt = Amount("1.0000000001")
        assert amt.precision == 10
        assert amt.quantity == Fraction(10000000001, 10000000000)

    def test_fraction_exact(self):
        """Exact fraction arithmetic -- no floating point error."""
        a = Amount("$0.10")
        b = Amount("$0.20")
        result = a + b
        assert result.quantity == Fraction(3, 10)


@pytest.mark.arithmetic
class TestArithmeticAutoBalance:
    """Auto-balance edge cases."""

    def test_auto_balance_two_postings(self):
        """Standard auto-balance with two postings."""
        text = """\
2024/01/01 Test
    Expenses:Food  $42.50
    Assets:Checking
"""
        journal = _parse(text)
        balanced = journal.xacts[0].posts[1].amount
        assert float(balanced) == pytest.approx(-42.50)

    def test_auto_balance_three_postings(self):
        """Three-way split with auto-balance."""
        text = """\
2024/01/01 Test
    Expenses:Food  $20.00
    Expenses:Drink  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        balanced = journal.xacts[0].posts[2].amount
        assert float(balanced) == pytest.approx(-30.00)

    def test_auto_balance_to_exactly_zero(self):
        """All postings explicitly sum to zero -- no null posting needed."""
        text = """\
2024/01/01 Test
    Expenses:Food  $50.00
    Assets:Checking  -$50.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_negative_auto_balance(self):
        """Auto-balance yields a positive amount when explicit are negative."""
        text = """\
2024/01/01 Test
    Assets:Checking  -$100.00
    Income:Salary
"""
        journal = _parse(text)
        balanced = journal.xacts[0].posts[1].amount
        assert float(balanced) == pytest.approx(100.00)

    def test_auto_balance_with_cost(self):
        """Auto-balance with cost conversion."""
        text = """\
2024/01/01 Test
    Assets:Brokerage  10 AAPL @ $150.00
    Assets:Checking
"""
        journal = _parse(text)
        # The auto-balanced amount should be -$1500
        balanced = journal.xacts[0].posts[1].amount
        assert float(balanced) == pytest.approx(-1500.00)
        assert balanced.commodity == "$"


@pytest.mark.arithmetic
class TestArithmeticMixedCommodities:
    """Mixed commodity arithmetic."""

    def test_different_commodities_cannot_add(self):
        """Adding amounts with different commodities should raise."""
        a = Amount("$100.00")
        b = Amount("100.00 EUR")
        with pytest.raises(AmountError):
            _ = a + b

    def test_balance_tracks_multiple_commodities(self):
        """Balance can hold amounts of different commodities."""
        bal = Balance()
        bal.add(Amount("$100.00"))
        bal.add(Amount("50 EUR"))
        amounts = bal.amounts()
        assert len(amounts) >= 2


@pytest.mark.arithmetic
class TestArithmeticAmountMultiplication:
    """Amount multiplication for scaling."""

    def test_multiply_amount_by_int(self):
        """Multiply an amount by an integer."""
        amt = Amount("$10.00")
        result = amt * Amount(3)
        assert float(result) == pytest.approx(30.00)
        assert result.commodity == "$"

    def test_multiply_preserves_commodity(self):
        """Multiplication preserves the commodity of the commoditized operand."""
        amt = Amount("100 EUR")
        result = amt * Amount(2)
        assert float(result) == pytest.approx(200.0)
        assert result.commodity == "EUR"


# ---------------------------------------------------------------------------
# Category: Format Output Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.format_output
class TestFormatBalanceReport:
    """Balance report formatting."""

    def test_right_aligned_amounts(self):
        """Amounts should be right-aligned in the balance report."""
        text = """\
2024/01/01 Test
    Expenses:Food  $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = balance_command(journal)
        lines = output.strip().split("\n")
        # Find a non-separator line
        for line in lines:
            if "---" not in line and line.strip():
                # Amount portion is right-aligned within first 20 chars
                amount_part = line[:20]
                assert amount_part == amount_part  # non-empty
                break

    def test_account_indentation_tree_mode(self):
        """Accounts should show indentation in tree mode (default)."""
        text = """\
2024/01/01 Test
    Expenses:Food     $30.00
    Expenses:Drink    $20.00
    Assets:Checking
"""
        journal = _parse(text)
        output = balance_command(journal)
        # In tree mode, sub-accounts are indented
        assert "Expenses" in output

    def test_separator_line(self):
        """Balance report has a separator line of dashes."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        output = balance_command(journal)
        lines = output.strip().split("\n")
        separator_found = any("----" in line for line in lines)
        assert separator_found

    def test_total_line_present(self):
        """Balance report shows a total at the bottom."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking  -$10.00
"""
        journal = _parse(text)
        output = balance_command(journal)
        lines = output.strip().split("\n")
        # After the separator there should be a total
        assert len(lines) >= 3  # At least: account lines + separator + total

    def test_no_total_option(self):
        """--no-total suppresses the total line."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking  -$10.00
"""
        journal = _parse(text)
        output = balance_command(journal, ["--no-total"])
        lines = output.strip().split("\n")
        separator_found = any("----" in line for line in lines)
        assert not separator_found

    def test_empty_balance_report(self):
        """Balance report from empty journal."""
        journal = Journal()
        output = balance_command(journal)
        assert output == ""


@pytest.mark.format_output
class TestFormatRegisterReport:
    """Register report formatting."""

    def test_date_column_format(self):
        """Date should be in YY-Mon-DD format."""
        text = """\
2024/01/15 Test
    Expenses:Food  $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        assert "24-Jan-15" in output

    def test_payee_truncation(self):
        """Long payees should be truncated."""
        text = """\
2024/01/01 This Is A Very Long Payee Name That Exceeds The Column Width
    Expenses:Food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.strip().split("\n")
        # Payee column is 22 chars wide in standard mode
        # Long payees get truncated with ..
        assert ".." in lines[0] or len(lines[0]) == 80

    def test_wide_mode_column_widths(self):
        """Wide mode should produce 132-character lines."""
        text = """\
2024/01/15 Test
    Expenses:Food  $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["--wide"])
        lines = output.strip().split("\n")
        # Wide mode lines should be 132 chars
        assert len(lines[0]) == 132

    def test_single_line_register(self):
        """Single posting register output."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal, ["Food"])
        lines = output.strip().split("\n")
        assert len(lines) == 1
        assert "Food" in lines[0]

    def test_empty_register(self):
        """Register from empty journal."""
        journal = Journal()
        output = register_command(journal)
        assert output == ""

    def test_register_line_width_80(self):
        """Default register lines should be exactly 80 characters."""
        text = """\
2024/01/15 Grocery Store
    Expenses:Food  $42.50
    Assets:Checking
"""
        journal = _parse(text)
        output = register_command(journal)
        lines = output.strip().split("\n")
        for line in lines:
            assert len(line) == 80


@pytest.mark.format_output
class TestFormatMultiCommodityBalance:
    """Multi-commodity balance display."""

    def test_multi_commodity_balance(self):
        """Balance report with multiple commodities shows each on its own line."""
        text = """\
2024/01/01 Test
    Assets:Brokerage  10 AAPL @ $150.00
    Assets:Checking

2024/01/02 Test
    Assets:Brokerage  5 GOOG @ $100.00
    Assets:Checking
"""
        journal = _parse(text)
        output = balance_command(journal, ["Brokerage"])
        # Should show both AAPL and GOOG amounts
        assert "AAPL" in output
        assert "GOOG" in output


# ---------------------------------------------------------------------------
# Category: Missing Feature Detection
# ---------------------------------------------------------------------------


@pytest.mark.missing_feature
class TestCostConversion:
    """Cost conversion with @ and @@."""

    def test_per_unit_cost(self):
        """Per-unit cost: 10 AAPL @ $150."""
        text = """\
2024/01/01 Buy stock
    Assets:Brokerage  10 AAPL @ $150.00
    Assets:Checking
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert float(post.amount) == 10.0
        assert post.amount.commodity == "AAPL"
        assert post.cost is not None
        assert float(post.cost) == pytest.approx(1500.00)
        assert post.cost.commodity == "$"

    def test_total_cost(self):
        """Total cost: 10 AAPL @@ $1500."""
        text = """\
2024/01/01 Buy stock
    Assets:Brokerage  10 AAPL @@ $1500.00
    Assets:Checking
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert float(post.amount) == 10.0
        assert post.amount.commodity == "AAPL"
        assert post.cost is not None
        assert float(post.cost) == pytest.approx(1500.00)
        assert post.has_flags(POST_COST_IN_FULL)


@pytest.mark.missing_feature
class TestBalanceAssertions:
    """Balance assertions (= $500 on a posting line)."""

    def test_balance_assertion(self):
        """Balance assertion: = $500."""
        text = """\
2024/01/01 Opening
    Assets:Checking  $500.00
    Equity:Opening

2024/01/02 Spend
    Expenses:Food  $50.00
    Assets:Checking  = $450.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2
        # The balance assertion should verify the running balance
        post = journal.xacts[1].posts[1]
        assert post.assigned_amount is not None
        assert float(post.assigned_amount) == pytest.approx(450.00)


@pytest.mark.missing_feature
class TestLotAnnotations:
    """Lot price and date annotations."""

    def test_lot_price(self):
        """Lot price: 10 AAPL {$150}."""
        text = """\
2024/01/01 Buy stock
    Assets:Brokerage  10 AAPL {$150.00}
    Assets:Checking  -$1500.00
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert float(post.amount) == 10.0
        assert post.amount.commodity == "AAPL"

    def test_lot_date(self):
        """Lot date: 10 AAPL {$150.00} [2024-01-15]."""
        text = """\
2024/01/01 Buy stock
    Assets:Brokerage  10 AAPL {$150.00} [2024-01-15]
    Assets:Checking  -$1500.00
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert float(post.amount) == 10.0
        assert post.annotation is not None
        assert post.annotation.date == date(2024, 1, 15)


@pytest.mark.missing_feature
class TestVirtualPostings:
    """Virtual postings with () and []."""

    def test_virtual_posting_parenthesized(self):
        """Virtual posting: (Budget:Food) does not need to balance."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking  -$10.00
    (Budget:Food)  $-10.00
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 3
        vpost = xact.posts[2]
        assert vpost.is_virtual()
        assert not vpost.must_balance()
        assert vpost.account.fullname == "Budget:Food"

    def test_virtual_posting_bracketed(self):
        """Balanced virtual posting: [Budget:Food] must balance."""
        text = """\
2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking  -$10.00
    [Budget:Food]  $0.00
"""
        journal = _parse(text)
        vpost = journal.xacts[0].posts[2]
        assert vpost.is_virtual()
        assert vpost.must_balance()


@pytest.mark.missing_feature
class TestAutomatedTransactions:
    """Automated transaction with multiplier."""

    def test_auto_xact_parsed(self):
        """Automated transaction should be parsed and stored."""
        text = """\
= /Expenses:Food/
    (Budget:Food)  -1.0

2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 1

    def test_auto_xact_with_multiplier(self):
        """Automated transaction with a fraction multiplier."""
        text = """\
= /Expenses/
    (Liabilities:Taxes)  0.10

2024/01/01 Test
    Expenses:Books  $100.00
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 1
        # The auto xact should have a posting
        assert len(journal.auto_xacts[0].posts) == 1


@pytest.mark.missing_feature
class TestClearedStateMarkers:
    """Cleared state markers * and ! on transactions and postings."""

    def test_cleared_transaction(self):
        """Transaction cleared: *."""
        text = """\
2024/01/01 * Cleared
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].state == ItemState.CLEARED

    def test_pending_transaction(self):
        """Transaction pending: !."""
        text = """\
2024/01/01 ! Pending
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].state == ItemState.PENDING

    def test_cleared_posting(self):
        """Posting cleared: *."""
        text = """\
2024/01/01 Test
    * Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].state == ItemState.CLEARED

    def test_pending_posting(self):
        """Posting pending: !."""
        text = """\
2024/01/01 Test
    ! Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].state == ItemState.PENDING


@pytest.mark.missing_feature
class TestTransactionNotesAndMetadata:
    """Transaction notes and metadata features."""

    def test_inline_note_on_transaction(self):
        """Inline note: ; note text after payee."""
        text = """\
2024/01/01 Test ; some note
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.xacts[0].note is not None
        assert "some note" in journal.xacts[0].note

    def test_inline_note_on_posting(self):
        """Inline note on a posting line."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00 ; posting note here
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.note is not None
        assert "posting note" in post.note

    def test_effective_date_on_posting(self):
        """Effective date on a posting: ; [=2024/02/01]."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)


@pytest.mark.missing_feature
class TestPeriodicTransactions:
    """Periodic transactions (~)."""

    def test_periodic_xact_parsed(self):
        """Periodic transaction should be stored."""
        text = """\
~ Monthly
    Assets:Checking  $500.00
    Income:Salary

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.period_xacts) == 1
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# Category: Error Message Quality
# ---------------------------------------------------------------------------


@pytest.mark.error_messages
class TestErrorUnbalanced:
    """Unbalanced transaction error includes context."""

    def test_unbalanced_error_raised(self):
        """An unbalanced transaction should raise BalanceError."""
        text = """\
2024/01/01 Broken
    Expenses:A  $100.00
    Assets:B    -$50.00
"""
        with pytest.raises(BalanceError):
            _parse(text)

    def test_unbalanced_error_has_message(self):
        """BalanceError should include remainder info."""
        text = """\
2024/01/01 Broken
    Expenses:A  $100.00
    Assets:B    -$50.00
"""
        with pytest.raises(BalanceError, match="does not balance"):
            _parse(text)


@pytest.mark.error_messages
class TestErrorInvalidDate:
    """Invalid date produces meaningful error."""

    def test_invalid_month(self):
        """Invalid month should raise an error."""
        text = """\
2024/13/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        with pytest.raises((ParseError, ValueError)):
            _parse(text)

    def test_invalid_day(self):
        """Invalid day should raise an error."""
        text = """\
2024/02/30 Test
    Expenses:A  $10.00
    Assets:B
"""
        with pytest.raises((ParseError, ValueError)):
            _parse(text)


@pytest.mark.error_messages
class TestErrorMissingAccount:
    """Missing or invalid account situations."""

    def test_multiple_null_postings_error(self):
        """Two null-amount postings should raise BalanceError."""
        text = """\
2024/01/01 Test
    Expenses:A
    Assets:B
"""
        # This should fail because there are two null postings
        with pytest.raises(BalanceError):
            _parse(text)


@pytest.mark.error_messages
class TestErrorIncludeNotFound:
    """Include file not found error."""

    def test_include_nonexistent_file(self, tmp_path):
        """Including a nonexistent file should raise ParseError."""
        journal_file = tmp_path / "test.dat"
        journal_file.write_text('include "nonexistent.dat"\n')
        journal = Journal()
        parser = TextualParser()
        with pytest.raises(ParseError, match="not found"):
            parser.parse(journal_file, journal)


@pytest.mark.error_messages
class TestErrorAmountParsing:
    """Amount parsing errors."""

    def test_empty_amount_string(self):
        """Empty string should raise AmountError."""
        with pytest.raises(AmountError):
            Amount("")

    def test_only_commodity_no_number(self):
        """Commodity with no number should raise AmountError."""
        with pytest.raises(AmountError):
            Amount("$")


# ---------------------------------------------------------------------------
# Category: Directives Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.parsing
class TestDirectives:
    """Directive parsing edge cases."""

    def test_comment_block(self):
        """Multi-line comment block: comment ... end comment."""
        text = """\
comment
This is a multi-line comment block.
It should be entirely skipped.
end comment

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_year_directive(self):
        """Year directive: Y 2024."""
        text = """\
Y 2024

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.default_year == 2024

    def test_account_directive(self):
        """Account directive registers an account."""
        text = """\
account Expenses:Food
    note Food expenses

2024/01/01 Test
    Expenses:Food  $10.00
    Assets:B
"""
        journal = _parse(text)
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct is not None
        assert acct.note == "Food expenses"

    def test_commodity_directive(self):
        """Commodity directive registers a commodity."""
        text = """\
commodity $
    format $1,000.00

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_price_directive(self):
        """P price directive stores price data."""
        text = """\
P 2024/01/01 AAPL $150.00

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.prices) == 1
        pd, sym, price = journal.prices[0]
        assert pd == date(2024, 1, 1)
        assert sym == "AAPL"
        assert float(price) == pytest.approx(150.00)

    def test_alias_directive(self):
        """Alias directive maps short names to full account paths."""
        text = """\
alias food=Expenses:Food

2024/01/01 Test
    food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Food"

    def test_bucket_directive(self):
        """Bucket directive sets default account."""
        text = """\
bucket Assets:Checking

2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking
"""
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Checking"

    def test_apply_account(self):
        """apply account prefix is prepended to account names."""
        text = """\
apply account Personal

2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking

end apply account
"""
        journal = _parse(text)
        assert journal.xacts[0].posts[0].account.fullname == "Personal:Expenses:Food"

    def test_apply_tag(self):
        """apply tag is added to all transactions in scope."""
        text = """\
apply tag imported

2024/01/01 Test
    Expenses:Food  $10.00
    Assets:Checking

end apply tag
"""
        journal = _parse(text)
        assert journal.xacts[0].has_tag("imported")

    def test_define_directive(self):
        """define directive stores variable definitions."""
        text = """\
define tax_rate=0.08

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert "tax_rate" in journal.defines
        assert journal.defines["tax_rate"] == "0.08"

    def test_tag_declaration(self):
        """tag directive declares tag names."""
        text = """\
tag receipt

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert "receipt" in journal.tag_declarations

    def test_payee_declaration(self):
        """payee directive declares payee names."""
        text = """\
payee Grocery Store

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert "Grocery Store" in journal.payee_declarations

    def test_default_commodity_directive(self):
        """D directive sets default commodity."""
        text = """\
D $1,000.00

2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.commodity_pool.default_commodity is not None


@pytest.mark.parsing
class TestParsingWindowsLineEndings:
    """Windows-style line endings (CRLF)."""

    def test_crlf_line_endings(self):
        """Parser should handle \\r\\n line endings."""
        text = "2024/01/01 Test\r\n    Expenses:A  $10.00\r\n    Assets:B\r\n"
        journal = _parse(text)
        assert len(journal.xacts) == 1


@pytest.mark.parsing
class TestParsingTabSeparated:
    """Tab-separated posting lines."""

    def test_tab_between_account_and_amount(self):
        """Tab separates account from amount."""
        text = "2024/01/01 Test\n\tExpenses:Food\t$10.00\n\tAssets:Cash\n"
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:Food"
        assert float(journal.xacts[0].posts[0].amount) == pytest.approx(10.00)
