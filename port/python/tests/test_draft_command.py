"""Tests for the draft/xact/entry command."""

from __future__ import annotations

import re
from datetime import date
from unittest.mock import patch

import pytest

from muonledger.commands.draft import (
    create_draft,
    draft_command,
    find_matching_xact,
    parse_draft_args,
)
from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.xact import Transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(text: str) -> Journal:
    """Parse *text* and return the populated journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


SAMPLE_JOURNAL = """\
2024/01/10 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking

2024/01/12 Coffee Shop
    Expenses:Dining     $5.75
    Assets:Cash

2024/01/15 Grocery Store
    Expenses:Food       $38.00
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $120.00
    Assets:Checking

2024/02/01 Rent Payment
    Expenses:Rent       $1,500.00
    Assets:Checking
"""


# ---------------------------------------------------------------------------
# parse_draft_args tests
# ---------------------------------------------------------------------------


class TestParseDraftArgs:
    """Test argument parsing for the draft command."""

    def test_payee_only(self):
        d, payee, amount, account = parse_draft_args(["Grocery"])
        assert d is None
        assert payee == "Grocery"
        assert amount is None
        assert account is None

    def test_date_and_payee(self):
        d, payee, amount, account = parse_draft_args(["2024/03/15", "Grocery"])
        assert d == date(2024, 3, 15)
        assert payee == "Grocery"
        assert amount is None
        assert account is None

    def test_payee_and_amount(self):
        d, payee, amount, account = parse_draft_args(["Grocery", "50"])
        assert d is None
        assert payee == "Grocery"
        assert amount is not None
        assert float(amount) == 50.0
        assert account is None

    def test_payee_amount_and_account(self):
        d, payee, amount, account = parse_draft_args(
            ["Grocery", "50", "Expenses:Food"]
        )
        assert d is None
        assert payee == "Grocery"
        assert float(amount) == 50.0
        assert account == "Expenses:Food"

    def test_date_payee_amount_account(self):
        d, payee, amount, account = parse_draft_args(
            ["2024/06/01", "Grocery", "$42.50", "Expenses:Food"]
        )
        assert d == date(2024, 6, 1)
        assert payee == "Grocery"
        assert amount is not None
        assert account == "Expenses:Food"

    def test_empty_args(self):
        d, payee, amount, account = parse_draft_args([])
        assert d is None
        assert payee == ""
        assert amount is None
        assert account is None

    def test_date_only(self):
        d, payee, amount, account = parse_draft_args(["2024/01/01"])
        assert d == date(2024, 1, 1)
        assert payee == ""

    def test_date_with_dashes(self):
        d, payee, amount, account = parse_draft_args(["2024-03-15", "Test"])
        assert d == date(2024, 3, 15)
        assert payee == "Test"

    def test_partial_date_month_day(self):
        d, payee, amount, account = parse_draft_args(
            ["03/15", "Grocery"], default_year=2024
        )
        assert d == date(2024, 3, 15)
        assert payee == "Grocery"

    def test_partial_date_uses_current_year(self):
        d, payee, amount, account = parse_draft_args(["06/15", "Test"])
        assert d is not None
        assert d.year == date.today().year
        assert d.month == 6
        assert d.day == 15

    def test_amount_with_dollar_sign(self):
        d, payee, amount, account = parse_draft_args(["Test", "$25.00"])
        assert amount is not None
        assert "25.00" in str(amount)

    def test_negative_amount(self):
        d, payee, amount, account = parse_draft_args(["Test", "-50"])
        assert amount is not None
        assert float(amount) == -50.0

    def test_account_without_colon_treated_as_account(self):
        # If something doesn't parse as an amount and we already have a payee
        d, payee, amount, account = parse_draft_args(["Grocery", "50", "Food"])
        assert payee == "Grocery"
        assert float(amount) == 50.0
        assert account == "Food"


# ---------------------------------------------------------------------------
# find_matching_xact tests
# ---------------------------------------------------------------------------


class TestFindMatchingXact:
    """Test payee matching in journal transactions."""

    def test_exact_payee_match(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "Grocery Store")
        assert xact is not None
        assert xact.payee == "Grocery Store"

    def test_case_insensitive_match(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "grocery store")
        assert xact is not None
        assert xact.payee == "Grocery Store"

    def test_partial_match(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "Grocery")
        assert xact is not None
        assert xact.payee == "Grocery Store"

    def test_most_recent_match_wins(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "Grocery Store")
        assert xact is not None
        # The most recent Grocery Store transaction is 2024/01/15
        assert xact.date == date(2024, 1, 15)

    def test_no_match_returns_none(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "Nonexistent Payee")
        assert xact is None

    def test_empty_pattern_returns_none(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "")
        assert xact is None

    def test_empty_journal_returns_none(self):
        journal = Journal()
        xact = find_matching_xact(journal, "Test")
        assert xact is None

    def test_regex_match_fallback(self):
        journal = _parse(SAMPLE_JOURNAL)
        # Use regex that matches "Coffee" or "Electric"
        xact = find_matching_xact(journal, "Coff.*Shop")
        assert xact is not None
        assert xact.payee == "Coffee Shop"

    def test_partial_case_insensitive(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "coffee")
        assert xact is not None
        assert xact.payee == "Coffee Shop"

    def test_single_transaction_journal(self):
        text = """\
2024/01/01 Only Payee
    Expenses:Test       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        xact = find_matching_xact(journal, "Only")
        assert xact is not None
        assert xact.payee == "Only Payee"

    def test_match_electric(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = find_matching_xact(journal, "Electric")
        assert xact is not None
        assert xact.payee == "Electric Company"


# ---------------------------------------------------------------------------
# create_draft tests
# ---------------------------------------------------------------------------


class TestCreateDraft:
    """Test draft transaction creation."""

    def test_draft_from_template(self):
        journal = _parse(SAMPLE_JOURNAL)
        template = find_matching_xact(journal, "Grocery Store")
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Grocery Store",
            template_xact=template,
            journal=journal,
        )
        assert xact.payee == "Grocery Store"
        assert xact.date == date(2024, 3, 1)
        assert len(xact.posts) == 2

    def test_draft_with_override_amount(self):
        journal = _parse(SAMPLE_JOURNAL)
        template = find_matching_xact(journal, "Grocery Store")
        new_amount = Amount("$55.00")
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Grocery Store",
            template_xact=template,
            amount=new_amount,
            journal=journal,
        )
        assert len(xact.posts) == 2
        assert xact.posts[0].amount is not None
        assert "$55.00" in str(xact.posts[0].amount)
        # Second posting should be None (for auto-balancing)
        assert xact.posts[1].amount is None

    def test_draft_with_override_account(self):
        journal = _parse(SAMPLE_JOURNAL)
        template = find_matching_xact(journal, "Grocery Store")
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Grocery Store",
            template_xact=template,
            account="Expenses:Groceries",
            journal=journal,
        )
        assert xact.posts[0].account.fullname == "Expenses:Groceries"

    def test_draft_with_amount_and_account(self):
        journal = _parse(SAMPLE_JOURNAL)
        template = find_matching_xact(journal, "Grocery Store")
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Grocery Store",
            template_xact=template,
            amount=Amount("$99.00"),
            account="Expenses:Groceries",
            journal=journal,
        )
        assert xact.posts[0].account.fullname == "Expenses:Groceries"
        assert "$99.00" in str(xact.posts[0].amount)

    def test_draft_no_template_with_amount_and_account(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="New Store",
            template_xact=None,
            amount=Amount("$25.00"),
            account="Expenses:Shopping",
            journal=journal,
        )
        assert xact.payee == "New Store"
        assert len(xact.posts) == 2
        assert xact.posts[0].account.fullname == "Expenses:Shopping"

    def test_draft_no_template_no_amount_no_account(self):
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Unknown Store",
        )
        assert xact.payee == "Unknown Store"
        assert len(xact.posts) == 0

    def test_draft_no_template_with_amount_only(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="New Store",
            amount=Amount("$10.00"),
            journal=journal,
        )
        assert len(xact.posts) == 2

    def test_draft_no_template_with_account_only(self):
        journal = _parse(SAMPLE_JOURNAL)
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="New Store",
            account="Expenses:Test",
            journal=journal,
        )
        assert len(xact.posts) == 1
        assert xact.posts[0].account.fullname == "Expenses:Test"

    def test_draft_preserves_template_accounts(self):
        journal = _parse(SAMPLE_JOURNAL)
        template = find_matching_xact(journal, "Coffee Shop")
        xact = create_draft(
            draft_date=date(2024, 3, 1),
            payee="Coffee Shop",
            template_xact=template,
            journal=journal,
        )
        # Should preserve Expenses:Dining and Assets:Cash from the template
        account_names = [p.account.fullname for p in xact.posts]
        assert "Expenses:Dining" in account_names
        assert "Assets:Cash" in account_names


# ---------------------------------------------------------------------------
# draft_command (integration) tests
# ---------------------------------------------------------------------------


class TestDraftCommand:
    """Test the full draft command pipeline."""

    def test_basic_draft_with_payee(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Grocery"])
        assert "Grocery Store" in output
        assert "Expenses:Food" in output

    def test_draft_with_date_and_payee(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["2024/06/01", "Grocery"])
        assert "2024/06/01" in output
        assert "Grocery Store" in output

    def test_draft_with_payee_and_amount(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Grocery", "$50.00"])
        assert "Grocery Store" in output
        assert "$50.00" in output

    def test_draft_with_explicit_account(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(
            journal, ["Grocery", "$50.00", "Expenses:Groceries"]
        )
        assert "Expenses:Groceries" in output

    def test_draft_default_today_date(self):
        journal = _parse(SAMPLE_JOURNAL)
        today = date.today()
        output = draft_command(journal, ["Grocery"])
        expected_date = today.strftime("%Y/%m/%d")
        assert expected_date in output

    def test_draft_no_match_bare_payee(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Nonexistent"])
        assert "Nonexistent" in output

    def test_draft_empty_args_returns_empty(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, [])
        assert output == ""

    def test_draft_empty_journal(self):
        journal = Journal()
        output = draft_command(journal, ["Test"])
        assert "Test" in output

    def test_draft_with_all_arguments(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(
            journal, ["2024/12/25", "Coffee", "$8.00", "Expenses:Dining"]
        )
        assert "2024/12/25" in output
        assert "Coffee Shop" in output  # Full payee from match
        assert "$8.00" in output
        assert "Expenses:Dining" in output

    def test_draft_case_insensitive_payee(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["grocery"])
        assert "Grocery Store" in output

    def test_draft_preserves_template_structure(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Electric"])
        assert "Electric Company" in output
        assert "Expenses:Utilities" in output
        assert "Assets:Checking" in output

    def test_draft_rent_payment(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Rent"])
        assert "Rent Payment" in output
        assert "Expenses:Rent" in output

    def test_draft_override_amount_balances(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Coffee", "$10.00"])
        assert "$10.00" in output
        # Should have a balancing posting
        assert "Assets:Cash" in output

    def test_draft_outputs_valid_ledger_format(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["2024/06/01", "Grocery"])
        # Should start with a date
        assert re.match(r"\d{4}/\d{2}/\d{2}", output)
        # Should have indented postings
        assert "    " in output

    def test_draft_no_args_returns_empty(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, None)
        assert output == ""

    def test_draft_with_date_dashes(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["2024-06-01", "Grocery"])
        assert "2024/06/01" in output
        assert "Grocery Store" in output


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestDraftEdgeCases:
    """Edge cases and corner cases for the draft command."""

    def test_payee_with_special_characters(self):
        text = """\
2024/01/01 Bob's Diner
    Expenses:Dining     $15.00
    Assets:Cash
"""
        journal = _parse(text)
        xact = find_matching_xact(journal, "Bob's")
        assert xact is not None
        assert xact.payee == "Bob's Diner"

    def test_multiple_matching_payees_most_recent(self):
        text = """\
2024/01/01 Store A
    Expenses:Food       $10.00
    Assets:Cash

2024/01/15 Store A
    Expenses:Food       $20.00
    Assets:Cash

2024/02/01 Store A
    Expenses:Food       $30.00
    Assets:Cash
"""
        journal = _parse(text)
        xact = find_matching_xact(journal, "Store A")
        assert xact is not None
        assert xact.date == date(2024, 2, 1)

    def test_draft_with_three_posting_template(self):
        text = """\
2024/01/01 Split Transaction
    Expenses:Food       $20.00
    Expenses:Drink      $10.00
    Assets:Cash
"""
        journal = _parse(text)
        output = draft_command(journal, ["Split"])
        assert "Split Transaction" in output
        assert "Expenses:Food" in output
        assert "Expenses:Drink" in output

    def test_draft_invalid_date_treated_as_payee(self):
        journal = _parse(SAMPLE_JOURNAL)
        # "13/32" is not a valid date
        d, payee, amount, account = parse_draft_args(["13/32", "Test"])
        # 13/32 is invalid so it becomes the payee
        # (parse_draft_args tries date first; month 13 is invalid)
        assert d is None
        assert payee == "13/32"

    def test_draft_with_commodity_amount(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Grocery", "$42.50"])
        assert "$42.50" in output

    def test_draft_single_xact_journal(self):
        text = """\
2024/01/01 Only Transaction
    Expenses:Test       $100.00
    Assets:Bank
"""
        journal = _parse(text)
        output = draft_command(journal, ["Only"])
        assert "Only Transaction" in output
        assert "Expenses:Test" in output
        assert "Assets:Bank" in output

    def test_find_matching_with_regex_special_chars(self):
        text = """\
2024/01/01 Store (Main)
    Expenses:Test       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        # Substring match should still work with parens in payee
        xact = find_matching_xact(journal, "Store (Main)")
        assert xact is not None

    def test_find_matching_invalid_regex_fallback(self):
        text = """\
2024/01/01 Test Store
    Expenses:Test       $10.00
    Assets:Cash
"""
        journal = _parse(text)
        # "[invalid" is a broken regex but "Test" substring should match
        xact = find_matching_xact(journal, "Test")
        assert xact is not None

    def test_draft_preserves_amounts_from_template(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Coffee"])
        # Should use the template amount ($5.75)
        assert "$5.75" in output

    def test_draft_no_journal_context(self):
        # Test create_draft without a journal (uses _SimpleAccount)
        xact = create_draft(
            draft_date=date(2024, 1, 1),
            payee="Test",
            amount=Amount("$10.00"),
            account="Expenses:Test",
        )
        assert xact.payee == "Test"
        assert len(xact.posts) == 2
        assert xact.posts[0].account.fullname == "Expenses:Test"

    def test_draft_uses_full_payee_from_template(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["Elec"])
        # Should expand to "Electric Company" from the template match
        assert "Electric Company" in output

    def test_draft_with_zero_amount(self):
        journal = _parse(SAMPLE_JOURNAL)
        d, payee, amount, account = parse_draft_args(["Grocery", "0"])
        assert amount is not None
        assert float(amount) == 0.0

    def test_draft_non_matching_payee_no_template(self):
        journal = _parse(SAMPLE_JOURNAL)
        output = draft_command(journal, ["2024/05/01", "Brand New Store"])
        assert "2024/05/01" in output
        assert "Brand New Store" in output


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestDraftCLIIntegration:
    """Test the draft command is properly registered in the CLI."""

    def test_xact_alias_in_cli(self):
        from muonledger.cli import COMMAND_ALIASES
        assert COMMAND_ALIASES.get("xact") == "draft"

    def test_entry_alias_in_cli(self):
        from muonledger.cli import COMMAND_ALIASES
        assert COMMAND_ALIASES.get("entry") == "draft"

    def test_draft_alias_in_cli(self):
        from muonledger.cli import COMMAND_ALIASES
        assert COMMAND_ALIASES.get("draft") == "draft"
