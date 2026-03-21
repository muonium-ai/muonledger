"""Pricedb command -- output prices in ledger P directive format.

Ported from ledger's ``pricedb`` command.  Outputs all prices in the
``P DATE HH:MM:SS COMMODITY PRICE`` format suitable for use as a price
database file that can be included in a ledger journal.

Output format::

    P 2024/01/15 00:00:00 AAPL $150.00
    P 2024/01/15 00:00:00 EUR $1.10

"""

from __future__ import annotations

from datetime import date
from typing import Optional

from muonledger.amount import Amount
from muonledger.journal import Journal

__all__ = ["pricedb_command"]


def _collect_prices(journal: Journal) -> list[tuple[date, str, Amount]]:
    """Collect all price entries from a journal.

    Gathers prices from two sources:
    1. Explicit ``P`` directives stored in ``journal.prices``
    2. Implicit prices from transactions with cost annotations

    Returns a list of ``(date, from_commodity, price_amount)`` tuples
    sorted by date, then commodity.
    """
    entries: list[tuple[date, str, Amount]] = []

    # 1. Explicit P directive prices
    for price_date, commodity_symbol, price_amount in journal.prices:
        entries.append((price_date, commodity_symbol, Amount(price_amount)))

    # 2. Implicit prices from cost annotations on postings
    for xact in journal.xacts:
        if xact.date is None:
            continue
        for post in xact.posts:
            if post.cost is None:
                continue
            if post.amount is None or post.amount.is_null():
                continue
            amt = post.amount
            cost = post.cost
            from_commodity = amt.commodity
            if from_commodity is None:
                continue
            to_commodity = cost.commodity
            if to_commodity is None:
                continue
            abs_qty = abs(amt.quantity)
            if abs_qty == 0:
                continue
            per_unit = cost / abs(amt)
            per_unit_amt = Amount(abs(per_unit).quantity, to_commodity)
            per_unit_amt._precision = max(cost._precision, 2)
            entries.append((xact.date, from_commodity, per_unit_amt))

    # Sort by date, then commodity name
    entries.sort(key=lambda e: (e[0], e[1]))
    return entries


def pricedb_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """Produce price database output from *journal*.

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
        The formatted price database text (P directives).
    """
    if args is None:
        args = []

    patterns = [p.lower() for p in args]
    entries = _collect_prices(journal)

    lines: list[str] = []
    for price_date, commodity, price_amount in entries:
        if patterns:
            if not any(
                p in commodity.lower() or p in (price_amount.commodity or "").lower()
                for p in patterns
            ):
                continue
        date_str = price_date.strftime("%Y/%m/%d")
        lines.append(f"P {date_str} 00:00:00 {commodity} {price_amount}")

    if not lines:
        return ""
    return "\n".join(lines) + "\n"
