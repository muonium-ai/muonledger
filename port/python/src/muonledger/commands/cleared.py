"""Cleared command -- shows cleared vs uncleared balances per account.

Ported from ledger's cleared report.  For each account that has postings,
displays three columns:

    Cleared    Uncleared        Total  Account

- **Cleared**: sum of postings whose effective state is CLEARED (``*``)
- **Uncleared**: sum of all other postings (PENDING ``!`` or UNCLEARED)
- **Total**: sum of all postings

A grand-total line is shown at the bottom.
"""

from __future__ import annotations

import re
from typing import Optional

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.item import ItemState
from muonledger.journal import Journal

__all__ = ["cleared_command"]

# Column width for each amount column (right-aligned).
AMOUNT_WIDTH = 14


def _effective_state(post) -> ItemState:
    """Return the effective clearing state for a posting.

    A posting inherits the transaction state unless it has its own
    explicit state set (i.e. state != UNCLEARED).
    """
    if post.state != ItemState.UNCLEARED:
        return post.state
    if post.xact is not None:
        return post.xact.state
    return ItemState.UNCLEARED


def _matches(name: str, patterns: list[str]) -> bool:
    """Return True if *name* matches any of the given patterns (substring, case-insensitive)."""
    name_lower = name.lower()
    return any(p.lower() in name_lower for p in patterns)


def _format_amount(bal: Balance) -> str:
    """Format a Balance into a right-aligned string within AMOUNT_WIDTH."""
    if bal.is_empty() or bal.is_zero():
        return "0".rjust(AMOUNT_WIDTH)
    amounts = list(bal)
    if len(amounts) == 1:
        return str(amounts[0]).rjust(AMOUNT_WIDTH)
    # Multi-commodity: join with newlines (each right-aligned)
    return "\n".join(str(a).rjust(AMOUNT_WIDTH) for a in amounts)


def cleared_command(
    journal: Journal,
    args: Optional[list[str]] = None,
    options: Optional[dict] = None,
) -> str:
    """Produce a cleared report from *journal*.

    Parameters
    ----------
    journal:
        The journal containing transactions to report on.
    args:
        Account filter patterns (substring match).
    options:
        Optional dict of options (reserved for future use).

    Returns
    -------
    str
        The formatted cleared report.
    """
    if args is None:
        args = []

    # Separate patterns from any flags (simple approach)
    patterns: list[str] = [a for a in args if not a.startswith("-")]

    # Accumulate cleared and uncleared balances per account.
    cleared_bals: dict[str, Balance] = {}
    uncleared_bals: dict[str, Balance] = {}

    for xact in journal.xacts:
        for post in xact.posts:
            if post.amount is None or post.amount.is_null():
                continue
            acct = post.account
            if acct is None:
                continue
            name = acct.fullname

            if name not in cleared_bals:
                cleared_bals[name] = Balance()
                uncleared_bals[name] = Balance()

            state = _effective_state(post)
            if state == ItemState.CLEARED:
                cleared_bals[name].add(post.amount)
            else:
                uncleared_bals[name].add(post.amount)

    # Filter by patterns if provided.
    account_names = sorted(cleared_bals.keys())
    if patterns:
        account_names = [n for n in account_names if _matches(n, patterns)]

    if not account_names:
        return ""

    # Build output lines.
    lines: list[str] = []

    # Header
    header = (
        "Cleared".rjust(AMOUNT_WIDTH)
        + "  "
        + "Uncleared".rjust(AMOUNT_WIDTH)
        + "  "
        + "Total".rjust(AMOUNT_WIDTH)
        + "  Account"
    )
    lines.append(header)

    # Grand totals
    grand_cleared = Balance()
    grand_uncleared = Balance()
    grand_total = Balance()

    for name in account_names:
        c_bal = cleared_bals.get(name, Balance())
        u_bal = uncleared_bals.get(name, Balance())

        # Total = cleared + uncleared
        t_bal = Balance()
        t_bal.add(c_bal)
        t_bal.add(u_bal)

        grand_cleared.add(c_bal)
        grand_uncleared.add(u_bal)
        grand_total.add(t_bal)

        c_str = _format_amount(c_bal)
        u_str = _format_amount(u_bal)
        t_str = _format_amount(t_bal)

        # Handle multi-commodity (multiple lines per amount)
        c_lines = c_str.split("\n")
        u_lines = u_str.split("\n")
        t_lines = t_str.split("\n")

        max_lines = max(len(c_lines), len(u_lines), len(t_lines))

        # Pad shorter lists
        while len(c_lines) < max_lines:
            c_lines.insert(0, " " * AMOUNT_WIDTH)
        while len(u_lines) < max_lines:
            u_lines.insert(0, " " * AMOUNT_WIDTH)
        while len(t_lines) < max_lines:
            t_lines.insert(0, " " * AMOUNT_WIDTH)

        for i in range(max_lines):
            acct_part = f"  {name}" if i == max_lines - 1 else ""
            lines.append(
                f"{c_lines[i]}  {u_lines[i]}  {t_lines[i]}{acct_part}"
            )

    # Separator and grand totals
    sep_width = AMOUNT_WIDTH * 3 + 4  # 3 columns + 2 gaps of 2 spaces
    lines.append("-" * sep_width)

    gc_str = _format_amount(grand_cleared)
    gu_str = _format_amount(grand_uncleared)
    gt_str = _format_amount(grand_total)

    gc_lines = gc_str.split("\n")
    gu_lines = gu_str.split("\n")
    gt_lines = gt_str.split("\n")

    max_lines = max(len(gc_lines), len(gu_lines), len(gt_lines))
    while len(gc_lines) < max_lines:
        gc_lines.insert(0, " " * AMOUNT_WIDTH)
    while len(gu_lines) < max_lines:
        gu_lines.insert(0, " " * AMOUNT_WIDTH)
    while len(gt_lines) < max_lines:
        gt_lines.insert(0, " " * AMOUNT_WIDTH)

    for i in range(max_lines):
        lines.append(f"{gc_lines[i]}  {gu_lines[i]}  {gt_lines[i]}")

    return "\n".join(lines) + "\n"
