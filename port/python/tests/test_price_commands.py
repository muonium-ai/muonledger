"""Tests for the prices, pricedb, and pricemap commands."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.prices import prices_command
from muonledger.commands.pricedb import pricedb_command
from muonledger.commands.pricemap import pricemap_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_journal(text: str) -> Journal:
    """Parse a journal from text."""
    j = Journal()
    parser = TextualParser()
    parser.parse_string(text, j)
    return j


def _make_journal_with_prices() -> Journal:
    """Create a journal with P directives."""
    text = """\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
P 2024/02/01 AAPL $155.00
P 2024/02/01 EUR $1.08

2024/01/01 Opening
    Assets:Bank:Checking     $1000.00
    Equity:Opening          $-1000.00
"""
    return _parse_journal(text)


def _make_journal_with_costs() -> Journal:
    """Create a journal with cost annotations (implicit prices)."""
    text = """\
2024/01/10 Buy Stock
    Assets:Brokerage       10 AAPL @ $150.00
    Assets:Bank:Checking   $-1500.00

2024/02/15 Buy Euros
    Assets:Euro Account    100 EUR @ $1.10
    Assets:Bank:Checking   $-110.00
"""
    return _parse_journal(text)


def _make_journal_mixed() -> Journal:
    """Create a journal with both P directives and cost transactions."""
    text = """\
P 2024/01/01 AAPL $148.00
P 2024/01/15 EUR $1.12

2024/01/10 Buy Stock
    Assets:Brokerage       10 AAPL @ $150.00
    Assets:Bank:Checking   $-1500.00

2024/02/01 Buy Euros
    Assets:Euro Account    100 EUR @ $1.10
    Assets:Bank:Checking   $-110.00
"""
    return _parse_journal(text)


# ===========================================================================
# prices command tests
# ===========================================================================


class TestPricesCommand:
    """Tests for the prices command."""

    def test_basic_p_directive(self):
        """P directives appear in prices output."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = prices_command(j)
        assert "2024/01/15 AAPL $150.00" in output

    def test_multiple_p_directives(self):
        """Multiple P directives all appear."""
        j = _make_journal_with_prices()
        output = prices_command(j)
        assert "AAPL" in output
        assert "EUR" in output
        lines = [l for l in output.strip().split("\n") if l]
        # 4 P directives
        assert len(lines) == 4

    def test_date_ordering(self):
        """Prices are sorted by date."""
        j = _make_journal_with_prices()
        output = prices_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        dates = [l.split()[0] for l in lines]
        assert dates == sorted(dates)

    def test_implicit_prices_from_cost(self):
        """Cost annotations generate implicit prices."""
        j = _make_journal_with_costs()
        output = prices_command(j)
        assert "AAPL" in output
        assert "EUR" in output

    def test_implicit_price_value(self):
        """Implicit prices have correct per-unit value."""
        j = _parse_journal("""\
2024/03/01 Buy
    Assets:Brokerage       5 AAPL @ $200.00
    Assets:Bank           $-1000.00
""")
        output = prices_command(j)
        assert "2024/03/01 AAPL $200.00" in output

    def test_mixed_prices(self):
        """Both explicit and implicit prices appear."""
        j = _make_journal_mixed()
        output = prices_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        # 2 P directives + 2 implicit from cost transactions
        assert len(lines) == 4

    def test_empty_journal(self):
        """Empty journal produces no output."""
        j = Journal()
        output = prices_command(j)
        assert output == ""

    def test_journal_no_prices(self):
        """Journal with transactions but no prices produces no output."""
        j = _parse_journal("""\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary           $-1000.00
""")
        output = prices_command(j)
        assert output == ""

    def test_multiple_prices_same_commodity(self):
        """Multiple price points for same commodity pair."""
        j = _parse_journal("""\
P 2024/01/01 AAPL $148.00
P 2024/01/15 AAPL $150.00
P 2024/02/01 AAPL $155.00
""")
        output = prices_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 3
        assert "$148.00" in lines[0]
        assert "$150.00" in lines[1]
        assert "$155.00" in lines[2]

    def test_filter_by_commodity(self):
        """Prices can be filtered by commodity name."""
        j = _make_journal_with_prices()
        output = prices_command(j, ["AAPL"])
        assert "AAPL" in output
        assert "EUR" not in output

    def test_filter_case_insensitive(self):
        """Commodity filter is case-insensitive."""
        j = _make_journal_with_prices()
        output = prices_command(j, ["aapl"])
        assert "AAPL" in output

    def test_filter_by_target_commodity(self):
        """Can filter by the target commodity (e.g. $)."""
        j = _make_journal_with_prices()
        output = prices_command(j, ["$"])
        # All prices target $, so all should appear
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 4

    def test_filter_no_match(self):
        """Filter that matches nothing returns empty."""
        j = _make_journal_with_prices()
        output = prices_command(j, ["GOOG"])
        assert output == ""

    def test_output_ends_with_newline(self):
        """Output ends with newline when non-empty."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = prices_command(j)
        assert output.endswith("\n")

    def test_none_args(self):
        """Passing None as args is same as no filter."""
        j = _make_journal_with_prices()
        output1 = prices_command(j, None)
        output2 = prices_command(j, [])
        assert output1 == output2

    def test_total_cost_annotation(self):
        """@@ total cost generates correct per-unit price."""
        j = _parse_journal("""\
2024/03/01 Buy
    Assets:Brokerage       10 AAPL @@ $1500.00
    Assets:Bank           $-1500.00
""")
        output = prices_command(j)
        assert "AAPL" in output
        assert "$150.00" in output


# ===========================================================================
# pricedb command tests
# ===========================================================================


class TestPricedbCommand:
    """Tests for the pricedb command."""

    def test_basic_format(self):
        """Output is in P directive format with time."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = pricedb_command(j)
        assert "P 2024/01/15 00:00:00 AAPL $150.00" in output

    def test_multiple_entries(self):
        """Multiple P directives produce multiple lines."""
        j = _make_journal_with_prices()
        output = pricedb_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 4
        for line in lines:
            assert line.startswith("P ")
            assert "00:00:00" in line

    def test_empty_journal(self):
        """Empty journal produces no output."""
        j = Journal()
        output = pricedb_command(j)
        assert output == ""

    def test_implicit_prices_included(self):
        """Implicit prices from cost annotations appear."""
        j = _make_journal_with_costs()
        output = pricedb_command(j)
        assert "AAPL" in output
        assert "EUR" in output
        lines = [l for l in output.strip().split("\n") if l]
        for line in lines:
            assert line.startswith("P ")

    def test_date_ordering(self):
        """Entries are sorted by date."""
        j = _make_journal_with_prices()
        output = pricedb_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        # Extract dates (format: P DATE TIME ...)
        dates = [l.split()[1] for l in lines]
        assert dates == sorted(dates)

    def test_round_trip_parseable(self):
        """pricedb output can be re-parsed as valid P directives."""
        original = """\
P 2024/01/15 AAPL $150.00
P 2024/02/01 EUR $1.10
"""
        j1 = _parse_journal(original)
        pricedb_out = pricedb_command(j1)

        # The pricedb output has time stamps; strip them for re-parse
        # by converting "P DATE TIME" to "P DATE"
        reparseable = ""
        for line in pricedb_out.strip().split("\n"):
            parts = line.split()
            # P DATE TIME COMMODITY PRICE -> P DATE COMMODITY PRICE
            reparseable += f"{parts[0]} {parts[1]} {' '.join(parts[3:])}\n"

        j2 = _parse_journal(reparseable)
        assert len(j2.prices) == len(j1.prices)

    def test_filter_by_commodity(self):
        """Pricedb entries can be filtered."""
        j = _make_journal_with_prices()
        output = pricedb_command(j, ["AAPL"])
        assert "AAPL" in output
        assert "EUR" not in output

    def test_output_ends_with_newline(self):
        """Output ends with newline when non-empty."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = pricedb_command(j)
        assert output.endswith("\n")

    def test_none_args(self):
        """Passing None as args is same as no filter."""
        j = _make_journal_with_prices()
        output1 = pricedb_command(j, None)
        output2 = pricedb_command(j, [])
        assert output1 == output2

    def test_all_lines_start_with_p(self):
        """Every line in pricedb output starts with P."""
        j = _make_journal_mixed()
        output = pricedb_command(j)
        for line in output.strip().split("\n"):
            if line:
                assert line.startswith("P ")

    def test_time_field_present(self):
        """Each line has a time field after the date."""
        j = _make_journal_with_prices()
        output = pricedb_command(j)
        for line in output.strip().split("\n"):
            if line:
                parts = line.split()
                assert len(parts) >= 5  # P DATE TIME COMMODITY PRICE
                assert parts[2] == "00:00:00"

    def test_multiple_prices_same_pair(self):
        """Multiple price points for same pair are all output."""
        j = _parse_journal("""\
P 2024/01/01 AAPL $148.00
P 2024/01/15 AAPL $150.00
P 2024/02/01 AAPL $155.00
""")
        output = pricedb_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 3


# ===========================================================================
# pricemap command tests
# ===========================================================================


class TestPricemapCommand:
    """Tests for the pricemap command."""

    def test_basic_graph(self):
        """P directive creates bidirectional edge."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = pricemap_command(j)
        assert "AAPL -> $" in output
        assert "$ -> AAPL" in output

    def test_multiple_commodities(self):
        """Multiple commodities all appear in the graph."""
        j = _make_journal_with_prices()
        output = pricemap_command(j)
        assert "AAPL" in output
        assert "EUR" in output
        assert "$" in output

    def test_bidirectional_edges(self):
        """Graph shows edges in both directions."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = pricemap_command(j)
        lines = output.strip().split("\n")
        assert len(lines) == 2
        # $ -> AAPL and AAPL -> $
        commodities = {l.split(" -> ")[0] for l in lines}
        assert commodities == {"$", "AAPL"}

    def test_multiple_targets(self):
        """Commodity with multiple connections shows all targets."""
        j = _parse_journal("""\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
""")
        output = pricemap_command(j)
        # $ connects to both AAPL and EUR
        for line in output.strip().split("\n"):
            if line.startswith("$ ->"):
                targets = line.split(" -> ")[1]
                assert "AAPL" in targets
                assert "EUR" in targets

    def test_empty_journal(self):
        """Empty journal produces no output."""
        j = Journal()
        output = pricemap_command(j)
        assert output == ""

    def test_no_prices(self):
        """Journal with no prices produces no output."""
        j = _parse_journal("""\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary           $-1000.00
""")
        output = pricemap_command(j)
        assert output == ""

    def test_implicit_prices_in_graph(self):
        """Cost annotations create graph edges."""
        j = _make_journal_with_costs()
        output = pricemap_command(j)
        assert "AAPL" in output
        assert "EUR" in output
        assert "$" in output

    def test_sorted_output(self):
        """Commodities are listed in sorted order."""
        j = _parse_journal("""\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
P 2024/01/15 GBP $1.25
""")
        output = pricemap_command(j)
        lines = output.strip().split("\n")
        commodities = [l.split(" -> ")[0] for l in lines]
        assert commodities == sorted(commodities)

    def test_sorted_targets(self):
        """Target commodities within each line are sorted."""
        j = _parse_journal("""\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
P 2024/01/15 GBP $1.25
""")
        output = pricemap_command(j)
        for line in output.strip().split("\n"):
            if line.startswith("$ ->"):
                targets_str = line.split(" -> ")[1]
                targets = [t.strip() for t in targets_str.split(",")]
                assert targets == sorted(targets)

    def test_filter_by_commodity(self):
        """Pricemap can be filtered by commodity."""
        j = _parse_journal("""\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
""")
        output = pricemap_command(j, ["AAPL"])
        assert "AAPL" in output
        # EUR line should not appear ($ may appear since AAPL -> $)
        lines = output.strip().split("\n")
        for line in lines:
            source = line.split(" -> ")[0]
            assert "aapl" in source.lower()

    def test_filter_no_match(self):
        """Filter with no match returns empty."""
        j = _make_journal_with_prices()
        output = pricemap_command(j, ["GOOG"])
        assert output == ""

    def test_output_ends_with_newline(self):
        """Output ends with newline when non-empty."""
        j = _parse_journal("P 2024/01/15 AAPL $150.00\n")
        output = pricemap_command(j)
        assert output.endswith("\n")

    def test_none_args(self):
        """Passing None as args is same as no filter."""
        j = _make_journal_with_prices()
        output1 = pricemap_command(j, None)
        output2 = pricemap_command(j, [])
        assert output1 == output2

    def test_deduplication(self):
        """Multiple prices between same pair don't create duplicate edges."""
        j = _parse_journal("""\
P 2024/01/01 AAPL $148.00
P 2024/01/15 AAPL $150.00
P 2024/02/01 AAPL $155.00
""")
        output = pricemap_command(j)
        lines = output.strip().split("\n")
        # Should have exactly 2 lines: $ -> AAPL and AAPL -> $
        assert len(lines) == 2

    def test_three_commodity_chain(self):
        """Graph shows transitive connections through intermediary."""
        j = _parse_journal("""\
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10
""")
        output = pricemap_command(j)
        # $ should connect to both AAPL and EUR
        for line in output.strip().split("\n"):
            if line.startswith("$ ->"):
                assert "AAPL" in line
                assert "EUR" in line

    def test_mixed_explicit_and_implicit(self):
        """Both explicit and implicit prices appear in the graph."""
        j = _make_journal_mixed()
        output = pricemap_command(j)
        assert "AAPL" in output
        assert "EUR" in output
        assert "$" in output


# ===========================================================================
# Integration / edge case tests
# ===========================================================================


class TestPriceCommandsIntegration:
    """Integration tests across all price commands."""

    def test_prices_and_pricedb_same_count(self):
        """prices and pricedb produce the same number of entries."""
        j = _make_journal_mixed()
        prices_out = prices_command(j)
        pricedb_out = pricedb_command(j)
        prices_lines = [l for l in prices_out.strip().split("\n") if l]
        pricedb_lines = [l for l in pricedb_out.strip().split("\n") if l]
        assert len(prices_lines) == len(pricedb_lines)

    def test_all_commands_empty_journal(self):
        """All three commands handle empty journal."""
        j = Journal()
        assert prices_command(j) == ""
        assert pricedb_command(j) == ""
        assert pricemap_command(j) == ""

    def test_single_price_all_commands(self):
        """Single P directive works across all commands."""
        j = _parse_journal("P 2024/06/15 GOOG $175.50\n")
        prices_out = prices_command(j)
        pricedb_out = pricedb_command(j)
        pricemap_out = pricemap_command(j)

        assert "GOOG" in prices_out
        assert "$175.50" in prices_out

        assert "P 2024/06/15 00:00:00 GOOG $175.50" in pricedb_out

        assert "GOOG -> $" in pricemap_out
        assert "$ -> GOOG" in pricemap_out

    def test_many_commodities(self):
        """Test with many different commodities."""
        lines = []
        commodities = ["AAPL", "GOOG", "MSFT", "AMZN", "META"]
        for i, comm in enumerate(commodities):
            price = 100 + i * 50
            lines.append(f"P 2024/01/15 {comm} ${price}.00")
        j = _parse_journal("\n".join(lines) + "\n")

        prices_out = prices_command(j)
        for comm in commodities:
            assert comm in prices_out

        pricemap_out = pricemap_command(j)
        # $ should connect to all commodities
        for line in pricemap_out.strip().split("\n"):
            if line.startswith("$ ->"):
                for comm in commodities:
                    assert comm in line

    def test_historical_price_ordering(self):
        """Prices spanning multiple dates are properly ordered."""
        j = _parse_journal("""\
P 2024/03/01 AAPL $170.00
P 2024/01/01 AAPL $148.00
P 2024/02/01 AAPL $155.00
""")
        output = prices_command(j)
        lines = [l for l in output.strip().split("\n") if l]
        dates = [l.split()[0] for l in lines]
        assert dates == ["2024/01/01", "2024/02/01", "2024/03/01"]

    def test_european_commodity(self):
        """European-style commodity symbols work."""
        j = _parse_journal("P 2024/01/15 EUR $1.10\n")
        output = prices_command(j)
        assert "EUR" in output

    def test_pricedb_round_trip_multiple(self):
        """pricedb output for multiple prices is re-parseable."""
        original = """\
P 2024/01/01 AAPL $148.00
P 2024/01/15 EUR $1.10
P 2024/02/01 AAPL $155.00
P 2024/02/01 GBP $1.25
"""
        j1 = _parse_journal(original)
        output = pricedb_command(j1)

        # Strip time for re-parsing
        reparseable = ""
        for line in output.strip().split("\n"):
            parts = line.split()
            reparseable += f"{parts[0]} {parts[1]} {' '.join(parts[3:])}\n"

        j2 = _parse_journal(reparseable)
        assert len(j2.prices) == len(j1.prices)
