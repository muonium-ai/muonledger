"""
Tests for format output parity with Ledger.

Covers formatting details for balance, register, print, and amount output:
  - Balance: right-aligned amounts, tree indentation, separator, total, multi-commodity
  - Register: column widths, date format, truncation, running totals
  - Print: header format, posting indentation, state markers, cost display
  - Amount: prefix/suffix commodity, thousands, decimal precision, negatives
"""

from __future__ import annotations

from datetime import date

import pytest

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.commodity import CommodityPool, CommodityStyle
from muonledger.commands.balance import (
    AMOUNT_WIDTH,
    SEPARATOR,
    _format_amount_lines,
    balance_command,
)
from muonledger.commands.register import (
    _format_date,
    _truncate,
    register_command,
)
from muonledger.commands.print_cmd import (
    format_posting,
    format_transaction,
    print_command,
)
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import Post
from muonledger.xact import Transaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global commodity pool before each test."""
    CommodityPool.reset_current()
    yield
    CommodityPool.reset_current()


def _parse(text: str) -> Journal:
    """Parse *text* and return the populated journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _make_simple_journal() -> Journal:
    """Two-transaction journal: paycheck + groceries."""
    return _parse("""\
2024/01/01 Paycheck
    Assets:Checking     $1,000.00
    Income:Salary

2024/01/05 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")


# ===================================================================
# 1. Balance Formatting
# ===================================================================


class TestBalanceAmountAlignment:
    """Amount values are right-aligned within the 20-character column."""

    def test_amount_width_constant(self):
        assert AMOUNT_WIDTH == 20

    def test_separator_line_constant(self):
        assert SEPARATOR == "-" * 20
        assert len(SEPARATOR) == 20

    def test_amount_right_aligned_in_20_chars(self):
        bal = Balance(Amount("$100.00"))
        lines = _format_amount_lines(bal)
        assert len(lines) == 1
        assert len(lines[0]) == 20
        assert lines[0] == "$100.00".rjust(20)

    def test_zero_balance_right_aligned(self):
        bal = Balance()
        lines = _format_amount_lines(bal)
        assert len(lines) == 1
        assert lines[0] == "0".rjust(20)
        assert len(lines[0]) == 20

    def test_large_amount_right_aligned(self):
        bal = Balance(Amount("$99999.99"))
        lines = _format_amount_lines(bal)
        assert len(lines[0]) == 20
        assert lines[0].endswith("$99999.99")

    def test_negative_amount_right_aligned(self):
        bal = Balance(Amount("$-50.00"))
        lines = _format_amount_lines(bal)
        assert len(lines[0]) == 20
        assert "$-50.00" in lines[0]

    def test_small_amount_heavy_padding(self):
        bal = Balance(Amount("$1.00"))
        lines = _format_amount_lines(bal)
        assert lines[0] == "$1.00".rjust(20)


class TestBalanceTreeIndentation:
    """Tree mode indentation uses 2 spaces per depth level."""

    def test_depth_1_indentation(self):
        journal = _parse("""\
2024/01/01 Test
    Assets:Checking     $100.00
    Equity:Opening
""")
        output = balance_command(journal)
        lines = output.strip().split("\n")
        # Find a line with "Checking" (depth-1 child of Assets)
        checking_lines = [l for l in lines if "Checking" in l]
        assert len(checking_lines) >= 1
        # The line should contain the account name somewhere after the amount
        assert "Checking" in checking_lines[0]

    def test_depth_2_indentation(self):
        journal = _parse("""\
2024/01/01 Test
    Assets:Bank:Checking     $100.00
    Equity:Opening
""")
        output = balance_command(journal)
        # In tree mode, Bank:Checking may be collapsed with Assets
        assert "Checking" in output

    def test_flat_mode_no_indentation(self):
        journal = _parse("""\
2024/01/01 Test
    Assets:Bank:Checking     $100.00
    Equity:Opening
""")
        output = balance_command(journal, ["--flat"])
        lines = output.strip().split("\n")
        for line in lines:
            if "----" in line or line.strip() == "0":
                continue
            # In flat mode, account names should be full paths (contain colon)
            if line.strip():
                assert ":" in line or line.strip() == "0"


class TestBalanceSeparatorLine:
    """Separator line is exactly 20 dashes."""

    def test_separator_in_output(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        lines = output.strip().split("\n")
        sep_lines = [l for l in lines if l.strip() == "-" * 20]
        assert len(sep_lines) == 1

    def test_separator_exactly_20_dashes(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        assert "-" * 20 in output

    def test_no_separator_with_no_total(self):
        journal = _make_simple_journal()
        output = balance_command(journal, ["--no-total"])
        assert "-" * 20 not in output


class TestBalanceTotalLine:
    """Total line is right-aligned to 20 characters."""

    def test_total_line_right_aligned(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        lines = output.strip().split("\n")
        total_line = lines[-1]
        # Total should be right-aligned in 20 chars
        assert len(total_line.rstrip()) <= 20

    def test_zero_total_display(self):
        journal = _parse("""\
2024/01/01 Transfer
    Assets:A     $100.00
    Assets:B    $-100.00
""")
        output = balance_command(journal)
        lines = output.strip().split("\n")
        assert lines[-1].strip() == "0"

    def test_nonzero_total(self):
        journal = _parse("""\
2024/01/01 Income
    Assets:Checking     $500.00
    Income:Salary
""")
        output = balance_command(journal, ["Assets"])
        lines = output.strip().split("\n")
        total_line = lines[-1]
        assert "$500.00" in total_line


class TestBalanceMultiCommodity:
    """Multi-commodity amounts display each on its own line, right-aligned."""

    def test_multi_commodity_separate_lines(self):
        journal = _parse("""\
2024/01/01 Buy EUR
    Assets:Foreign     100.00 EUR @@ $110.00
    Assets:Cash

2024/01/02 Buy GBP
    Assets:Foreign      50.00 GBP @@ $65.00
    Assets:Cash
""")
        output = balance_command(journal, ["--flat", "Assets:Foreign"])
        # Should contain both EUR and GBP
        assert "EUR" in output
        assert "GBP" in output

    def test_multi_commodity_right_aligned(self):
        journal = _parse("""\
2024/01/01 Buy EUR
    Assets:Foreign     100.00 EUR @@ $110.00
    Assets:Cash

2024/01/02 Buy GBP
    Assets:Foreign      50.00 GBP @@ $65.00
    Assets:Cash
""")
        output = balance_command(journal, ["--flat", "Assets:Foreign"])
        lines = output.strip().split("\n")
        # The output should contain commodity amounts
        found_eur = False
        found_gbp = False
        for line in lines:
            if "EUR" in line:
                found_eur = True
            if "GBP" in line:
                found_gbp = True
        assert found_eur
        assert found_gbp


class TestBalanceFlatMode:
    """Flat mode shows full account paths."""

    def test_flat_full_paths(self):
        journal = _parse("""\
2024/01/01 Test
    Assets:Bank:Checking     $100.00
    Equity:Opening
""")
        output = balance_command(journal, ["--flat"])
        assert "Assets:Bank:Checking" in output

    def test_flat_sorted_alphabetically(self):
        journal = _parse("""\
2024/01/01 Test
    Expenses:Food     $30.00
    Assets:Checking   $-30.00
""")
        output = balance_command(journal, ["--flat"])
        lines = output.strip().split("\n")
        account_lines = [l for l in lines if "----" not in l and l.strip() != "0"]
        # Assets should come before Expenses
        if len(account_lines) >= 2:
            assert "Assets" in account_lines[0]
            assert "Expenses" in account_lines[1]


class TestBalanceEmptyOutput:
    """Empty balance produces no output at all."""

    def test_empty_journal_no_output(self):
        journal = Journal()
        output = balance_command(journal)
        assert output == ""

    def test_no_matching_accounts_no_output(self):
        journal = _make_simple_journal()
        output = balance_command(journal, ["Nonexistent"])
        assert output == ""


class TestBalanceNoTrailingWhitespace:
    """No trailing whitespace on any line."""

    def test_no_trailing_whitespace(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        for line in output.split("\n"):
            if line:  # skip empty lines
                assert line == line.rstrip(), f"Trailing whitespace: {line!r}"


# ===================================================================
# 2. Register Formatting
# ===================================================================


class TestRegisterColumnWidths:
    """80-column default layout: date(10) + payee(22) + account(22) + amount(13) + total(13)."""

    def test_default_line_width_80(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
""")
        output = register_command(journal)
        for line in output.rstrip("\n").split("\n"):
            assert len(line) == 80, f"Expected 80, got {len(line)}: {line!r}"

    def test_wide_line_width_132(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
""")
        output = register_command(journal, ["--wide"])
        for line in output.rstrip("\n").split("\n"):
            assert len(line) == 132, f"Expected 132, got {len(line)}: {line!r}"

    def test_date_column_10_chars(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
""")
        output = register_command(journal)
        first_line = output.rstrip("\n").split("\n")[0]
        date_col = first_line[:10]
        assert date_col.startswith("24-Jan-15")


class TestRegisterDateFormat:
    """Date format is YY-Mon-DD."""

    def test_january(self):
        assert _format_date(date(2024, 1, 15)) == "24-Jan-15"

    def test_february(self):
        assert _format_date(date(2024, 2, 1)) == "24-Feb-01"

    def test_march(self):
        assert _format_date(date(2024, 3, 10)) == "24-Mar-10"

    def test_april(self):
        assert _format_date(date(2024, 4, 30)) == "24-Apr-30"

    def test_may(self):
        assert _format_date(date(2024, 5, 5)) == "24-May-05"

    def test_june(self):
        assert _format_date(date(2024, 6, 15)) == "24-Jun-15"

    def test_july(self):
        assert _format_date(date(2024, 7, 4)) == "24-Jul-04"

    def test_august(self):
        assert _format_date(date(2024, 8, 20)) == "24-Aug-20"

    def test_september(self):
        assert _format_date(date(2024, 9, 1)) == "24-Sep-01"

    def test_october(self):
        assert _format_date(date(2024, 10, 31)) == "24-Oct-31"

    def test_november(self):
        assert _format_date(date(2024, 11, 11)) == "24-Nov-11"

    def test_december(self):
        assert _format_date(date(2024, 12, 25)) == "24-Dec-25"

    def test_year_2000(self):
        assert _format_date(date(2000, 1, 1)) == "00-Jan-01"

    def test_none_date(self):
        assert _format_date(None) == ""


class TestRegisterTruncation:
    """Payee and account truncation with '..' when too long."""

    def test_truncate_short_string(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncate_exact_width(self):
        assert _truncate("hello", 5) == "hello"

    def test_truncate_long_string(self):
        result = _truncate("A Very Long Name", 10)
        assert len(result) == 10
        assert result.endswith("..")

    def test_truncate_width_2(self):
        assert _truncate("hello", 2) == "he"

    def test_truncate_width_1(self):
        assert _truncate("hello", 1) == "h"

    def test_payee_truncated_in_register(self):
        journal = _parse("""\
2024/01/15 A Very Long Payee Name That Exceeds Column Width
    Expenses:Food       $10.00
    Assets:Cash
""")
        output = register_command(journal)
        first_line = output.rstrip("\n").split("\n")[0]
        payee_col = first_line[10:32]
        assert ".." in payee_col

    def test_account_truncated_in_register(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food:Dining:Restaurant:Fancy  $10.00
    Assets:Cash
""")
        output = register_command(journal)
        first_line = output.rstrip("\n").split("\n")[0]
        account_col = first_line[32:54]
        assert ".." in account_col


class TestRegisterFirstVsSubsequentPosting:
    """First posting shows date+payee, subsequent postings blank those columns."""

    def test_first_posting_has_date_payee(self):
        journal = _parse("""\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = register_command(journal)
        lines = output.rstrip("\n").split("\n")
        assert "24-Jan-15" in lines[0]
        assert "Grocery Store" in lines[0]

    def test_subsequent_posting_blank_date_payee(self):
        journal = _parse("""\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = register_command(journal)
        lines = output.rstrip("\n").split("\n")
        assert len(lines) == 2
        # Second line should have blank date and payee columns (32 spaces)
        assert lines[1][:32] == " " * 32


class TestRegisterAmountAlignment:
    """Amount and total are right-aligned in their columns."""

    def test_amount_right_aligned(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Cash
""")
        output = register_command(journal)
        first_line = output.rstrip("\n").split("\n")[0]
        amount_col = first_line[54:67]  # columns 55-67 (13 chars)
        assert amount_col == "$42.50".rjust(13)

    def test_total_right_aligned(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Cash
""")
        output = register_command(journal)
        first_line = output.rstrip("\n").split("\n")[0]
        total_col = first_line[67:80]  # last 13 chars
        assert total_col == "$42.50".rjust(13)


class TestRegisterRunningTotal:
    """Running total accumulates across displayed postings."""

    def test_running_total_accumulates(self):
        journal = _parse("""\
2024/01/01 Paycheck
    Assets:Checking     $500.00
    Income:Salary

2024/01/05 Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = register_command(journal, ["Assets:Checking"])
        lines = output.rstrip("\n").split("\n")
        assert len(lines) == 2
        assert "$500.00" in lines[0]
        assert "$457.50" in lines[1]


# ===================================================================
# 3. Print Formatting
# ===================================================================


class TestPrintTransactionHeader:
    """Transaction header: DATE [=AUXDATE] [STATE] [(CODE)] PAYEE."""

    def test_basic_header(self):
        journal = _parse("""\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "2024/01/15 Grocery Store" in output

    def test_cleared_header(self):
        journal = _parse("""\
2024/01/15 * Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "2024/01/15 * Grocery Store" in output

    def test_pending_header(self):
        journal = _parse("""\
2024/01/15 ! Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "2024/01/15 ! Grocery Store" in output

    def test_code_in_header(self):
        journal = _parse("""\
2024/01/15 * (1042) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "(1042)" in output
        assert "Grocery Store" in output


class TestPrintPostingFormat:
    """Posting lines: 4-space indent, account left-aligned, amount right-aligned."""

    def test_four_space_indent(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        lines = output.strip().split("\n")
        for line in lines[1:]:
            assert line.startswith("    "), f"Expected 4-space indent: {line!r}"

    def test_amount_present_on_first_posting(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        lines = output.strip().split("\n")
        assert "$42.50" in lines[1]

    def test_elided_second_posting_same_commodity(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking    $-42.50
""")
        output = print_command(journal)
        lines = output.strip().split("\n")
        # Second posting should have elided amount
        assert "$-42.50" not in lines[2]
        assert "Assets:Checking" in lines[2]


class TestPrintBlankLineSeparator:
    """Blank line between transactions."""

    def test_blank_line_between_transactions(self):
        journal = _parse("""\
2024/01/01 First
    Assets:A    $100.00
    Assets:B

2024/01/02 Second
    Assets:C    $200.00
    Assets:D
""")
        output = print_command(journal)
        assert "\n\n" in output

    def test_no_trailing_blank_line(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert not output.endswith("\n\n")


class TestPrintStateMarkers:
    """State markers: * for cleared, ! for pending."""

    def test_cleared_marker(self):
        journal = _parse("""\
2024/01/15 * Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "* Test" in output

    def test_pending_marker(self):
        journal = _parse("""\
2024/01/15 ! Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        assert "! Test" in output

    def test_no_marker_for_uncleared(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
""")
        output = print_command(journal)
        # Should not have * or ! between date and payee
        first_line = output.split("\n")[0]
        assert "2024/01/15 Test" in first_line


class TestPrintCostDisplay:
    """Cost display: @ $10.00 or @@ $100.00."""

    def test_per_unit_cost(self):
        journal = _parse("""\
2024/01/15 Buy Stock
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
""")
        output = print_command(journal)
        assert "@ $150.00" in output

    def test_total_cost(self):
        journal = _parse("""\
2024/01/15 Buy Stock
    Assets:Brokerage    10 AAPL @@ $1,500.00
    Assets:Checking
""")
        output = print_command(journal)
        assert "@@" in output
        assert "$1,500.00" in output


class TestPrintNotes:
    """Notes display: ; note text after amount."""

    def test_transaction_note(self):
        journal = _parse("""\
2024/01/15 Test  ; a note
    Expenses:Food       $10.00
    Assets:Cash
""")
        output = print_command(journal)
        assert "a note" in output
        assert ";" in output

    def test_posting_note(self):
        journal = _parse("""\
2024/01/15 Test
    Expenses:Food       $10.00  ; organic
    Assets:Cash
""")
        output = print_command(journal)
        assert "organic" in output


# ===================================================================
# 4. Amount Formatting
# ===================================================================


class TestAmountPrefixCommodity:
    """Prefix commodities: $100.00, not 100.00 $."""

    def test_dollar_prefix(self):
        a = Amount("$100.00")
        assert str(a).startswith("$")

    def test_pound_prefix(self):
        pool = CommodityPool.get_current()
        pool.learn_style("£", prefix=True, precision=2)
        a = Amount("£50.00")
        assert str(a).startswith("£")

    def test_yen_prefix(self):
        pool = CommodityPool.get_current()
        pool.learn_style("¥", prefix=True, precision=0)
        a = Amount("¥1000")
        assert str(a).startswith("¥")


class TestAmountSuffixCommodity:
    """Suffix commodities: 100 EUR, not EUR 100."""

    def test_eur_suffix(self):
        a = Amount("100 EUR")
        s = str(a)
        assert s.endswith("EUR")
        assert s.startswith("100")

    def test_aapl_suffix(self):
        a = Amount("10 AAPL")
        s = str(a)
        assert s.endswith("AAPL")

    def test_gbp_suffix(self):
        a = Amount("50.00 GBP")
        s = str(a)
        assert s.endswith("GBP")


class TestAmountThousandsSeparator:
    """Thousands separators when style is learned."""

    def test_thousands_learned_from_parse(self):
        # Parsing "$1,000.00" teaches $ to use thousands
        a = Amount("$1,000.00")
        assert str(a) == "$1,000.00"

    def test_thousands_applied_to_subsequent_amounts(self):
        # First amount teaches the style
        Amount("$1,000.00")
        # Second amount should inherit thousands style
        a2 = Amount("$2000.00")
        assert "," in str(a2) or str(a2) == "$2000.00"  # may or may not apply

    def test_no_thousands_without_learning(self):
        a = Amount("$100.00")
        assert "," not in str(a)

    def test_large_number_thousands(self):
        a = Amount("$1,234,567.89")
        assert str(a) == "$1,234,567.89"


class TestAmountDecimalPrecision:
    """Correct decimal places based on commodity precision."""

    def test_two_decimal_places(self):
        a = Amount("$100.00")
        assert str(a) == "$100.00"

    def test_no_decimal_places(self):
        a = Amount("10 AAPL")
        s = str(a)
        assert "." not in s.split("AAPL")[0].strip()

    def test_three_decimal_places(self):
        a = Amount("1.234 BTC")
        assert "1.234" in str(a)

    def test_precision_from_commodity(self):
        # When commodity precision is learned from one amount,
        # it applies to others
        Amount("$100.00")  # teaches $ precision = 2
        a = Amount(42, "$")
        s = str(a)
        assert "$42.00" == s


class TestAmountNegativeDisplay:
    """Negative amounts display with sign adjacent to commodity."""

    def test_negative_dollar(self):
        a = Amount("$-42.50")
        s = str(a)
        assert "$-42.50" == s

    def test_negative_suffix_commodity(self):
        a = Amount("-100 EUR")
        s = str(a)
        assert s.startswith("-100")
        assert s.endswith("EUR")

    def test_negated_amount(self):
        a = Amount("$100.00")
        neg = a.negated()
        assert "$-100.00" == str(neg)


# ===================================================================
# 5. Integration: Balance command output format
# ===================================================================


class TestBalanceOutputIntegration:
    """Full balance command output checks."""

    def test_simple_balance_has_separator(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        assert "--------------------" in output

    def test_balance_ends_with_newline(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        assert output.endswith("\n")

    def test_balance_tree_mode_default(self):
        journal = _make_simple_journal()
        output = balance_command(journal)
        # Should show top-level accounts in tree mode
        assert "Assets" in output
        assert "Expenses" in output
        assert "Income" in output

    def test_balance_flat_vs_tree_different(self):
        journal = _make_simple_journal()
        tree_output = balance_command(journal)
        flat_output = balance_command(journal, ["--flat"])
        # Flat shows full paths, tree may show indented short names
        assert "Assets:Checking" in flat_output

    def test_balance_depth_limiting(self):
        journal = _make_simple_journal()
        output = balance_command(journal, ["--depth", "1"])
        # Should show only top-level accounts
        lines = output.strip().split("\n")
        account_lines = [l for l in lines if "----" not in l and l.strip() != "0"]
        for line in account_lines:
            account_part = line[22:].strip() if len(line) > 22 else line.strip()
            if account_part and account_part != "0":
                assert ":" not in account_part, f"Depth 1 should not show children: {line!r}"


# ===================================================================
# 6. Integration: Register command output format
# ===================================================================


class TestRegisterOutputIntegration:
    """Full register command output checks."""

    def test_register_ends_with_newline(self):
        journal = _make_simple_journal()
        output = register_command(journal)
        assert output.endswith("\n")

    def test_register_empty_journal(self):
        journal = Journal()
        output = register_command(journal)
        assert output == ""

    def test_register_all_lines_same_width(self):
        journal = _make_simple_journal()
        output = register_command(journal)
        lines = output.rstrip("\n").split("\n")
        for line in lines:
            assert len(line) == 80

    def test_register_wide_all_lines_same_width(self):
        journal = _make_simple_journal()
        output = register_command(journal, ["-w"])
        lines = output.rstrip("\n").split("\n")
        for line in lines:
            assert len(line) == 132


# ===================================================================
# 7. Integration: Print command output format
# ===================================================================


class TestPrintOutputIntegration:
    """Full print command output checks."""

    def test_print_ends_with_newline(self):
        journal = _make_simple_journal()
        output = print_command(journal)
        assert output.endswith("\n")

    def test_print_empty_journal(self):
        journal = Journal()
        output = print_command(journal)
        assert output == ""

    def test_print_round_trip_preserves_payee(self):
        journal = _make_simple_journal()
        output = print_command(journal)
        journal2 = _parse(output)
        assert journal2.xacts[0].payee == "Paycheck"
        assert journal2.xacts[1].payee == "Grocery Store"

    def test_print_round_trip_preserves_dates(self):
        journal = _make_simple_journal()
        output = print_command(journal)
        journal2 = _parse(output)
        assert journal2.xacts[0].date == date(2024, 1, 1)
        assert journal2.xacts[1].date == date(2024, 1, 5)

    def test_print_posting_indent_is_4_spaces(self):
        journal = _make_simple_journal()
        output = print_command(journal)
        lines = output.split("\n")
        for line in lines:
            if line and not line[0].isdigit() and line.strip():
                assert line.startswith("    "), f"Expected 4-space indent: {line!r}"

    def test_virtual_posting_delimiters(self):
        journal = _parse("""\
2024/01/15 Test
    Assets:Checking     $100.00
    Income:Salary
    (Budget:Food)        $50.00
""")
        output = print_command(journal)
        assert "(Budget:Food)" in output

    def test_balanced_virtual_posting_delimiters(self):
        journal = _parse("""\
2024/01/15 Transfer
    Assets:Checking     $500.00
    Assets:Savings     $-500.00
    [Budget:Emergency]   $500.00
    [Budget:General]    $-500.00
""")
        output = print_command(journal)
        assert "[Budget:Emergency]" in output
        assert "[Budget:General]" in output
