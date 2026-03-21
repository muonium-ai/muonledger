"""Tests for directive parsing in the textual journal parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.parser import ParseError, TextualParser


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
# account directive
# ---------------------------------------------------------------------------


class TestAccountDirective:
    def test_account_registered(self):
        text = """\
account Expenses:Food

2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Cash
"""
        journal = _parse(text)
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct is not None

    def test_account_with_note(self):
        text = """\
account Expenses:Food
    note Food expenses

2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Cash
"""
        journal = _parse(text)
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct is not None
        assert acct.note == "Food expenses"

    def test_account_with_alias(self):
        text = """\
account Expenses:Food
    alias food

2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Cash
"""
        journal = _parse(text)
        assert "food" in journal.account_aliases
        assert journal.account_aliases["food"].fullname == "Expenses:Food"

    def test_account_with_default(self):
        text = """\
account Expenses:Food
    default
"""
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Expenses:Food"

    def test_account_with_multiple_sub_directives(self):
        text = """\
account Expenses:Food
    note Food expenses
    alias food
    default
"""
        journal = _parse(text)
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct.note == "Food expenses"
        assert "food" in journal.account_aliases
        assert journal.bucket is acct

    def test_account_no_sub_directives(self):
        text = """\
account Assets:Checking
"""
        journal = _parse(text)
        acct = journal.find_account("Assets:Checking", auto_create=False)
        assert acct is not None

    def test_account_followed_by_transaction(self):
        """Account directive followed immediately by a transaction."""
        text = """\
account Expenses:Food
    note Groceries
2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Cash
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct.note == "Groceries"


# ---------------------------------------------------------------------------
# commodity directive
# ---------------------------------------------------------------------------


class TestCommodityDirective:
    def test_commodity_registered(self):
        text = """\
commodity $
"""
        journal = _parse(text)
        comm = journal.commodity_pool.find("$")
        assert comm is not None
        assert comm.symbol == "$"

    def test_commodity_with_format(self):
        text = """\
commodity $
    format $1,000.00
"""
        journal = _parse(text)
        comm = journal.commodity_pool.find("$")
        assert comm is not None

    def test_commodity_with_note(self):
        text = """\
commodity $
    note US Dollar
"""
        journal = _parse(text)
        comm = journal.commodity_pool.find("$")
        assert comm is not None
        assert comm.note == "US Dollar"

    def test_commodity_with_default(self):
        text = """\
commodity EUR
    default
"""
        journal = _parse(text)
        assert journal.commodity_pool.default_commodity is not None
        assert journal.commodity_pool.default_commodity.symbol == "EUR"

    def test_commodity_multiple_sub_directives(self):
        text = """\
commodity $
    format $1,000.00
    note US Dollar
"""
        journal = _parse(text)
        comm = journal.commodity_pool.find("$")
        assert comm is not None
        assert comm.note == "US Dollar"


# ---------------------------------------------------------------------------
# include directive
# ---------------------------------------------------------------------------


class TestIncludeDirective:
    def test_include_file(self, tmp_path):
        """Include a file and parse its transactions."""
        included = tmp_path / "included.dat"
        included.write_text("""\
2024/01/01 Included Transaction
    Expenses:Food     $10.00
    Assets:Cash
""")
        main_file = tmp_path / "main.dat"
        main_file.write_text(f"""\
include included.dat

2024/01/02 Main Transaction
    Expenses:Drink    $5.00
    Assets:Cash
""")
        journal = Journal()
        parser = TextualParser()
        parser.parse(main_file, journal)
        assert len(journal.xacts) == 2
        payees = [x.payee for x in journal.xacts]
        assert "Included Transaction" in payees
        assert "Main Transaction" in payees

    def test_include_relative_path(self, tmp_path):
        """Include resolves paths relative to the current file."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        included = subdir / "data.dat"
        included.write_text("""\
2024/01/01 Sub Transaction
    Expenses:A     $1.00
    Assets:B
""")
        main_file = tmp_path / "main.dat"
        main_file.write_text("""\
include sub/data.dat
""")
        journal = Journal()
        parser = TextualParser()
        parser.parse(main_file, journal)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Sub Transaction"

    def test_include_missing_file(self, tmp_path):
        """Include of a non-existent file raises ParseError."""
        main_file = tmp_path / "main.dat"
        main_file.write_text("include nonexistent.dat\n")
        journal = Journal()
        parser = TextualParser()
        with pytest.raises(ParseError, match="not found"):
            parser.parse(main_file, journal)

    def test_include_quoted_path(self, tmp_path):
        """Include path with surrounding quotes."""
        included = tmp_path / "data.dat"
        included.write_text("""\
2024/01/01 Quoted Include
    Expenses:A     $1.00
    Assets:B
""")
        main_file = tmp_path / "main.dat"
        main_file.write_text('include "data.dat"\n')
        journal = Journal()
        parser = TextualParser()
        parser.parse(main_file, journal)
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# comment / end comment blocks
# ---------------------------------------------------------------------------


class TestCommentBlock:
    def test_comment_block_skipped(self):
        text = """\
comment
This is a multi-line comment
that spans several lines.
end comment

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Test"

    def test_comment_block_with_transaction_like_content(self):
        """Content inside comment block should not be parsed."""
        text = """\
comment
2024/01/01 Fake Transaction
    Expenses:Fake     $999.00
    Assets:Fake
end comment

2024/01/01 Real Transaction
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Real Transaction"

    def test_multiple_comment_blocks(self):
        text = """\
comment
block one
end comment

2024/01/01 Between
    Expenses:A     $1.00
    Assets:B

comment
block two
end comment
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_empty_comment_block(self):
        text = """\
comment
end comment

2024/01/01 Test
    Expenses:A     $1.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# P price directive
# ---------------------------------------------------------------------------


class TestPriceDirective:
    def test_price_entry(self):
        text = """\
P 2024/01/01 EUR $1.10
"""
        journal = _parse(text)
        assert len(journal.prices) == 1
        price_date, commodity, amount = journal.prices[0]
        assert price_date == date(2024, 1, 1)
        assert commodity == "EUR"
        assert float(amount) == pytest.approx(1.10)
        assert amount.commodity == "$"

    def test_multiple_prices(self):
        text = """\
P 2024/01/01 EUR $1.10
P 2024/01/01 AAPL $150.00
P 2024/06/15 EUR $1.08
"""
        journal = _parse(text)
        assert len(journal.prices) == 3

    def test_price_with_dash_date(self):
        text = """\
P 2024-01-01 BTC $42000.00
"""
        journal = _parse(text)
        assert len(journal.prices) == 1
        price_date, commodity, amount = journal.prices[0]
        assert price_date == date(2024, 1, 1)
        assert commodity == "BTC"
        assert float(amount) == pytest.approx(42000.00)

    def test_price_alongside_transactions(self):
        text = """\
P 2024/01/01 EUR $1.10

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.prices) == 1
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# D default commodity directive
# ---------------------------------------------------------------------------


class TestDefaultCommodityDirective:
    def test_default_commodity(self):
        text = """\
D $1,000.00
"""
        journal = _parse(text)
        assert journal.commodity_pool.default_commodity is not None
        assert journal.commodity_pool.default_commodity.symbol == "$"

    def test_default_commodity_eur(self):
        text = """\
D 1.000,00 EUR
"""
        journal = _parse(text)
        assert journal.commodity_pool.default_commodity is not None
        assert journal.commodity_pool.default_commodity.symbol == "EUR"


# ---------------------------------------------------------------------------
# Y / year directive
# ---------------------------------------------------------------------------


class TestYearDirective:
    def test_year_Y(self):
        text = """\
Y 2024
"""
        journal = _parse(text)
        assert journal.default_year == 2024

    def test_year_word(self):
        text = """\
year 2025
"""
        journal = _parse(text)
        assert journal.default_year == 2025

    def test_year_overwrite(self):
        text = """\
Y 2024
Y 2025
"""
        journal = _parse(text)
        assert journal.default_year == 2025

    def test_year_with_transactions(self):
        text = """\
Y 2024

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
"""
        journal = _parse(text)
        assert journal.default_year == 2024
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# alias directive
# ---------------------------------------------------------------------------


class TestAliasDirective:
    def test_simple_alias(self):
        text = "alias chk=Assets:Bank:Checking\n"
        journal = _parse(text)
        assert "chk" in journal.account_aliases
        assert journal.account_aliases["chk"].fullname == "Assets:Bank:Checking"

    def test_alias_with_spaces(self):
        text = "alias  savings = Assets:Bank:Savings \n"
        journal = _parse(text)
        assert "savings" in journal.account_aliases
        assert journal.account_aliases["savings"].fullname == "Assets:Bank:Savings"

    def test_alias_as_account_sub_directive(self):
        text = (
            "account Assets:Bank:Checking\n"
            "  alias chk\n"
            "  alias checking\n"
        )
        journal = _parse(text)
        assert "chk" in journal.account_aliases
        assert "checking" in journal.account_aliases
        assert journal.account_aliases["chk"].fullname == "Assets:Bank:Checking"
        assert journal.account_aliases["checking"].fullname == "Assets:Bank:Checking"

    def test_alias_resolution_in_posting(self):
        text = (
            "alias chk=Assets:Bank:Checking\n"
            "\n"
            "2024/01/15 Deposit\n"
            "  chk  $100\n"
            "  Income:Salary\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.posts[0].account.fullname == "Assets:Bank:Checking"

    def test_alias_no_equals(self):
        text = "alias chk\n"
        journal = _parse(text)
        assert len(journal.account_aliases) == 0

    def test_alias_empty_parts(self):
        text = "alias =\n"
        journal = _parse(text)
        assert len(journal.account_aliases) == 0


# ---------------------------------------------------------------------------
# bucket / A directive
# ---------------------------------------------------------------------------


class TestBucketDirective:
    def test_bucket_directive(self):
        text = "bucket Assets:Bank:Checking\n"
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Bank:Checking"

    def test_a_directive(self):
        text = "A Assets:Bank:Checking\n"
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Bank:Checking"

    def test_a_directive_lowercase(self):
        text = "a Assets:Bank:Savings\n"
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Bank:Savings"

    def test_bucket_overwrites_previous(self):
        text = (
            "bucket Assets:Checking\n"
            "bucket Assets:Savings\n"
        )
        journal = _parse(text)
        assert journal.bucket.fullname == "Assets:Savings"


# ---------------------------------------------------------------------------
# tag directive
# ---------------------------------------------------------------------------


class TestTagDirective:
    def test_single_tag(self):
        text = "tag receipt\n"
        journal = _parse(text)
        assert "receipt" in journal.tag_declarations

    def test_multiple_tags(self):
        text = (
            "tag receipt\n"
            "tag project\n"
            "tag client\n"
        )
        journal = _parse(text)
        assert journal.tag_declarations == ["receipt", "project", "client"]

    def test_tag_with_sub_directives(self):
        text = (
            "tag receipt\n"
            "  check value =~ /.*\\.pdf$/\n"
            "  assert value != \"\"\n"
        )
        journal = _parse(text)
        assert "receipt" in journal.tag_declarations

    def test_tag_with_comments(self):
        text = (
            "tag receipt\n"
            "  ; A tag for receipts\n"
        )
        journal = _parse(text)
        assert "receipt" in journal.tag_declarations


# ---------------------------------------------------------------------------
# payee directive
# ---------------------------------------------------------------------------


class TestPayeeDirective:
    def test_single_payee(self):
        text = "payee Whole Foods\n"
        journal = _parse(text)
        assert "Whole Foods" in journal.payee_declarations

    def test_multiple_payees(self):
        text = (
            "payee Whole Foods\n"
            "payee Trader Joe's\n"
        )
        journal = _parse(text)
        assert journal.payee_declarations == ["Whole Foods", "Trader Joe's"]

    def test_payee_with_sub_directives(self):
        text = (
            "payee Whole Foods\n"
            "  alias WholeFoods\n"
            "  uuid abc-123\n"
        )
        journal = _parse(text)
        assert "Whole Foods" in journal.payee_declarations


# ---------------------------------------------------------------------------
# apply account
# ---------------------------------------------------------------------------


class TestApplyAccount:
    def test_simple_apply_account(self):
        text = (
            "apply account Personal\n"
            "\n"
            "2024/01/15 Groceries\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply account\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.posts[0].account.fullname == "Personal:Expenses:Food"
        assert xact.posts[1].account.fullname == "Personal:Assets:Checking"

    def test_nested_apply_account(self):
        text = (
            "apply account Personal\n"
            "apply account Finances\n"
            "\n"
            "2024/01/15 Groceries\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply account\n"
            "end apply account\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.posts[0].account.fullname == "Personal:Finances:Expenses:Food"

    def test_end_apply_account_pops_stack(self):
        text = (
            "apply account Personal\n"
            "\n"
            "2024/01/15 Test 1\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply account\n"
            "\n"
            "2024/01/16 Test 2\n"
            "  Expenses:Food  $30\n"
            "  Assets:Checking\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 2
        assert journal.xacts[0].posts[0].account.fullname == "Personal:Expenses:Food"
        assert journal.xacts[1].posts[0].account.fullname == "Expenses:Food"

    def test_apply_account_stack_empty_after_end(self):
        text = (
            "apply account Personal\n"
            "end apply account\n"
        )
        journal = _parse(text)
        assert journal.apply_account_stack == []


# ---------------------------------------------------------------------------
# apply tag
# ---------------------------------------------------------------------------


class TestApplyTag:
    def test_simple_apply_tag(self):
        text = (
            "apply tag project\n"
            "\n"
            "2024/01/15 Groceries\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply tag\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.has_tag("project")

    def test_nested_apply_tag(self):
        text = (
            "apply tag project\n"
            "apply tag client\n"
            "\n"
            "2024/01/15 Groceries\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply tag\n"
            "end apply tag\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.has_tag("project")
        assert xact.has_tag("client")

    def test_end_apply_tag_pops_stack(self):
        text = (
            "apply tag project\n"
            "\n"
            "2024/01/15 Test 1\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply tag\n"
            "\n"
            "2024/01/16 Test 2\n"
            "  Expenses:Food  $30\n"
            "  Assets:Checking\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 2
        assert journal.xacts[0].has_tag("project")
        assert not journal.xacts[1].has_tag("project")

    def test_apply_tag_stack_empty_after_end(self):
        text = (
            "apply tag project\n"
            "end apply tag\n"
        )
        journal = _parse(text)
        assert journal.apply_tag_stack == []


# ---------------------------------------------------------------------------
# N no-market directive
# ---------------------------------------------------------------------------


class TestNoMarketDirective:
    def test_n_directive(self):
        text = "N $\n"
        journal = _parse(text)
        assert "$" in journal.no_market_commodities

    def test_n_directive_multiple(self):
        text = (
            "N $\n"
            "N EUR\n"
        )
        journal = _parse(text)
        assert journal.no_market_commodities == ["$", "EUR"]

    def test_n_directive_lowercase(self):
        text = "n $\n"
        journal = _parse(text)
        assert "$" in journal.no_market_commodities


# ---------------------------------------------------------------------------
# define directive
# ---------------------------------------------------------------------------


class TestDefineDirective:
    def test_simple_define(self):
        text = "define rate=1.5\n"
        journal = _parse(text)
        assert journal.defines["rate"] == "1.5"

    def test_define_with_expression(self):
        text = "define hour=$25.00\n"
        journal = _parse(text)
        assert journal.defines["hour"] == "$25.00"

    def test_define_no_equals(self):
        text = "define something\n"
        journal = _parse(text)
        assert len(journal.defines) == 0

    def test_define_empty_var(self):
        text = "define =value\n"
        journal = _parse(text)
        assert len(journal.defines) == 0


# ---------------------------------------------------------------------------
# Combined directives
# ---------------------------------------------------------------------------


class TestCombinedDirectives:
    def test_multiple_directive_types(self):
        text = (
            "alias chk=Assets:Checking\n"
            "bucket Assets:Checking\n"
            "tag receipt\n"
            "payee Grocery Store\n"
            "N $\n"
            "define rate=1.5\n"
            "\n"
            "2024/01/15 Grocery Store\n"
            "  Expenses:Food  $50\n"
            "  chk\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert "chk" in journal.account_aliases
        assert journal.bucket.fullname == "Assets:Checking"
        assert "receipt" in journal.tag_declarations
        assert "Grocery Store" in journal.payee_declarations
        assert "$" in journal.no_market_commodities
        assert journal.defines["rate"] == "1.5"
        # Alias resolved in posting
        assert journal.xacts[0].posts[1].account.fullname == "Assets:Checking"

    def test_apply_account_with_alias(self):
        text = (
            "alias food=Expenses:Food\n"
            "apply account Personal\n"
            "\n"
            "2024/01/15 Groceries\n"
            "  Expenses:Dining  $50\n"
            "  Assets:Checking\n"
            "\n"
            "end apply account\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].posts[0].account.fullname == "Personal:Expenses:Dining"

    def test_apply_tag_and_apply_account_together(self):
        text = (
            "apply account Personal\n"
            "apply tag work\n"
            "\n"
            "2024/01/15 Lunch\n"
            "  Expenses:Food  $20\n"
            "  Assets:Checking\n"
            "\n"
            "end apply tag\n"
            "end apply account\n"
        )
        journal = _parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.has_tag("work")
        assert xact.posts[0].account.fullname == "Personal:Expenses:Food"

    def test_bang_prefix_alias(self):
        """Ledger allows ! prefix on directives."""
        text = "!alias chk=Assets:Checking\n"
        journal = _parse(text)
        assert "chk" in journal.account_aliases

    def test_at_prefix_bucket(self):
        """Ledger allows @ prefix on directives."""
        text = "@bucket Assets:Savings\n"
        journal = _parse(text)
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Savings"


# ---------------------------------------------------------------------------
# Directives mixed with transactions
# ---------------------------------------------------------------------------


class TestMixedDirectivesAndTransactions:
    def test_all_directives_together(self):
        text = """\
; Top-level comment
Y 2024
D $1,000.00

account Expenses:Food
    note Food expenses
    alias food

commodity EUR
    note Euro
    default

P 2024/01/01 EUR $1.10

comment
This is a multi-line comment.
end comment

2024/01/01 * Grocery Store
    Expenses:Food     $42.50
    Assets:Checking

2024/01/02 Coffee Shop
    Expenses:Dining   $4.50
    Assets:Checking
"""
        journal = _parse(text)

        # Year
        assert journal.default_year == 2024

        # Default commodity from D directive ($ from D $1,000.00)
        assert journal.commodity_pool.default_commodity is not None

        # Account directive
        acct = journal.find_account("Expenses:Food", auto_create=False)
        assert acct is not None
        assert acct.note == "Food expenses"
        assert "food" in journal.account_aliases

        # Commodity directive
        eur = journal.commodity_pool.find("EUR")
        assert eur is not None
        assert eur.note == "Euro"

        # Price
        assert len(journal.prices) == 1

        # Transactions
        assert len(journal.xacts) == 2


# ---------------------------------------------------------------------------
# Journal clear() resets new fields
# ---------------------------------------------------------------------------


class TestJournalClear:
    def test_clear_resets_new_fields(self):
        journal = Journal()
        journal.tag_declarations.append("test")
        journal.payee_declarations.append("Store")
        journal.apply_account_stack.append("Personal")
        journal.apply_tag_stack.append("work")
        journal.no_market_commodities.append("$")
        journal.defines["x"] = "1"

        journal.clear()

        assert journal.tag_declarations == []
        assert journal.payee_declarations == []
        assert journal.apply_account_stack == []
        assert journal.apply_tag_stack == []
        assert journal.no_market_commodities == []
        assert journal.defines == {}
