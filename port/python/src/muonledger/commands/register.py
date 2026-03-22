"""Register command: list postings chronologically with running totals.

Ported from ledger's register report. Outputs postings in chronological
order, showing date, payee, account, amount, and a running total that
accumulates across all displayed postings.
"""

from __future__ import annotations

from typing import Optional

from datetime import date, datetime

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.journal import Journal

__all__ = ["register_command"]


# ---------------------------------------------------------------------------
# Column layout constants
# ---------------------------------------------------------------------------

# Default (80-column) layout
_DATE_WIDTH = 10
_PAYEE_WIDTH = 22
_ACCOUNT_WIDTH = 22
_AMOUNT_WIDTH = 13
_TOTAL_WIDTH = 13
# Total: 10 + 22 + 22 + 13 + 13 = 80

# Wide (132-column) layout
_WIDE_DATE_WIDTH = 10
_WIDE_PAYEE_WIDTH = 35
_WIDE_ACCOUNT_WIDTH = 39
_WIDE_AMOUNT_WIDTH = 24
_WIDE_TOTAL_WIDTH = 24
# Total: 10 + 35 + 39 + 24 + 24 = 132


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_date(dt) -> str:
    """Format a date as YY-Mon-DD (e.g., 24-Jan-01)."""
    if dt is None:
        return ""
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    return f"{dt.year % 100:02d}-{months[dt.month - 1]}-{dt.day:02d}"


def _truncate(text: str, width: int) -> str:
    """Truncate *text* to *width*, appending '..' if truncated."""
    if len(text) <= width:
        return text
    if width <= 2:
        return text[:width]
    return text[: width - 2] + ".."


def _balance_to_lines(bal: Balance) -> list[str]:
    """Convert a Balance to display lines, one per commodity.

    Returns amount strings sorted by commodity symbol, matching ledger's
    output order.
    """
    if bal.is_empty():
        return ["0"]
    amounts = bal.amounts()
    # Sort by commodity key (empty string sorts first)
    result = []
    for key in sorted(amounts.keys()):
        result.append(str(amounts[key]))
    return result


def _amount_str(amt: Optional[Amount]) -> str:
    """Format a posting amount as a string."""
    if amt is None or amt.is_null():
        return "0"
    return str(amt)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(args: list[str]) -> dict:
    """Parse register command arguments.

    Returns a dict with keys: wide, head, tail, account_patterns.
    """
    result = {
        "wide": False,
        "head": None,
        "tail": None,
        "begin": None,
        "end": None,
        "account_patterns": [],
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--wide", "-w"):
            result["wide"] = True
        elif arg == "--head":
            i += 1
            if i < len(args):
                result["head"] = int(args[i])
        elif arg == "--tail":
            i += 1
            if i < len(args):
                result["tail"] = int(args[i])
        elif arg == "--begin":
            i += 1
            if i < len(args):
                result["begin"] = _parse_date_arg(args[i])
        elif arg == "--end":
            i += 1
            if i < len(args):
                result["end"] = _parse_date_arg(args[i])
        else:
            result["account_patterns"].append(arg)
        i += 1
    return result


def _parse_date_arg(text: str) -> date:
    """Parse a date argument in YYYY-MM-DD or YYYY/MM/DD format."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {text!r}")


def _matches_account(account_fullname: str, patterns: list[str]) -> bool:
    """Check if an account name matches any of the filter patterns.

    Patterns are matched case-insensitively as substrings of the full
    account name (matching ledger's default behavior).
    """
    if not patterns:
        return True
    lower_name = account_fullname.lower()
    for pat in patterns:
        if pat.lower() in lower_name:
            return True
    return False


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

def register_command(journal: Journal, args: Optional[list[str]] = None) -> str:
    """Generate a register report from *journal*.

    Parameters
    ----------
    journal : Journal
        A populated journal with transactions and postings.
    args : list[str] | None
        Command-line arguments: account patterns and options like
        ``--wide``, ``--head N``, ``--tail N``.

    Returns
    -------
    str
        The formatted register report.
    """
    if args is None:
        args = []

    opts = _parse_args(args)

    if opts["wide"]:
        date_w = _WIDE_DATE_WIDTH
        payee_w = _WIDE_PAYEE_WIDTH
        account_w = _WIDE_ACCOUNT_WIDTH
        amount_w = _WIDE_AMOUNT_WIDTH
        total_w = _WIDE_TOTAL_WIDTH
    else:
        date_w = _DATE_WIDTH
        payee_w = _PAYEE_WIDTH
        account_w = _ACCOUNT_WIDTH
        amount_w = _AMOUNT_WIDTH
        total_w = _TOTAL_WIDTH

    # Gather all output rows (before head/tail slicing).
    # Each row is a list of output lines (a posting may produce multiple
    # lines when the running total spans multiple commodities).
    rows: list[list[str]] = []
    running_total = Balance()

    for xact in journal.xacts:
        # Date filtering: --begin means >= date, --end means < date
        if opts["begin"] is not None and xact.date is not None:
            if xact.date < opts["begin"]:
                continue
        if opts["end"] is not None and xact.date is not None:
            if xact.date >= opts["end"]:
                continue

        first_in_xact = True
        for post in xact.posts:
            account_name = post.account.fullname if post.account is not None else ""

            if not _matches_account(account_name, opts["account_patterns"]):
                continue

            # Update running total with this posting's amount
            amt = post.amount
            if amt is not None and not amt.is_null():
                running_total.add(amt)

            # Format the date and payee (only for the first posting shown
            # in this transaction).
            if first_in_xact:
                date_str = _format_date(xact.date)
                payee_str = _truncate(xact.payee, payee_w - 1)
                first_in_xact = False
            else:
                date_str = ""
                payee_str = ""

            # Format the posting amount
            amt_str = _amount_str(amt)

            # Format the running total (may be multi-line for multi-commodity)
            total_lines = _balance_to_lines(running_total)

            # Build the output lines for this posting.
            # First line has date, payee, account, amount, and first total line.
            # Subsequent lines (for multi-commodity totals) show only the total.
            lines: list[str] = []

            date_col = date_str.ljust(date_w)
            payee_col = payee_str.ljust(payee_w)
            account_col = _truncate(account_name, account_w - 1).ljust(account_w)
            amount_col = amt_str.rjust(amount_w)

            first_total = total_lines[0] if total_lines else ""
            total_col = first_total.rjust(total_w)

            first_line = f"{date_col}{payee_col}{account_col}{amount_col}{total_col}"
            lines.append(first_line)

            # Additional total lines (multi-commodity running total)
            for extra_total in total_lines[1:]:
                blank_prefix = " " * (date_w + payee_w + account_w + amount_w)
                lines.append(f"{blank_prefix}{extra_total.rjust(total_w)}")

            rows.append(lines)

    # Apply --head / --tail
    if opts["head"] is not None:
        rows = rows[: opts["head"]]
    if opts["tail"] is not None:
        rows = rows[-opts["tail"]:]

    # Flatten rows into output lines
    output_lines: list[str] = []
    for row in rows:
        output_lines.extend(row)

    if not output_lines:
        return ""
    return "\n".join(output_lines) + "\n"
