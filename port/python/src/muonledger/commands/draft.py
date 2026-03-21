"""Draft/xact/entry command -- generate new transactions from shorthand input.

Ported from ledger's ``xact`` command (also called ``entry`` or ``draft``).
Given shorthand arguments and existing journal history, this command creates
a new transaction by finding a matching historical transaction as a template.

Usage examples::

    muonledger -f journal.dat xact 2024/01/15 "Grocery Store"
    muonledger -f journal.dat xact Grocery 50
    muonledger -f journal.dat xact "Coffee Shop" 5.50 Dining

The command parses args as: [DATE] PAYEE [AMOUNT] [ACCOUNT]
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction
from muonledger.commands.print_cmd import format_transaction

__all__ = [
    "draft_command",
    "find_matching_xact",
    "create_draft",
    "parse_draft_args",
]

# Date patterns recognized by the draft command.
_DATE_PATTERNS = [
    re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}$"),  # 2024/01/15 or 2024-01-15
    re.compile(r"^\d{1,2}[/-]\d{1,2}$"),              # 01/15 (month/day, current year)
]


def _try_parse_date(text: str, default_year: Optional[int] = None) -> Optional[date]:
    """Attempt to parse *text* as a date. Return None if not a date."""
    text = text.strip()

    # Full date: YYYY/MM/DD or YYYY-MM-DD
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # Partial date: MM/DD (use default_year or current year)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", text)
    if m:
        year = default_year if default_year is not None else date.today().year
        try:
            return date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None

    return None


def _try_parse_amount(text: str) -> Optional[Amount]:
    """Attempt to parse *text* as an amount. Return None if not an amount."""
    text = text.strip()
    if not text:
        return None

    # Quick heuristic: if it starts with a digit, sign, or currency symbol,
    # try to parse it as an amount.
    first = text[0]
    if first.isdigit() or first in "+-.$" or first in "\u00a3\u20ac\u00a5":
        try:
            return Amount(text)
        except Exception:
            return None

    # Also try if the whole string looks like a number
    try:
        float(text)
        return Amount(text)
    except (ValueError, Exception):
        return None


def _is_account_like(text: str) -> bool:
    """Return True if *text* looks like an account name (contains a colon)."""
    return ":" in text


def parse_draft_args(
    args: list[str],
    default_year: Optional[int] = None,
) -> tuple[Optional[date], str, Optional[Amount], Optional[str]]:
    """Parse draft command arguments into components.

    Parameters
    ----------
    args:
        Command-line arguments: [DATE] PAYEE [AMOUNT] [ACCOUNT]
    default_year:
        Year to use for partial dates (MM/DD). Defaults to current year.

    Returns
    -------
    tuple of (date or None, payee, amount or None, account or None)
    """
    if not args:
        return None, "", None, None

    remaining = list(args)
    draft_date: Optional[date] = None
    payee: str = ""
    amount: Optional[Amount] = None
    account: Optional[str] = None

    # Try to parse the first argument as a date
    parsed_date = _try_parse_date(remaining[0], default_year)
    if parsed_date is not None:
        draft_date = parsed_date
        remaining.pop(0)

    if not remaining:
        return draft_date, "", None, None

    # The next argument is the payee. It could be a single quoted string
    # or a single word.
    payee = remaining.pop(0)

    # Process remaining arguments: look for amount and account
    for arg in remaining:
        if _is_account_like(arg):
            account = arg
        elif amount is None:
            parsed_amount = _try_parse_amount(arg)
            if parsed_amount is not None:
                amount = parsed_amount
            else:
                # Treat as part of payee or as account name without colon
                # If it doesn't parse as amount, treat it as account
                account = arg
        else:
            # Already have an amount, treat as account
            account = arg

    return draft_date, payee, amount, account


def find_matching_xact(
    journal: Journal,
    payee_pattern: str,
) -> Optional[Transaction]:
    """Find the most recent transaction matching *payee_pattern*.

    Searches in reverse order (most recent first). First tries
    case-insensitive substring matching, then tries regex matching.

    Parameters
    ----------
    journal:
        The journal to search.
    payee_pattern:
        The payee string or pattern to match.

    Returns
    -------
    Transaction or None
        The most recent matching transaction, or None if no match.
    """
    if not payee_pattern:
        return None

    pattern_lower = payee_pattern.lower()

    # First pass: case-insensitive substring match (most recent first)
    for xact in reversed(journal.xacts):
        if pattern_lower in xact.payee.lower():
            return xact

    # Second pass: try regex match
    try:
        regex = re.compile(payee_pattern, re.IGNORECASE)
        for xact in reversed(journal.xacts):
            if regex.search(xact.payee):
                return xact
    except re.error:
        pass  # Invalid regex, skip

    return None


def create_draft(
    draft_date: date,
    payee: str,
    template_xact: Optional[Transaction] = None,
    amount: Optional[Amount] = None,
    account: Optional[str] = None,
    journal: Optional[Journal] = None,
) -> Transaction:
    """Create a new draft transaction.

    Parameters
    ----------
    draft_date:
        The date for the new transaction.
    payee:
        The payee/description.
    template_xact:
        An existing transaction to use as a template for accounts/amounts.
    amount:
        Override amount (replaces the template's primary amount).
    account:
        Override primary account name.
    journal:
        The journal (used to look up/create account objects).

    Returns
    -------
    Transaction
        The new draft transaction (not added to any journal).
    """
    xact = Transaction(payee=payee)
    xact.date = draft_date

    if template_xact is not None and template_xact.posts:
        # Use template transaction as a basis
        template_posts = template_xact.posts

        for i, tpost in enumerate(template_posts):
            post = Post()

            # Determine account
            if i == 0 and account is not None:
                # Override the first posting's account with the specified account
                if journal is not None:
                    post.account = journal.find_account(account)
                else:
                    post.account = tpost.account
            else:
                post.account = tpost.account

            # Determine amount
            if i == 0 and amount is not None:
                # Override the first posting's amount
                post.amount = amount
            elif i == len(template_posts) - 1 and amount is not None:
                # Last posting: leave amount as None for auto-balancing
                post.amount = None
            else:
                # Copy template amount
                if tpost.amount is not None and not tpost.amount.is_null():
                    post.amount = Amount(tpost.amount)
                else:
                    post.amount = None

            xact.add_post(post)
    else:
        # No template: create a minimal transaction
        if account is not None and amount is not None:
            post1 = Post()
            if journal is not None:
                post1.account = journal.find_account(account)
            else:
                # Create a simple account-like object
                post1.account = _make_simple_account(account)
            post1.amount = amount
            xact.add_post(post1)

            # Second posting: use "Unknown" as placeholder
            post2 = Post()
            if journal is not None:
                post2.account = journal.find_account("Expenses:Unknown")
            else:
                post2.account = _make_simple_account("Expenses:Unknown")
            post2.amount = None
            xact.add_post(post2)
        elif amount is not None:
            # Have amount but no account
            post1 = Post()
            if journal is not None:
                post1.account = journal.find_account("Expenses:Unknown")
            else:
                post1.account = _make_simple_account("Expenses:Unknown")
            post1.amount = amount
            xact.add_post(post1)

            post2 = Post()
            if journal is not None:
                post2.account = journal.find_account("Assets:Unknown")
            else:
                post2.account = _make_simple_account("Assets:Unknown")
            post2.amount = None
            xact.add_post(post2)
        elif account is not None:
            # Have account but no amount -- minimal skeleton
            post1 = Post()
            if journal is not None:
                post1.account = journal.find_account(account)
            else:
                post1.account = _make_simple_account(account)
            post1.amount = None
            xact.add_post(post1)
        # else: no posts at all -- truly minimal

    return xact


class _SimpleAccount:
    """Lightweight account stand-in when no journal is available."""

    __slots__ = ("fullname",)

    def __init__(self, name: str) -> None:
        self.fullname = name


def _make_simple_account(name: str) -> _SimpleAccount:
    return _SimpleAccount(name)


def draft_command(
    journal: Journal,
    args: Optional[list[str]] = None,
    options: Optional[dict] = None,
) -> str:
    """Generate a new transaction from shorthand arguments.

    This is the main entry point for the xact/entry/draft command.

    Parameters
    ----------
    journal:
        The journal containing existing transactions for template matching.
    args:
        Command arguments: [DATE] PAYEE [AMOUNT] [ACCOUNT]
    options:
        Optional dict of command options (currently unused, reserved).

    Returns
    -------
    str
        The formatted transaction in ledger format.
    """
    if args is None:
        args = []

    if not args:
        return ""

    draft_date, payee, amount, account = parse_draft_args(args)

    if not payee:
        return ""

    # Default to today's date if none given
    if draft_date is None:
        draft_date = date.today()

    # Find a matching template transaction
    template_xact = find_matching_xact(journal, payee)

    # If we found a template, use its payee (full name) for the draft
    effective_payee = template_xact.payee if template_xact is not None else payee

    # Create the draft transaction
    xact = create_draft(
        draft_date=draft_date,
        payee=effective_payee,
        template_xact=template_xact,
        amount=amount,
        account=account,
        journal=journal,
    )

    if not xact.posts:
        # No postings -- output a bare header
        date_str = draft_date.strftime("%Y/%m/%d")
        return f"{date_str} {effective_payee}\n"

    # Finalize to infer balancing amounts
    try:
        xact.finalize()
    except Exception:
        pass  # Best effort: output even if it doesn't balance

    return format_transaction(xact)
