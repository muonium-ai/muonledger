"""Date/time utilities for muonledger.

Provides date and datetime parsing, formatting, period expression parsing,
and DateInterval iteration -- a Python port of Ledger's times.h / times.cc.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterator, Optional

from dateutil.relativedelta import relativedelta

__all__ = [
    "parse_date",
    "parse_datetime",
    "parse_period",
    "DateInterval",
    "today",
    "now",
    "format_date",
    "format_datetime",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def today() -> date:
    """Return the current local date."""
    return date.today()


def now() -> datetime:
    """Return the current local datetime."""
    return datetime.now()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Ordered list of (regex, builder) pairs.  The first match wins.
_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # YYYY/MM/DD or YYYY-MM-DD (2 or 1 digit month/day)
    (
        re.compile(
            r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$"
        ),
        "ymd",
    ),
    # MM/DD or M/D (current year assumed)
    (
        re.compile(r"^(\d{1,2})[/\-.](\d{1,2})$"),
        "md",
    ),
]


def parse_date(s: str) -> date:
    """Parse a date string into a :class:`datetime.date`.

    Supported formats:
      - ``YYYY/MM/DD``, ``YYYY-MM-DD``, ``YYYY.MM.DD``
      - ``YYYY/M/D`` (single-digit month/day)
      - ``MM/DD`` or ``M/D`` (current year assumed)

    Raises :class:`ValueError` if the string cannot be parsed.
    """
    s = s.strip()

    for pattern, kind in _DATE_PATTERNS:
        m = pattern.match(s)
        if m is None:
            continue
        groups = m.groups()
        if kind == "ymd":
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        if kind == "md":
            return date(today().year, int(groups[0]), int(groups[1]))

    raise ValueError(f"Cannot parse date: {s!r}")


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

_DATETIME_PATTERNS: list[re.Pattern[str]] = [
    # YYYY/MM/DD HH:MM:SS
    re.compile(
        r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})"
        r"\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$"
    ),
]


def parse_datetime(s: str) -> datetime:
    """Parse a datetime string into a :class:`datetime.datetime`.

    Supported formats:
      - ``YYYY/MM/DD HH:MM:SS``
      - ``YYYY-MM-DD HH:MM:SS``
      - ``YYYY/MM/DD HH:MM`` (seconds default to 0)

    Raises :class:`ValueError` if the string cannot be parsed.
    """
    s = s.strip()

    for pattern in _DATETIME_PATTERNS:
        m = pattern.match(s)
        if m is None:
            continue
        g = m.groups()
        sec = int(g[5]) if g[5] is not None else 0
        return datetime(
            int(g[0]), int(g[1]), int(g[2]),
            int(g[3]), int(g[4]), sec,
        )

    raise ValueError(f"Cannot parse datetime: {s!r}")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_DEFAULT_DATE_FMT = "%Y/%m/%d"
_DEFAULT_DATETIME_FMT = "%Y/%m/%d %H:%M:%S"


def format_date(d: date, fmt: Optional[str] = None) -> str:
    """Format a date as a string.

    *fmt* is a :func:`strftime` format string; defaults to ``YYYY/MM/DD``.
    """
    return d.strftime(fmt or _DEFAULT_DATE_FMT)


def format_datetime(dt: datetime, fmt: Optional[str] = None) -> str:
    """Format a datetime as a string.

    *fmt* is a :func:`strftime` format string; defaults to
    ``YYYY/MM/DD HH:MM:SS``.
    """
    return dt.strftime(fmt or _DEFAULT_DATETIME_FMT)


# ---------------------------------------------------------------------------
# DateInterval
# ---------------------------------------------------------------------------

class DateInterval:
    """Represents a repeating calendar interval with optional bounds.

    The interval is defined by a *quantum* (``"days"``, ``"weeks"``,
    ``"months"``, ``"quarters"``, ``"years"``) and a *length* (multiplier).
    Optional *start* and *end* dates restrict iteration.

    Iteration yields successive period-start dates within the bounded range.
    """

    VALID_QUANTA = {"days", "weeks", "months", "quarters", "years"}

    def __init__(
        self,
        quantum: str = "months",
        length: int = 1,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> None:
        if quantum not in self.VALID_QUANTA:
            raise ValueError(
                f"Invalid quantum {quantum!r}; "
                f"expected one of {sorted(self.VALID_QUANTA)}"
            )
        self.quantum = quantum
        self.length = length
        self.start = start
        self.end = end

    # -- duration property ---------------------------------------------------

    @property
    def duration(self) -> relativedelta | timedelta:
        """Return the step size as a :class:`relativedelta` or :class:`timedelta`."""
        if self.quantum == "days":
            return timedelta(days=self.length)
        if self.quantum == "weeks":
            return timedelta(weeks=self.length)
        if self.quantum == "months":
            return relativedelta(months=self.length)
        if self.quantum == "quarters":
            return relativedelta(months=self.length * 3)
        if self.quantum == "years":
            return relativedelta(years=self.length)
        raise ValueError(f"Unknown quantum: {self.quantum!r}")  # pragma: no cover

    # -- iteration -----------------------------------------------------------

    def __iter__(self) -> Iterator[date]:
        """Yield successive period-start dates within [start, end)."""
        if self.start is None:
            raise ValueError("Cannot iterate a DateInterval without a start date")

        current = self.start
        dur = self.duration

        while True:
            if self.end is not None and current >= self.end:
                break
            yield current
            current = current + dur

    # -- repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        parts = [f"quantum={self.quantum!r}", f"length={self.length}"]
        if self.start is not None:
            parts.append(f"start={self.start!r}")
        if self.end is not None:
            parts.append(f"end={self.end!r}")
        return f"DateInterval({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DateInterval):
            return NotImplemented
        return (
            self.quantum == other.quantum
            and self.length == other.length
            and self.start == other.start
            and self.end == other.end
        )


# ---------------------------------------------------------------------------
# Period expression parsing
# ---------------------------------------------------------------------------

# Maps simple keywords to (quantum, length).
_SIMPLE_PERIODS: dict[str, tuple[str, int]] = {
    "daily": ("days", 1),
    "weekly": ("weeks", 1),
    "biweekly": ("weeks", 2),
    "monthly": ("months", 1),
    "bimonthly": ("months", 2),
    "quarterly": ("quarters", 1),
    "yearly": ("years", 1),
}

_EVERY_RE = re.compile(
    r"every\s+(\d+)\s+(days?|weeks?|months?|quarters?|years?)",
    re.IGNORECASE,
)

_FROM_RE = re.compile(
    r"from\s+(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})",
    re.IGNORECASE,
)

_TO_RE = re.compile(
    r"to\s+(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})",
    re.IGNORECASE,
)


def _normalize_quantum(word: str) -> str:
    """Normalize a quantum word to its plural canonical form."""
    word = word.lower().rstrip("s") + "s"
    # "quartes" can't happen but safety:
    if word == "quartes":  # pragma: no cover
        word = "quarters"
    return word


def _this_month_interval() -> DateInterval:
    t = today()
    start = t.replace(day=1)
    end = (start + relativedelta(months=1))
    return DateInterval("months", 1, start, end)


def _last_month_interval() -> DateInterval:
    t = today()
    end = t.replace(day=1)
    start = end - relativedelta(months=1)
    return DateInterval("months", 1, start, end)


def _this_year_interval() -> DateInterval:
    t = today()
    start = date(t.year, 1, 1)
    end = date(t.year + 1, 1, 1)
    return DateInterval("years", 1, start, end)


def _last_year_interval() -> DateInterval:
    t = today()
    start = date(t.year - 1, 1, 1)
    end = date(t.year, 1, 1)
    return DateInterval("years", 1, start, end)


_RELATIVE_PERIODS: dict[str, callable] = {
    "this month": _this_month_interval,
    "last month": _last_month_interval,
    "this year": _this_year_interval,
    "last year": _last_year_interval,
}


def parse_period(s: str) -> DateInterval:
    """Parse a human-readable period expression into a :class:`DateInterval`.

    Supported expressions:

    - ``"daily"``, ``"weekly"``, ``"biweekly"``, ``"monthly"``,
      ``"bimonthly"``, ``"quarterly"``, ``"yearly"``
    - ``"every N days/weeks/months/quarters/years"``
    - Any of the above followed by ``"from YYYY/MM/DD"``
      and/or ``"to YYYY/MM/DD"``
    - ``"this month"``, ``"last month"``, ``"this year"``, ``"last year"``

    Raises :class:`ValueError` if the expression is not recognized.
    """
    s = s.strip()
    s_lower = s.lower()

    # Check relative periods first.
    if s_lower in _RELATIVE_PERIODS:
        return _RELATIVE_PERIODS[s_lower]()

    # Try "every N <quantum>" first since simple keywords may appear as prefix
    quantum: Optional[str] = None
    length: int = 1

    every_m = _EVERY_RE.search(s_lower)
    if every_m:
        length = int(every_m.group(1))
        quantum = _normalize_quantum(every_m.group(2))
    else:
        # Try simple keyword at the start
        for keyword, (q, l) in _SIMPLE_PERIODS.items():
            if s_lower.startswith(keyword):
                quantum = q
                length = l
                break

    if quantum is None:
        raise ValueError(f"Cannot parse period expression: {s!r}")

    # Extract optional bounds.
    start: Optional[date] = None
    end: Optional[date] = None

    from_m = _FROM_RE.search(s)
    if from_m:
        start = parse_date(from_m.group(1))

    to_m = _TO_RE.search(s)
    if to_m:
        end = parse_date(to_m.group(1))

    return DateInterval(quantum, length, start, end)
