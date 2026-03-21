"""Tests for lot annotation parsing and display.

Covers: {price}, {=price} (fixated), [date], (tag), combined annotations,
annotations with @ and @@ cost, round-trip parsing, and edge cases.
"""

from __future__ import annotations

import datetime
from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.annotate import Annotation
from muonledger.commodity import CommodityPool
from muonledger.journal import Journal
from muonledger.parser import (
    TextualParser,
    _parse_lot_annotation,
    _parse_lot_date,
    _split_amount_and_cost,
)


@pytest.fixture(autouse=True)
def _fresh_pool():
    """Reset the commodity pool before each test."""
    CommodityPool._current = CommodityPool()
    yield
    CommodityPool._current = CommodityPool()


# ---------------------------------------------------------------------------
# Helper to parse a journal string and return the first transaction
# ---------------------------------------------------------------------------

def _parse(text: str) -> Journal:
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _first_post(text: str):
    journal = _parse(text)
    assert journal.xacts, "Expected at least one transaction"
    xact = journal.xacts[0]
    assert xact.posts, "Expected at least one posting"
    return xact.posts[0]


# ===========================================================================
# _parse_lot_date tests
# ===========================================================================


class TestParseLotDate:
    def test_slash_format(self):
        assert _parse_lot_date("2024/01/15") == datetime.date(2024, 1, 15)

    def test_dash_format(self):
        assert _parse_lot_date("2024-01-15") == datetime.date(2024, 1, 15)

    def test_dot_format(self):
        assert _parse_lot_date("2024.01.15") == datetime.date(2024, 1, 15)

    def test_invalid_date(self):
        with pytest.raises(ValueError, match="Cannot parse lot date"):
            _parse_lot_date("not-a-date")

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            _parse_lot_date("2024/13/01")


# ===========================================================================
# _parse_lot_annotation unit tests
# ===========================================================================


class TestParseLotAnnotation:
    def test_no_annotation(self):
        amt, ann = _parse_lot_annotation("$100.00")
        assert amt == "$100.00"
        assert ann is None

    def test_price_only(self):
        amt, ann = _parse_lot_annotation("10 AAPL {$50.00}")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.price is not None
        assert str(ann.price) == "$50.00"

    def test_fixated_price(self):
        amt, ann = _parse_lot_annotation("10 AAPL {=$50.00}")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.price is not None
        assert ann.has_flags(Annotation.PRICE_FIXATED)

    def test_date_only(self):
        amt, ann = _parse_lot_annotation("10 AAPL [2024-01-15]")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.date == datetime.date(2024, 1, 15)

    def test_tag_only(self):
        amt, ann = _parse_lot_annotation("10 AAPL (buy)")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.tag == "buy"

    def test_price_and_date(self):
        amt, ann = _parse_lot_annotation("10 AAPL {$50.00} [2024-01-15]")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.price is not None
        assert ann.date == datetime.date(2024, 1, 15)

    def test_all_three(self):
        amt, ann = _parse_lot_annotation("10 AAPL {$50.00} [2024-01-15] (buy)")
        assert amt == "10 AAPL"
        assert ann is not None
        assert ann.price is not None
        assert ann.date == datetime.date(2024, 1, 15)
        assert ann.tag == "buy"

    def test_fixated_with_date_and_tag(self):
        amt, ann = _parse_lot_annotation("5 GOOG {=$120.00} [2023-06-01] (lot1)")
        assert amt == "5 GOOG"
        assert ann is not None
        assert ann.has_flags(Annotation.PRICE_FIXATED)
        assert ann.date == datetime.date(2023, 6, 1)
        assert ann.tag == "lot1"

    def test_unclosed_brace_returns_none(self):
        amt, ann = _parse_lot_annotation("10 AAPL {$50.00")
        # Unclosed brace returns original text, None annotation
        assert ann is None

    def test_unclosed_bracket_returns_none(self):
        amt, ann = _parse_lot_annotation("10 AAPL [2024-01-15")
        assert ann is None

    def test_unclosed_paren_returns_none(self):
        amt, ann = _parse_lot_annotation("10 AAPL (buy")
        assert ann is None

    def test_empty_string(self):
        amt, ann = _parse_lot_annotation("")
        assert amt == ""
        assert ann is None

    def test_date_slash_format_in_annotation(self):
        amt, ann = _parse_lot_annotation("10 AAPL [2024/01/15]")
        assert ann is not None
        assert ann.date == datetime.date(2024, 1, 15)

    def test_tag_with_spaces(self):
        amt, ann = _parse_lot_annotation("10 AAPL (initial purchase)")
        assert ann is not None
        assert ann.tag == "initial purchase"

    def test_prefix_commodity_with_annotation(self):
        amt, ann = _parse_lot_annotation("$500 {$50.00}")
        assert amt == "$500"
        assert ann is not None
        assert ann.price is not None


# ===========================================================================
# _split_amount_and_cost with lot annotations
# ===========================================================================


class TestSplitAmountAndCostWithAnnotations:
    def test_annotation_before_cost(self):
        amt, cost, is_total = _split_amount_and_cost(
            "10 AAPL {$50.00} @ $55.00"
        )
        assert "AAPL" in amt
        assert "{$50.00}" in amt
        assert cost is not None
        assert "$55.00" in cost
        assert not is_total

    def test_annotation_before_total_cost(self):
        amt, cost, is_total = _split_amount_and_cost(
            "10 AAPL {$50.00} @@ $550.00"
        )
        assert "{$50.00}" in amt
        assert cost is not None
        assert is_total

    def test_all_annotations_before_cost(self):
        amt, cost, is_total = _split_amount_and_cost(
            "10 AAPL {$50.00} [2024-01-15] (buy) @ $55.00"
        )
        assert "{$50.00}" in amt
        assert "[2024-01-15]" in amt
        assert "(buy)" in amt
        assert cost is not None
        assert not is_total

    def test_no_cost_with_annotations(self):
        amt, cost, is_total = _split_amount_and_cost(
            "10 AAPL {$50.00} [2024-01-15]"
        )
        assert cost is None
        assert not is_total


# ===========================================================================
# Full parser integration tests
# ===========================================================================


class TestParserLotAnnotations:
    def test_basic_lot_price(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00}\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.price is not None
        assert str(post.annotation.price) == "$50.00"

    def test_fixated_lot_price(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {=$50.00}\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.has_flags(Annotation.PRICE_FIXATED)

    def test_lot_date(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL [2024-01-15]\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.date == datetime.date(2024, 1, 15)

    def test_lot_tag(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL (initial)\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.tag == "initial"

    def test_combined_price_date_tag(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$150.00} [2024-01-15] (buy)\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.price is not None
        assert post.annotation.date == datetime.date(2024, 1, 15)
        assert post.annotation.tag == "buy"

    def test_annotation_with_per_unit_cost(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @ $55.00\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.price is not None
        assert str(post.annotation.price) == "$50.00"
        assert post.cost is not None

    def test_annotation_with_total_cost(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @@ $550.00\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert str(post.annotation.price) == "$50.00"
        assert post.cost is not None

    def test_no_annotation(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is None

    def test_no_annotation_with_cost(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL @ $55.00\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is None
        assert post.cost is not None

    def test_amount_preserved_with_annotation(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00}\n"
            "    Assets:Checking\n"
        )
        assert post.amount is not None
        assert post.amount.quantity == Fraction(10)
        assert post.amount.commodity == "AAPL"

    def test_amount_preserved_with_all_annotations(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} [2024-01-15] (buy) @ $55.00\n"
            "    Assets:Checking\n"
        )
        assert post.amount is not None
        assert post.amount.quantity == Fraction(10)
        assert post.amount.commodity == "AAPL"
        assert post.annotation is not None
        assert post.cost is not None

    def test_negative_amount_with_annotation(self):
        post = _first_post(
            "2024/06/15 Sell stock\n"
            "    Assets:Brokerage  -5 AAPL {$50.00} @ $60.00\n"
            "    Assets:Checking\n"
        )
        assert post.amount is not None
        assert post.amount.quantity == Fraction(-5)
        assert post.annotation is not None
        assert str(post.annotation.price) == "$50.00"

    def test_annotation_with_inline_comment(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} ; some note\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.note is not None
        assert "some note" in post.note

    def test_annotation_with_cost_and_comment(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @ $55.00 ; note\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.cost is not None
        assert post.note is not None

    def test_lot_price_decimal(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  100 AAPL {150.5025 GBP}\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.annotation.price is not None
        # Check the numeric value
        assert float(post.annotation.price.quantity) == pytest.approx(150.5025)


# ===========================================================================
# Annotation __str__ round-trip tests
# ===========================================================================


class TestAnnotationDisplay:
    def test_price_only_str(self):
        ann = Annotation(price=Amount("$50.00"))
        s = str(ann)
        assert s.startswith("{$")
        assert "50" in s
        assert s.endswith("}")

    def test_fixated_price_str(self):
        ann = Annotation(price=Amount("$50.00"), flags=Annotation.PRICE_FIXATED)
        s = str(ann)
        assert s.startswith("{=$")
        assert "50" in s

    def test_date_only_str(self):
        ann = Annotation(date=datetime.date(2024, 1, 15))
        s = str(ann)
        assert "[2024/01/15]" in s

    def test_tag_only_str(self):
        ann = Annotation(tag="buy")
        s = str(ann)
        assert "(buy)" in s

    def test_full_str(self):
        ann = Annotation(
            price=Amount("$50.00"),
            date=datetime.date(2024, 1, 15),
            tag="buy",
        )
        s = str(ann)
        assert "{$" in s and "50" in s
        assert "[2024/01/15]" in s
        assert "(buy)" in s

    def test_empty_str(self):
        ann = Annotation()
        assert str(ann) == ""


# ===========================================================================
# Print command round-trip
# ===========================================================================


class TestPrintRoundTrip:
    def _print_journal(self, text: str) -> str:
        from muonledger.commands.print_cmd import print_command
        journal = _parse(text)
        return print_command(journal)

    def test_roundtrip_lot_price(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "{$" in output and "50" in output

    def test_roundtrip_fixated_price(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {=$50.00} @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "{=$" in output and "50" in output

    def test_roundtrip_lot_date(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL [2024/01/15] @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "[2024/01/15]" in output

    def test_roundtrip_lot_tag(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL (buy) @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "(buy)" in output

    def test_roundtrip_full_annotation(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} [2024/01/15] (buy) @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "{$" in output
        assert "[2024/01/15]" in output
        assert "(buy)" in output

    def test_roundtrip_annotation_with_cost(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @ $55.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "{$" in output
        assert "@ $" in output

    def test_roundtrip_annotation_with_total_cost(self):
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @@ $550.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        assert "{$" in output
        assert "@@" in output

    def test_reparse_printed_annotation(self):
        """Parse, print, re-parse: annotation should survive."""
        text = (
            "2024/01/15 Buy stock\n"
            "    Assets:Brokerage  10 AAPL {$50.00} [2024/01/15] (buy) @ $50.00\n"
            "    Assets:Checking\n"
        )
        output = self._print_journal(text)
        # Re-parse the printed output
        journal2 = _parse(output)
        post2 = journal2.xacts[0].posts[0]
        assert post2.annotation is not None
        assert post2.annotation.price is not None
        assert post2.annotation.date == datetime.date(2024, 1, 15)
        assert post2.annotation.tag == "buy"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_annotation_on_second_posting(self):
        journal = _parse(
            "2024/01/15 Trade\n"
            "    Assets:Brokerage  10 AAPL {$50.00} @ $50.00\n"
            "    Assets:Checking\n"
        )
        post1 = journal.xacts[0].posts[0]
        post2 = journal.xacts[0].posts[1]
        assert post1.annotation is not None
        assert post2.annotation is None

    def test_multiple_commodities_with_annotations(self):
        # Each posting with a separate cost so the xact can balance
        journal = _parse(
            "2024/01/15 Trade\n"
            "    Assets:Stock  10 AAPL {$150.00} @ $150.00\n"
            "    Assets:Checking  $-1500.00\n"
        )
        post1 = journal.xacts[0].posts[0]
        assert post1.annotation is not None
        assert "150" in str(post1.annotation.price)

    def test_annotation_with_virtual_posting(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    (Assets:Brokerage)  10 AAPL {$50.00}\n"
            "    Assets:Checking\n"
        )
        assert post.annotation is not None
        assert post.is_virtual()

    def test_annotation_with_balanced_virtual(self):
        post = _first_post(
            "2024/01/15 Buy stock\n"
            "    [Assets:Brokerage]  10 AAPL {$50.00} @ $50.00\n"
            "    [Assets:Checking]\n"
        )
        assert post.annotation is not None
        assert post.is_virtual()
        assert post.must_balance()

    def test_annotation_is_empty(self):
        ann = Annotation()
        assert ann.is_empty()
        assert not bool(ann)

    def test_annotation_not_empty_with_price(self):
        ann = Annotation(price=Amount("$50.00"))
        assert not ann.is_empty()
        assert bool(ann)

    def test_annotation_not_empty_with_date(self):
        ann = Annotation(date=datetime.date(2024, 1, 15))
        assert not ann.is_empty()

    def test_annotation_not_empty_with_tag(self):
        ann = Annotation(tag="lot1")
        assert not ann.is_empty()

    def test_annotation_equality(self):
        a = Annotation(price=Amount("$50.00"), date=datetime.date(2024, 1, 15))
        b = Annotation(price=Amount("$50.00"), date=datetime.date(2024, 1, 15))
        assert a == b

    def test_annotation_inequality(self):
        a = Annotation(price=Amount("$50.00"))
        b = Annotation(price=Amount("$60.00"))
        assert a != b

    def test_fixated_vs_non_fixated_not_equal(self):
        a = Annotation(price=Amount("$50.00"))
        b = Annotation(price=Amount("$50.00"), flags=Annotation.PRICE_FIXATED)
        assert a != b

    def test_date_with_dot_format(self):
        amt, ann = _parse_lot_annotation("10 AAPL [2024.01.15]")
        assert ann is not None
        assert ann.date == datetime.date(2024, 1, 15)

    def test_price_with_european_commodity(self):
        amt, ann = _parse_lot_annotation('10 "MUTUAL FUND" {$50.00}')
        assert amt == '10 "MUTUAL FUND"'
        assert ann is not None
        assert ann.price is not None
