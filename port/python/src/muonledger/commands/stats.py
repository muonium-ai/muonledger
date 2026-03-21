"""Stats command -- produces journal statistics.

Ported from ledger's ``stats.cc`` (``report_statistics``).  Given a
:class:`Journal`, collects and displays statistics about the journal data
including transaction counts, date ranges, payees, accounts, and commodities.

The output format mirrors ledger's stats command::

    Time period: 2024/01/01 to 2024/01/31 (30 days)

      Files these postings came from:
        /path/to/file.dat

      Unique payees:               5
      Unique accounts:             8

      Number of postings:         12 (0.40 per day)
      Uncleared postings:          3

      Days since last post:       10
      Posts in last 7 days:        2
      Posts in last 30 days:       8
      Posts seen this month:       4

"""

from __future__ import annotations

from datetime import date
from typing import Optional

from muonledger.item import ItemState
from muonledger.journal import Journal

__all__ = ["stats_command"]


def stats_command(
    journal: Journal,
    args: Optional[list[str]] = None,
    today: Optional[date] = None,
) -> str:
    """Produce a statistics report from *journal*.

    Parameters
    ----------
    journal:
        The journal containing transactions to report on.
    args:
        Command-line style arguments (currently unused, reserved for future).
    today:
        Override for the current date (useful for testing).

    Returns
    -------
    str
        The formatted statistics report.
    """
    if today is None:
        today = date.today()

    xacts = journal.xacts

    if not xacts:
        return ""

    # Collect dates from transactions
    dates: list[date] = []
    for xact in xacts:
        if xact.date is not None:
            dates.append(xact.date)

    if not dates:
        return ""

    earliest = min(dates)
    latest = max(dates)
    span_days = (latest - earliest).days

    # Collect statistics
    total_posts = 0
    uncleared_posts = 0
    payees: set[str] = set()
    account_names: set[str] = set()
    commodity_symbols: set[str] = set()
    filenames: set[str] = set()
    posts_last_7 = 0
    posts_last_30 = 0
    posts_this_month = 0

    for xact in xacts:
        payees.add(xact.payee)

        for post in xact.posts:
            total_posts += 1

            # Clearing state
            post_state = post.state
            if post_state == ItemState.UNCLEARED:
                # Check parent xact state too
                if xact.state == ItemState.UNCLEARED:
                    uncleared_posts += 1

            # Account
            if post.account is not None:
                account_names.add(post.account.fullname)

            # Commodity
            if post.amount is not None and not post.amount.is_null():
                comm = post.amount.commodity
                if comm is not None and comm:
                    commodity_symbols.add(comm)

            # Source file from posting or transaction position
            pos = post.position or xact.position
            if pos is not None and pos.pathname:
                filenames.add(pos.pathname)

            # Time-based counts (use transaction date)
            xact_date = xact.date
            if xact_date is not None:
                days_ago = (today - xact_date).days
                if days_ago < 7:
                    posts_last_7 += 1
                if days_ago < 30:
                    posts_last_30 += 1
                if (xact_date.year == today.year
                        and xact_date.month == today.month):
                    posts_this_month += 1

    # Also collect filenames from journal sources
    for src in journal.sources:
        if src:
            filenames.add(src)

    days_since_last = (today - latest).days

    # Per-day rate
    if span_days > 0:
        per_day = total_posts / span_days
    else:
        per_day = float(total_posts)

    # Format output matching ledger's stats.cc
    lines: list[str] = []

    lines.append(
        f"Time period: {_fmt_date(earliest)} to {_fmt_date(latest)}"
        f" ({span_days} days)"
    )
    lines.append("")

    lines.append("  Files these postings came from:")
    if filenames:
        for fn in sorted(filenames):
            lines.append(f"    {fn}")
    else:
        lines.append("    (no file information)")
    lines.append("")

    lines.append(f"  Unique payees:          {len(payees):>6}")
    lines.append(f"  Unique accounts:        {len(account_names):>6}")
    lines.append("")

    lines.append(
        f"  Number of postings:     {total_posts:>6}"
        f" ({per_day:.2f} per day)"
    )
    lines.append(f"  Uncleared postings:     {uncleared_posts:>6}")
    lines.append("")

    lines.append(f"  Days since last post:   {days_since_last:>6}")
    lines.append(f"  Posts in last 7 days:   {posts_last_7:>6}")
    lines.append(f"  Posts in last 30 days:  {posts_last_30:>6}")
    lines.append(f"  Posts seen this month:  {posts_this_month:>6}")

    return "\n".join(lines) + "\n"


def _fmt_date(d: date) -> str:
    """Format a date as YYYY/MM/DD matching ledger's default."""
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"
