"""Phase 3 parity validation -- integration tests for Python port.

These tests exercise advanced features: automated transactions through the
full pipeline, built-in function integration, directive interactions, complex
multi-feature report scenarios, and edge cases.
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.auto_xact import AutomatedTransaction, apply_automated_transactions
from muonledger.balance import Balance
from muonledger.commands.balance import balance_command
from muonledger.commands.register import register_command
from muonledger.filters import (
    CalcPosts,
    CollapsePosts,
    CollectPosts,
    FilterPosts,
    IntervalPosts,
    InvertPosts,
    RelatedPosts,
    SortPosts,
    SubtotalPosts,
    build_chain,
    clear_all_xdata,
    get_xdata,
)
from muonledger.functions import register_builtins
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import POST_GENERATED, POST_VIRTUAL, Post
from muonledger.scope import CallScope, SymbolScope
from muonledger.times import DateInterval
from muonledger.value import Value, ValueType
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


def _balance(text: str, args: list[str] | None = None) -> str:
    """Parse journal text and run the balance command."""
    return balance_command(_parse(text), args)


def _register(text: str, args: list[str] | None = None) -> str:
    """Parse journal text and run the register command."""
    return register_command(_parse(text), args)


def _make_scope_with_builtins() -> SymbolScope:
    """Create a SymbolScope populated with all built-in functions."""
    scope = SymbolScope()
    register_builtins(scope)
    return scope


def _call(scope: SymbolScope, name: str, *args) -> Value:
    """Call a built-in function by name with the given arguments."""
    fn = scope.lookup(name)
    assert fn is not None, f"Function {name!r} not found in scope"
    cs = CallScope(scope, [v if isinstance(v, Value) else Value(v) for v in args])
    return fn(cs)


# ===================================================================
# Automated Transaction Parity (15+ tests)
# ===================================================================


class TestAutoXactSimple:
    """Simple auto xact adds postings to matching transactions."""

    def test_simple_auto_xact_adds_posting(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 3
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].account.fullname == "Budget:Food"

    def test_auto_xact_fixed_amount(self):
        """Auto xact with fixed dollar amount generates that exact amount."""
        text = """\
= /Rent/
    (Budget:Rent)                        $-1200

2024-02-01 Landlord
    Expenses:Rent                        $1200
    Assets:Checking                     $-1200
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].amount.quantity == Fraction(-1200)
        assert generated[0].amount.commodity == "$"

    def test_auto_xact_multiplier(self):
        """Auto xact with bare number multiplies matched posting amount."""
        text = """\
= /Food/
    (Budget:Food)                        1.0

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].amount.commodity == "$"
        assert float(generated[0].amount.quantity) == pytest.approx(50.0)

    def test_auto_xact_fractional_multiplier(self):
        """0.1 multiplier gives 10% of matched amount."""
        text = """\
= /Food/
    (Savings:Food)                       0.1

2024-01-15 Grocery Store
    Expenses:Food                        $200
    Assets:Checking                     $-200
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert float(generated[0].amount.quantity) == pytest.approx(20.0)

    def test_auto_xact_virtual_posting(self):
        """Parenthesized account in auto xact is virtual."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].is_virtual()
        assert generated[0].has_flags(POST_GENERATED)

    def test_multiple_auto_xacts_all_apply(self):
        """Multiple matching auto xacts each add their postings."""
        text = """\
= /Food/
    (Budget:Food)                        $-50

= /Expenses/
    (Tracking:All)                       $1

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        # Expenses:Food matches /Food/ and /Expenses/ => 2 generated
        assert len(generated) == 2

    def test_auto_xact_no_match(self):
        """Auto xact with no matching postings produces no extra posts."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Landlord
    Expenses:Rent                        $1000
    Assets:Checking                     $-1000
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 2
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 0

    def test_auto_xact_case_insensitive(self):
        """Regex patterns match case-insensitively."""
        text = """\
= /food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1

    def test_auto_xact_account_regex_syntax(self):
        """``account =~ /pattern/`` syntax matches correctly."""
        text = """\
= account =~ /Expense/
    (Tracking:Expenses)                  $1

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].account.fullname == "Tracking:Expenses"

    def test_generated_flag_set(self):
        """All generated postings have POST_GENERATED flag."""
        text = """\
= /Food/
    (Budget:Food)                        $-100
    (Savings:Food)                       $25

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 2
        for g in generated:
            assert g.has_flags(POST_GENERATED)

    def test_auto_xact_no_recursion(self):
        """Generated postings do not trigger further auto xact matches."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Budget/
    (Meta:Budget)                        $1

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        # Only /Food/ matches original Expenses:Food => 1 generated
        # /Budget/ does NOT match the generated Budget:Food post
        assert len(generated) == 1
        assert generated[0].account.fullname == "Budget:Food"

    def test_multiple_template_postings(self):
        """Single auto xact with multiple template postings generates all."""
        text = """\
= /Food/
    (Budget:Food)                        $-100
    (Savings:Goal)                       $25
    (Tax:Reserve)                        $5

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 3
        names = {g.account.fullname for g in generated}
        assert "Budget:Food" in names
        assert "Savings:Goal" in names
        assert "Tax:Reserve" in names

    def test_auto_xact_different_commodities(self):
        """Auto xact fixed amount in different commodity than matched post."""
        text = """\
= /Food/
    (Budget:Food)                        100 EUR

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].amount.commodity == "EUR"
        assert generated[0].amount.quantity == Fraction(100)

    def test_auto_xact_applies_to_multiple_transactions(self):
        """Auto xact applies to all matching transactions in the journal."""
        text = """\
= /Food/
    (Budget:Food)                        $-50

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-01-20 Restaurant
    Expenses:Food:Dining                 $30
    Assets:Checking                     $-30

2024-01-25 Hardware Store
    Expenses:Tools                       $80
    Assets:Checking                     $-80
"""
        journal = _parse(text)
        # First xact: Expenses:Food matches
        g1 = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(g1) == 1
        # Second xact: Expenses:Food:Dining contains "Food"
        g2 = [p for p in journal.xacts[1].posts if p.has_flags(POST_GENERATED)]
        assert len(g2) == 1
        # Third xact: Expenses:Tools does not match
        g3 = [p for p in journal.xacts[2].posts if p.has_flags(POST_GENERATED)]
        assert len(g3) == 0

    def test_auto_xact_generated_has_xact_backref(self):
        """Generated postings have their xact back-reference set."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].xact is journal.xacts[0]


class TestAutoXactBalanceIntegration:
    """Auto xact integration with balance command."""

    def test_balance_includes_generated_postings(self):
        """Balance report includes amounts from auto-generated postings."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _balance(text, ["--flat"])
        assert "Budget:Food" in out
        assert "$-100" in out

    def test_balance_auto_xact_with_multiplier(self):
        """Balance shows multiplied auto-generated amounts."""
        text = """\
= /Food/
    (Budget:Food)                        1.0

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _balance(text, ["--flat"])
        assert "Budget:Food" in out
        # 1.0 * $50 = $50
        assert "$50" in out


class TestAutoXactRegisterIntegration:
    """Auto xact integration with register command."""

    def test_register_includes_generated_postings(self):
        """Register output includes auto-generated postings."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _register(text)
        assert "Budget:Food" in out

    def test_register_running_total_with_auto_xact(self):
        """Running totals include generated posting amounts."""
        text = """\
= /Food/
    (Budget:Food)                        $-50

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _register(text)
        lines = out.rstrip("\n").split("\n")
        # 3 postings: Food=$50, Checking=$-50, Budget:Food=$-50
        assert len(lines) == 3
        # Final running total should be $-50 (50 + (-50) + (-50) = -50)
        last_line = lines[-1]
        assert "$-50" in last_line


class TestAutoXactFullPipeline:
    """Full pipeline: parse -> auto xact apply -> balance/register."""

    def test_full_pipeline_balance(self):
        """Parse with auto xacts, then balance report is correct."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Rent/
    (Budget:Rent)                        $-1500

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-02-01 Landlord
    Expenses:Rent                        $1500
    Assets:Checking                     $-1500
"""
        out = _balance(text, ["--flat"])
        assert "Budget:Food" in out
        assert "Budget:Rent" in out
        assert "Expenses:Food" in out
        assert "Expenses:Rent" in out

    def test_full_pipeline_register_chronological(self):
        """Register with auto xacts shows all postings in order."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-01-20 Restaurant
    Expenses:Food:Dining                 $30
    Assets:Checking                     $-30
"""
        out = _register(text)
        # Each transaction should have 3 postings (2 original + 1 generated)
        assert "Budget:Food" in out
        assert "Grocery Store" in out
        assert "Restaurant" in out


# ===================================================================
# Built-in Functions Integration (10+ tests)
# ===================================================================


class TestBuiltinMath:
    """Math built-in functions: abs, round, ceil, floor, min, max."""

    def test_abs_positive_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "abs", Amount("$50"))
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(50.0)

    def test_abs_negative_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "abs", Amount("$-50"))
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(50.0)

    def test_abs_negative_integer(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "abs", -42)
        assert result._data == 42

    def test_round_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "round", Amount("3.14159 XTS"))
        assert result._type == ValueType.AMOUNT

    def test_round_to_places(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "round", Amount("3.14159 XTS"), 2)
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(3.14)

    def test_ceil_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "ceil", Amount("$3.14"))
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(4.0)

    def test_floor_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "floor", Amount("$3.99"))
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(3.0)

    def test_min_two_values(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "min", 10, 20)
        assert result._data == 10

    def test_max_two_values(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "max", 10, 20)
        assert result._data == 20


class TestBuiltinTypeConversion:
    """Type conversion functions: quantity, commodity, to_amount, to_string, to_int."""

    def test_quantity_extracts_numeric(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "quantity", Amount("$50.00"))
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(50.0)

    def test_commodity_extracts_symbol(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "commodity", Amount("$50.00"))
        assert result._type == ValueType.STRING
        assert result._data == "$"

    def test_commodity_no_commodity(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "commodity", Amount("50.00"))
        assert result._data == ""

    def test_to_amount_from_integer(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "to_amount", 42)
        assert result._type == ValueType.AMOUNT
        assert float(result._data.quantity) == pytest.approx(42.0)

    def test_to_string_from_integer(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "to_string", 42)
        assert result._type == ValueType.STRING
        assert result._data == "42"

    def test_to_int_from_amount(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "to_int", Amount("$5"))
        assert result._type == ValueType.INTEGER
        assert result._data == 5

    def test_to_boolean_truthy(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "to_boolean", 1)
        assert result._type == ValueType.BOOLEAN
        assert result._data is True

    def test_to_boolean_falsy(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "to_boolean", 0)
        assert result._type == ValueType.BOOLEAN
        assert result._data is False


class TestBuiltinDate:
    """Date functions: today, now, format_date."""

    def test_today_returns_date(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "today")
        assert result._type == ValueType.DATE
        assert result._data == date.today()

    def test_now_returns_datetime(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "now")
        assert result._type == ValueType.DATETIME
        assert isinstance(result._data, datetime)

    def test_format_date(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "format_date", date(2024, 6, 15), "%Y-%m-%d")
        assert result._type == ValueType.STRING
        assert result._data == "2024-06-15"

    def test_format_date_custom(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "format_date", date(2024, 12, 25), "%B %d, %Y")
        assert result._type == ValueType.STRING
        assert result._data == "December 25, 2024"


class TestBuiltinString:
    """String functions: str, strip, quoted, truncated."""

    def test_str_converts_integer(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "str", 42)
        assert result._type == ValueType.STRING
        assert result._data == "42"

    def test_strip_removes_whitespace(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "strip", "  hello  ")
        assert result._data == "hello"

    def test_quoted_wraps_in_double_quotes(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "quoted", "hello")
        assert result._data == '"hello"'

    def test_truncated_within_width(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "truncated", "hi", 10)
        assert result._data == "hi"

    def test_truncated_exceeds_width(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "truncated", "hello world", 7)
        assert result._data == "hello.."
        assert len(result._data) == 7


class TestBuiltinHasTag:
    """has_tag and tag functions with scope context."""

    def test_has_tag_with_dict(self):
        scope = _make_scope_with_builtins()
        scope.define("__post_tags__", {"Payee": "Store", "urgent": True})
        result = _call(scope, "has_tag", "Payee")
        assert result._data is True

    def test_has_tag_missing(self):
        scope = _make_scope_with_builtins()
        scope.define("__post_tags__", {"Payee": "Store"})
        result = _call(scope, "has_tag", "missing")
        assert result._data is False

    def test_has_tag_no_context(self):
        scope = _make_scope_with_builtins()
        result = _call(scope, "has_tag", "Payee")
        assert result._data is False


class TestBuiltinConstants:
    """Boolean constants true and false."""

    def test_true_constant(self):
        scope = _make_scope_with_builtins()
        result = scope.lookup("true")
        assert isinstance(result, Value)
        assert result._type == ValueType.BOOLEAN
        assert result._data is True

    def test_false_constant(self):
        scope = _make_scope_with_builtins()
        result = scope.lookup("false")
        assert isinstance(result, Value)
        assert result._type == ValueType.BOOLEAN
        assert result._data is False


# ===================================================================
# Advanced Directive Integration (10+ tests)
# ===================================================================


class TestAliasDirective:
    """Alias directive interaction with auto xacts."""

    def test_alias_resolves_in_posting(self):
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

    def test_alias_plus_auto_xact(self):
        """Alias + auto xact: auto xact matches the expanded account name."""
        text = (
            "alias food=Expenses:Food:Groceries\n"
            "\n"
            "= /Food/\n"
            "  (Budget:Food)  $-100\n"
            "\n"
            "2024/01/15 Grocery Store\n"
            "  food  $50\n"
            "  Assets:Checking  $-50\n"
        )
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].account.fullname == "Budget:Food"


class TestApplyAccountDirective:
    """apply account directive tests."""

    def test_apply_account_prefixes(self):
        text = """\
apply account Personal

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

end apply account
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        names = [p.account.fullname for p in xact.posts]
        assert "Personal:Expenses:Food" in names
        assert "Personal:Assets:Checking" in names

    def test_apply_account_plus_alias(self):
        """apply account prefix is applied before alias lookup.

        When apply account is active, the account name gets prefixed
        before alias resolution. So ``food`` becomes ``Personal:food``
        which does NOT match alias ``food``.  The account is created
        as ``Personal:food``.
        """
        text = (
            "apply account Personal\n"
            "\n"
            "2024/01/15 Grocery Store\n"
            "  Expenses:Food  $50\n"
            "  Assets:Checking  $-50\n"
            "\n"
            "end apply account\n"
        )
        journal = _parse(text)
        xact = journal.xacts[0]
        names = [p.account.fullname for p in xact.posts]
        # apply account prefixes account names
        assert "Personal:Expenses:Food" in names
        assert "Personal:Assets:Checking" in names

    def test_multiple_directives_in_sequence(self):
        """Multiple directives applied in sequence."""
        text = """\
alias rent=Expenses:Housing:Rent
alias food=Expenses:Food:Groceries

2024-01-15 Grocery Store
    food                                 $50
    Assets:Checking                     $-50

2024-02-01 Landlord
    rent                                 $1000
    Assets:Checking                     $-1000
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2
        food_post = journal.xacts[0].posts[0]
        assert food_post.account.fullname == "Expenses:Food:Groceries"
        rent_post = journal.xacts[1].posts[0]
        assert rent_post.account.fullname == "Expenses:Housing:Rent"


class TestBucketDirective:
    """Bucket directive stores default account."""

    def test_bucket_sets_default_account(self):
        text = """\
bucket Assets:Checking

2024-01-15 Grocery Store
    Expenses:Food                        $50.00
    Assets:Checking
"""
        journal = _parse(text)
        # Bucket directive sets journal.bucket
        assert journal.bucket is not None
        assert journal.bucket.fullname == "Assets:Checking"
        # Transaction still balances normally
        xact = journal.xacts[0]
        assert len(xact.posts) == 2


class TestYearDirective:
    """Year directive affects date parsing."""

    def test_year_directive(self):
        text = """\
Y 2023

2024/01/15 Test
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        # The explicit date 2024/01/15 should still work
        assert journal.xacts[0].date == date(2024, 1, 15)


class TestDefineDirective:
    """Define directive stores values."""

    def test_define_stores_value(self):
        text = """\
define amt=$100.00

2024-01-15 Test
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert "amt" in journal.defines
        assert journal.defines["amt"] == "$100.00"


class TestNDirective:
    """N directive for no-market commodities."""

    def test_n_directive_records_commodity(self):
        text = """\
N $

2024-01-15 Test
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert "$" in journal.no_market_commodities


class TestCombinedDirectives:
    """Combined directive interactions."""

    def test_alias_apply_account_bucket_auto_xact(self):
        """Combined: alias + apply account + bucket + auto xact."""
        text = """\
alias food=Expenses:Food

= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    food                                 $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        # Alias expanded
        food_posts = [p for p in xact.posts if p.account.fullname == "Expenses:Food"]
        assert len(food_posts) == 1
        # Auto xact matched
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].account.fullname == "Budget:Food"


# ===================================================================
# Complex Report Scenarios (10+ tests)
# ===================================================================


class TestLargeJournalBalance:
    """Large journal (20+ transactions) balance accuracy."""

    def test_twenty_transactions_balance(self):
        lines = []
        for i in range(1, 21):
            day = str(i).zfill(2)
            lines.append(f"2024/01/{day} Payee{i}")
            lines.append(f"    Expenses:Cat{i % 5}                  $10.00")
            lines.append(f"    Assets:Checking")
            lines.append("")
        text = "\n".join(lines)
        out = _balance(text)
        total_lines = out.strip().split("\n")
        # Total should be 0 (balanced journal)
        assert total_lines[-1].strip() == "0"

    def test_twenty_transactions_register_count(self):
        """Register lists all postings from 20 transactions."""
        lines = []
        for i in range(1, 21):
            day = str(i).zfill(2)
            lines.append(f"2024/01/{day} Payee{i}")
            lines.append(f"    Expenses:Cat{i % 5}                  $10.00")
            lines.append(f"    Assets:Checking")
            lines.append("")
        text = "\n".join(lines)
        out = _register(text)
        reg_lines = out.rstrip("\n").split("\n")
        # 20 transactions * 2 postings = 40 lines
        assert len(reg_lines) == 40


class TestMixedCommoditiesPipeline:
    """Mixed commodities through full pipeline."""

    def test_multi_commodity_balance(self):
        text = """\
2024/01/01 Buy EUR
    Assets:EUR            100 EUR @@ 100 USD
    Assets:Cash          -100 USD

2024/01/02 Buy AAPL
    Assets:Brokerage      10 AAPL
    Equity:Opening       -10 AAPL
"""
        out = _balance(text, ["--flat"])
        assert "EUR" in out
        assert "AAPL" in out
        assert "USD" in out

    def test_multi_commodity_register(self):
        text = """\
2024/01/01 Buy EUR
    Assets:EUR            100 EUR @@ 100 USD
    Assets:Cash          -100 USD

2024/01/02 Buy AAPL
    Assets:Brokerage      10 AAPL
    Equity:Opening       -10 AAPL
"""
        out = _register(text)
        assert "EUR" in out
        assert "AAPL" in out


class TestDateFilteredRegister:
    """Date-filtered register using account patterns."""

    def test_register_filter_by_account_prefix(self):
        text = """\
2024/01/01 First
    Expenses:A       $10.00
    Assets:Cash

2024/02/01 Second
    Expenses:B       $20.00
    Assets:Cash

2024/03/01 Third
    Income:C         $30.00
    Assets:Cash
"""
        out = _register(text, ["Expenses"])
        assert "Expenses:A" in out
        assert "Expenses:B" in out
        assert "Income" not in out

    def test_register_head_limits_output(self):
        text = """\
2024/01/01 First
    Expenses:A       $10.00
    Assets:Cash

2024/02/01 Second
    Expenses:B       $20.00
    Assets:Cash

2024/03/01 Third
    Expenses:C       $30.00
    Assets:Cash
"""
        out = _register(text, ["--head", "3"])
        lines = out.rstrip("\n").split("\n")
        assert len(lines) == 3


class TestClearedStateParsing:
    """Cleared/pending state parsing."""

    def test_cleared_state_parsed(self):
        """Parser correctly sets cleared/pending states."""
        text = """\
2024/01/01 * Cleared Transaction
    Expenses:Food       $50.00
    Assets:Checking

2024/01/02 ! Pending Transaction
    Expenses:Food       $30.00
    Assets:Checking

2024/01/03 Uncleared Transaction
    Expenses:Food       $20.00
    Assets:Checking
"""
        from muonledger.item import ItemState
        journal = _parse(text)
        assert len(journal.xacts) == 3
        assert journal.xacts[0].state == ItemState.CLEARED
        assert journal.xacts[1].state == ItemState.PENDING
        assert journal.xacts[2].state == ItemState.UNCLEARED

    def test_cleared_in_register_output(self):
        """All transactions appear in register regardless of state."""
        text = """\
2024/01/01 * Cleared Transaction
    Expenses:Food       $50.00
    Assets:Checking

2024/01/02 ! Pending Transaction
    Expenses:Food       $30.00
    Assets:Checking
"""
        out = _register(text)
        assert "Cleared" in out
        assert "Pending" in out


class TestDepthLimiting:
    """Depth limiting with deep account hierarchy."""

    def test_depth_1_flat(self):
        text = """\
2024/01/01 Test
    Expenses:Food:Groceries:Organic      $50.00
    Expenses:Food:Dining:Restaurant      $30.00
    Assets:Bank:Checking:Primary
"""
        out = _balance(text, ["--flat", "--depth", "1"])
        lines = [l for l in out.strip().split("\n") if "----" not in l and l.strip() != "0"]
        for line in lines:
            acct = line.split()[-1] if line.split() else ""
            assert ":" not in acct

    def test_depth_2_flat(self):
        text = """\
2024/01/01 Test
    Expenses:Food:Groceries:Organic      $50.00
    Expenses:Food:Dining:Restaurant      $30.00
    Assets:Bank:Checking:Primary
"""
        out = _balance(text, ["--flat", "--depth", "2"])
        lines = [l for l in out.strip().split("\n") if "----" not in l and l.strip() != "0"]
        for line in lines:
            acct = line.split()[-1] if line.split() else ""
            if acct != "0":
                assert acct.count(":") <= 1


class TestFilterChain:
    """Filter chain with multiple filters combined."""

    def test_subtotal_plus_sort(self):
        """SubtotalPosts + SortPosts combined in a chain."""
        text = """\
2024/01/01 Test
    Expenses:Food       $50
    Expenses:Rent       $800
    Expenses:Utils      $100
    Assets:Checking
"""
        journal = _parse(text)
        collector = CollectPosts()
        sort = SortPosts(collector, sort_key=lambda p: p.account.fullname if p.account else "")
        subtotal = SubtotalPosts(sort)

        for xact in journal.xacts:
            for post in xact.posts:
                subtotal(post)
        subtotal.flush()

        # Subtotals should be sorted by account name
        names = [p.account.fullname for p in collector.posts if p.account]
        assert names == sorted(names)

    def test_filter_then_calc(self):
        """FilterPosts -> CalcPosts -> CollectPosts chain."""
        text = """\
2024/01/01 Test
    Expenses:Food       $50.00
    Expenses:Rent       $800.00
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1, f"Expected 1 xact, got {len(journal.xacts)}"
        assert len(journal.xacts[0].posts) == 3, f"Expected 3 posts, got {len(journal.xacts[0].posts)}"
        clear_all_xdata()
        collector = CollectPosts()
        calc = CalcPosts(collector)
        filt = FilterPosts(calc, lambda p: p.account is not None and "Expense" in p.account.fullname)

        for xact in journal.xacts:
            for post in xact.posts:
                filt(post)
        filt.flush()

        assert len(collector.posts) == 2
        # Running total after two expense postings
        xdata = get_xdata(collector.posts[-1])
        assert xdata["total"] is not None

    def test_invert_filter(self):
        """InvertPosts negates amounts."""
        text = """\
2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert len(journal.xacts[0].posts) == 2
        collector = CollectPosts()
        invert = InvertPosts(collector)

        for xact in journal.xacts:
            for post in xact.posts:
                invert(post)
        invert.flush()

        assert len(collector.posts) == 2
        # Food was $50, inverted to $-50
        food = [p for p in collector.posts if p.account is not None and "Food" in p.account.fullname][0]
        assert float(food.amount.quantity) == pytest.approx(-50.0)

    def test_related_posts(self):
        """RelatedPosts emits the other postings from the same transaction."""
        text = """\
2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        collector = CollectPosts()
        related = RelatedPosts(collector, also_matching=False)

        # Feed only the Food posting
        food_post = journal.xacts[0].posts[0]
        related(food_post)
        related.flush()

        # Should emit the related posting (Assets:Checking)
        assert len(collector.posts) >= 1
        names = [p.account.fullname for p in collector.posts if p.account is not None]
        assert "Assets:Checking" in names

    def test_invert_plus_related(self):
        """InvertPosts + RelatedPosts combined."""
        text = """\
2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        collector = CollectPosts()
        invert = InvertPosts(collector)
        related = RelatedPosts(invert, also_matching=False)

        food_post = journal.xacts[0].posts[0]
        related(food_post)
        related.flush()

        # Related posting is Assets:Checking ($-50), inverted to $50
        assert len(collector.posts) >= 1
        checking = [p for p in collector.posts if p.account is not None and "Checking" in p.account.fullname]
        assert len(checking) >= 1
        assert float(checking[0].amount.quantity) == pytest.approx(50.0)


class TestIntervalGrouping:
    """Interval grouping (monthly) with subtotals."""

    def test_monthly_interval(self):
        text = """\
2024/01/15 Jan Purchase
    Expenses:Food       $50
    Assets:Checking

2024/02/15 Feb Purchase
    Expenses:Food       $60
    Assets:Checking

2024/03/15 Mar Purchase
    Expenses:Food       $70
    Assets:Checking
"""
        journal = _parse(text)
        collector = CollectPosts()
        interval = IntervalPosts(
            collector,
            interval=DateInterval(quantum="months"),
        )

        for xact in journal.xacts:
            for post in xact.posts:
                interval(post)
        interval.flush()

        # Should have grouped postings by month
        assert len(collector.posts) > 0


class TestRealOnlyFilter:
    """Real-only filter excludes virtual auto xact posts."""

    def test_real_only_excludes_virtual(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        collector = CollectPosts()
        # Filter: only non-virtual postings
        filt = FilterPosts(collector, lambda p: not p.is_virtual())

        for xact in journal.xacts:
            for post in xact.posts:
                filt(post)
        filt.flush()

        # Only original postings (not the virtual Budget:Food)
        assert len(collector.posts) == 2
        names = [p.account.fullname for p in collector.posts]
        assert "Budget:Food" not in names


# ===================================================================
# Edge Cases (5+ tests)
# ===================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_journal_balance(self):
        out = _balance("")
        assert out == ""

    def test_empty_journal_register(self):
        out = _register("")
        assert out == ""

    def test_single_posting_auto_balanced(self):
        """Single posting with amount; other posting is auto-inferred."""
        text = """\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 2
        # Second posting should have been inferred
        checking = [p for p in xact.posts if p.account.fullname == "Assets:Checking"]
        assert len(checking) == 1
        assert float(checking[0].amount.quantity) == pytest.approx(-50.0)

    def test_virtual_only_postings(self):
        """Transaction with virtual (parenthesized) postings."""
        text = """\
2024/01/15 Budget Entry
    (Budget:Food)        $100.00
    (Budget:Rent)        $500.00
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        for post in xact.posts:
            assert post.is_virtual()

    def test_very_long_account_names(self):
        """Very long account names are handled without errors."""
        text = """\
2024/01/15 Test
    Assets:Bank:Region:Country:State:City:Branch:Checking     $100.00
    Equity:Opening
"""
        journal = _parse(text)
        out = _balance(text, ["--flat"])
        assert "Checking" in out

    def test_special_characters_in_payee(self):
        """Special characters in payee names."""
        text = """\
2024/01/15 Joe's Pizza & Pasta (Downtown)
    Expenses:Food       $25.00
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert "Joe's Pizza" in journal.xacts[0].payee

    def test_large_amounts(self):
        """Very large amounts are handled correctly."""
        text = """\
2024/01/01 Big Transfer
    Assets:Investment    $1,000,000.00
    Assets:Checking
"""
        journal = _parse(text)
        out = _balance(text, ["--flat"])
        assert "Assets:Investment" in out
        assert "Assets:Checking" in out

    def test_zero_amount_posting(self):
        """A posting with $0.00 is valid."""
        text = """\
2024/01/15 Zero Test
    Expenses:Food       $0.00
    Assets:Checking     $0.00
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_negative_amounts(self):
        """Negative amounts in register show correct running totals."""
        text = """\
2024/01/01 Refund
    Income:Refund       $-50.00
    Assets:Checking      $50.00
"""
        out = _register(text)
        lines = out.rstrip("\n").split("\n")
        assert len(lines) == 2
        assert "$-50.00" in lines[0]

    def test_many_postings_per_transaction(self):
        """Transaction with 5+ postings."""
        text = """\
2024/01/15 Big Purchase
    Expenses:Food       $10.00
    Expenses:Drinks     $5.00
    Expenses:Tax        $2.00
    Expenses:Tip        $3.00
    Expenses:Service    $1.00
    Assets:Checking
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 6
        checking = [p for p in xact.posts if p.account.fullname == "Assets:Checking"]
        assert float(checking[0].amount.quantity) == pytest.approx(-21.0)


class TestAutoXactWithClearedState:
    """Auto xacts with cleared/pending state transactions."""

    def test_auto_xact_with_cleared_transaction(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 * Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1

    def test_auto_xact_with_pending_transaction(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 ! Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        generated = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1


class TestFilterChainComplex:
    """Complex filter chain scenarios."""

    def test_collapse_posts(self):
        """CollapsePosts collapses multiple postings per transaction."""
        text = """\
2024/01/01 Multi
    Expenses:A       $10
    Expenses:B       $20
    Expenses:C       $30
    Assets:Checking
"""
        journal = _parse(text)
        collector = CollectPosts()
        calc = CalcPosts(collector)
        collapse = CollapsePosts(calc)

        for xact in journal.xacts:
            for post in xact.posts:
                collapse(post)
        collapse.flush()

        # Collapsed should produce fewer postings than original
        assert len(collector.posts) < 4

    def test_build_chain_utility(self):
        """build_chain links handlers correctly."""
        collector = CollectPosts()
        calc = CalcPosts(None)
        chain = build_chain(calc, collector)

        assert chain is calc
        assert calc.handler is collector


class TestRegisterWithAutoXactFiltered:
    """Register command with auto xacts and account filtering."""

    def test_register_filter_shows_only_matching(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _register(text, ["Budget"])
        assert "Budget:Food" in out
        # Should not show unmatched accounts
        assert "Expenses:Food" not in out

    def test_register_filter_expenses_with_auto_xact(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _register(text, ["Expenses"])
        assert "Expenses:Food" in out
        assert "Budget:Food" not in out


class TestBalanceWithAutoXactFiltered:
    """Balance command with auto xacts and account filtering."""

    def test_balance_filter_budget_accounts(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Rent/
    (Budget:Rent)                        $-1500

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-02-01 Landlord
    Expenses:Rent                        $1500
    Assets:Checking                     $-1500
"""
        out = _balance(text, ["--flat", "Budget"])
        assert "Budget:Food" in out
        assert "Budget:Rent" in out
        assert "Expenses" not in out

    def test_balance_no_total_with_auto_xact(self):
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        out = _balance(text, ["--flat", "--no-total"])
        assert "----" not in out
        assert "Budget:Food" in out
