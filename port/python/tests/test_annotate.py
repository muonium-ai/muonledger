"""Tests for the Annotation, KeepDetails, and AnnotatedCommodity classes."""

import datetime

import pytest

from muonledger.amount import Amount
from muonledger.commodity import Commodity, CommodityPool
from muonledger.annotate import Annotation, AnnotatedCommodity, KeepDetails


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
# Annotation basics
# ---------------------------------------------------------------------------

class TestAnnotation:
    def test_empty_by_default(self):
        a = Annotation()
        assert a.is_empty()
        assert not a

    def test_bool_with_price(self):
        a = Annotation(price=Amount("$10"))
        assert not a.is_empty()
        assert a

    def test_bool_with_date(self):
        a = Annotation(date=datetime.date(2024, 1, 15))
        assert a

    def test_bool_with_tag(self):
        a = Annotation(tag="lot1")
        assert a

    def test_bool_with_value_expr(self):
        a = Annotation(value_expr="market(amount, date, t)")
        assert a

    def test_equality_empty(self):
        assert Annotation() == Annotation()

    def test_equality_with_price(self):
        a = Annotation(price=Amount("$10"))
        b = Annotation(price=Amount("$10"))
        assert a == b

    def test_inequality_different_price(self):
        a = Annotation(price=Amount("$10"))
        b = Annotation(price=Amount("$20"))
        assert a != b

    def test_equality_with_date(self):
        d = datetime.date(2024, 6, 15)
        assert Annotation(date=d) == Annotation(date=d)

    def test_inequality_different_date(self):
        a = Annotation(date=datetime.date(2024, 1, 1))
        b = Annotation(date=datetime.date(2024, 6, 1))
        assert a != b

    def test_equality_with_tag(self):
        assert Annotation(tag="lot1") == Annotation(tag="lot1")

    def test_inequality_different_tag(self):
        assert Annotation(tag="lot1") != Annotation(tag="lot2")

    def test_equality_with_value_expr(self):
        assert Annotation(value_expr="expr1") == Annotation(value_expr="expr1")

    def test_inequality_different_value_expr(self):
        assert Annotation(value_expr="expr1") != Annotation(value_expr="expr2")

    def test_equality_with_all_fields(self):
        kwargs = dict(
            price=Amount("$10"),
            date=datetime.date(2024, 1, 15),
            tag="lot1",
            value_expr="market()",
        )
        assert Annotation(**kwargs) == Annotation(**kwargs)

    def test_fixated_flag_affects_equality(self):
        """A fixated annotation is not equal to a non-fixated one."""
        a = Annotation(price=Amount("$10"))
        b = Annotation(price=Amount("$10"))
        b.add_flags(Annotation.PRICE_FIXATED)
        assert a != b

    def test_calculated_flag_does_not_affect_equality(self):
        """PRICE_CALCULATED is not a semantic flag, so equality ignores it."""
        a = Annotation(price=Amount("$10"))
        b = Annotation(price=Amount("$10"))
        b.add_flags(Annotation.PRICE_CALCULATED)
        assert a == b

    def test_hash_equal_annotations(self):
        a = Annotation(price=Amount("$10"), tag="lot1")
        b = Annotation(price=Amount("$10"), tag="lot1")
        assert hash(a) == hash(b)

    def test_hash_different_annotations(self):
        a = Annotation(tag="lot1")
        b = Annotation(tag="lot2")
        # Hashes may collide, but typically won't for simple cases.
        # Just ensure both are hashable.
        {a, b}  # should not raise

    def test_str_price_only(self):
        a = Annotation(price=Amount("$10"))
        assert str(a) == "{$10}"

    def test_str_fixated_price(self):
        a = Annotation(price=Amount("$50"))
        a.add_flags(Annotation.PRICE_FIXATED)
        assert str(a) == "{=$50}"

    def test_str_date_only(self):
        a = Annotation(date=datetime.date(2024, 1, 15))
        assert str(a) == "[2024/01/15]"

    def test_str_tag_only(self):
        a = Annotation(tag="lot1")
        assert str(a) == "(lot1)"

    def test_str_value_expr_only(self):
        a = Annotation(value_expr="market()")
        assert str(a) == "((market()))"

    def test_str_all_fields(self):
        a = Annotation(
            price=Amount("$10"),
            date=datetime.date(2024, 1, 15),
            tag="lot1",
            value_expr="market()",
        )
        assert str(a) == "{$10} [2024/01/15] (lot1) ((market()))"

    def test_str_empty(self):
        assert str(Annotation()) == ""

    def test_ordering_absent_before_present(self):
        empty = Annotation()
        with_tag = Annotation(tag="lot1")
        assert empty < with_tag

    def test_ordering_by_date(self):
        a = Annotation(date=datetime.date(2024, 1, 1))
        b = Annotation(date=datetime.date(2024, 6, 1))
        assert a < b
        assert not b < a

    def test_ordering_by_tag(self):
        a = Annotation(tag="aaa")
        b = Annotation(tag="zzz")
        assert a < b

    def test_not_equal_to_non_annotation(self):
        assert Annotation() != "not an annotation"


# ---------------------------------------------------------------------------
# Annotation flags
# ---------------------------------------------------------------------------

class TestAnnotationFlags:
    def test_add_and_check_flags(self):
        a = Annotation()
        assert not a.has_flags(Annotation.PRICE_CALCULATED)
        a.add_flags(Annotation.PRICE_CALCULATED)
        assert a.has_flags(Annotation.PRICE_CALCULATED)

    def test_drop_flags(self):
        a = Annotation()
        a.add_flags(Annotation.PRICE_FIXATED | Annotation.PRICE_CALCULATED)
        a.drop_flags(Annotation.PRICE_CALCULATED)
        assert a.has_flags(Annotation.PRICE_FIXATED)
        assert not a.has_flags(Annotation.PRICE_CALCULATED)

    def test_multiple_flags(self):
        a = Annotation()
        a.add_flags(Annotation.PRICE_CALCULATED | Annotation.DATE_CALCULATED)
        assert a.has_flags(Annotation.PRICE_CALCULATED)
        assert a.has_flags(Annotation.DATE_CALCULATED)
        assert not a.has_flags(Annotation.TAG_CALCULATED)


# ---------------------------------------------------------------------------
# KeepDetails
# ---------------------------------------------------------------------------

class TestKeepDetails:
    def test_defaults_keep_nothing(self):
        kd = KeepDetails()
        assert not kd.keep_any()

    def test_keep_any_with_price(self):
        kd = KeepDetails(keep_price=True)
        assert kd.keep_any()

    def test_keep_any_with_date(self):
        kd = KeepDetails(keep_date=True)
        assert kd.keep_any()

    def test_keep_any_with_tag(self):
        kd = KeepDetails(keep_tag=True)
        assert kd.keep_any()

    def test_keep_any_with_keep_all(self):
        kd = KeepDetails(keep_all=True)
        assert kd.keep_any()

    def test_should_keep_strips_all_by_default(self):
        ann = Annotation(
            price=Amount("$10"),
            date=datetime.date(2024, 1, 1),
            tag="lot1",
        )
        kd = KeepDetails()
        result = kd.should_keep(ann)
        assert result.price is None
        assert result.date is None
        assert result.tag is None

    def test_should_keep_price_only(self):
        ann = Annotation(
            price=Amount("$10"),
            date=datetime.date(2024, 1, 1),
            tag="lot1",
        )
        kd = KeepDetails(keep_price=True)
        result = kd.should_keep(ann)
        assert result.price == Amount("$10")
        assert result.date is None
        assert result.tag is None

    def test_should_keep_date_only(self):
        d = datetime.date(2024, 6, 15)
        ann = Annotation(price=Amount("$10"), date=d, tag="lot1")
        kd = KeepDetails(keep_date=True)
        result = kd.should_keep(ann)
        assert result.price is None
        assert result.date == d
        assert result.tag is None

    def test_should_keep_tag_only(self):
        ann = Annotation(price=Amount("$10"), date=datetime.date(2024, 1, 1), tag="lot1")
        kd = KeepDetails(keep_tag=True)
        result = kd.should_keep(ann)
        assert result.price is None
        assert result.date is None
        assert result.tag == "lot1"

    def test_should_keep_all(self):
        d = datetime.date(2024, 1, 15)
        ann = Annotation(price=Amount("$10"), date=d, tag="lot1", value_expr="market()")
        kd = KeepDetails(keep_all=True)
        result = kd.should_keep(ann)
        assert result.price == Amount("$10")
        assert result.date == d
        assert result.tag == "lot1"
        assert result.value_expr == "market()"

    def test_should_keep_empty_annotation(self):
        kd = KeepDetails(keep_all=True)
        result = kd.should_keep(Annotation())
        assert result.is_empty()

    def test_should_keep_with_only_actuals_strips_calculated(self):
        ann = Annotation(price=Amount("$10"), date=datetime.date(2024, 1, 1))
        ann.add_flags(Annotation.PRICE_CALCULATED)
        kd = KeepDetails(keep_price=True, keep_date=True, only_actuals=True)
        result = kd.should_keep(ann)
        # Price was calculated, so it should be stripped.
        assert result.price is None
        # Date was not calculated, so it survives.
        assert result.date == datetime.date(2024, 1, 1)

    def test_should_keep_only_actuals_keeps_non_calculated(self):
        ann = Annotation(price=Amount("$10"), tag="lot1")
        # Neither is calculated.
        kd = KeepDetails(keep_price=True, keep_tag=True, only_actuals=True)
        result = kd.should_keep(ann)
        assert result.price == Amount("$10")
        assert result.tag == "lot1"

    def test_should_keep_preserves_fixated_flag(self):
        ann = Annotation(price=Amount("$50"))
        ann.add_flags(Annotation.PRICE_FIXATED)
        kd = KeepDetails(keep_price=True)
        result = kd.should_keep(ann)
        assert result.has_flags(Annotation.PRICE_FIXATED)

    def test_should_keep_all_with_only_actuals_strips_calculated_date(self):
        ann = Annotation(
            price=Amount("$10"),
            date=datetime.date(2024, 1, 1),
            tag="lot1",
        )
        ann.add_flags(Annotation.DATE_CALCULATED)
        kd = KeepDetails(keep_all=True, only_actuals=True)
        result = kd.should_keep(ann)
        assert result.price == Amount("$10")
        assert result.date is None  # calculated, so stripped
        assert result.tag == "lot1"

    def test_should_keep_value_expr_not_calculated(self):
        """Non-calculated value_expr is always preserved."""
        ann = Annotation(value_expr="market()")
        kd = KeepDetails()  # keep nothing
        result = kd.should_keep(ann)
        assert result.value_expr == "market()"

    def test_should_keep_value_expr_calculated_is_stripped(self):
        """Calculated value_expr is stripped."""
        ann = Annotation(value_expr="market()")
        ann.add_flags(Annotation.VALUE_EXPR_CALCULATED)
        kd = KeepDetails()
        result = kd.should_keep(ann)
        assert result.value_expr is None


# ---------------------------------------------------------------------------
# AnnotatedCommodity
# ---------------------------------------------------------------------------

class TestAnnotatedCommodity:
    def test_creation(self):
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), date=datetime.date(2024, 1, 15))
        ac = AnnotatedCommodity(comm, ann)
        assert ac.commodity is comm
        assert ac.annotation is ann

    def test_symbol_delegation(self):
        comm = Commodity("EUR")
        ac = AnnotatedCommodity(comm, Annotation(tag="lot1"))
        assert ac.symbol == "EUR"
        assert ac.qualified_symbol == "EUR"

    def test_equality_same(self):
        comm = Commodity("$")
        ann = Annotation(tag="lot1")
        a = AnnotatedCommodity(comm, ann)
        b = AnnotatedCommodity(comm, Annotation(tag="lot1"))
        assert a == b

    def test_inequality_different_annotation(self):
        comm = Commodity("$")
        a = AnnotatedCommodity(comm, Annotation(tag="lot1"))
        b = AnnotatedCommodity(comm, Annotation(tag="lot2"))
        assert a != b

    def test_inequality_different_commodity(self):
        a = AnnotatedCommodity(Commodity("$"), Annotation(tag="lot1"))
        b = AnnotatedCommodity(Commodity("EUR"), Annotation(tag="lot1"))
        assert a != b

    def test_equality_with_plain_commodity_empty_annotation(self):
        comm = Commodity("$")
        ac = AnnotatedCommodity(comm, Annotation())
        assert ac == comm

    def test_inequality_with_plain_commodity_nonempty_annotation(self):
        comm = Commodity("$")
        ac = AnnotatedCommodity(comm, Annotation(tag="lot1"))
        assert ac != comm

    def test_hash(self):
        comm = Commodity("AAPL")
        ann = Annotation(tag="lot1")
        a = AnnotatedCommodity(comm, ann)
        b = AnnotatedCommodity(comm, Annotation(tag="lot1"))
        assert hash(a) == hash(b)
        # Usable in sets.
        {a, b}

    def test_str_with_annotation(self):
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), tag="lot1")
        ac = AnnotatedCommodity(comm, ann)
        s = str(ac)
        assert "AAPL" in s
        assert "{$150}" in s
        assert "(lot1)" in s

    def test_str_empty_annotation(self):
        comm = Commodity("$")
        ac = AnnotatedCommodity(comm, Annotation())
        assert str(ac) == "$"

    def test_repr(self):
        comm = Commodity("$")
        ac = AnnotatedCommodity(comm, Annotation(tag="x"))
        r = repr(ac)
        assert "AnnotatedCommodity" in r

    def test_strip_annotations_keep_nothing(self):
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), date=datetime.date(2024, 1, 1), tag="lot1")
        ac = AnnotatedCommodity(comm, ann)
        result = ac.strip_annotations(KeepDetails())
        # No fields kept, should return the base commodity.
        assert isinstance(result, Commodity)
        assert result is comm

    def test_strip_annotations_keep_price(self):
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), date=datetime.date(2024, 1, 1), tag="lot1")
        ac = AnnotatedCommodity(comm, ann)
        result = ac.strip_annotations(KeepDetails(keep_price=True))
        assert isinstance(result, AnnotatedCommodity)
        assert result.annotation.price == Amount("$150")
        assert result.annotation.date is None
        assert result.annotation.tag is None

    def test_strip_annotations_keep_all(self):
        d = datetime.date(2024, 1, 15)
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), date=d, tag="lot1")
        ac = AnnotatedCommodity(comm, ann)
        result = ac.strip_annotations(KeepDetails(keep_all=True))
        assert isinstance(result, AnnotatedCommodity)
        assert result.annotation.price == Amount("$150")
        assert result.annotation.date == d
        assert result.annotation.tag == "lot1"

    def test_strip_annotations_returns_base_when_no_value_expr(self):
        """When only a value_expr survives but no price/date/tag, the
        annotation is still truthy, so an AnnotatedCommodity is returned."""
        comm = Commodity("AAPL")
        ann = Annotation(value_expr="market()")
        ac = AnnotatedCommodity(comm, ann)
        result = ac.strip_annotations(KeepDetails())
        # value_expr is not calculated, so it survives.
        assert isinstance(result, AnnotatedCommodity)
        assert result.annotation.value_expr == "market()"

    def test_strip_annotations_only_actuals(self):
        comm = Commodity("AAPL")
        ann = Annotation(price=Amount("$150"), tag="lot1")
        ann.add_flags(Annotation.PRICE_CALCULATED)
        ac = AnnotatedCommodity(comm, ann)
        result = ac.strip_annotations(
            KeepDetails(keep_price=True, keep_tag=True, only_actuals=True)
        )
        assert isinstance(result, AnnotatedCommodity)
        # Price was calculated, stripped by only_actuals.
        assert result.annotation.price is None
        # Tag was not calculated, so it survives.
        assert result.annotation.tag == "lot1"

    def test_not_equal_to_unrelated_type(self):
        comm = Commodity("$")
        ac = AnnotatedCommodity(comm, Annotation())
        assert ac != 42
