"""Equity command -- generate opening balance transactions.

Ported from ledger's equity-related output logic.  The equity command
computes the net balance for each account across all transactions in a
journal and emits an "Opening Balances" transaction that reproduces
those balances, offset by an ``Equity:Opening Balances`` posting.

This is useful for closing books at year-end or starting a new journal
file with carried-forward balances.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.commands.print_cmd import format_posting, format_transaction
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import Transaction

__all__ = ["equity_command"]


def _compute_account_balances(
    journal: Journal,
    account_filter: Optional[list[str]] = None,
) -> dict[str, Balance]:
    """Walk all transactions and accumulate per-account balances.

    Parameters
    ----------
    journal:
        The journal to scan.
    account_filter:
        If provided, only include accounts whose fullname contains one
        of these substrings (case-insensitive).

    Returns
    -------
    dict mapping account fullname to its net Balance.
    """
    balances: dict[str, Balance] = {}
    patterns = [p.lower() for p in account_filter] if account_filter else []

    for xact in journal.xacts:
        for post in xact.posts:
            if post.amount is None or post.amount.is_null():
                continue

            acct = post.account
            if acct is None:
                continue

            name = acct.fullname
            if patterns and not any(p in name.lower() for p in patterns):
                continue

            if name not in balances:
                balances[name] = Balance()
            balances[name].add(post.amount)

    return balances


def _format_equity_transaction(xact: Transaction) -> str:
    """Format an equity transaction without eliding any amounts.

    Unlike ``format_transaction``, this always prints every posting's
    amount explicitly -- the whole point of the equity command is to
    show the balances.
    """
    lines: list[str] = []

    # Header line
    header: list[str] = []
    if xact.date is not None:
        header.append(xact.date.strftime("%Y/%m/%d"))
    else:
        header.append("0000/00/00")
    header.append(" ")
    header.append(xact.payee)
    lines.append("".join(header))

    # Postings -- never elide
    for post in xact.posts:
        post_line = format_posting(xact, post, elide_amount=False)
        lines.append(post_line)

    return "\n".join(lines) + "\n"


def equity_command(
    journal: Journal,
    args: Optional[list[str]] = None,
    equity_date: Optional[date] = None,
) -> str:
    """Produce equity output from *journal*.

    Generates an "Opening Balances" transaction whose postings reproduce
    the net balance of every account, offset by ``Equity:Opening Balances``.

    Parameters
    ----------
    journal:
        The journal containing transactions to process.
    args:
        Optional list of account-filter patterns.  Only accounts whose
        fullname contains one of these substrings (case-insensitive)
        will be included.
    equity_date:
        Date for the opening balance transaction.  Defaults to today.

    Returns
    -------
    str
        The formatted equity transaction(s) in journal format.
    """
    if args is None:
        args = []

    # Determine the date for the equity transaction.
    txn_date = equity_date if equity_date is not None else date.today()

    # Compute per-account balances.
    account_filter = args if args else None
    balances = _compute_account_balances(journal, account_filter)

    # Remove zero-balance accounts.
    balances = {
        name: bal for name, bal in balances.items()
        if not bal.is_zero() and not bal.is_empty()
    }

    if not balances:
        return ""

    # Build the equity transaction.
    xact = Transaction(payee="Opening Balances")
    xact.date = txn_date

    # Track the total offset needed for Equity:Opening Balances.
    equity_balance = Balance()

    # Sort accounts for deterministic output.
    for name in sorted(balances.keys()):
        bal = balances[name]
        # Each commodity in the balance gets its own posting.
        for amt in bal:
            account = journal.find_account(name)
            post = Post(account=account, amount=Amount(amt))
            xact.add_post(post)
            equity_balance.add(amt)

    # Add the balancing Equity:Opening Balances posting(s).
    neg_equity = -equity_balance
    if neg_equity.is_empty() or neg_equity.is_zero():
        # If the total is zero (e.g. filtered accounts that net to zero),
        # we still need a balancing entry with zero.  But typically the
        # full journal nets to zero, so the equity posting carries the
        # offset of the filtered subset.
        pass
    else:
        equity_account = journal.find_account("Equity:Opening Balances")
        for amt in neg_equity:
            post = Post(account=equity_account, amount=Amount(amt))
            xact.add_post(post)

    return _format_equity_transaction(xact)
