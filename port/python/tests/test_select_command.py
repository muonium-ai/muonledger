"""Tests for the select command."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.select import (
    SelectError,
    _format_date,
    _format_table,
    _parse_select_query,
    _parse_where_clause,
    _resolve_field_name,
    select_command,
)


# ---------------------------------------------------------------------------
# Helpers to build test journals
# ---------------------------------------------------------------------------


def _make_journal(*xact_specs) -> Journal:
    """Build a journal from xact specs.

    Each spec is a tuple: (date, payee, [(account_name, amount_str), ...])
    amount_str can be a number (interpreted as commodity-less) or "$N".
    """
    journal = Journal()

    for dt, payee, postings in xact_specs:
        xact = Transaction(payee=payee)
        xact.date = dt

        for acct_name, amt_val in postings:
            account = journal.find_account(acct_name)
            if amt_val is None:
                post = Post(account=account, amount=None)
            elif isinstance(amt_val, str):
                amt = Amount(amt_val)
                post = Post(account=account, amount=amt)
            elif isinstance(amt_val, Amount):
                post = Post(account=account, amount=amt_val)
            else:
                post = Post(account=account, amount=Amount(Fraction(amt_val)))
            xact.add_post(post)

        journal.add_xact(xact)

    return journal


def _simple_journal() -> Journal:
    """A simple two-transaction journal for most tests."""
    return _make_journal(
        (
            date(2024, 1, 15),
            "Grocery Store",
            [("Expenses:Food", "$42.50"), ("Assets:Checking", "$-42.50")],
        ),
        (
            date(2024, 1, 20),
            "Gas Station",
            [("Expenses:Transport", "$30"), ("Assets:Checking", "$-30")],
        ),
    )


def _multi_journal() -> Journal:
    """A larger journal with varied transactions."""
    return _make_journal(
        (
            date(2024, 1, 5),
            "Opening Balance",
            [("Assets:Checking", "$1000"), ("Equity:Opening", "$-1000")],
        ),
        (
            date(2024, 1, 10),
            "Supermarket",
            [("Expenses:Food:Groceries", "$55.20"), ("Assets:Checking", "$-55.20")],
        ),
        (
            date(2024, 1, 15),
            "Coffee Shop",
            [("Expenses:Food:Dining", "$4.75"), ("Assets:Checking", "$-4.75")],
        ),
        (
            date(2024, 2, 1),
            "Employer",
            [("Assets:Checking", "$3000"), ("Income:Salary", "$-3000")],
        ),
        (
            date(2024, 2, 5),
            "Landlord",
            [("Expenses:Rent", "$1200"), ("Assets:Checking", "$-1200")],
        ),
    )


# ---------------------------------------------------------------------------
# Tests: _parse_select_query
# ---------------------------------------------------------------------------


class TestParseSelectQuery:
    def test_single_field(self):
        fields, where = _parse_select_query("date")
        assert fields == ["date"]
        assert where is None

    def test_multiple_fields(self):
        fields, where = _parse_select_query("date, payee, account, amount")
        assert fields == ["date", "payee", "account", "amount"]
        assert where is None

    def test_with_select_keyword(self):
        fields, where = _parse_select_query("select date, payee")
        assert fields == ["date", "payee"]
        assert where is None

    def test_with_where_clause(self):
        fields, where = _parse_select_query(
            "date, payee, amount where account =~ /Expenses/"
        )
        assert fields == ["date", "payee", "amount"]
        assert where == "account =~ /Expenses/"

    def test_with_from_postings(self):
        fields, where = _parse_select_query(
            "date, payee from postings where account =~ /Food/"
        )
        assert fields == ["date", "payee"]
        assert where == "account =~ /Food/"

    def test_from_postings_no_where(self):
        fields, where = _parse_select_query("date, payee from postings")
        assert fields == ["date", "payee"]
        assert where is None

    def test_field_alias_display_amount(self):
        fields, where = _parse_select_query("display_amount")
        assert fields == ["amount"]

    def test_field_alias_desc(self):
        fields, where = _parse_select_query("desc")
        assert fields == ["payee"]

    def test_field_alias_state(self):
        fields, where = _parse_select_query("state")
        assert fields == ["status"]

    def test_star_wildcard(self):
        fields, where = _parse_select_query("*")
        assert fields == ["date", "payee", "account", "amount"]

    def test_empty_query_raises(self):
        with pytest.raises(SelectError):
            _parse_select_query("")

    def test_select_only_raises(self):
        with pytest.raises(SelectError):
            _parse_select_query("select")

    def test_unknown_field_raises(self):
        with pytest.raises(SelectError, match="Unknown field"):
            _parse_select_query("date, nonexistent")


# ---------------------------------------------------------------------------
# Tests: _resolve_field_name
# ---------------------------------------------------------------------------


class TestResolveFieldName:
    def test_canonical_names(self):
        assert _resolve_field_name("date") == "date"
        assert _resolve_field_name("payee") == "payee"
        assert _resolve_field_name("account") == "account"
        assert _resolve_field_name("amount") == "amount"

    def test_aliases(self):
        assert _resolve_field_name("display_amount") == "amount"
        assert _resolve_field_name("desc") == "payee"
        assert _resolve_field_name("description") == "payee"
        assert _resolve_field_name("state") == "status"
        assert _resolve_field_name("cleared") == "status"
        assert _resolve_field_name("display_total") == "total"

    def test_case_insensitive(self):
        assert _resolve_field_name("Date") == "date"
        assert _resolve_field_name("PAYEE") == "payee"
        assert _resolve_field_name("Display_Amount") == "amount"


# ---------------------------------------------------------------------------
# Tests: _format_date
# ---------------------------------------------------------------------------


class TestFormatDate:
    def test_normal_date(self):
        assert _format_date(date(2024, 1, 15)) == "2024/01/15"

    def test_none_date(self):
        assert _format_date(None) == ""

    def test_year_padding(self):
        assert _format_date(date(900, 3, 5)) == "0900/03/05"


# ---------------------------------------------------------------------------
# Tests: _format_table
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_basic_table(self):
        headers = ["Name", "Value"]
        rows = [["foo", "1"], ["bar", "22"]]
        output = _format_table(headers, rows)
        lines = output.strip().split("\n")
        assert len(lines) == 4  # header + separator + 2 data rows
        assert "Name" in lines[0]
        assert "---" in lines[1]

    def test_empty_rows(self):
        assert _format_table(["A"], []) == ""

    def test_column_alignment(self):
        headers = ["X"]
        rows = [["short"], ["a much longer value"]]
        output = _format_table(headers, rows)
        lines = output.strip().split("\n")
        # Separator should be at least as wide as longest value
        assert len(lines[1]) >= len("a much longer value")


# ---------------------------------------------------------------------------
# Tests: _parse_where_clause
# ---------------------------------------------------------------------------


class TestParseWhereClause:
    def test_account_regex(self):
        clause = _parse_where_clause("account =~ /Expenses/")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][0] == "account"
        assert clause.conditions[0][1] == "=~"

    def test_payee_regex(self):
        clause = _parse_where_clause("payee =~ /Store/")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][0] == "payee"

    def test_amount_comparison(self):
        clause = _parse_where_clause("amount > 100")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][1] == ">"

    def test_and_connective(self):
        clause = _parse_where_clause(
            "account =~ /Expenses/ and payee =~ /Store/"
        )
        assert len(clause.conditions) == 2
        assert clause.connectives == ["and"]

    def test_or_connective(self):
        clause = _parse_where_clause(
            "account =~ /Food/ or account =~ /Transport/"
        )
        assert len(clause.conditions) == 2
        assert clause.connectives == ["or"]

    def test_empty_where(self):
        clause = _parse_where_clause("")
        assert len(clause.conditions) == 0

    def test_equality(self):
        clause = _parse_where_clause("payee == Grocery Store")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][1] == "=="

    def test_not_equal(self):
        clause = _parse_where_clause("account != Assets")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][1] == "!="

    def test_negative_regex(self):
        clause = _parse_where_clause("account !~ /Assets/")
        assert len(clause.conditions) == 1
        assert clause.conditions[0][1] == "!~"


# ---------------------------------------------------------------------------
# Tests: select_command — basic field selection
# ---------------------------------------------------------------------------


class TestSelectCommandBasicFields:
    def test_select_date(self):
        journal = _simple_journal()
        output = select_command(journal, "date")
        assert "2024/01/15" in output
        assert "2024/01/20" in output

    def test_select_payee(self):
        journal = _simple_journal()
        output = select_command(journal, "payee")
        assert "Grocery Store" in output
        assert "Gas Station" in output

    def test_select_account(self):
        journal = _simple_journal()
        output = select_command(journal, "account")
        assert "Expenses:Food" in output
        assert "Assets:Checking" in output
        assert "Expenses:Transport" in output

    def test_select_amount(self):
        journal = _simple_journal()
        output = select_command(journal, "amount")
        assert "$42.50" in output or "42.50" in output

    def test_select_multiple_fields(self):
        journal = _simple_journal()
        output = select_command(journal, "date, payee, account, amount")
        assert "2024/01/15" in output
        assert "Grocery Store" in output
        assert "Expenses:Food" in output

    def test_select_note(self):
        journal = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.note = "a note"
        account = journal.find_account("Expenses:Food")
        p1 = Post(account=account, amount=Amount(Fraction(10)))
        account2 = journal.find_account("Assets:Cash")
        p2 = Post(account=account2, amount=Amount(Fraction(-10)))
        xact.add_post(p1)
        xact.add_post(p2)
        journal.add_xact(xact)
        output = select_command(journal, "note")
        assert "a note" in output

    def test_select_status_cleared(self):
        journal = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.state = ItemState.CLEARED
        account = journal.find_account("Expenses:Food")
        p1 = Post(account=account, amount=Amount(Fraction(10)))
        account2 = journal.find_account("Assets:Cash")
        p2 = Post(account=account2, amount=Amount(Fraction(-10)))
        xact.add_post(p1)
        xact.add_post(p2)
        journal.add_xact(xact)
        output = select_command(journal, "status")
        assert "*" in output

    def test_select_status_pending(self):
        journal = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.state = ItemState.PENDING
        account = journal.find_account("Expenses:Food")
        p1 = Post(account=account, amount=Amount(Fraction(10)))
        account2 = journal.find_account("Assets:Cash")
        p2 = Post(account=account2, amount=Amount(Fraction(-10)))
        xact.add_post(p1)
        xact.add_post(p2)
        journal.add_xact(xact)
        output = select_command(journal, "status")
        assert "!" in output

    def test_select_status_uncleared(self):
        journal = _simple_journal()
        output = select_command(journal, "date, status")
        # Uncleared status shows empty string for each posting
        lines = output.strip().split("\n")
        assert len(lines) >= 3  # header + sep + at least 1 data row
        assert "Date" in lines[0]
        assert "Status" in lines[0]

    def test_select_commodity(self):
        journal = _simple_journal()
        output = select_command(journal, "commodity")
        assert "$" in output

    def test_select_quantity(self):
        journal = _simple_journal()
        output = select_command(journal, "quantity")
        # Should contain numeric quantities
        assert "42" in output or "30" in output

    def test_select_code(self):
        journal = Journal()
        xact = Transaction(payee="Test")
        xact.date = date(2024, 1, 1)
        xact.code = "1042"
        account = journal.find_account("Expenses:Food")
        p1 = Post(account=account, amount=Amount(Fraction(10)))
        account2 = journal.find_account("Assets:Cash")
        p2 = Post(account=account2, amount=Amount(Fraction(-10)))
        xact.add_post(p1)
        xact.add_post(p2)
        journal.add_xact(xact)
        output = select_command(journal, "code")
        assert "1042" in output


# ---------------------------------------------------------------------------
# Tests: select_command — where clause filtering
# ---------------------------------------------------------------------------


class TestSelectCommandWhereClause:
    def test_where_account_filter(self):
        journal = _simple_journal()
        output = select_command(
            journal, "date, payee, amount where account =~ /Expenses/"
        )
        assert "Grocery Store" in output
        assert "Gas Station" in output
        # Checking account should not appear (it's filtered out)
        lines = output.strip().split("\n")
        data_lines = lines[2:]  # skip header and separator
        for line in data_lines:
            assert "Assets:Checking" not in line

    def test_where_payee_filter(self):
        journal = _simple_journal()
        output = select_command(
            journal, "date, account where payee =~ /Grocery/"
        )
        assert "Expenses:Food" in output
        # Gas Station postings should not appear
        assert "Expenses:Transport" not in output

    def test_where_amount_greater_than(self):
        journal = _simple_journal()
        output = select_command(
            journal, "payee, amount where amount > 40"
        )
        # $42.50 > 40 should match; $30 > 40 should not
        assert "Grocery Store" in output

    def test_where_amount_less_than(self):
        journal = _simple_journal()
        output = select_command(
            journal, "payee, amount where amount < 35"
        )
        assert "Gas Station" in output

    def test_where_regex_case_insensitive(self):
        journal = _simple_journal()
        output = select_command(
            journal, "payee where account =~ /expenses/"
        )
        assert "Grocery Store" in output

    def test_where_negative_regex(self):
        journal = _simple_journal()
        output = select_command(
            journal, "account where account !~ /Assets/"
        )
        lines = output.strip().split("\n")
        data_lines = lines[2:]
        for line in data_lines:
            assert "Assets" not in line

    def test_where_and_condition(self):
        journal = _multi_journal()
        output = select_command(
            journal,
            "date, payee where account =~ /Expenses/ and payee =~ /Super/",
        )
        assert "Supermarket" in output
        assert "Coffee" not in output

    def test_where_or_condition(self):
        journal = _multi_journal()
        output = select_command(
            journal,
            "payee where payee =~ /Supermarket/ or payee =~ /Coffee/",
        )
        assert "Supermarket" in output
        assert "Coffee Shop" in output
        # Others should not appear
        assert "Landlord" not in output
        assert "Employer" not in output

    def test_where_empty_result(self):
        journal = _simple_journal()
        output = select_command(
            journal, "date where account =~ /NonExistent/"
        )
        assert output == ""

    def test_where_equality(self):
        journal = _simple_journal()
        output = select_command(
            journal, "amount where payee == Grocery Store"
        )
        assert "$42.50" in output or "42.50" in output


# ---------------------------------------------------------------------------
# Tests: select_command — output format
# ---------------------------------------------------------------------------


class TestSelectCommandOutputFormat:
    def test_has_header_line(self):
        journal = _simple_journal()
        output = select_command(journal, "date, payee")
        lines = output.strip().split("\n")
        assert len(lines) >= 3  # header + separator + data
        assert "Date" in lines[0]
        assert "Payee" in lines[0]

    def test_has_separator_line(self):
        journal = _simple_journal()
        output = select_command(journal, "date")
        lines = output.strip().split("\n")
        assert "---" in lines[1]

    def test_column_alignment(self):
        journal = _simple_journal()
        output = select_command(journal, "date, payee, account")
        lines = output.strip().split("\n")
        # All lines should have similar structure (padded columns)
        # Header and data lines should align
        assert len(lines) >= 3

    def test_date_format_in_output(self):
        journal = _simple_journal()
        output = select_command(journal, "date")
        assert "2024/01/15" in output

    def test_amount_format_in_output(self):
        journal = _simple_journal()
        output = select_command(journal, "amount")
        # Should show commodity symbol with amount
        assert "$" in output

    def test_trailing_newline(self):
        journal = _simple_journal()
        output = select_command(journal, "date")
        assert output.endswith("\n")

    def test_all_canonical_fields(self):
        """Select all canonical fields at once."""
        journal = _simple_journal()
        output = select_command(
            journal, "date, payee, account, amount, note, status, commodity, quantity, code"
        )
        lines = output.strip().split("\n")
        # Header should contain all field names
        header = lines[0]
        assert "Date" in header
        assert "Payee" in header
        assert "Account" in header
        assert "Amount" in header


# ---------------------------------------------------------------------------
# Tests: select_command — edge cases
# ---------------------------------------------------------------------------


class TestSelectCommandEdgeCases:
    def test_empty_journal(self):
        journal = Journal()
        output = select_command(journal, "date, payee")
        assert output == ""

    def test_single_posting_transaction(self):
        """Single posting (after inferred amount)."""
        journal = _make_journal(
            (
                date(2024, 3, 1),
                "Test",
                [("Expenses:Food", "50"), ("Assets:Cash", "-50")],
            ),
        )
        output = select_command(journal, "date, payee, account")
        assert "Test" in output
        assert "Expenses:Food" in output

    def test_no_where_clause(self):
        journal = _simple_journal()
        output = select_command(journal, "date, payee")
        lines = output.strip().split("\n")
        # 4 postings (2 per xact) + header + separator = 6 lines
        assert len(lines) == 6

    def test_list_input(self):
        """Query passed as list of strings."""
        journal = _simple_journal()
        output = select_command(journal, ["date,", "payee"])
        assert "Date" in output
        assert "Payee" in output

    def test_select_keyword_prefix(self):
        journal = _simple_journal()
        output = select_command(journal, "select date, payee")
        assert "Date" in output

    def test_from_postings_clause(self):
        journal = _simple_journal()
        output = select_command(
            journal, "date, payee from postings where account =~ /Expenses/"
        )
        assert "Grocery Store" in output

    def test_multiple_transactions(self):
        journal = _multi_journal()
        output = select_command(journal, "date, payee, account, amount")
        lines = output.strip().split("\n")
        # 5 xacts * 2 postings each = 10 data lines + header + sep = 12
        assert len(lines) == 12

    def test_field_alias_display_amount_in_query(self):
        journal = _simple_journal()
        output = select_command(journal, "display_amount")
        # Should still work (resolves to "amount")
        assert "$42.50" in output or "42.50" in output

    def test_total_field_running(self):
        """The total field should produce a running total."""
        journal = _make_journal(
            (
                date(2024, 1, 1),
                "A",
                [("Expenses:Food", "10"), ("Assets:Cash", "-10")],
            ),
            (
                date(2024, 1, 2),
                "B",
                [("Expenses:Food", "20"), ("Assets:Cash", "-20")],
            ),
        )
        output = select_command(
            journal,
            "payee, amount, total where account =~ /Expenses/",
        )
        # After first Expenses posting: total=10
        # After second: total=30
        assert "10" in output
        assert "30" in output

    def test_select_star(self):
        journal = _simple_journal()
        output = select_command(journal, "*")
        assert "Date" in output
        assert "Payee" in output
        assert "Account" in output
        assert "Amount" in output

    def test_malformed_query_no_fields(self):
        with pytest.raises(SelectError):
            _parse_select_query("select from postings")

    def test_where_with_multiple_and(self):
        journal = _multi_journal()
        output = select_command(
            journal,
            "payee where account =~ /Food/ and payee =~ /Super/ and amount > 0",
        )
        assert "Supermarket" in output

    def test_commodity_less_amounts(self):
        """Amounts without commodity should show plain numbers."""
        journal = _make_journal(
            (
                date(2024, 1, 1),
                "Plain",
                [("Expenses:Test", "100"), ("Assets:Cash", "-100")],
            ),
        )
        output = select_command(journal, "amount")
        assert "100" in output
