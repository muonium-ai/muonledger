"""Tests for the Commodity and CommodityPool classes, and Amount integration."""

import pytest

from muonledger.commodity import Commodity, CommodityPool, CommodityStyle
from muonledger.amount import Amount, AmountError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global CommodityPool before each test."""
    CommodityPool.reset_current()
    yield
    CommodityPool.reset_current()


# ---------------------------------------------------------------------------
# Commodity creation and properties
# ---------------------------------------------------------------------------


class TestCommodity:
    def test_creation_defaults(self):
        c = Commodity("$")
        assert c.symbol == "$"
        assert c.precision == 0
        assert c.flags == CommodityStyle.DEFAULTS
        assert c.note is None

    def test_creation_with_args(self):
        c = Commodity("EUR", precision=2, flags=CommodityStyle.SUFFIXED | CommodityStyle.SEPARATED)
        assert c.symbol == "EUR"
        assert c.precision == 2
        assert c.has_flags(CommodityStyle.SUFFIXED)
        assert c.has_flags(CommodityStyle.SEPARATED)

    def test_is_prefix(self):
        c = Commodity("$")
        assert c.is_prefix is True
        c2 = Commodity("EUR", flags=CommodityStyle.SUFFIXED)
        assert c2.is_prefix is False

    def test_qualified_symbol_simple(self):
        c = Commodity("$")
        assert c.qualified_symbol == "$"

    def test_qualified_symbol_needs_quoting(self):
        c = Commodity("MUTUAL FUND")
        assert c.qualified_symbol == '"MUTUAL FUND"'

    def test_qualified_symbol_with_digits(self):
        c = Commodity("H20")
        assert c.qualified_symbol == '"H20"'

    def test_note(self):
        c = Commodity("USD", note="US Dollar")
        assert c.note == "US Dollar"

    def test_has_flags(self):
        c = Commodity("$", flags=CommodityStyle.THOUSANDS | CommodityStyle.SEPARATED)
        assert c.has_flags(CommodityStyle.THOUSANDS)
        assert c.has_flags(CommodityStyle.SEPARATED)
        assert not c.has_flags(CommodityStyle.SUFFIXED)

    def test_add_flags(self):
        c = Commodity("$")
        c.add_flags(CommodityStyle.THOUSANDS)
        assert c.has_flags(CommodityStyle.THOUSANDS)
        c.add_flags(CommodityStyle.SEPARATED)
        assert c.has_flags(CommodityStyle.THOUSANDS | CommodityStyle.SEPARATED)

    def test_drop_flags(self):
        c = Commodity("$", flags=CommodityStyle.THOUSANDS | CommodityStyle.SEPARATED)
        c.drop_flags(CommodityStyle.THOUSANDS)
        assert not c.has_flags(CommodityStyle.THOUSANDS)
        assert c.has_flags(CommodityStyle.SEPARATED)

    def test_eq_same_symbol(self):
        c1 = Commodity("$")
        c2 = Commodity("$")
        assert c1 == c2

    def test_eq_different_symbol(self):
        c1 = Commodity("$")
        c2 = Commodity("EUR")
        assert c1 != c2

    def test_eq_string(self):
        c = Commodity("$")
        assert c == "$"
        assert c != "EUR"

    def test_hash_same_symbol(self):
        c1 = Commodity("$")
        c2 = Commodity("$")
        assert hash(c1) == hash(c2)

    def test_bool_truthy(self):
        c = Commodity("USD")
        assert bool(c) is True

    def test_bool_falsy_null(self):
        c = Commodity("")
        assert bool(c) is False

    def test_repr(self):
        c = Commodity("USD")
        assert repr(c) == "Commodity('USD')"

    def test_str(self):
        c = Commodity("USD")
        assert str(c) == "USD"

    def test_str_quoted(self):
        c = Commodity("MUTUAL FUND")
        assert str(c) == '"MUTUAL FUND"'


# ---------------------------------------------------------------------------
# CommodityPool
# ---------------------------------------------------------------------------


class TestCommodityPool:
    def test_pool_has_null_commodity(self):
        pool = CommodityPool()
        assert pool.null_commodity is not None
        assert pool.null_commodity.symbol == ""
        assert pool.null_commodity.has_flags(CommodityStyle.BUILTIN)
        assert pool.null_commodity.has_flags(CommodityStyle.NOMARKET)

    def test_create(self):
        pool = CommodityPool()
        c = pool.create("USD")
        assert c.symbol == "USD"
        assert pool.find("USD") is c

    def test_create_duplicate_raises(self):
        pool = CommodityPool()
        pool.create("USD")
        with pytest.raises(ValueError):
            pool.create("USD")

    def test_find_existing(self):
        pool = CommodityPool()
        c = pool.create("$")
        assert pool.find("$") is c

    def test_find_nonexistent(self):
        pool = CommodityPool()
        assert pool.find("NONEXISTENT") is None

    def test_find_or_create_new(self):
        pool = CommodityPool()
        c = pool.find_or_create("EUR")
        assert c.symbol == "EUR"

    def test_find_or_create_existing(self):
        pool = CommodityPool()
        c1 = pool.create("EUR")
        c2 = pool.find_or_create("EUR")
        assert c1 is c2

    def test_default_commodity(self):
        pool = CommodityPool()
        assert pool.default_commodity is None
        c = pool.create("USD")
        pool.default_commodity = c
        assert pool.default_commodity is c

    def test_len(self):
        pool = CommodityPool()
        # null commodity is created in __init__
        initial = len(pool)
        pool.create("USD")
        assert len(pool) == initial + 1

    def test_contains(self):
        pool = CommodityPool()
        pool.create("USD")
        assert "USD" in pool
        assert "EUR" not in pool

    def test_iter(self):
        pool = CommodityPool()
        pool.create("USD")
        pool.create("EUR")
        symbols = {c.symbol for c in pool}
        assert "USD" in symbols
        assert "EUR" in symbols

    def test_get_current_creates_pool(self):
        CommodityPool.reset_current()
        pool = CommodityPool.get_current()
        assert pool is not None
        assert CommodityPool.current_pool is pool

    def test_get_current_returns_same(self):
        pool1 = CommodityPool.get_current()
        pool2 = CommodityPool.get_current()
        assert pool1 is pool2


# ---------------------------------------------------------------------------
# Style learning
# ---------------------------------------------------------------------------


class TestStyleLearning:
    def test_learn_prefix_style(self):
        pool = CommodityPool()
        c = pool.learn_style("$", prefix=True, precision=2, thousands=True, separated=False)
        assert c.symbol == "$"
        assert c.precision == 2
        assert c.is_prefix is True
        assert c.has_flags(CommodityStyle.THOUSANDS)
        assert not c.has_flags(CommodityStyle.SEPARATED)

    def test_learn_suffix_style(self):
        pool = CommodityPool()
        c = pool.learn_style("EUR", prefix=False, precision=2, separated=True)
        assert c.symbol == "EUR"
        assert c.has_flags(CommodityStyle.SUFFIXED)
        assert c.has_flags(CommodityStyle.SEPARATED)

    def test_learn_precision_max(self):
        pool = CommodityPool()
        pool.learn_style("$", prefix=True, precision=2)
        c = pool.learn_style("$", prefix=True, precision=4)
        assert c.precision == 4

    def test_learn_precision_no_decrease(self):
        pool = CommodityPool()
        pool.learn_style("$", prefix=True, precision=4)
        c = pool.learn_style("$", prefix=True, precision=2)
        assert c.precision == 4

    def test_learn_flags_grow(self):
        pool = CommodityPool()
        pool.learn_style("$", prefix=True, precision=2)
        pool.learn_style("$", prefix=True, precision=2, thousands=True)
        c = pool.find("$")
        assert c.has_flags(CommodityStyle.THOUSANDS)

    def test_learn_decimal_comma(self):
        pool = CommodityPool()
        c = pool.learn_style("EUR", prefix=False, precision=2, decimal_comma=True, separated=True)
        assert c.has_flags(CommodityStyle.DECIMAL_COMMA)

    def test_learn_idempotent_commodity(self):
        pool = CommodityPool()
        c1 = pool.learn_style("$", prefix=True, precision=2)
        c2 = pool.learn_style("$", prefix=True, precision=2)
        assert c1 is c2


# ---------------------------------------------------------------------------
# Amount integration with Commodity
# ---------------------------------------------------------------------------


class TestAmountCommodityIntegration:
    def test_parsed_amount_has_commodity_object(self):
        a = Amount("$10.00")
        assert a.commodity_ptr is not None
        assert isinstance(a.commodity_ptr, Commodity)
        assert a.commodity_ptr.symbol == "$"

    def test_parsed_amount_commodity_string(self):
        a = Amount("$10.00")
        assert a.commodity == "$"

    def test_parsed_amount_learns_style(self):
        a = Amount("$1,000.00")
        c = a.commodity_ptr
        assert c is not None
        assert c.precision == 2
        assert c.is_prefix is True
        assert c.has_flags(CommodityStyle.THOUSANDS)

    def test_suffix_commodity_learns_style(self):
        a = Amount("10.50 EUR")
        c = a.commodity_ptr
        assert c is not None
        assert c.has_flags(CommodityStyle.SUFFIXED)
        assert c.has_flags(CommodityStyle.SEPARATED)

    def test_pool_shared_across_amounts(self):
        a1 = Amount("$10.00")
        a2 = Amount("$20.00")
        assert a1.commodity_ptr is a2.commodity_ptr

    def test_style_learning_from_parsing(self):
        """Parsing $1,000.00 should teach the pool about $ style."""
        Amount("$1,000.00")
        pool = CommodityPool.get_current()
        c = pool.find("$")
        assert c is not None
        assert c.precision == 2
        assert c.has_flags(CommodityStyle.THOUSANDS)
        assert c.is_prefix

    def test_commodity_precision_propagates(self):
        """If one amount teaches 2 decimals, another with 0 should display at 2."""
        Amount("$10.00")
        b = Amount("$5")
        # display_precision should use the commodity's learned precision
        assert b.display_precision() == 2

    def test_set_commodity_from_string(self):
        a = Amount(10)
        a.commodity = "USD"
        assert a.commodity == "USD"
        assert isinstance(a.commodity_ptr, Commodity)

    def test_set_commodity_from_commodity(self):
        c = Commodity("GBP")
        a = Amount(10)
        a.commodity = c
        assert a.commodity == "GBP"
        assert a.commodity_ptr is c

    def test_set_commodity_none(self):
        a = Amount("$10.00")
        a.commodity = None
        assert a.commodity is None
        assert not a.has_commodity()

    def test_number_strips_commodity(self):
        a = Amount("$10.00")
        n = a.number()
        assert n.commodity is None
        assert n.commodity_ptr is None

    def test_clear_commodity(self):
        a = Amount("$10.00")
        a.clear_commodity()
        assert a.commodity is None

    def test_amount_str_prefix(self):
        a = Amount("$10.00")
        assert str(a) == "$10.00"

    def test_amount_str_suffix(self):
        a = Amount("10.00 EUR")
        assert str(a) == "10.00 EUR"

    def test_amount_str_thousands(self):
        a = Amount("$1,000.00")
        assert str(a) == "$1,000.00"

    def test_amount_str_negative_prefix(self):
        a = Amount("-$42.50")
        assert str(a) == "$-42.50"

    def test_amount_with_quoted_commodity(self):
        a = Amount('10 "MUTUAL FUND"')
        assert a.commodity == "MUTUAL FUND"
        # The qualified_symbol should be quoted
        assert a.commodity_ptr.qualified_symbol == '"MUTUAL FUND"'

    def test_add_preserves_commodity_object(self):
        a = Amount("$10.00")
        b = Amount("$5.00")
        c = a + b
        assert c.commodity_ptr is a.commodity_ptr

    def test_arithmetic_different_commodities_raises(self):
        a = Amount("$10.00")
        b = Amount("10.00 EUR")
        with pytest.raises(AmountError):
            _ = a + b

    def test_construct_with_commodity_string(self):
        a = Amount(10, commodity="AAPL")
        assert a.commodity == "AAPL"
        assert isinstance(a.commodity_ptr, Commodity)

    def test_construct_with_commodity_object(self):
        c = Commodity("BTC")
        a = Amount(10, commodity=c)
        assert a.commodity == "BTC"
        assert a.commodity_ptr is c

    def test_has_commodity(self):
        assert Amount("$10").has_commodity()
        assert not Amount("10").has_commodity()

    def test_amount_hash_with_commodity(self):
        a = Amount("$10.00")
        b = Amount("$10.00")
        assert hash(a) == hash(b)

    def test_comparison_same_commodity(self):
        assert Amount("$10.00") == Amount("$10.00")
        assert Amount("$5.00") < Amount("$10.00")

    def test_comparison_different_commodities(self):
        assert Amount("$10.00") != Amount("10.00 EUR")

    def test_eq_with_int(self):
        assert Amount("$10") == 10


# ---------------------------------------------------------------------------
# Formatting with commodity flags
# ---------------------------------------------------------------------------


class TestCommodityFormatting:
    def test_format_with_thousands_from_commodity(self):
        """Even if parsing doesn't see thousands, commodity flags apply."""
        pool = CommodityPool.get_current()
        pool.learn_style("$", prefix=True, precision=2, thousands=True)
        a = Amount("$10000")
        # display_precision from commodity is 2, thousands from commodity
        assert str(a) == "$10,000.00"

    def test_format_suffix_separated(self):
        pool = CommodityPool.get_current()
        pool.learn_style("EUR", prefix=False, precision=2, separated=True)
        a = Amount("1000 EUR")
        assert "EUR" in str(a)
        assert str(a).endswith("EUR")

    def test_format_preserves_precision_from_commodity(self):
        Amount("$10.00")  # teaches precision=2
        a = Amount("$5")
        assert str(a) == "$5.00"

    def test_repr_with_commodity(self):
        a = Amount("$10.00")
        assert repr(a) == "Amount('$10.00')"
