"""Tests for the 39 built-in functions in muonledger.functions."""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.functions import register_builtins
from muonledger.scope import CallScope, SymbolScope
from muonledger.value import Value, ValueType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scope() -> SymbolScope:
    """Return a SymbolScope with all builtins registered."""
    scope = SymbolScope()
    register_builtins(scope)
    return scope


def _call(scope: SymbolScope, name: str, *args) -> Value:
    """Look up *name* in *scope* and call it with the given arguments."""
    fn = scope.lookup(name)
    assert fn is not None, f"Built-in '{name}' not found in scope"
    if isinstance(fn, Value):
        return fn  # constant (true/false)
    cs = CallScope(scope, [Value(a) if not isinstance(a, Value) else a for a in args])
    return fn(cs)


# ---------------------------------------------------------------------------
# Math functions
# ---------------------------------------------------------------------------

class TestMathFunctions:
    def test_abs_positive_int(self):
        scope = _make_scope()
        result = _call(scope, "abs", 42)
        assert result == Value(42)

    def test_abs_negative_int(self):
        scope = _make_scope()
        result = _call(scope, "abs", -42)
        assert result == Value(42)

    def test_abs_positive_amount(self):
        scope = _make_scope()
        result = _call(scope, "abs", Amount("10.50"))
        assert result == Value(Amount("10.50"))

    def test_abs_negative_amount(self):
        scope = _make_scope()
        result = _call(scope, "abs", Amount("-10.50"))
        assert result == Value(Amount("10.50"))

    def test_round_amount(self):
        scope = _make_scope()
        amt = Amount("3.14159")
        result = _call(scope, "round", amt)
        # rounded() clears keep_precision flag
        assert result._type == ValueType.AMOUNT

    def test_round_with_places(self):
        scope = _make_scope()
        amt = Amount("3.14159")
        result = _call(scope, "round", amt, 2)
        assert result._type == ValueType.AMOUNT
        assert "3.14" in str(result)

    def test_roundto_alias(self):
        scope = _make_scope()
        amt = Amount("3.14159")
        result = _call(scope, "roundto", amt, 2)
        assert "3.14" in str(result)

    def test_round_integer(self):
        scope = _make_scope()
        result = _call(scope, "round", 42)
        assert result == Value(42)

    def test_ceil_amount(self):
        scope = _make_scope()
        amt = Amount("3.14")
        result = _call(scope, "ceil", amt)
        assert result._type == ValueType.AMOUNT
        expected = amt.ceilinged()
        assert result._data.quantity == expected.quantity

    def test_ceil_integer(self):
        scope = _make_scope()
        result = _call(scope, "ceil", 5)
        assert result == Value(5)

    def test_floor_amount(self):
        scope = _make_scope()
        amt = Amount("3.99")
        result = _call(scope, "floor", amt)
        expected = amt.floored()
        assert result._data.quantity == expected.quantity

    def test_floor_integer(self):
        scope = _make_scope()
        result = _call(scope, "floor", 5)
        assert result == Value(5)

    def test_min_integers(self):
        scope = _make_scope()
        result = _call(scope, "min", 3, 7)
        assert result == Value(3)

    def test_min_amounts(self):
        scope = _make_scope()
        result = _call(scope, "min", Amount("10.00"), Amount("5.00"))
        assert result == Value(Amount("5.00"))

    def test_min_second_smaller(self):
        scope = _make_scope()
        result = _call(scope, "min", 7, 3)
        assert result == Value(3)

    def test_max_integers(self):
        scope = _make_scope()
        result = _call(scope, "max", 3, 7)
        assert result == Value(7)

    def test_max_amounts(self):
        scope = _make_scope()
        result = _call(scope, "max", Amount("10.00"), Amount("5.00"))
        assert result == Value(Amount("10.00"))

    def test_max_first_larger(self):
        scope = _make_scope()
        result = _call(scope, "max", 7, 3)
        assert result == Value(7)


# ---------------------------------------------------------------------------
# String functions
# ---------------------------------------------------------------------------

class TestStringFunctions:
    def test_str_from_int(self):
        scope = _make_scope()
        result = _call(scope, "str", 42)
        assert result == Value("42")

    def test_str_from_bool(self):
        scope = _make_scope()
        result = _call(scope, "str", True)
        assert result == Value("true")

    def test_str_from_string(self):
        scope = _make_scope()
        result = _call(scope, "str", "hello")
        assert result == Value("hello")

    def test_strip_whitespace(self):
        scope = _make_scope()
        result = _call(scope, "strip", "  hello  ")
        assert result == Value("hello")

    def test_strip_no_whitespace(self):
        scope = _make_scope()
        result = _call(scope, "strip", "hello")
        assert result == Value("hello")

    def test_trim_alias(self):
        scope = _make_scope()
        result = _call(scope, "trim", "  hello  ")
        assert result == Value("hello")

    def test_join_sequence(self):
        scope = _make_scope()
        seq = Value([Value("a"), Value("b"), Value("c")])
        result = _call(scope, "join", seq, ", ")
        assert result == Value("a, b, c")

    def test_join_non_sequence(self):
        scope = _make_scope()
        result = _call(scope, "join", "hello", ", ")
        assert result == Value("hello")

    def test_join_no_separator(self):
        scope = _make_scope()
        seq = Value([Value("x"), Value("y")])
        result = _call(scope, "join", seq)
        assert result == Value("xy")

    def test_quoted(self):
        scope = _make_scope()
        result = _call(scope, "quoted", "hello")
        assert result == Value('"hello"')

    def test_justify_left(self):
        scope = _make_scope()
        result = _call(scope, "justify", "hi", 10)
        assert result == Value("hi        ")
        assert len(result._data) == 10

    def test_justify_right(self):
        scope = _make_scope()
        result = _call(scope, "justify", "hi", 10, True)
        assert result == Value("        hi")
        assert len(result._data) == 10

    def test_truncated_long_string(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hello World", 8)
        assert result == Value("Hello ..")

    def test_truncated_short_string(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hi", 10)
        assert result == Value("Hi")

    def test_truncated_zero_width(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hello", 0)
        assert result == Value("")

    def test_truncated_width_2(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hello", 2)
        assert result == Value("..")

    def test_truncated_width_1(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hello", 1)
        assert result == Value(".")

    def test_format_int(self):
        scope = _make_scope()
        result = _call(scope, "format", "%05d", 42)
        assert result == Value("00042")

    def test_format_amount(self):
        scope = _make_scope()
        result = _call(scope, "format", "%.2f", Amount("3.14159"))
        assert result == Value("3.14")


# ---------------------------------------------------------------------------
# Date functions
# ---------------------------------------------------------------------------

class TestDateFunctions:
    def test_now_returns_datetime(self):
        scope = _make_scope()
        result = _call(scope, "now")
        assert result._type == ValueType.DATETIME
        assert isinstance(result._data, datetime)

    def test_today_returns_date(self):
        scope = _make_scope()
        result = _call(scope, "today")
        assert result._type == ValueType.DATE
        assert isinstance(result._data, date)
        assert result._data == date.today()

    def test_date_from_datetime(self):
        scope = _make_scope()
        dt = datetime(2024, 6, 15, 10, 30, 0)
        result = _call(scope, "date", dt)
        assert result._type == ValueType.DATE
        assert result._data == date(2024, 6, 15)

    def test_date_from_date(self):
        scope = _make_scope()
        d = date(2024, 6, 15)
        result = _call(scope, "date", d)
        assert result._type == ValueType.DATE
        assert result._data == date(2024, 6, 15)

    def test_date_from_string(self):
        scope = _make_scope()
        result = _call(scope, "date", "2024-06-15")
        assert result._type == ValueType.DATE
        assert result._data == date(2024, 6, 15)

    def test_date_from_string_slash(self):
        scope = _make_scope()
        result = _call(scope, "date", "2024/06/15")
        assert result._type == ValueType.DATE
        assert result._data == date(2024, 6, 15)

    def test_format_date(self):
        scope = _make_scope()
        d = date(2024, 6, 15)
        result = _call(scope, "format_date", d, "%Y/%m/%d")
        assert result == Value("2024/06/15")

    def test_format_date_custom(self):
        scope = _make_scope()
        d = date(2024, 1, 5)
        result = _call(scope, "format_date", d, "%d %b %Y")
        assert result == Value("05 Jan 2024")


# ---------------------------------------------------------------------------
# Type conversion / query functions
# ---------------------------------------------------------------------------

class TestTypeConversionFunctions:
    def test_int_from_int(self):
        scope = _make_scope()
        result = _call(scope, "int", 42)
        assert result == Value(42)

    def test_int_from_amount(self):
        scope = _make_scope()
        result = _call(scope, "int", Amount("3.99"))
        assert result._type == ValueType.INTEGER
        # Amount.__int__ rounds (half away from zero), so 3.99 -> 4
        assert result._data == 4

    def test_int_from_bool(self):
        scope = _make_scope()
        result = _call(scope, "int", True)
        assert result == Value(1)

    def test_quantity_from_amount(self):
        scope = _make_scope()
        amt = Amount("$10.50")
        result = _call(scope, "quantity", amt)
        assert result._type == ValueType.AMOUNT
        # quantity should strip commodity
        assert not result._data.has_commodity()

    def test_quantity_from_integer(self):
        scope = _make_scope()
        result = _call(scope, "quantity", 42)
        assert result == Value(42)

    def test_commodity_from_amount(self):
        scope = _make_scope()
        amt = Amount("$10.50")
        result = _call(scope, "commodity", amt)
        assert result._type == ValueType.STRING
        assert result._data == "$"

    def test_commodity_no_commodity(self):
        scope = _make_scope()
        amt = Amount("10.50")
        result = _call(scope, "commodity", amt)
        assert result == Value("")

    def test_commodity_from_non_amount(self):
        scope = _make_scope()
        result = _call(scope, "commodity", 42)
        assert result == Value("")

    def test_is_seq_true(self):
        scope = _make_scope()
        seq = Value([Value(1), Value(2)])
        result = _call(scope, "is_seq", seq)
        assert result == Value(True)

    def test_is_seq_false(self):
        scope = _make_scope()
        result = _call(scope, "is_seq", 42)
        assert result == Value(False)

    def test_to_amount(self):
        scope = _make_scope()
        result = _call(scope, "to_amount", 42)
        assert result._type == ValueType.AMOUNT

    def test_to_balance(self):
        scope = _make_scope()
        result = _call(scope, "to_balance", Amount("10.00"))
        assert result._type == ValueType.BALANCE

    def test_to_string(self):
        scope = _make_scope()
        result = _call(scope, "to_string", 42)
        assert result == Value("42")

    def test_to_int(self):
        scope = _make_scope()
        result = _call(scope, "to_int", Amount("5.00"))
        assert result._type == ValueType.INTEGER
        assert result._data == 5

    def test_to_date(self):
        scope = _make_scope()
        dt = datetime(2024, 6, 15, 10, 30)
        result = _call(scope, "to_date", dt)
        assert result._type == ValueType.DATE
        assert result._data == date(2024, 6, 15)

    def test_to_boolean_true(self):
        scope = _make_scope()
        result = _call(scope, "to_boolean", 1)
        assert result == Value(True)

    def test_to_boolean_false(self):
        scope = _make_scope()
        result = _call(scope, "to_boolean", 0)
        assert result == Value(False)

    def test_to_boolean_string(self):
        scope = _make_scope()
        result = _call(scope, "to_boolean", "hello")
        assert result == Value(True)

    def test_to_boolean_empty_string(self):
        scope = _make_scope()
        result = _call(scope, "to_boolean", "")
        assert result == Value(False)


# ---------------------------------------------------------------------------
# Posting / account query functions
# ---------------------------------------------------------------------------

class TestPostingQueryFunctions:
    def test_amount_default(self):
        """Without posting context, amount returns VOID."""
        scope = _make_scope()
        result = _call(scope, "amount")
        assert result.is_null()

    def test_amount_with_context(self):
        """With __post_amount__ in scope, amount returns it."""
        scope = _make_scope()
        scope.define("__post_amount__", Value(Amount("$50.00")))
        result = _call(scope, "amount")
        assert result == Value(Amount("$50.00"))

    def test_amount_with_callable_context(self):
        scope = _make_scope()
        scope.define("__post_amount__", lambda cs: Value(Amount("$75.00")))
        result = _call(scope, "amount")
        assert result == Value(Amount("$75.00"))

    def test_account_default(self):
        scope = _make_scope()
        result = _call(scope, "account")
        assert result == Value("")

    def test_account_with_context(self):
        scope = _make_scope()
        scope.define("__post_account__", Value("Expenses:Food"))
        result = _call(scope, "account")
        assert result == Value("Expenses:Food")

    def test_payee_default(self):
        scope = _make_scope()
        result = _call(scope, "payee")
        assert result == Value("")

    def test_payee_with_context(self):
        scope = _make_scope()
        scope.define("__xact_payee__", Value("Grocery Store"))
        result = _call(scope, "payee")
        assert result == Value("Grocery Store")

    def test_total_default(self):
        scope = _make_scope()
        result = _call(scope, "total")
        assert result.is_null()

    def test_total_with_context(self):
        scope = _make_scope()
        scope.define("__post_total__", Value(Amount("$150.00")))
        result = _call(scope, "total")
        assert result == Value(Amount("$150.00"))

    def test_display_amount_default_fallback(self):
        """display_amount falls back to amount when no display context."""
        scope = _make_scope()
        scope.define("__post_amount__", Value(Amount("$50.00")))
        result = _call(scope, "display_amount")
        assert result == Value(Amount("$50.00"))

    def test_display_amount_with_context(self):
        scope = _make_scope()
        scope.define("__display_amount__", Value(Amount("$50.00")))
        result = _call(scope, "display_amount")
        assert result == Value(Amount("$50.00"))

    def test_display_total_default_fallback(self):
        scope = _make_scope()
        scope.define("__post_total__", Value(Amount("$200.00")))
        result = _call(scope, "display_total")
        assert result == Value(Amount("$200.00"))

    def test_has_tag_false(self):
        scope = _make_scope()
        result = _call(scope, "has_tag", "Payee")
        assert result == Value(False)

    def test_has_tag_with_dict(self):
        scope = _make_scope()
        scope.define("__post_tags__", {"Payee": "Store", "Date": "2024-01-01"})
        result = _call(scope, "has_tag", "Payee")
        assert result == Value(True)

    def test_has_tag_missing_tag(self):
        scope = _make_scope()
        scope.define("__post_tags__", {"Payee": "Store"})
        result = _call(scope, "has_tag", "Missing")
        assert result == Value(False)

    def test_tag_value(self):
        scope = _make_scope()
        scope.define("__post_tags__", {"Payee": "Store"})
        result = _call(scope, "tag", "Payee")
        assert result == Value("Store")

    def test_tag_missing(self):
        scope = _make_scope()
        scope.define("__post_tags__", {"Payee": "Store"})
        result = _call(scope, "tag", "Missing")
        assert result.is_null()

    def test_post_default(self):
        scope = _make_scope()
        result = _call(scope, "post")
        assert result.is_null()

    def test_lot_date_default(self):
        scope = _make_scope()
        result = _call(scope, "lot_date")
        assert result.is_null()

    def test_lot_price_default(self):
        scope = _make_scope()
        result = _call(scope, "lot_price")
        assert result.is_null()

    def test_lot_tag_default(self):
        scope = _make_scope()
        result = _call(scope, "lot_tag")
        assert result.is_null()

    def test_lot_date_with_context(self):
        scope = _make_scope()
        d = date(2024, 1, 15)
        scope.define("__lot_date__", Value(d))
        result = _call(scope, "lot_date")
        assert result._type == ValueType.DATE
        assert result._data == d

    def test_lot_price_with_context(self):
        scope = _make_scope()
        scope.define("__lot_price__", Value(Amount("$10.00")))
        result = _call(scope, "lot_price")
        assert result == Value(Amount("$10.00"))

    def test_lot_tag_with_context(self):
        scope = _make_scope()
        scope.define("__lot_tag__", Value("lot123"))
        result = _call(scope, "lot_tag")
        assert result == Value("lot123")


# ---------------------------------------------------------------------------
# Boolean constants
# ---------------------------------------------------------------------------

class TestBooleanConstants:
    def test_true(self):
        scope = _make_scope()
        result = _call(scope, "true")
        assert result == Value(True)

    def test_false(self):
        scope = _make_scope()
        result = _call(scope, "false")
        assert result == Value(False)

    def test_true_is_truthy(self):
        scope = _make_scope()
        result = _call(scope, "true")
        assert bool(result)

    def test_false_is_falsy(self):
        scope = _make_scope()
        result = _call(scope, "false")
        assert not bool(result)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_abs_of_void(self):
        """abs of void raises (matches Value.__abs__ behaviour)."""
        scope = _make_scope()
        with pytest.raises(Exception):
            _call(scope, "abs", Value())

    def test_str_of_void(self):
        scope = _make_scope()
        result = _call(scope, "str", Value())
        assert result == Value("")

    def test_int_of_void(self):
        scope = _make_scope()
        result = _call(scope, "int", Value())
        assert result == Value(0)

    def test_to_boolean_of_void(self):
        scope = _make_scope()
        result = _call(scope, "to_boolean", Value())
        assert result == Value(False)

    def test_is_seq_of_void(self):
        scope = _make_scope()
        result = _call(scope, "is_seq", Value())
        assert result == Value(False)

    def test_commodity_of_void(self):
        scope = _make_scope()
        result = _call(scope, "commodity", Value())
        assert result == Value("")

    def test_register_builtins_count(self):
        """Verify all 39+ symbols are registered (including aliases)."""
        scope = _make_scope()
        expected_names = [
            "abs", "round", "roundto", "ceil", "floor", "min", "max",
            "str", "strip", "trim", "join", "quoted", "justify",
            "truncated", "format",
            "now", "today", "date", "format_date",
            "int", "quantity", "commodity", "is_seq",
            "to_amount", "to_balance", "to_string", "to_int",
            "to_date", "to_boolean",
            "amount", "account", "payee", "total",
            "display_amount", "display_total",
            "has_tag", "tag", "post",
            "lot_date", "lot_price", "lot_tag",
            "true", "false",
        ]
        for name in expected_names:
            assert scope.lookup(name) is not None, f"Missing built-in: {name}"

    def test_min_equal_values(self):
        scope = _make_scope()
        result = _call(scope, "min", 5, 5)
        assert result == Value(5)

    def test_max_equal_values(self):
        scope = _make_scope()
        result = _call(scope, "max", 5, 5)
        assert result == Value(5)

    def test_round_void(self):
        """Rounding a non-numeric type returns as-is."""
        scope = _make_scope()
        result = _call(scope, "round", "hello")
        assert result == Value("hello")

    def test_ceil_void(self):
        scope = _make_scope()
        result = _call(scope, "ceil", "hello")
        assert result == Value("hello")

    def test_floor_void(self):
        scope = _make_scope()
        result = _call(scope, "floor", "hello")
        assert result == Value("hello")

    def test_join_empty_sequence(self):
        scope = _make_scope()
        seq = Value([])
        # Empty sequence becomes VOID in Value constructor
        result = _call(scope, "join", seq, ", ")
        # Empty join returns empty string
        assert result._type == ValueType.STRING

    def test_truncated_exact_width(self):
        scope = _make_scope()
        result = _call(scope, "truncated", "Hello", 5)
        assert result == Value("Hello")
