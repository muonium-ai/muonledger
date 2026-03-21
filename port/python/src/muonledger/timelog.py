"""Time logging support for clock-in/clock-out directives.

Ported from ledger's ``timelog.h`` / ``timelog.cc``.  Supports the ``i``
(clock-in) and ``o`` (clock-out) directives that track time spent on
accounts and generate transactions with hour-based amounts.

Example journal input::

    i 2024/01/15 09:00:00 Projects:ClientA
    o 2024/01/15 12:30:00

This generates a transaction equivalent to::

    2024/01/15 Projects:ClientA
        (Projects:ClientA)  3.50h
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Optional

from muonledger.amount import Amount
from muonledger.commodity import Commodity, CommodityPool
from muonledger.item import ITEM_GENERATED, Position
from muonledger.post import POST_VIRTUAL, Post
from muonledger.xact import Transaction

__all__ = [
    "TimelogEntry",
    "TimelogProcessor",
    "TimelogError",
]


class TimelogError(Exception):
    """Raised for invalid timelog operations."""

    def __init__(self, message: str, line_num: int = 0, source: str = ""):
        self.message = message
        self.line_num = line_num
        self.source = source
        super().__init__(str(self))

    def __str__(self) -> str:
        parts: list[str] = []
        if self.source and self.source != "<string>":
            parts.append(f"{self.source}:")
        if self.line_num > 0:
            parts.append(f"{self.line_num}:")
        parts.append(f" {self.message}")
        return "".join(parts)


@dataclass
class TimelogEntry:
    """A pending clock-in entry awaiting a matching clock-out.

    Attributes
    ----------
    checkin_dt : datetime
        The date and time of the clock-in.
    account : str
        The account being clocked into.
    payee : str
        Optional payee/description for the time entry.
    line_num : int
        Source line number for error reporting.
    source : str
        Source file name for error reporting.
    """

    checkin_dt: datetime
    account: str
    payee: str = ""
    line_num: int = 0
    source: str = ""


def calculate_duration_hours(start: datetime, end: datetime) -> Fraction:
    """Calculate the duration between two datetimes in fractional hours.

    Returns a :class:`Fraction` for exact representation.

    Raises
    ------
    TimelogError
        If end is before start.
    """
    delta = end - start
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        raise TimelogError(
            f"Clock-out time {end} is before clock-in time {start}"
        )
    # Convert to hours as a Fraction for exact arithmetic
    return Fraction(total_seconds, 3600)


def format_hours(hours: Fraction) -> str:
    """Format a fractional hour value as a decimal string with 2 places.

    Examples: ``Fraction(7, 2)`` -> ``"3.50"``, ``Fraction(1, 4)`` -> ``"0.25"``
    """
    # Round to 2 decimal places for display
    value = float(hours)
    return f"{value:.2f}"


class TimelogProcessor:
    """Processes clock-in/clock-out pairs and generates transactions.

    Maintains the pending clock-in state and converts completed pairs
    into :class:`Transaction` objects with hour-based amounts.
    """

    def __init__(self) -> None:
        self._pending: Optional[TimelogEntry] = None

    @property
    def pending(self) -> Optional[TimelogEntry]:
        """The current pending clock-in entry, if any."""
        return self._pending

    @property
    def has_pending(self) -> bool:
        """Whether there is an open clock-in without a matching clock-out."""
        return self._pending is not None

    def clock_in(
        self,
        dt: datetime,
        account: str,
        payee: str = "",
        line_num: int = 0,
        source: str = "",
    ) -> None:
        """Record a clock-in event.

        If there is already a pending clock-in, it is automatically
        closed at the new clock-in time (generating a transaction via
        the journal).

        Parameters
        ----------
        dt : datetime
            The clock-in date and time.
        account : str
            The account to clock into.
        payee : str
            Optional payee description.
        line_num : int
            Source line number.
        source : str
            Source file name.
        """
        self._pending = TimelogEntry(
            checkin_dt=dt,
            account=account,
            payee=payee,
            line_num=line_num,
            source=source,
        )

    def clock_out(
        self,
        dt: datetime,
        line_num: int = 0,
        source: str = "",
        commodity_pool: Optional[CommodityPool] = None,
    ) -> Optional[Transaction]:
        """Record a clock-out event and generate a transaction.

        Parameters
        ----------
        dt : datetime
            The clock-out date and time.
        line_num : int
            Source line number.
        source : str
            Source file name.
        commodity_pool : CommodityPool | None
            Pool for creating the ``h`` commodity.

        Returns
        -------
        Transaction | None
            The generated transaction, or None if there was no pending
            clock-in.

        Raises
        ------
        TimelogError
            If there is no pending clock-in.
        """
        if self._pending is None:
            raise TimelogError(
                "Clock-out without a matching clock-in",
                line_num=line_num,
                source=source,
            )

        entry = self._pending
        self._pending = None

        return create_timelog_transaction(
            entry=entry,
            checkout_dt=dt,
            line_num=line_num,
            source=source,
            commodity_pool=commodity_pool,
        )


def create_timelog_transaction(
    entry: TimelogEntry,
    checkout_dt: datetime,
    line_num: int = 0,
    source: str = "",
    commodity_pool: Optional[CommodityPool] = None,
) -> Transaction:
    """Create a transaction from a clock-in/clock-out pair.

    The transaction has a single virtual posting to the clocked account
    with the duration in hours as the amount.

    Parameters
    ----------
    entry : TimelogEntry
        The clock-in entry.
    checkout_dt : datetime
        The clock-out datetime.
    line_num : int
        Source line number of the clock-out.
    source : str
        Source file name.
    commodity_pool : CommodityPool | None
        Pool for creating the ``h`` commodity.

    Returns
    -------
    Transaction
        The generated time-tracking transaction.
    """
    hours = calculate_duration_hours(entry.checkin_dt, checkout_dt)
    hours_str = format_hours(hours)

    # Create the amount with "h" commodity
    amt = Amount(hours_str, commodity="h")

    # Build payee: use explicit payee if given, else account name
    payee = entry.payee if entry.payee else entry.account

    xact = Transaction(payee=payee)
    xact.date = entry.checkin_dt.date()
    xact.position = Position(
        pathname=source,
        beg_line=entry.line_num,
    )

    # Single virtual posting (like C++ ledger's timelog).
    # Store the account name as a string; the parser resolves it to a
    # real Account object via journal.find_account later.
    post = Post(account=entry.account, amount=amt)
    post.flags |= POST_VIRTUAL
    xact.add_post(post)

    return xact


def process_timelog_entries(
    entries: list[tuple[str, datetime, str, str]],
    commodity_pool: Optional[CommodityPool] = None,
) -> list[Transaction]:
    """Convert a list of clock-in/out events into transactions.

    Parameters
    ----------
    entries : list of tuples
        Each tuple is (directive, datetime, account_or_empty, payee_or_empty).
        directive is ``"i"`` for clock-in or ``"o"`` for clock-out.

    Returns
    -------
    list[Transaction]
        Generated transactions.

    Raises
    ------
    TimelogError
        On mismatched clock-in/out pairs.
    """
    processor = TimelogProcessor()
    transactions: list[Transaction] = []

    for directive, dt, account, payee in entries:
        if directive == "i":
            # If there's already a pending, auto-close it
            if processor.has_pending:
                xact = processor.clock_out(
                    dt, commodity_pool=commodity_pool
                )
                if xact is not None:
                    transactions.append(xact)
            processor.clock_in(dt, account, payee)
        elif directive == "o":
            xact = processor.clock_out(
                dt, commodity_pool=commodity_pool
            )
            if xact is not None:
                transactions.append(xact)

    return transactions
