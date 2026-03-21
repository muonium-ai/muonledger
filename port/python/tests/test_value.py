"""Tests for the polymorphic Value type."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.value import Value, ValueType, ValueError_


# ---------------------------------------------------------------------------
# Construction and type detection
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_void(self):
        v = Value()
        assert v.type == ValueType.VOID
        assert v.is_null()

    def test_none(self):
        v = Value(None)
        assert v.type == ValueType.VOID

    def test_boolean_true(self):
        v = Value(True)
        assert v.type == ValueType.BOOLEAN
        assert v.to_boolean() is True

    def test_boolean_false(self):
        v = Value(False)
        assert v.type == ValueType.BOOLEAN
        assert v.to_boolean() is False

    def test_integer(self):
        v = Value(42)
        assert v.type == ValueType.INTEGER
        assert v.to_int() == 42

    def test_float_becomes_amount(self):
        v = Value(3.14)
        assert v.type == ValueType.AMOUNT

    def test_amount(self):
        a = Amount(100)
        v = Value(a)
        assert v.type == ValueType.AMOUNT

    def test_balance(self):
        b = Balance(Amount("10 USD"))
        v = Value(b)
        assert v.type == ValueType.BALANCE

    def test_string(self):
        v = Value("hello")
        assert v.type == ValueType.STRING
        assert v.to_string() == "hello"

    def test_date(self):
        d = date(2025, 1, 15)
        v = Value(d)
        assert v.type == ValueType.DATE

    def test_datetime(self):
        dt = datetime(2025, 1, 15, 10, 30)
        v = Value(dt)
        assert v.type == ValueType.DATETIME

    def test_sequence(self):
        v = Value([1, 2, 3])
        assert v.type == ValueType.SEQUENCE
        assert len(v) == 3

    def test_mask(self):
        pat = re.compile(r"foo.*")
        v = Value(pat)
        assert v.type == ValueType.MASK

    def test_copy_value(self):
        orig = Value(42)
        copy = Value(orig)
        assert copy.type == ValueType.INTEGER
        assert copy.to_int() == 42

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            Value(object())


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

class TestCoercion:
    def test_to_boolean_from_int(self):
        assert Value(0).to_boolean() is False
        assert Value(1).to_boolean() is True
        assert Value(-5).to_boolean() is True

    def test_to_int_from_boolean(self):
        assert Value(True).to_int() == 1
        assert Value(False).to_int() == 0

    def test_to_int_from_amount(self):
        assert Value(Amount(42)).to_int() == 42

    def test_to_long_alias(self):
        assert Value(99).to_long() == 99

    def test_to_amount_from_int(self):
        a = Value(10).to_amount()
        assert isinstance(a, Amount)
        assert int(a) == 10

    def test_to_balance_from_amount(self):
        b = Value(Amount(5)).to_balance()
        assert isinstance(b, Balance)

    def test_to_balance_from_int(self):
        b = Value(7).to_balance()
        assert isinstance(b, Balance)

    def test_to_string_from_int(self):
        assert Value(42).to_string() == "42"

    def test_to_string_from_bool(self):
        assert Value(True).to_string() == "true"
        assert Value(False).to_string() == "false"

    def test_to_string_from_void(self):
        assert Value().to_string() == ""

    def test_to_date_from_datetime(self):
        dt = datetime(2025, 3, 15, 12, 0)
        d = Value(dt).to_date()
        assert d == date(2025, 3, 15)

    def test_to_datetime_from_date(self):
        d = date(2025, 3, 15)
        dt = Value(d).to_datetime()
        assert dt == datetime(2025, 3, 15)

    def test_to_sequence_from_scalar(self):
        seq = Value(42).to_sequence()
        assert len(seq) == 1
        assert seq[0].to_int() == 42

    def test_to_sequence_from_void(self):
        assert Value().to_sequence() == []

    def test_to_int_from_string_raises(self):
        with pytest.raises(ValueError_):
            Value("hello").to_int()

    def test_to_date_from_int_raises(self):
        with pytest.raises(ValueError_):
            Value(42).to_date()


# ---------------------------------------------------------------------------
# is_zero / is_null / is_realzero
# ---------------------------------------------------------------------------

class TestZeroNull:
    def test_void_is_null(self):
        assert Value().is_null()
        assert not Value(0).is_null()

    def test_void_is_zero(self):
        assert Value().is_zero()

    def test_int_zero(self):
        assert Value(0).is_zero()
        assert Value(0).is_realzero()
        assert not Value(0).is_nonzero()

    def test_int_nonzero(self):
        assert not Value(1).is_zero()
        assert Value(1).is_nonzero()

    def test_bool_false_is_zero(self):
        assert Value(False).is_zero()

    def test_amount_zero(self):
        assert Value(Amount(0)).is_zero()
        assert Value(Amount(0)).is_realzero()

    def test_amount_nonzero(self):
        assert not Value(Amount(10)).is_zero()

    def test_empty_string_is_zero(self):
        assert Value("").is_zero()

    def test_nonempty_string_not_zero(self):
        assert not Value("x").is_zero()

    def test_empty_sequence_is_zero(self):
        assert Value([]).is_zero()

    def test_balance_zero(self):
        assert Value(Balance()).is_zero()
        assert Value(Balance()).is_realzero()


# ---------------------------------------------------------------------------
# __bool__
# ---------------------------------------------------------------------------

class TestBool:
    def test_void_false(self):
        assert not Value()

    def test_true_bool(self):
        assert Value(True)

    def test_false_bool(self):
        assert not Value(False)

    def test_nonzero_int(self):
        assert Value(5)

    def test_zero_int(self):
        assert not Value(0)

    def test_nonempty_string(self):
        assert Value("hello")

    def test_empty_string(self):
        assert not Value("")

    def test_sequence_with_truthy(self):
        assert Value([1, 0])

    def test_sequence_all_falsy(self):
        assert not Value([0, 0])

    def test_date_is_true(self):
        assert Value(date.today())


# ---------------------------------------------------------------------------
# Arithmetic with type promotion
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_int_add(self):
        r = Value(3) + Value(4)
        assert r.type == ValueType.INTEGER
        assert r.to_int() == 7

    def test_int_sub(self):
        r = Value(10) - Value(3)
        assert r.to_int() == 7

    def test_int_mul(self):
        r = Value(6) * Value(7)
        assert r.to_int() == 42

    def test_int_div_produces_amount(self):
        r = Value(10) / Value(3)
        # Division of integers produces an Amount for precision
        assert r.type == ValueType.AMOUNT

    def test_int_add_amount_promotes(self):
        """INTEGER + AMOUNT -> AMOUNT."""
        r = Value(5) + Value(Amount(10))
        assert r.type == ValueType.AMOUNT
        assert int(r.to_amount()) == 15

    def test_amount_add_int_promotes(self):
        """AMOUNT + INTEGER -> AMOUNT."""
        r = Value(Amount(10)) + Value(5)
        assert r.type == ValueType.AMOUNT

    def test_amount_add_balance_promotes(self):
        """AMOUNT + BALANCE -> BALANCE."""
        a = Value(Amount("10 USD"))
        b = Value(Balance(Amount("5 USD")))
        r = a + b
        assert r.type == ValueType.BALANCE

    def test_different_commodities_promote_to_balance(self):
        """AMOUNT(USD) + AMOUNT(EUR) -> BALANCE."""
        a = Value(Amount("10 USD"))
        b = Value(Amount("20 EUR"))
        r = a + b
        assert r.type == ValueType.BALANCE

    def test_void_plus_value(self):
        r = Value() + Value(42)
        assert r.to_int() == 42

    def test_value_plus_void(self):
        r = Value(42) + Value()
        assert r.to_int() == 42

    def test_string_concat(self):
        r = Value("foo") + Value("bar")
        assert r.to_string() == "foobar"

    def test_string_repeat(self):
        r = Value("ab") * Value(3)
        assert r.to_string() == "ababab"

    def test_unary_neg_int(self):
        r = -Value(5)
        assert r.to_int() == -5

    def test_unary_neg_amount(self):
        r = -Value(Amount(10))
        assert r.to_amount().is_negative()

    def test_abs_int(self):
        assert abs(Value(-3)).to_int() == 3
        assert abs(Value(3)).to_int() == 3

    def test_abs_amount(self):
        r = abs(Value(Amount(-10)))
        assert r.to_amount().is_positive()

    def test_balance_mul_scalar(self):
        b = Balance(Amount("10 USD"))
        r = Value(b) * Value(2)
        # Should stay BALANCE
        assert r.type == ValueType.BALANCE

    def test_radd_int(self):
        r = 5 + Value(3)
        assert r.to_int() == 8

    def test_rsub_int(self):
        r = 10 - Value(3)
        assert r.to_int() == 7

    def test_rmul_int(self):
        r = 2 * Value(6)
        assert r.to_int() == 12

    def test_divide_by_zero_raises(self):
        with pytest.raises(ValueError_):
            Value(10) / Value(0)

    def test_balance_mul_balance_raises(self):
        b1 = Value(Balance(Amount("5 USD")))
        b2 = Value(Balance(Amount("3 USD")))
        with pytest.raises(ValueError_):
            b1 * b2

    def test_non_numeric_arithmetic_raises(self):
        with pytest.raises(ValueError_):
            Value(date.today()) + Value(date.today())


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

class TestComparison:
    def test_int_eq(self):
        assert Value(5) == Value(5)
        assert not (Value(5) == Value(6))

    def test_int_ne(self):
        assert Value(5) != Value(6)

    def test_int_lt(self):
        assert Value(3) < Value(5)
        assert not (Value(5) < Value(3))

    def test_int_le(self):
        assert Value(3) <= Value(5)
        assert Value(5) <= Value(5)

    def test_int_gt(self):
        assert Value(5) > Value(3)

    def test_int_ge(self):
        assert Value(5) >= Value(5)
        assert Value(5) >= Value(3)

    def test_cross_type_int_amount(self):
        """INTEGER and AMOUNT should be comparable."""
        assert Value(10) == Value(Amount(10))
        assert Value(5) < Value(Amount(10))

    def test_void_eq_void(self):
        assert Value() == Value()

    def test_void_ne_int(self):
        assert Value() != Value(0)

    def test_string_compare(self):
        assert Value("abc") < Value("def")
        assert Value("xyz") > Value("abc")
        assert Value("same") == Value("same")

    def test_date_compare(self):
        d1 = Value(date(2025, 1, 1))
        d2 = Value(date(2025, 6, 1))
        assert d1 < d2
        assert d2 > d1

    def test_bool_compare(self):
        assert Value(False) < Value(True)

    def test_compare_with_raw_int(self):
        assert Value(5) == 5
        assert Value(5) > 3
        assert Value(5) < 10


# ---------------------------------------------------------------------------
# Sequence operations
# ---------------------------------------------------------------------------

class TestSequence:
    def test_push_back_on_void(self):
        v = Value()
        v.push_back(1)
        assert v.type == ValueType.SEQUENCE
        assert len(v) == 1
        assert v[0].to_int() == 1

    def test_push_back_on_scalar(self):
        v = Value(42)
        v.push_back(99)
        assert v.type == ValueType.SEQUENCE
        assert len(v) == 2
        assert v[0].to_int() == 42
        assert v[1].to_int() == 99

    def test_pop_back_to_single(self):
        v = Value([1, 2])
        v.pop_back()
        # Single element unwraps
        assert v.type == ValueType.INTEGER
        assert v.to_int() == 1

    def test_pop_back_to_void(self):
        v = Value([1])
        v.pop_back()
        assert v.type == ValueType.VOID

    def test_pop_back_non_sequence(self):
        v = Value(42)
        v.pop_back()
        assert v.is_null()

    def test_getitem(self):
        v = Value([10, 20, 30])
        assert v[0].to_int() == 10
        assert v[2].to_int() == 30

    def test_getitem_scalar(self):
        v = Value(42)
        assert v[0].to_int() == 42
        with pytest.raises(IndexError):
            v[1]

    def test_iter(self):
        v = Value([1, 2, 3])
        result = [x.to_int() for x in v]
        assert result == [1, 2, 3]

    def test_len_void(self):
        assert len(Value()) == 0

    def test_len_scalar(self):
        assert len(Value(5)) == 1

    def test_len_sequence(self):
        assert len(Value([1, 2, 3])) == 3

    def test_pop_back_void_raises(self):
        with pytest.raises(ValueError_):
            Value().pop_back()


# ---------------------------------------------------------------------------
# String conversion
# ---------------------------------------------------------------------------

class TestStringConversion:
    def test_str_void(self):
        assert str(Value()) == ""

    def test_str_bool(self):
        assert str(Value(True)) == "true"
        assert str(Value(False)) == "false"

    def test_str_int(self):
        assert str(Value(42)) == "42"

    def test_str_amount(self):
        s = str(Value(Amount(100)))
        assert "100" in s

    def test_str_string(self):
        assert str(Value("hello")) == "hello"

    def test_str_sequence(self):
        s = str(Value([1, 2]))
        assert "1" in s and "2" in s

    def test_repr(self):
        r = repr(Value(42))
        assert "42" in r

    def test_str_mask(self):
        v = Value(re.compile(r"foo"))
        assert str(v) == "foo"
