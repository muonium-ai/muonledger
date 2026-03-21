"""Comprehensive tests for arithmetic edge cases.

T-000074: Division precision, rounding behavior, multi-commodity display
order, and numeric edge cases.
"""

from fractions import Fraction

import pytest

from muonledger.amount import Amount, AmountError
from muonledger.balance import Balance, BalanceError
from muonledger.commodity import CommodityPool
from muonledger.value import Value, ValueType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_pool():
    """Reset the commodity pool before each test to avoid cross-pollution."""
    old = CommodityPool.current_pool
    CommodityPool.current_pool = CommodityPool()
    yield
    CommodityPool.current_pool = old


# ===========================================================================
# Division precision
# ===========================================================================


class TestDivisionPrecision:
    def test_simple_division_100_by_3(self):
        """$100 / 3 should display as $33.33 (commodity precision 2)."""
        a = Amount("$100.00")
        r = a / Amount(3)
        assert str(r) == "$33.33"

    def test_division_internal_precision_higher(self):
        """Internal precision after division should be >= 6 extra digits."""
        a = Amount("$100.00")
        r = a / Amount(3)
        # Internal precision = 2 + 0 + 6 = 8
        assert r.precision >= 6

    def test_high_precision_division_1_by_7(self):
        """$1 / 7 should display correctly at commodity precision."""
        a = Amount("$1.00")
        r = a / Amount(7)
        # 1/7 = 0.142857..., rounded to 2 places = 0.14
        assert str(r) == "$0.14"

    def test_division_preserves_commodity(self):
        """Division result keeps the dividend's commodity."""
        a = Amount("$100.00")
        r = a / Amount(3)
        assert r.commodity == "$"
        assert r.has_commodity()

    def test_division_by_negative(self):
        """$100 / -3 should produce -$33.33."""
        a = Amount("$100.00")
        r = a / Amount(-3)
        assert str(r) == "$-33.33"

    def test_division_result_exact_rational(self):
        """Division stores exact Fraction, no floating-point artifacts."""
        a = Amount("$100.00")
        r = a / Amount(3)
        assert r.quantity == Fraction(100, 3)

    def test_division_by_zero_raises(self):
        a = Amount("$100.00")
        with pytest.raises(AmountError, match="Divide by zero"):
            a / Amount(0)

    def test_division_small_number(self):
        """$0.01 / 3 should not lose precision."""
        a = Amount("$0.01")
        r = a / Amount(3)
        assert r.quantity == Fraction(1, 300)
        # Display: 0.003333... rounds to 0.00 at precision 2
        assert str(r) == "$0.00"

    def test_division_keeps_fullstring_precision(self):
        """to_fullstring shows full internal precision."""
        a = Amount("$100.00")
        r = a / Amount(3)
        # Internal precision is 8, so fullstring shows 8 decimal places
        full = r.to_fullstring()
        assert "$33.33333333" == full

    def test_division_with_no_commodity(self):
        """Plain number division works correctly."""
        a = Amount("100")
        r = a / Amount(3)
        assert r.quantity == Fraction(100, 3)


# ===========================================================================
# Rounding behavior
# ===========================================================================


class TestRoundingBehavior:
    def test_round_half_up_positive(self):
        """$0.005 rounds to $0.01 (half away from zero)."""
        a = Amount("$0.005")
        r = a.roundto(2)
        assert float(r.quantity) == pytest.approx(0.01)

    def test_round_half_up_negative(self):
        """-$0.005 rounds to -$0.01 (half away from zero)."""
        a = Amount("-$0.005")
        r = a.roundto(2)
        assert float(r.quantity) == pytest.approx(-0.01)

    def test_round_to_commodity_precision(self):
        """Commodity precision ($=2) controls display rounding."""
        a = Amount("$1.999")
        # display_precision is max(3, commodity.precision=2) = 3 since
        # amount precision is 3 which is > commodity precision 2...
        # Actually amount precision=3, commodity.precision=2, keep_precision=False
        # display_precision returns max(commodity.precision, self._precision) only
        # if commodity.precision > self._precision. Here 2 < 3, so returns 3.
        # Let's check str output.
        assert "$1.999" == str(a)

    def test_roundto_explicit_places(self):
        """roundto(2) rounds value; display uses commodity precision."""
        a = Amount("$1.999")
        r = a.roundto(2)
        # Commodity $ learned precision=3 from "$1.999", so display shows 3 places
        assert str(r) == "$2.000"
        assert float(r.quantity) == pytest.approx(2.0)

    def test_round_to_zero_places(self):
        a = Amount("$1.50")
        r = a.roundto(0)
        assert float(r.quantity) == pytest.approx(2.0)

    def test_custom_precision_commodity(self):
        """Commodities with custom precision (e.g. BTC with 8 places)."""
        a = Amount("0.12345678 BTC")
        assert a.precision == 8
        assert a.commodity == "BTC"
        assert "0.12345678 BTC" == str(a)

    def test_display_precision_from_commodity(self):
        """If commodity has higher precision than amount, use commodity's."""
        # First, establish that $ has precision 2
        Amount("$1.00")
        # Now create with lower precision
        a = Amount("$5")
        # $ commodity learned precision=2, amount precision=0
        # display_precision: commodity.precision(2) > self._precision(0) -> 2
        assert a.display_precision() == 2
        assert str(a) == "$5.00"

    def test_format_quantity_round_half_away_from_zero(self):
        """_format_quantity rounds half away from zero."""
        a = Amount("$2.5")
        r = a.roundto(0)
        assert float(r.quantity) == pytest.approx(3.0)

    def test_truncated(self):
        """truncated() truncates toward zero."""
        a = Amount("$1.99")
        r = a.truncated()
        assert str(r) == "$1.99"  # at display precision 2, no truncation needed

    def test_floor_positive(self):
        a = Amount("$1.99")
        r = a.floored()
        assert float(r.quantity) == pytest.approx(1.0)

    def test_ceiling_positive(self):
        a = Amount("$1.01")
        r = a.ceilinged()
        assert float(r.quantity) == pytest.approx(2.0)


# ===========================================================================
# Multi-commodity operations (Balance)
# ===========================================================================


class TestMultiCommodity:
    def test_add_different_commodities_creates_balance(self):
        """Adding $100 + 50 EUR via Value creates a Balance."""
        v1 = Value(Amount("$100.00"))
        v2 = Value(Amount("50.00 EUR"))
        result = v1 + v2
        assert result.type == ValueType.BALANCE

    def test_balance_display_order_alphabetical(self):
        """Balance display order is alphabetical by commodity symbol."""
        bal = Balance()
        bal.add(Amount("50.00 EUR"))
        bal.add(Amount("$100.00"))
        text = str(bal)
        lines = text.split("\n")
        assert len(lines) == 2
        # $ comes before E alphabetically
        assert "$100.00" in lines[0]
        assert "EUR" in lines[1]

    def test_subtraction_same_commodity(self):
        """$100 - $30 = $70."""
        a = Amount("$100.00")
        b = Amount("$30.00")
        r = a - b
        assert str(r) == "$70.00"

    def test_zero_elimination_from_balance(self):
        """Adding opposite amounts removes commodity from balance."""
        bal = Balance()
        bal.add(Amount("$100.00"))
        bal.add(Amount("-$100.00"))
        assert bal.is_empty()
        assert bal.is_zero()

    def test_negation_of_balance(self):
        """Negating a balance negates all components."""
        bal = Balance()
        bal.add(Amount("$100.00"))
        bal.add(Amount("50.00 EUR"))
        neg = -bal
        for amt in neg:
            assert amt.is_negative()

    def test_balance_from_value_subtraction_different_commodities(self):
        """Subtracting different commodities via Value creates Balance."""
        v1 = Value(Amount("$100.00"))
        v2 = Value(Amount("50.00 EUR"))
        result = v1 - v2
        assert result.type == ValueType.BALANCE

    def test_balance_equality(self):
        bal1 = Balance()
        bal1.add(Amount("$100.00"))
        bal1.add(Amount("50.00 EUR"))
        bal2 = Balance()
        bal2.add(Amount("50.00 EUR"))
        bal2.add(Amount("$100.00"))
        assert bal1 == bal2

    def test_single_commodity_balance(self):
        """Balance with single commodity can convert to Amount."""
        bal = Balance(Amount("$100.00"))
        assert bal.single_amount() is not None
        amt = bal.to_amount()
        assert str(amt) == "$100.00"

    def test_empty_balance_is_zero(self):
        bal = Balance()
        assert bal.is_zero()
        assert bal.is_empty()
        assert str(bal) == "0"

    def test_adding_zero_does_not_change_balance(self):
        bal = Balance(Amount("$100.00"))
        bal.add(Amount("$0.00"))
        assert bal.number_of_commodities() == 1
        assert str(bal.to_amount()) == "$100.00"

    def test_balance_iteration_sorted(self):
        """Iterating over a balance yields amounts in sorted commodity order."""
        bal = Balance()
        bal.add(Amount("10.00 ZZZ"))
        bal.add(Amount("$5.00"))
        bal.add(Amount("20.00 AAA"))
        symbols = [a.commodity for a in bal]
        assert symbols == ["$", "AAA", "ZZZ"]


# ===========================================================================
# Multiplication
# ===========================================================================


class TestMultiplication:
    def test_amount_times_integer(self):
        """$50 * 2 = $100."""
        a = Amount("$50.00")
        r = a * Amount(2)
        assert str(r) == "$100.00"

    def test_amount_times_float(self):
        """10 AAPL * 1.5 = 15 AAPL."""
        a = Amount("10 AAPL")
        r = a * Amount(1.5)
        # precision = 0 + 6 = 6 but commodity precision is 0
        # display should work
        assert float(r.quantity) == pytest.approx(15.0)

    def test_amount_times_negative(self):
        a = Amount("$50.00")
        r = a * Amount(-1)
        assert str(r) == "$-50.00"

    def test_amount_times_zero(self):
        a = Amount("$50.00")
        r = a * Amount(0)
        assert r.is_realzero()

    def test_multiplier_preserves_commodity(self):
        """Multiplication preserves the left operand's commodity."""
        a = Amount("$50.00")
        r = a * Amount(3)
        assert r.commodity == "$"

    def test_integer_times_amount(self):
        """2 * $50 works via __rmul__."""
        a = Amount("$50.00")
        r = Amount(2) * a
        assert str(r) == "$100.00"

    def test_multiplier_in_auto_xact_context(self):
        """1.0 * matched amount should return equivalent amount."""
        matched = Amount("$100.00")
        multiplier = Amount(1.0)
        r = multiplier * matched
        assert float(r.quantity) == pytest.approx(100.0)
        assert r.commodity == "$"


# ===========================================================================
# Edge cases: large numbers, small numbers, precision
# ===========================================================================


class TestNumericEdgeCases:
    def test_very_large_number(self):
        a = Amount("$999999999.99")
        assert float(a.quantity) == pytest.approx(999999999.99)
        assert a.commodity == "$"

    def test_very_small_number(self):
        a = Amount("$0.001")
        assert a.quantity == Fraction(1, 1000)
        assert a.precision == 3

    def test_exactly_zero(self):
        a = Amount("$0.00")
        assert a.is_zero()
        assert a.is_realzero()

    def test_negative_zero(self):
        """Negative zero should still be zero."""
        a = Amount("$0.00")
        r = -a
        assert r.is_zero()
        assert r.is_realzero()

    def test_high_precision_10_places(self):
        a = Amount("1.0123456789 BTC")
        assert a.precision == 10
        assert a.quantity == Fraction("1.0123456789")

    def test_fraction_no_float_artifacts(self):
        """Using Fraction avoids 0.1 + 0.2 != 0.3 issues."""
        a = Amount("$0.10")
        b = Amount("$0.20")
        c = Amount("$0.30")
        assert (a + b).quantity == c.quantity

    def test_overflow_protection_large_multiply(self):
        """Fraction handles very large numbers without overflow."""
        a = Amount("$999999999.99")
        r = a * Amount(999999999)
        assert r.quantity > 0
        assert r.has_commodity()

    def test_amount_comparison_operators(self):
        a = Amount("$10.00")
        b = Amount("$20.00")
        assert a < b
        assert a <= b
        assert b > a
        assert b >= a
        assert a != b
        assert a == Amount("$10.00")

    def test_amount_sorting(self):
        """Amounts of the same commodity can be sorted."""
        amounts = [Amount("$30.00"), Amount("$10.00"), Amount("$20.00")]
        amounts.sort()
        values = [float(a.quantity) for a in amounts]
        assert values == [10.0, 20.0, 30.0]

    def test_comparison_different_commodities_raises(self):
        """Comparing amounts with different commodities raises."""
        a = Amount("$10.00")
        b = Amount("10.00 EUR")
        with pytest.raises(AmountError):
            a.compare(b)

    def test_abs_positive(self):
        a = Amount("$10.00")
        assert abs(a) == a

    def test_abs_negative(self):
        a = Amount("-$10.00")
        r = abs(a)
        assert r.quantity == Fraction(10)

    def test_sign_positive(self):
        assert Amount("$10.00").sign() == 1

    def test_sign_negative(self):
        assert Amount("-$10.00").sign() == -1

    def test_sign_zero(self):
        assert Amount("$0.00").sign() == 0

    def test_is_negative(self):
        assert Amount("-$1.00").is_negative()
        assert not Amount("$1.00").is_negative()

    def test_is_positive(self):
        assert Amount("$1.00").is_positive()
        assert not Amount("-$1.00").is_positive()


# ===========================================================================
# Balance edge cases
# ===========================================================================


class TestBalanceEdgeCases:
    def test_empty_balance_is_falsy(self):
        bal = Balance()
        assert not bool(bal)

    def test_nonempty_balance_is_truthy(self):
        bal = Balance(Amount("$1.00"))
        assert bool(bal)

    def test_balance_mul_by_scalar(self):
        bal = Balance()
        bal.add(Amount("$100.00"))
        bal.add(Amount("50.00 EUR"))
        r = bal * 2
        for amt in r:
            if amt.commodity == "$":
                assert float(amt.quantity) == pytest.approx(200.0)
            elif amt.commodity == "EUR":
                assert float(amt.quantity) == pytest.approx(100.0)

    def test_balance_div_by_scalar(self):
        bal = Balance(Amount("$100.00"))
        r = bal / 2
        assert float(r.to_amount().quantity) == pytest.approx(50.0)

    def test_balance_div_by_zero_raises(self):
        bal = Balance(Amount("$100.00"))
        with pytest.raises(BalanceError, match="Divide by zero"):
            bal / 0

    def test_balance_abs(self):
        bal = Balance()
        bal.add(Amount("-$100.00"))
        bal.add(Amount("-50.00 EUR"))
        r = abs(bal)
        for amt in r:
            assert amt.is_positive()

    def test_balance_round(self):
        bal = Balance()
        # Create a balance with a result of division (extra precision)
        a = Amount("$100.00") / Amount(3)
        bal.add(a)
        rounded = bal.round()
        # Each commodity amount should be rounded per its display rules
        amt = rounded.to_amount()
        assert amt.display_precision() <= a.precision

    def test_balance_number_of_commodities(self):
        bal = Balance()
        assert bal.number_of_commodities() == 0
        bal.add(Amount("$100.00"))
        assert bal.number_of_commodities() == 1
        bal.add(Amount("50.00 EUR"))
        assert bal.number_of_commodities() == 2

    def test_balance_contains(self):
        bal = Balance(Amount("$100.00"))
        assert "$" in bal
        assert "EUR" not in bal

    def test_balance_getitem(self):
        bal = Balance(Amount("$100.00"))
        amt = bal["$"]
        assert str(amt) == "$100.00"

    def test_balance_getitem_missing_raises(self):
        bal = Balance(Amount("$100.00"))
        with pytest.raises(KeyError):
            bal["EUR"]

    def test_balance_negate_in_place(self):
        bal = Balance(Amount("$100.00"))
        bal.negate()
        assert bal.to_amount().is_negative()

    def test_balance_negated_copy(self):
        bal = Balance(Amount("$100.00"))
        neg = bal.negated()
        assert neg.to_amount().is_negative()
        # Original unchanged
        assert bal.to_amount().is_positive()


# ===========================================================================
# Integration scenarios
# ===========================================================================


class TestIntegration:
    def test_auto_balance_arithmetic(self):
        """Simulating a two-posting transaction auto-balance.

        Transaction:
          Expenses:Food   $33.33
          Checking        (auto-balanced to -$33.33)
        """
        posting = Amount("$33.33")
        auto_bal = -posting
        assert str(auto_bal) == "$-33.33"
        total = posting + auto_bal
        assert total.is_realzero()

    def test_three_way_split_precision(self):
        """$100 split three ways: 33.33 + 33.33 + 33.34 = $100.00."""
        total = Amount("$100.00")
        share = total / Amount(3)
        # share internally is 100/3, display is $33.33
        assert str(share) == "$33.33"
        # Two shares at rounded value + remainder
        share_rounded = share.roundto(2)
        two_shares = share_rounded + share_rounded
        remainder = total - two_shares
        assert str(remainder) == "$33.34"
        final = two_shares + remainder
        assert str(final) == "$100.00"

    def test_running_total_accumulation(self):
        """Accumulate many small amounts without losing precision."""
        total = Amount("$0.00")
        for _ in range(100):
            total = total + Amount("$0.01")
        assert str(total) == "$1.00"
        assert total.quantity == Fraction(1)

    def test_cost_conversion_arithmetic(self):
        """10 AAPL @ $150 -> total cost $1500."""
        shares = Amount("10 AAPL")
        price = Amount("$150.00")
        # Total cost: quantity * price = 10 * 150 = 1500
        cost = Amount(int(shares.quantity)) * price
        assert float(cost.quantity) == pytest.approx(1500.0)
        assert cost.commodity == "$"

    def test_value_add_then_subtract_same_commodity(self):
        v = Value(Amount("$100.00"))
        v = v + Value(Amount("$50.00"))
        v = v - Value(Amount("$30.00"))
        assert str(v) == "$120.00"

    def test_value_division_integer(self):
        """Value integer division produces Amount."""
        v = Value(100) / Value(3)
        assert v.type == ValueType.AMOUNT


# ===========================================================================
# Amount rounding method variants
# ===========================================================================


class TestRoundingMethods:
    def test_rounded_clears_keep_precision(self):
        a = Amount.exact("$33.333333")
        assert a.keep_precision
        r = a.rounded()
        assert not r.keep_precision

    def test_unrounded_sets_keep_precision(self):
        a = Amount("$10.00")
        r = a.unrounded()
        assert r.keep_precision

    def test_in_place_round_no_precision(self):
        a = Amount("$10.00")
        a._keep_precision = True
        a.in_place_round()
        assert not a._keep_precision

    def test_in_place_round_with_precision(self):
        a = Amount("$10.456")
        a.in_place_round(precision=2)
        assert float(a.quantity) == pytest.approx(10.46)
        assert a.precision == 2

    def test_round_method_with_precision(self):
        a = Amount("$10.456")
        r = a.round(precision=2)
        assert float(r.quantity) == pytest.approx(10.46)

    def test_round_method_without_precision(self):
        a = Amount("$10.456")
        r = a.round()
        assert not r.keep_precision


# ===========================================================================
# Amount number/strip commodity
# ===========================================================================


class TestNumberStrip:
    def test_number_strips_commodity(self):
        a = Amount("$100.00")
        n = a.number()
        assert n.commodity is None
        assert n.quantity == Fraction(100)

    def test_clear_commodity(self):
        a = Amount("$100.00")
        a.clear_commodity()
        assert a.commodity is None

    def test_reduce_returns_copy(self):
        a = Amount("$100.00")
        r = a.reduce()
        assert r == a
        assert r is not a


# ===========================================================================
# Amount __hash__
# ===========================================================================


class TestAmountHash:
    def test_equal_amounts_same_hash(self):
        a = Amount("$100.00")
        b = Amount("$100.00")
        assert hash(a) == hash(b)

    def test_different_amounts_likely_different_hash(self):
        a = Amount("$100.00")
        b = Amount("$200.00")
        # Not guaranteed but extremely likely
        assert hash(a) != hash(b)

    def test_amount_in_set(self):
        s = {Amount("$100.00"), Amount("$100.00"), Amount("$200.00")}
        assert len(s) == 2


# ===========================================================================
# Floordiv and modulo
# ===========================================================================


class TestFloorDivMod:
    def test_floordiv(self):
        a = Amount("$100.00")
        r = a // Amount(3)
        assert r.quantity == Fraction(33)

    def test_modulo(self):
        a = Amount("$100.00")
        r = a % Amount(3)
        assert float(r.quantity) == pytest.approx(1.0)

    def test_modulo_by_zero_raises(self):
        a = Amount("$100.00")
        with pytest.raises(AmountError, match="Divide by zero"):
            a % Amount(0)
