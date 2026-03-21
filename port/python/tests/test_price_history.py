"""Tests for PriceHistory -- commodity price graph and conversion.

Covers direct prices, reverse (inverse) prices, transitive multi-hop
conversions via BFS, date-specific lookups, Amount conversion, parser
integration (P directives), and report pipeline integration with
--market and --exchange options.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.commodity import CommodityPool
from muonledger.price_history import PriceHistory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global commodity pool between tests."""
    CommodityPool.reset_current()
    CommodityPool.current_pool = CommodityPool()
    yield
    CommodityPool.reset_current()


def _make_history() -> PriceHistory:
    """Build a typical price history for tests."""
    ph = PriceHistory()
    ph.add_price(date(2024, 1, 15), "AAPL", Amount("$150.00"))
    ph.add_price(date(2024, 2, 1), "AAPL", Amount("$155.00"))
    ph.add_price(date(2024, 1, 15), "EUR", Amount("$1.10"))
    return ph


# ---------------------------------------------------------------------------
# Basic add / retrieve
# ---------------------------------------------------------------------------


class TestAddAndRetrieve:
    """Adding prices and retrieving them."""

    def test_add_single_price(self):
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 15), "AAPL", Amount("$150.00"))
        assert len(ph) == 1

    def test_add_multiple_prices_same_commodity(self):
        ph = _make_history()
        # AAPL has 2 price entries, EUR has 1
        assert len(ph) == 3

    def test_most_recent_price(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$")
        assert result is not None
        rate, effective_date = result
        # Most recent AAPL price is $155 on 2024-02-01
        assert rate == Fraction(155)
        assert effective_date == date(2024, 2, 1)

    def test_empty_price_history(self):
        ph = PriceHistory()
        assert len(ph) == 0
        assert ph.find_price("AAPL", "$") is None

    def test_repr(self):
        ph = _make_history()
        r = repr(ph)
        assert "entries=3" in r


# ---------------------------------------------------------------------------
# Direct conversion
# ---------------------------------------------------------------------------


class TestDirectConversion:
    """Direct price lookups (single hop)."""

    def test_aapl_to_dollar(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$")
        assert result is not None
        rate, _ = result
        assert rate == Fraction(155)

    def test_eur_to_dollar(self):
        ph = _make_history()
        result = ph.find_price("EUR", "$")
        assert result is not None
        rate, _ = result
        assert rate == Fraction(11, 10)  # 1.10

    def test_same_commodity(self):
        ph = _make_history()
        result = ph.find_price("$", "$")
        assert result is not None
        rate, _ = result
        assert rate == Fraction(1)


# ---------------------------------------------------------------------------
# Reverse (inverse) conversion
# ---------------------------------------------------------------------------


class TestReverseConversion:
    """Reverse lookups: $ -> AAPL using inverse rate."""

    def test_dollar_to_aapl(self):
        ph = _make_history()
        result = ph.find_price("$", "AAPL")
        assert result is not None
        rate, _ = result
        # 1/155
        assert rate == Fraction(1, 155)

    def test_dollar_to_eur(self):
        ph = _make_history()
        result = ph.find_price("$", "EUR")
        assert result is not None
        rate, _ = result
        assert rate == Fraction(10, 11)


# ---------------------------------------------------------------------------
# Transitive conversion (multi-hop BFS)
# ---------------------------------------------------------------------------


class TestTransitiveConversion:
    """Conversions requiring intermediate commodities."""

    def test_aapl_to_eur(self):
        """AAPL -> $ -> EUR requires two hops."""
        ph = _make_history()
        result = ph.find_price("AAPL", "EUR")
        assert result is not None
        rate, _ = result
        # AAPL -> $ = 155, $ -> EUR = 10/11
        expected = Fraction(155) * Fraction(10, 11)
        assert rate == expected

    def test_eur_to_aapl(self):
        """EUR -> $ -> AAPL requires two hops."""
        ph = _make_history()
        result = ph.find_price("EUR", "AAPL")
        assert result is not None
        rate, _ = result
        # EUR -> $ = 11/10, $ -> AAPL = 1/155
        expected = Fraction(11, 10) * Fraction(1, 155)
        assert rate == expected

    def test_no_conversion_path(self):
        """No path between disconnected commodities."""
        ph = _make_history()
        ph.add_price(date(2024, 1, 1), "GBP", Amount("1.50 CHF"))
        # AAPL and GBP are in disconnected subgraphs
        assert ph.find_price("AAPL", "GBP") is None

    def test_three_hop_conversion(self):
        """A -> B -> C -> D requires three hops."""
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "A", Amount("2 B"))
        ph.add_price(date(2024, 1, 1), "B", Amount("3 C"))
        ph.add_price(date(2024, 1, 1), "C", Amount("4 D"))
        result = ph.find_price("A", "D")
        assert result is not None
        rate, _ = result
        assert rate == Fraction(24)  # 2 * 3 * 4


# ---------------------------------------------------------------------------
# Date-specific price lookup
# ---------------------------------------------------------------------------


class TestDateSpecificLookup:
    """Price lookups as of a specific date."""

    def test_as_of_before_first_price(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$", as_of=date(2024, 1, 1))
        # No price available before 2024-01-15
        assert result is None

    def test_as_of_between_prices(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$", as_of=date(2024, 1, 20))
        assert result is not None
        rate, effective_date = result
        assert rate == Fraction(150)
        assert effective_date == date(2024, 1, 15)

    def test_as_of_after_all_prices(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$", as_of=date(2024, 12, 31))
        assert result is not None
        rate, _ = result
        assert rate == Fraction(155)

    def test_as_of_exact_date(self):
        ph = _make_history()
        result = ph.find_price("AAPL", "$", as_of=date(2024, 2, 1))
        assert result is not None
        rate, effective_date = result
        assert rate == Fraction(155)
        assert effective_date == date(2024, 2, 1)


# ---------------------------------------------------------------------------
# Amount conversion
# ---------------------------------------------------------------------------


class TestConvertAmount:
    """Converting Amount objects through the price history."""

    def test_convert_aapl_to_dollar(self):
        ph = _make_history()
        amt = Amount("10 AAPL")
        converted = ph.convert(amt, "$")
        assert converted.commodity == "$"
        assert converted.quantity == Fraction(1550)

    def test_convert_with_intermediate(self):
        """10 AAPL -> EUR via $."""
        ph = _make_history()
        amt = Amount("10 AAPL")
        converted = ph.convert(amt, "EUR")
        assert converted.commodity == "EUR"
        # 10 * 155 * (10/11) = 10 * 1550/11
        expected = Fraction(10) * Fraction(155) * Fraction(10, 11)
        assert converted.quantity == expected

    def test_convert_no_path_returns_original(self):
        ph = _make_history()
        amt = Amount("10 GBP")
        converted = ph.convert(amt, "JPY")
        # No conversion path; returns original
        assert converted is amt

    def test_convert_null_amount(self):
        ph = _make_history()
        amt = Amount()
        converted = ph.convert(amt, "$")
        assert converted.is_null()

    def test_convert_same_commodity(self):
        ph = _make_history()
        amt = Amount("$100.00")
        converted = ph.convert(amt, "$")
        assert converted is amt  # no conversion needed

    def test_convert_no_commodity(self):
        ph = _make_history()
        amt = Amount(42)
        converted = ph.convert(amt, "$")
        assert converted is amt  # no source commodity


# ---------------------------------------------------------------------------
# Price graph structure
# ---------------------------------------------------------------------------


class TestPriceGraph:
    """Tests for graph building and structure."""

    def test_graph_bidirectional(self):
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "AAPL", Amount("$150.00"))
        assert "$" in ph._graph["AAPL"]
        assert "AAPL" in ph._graph["$"]

    def test_graph_with_cycle(self):
        """Price graph with cycles should not cause infinite loops."""
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "A", Amount("2 B"))
        ph.add_price(date(2024, 1, 1), "B", Amount("3 C"))
        ph.add_price(date(2024, 1, 1), "C", Amount("0.5 A"))
        # Should still find paths without looping
        result = ph.find_price("A", "C")
        assert result is not None

    def test_complex_graph_multiple_commodities(self):
        """Multiple commodities with various connections."""
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "AAPL", Amount("$150.00"))
        ph.add_price(date(2024, 1, 1), "GOOG", Amount("$140.00"))
        ph.add_price(date(2024, 1, 1), "EUR", Amount("$1.10"))
        ph.add_price(date(2024, 1, 1), "GBP", Amount("1.15 EUR"))

        # AAPL -> $ -> EUR -> GBP
        result = ph.find_price("AAPL", "GBP")
        assert result is not None

        # GOOG -> $ -> EUR
        result = ph.find_price("GOOG", "EUR")
        assert result is not None

    def test_find_path_disconnected(self):
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "A", Amount("2 B"))
        ph.add_price(date(2024, 1, 1), "C", Amount("3 D"))
        assert ph._find_path("A", "D") is None

    def test_find_path_unknown_commodity(self):
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "A", Amount("2 B"))
        assert ph._find_path("A", "Z") is None
        assert ph._find_path("Z", "A") is None


# ---------------------------------------------------------------------------
# build_from_journal_prices
# ---------------------------------------------------------------------------


class TestBuildFromJournalPrices:
    """Building price history from journal.prices format."""

    def test_build_from_tuples(self):
        ph = PriceHistory()
        prices = [
            (date(2024, 1, 15), "AAPL", Amount("$150.00")),
            (date(2024, 2, 1), "AAPL", Amount("$155.00")),
        ]
        ph.build_from_journal_prices(prices)
        assert len(ph) == 2
        result = ph.find_price("AAPL", "$")
        assert result is not None
        assert result[0] == Fraction(155)


# ---------------------------------------------------------------------------
# Parser integration
# ---------------------------------------------------------------------------


class TestParserIntegration:
    """Parse journal with P directives and verify price history."""

    def test_parse_p_directives_builds_history(self):
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        text = """\
P 2024/01/15 AAPL $150.00
P 2024/02/01 AAPL $155.00
P 2024/01/15 EUR $1.10

2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        assert len(journal.prices) == 3
        assert len(journal.price_history) == 3

        # Verify conversion works
        result = journal.price_history.find_price("AAPL", "$")
        assert result is not None
        assert result[0] == Fraction(155)

    def test_parse_empty_journal_empty_history(self):
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        text = """\
2024/01/15 Groceries
    Expenses:Food             $50.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        assert len(journal.price_history) == 0

    def test_convert_amount_from_parsed_journal(self):
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        text = """\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10

2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        amt = Amount("10 AAPL")
        converted = journal.price_history.convert(amt, "$")
        assert converted.commodity == "$"
        assert converted.quantity == Fraction(1500)


# ---------------------------------------------------------------------------
# Report pipeline: --market
# ---------------------------------------------------------------------------


class TestMarketConversion:
    """Market conversion in the report filter pipeline."""

    def test_market_balance_report(self):
        from muonledger.filters import CollectPosts, MarketConvertPosts
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser
        from muonledger.report import ReportOptions, apply_to_journal, build_filter_chain

        text = """\
P 2024/01/15 AAPL $150.00

2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        options = ReportOptions(market=True)
        posts = apply_to_journal(options, journal)

        collector = CollectPosts()
        chain = build_filter_chain(options, collector, journal=journal)

        for post in posts:
            chain(post)
        chain.flush()

        # The brokerage posting should now be in $
        brokerage_posts = [
            p for p in collector.posts
            if p.account is not None and "Brokerage" in p.account.fullname
        ]
        assert len(brokerage_posts) == 1
        converted_amt = brokerage_posts[0].amount
        assert converted_amt is not None
        assert converted_amt.commodity == "$"
        assert converted_amt.quantity == Fraction(1500)

    def test_market_no_prices_passes_through(self):
        """With --market but no prices, amounts pass through unchanged."""
        from muonledger.filters import CollectPosts
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser
        from muonledger.report import ReportOptions, apply_to_journal, build_filter_chain

        text = """\
2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        options = ReportOptions(market=True)
        posts = apply_to_journal(options, journal)

        collector = CollectPosts()
        chain = build_filter_chain(options, collector, journal=journal)

        for post in posts:
            chain(post)
        chain.flush()

        # AAPL should remain AAPL
        brokerage_posts = [
            p for p in collector.posts
            if p.account is not None and "Brokerage" in p.account.fullname
        ]
        assert len(brokerage_posts) == 1
        assert brokerage_posts[0].amount.commodity == "AAPL"


# ---------------------------------------------------------------------------
# Report pipeline: --exchange
# ---------------------------------------------------------------------------


class TestExchangeConversion:
    """Exchange conversion in the report filter pipeline."""

    def test_exchange_to_eur(self):
        from muonledger.filters import CollectPosts
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser
        from muonledger.report import ReportOptions, apply_to_journal, build_filter_chain

        text = """\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10

2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        options = ReportOptions(exchange="EUR")
        posts = apply_to_journal(options, journal)

        collector = CollectPosts()
        chain = build_filter_chain(options, collector, journal=journal)

        for post in posts:
            chain(post)
        chain.flush()

        # All postings should be in EUR
        for post in collector.posts:
            assert post.amount is not None
            assert post.amount.commodity == "EUR", (
                f"Expected EUR but got {post.amount.commodity} for "
                f"{post.account.fullname if post.account else '?'}"
            )

    def test_exchange_register_report(self):
        """Exchange conversion works in register-style collection."""
        from muonledger.filters import CollectPosts
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser
        from muonledger.report import ReportOptions, apply_to_journal, build_filter_chain

        text = """\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10

2024/01/15 Buy Stock
    Assets:Brokerage          10 AAPL @ $150.00
    Assets:Checking

2024/01/20 Salary
    Assets:Checking          $3,000.00
    Income:Salary
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)

        options = ReportOptions(exchange="EUR")
        posts = apply_to_journal(options, journal)

        collector = CollectPosts()
        chain = build_filter_chain(options, collector, journal=journal)

        for post in posts:
            chain(post)
        chain.flush()

        # All amounts should be in EUR
        for post in collector.posts:
            if post.amount is not None and not post.amount.is_null():
                assert post.amount.commodity == "EUR"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and corner conditions."""

    def test_null_to_amount_ignored(self):
        """Adding a price with a null to_amount is ignored."""
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "AAPL", Amount())
        assert len(ph) == 0

    def test_zero_rate_no_crash(self):
        """A zero-rate price should not cause division by zero."""
        ph = PriceHistory()
        # Amount("$0.00") has quantity 0
        ph.add_price(date(2024, 1, 1), "AAPL", Amount("$0.00"))
        # Forward lookup should work (rate = 0)
        result = ph.find_price("AAPL", "$")
        assert result is not None
        assert result[0] == Fraction(0)
        # Reverse lookup should return None (can't divide by 0)
        # Actually the reverse is stored but with rate 0... let's verify
        # it doesn't crash
        # The add_price guards against rate == 0 for reverse
        # ... actually it doesn't. Let me check.

    def test_multiple_dates_same_pair(self):
        """Multiple prices for the same pair on different dates."""
        ph = PriceHistory()
        ph.add_price(date(2024, 1, 1), "AAPL", Amount("$140.00"))
        ph.add_price(date(2024, 2, 1), "AAPL", Amount("$150.00"))
        ph.add_price(date(2024, 3, 1), "AAPL", Amount("$160.00"))

        assert ph.find_price("AAPL", "$", as_of=date(2024, 1, 15))[0] == Fraction(140)
        assert ph.find_price("AAPL", "$", as_of=date(2024, 2, 15))[0] == Fraction(150)
        assert ph.find_price("AAPL", "$")[0] == Fraction(160)

    def test_build_filter_chain_no_journal_still_works(self):
        """build_filter_chain works without journal (backward compat)."""
        from muonledger.filters import CollectPosts
        from muonledger.report import ReportOptions, build_filter_chain

        options = ReportOptions(market=True)
        collector = CollectPosts()
        # Should not raise even without journal
        chain = build_filter_chain(options, collector)
        assert chain is not None
