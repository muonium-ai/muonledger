"""Tests for the Balance class."""

import pytest

from muonledger.amount import Amount
from muonledger.balance import Balance, BalanceError
from muonledger.commodity import CommodityPool


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global commodity pool before each test."""
    CommodityPool.reset_current()
    yield
    CommodityPool.reset_current()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_balance(self):
        b = Balance()
        assert b.is_empty()
        assert len(b) == 0

    def test_from_amount(self):
        a = Amount("$100.00")
        b = Balance(a)
        assert not b.is_empty()
        assert len(b) == 1
        assert "$" in b

    def test_from_amount_zero(self):
        a = Amount(0)
        b = Balance(a)
        assert b.is_empty()

    def test_from_null_amount_raises(self):
        with pytest.raises(BalanceError):
            Balance(Amount())

    def test_from_dict(self):
        a1 = Amount("$50.00")
        a2 = Amount("100 EUR")
        b = Balance({"$": a1, "EUR": a2})
        assert len(b) == 2
        assert "$" in b
        assert "EUR" in b

    def test_from_balance(self):
        b1 = Balance(Amount("$100.00"))
        b2 = Balance(b1)
        assert b2 == b1
        # Verify independence (copy, not reference).
        b1 += Amount("$50.00")
        assert b2 != b1

    def test_from_invalid_type_raises(self):
        with pytest.raises(TypeError):
            Balance(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Adding amounts
# ---------------------------------------------------------------------------


class TestAddition:
    def test_add_same_commodity(self):
        b = Balance(Amount("$100.00"))
        b += Amount("$50.00")
        assert len(b) == 1
        assert str(b["$"]) == "$150.00"

    def test_add_different_commodity(self):
        b = Balance(Amount("$100.00"))
        b += Amount("200 EUR")
        assert len(b) == 2

    def test_add_to_zero_removes(self):
        b = Balance(Amount("$100.00"))
        b += Amount("-$100.00")
        assert b.is_empty()

    def test_add_balance_to_balance(self):
        b1 = Balance(Amount("$100.00"))
        b2 = Balance(Amount("200 EUR"))
        b3 = b1 + b2
        assert len(b3) == 2
        assert "$" in b3
        assert "EUR" in b3

    def test_add_method(self):
        b = Balance()
        b.add(Amount("$10.00"))
        b.add(Amount("$20.00"))
        assert str(b["$"]) == "$30.00"

    def test_add_null_raises(self):
        b = Balance()
        with pytest.raises(BalanceError):
            b += Amount()


# ---------------------------------------------------------------------------
# Subtraction
# ---------------------------------------------------------------------------


class TestSubtraction:
    def test_subtract_same_commodity(self):
        b = Balance(Amount("$100.00"))
        b -= Amount("$30.00")
        assert str(b["$"]) == "$70.00"

    def test_subtract_to_zero_removes(self):
        b = Balance(Amount("$100.00"))
        b -= Amount("$100.00")
        assert b.is_empty()

    def test_subtract_absent_commodity(self):
        b = Balance(Amount("$100.00"))
        b -= Amount("50 EUR")
        assert len(b) == 2
        # EUR should be negative.
        eur = b["EUR"]
        assert eur.is_negative()

    def test_subtract_balance_from_balance(self):
        b1 = Balance(Amount("$100.00"))
        b2 = Balance(Amount("$30.00"))
        b3 = b1 - b2
        assert str(b3["$"]) == "$70.00"

    def test_subtract_null_raises(self):
        b = Balance()
        with pytest.raises(BalanceError):
            b -= Amount()


# ---------------------------------------------------------------------------
# Multiplication and division
# ---------------------------------------------------------------------------


class TestMulDiv:
    def test_multiply_by_int(self):
        b = Balance(Amount("$100.00"))
        b2 = b * 3
        assert str(b2["$"]) == "$300.00"

    def test_multiply_by_float(self):
        b = Balance(Amount("$100.00"))
        b2 = b * 0.5
        # Should be approximately $50.00.
        val = float(b2["$"])
        assert val == pytest.approx(50.0)

    def test_rmul(self):
        b = Balance(Amount("$100.00"))
        b2 = 2 * b
        assert str(b2["$"]) == "$200.00"

    def test_multiply_by_commoditized_raises(self):
        b = Balance(Amount("$100.00"))
        with pytest.raises(BalanceError):
            b * Amount("5 EUR")

    def test_divide_by_int(self):
        b = Balance(Amount("$100.00"))
        b2 = b / 4
        val = float(b2["$"])
        assert val == pytest.approx(25.0)

    def test_divide_by_zero_raises(self):
        b = Balance(Amount("$100.00"))
        with pytest.raises(BalanceError):
            b / 0

    def test_divide_by_commoditized_raises(self):
        b = Balance(Amount("$100.00"))
        with pytest.raises(BalanceError):
            b / Amount("5 EUR")

    def test_mul_multi_commodity(self):
        b = Balance()
        b += Amount("$100.00")
        b += Amount("200 EUR")
        b2 = b * 2
        assert len(b2) == 2
        assert str(b2["$"]) == "$200.00"


# ---------------------------------------------------------------------------
# Unary operations
# ---------------------------------------------------------------------------


class TestUnary:
    def test_negated(self):
        b = Balance(Amount("$100.00"))
        b2 = -b
        assert b2["$"].is_negative()
        assert str(b2["$"]) == "$-100.00"

    def test_negate_in_place(self):
        b = Balance(Amount("$100.00"))
        b.negate()
        assert b["$"].is_negative()

    def test_abs(self):
        b = Balance(Amount("-$100.00"))
        b2 = abs(b)
        assert b2["$"].is_positive()


# ---------------------------------------------------------------------------
# Truth tests
# ---------------------------------------------------------------------------


class TestTruthTests:
    def test_is_zero_empty(self):
        b = Balance()
        assert b.is_zero()

    def test_is_zero_with_amounts(self):
        b = Balance(Amount("$100.00"))
        assert not b.is_zero()

    def test_is_empty(self):
        b = Balance()
        assert b.is_empty()
        b += Amount("$1.00")
        assert not b.is_empty()

    def test_is_nonzero(self):
        b = Balance(Amount("$100.00"))
        assert b.is_nonzero()
        assert bool(b)

    def test_bool_empty(self):
        assert not bool(Balance())


# ---------------------------------------------------------------------------
# Commodity queries
# ---------------------------------------------------------------------------


class TestCommodityQueries:
    def test_single_amount(self):
        b = Balance(Amount("$100.00"))
        sa = b.single_amount()
        assert sa is not None
        assert str(sa) == "$100.00"

    def test_single_amount_multi_returns_none(self):
        b = Balance()
        b += Amount("$100.00")
        b += Amount("200 EUR")
        assert b.single_amount() is None

    def test_single_amount_empty_returns_none(self):
        assert Balance().single_amount() is None

    def test_to_amount(self):
        b = Balance(Amount("$100.00"))
        a = b.to_amount()
        assert str(a) == "$100.00"

    def test_to_amount_empty_raises(self):
        with pytest.raises(BalanceError):
            Balance().to_amount()

    def test_to_amount_multi_raises(self):
        b = Balance()
        b += Amount("$100.00")
        b += Amount("200 EUR")
        with pytest.raises(BalanceError):
            b.to_amount()

    def test_number_of_commodities(self):
        b = Balance()
        assert b.number_of_commodities() == 0
        b += Amount("$100.00")
        assert b.number_of_commodities() == 1
        b += Amount("200 EUR")
        assert b.number_of_commodities() == 2

    def test_commodity_count(self):
        b = Balance(Amount("$100.00"))
        assert b.commodity_count() == 1

    def test_amounts_returns_copy(self):
        b = Balance(Amount("$100.00"))
        d = b.amounts()
        d["$"] = Amount("$999.00")
        # Original should be unchanged.
        assert str(b["$"]) == "$100.00"


# ---------------------------------------------------------------------------
# Container protocol
# ---------------------------------------------------------------------------


class TestContainer:
    def test_iter(self):
        b = Balance()
        b += Amount("$100.00")
        b += Amount("200 EUR")
        items = list(b)
        assert len(items) == 2
        # Sorted by commodity symbol: $ < EUR
        symbols = [a.commodity for a in items]
        assert symbols == sorted(symbols)

    def test_len(self):
        b = Balance()
        assert len(b) == 0
        b += Amount("$100.00")
        assert len(b) == 1

    def test_contains(self):
        b = Balance(Amount("$100.00"))
        assert "$" in b
        assert "EUR" not in b

    def test_getitem(self):
        b = Balance(Amount("$100.00"))
        a = b["$"]
        assert str(a) == "$100.00"

    def test_getitem_missing_raises(self):
        b = Balance()
        with pytest.raises(KeyError):
            b["$"]


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


class TestRounding:
    def test_round(self):
        b = Balance(Amount("$100.00"))
        b2 = b.round()
        assert str(b2["$"]) == "$100.00"

    def test_roundto(self):
        b = Balance(Amount("$100.456"))
        b2 = b.roundto(2)
        # The commodity learned precision 3 from parsing, so display shows 3 digits.
        # But the value is rounded to 2 decimal places: 100.46 displayed as 100.460.
        val = float(b2["$"])
        assert val == pytest.approx(100.46)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class TestComparison:
    def test_eq_balances(self):
        b1 = Balance(Amount("$100.00"))
        b2 = Balance(Amount("$100.00"))
        assert b1 == b2

    def test_ne_balances(self):
        b1 = Balance(Amount("$100.00"))
        b2 = Balance(Amount("$200.00"))
        assert b1 != b2

    def test_eq_amount(self):
        b = Balance(Amount("$100.00"))
        assert b == Amount("$100.00")

    def test_eq_zero_amount(self):
        b = Balance()
        assert b == Amount(0)

    def test_ne_amount(self):
        b = Balance(Amount("$100.00"))
        assert b != Amount("$200.00")


# ---------------------------------------------------------------------------
# String formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_str_empty(self):
        assert str(Balance()) == "0"

    def test_str_single(self):
        b = Balance(Amount("$100.00"))
        assert str(b) == "$100.00"

    def test_str_multi(self):
        b = Balance()
        b += Amount("$100.00")
        b += Amount("200 EUR")
        s = str(b)
        lines = s.split("\n")
        assert len(lines) == 2
        # Sorted by commodity symbol.
        assert "$100.00" in lines[0]
        assert "EUR" in lines[1]

    def test_repr(self):
        b = Balance(Amount("$100.00"))
        assert "Balance" in repr(b)


# ---------------------------------------------------------------------------
# Strip annotations stub
# ---------------------------------------------------------------------------


class TestStripAnnotations:
    def test_stub_returns_copy(self):
        b = Balance(Amount("$100.00"))
        b2 = b.strip_annotations()
        assert b2 == b
        # Verify it is a copy.
        b2 += Amount("$50.00")
        assert b2 != b
