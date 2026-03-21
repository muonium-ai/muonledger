"""Comprehensive tests for the Amount class."""

import math
from fractions import Fraction

import pytest

from muonledger.amount import Amount, AmountError


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_null_amount(self):
        a = Amount()
        assert a.is_null()
        assert str(a) == "<null>"

    def test_from_int(self):
        a = Amount(42)
        assert a.quantity == Fraction(42)
        assert not a.is_null()
        assert a.precision == 0

    def test_from_negative_int(self):
        a = Amount(-7)
        assert a.quantity == Fraction(-7)

    def test_from_zero(self):
        a = Amount(0)
        assert a.is_zero()
        assert a.is_realzero()

    def test_from_float(self):
        a = Amount(10.5)
        assert float(a) == pytest.approx(10.5)

    def test_from_fraction(self):
        a = Amount(Fraction(1, 3))
        assert a.quantity == Fraction(1, 3)

    def test_copy_from_amount(self):
        a = Amount("$10.00")
        b = Amount(a)
        assert b.quantity == a.quantity
        assert b.commodity == a.commodity

    def test_from_int_with_commodity(self):
        a = Amount(10, commodity="AAPL")
        assert a.quantity == Fraction(10)
        assert a.commodity == "AAPL"


# ---------------------------------------------------------------------------
# String parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_plain_integer(self):
        a = Amount("42")
        assert a.quantity == Fraction(42)
        assert a.commodity is None
        assert a.precision == 0

    def test_plain_decimal(self):
        a = Amount("10.50")
        assert a.quantity == Fraction(21, 2)
        assert a.precision == 2

    def test_negative_plain(self):
        a = Amount("-5.25")
        assert a.quantity == Fraction(-21, 4)
        assert a.precision == 2

    def test_prefix_dollar(self):
        a = Amount("$10.00")
        assert a.commodity == "$"
        assert a.quantity == Fraction(10)
        assert a.precision == 2

    def test_prefix_dollar_negative(self):
        a = Amount("-$42.50")
        assert a.commodity == "$"
        assert a.quantity == Fraction(-85, 2)

    def test_suffix_commodity(self):
        a = Amount("10 AAPL")
        assert a.commodity == "AAPL"
        assert a.quantity == Fraction(10)

    def test_suffix_commodity_decimal(self):
        a = Amount("-5.25 EUR")
        assert a.commodity == "EUR"
        assert a.quantity == Fraction(-21, 4)
        assert a.precision == 2

    def test_thousands_comma(self):
        a = Amount("1,000.00")
        assert a.quantity == Fraction(1000)
        assert a.precision == 2

    def test_thousands_with_commodity(self):
        a = Amount("$1,000.00")
        assert a.commodity == "$"
        assert a.quantity == Fraction(1000)

    def test_large_thousands(self):
        a = Amount("1,234,567.89")
        assert a.quantity == Fraction(123456789, 100)

    def test_quoted_commodity(self):
        a = Amount('10 "MUTUAL FUND"')
        assert a.commodity == "MUTUAL FUND"
        assert a.quantity == Fraction(10)

    def test_positive_sign(self):
        a = Amount("+100.00")
        assert a.quantity == Fraction(100)

    def test_empty_string_raises(self):
        with pytest.raises(AmountError):
            Amount("")

    def test_no_quantity_raises(self):
        with pytest.raises(AmountError):
            Amount("   ")

    def test_european_decimal_comma_large_fraction(self):
        # single comma with >3 digits after is a decimal
        a = Amount("1,2345")
        assert a.quantity == Fraction(12345, 10000)
        assert a.precision == 4

    def test_apostrophe_thousands(self):
        a = Amount("1'234'567.89")
        assert a.quantity == Fraction(123456789, 100)
        assert a.precision == 2


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


class TestArithmetic:
    def test_add_plain(self):
        a = Amount("10.00")
        b = Amount("5.50")
        c = a + b
        assert c.quantity == Fraction(31, 2)

    def test_add_preserves_commodity(self):
        a = Amount("$10.00")
        b = Amount("$5.00")
        c = a + b
        assert c.commodity == "$"
        assert c.quantity == Fraction(15)

    def test_add_different_commodity_raises(self):
        a = Amount("$10.00")
        b = Amount("10.00 EUR")
        with pytest.raises(AmountError):
            _ = a + b

    def test_add_int(self):
        a = Amount("$10.00")
        c = a + 5
        assert c.quantity == Fraction(15)

    def test_sub(self):
        a = Amount("10.00")
        b = Amount("3.50")
        c = a - b
        assert c.quantity == Fraction(13, 2)

    def test_sub_int(self):
        a = Amount("10.00")
        c = a - 3
        assert c.quantity == Fraction(7)

    def test_mul(self):
        a = Amount("10.00")
        b = Amount("3")
        c = a * b
        assert c.quantity == Fraction(30)

    def test_mul_int(self):
        a = Amount("$10.00")
        c = a * 3
        assert c.quantity == Fraction(30)

    def test_div(self):
        a = Amount("10.00")
        b = Amount("3")
        c = a / b
        assert c.quantity == Fraction(10, 3)

    def test_div_by_zero_raises(self):
        a = Amount("10.00")
        b = Amount("0")
        with pytest.raises(AmountError):
            _ = a / b

    def test_div_precision_extension(self):
        a = Amount("10.00")
        b = Amount("3")
        c = a / b
        # precision should be extended by extend_by_digits
        assert c.precision == 2 + 0 + Amount.extend_by_digits

    def test_floordiv(self):
        a = Amount("10.00")
        b = Amount("3")
        c = a // b
        assert c.quantity == Fraction(3)

    def test_mod(self):
        a = Amount("10.00")
        b = Amount("3")
        c = a % b
        assert c.quantity == Fraction(1)

    def test_neg(self):
        a = Amount("10.00")
        b = -a
        assert b.quantity == Fraction(-10)

    def test_abs_negative(self):
        a = Amount("-10.00")
        b = abs(a)
        assert b.quantity == Fraction(10)

    def test_abs_positive(self):
        a = Amount("10.00")
        b = abs(a)
        assert b.quantity == Fraction(10)

    def test_mixed_precision_add(self):
        a = Amount("10.5")
        b = Amount("1.25")
        c = a + b
        assert c.quantity == Fraction(47, 4)
        assert c.precision == 2  # max(1, 2)

    def test_mixed_precision_mul(self):
        a = Amount("10.5")
        b = Amount("1.25")
        c = a * b
        assert c.precision == 3  # 1 + 2

    def test_radd(self):
        a = Amount("10.00")
        c = 5 + a
        assert c.quantity == Fraction(15)

    def test_rsub(self):
        a = Amount("3.00")
        c = 10 - a
        assert c.quantity == Fraction(7)

    def test_rmul(self):
        a = Amount("10.00")
        c = 3 * a
        assert c.quantity == Fraction(30)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class TestComparison:
    def test_eq_same(self):
        assert Amount("10.00") == Amount("10.00")

    def test_eq_different_precision(self):
        assert Amount("10.0") == Amount("10.00")

    def test_eq_int(self):
        assert Amount("10") == 10

    def test_ne(self):
        assert Amount("10") != Amount("11")

    def test_lt(self):
        assert Amount("5") < Amount("10")

    def test_le(self):
        assert Amount("5") <= Amount("5")
        assert Amount("5") <= Amount("10")

    def test_gt(self):
        assert Amount("10") > Amount("5")

    def test_ge(self):
        assert Amount("10") >= Amount("10")
        assert Amount("10") >= Amount("5")

    def test_compare_different_commodities_raises(self):
        with pytest.raises(AmountError):
            Amount("$10") < Amount("10 EUR")

    def test_eq_different_commodities_false(self):
        assert Amount("$10") != Amount("10 EUR")

    def test_null_amounts_equal(self):
        assert Amount() == Amount()

    def test_null_vs_non_null(self):
        assert Amount() != Amount(0)

    def test_compare_with_int(self):
        assert Amount("10") > 5
        assert Amount("3") < 10


# ---------------------------------------------------------------------------
# Truth tests and sign
# ---------------------------------------------------------------------------


class TestTruthAndSign:
    def test_is_zero(self):
        assert Amount(0).is_zero()
        assert Amount("0.00").is_zero()

    def test_is_not_zero(self):
        assert not Amount("1").is_zero()

    def test_is_realzero(self):
        assert Amount(0).is_realzero()

    def test_is_negative(self):
        assert Amount("-5").is_negative()
        assert not Amount("5").is_negative()

    def test_is_positive(self):
        assert Amount("5").is_positive()
        assert not Amount("-5").is_positive()
        assert not Amount("0").is_positive()

    def test_sign(self):
        assert Amount("10").sign() == 1
        assert Amount("-10").sign() == -1
        assert Amount("0").sign() == 0

    def test_bool_nonzero(self):
        assert bool(Amount("1"))

    def test_bool_zero(self):
        assert not bool(Amount("0"))

    def test_is_null(self):
        assert Amount().is_null()
        assert not Amount(0).is_null()

    def test_uninitialized_raises(self):
        a = Amount()
        with pytest.raises(AmountError):
            a.sign()
        with pytest.raises(AmountError):
            a.is_zero()
        with pytest.raises(AmountError):
            _ = a.quantity


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


class TestRounding:
    def test_roundto(self):
        a = Amount("10.555")
        b = a.roundto(2)
        assert b.quantity == Fraction(1056, 100)  # 10.56

    def test_roundto_half_away_from_zero_positive(self):
        a = Amount("10.545")
        b = a.roundto(2)
        assert b.quantity == Fraction(1055, 100)  # 10.55 (round half away from zero -> 10.55)
        # Actually 10.545 -> 10.55 (round up at 5)
        assert float(b) == pytest.approx(10.55)

    def test_roundto_half_away_from_zero_negative(self):
        a = Amount("-10.545")
        b = a.roundto(2)
        assert float(b) == pytest.approx(-10.55)

    def test_roundto_zero_places(self):
        a = Amount("10.6")
        b = a.roundto(0)
        assert b.quantity == Fraction(11)

    def test_in_place_roundto(self):
        a = Amount("10.555")
        a.in_place_roundto(2)
        assert float(a) == pytest.approx(10.56)

    def test_truncated(self):
        a = Amount("10.999")
        b = a.truncated()
        # display precision = 3, so truncation at 3 digits keeps it
        assert float(b) == pytest.approx(10.999)

    def test_round_method_with_precision(self):
        a = Amount("10.555")
        b = a.round(2)
        assert float(b) == pytest.approx(10.56)

    def test_round_method_without_precision(self):
        a = Amount("10.555")
        b = a.round()
        assert not b.keep_precision

    def test_unround(self):
        a = Amount("10.555")
        b = a.round()
        c = b.unround()
        assert c.keep_precision


# ---------------------------------------------------------------------------
# String formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_plain_integer_str(self):
        assert str(Amount(42)) == "42"

    def test_plain_decimal_str(self):
        assert str(Amount("10.50")) == "10.50"

    def test_prefix_commodity(self):
        a = Amount("$10.00")
        assert str(a) == "$10.00"

    def test_suffix_commodity(self):
        a = Amount("10 AAPL")
        assert str(a) == "10 AAPL"

    def test_suffix_commodity_decimal(self):
        a = Amount("-5.25 EUR")
        assert str(a) == "-5.25 EUR"

    def test_negative_prefix(self):
        a = Amount("-$42.50")
        assert str(a) == "$-42.50"

    def test_thousands_display(self):
        a = Amount("$1,000.00")
        s = str(a)
        assert s == "$1,000.00"

    def test_repr(self):
        a = Amount("$10.00")
        assert repr(a) == "Amount('$10.00')"

    def test_null_str(self):
        assert str(Amount()) == "<null>"

    def test_quantity_string(self):
        a = Amount("$1,000.00")
        qs = a.quantity_string()
        assert "$" not in qs
        assert "1" in qs
        assert "000" in qs

    def test_to_fullstring(self):
        a = Amount("$10.00")
        assert a.to_fullstring() == "$10.00"


# ---------------------------------------------------------------------------
# Properties and methods
# ---------------------------------------------------------------------------


class TestProperties:
    def test_quantity_property(self):
        a = Amount("10.5")
        assert a.quantity == Fraction(21, 2)

    def test_commodity_property(self):
        a = Amount("$10.00")
        assert a.commodity == "$"

    def test_has_commodity(self):
        assert Amount("$10").has_commodity()
        assert not Amount("10").has_commodity()

    def test_set_commodity(self):
        a = Amount("10.00")
        a.commodity = "USD"
        assert a.commodity == "USD"

    def test_number(self):
        a = Amount("$10.00")
        n = a.number()
        assert n.commodity is None
        assert n.quantity == Fraction(10)

    def test_negate(self):
        a = Amount("10")
        b = a.negate()
        assert b.quantity == Fraction(-10)

    def test_abs_method(self):
        a = Amount("-10")
        b = a.abs()
        assert b.quantity == Fraction(10)

    def test_reduce_noop(self):
        a = Amount("10.00")
        b = a.reduce()
        assert b.quantity == a.quantity

    def test_exact_factory(self):
        a = Amount.exact("$100.005")
        assert a.keep_precision
        assert a.quantity == Fraction(100005, 1000)

    def test_to_double(self):
        a = Amount("10.5")
        assert a.to_double() == pytest.approx(10.5)

    def test_to_long(self):
        a = Amount("10.5")
        assert a.to_long() == 10  # Python round-to-even (banker's rounding)

    def test_int_conversion(self):
        a = Amount("10.5")
        assert int(a) == 10  # Python round-to-even (banker's rounding)

    def test_float_conversion(self):
        a = Amount("10.5")
        assert float(a) == pytest.approx(10.5)

    def test_display_precision(self):
        a = Amount("10.50")
        assert a.display_precision() == 2

    def test_precision_property(self):
        a = Amount("10.123")
        assert a.precision == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_very_large_number(self):
        a = Amount("999999999999.99")
        b = Amount("0.01")
        c = a + b
        assert c.quantity == Fraction(10**12)

    def test_division_exact(self):
        a = Amount("10")
        b = Amount("4")
        c = a / b
        assert c.quantity == Fraction(5, 2)

    def test_division_repeating(self):
        a = Amount("1")
        b = Amount("3")
        c = a / b
        # Exact rational
        assert c.quantity == Fraction(1, 3)

    def test_chain_operations(self):
        a = Amount("100.00")
        b = Amount("3")
        c = (a / b) * b
        assert c.quantity == Fraction(100)

    def test_zero_commodity_amount(self):
        a = Amount("$0.00")
        assert a.is_zero()
        assert a.commodity == "$"

    def test_hash_equal_amounts(self):
        a = Amount("10.00")
        b = Amount("10.00")
        assert hash(a) == hash(b)

    def test_type_error_on_bad_type(self):
        with pytest.raises(TypeError):
            Amount([1, 2, 3])
