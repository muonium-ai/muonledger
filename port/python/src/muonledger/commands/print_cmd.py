"""Print command -- output transactions in canonical journal format.

Ported from ledger's ``print.cc``.  The print command reconstructs each
transaction line by line from parsed data structures, producing output
that is itself valid Ledger journal input (round-trippable).

Key concerns handled here:
  - Eliding redundant amounts in two-posting transactions where both
    postings have the same commodity and simple amounts.
  - Preserving cost annotations (``@``, ``@@``), virtual postings
    (``()`` and ``[]``), and per-posting clearing state.
  - Aligning amounts to a configurable column width.
  - Printing metadata tags and notes with proper indentation.
"""

from __future__ import annotations

from typing import Optional

from muonledger.item import ITEM_NOTE_ON_NEXT_LINE, ItemState
from muonledger.journal import Journal
from muonledger.post import (
    POST_CALCULATED,
    POST_COST_IN_FULL,
    POST_MUST_BALANCE,
    POST_VIRTUAL,
    Post,
)
from muonledger.xact import Transaction

__all__ = [
    "print_command",
    "format_transaction",
    "format_posting",
]

# Default column widths matching C++ ledger defaults.
ACCOUNT_WIDTH = 36
AMOUNT_WIDTH = 12
COLUMNS = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_has_simple_amount(post: Post) -> bool:
    """Return True if this posting has a simple, elide-able amount.

    A simple amount is one that was not calculated/inferred, has no
    assigned balance, and has no explicit cost.
    """
    if post.has_flags(POST_CALCULATED):
        return False
    if post.amount is None or post.amount.is_null():
        return False
    if post.assigned_amount is not None:
        return False
    if post.cost is not None:
        return False
    return True


def _format_account_name(xact: Transaction, post: Post) -> str:
    """Format a posting's account name with virtual delimiters and state."""
    parts: list[str] = []

    # Per-posting state marker (only if xact is uncleared)
    if xact.state == ItemState.UNCLEARED:
        if post.state == ItemState.CLEARED:
            parts.append("* ")
        elif post.state == ItemState.PENDING:
            parts.append("! ")

    # Virtual posting delimiters
    if post.has_flags(POST_VIRTUAL):
        if post.has_flags(POST_MUST_BALANCE):
            parts.append("[")
        else:
            parts.append("(")

    acct = post.account
    if acct is not None:
        parts.append(acct.fullname)
    else:
        parts.append("<unknown>")

    if post.has_flags(POST_VIRTUAL):
        if post.has_flags(POST_MUST_BALANCE):
            parts.append("]")
        else:
            parts.append(")")

    return "".join(parts)


def _print_note(
    note: str,
    note_on_next_line: bool,
    columns: int,
    prior_width: int,
) -> str:
    """Format a note/comment for output.

    If the note would overflow the column width or was originally on its
    own line, it is placed on a new indented line prefixed with ``;``.
    Multi-line notes have each line indented and prefixed.
    """
    # 3 = two spaces + semicolon before note
    if note_on_next_line or (
        columns > 0
        and (
            columns <= prior_width + 3
            or len(note) > columns - (prior_width + 3)
        )
    ):
        prefix = "\n    ;"
    else:
        prefix = "  ;"

    result = [prefix]
    need_separator = False
    for ch in note:
        if ch == "\n":
            need_separator = True
        else:
            if need_separator:
                result.append("\n    ;")
                need_separator = False
            result.append(ch)

    return "".join(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_posting(
    xact: Transaction,
    post: Post,
    account_width: int = ACCOUNT_WIDTH,
    amount_width: int = AMOUNT_WIDTH,
    columns: int = COLUMNS,
    elide_amount: bool = False,
) -> str:
    """Format a single posting line.

    Parameters
    ----------
    xact:
        The parent transaction (used for state comparison).
    post:
        The posting to format.
    account_width:
        Minimum column width for the account name.
    amount_width:
        Column width for amount right-justification.
    columns:
        Total terminal width for note wrapping.
    elide_amount:
        If True, omit the amount (used for auto-balanced postings).

    Returns
    -------
    str
        The formatted posting line (without trailing newline).
    """
    buf: list[str] = []
    buf.append("    ")

    acct_name = _format_account_name(xact, post)

    # Determine effective account width (expand if name is longer)
    eff_account_width = max(account_width, len(acct_name))

    if elide_amount:
        # Just the account name, no amount
        buf.append(acct_name)
    elif post.has_flags(POST_CALCULATED) and post.assigned_amount is None:
        # Calculated posting without balance assignment -- just account
        buf.append(acct_name)
    else:
        buf.append(acct_name)

        # Format the amount
        amt_str = ""
        if post.assigned_amount is not None and post.has_flags(POST_CALCULATED):
            # Balance assignment
            assign_str = " = " + str(post.assigned_amount)
            padding = amount_width - len(assign_str)
            if padding > 0:
                amt_str = " " * padding + assign_str
            else:
                amt_str = assign_str
        elif post.amount is not None and not post.amount.is_null():
            raw = str(post.amount)
            padding = amount_width - len(raw)
            if padding > 0:
                amt_str = " " * padding + raw
            else:
                amt_str = raw

        if amt_str:
            # Build the cost suffix
            cost_suffix = ""
            if (
                post.cost is not None
                and not post.has_flags(POST_CALCULATED)
            ):
                if post.has_flags(POST_COST_IN_FULL):
                    cost_op = "@@"
                    cost_val = str(abs(post.cost))
                else:
                    # Per-unit cost: cost / |amount|
                    if (
                        post.amount is not None
                        and not post.amount.is_null()
                        and not post.amount.is_realzero()
                    ):
                        per_unit = post.cost / abs(post.amount)
                        cost_val = str(abs(per_unit))
                    else:
                        cost_val = str(abs(post.cost))
                    cost_op = "@"
                cost_suffix = f" {cost_op} {cost_val}"

            full_amt = amt_str + cost_suffix

            # Ensure at least 2 spaces between account name and amount
            trimmed = full_amt.lstrip()
            amt_leading_spaces = len(full_amt) - len(trimmed)
            slip = eff_account_width - len(acct_name)
            if slip + amt_leading_spaces < 2:
                extra = 2 - (slip + amt_leading_spaces)
                full_amt = " " * extra + full_amt

            if slip > 0:
                buf.append(" " * slip)
            buf.append(full_amt)

    # Post note
    if post.note:
        note_str = _print_note(
            post.note,
            post.has_flags(ITEM_NOTE_ON_NEXT_LINE),
            columns,
            4 + eff_account_width,
        )
        buf.append(note_str)

    return "".join(buf)


def format_transaction(
    xact: Transaction,
    account_width: int = ACCOUNT_WIDTH,
    amount_width: int = AMOUNT_WIDTH,
    columns: int = COLUMNS,
) -> str:
    """Format a complete transaction as canonical journal text.

    Parameters
    ----------
    xact:
        The transaction to format.
    account_width:
        Minimum column width for account names.
    amount_width:
        Column width for amount right-justification.
    columns:
        Total terminal width for note wrapping.

    Returns
    -------
    str
        The formatted transaction (including trailing newline).
    """
    lines: list[str] = []

    # -- Header line --
    header: list[str] = []

    # Date
    if xact.date is not None:
        header.append(xact.date.strftime("%Y/%m/%d"))
    else:
        header.append("0000/00/00")

    # Auxiliary date
    if xact.date_aux is not None:
        header.append("=" + xact.date_aux.strftime("%Y/%m/%d"))

    header.append(" ")

    # State
    if xact.state == ItemState.CLEARED:
        header.append("* ")
    elif xact.state == ItemState.PENDING:
        header.append("! ")

    # Code
    if xact.code:
        header.append(f"({xact.code}) ")

    # Payee
    header.append(xact.payee)

    leader = "".join(header)
    line = leader

    # Transaction note
    if xact.note:
        note_str = _print_note(
            xact.note,
            xact.has_flags(ITEM_NOTE_ON_NEXT_LINE),
            columns,
            len(leader),
        )
        line += note_str

    lines.append(line)

    # -- Transaction-level metadata --
    if xact._metadata:
        for key, value in xact._metadata.items():
            if value is True:
                lines.append(f"    ; :{key}:")
            else:
                lines.append(f"    ; {key}: {value}")

    # -- Postings --
    count = len(xact.posts)

    # Compute effective account width (expand for long names)
    eff_account_width = account_width
    for post in xact.posts:
        name = _format_account_name(xact, post)
        if len(name) > eff_account_width:
            eff_account_width = len(name)

    for index, post in enumerate(xact.posts):
        # Determine if we should elide this posting's amount
        elide = False
        if (
            count == 2
            and index == 1
            and _post_has_simple_amount(post)
            and _post_has_simple_amount(xact.posts[0])
            and post.must_balance()
            and xact.posts[0].must_balance()
        ):
            # Check same commodity
            amt0 = xact.posts[0].amount
            amt1 = post.amount
            if (
                amt0 is not None
                and amt1 is not None
                and not amt0.is_null()
                and not amt1.is_null()
                and amt0.commodity == amt1.commodity
            ):
                elide = True

        post_line = format_posting(
            xact,
            post,
            account_width=eff_account_width,
            amount_width=amount_width,
            columns=columns,
            elide_amount=elide,
        )
        lines.append(post_line)

    return "\n".join(lines) + "\n"


def print_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """Produce print output from *journal*.

    Parameters
    ----------
    journal:
        The journal containing transactions to print.
    args:
        Optional list of pattern strings to filter transactions.
        A transaction matches if its payee contains any pattern
        (case-insensitive substring match).

    Returns
    -------
    str
        The formatted journal text.
    """
    if args is None:
        args = []

    patterns = [p.lower() for p in args]

    output_parts: list[str] = []
    first = True

    for xact in journal.xacts:
        # Filter by pattern if specified
        if patterns:
            payee_lower = xact.payee.lower()
            if not any(pat in payee_lower for pat in patterns):
                continue

        if first:
            first = False
        else:
            output_parts.append("\n")

        output_parts.append(format_transaction(xact))

    return "".join(output_parts)
