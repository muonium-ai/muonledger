"""Commodity price history with shortest-path conversion.

Ported from ledger's ``commodity_history_t`` in ``history.h`` / ``history.cc``.
The :class:`PriceHistory` maintains a graph of commodity prices learned from
``P`` directives and enables conversions using BFS shortest-path through
intermediate commodities.

Usage::

    ph = PriceHistory()
    ph.add_price(date(2024, 1, 15), "AAPL", Amount("$150.00"))
    ph.add_price(date(2024, 1, 15), "EUR", Amount("$1.10"))

    # Direct: AAPL -> $
    rate, when = ph.find_price("AAPL", "$")
    # Transitive: AAPL -> $ -> EUR
    converted = ph.convert(Amount("10 AAPL"), "EUR")
"""

from __future__ import annotations

from collections import deque
from datetime import date
from fractions import Fraction
from typing import Optional

from muonledger.amount import Amount

__all__ = ["PriceHistory"]


class PriceHistory:
    """Commodity price history with shortest-path conversion.

    Stores price entries from ``P`` directives and builds an adjacency graph
    for BFS-based shortest-path conversions between commodities.

    Each price entry records: 1 unit of *from_commodity* equals *to_amount*
    (which carries both a quantity and a target commodity symbol).
    """

    def __init__(self) -> None:
        # List of (date, from_commodity, to_commodity, rate_quantity)
        self.prices: list[tuple[date, str, str, Fraction]] = []
        # Adjacency list: commodity -> set of connected commodities
        self._graph: dict[str, set[str]] = {}
        # Best prices indexed by (from, to) -> list of (date, rate) sorted by date
        self._price_map: dict[tuple[str, str], list[tuple[date, Fraction]]] = {}

    def add_price(
        self,
        price_date: date,
        from_commodity: str,
        to_amount: Amount,
    ) -> None:
        """Add a price entry: 1 unit of *from_commodity* = *to_amount*.

        Parameters
        ----------
        price_date : date
            The date this price is effective.
        from_commodity : str
            The commodity being priced (e.g., ``"AAPL"``).
        to_amount : Amount
            The price amount (e.g., ``Amount("$150.00")``).
        """
        if to_amount.is_null():
            return

        to_commodity = to_amount.commodity or ""
        if not to_commodity:
            return

        rate = to_amount.quantity

        self.prices.append((price_date, from_commodity, to_commodity, rate))

        # Update adjacency graph (bidirectional)
        if from_commodity not in self._graph:
            self._graph[from_commodity] = set()
        self._graph[from_commodity].add(to_commodity)

        if to_commodity not in self._graph:
            self._graph[to_commodity] = set()
        self._graph[to_commodity].add(from_commodity)

        # Update price map (forward direction)
        key = (from_commodity, to_commodity)
        if key not in self._price_map:
            self._price_map[key] = []
        self._price_map[key].append((price_date, rate))
        self._price_map[key].sort(key=lambda x: x[0])

        # Update price map (reverse direction)
        if rate != 0:
            rev_key = (to_commodity, from_commodity)
            rev_rate = Fraction(1) / rate
            if rev_key not in self._price_map:
                self._price_map[rev_key] = []
            self._price_map[rev_key].append((price_date, rev_rate))
            self._price_map[rev_key].sort(key=lambda x: x[0])

    def find_price(
        self,
        commodity: str,
        target_commodity: str,
        as_of: Optional[date] = None,
    ) -> Optional[tuple[Fraction, date]]:
        """Find conversion rate from *commodity* to *target_commodity*.

        Uses shortest-path through the price graph if no direct price exists.

        Parameters
        ----------
        commodity : str
            Source commodity symbol.
        target_commodity : str
            Target commodity symbol.
        as_of : date, optional
            If given, use the most recent price on or before this date.
            If ``None``, use the most recent price overall.

        Returns
        -------
        tuple[Fraction, date] or None
            ``(rate, effective_date)`` where rate is the conversion factor
            (multiply source quantity by rate to get target quantity), or
            ``None`` if no conversion path exists.
        """
        if commodity == target_commodity:
            return (Fraction(1), as_of or date.min)

        # Try direct price first
        direct = self._get_rate(commodity, target_commodity, as_of)
        if direct is not None:
            return direct

        # BFS through the price graph
        path = self._find_path(commodity, target_commodity)
        if path is None:
            return None

        # Multiply rates along the path
        total_rate = Fraction(1)
        latest_date = date.min
        for i in range(len(path) - 1):
            step_result = self._get_rate(path[i], path[i + 1], as_of)
            if step_result is None:
                return None
            rate, rate_date = step_result
            total_rate *= rate
            if rate_date > latest_date:
                latest_date = rate_date

        return (total_rate, latest_date)

    def convert(
        self,
        amount: Amount,
        target_commodity: str,
        as_of: Optional[date] = None,
    ) -> Amount:
        """Convert an amount to the target commodity using price history.

        Parameters
        ----------
        amount : Amount
            The amount to convert.
        target_commodity : str
            The commodity to convert to.
        as_of : date, optional
            Use prices as of this date.

        Returns
        -------
        Amount
            The converted amount, or the original if no conversion path exists.
        """
        if amount.is_null():
            return amount

        source_commodity = amount.commodity or ""
        if not source_commodity or source_commodity == target_commodity:
            return amount

        result = self.find_price(source_commodity, target_commodity, as_of)
        if result is None:
            return amount

        rate, _ = result
        new_quantity = amount.quantity * rate
        converted = Amount(new_quantity, target_commodity)

        # Copy precision from the target commodity's known style
        # Use the precision of the rate's target commodity prices
        target_prices = self._price_map.get(
            (source_commodity, target_commodity)
        )
        if target_prices:
            # Use the precision from amount formatting
            converted._precision = max(converted._precision, 2)

        return converted

    def _get_rate(
        self,
        from_commodity: str,
        to_commodity: str,
        as_of: Optional[date] = None,
    ) -> Optional[tuple[Fraction, date]]:
        """Get the direct rate between two commodities.

        Returns the most recent price on or before *as_of* (or the most
        recent overall if *as_of* is None).
        """
        key = (from_commodity, to_commodity)
        entries = self._price_map.get(key)
        if not entries:
            return None

        if as_of is None:
            # Return the most recent price
            rate_date, rate = entries[-1]
            return (rate, rate_date)

        # Find the most recent price on or before as_of
        best: Optional[tuple[Fraction, date]] = None
        for entry_date, rate in entries:
            if entry_date <= as_of:
                best = (rate, entry_date)
            else:
                break  # entries are sorted by date

        return best

    def _find_path(
        self,
        from_commodity: str,
        to_commodity: str,
    ) -> Optional[list[str]]:
        """BFS shortest path through the price graph.

        Returns the path as a list of commodity symbols from *from_commodity*
        to *to_commodity*, or ``None`` if no path exists.
        """
        if from_commodity not in self._graph or to_commodity not in self._graph:
            return None

        if from_commodity == to_commodity:
            return [from_commodity]

        visited: set[str] = {from_commodity}
        queue: deque[list[str]] = deque([[from_commodity]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in self._graph.get(current, set()):
                if neighbor == to_commodity:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return None

    def build_from_journal_prices(
        self,
        prices: list[tuple],
    ) -> None:
        """Populate from journal.prices entries.

        Parameters
        ----------
        prices : list of tuple
            Each tuple is ``(date, commodity_symbol, price_amount)`` as
            stored in :attr:`Journal.prices`.
        """
        for entry in prices:
            price_date, commodity_symbol, price_amount = entry
            self.add_price(price_date, commodity_symbol, price_amount)

    def __len__(self) -> int:
        """Number of price entries."""
        return len(self.prices)

    def __repr__(self) -> str:
        commodities = set()
        for _, frm, to, _ in self.prices:
            commodities.add(frm)
            commodities.add(to)
        return (
            f"PriceHistory(entries={len(self.prices)}, "
            f"commodities={len(commodities)})"
        )
