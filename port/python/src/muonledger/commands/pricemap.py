"""Pricemap command -- show the commodity price graph.

Ported from ledger's ``pricemap`` command.  Shows the graph of commodity
connections: which commodities can be converted to which via the price
history.  Useful for debugging exchange rate paths.

Output format::

    AAPL -> $
    EUR -> $
    $ -> AAPL, EUR

Each line shows a commodity and the set of commodities it has a direct
price relationship with (from P directives and implicit transaction costs).
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from typing import Optional

from muonledger.amount import Amount
from muonledger.journal import Journal

__all__ = ["pricemap_command"]


def _build_graph(
    journal: Journal,
) -> dict[str, set[str]]:
    """Build the commodity adjacency graph from a journal.

    Gathers commodity relationships from:
    1. Explicit ``P`` directives
    2. Implicit prices from transactions with cost annotations

    Returns a dict mapping each commodity to its set of directly
    connected commodities.
    """
    graph: dict[str, set[str]] = {}

    def _add_edge(from_c: str, to_c: str) -> None:
        if from_c not in graph:
            graph[from_c] = set()
        graph[from_c].add(to_c)
        if to_c not in graph:
            graph[to_c] = set()
        graph[to_c].add(from_c)

    # 1. Explicit P directive prices
    for price_date, commodity_symbol, price_amount in journal.prices:
        to_commodity = price_amount.commodity
        if to_commodity:
            _add_edge(commodity_symbol, to_commodity)

    # 2. Implicit prices from cost annotations on postings
    for xact in journal.xacts:
        if xact.date is None:
            continue
        for post in xact.posts:
            if post.cost is None:
                continue
            if post.amount is None or post.amount.is_null():
                continue
            from_commodity = post.amount.commodity
            to_commodity = post.cost.commodity
            if from_commodity and to_commodity:
                _add_edge(from_commodity, to_commodity)

    return graph


def pricemap_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """Produce a price map (commodity graph) from *journal*.

    Parameters
    ----------
    journal:
        The journal containing price data.
    args:
        Optional list of pattern strings to filter by commodity name
        (case-insensitive substring match).

    Returns
    -------
    str
        The formatted price map showing commodity connections.
    """
    if args is None:
        args = []

    patterns = [p.lower() for p in args]
    graph = _build_graph(journal)

    lines: list[str] = []
    for commodity in sorted(graph.keys()):
        if patterns:
            if not any(p in commodity.lower() for p in patterns):
                continue
        targets = sorted(graph[commodity])
        targets_str = ", ".join(targets)
        lines.append(f"{commodity} -> {targets_str}")

    if not lines:
        return ""
    return "\n".join(lines) + "\n"
