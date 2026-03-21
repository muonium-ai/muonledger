"""Listing commands: accounts, payees, tags, commodities.

Ported from ledger's ``report.cc`` (accounts_command, payees_command,
tags_command, commodities_command).  Each command walks the journal's
transactions and collects unique items, returning them sorted one per line.

All commands accept:
  - An optional list of filter patterns (substring match on payee or account)
  - A ``--count`` flag to prepend usage counts
"""

from __future__ import annotations

import argparse
from typing import Optional

from muonledger.journal import Journal

__all__ = [
    "accounts_command",
    "payees_command",
    "tags_command",
    "commodities_command",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(args: list[str]) -> argparse.Namespace:
    """Parse listing command arguments."""
    parser = argparse.ArgumentParser(prog="listing", add_help=False)
    parser.add_argument("--count", action="store_true", default=False)
    parser.add_argument("patterns", nargs="*")
    return parser.parse_args(args)


def _matches(text: str, patterns: list[str]) -> bool:
    """Return True if *text* contains any of the *patterns* (case-insensitive)."""
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in patterns)


def _xact_matches(xact, patterns: list[str]) -> bool:
    """Return True if a transaction matches any filter pattern.

    Checks the payee and all posting account names.
    """
    if _matches(xact.payee, patterns):
        return True
    for post in xact.posts:
        if post.account is not None and _matches(post.account.fullname, patterns):
            return True
    return False


# ---------------------------------------------------------------------------
# accounts_command
# ---------------------------------------------------------------------------

def accounts_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """List all accounts used in transactions, sorted alphabetically.

    Parameters
    ----------
    journal:
        The journal containing transactions.
    args:
        Command-line style arguments (e.g. ``["--count", "Expenses"]``).

    Returns
    -------
    str
        One account per line, sorted alphabetically.
    """
    if args is None:
        args = []
    opts = _parse_args(args)

    counts: dict[str, int] = {}
    for xact in journal.xacts:
        if opts.patterns and not _xact_matches(xact, opts.patterns):
            continue
        for post in xact.posts:
            if post.account is None:
                continue
            name = post.account.fullname
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1

    if not counts:
        return ""

    lines: list[str] = []
    for name in sorted(counts.keys()):
        if opts.count:
            lines.append(f"{counts[name]} {name}")
        else:
            lines.append(name)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# payees_command
# ---------------------------------------------------------------------------

def payees_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """List all unique payees, sorted alphabetically.

    Parameters
    ----------
    journal:
        The journal containing transactions.
    args:
        Command-line style arguments (e.g. ``["--count"]``).

    Returns
    -------
    str
        One payee per line, sorted alphabetically.
    """
    if args is None:
        args = []
    opts = _parse_args(args)

    counts: dict[str, int] = {}
    for xact in journal.xacts:
        if opts.patterns and not _xact_matches(xact, opts.patterns):
            continue
        payee = xact.payee
        if not payee:
            continue
        counts[payee] = counts.get(payee, 0) + 1

    if not counts:
        return ""

    lines: list[str] = []
    for payee in sorted(counts.keys()):
        if opts.count:
            lines.append(f"{counts[payee]} {payee}")
        else:
            lines.append(payee)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# tags_command
# ---------------------------------------------------------------------------

def tags_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """List all unique metadata tags from transactions and postings.

    Tags are collected from both transaction-level and posting-level
    metadata.  Duplicates are removed and the result is sorted.

    Parameters
    ----------
    journal:
        The journal containing transactions.
    args:
        Command-line style arguments (e.g. ``["--count"]``).

    Returns
    -------
    str
        One tag per line, sorted alphabetically.
    """
    if args is None:
        args = []
    opts = _parse_args(args)

    counts: dict[str, int] = {}
    for xact in journal.xacts:
        if opts.patterns and not _xact_matches(xact, opts.patterns):
            continue
        # Transaction-level tags
        if xact._metadata:
            for tag in xact._metadata:
                counts[tag] = counts.get(tag, 0) + 1
        # Posting-level tags
        for post in xact.posts:
            if post._metadata:
                for tag in post._metadata:
                    counts[tag] = counts.get(tag, 0) + 1

    if not counts:
        return ""

    lines: list[str] = []
    for tag in sorted(counts.keys()):
        if opts.count:
            lines.append(f"{counts[tag]} {tag}")
        else:
            lines.append(tag)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# commodities_command
# ---------------------------------------------------------------------------

def commodities_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """List all commodities used in amounts (including costs).

    Scans all posting amounts and costs to collect commodity symbols.
    The null commodity (empty symbol) is excluded.

    Parameters
    ----------
    journal:
        The journal containing transactions.
    args:
        Command-line style arguments (e.g. ``["--count"]``).

    Returns
    -------
    str
        One commodity per line, sorted alphabetically.
    """
    if args is None:
        args = []
    opts = _parse_args(args)

    counts: dict[str, int] = {}
    for xact in journal.xacts:
        if opts.patterns and not _xact_matches(xact, opts.patterns):
            continue
        for post in xact.posts:
            # Collect from posting amount
            if post.amount is not None and not post.amount.is_null():
                sym = post.amount.commodity
                if sym:
                    counts[sym] = counts.get(sym, 0) + 1
            # Collect from cost (e.g., "10 AAPL @ $50" has both AAPL and $)
            if post.cost is not None and not post.cost.is_null():
                sym = post.cost.commodity
                if sym:
                    counts[sym] = counts.get(sym, 0) + 1

    if not counts:
        return ""

    lines: list[str] = []
    for sym in sorted(counts.keys()):
        if opts.count:
            lines.append(f"{counts[sym]} {sym}")
        else:
            lines.append(sym)

    return "\n".join(lines) + "\n"
