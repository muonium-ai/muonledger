"""Balance command -- produces a balance report from a journal.

Ported from ledger's ``output.cc`` (``format_accounts``) and the balance
report logic.  Given a :class:`Journal`, accumulates posting amounts into
their accounts and renders a formatted balance report.

The output format mirrors ledger's default balance format::

               $100.00  Assets:Bank:Checking
               $-50.00  Expenses:Food
    --------------------
                $50.00

"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Optional

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.balance import Balance
from muonledger.journal import Journal

__all__ = ["balance_command"]

# Column width for amounts (right-aligned within this width).
AMOUNT_WIDTH = 20
# Separator line width matches amount column.
SEPARATOR = "-" * AMOUNT_WIDTH


def _parse_date_arg(text: str) -> date:
    """Parse a date argument in YYYY-MM-DD or YYYY/MM/DD format."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {text!r}")


def _parse_args(args: list[str]) -> argparse.Namespace:
    """Parse balance command arguments."""
    parser = argparse.ArgumentParser(prog="balance", add_help=False)
    parser.add_argument("--flat", action="store_true", default=False)
    parser.add_argument("--no-total", action="store_true", default=False)
    parser.add_argument("-n", "--collapse", action="store_true", default=False,
                        dest="collapse")
    parser.add_argument("--empty", "-E", action="store_true", default=False)
    parser.add_argument("--depth", type=int, default=0)
    parser.add_argument("--begin", type=_parse_date_arg, default=None)
    parser.add_argument("--end", type=_parse_date_arg, default=None)
    parser.add_argument("patterns", nargs="*")
    return parser.parse_args(args)


def _accumulate_balances(journal: Journal, begin: Optional[date] = None,
                         end: Optional[date] = None) -> dict[str, Balance]:
    """Walk all transactions and accumulate per-account balances.

    Returns a dict mapping full account name to its Balance.
    """
    balances: dict[str, Balance] = {}
    for xact in journal.xacts:
        # Date filtering: --begin means >= date, --end means < date
        if begin is not None and xact.date is not None:
            if xact.date < begin:
                continue
        if end is not None and xact.date is not None:
            if xact.date >= end:
                continue
        for post in xact.posts:
            if post.amount is None or post.amount.is_null():
                continue
            acct = post.account
            if acct is None:
                continue
            name = acct.fullname
            if name not in balances:
                balances[name] = Balance()
            balances[name].add(post.amount)
    return balances


def _roll_up_to_parents(
    balances: dict[str, Balance],
) -> dict[str, Balance]:
    """Roll up leaf balances into all ancestor accounts.

    Returns a new dict containing every account (leaf and parent) with its
    rolled-up total.
    """
    rolled: dict[str, Balance] = {}
    for name, bal in balances.items():
        parts = name.split(":")
        for i in range(1, len(parts) + 1):
            ancestor = ":".join(parts[:i])
            if ancestor not in rolled:
                rolled[ancestor] = Balance()
            rolled[ancestor].add(bal)
    return rolled


def _get_children(name: str, all_names: set[str]) -> list[str]:
    """Return immediate children of *name* from the set of all account names."""
    prefix = name + ":"
    children = []
    for n in all_names:
        if not n.startswith(prefix):
            continue
        rest = n[len(prefix):]
        if ":" not in rest:
            children.append(n)
    return sorted(children)


def _account_known(name: str, journal: Journal) -> bool:
    """Return True if the account exists in the journal's account tree."""
    return journal.master.find_account(name, auto_create=False) is not None


def _collect_tree_accounts(
    rolled: dict[str, Balance],
    leaf_balances: dict[str, Balance],
    show_empty: bool,
    depth: int,
    journal: Journal,
) -> list[tuple[str, str, Balance]]:
    """Determine which accounts to show in tree mode.

    Returns a list of (display_name, full_name, balance) tuples.

    Ledger's tree mode collapses single-child chains: if an account has
    exactly one visible child and no direct postings, the account is not
    shown on its own line; instead, its child absorbs it and displays
    with a collapsed name (e.g. ``Equity:Opening balances``).

    The display_name for child accounts whose parents are already
    displayed uses only the leaf segment of the name.
    """
    all_names = set(rolled.keys())
    top_level = sorted(n for n in all_names if ":" not in n)

    result: list[tuple[str, str, Balance]] = []

    def _visible_children(name: str) -> list[str]:
        children = _get_children(name, all_names)
        if not show_empty:
            children = [c for c in children
                        if rolled.get(c, Balance()).is_nonzero()]
        return children

    def _has_direct(name: str) -> bool:
        """Does this account have direct postings with non-zero balance?"""
        return name in leaf_balances and leaf_balances[name].is_nonzero()

    def _has_direct_or_known(name: str) -> bool:
        """Check if account has direct postings (appears in leaf_balances).

        This determines whether an account can be collapsed. An account
        with direct postings should NOT be collapsed even if it has only
        one child, because collapsing would hide the account's own entry.
        """
        return name in leaf_balances

    def _walk(name: str, current_depth: int, collapse_prefix: str,
              indent_depth: int) -> None:
        """Walk the account tree depth-first.

        *collapse_prefix* accumulates collapsed parent names. When a
        parent with a single child and no direct postings is encountered,
        its name is prepended to the child's display name via this
        parameter.

        *indent_depth* tracks the visual indentation level (number of
        parent accounts already displayed above this one).
        """
        if depth > 0 and current_depth >= depth:
            return

        bal = rolled.get(name, Balance())
        children = _visible_children(name)

        # Build the display name for this node.
        leaf_segment = name.rsplit(":", 1)[-1]
        if collapse_prefix:
            display = collapse_prefix + ":" + leaf_segment
        else:
            display = leaf_segment

        # Collapse: if exactly one child and no direct postings,
        # pass our display name down to the child.
        if len(children) == 1 and not _has_direct_or_known(name):
            _walk(children[0], current_depth, display, indent_depth)
            return

        # Should we display this account?
        should_show = False
        if bal.is_nonzero():
            should_show = True
        elif show_empty and _has_direct_or_known(name):
            should_show = True

        if not should_show and not children:
            return

        if should_show:
            # Add indentation: 2 spaces per indent level
            indented_display = "  " * indent_depth + display
            result.append((indented_display, name, bal))

        for child in children:
            child_prefix = "" if should_show else display
            _walk(child, current_depth + 1, child_prefix,
                  indent_depth + 1 if should_show else indent_depth)

    for top in top_level:
        _walk(top, 0, "", 0)

    return result


def _format_amount_lines(bal: Balance) -> list[str]:
    """Format a Balance into right-aligned amount strings.

    Each commodity gets its own line (multi-commodity support).
    If the balance is empty/zero, returns a single "0" line.
    """
    if bal.is_empty():
        return [str(0).rjust(AMOUNT_WIDTH)]

    lines = []
    for amt in bal:  # iterates in sorted commodity order
        lines.append(str(amt).rjust(AMOUNT_WIDTH))

    if not lines:
        lines.append(str(0).rjust(AMOUNT_WIDTH))

    return lines


def balance_command(
    journal: Journal,
    args: Optional[list[str]] = None,
) -> str:
    """Produce a balance report from *journal*.

    Parameters
    ----------
    journal:
        The journal containing transactions to report on.
    args:
        Command-line style arguments (e.g. ``["--flat", "Assets"]``).

    Returns
    -------
    str
        The formatted balance report.
    """
    if args is None:
        args = []
    opts = _parse_args(args)
    no_total = opts.no_total
    patterns = opts.patterns

    # -n / --collapse is equivalent to --depth 1 in tree mode.
    # In flat mode, -n produces no output (collapse is meaningless for flat).
    effective_depth = opts.depth
    if opts.collapse and not opts.flat and effective_depth == 0:
        effective_depth = 1

    # Step 1: Accumulate per-account (leaf) balances.
    leaf_balances = _accumulate_balances(journal, begin=opts.begin, end=opts.end)

    # Step 2: Roll up balances to parents.
    rolled = _roll_up_to_parents(leaf_balances)

    # Step 3: Apply depth limiting.
    if effective_depth > 0:
        rolled = _apply_depth(rolled, effective_depth)
        leaf_balances_depth: dict[str, Balance] = {}
        for name, bal in leaf_balances.items():
            parts = name.split(":")
            if len(parts) > effective_depth:
                truncated = ":".join(parts[: effective_depth])
            else:
                truncated = name
            if truncated not in leaf_balances_depth:
                leaf_balances_depth[truncated] = Balance()
            leaf_balances_depth[truncated].add(bal)
        leaf_balances = leaf_balances_depth

    # Step 4: Determine which accounts to display.
    if opts.flat and opts.collapse:
        # -n/--collapse with --flat produces no output in C++ ledger.
        accounts = []
    elif opts.flat:
        accounts = _flat_accounts(
            leaf_balances, rolled, patterns, opts.empty, effective_depth
        )
    else:
        accounts = _tree_accounts(
            leaf_balances, rolled, patterns, opts.empty, effective_depth, journal
        )

    # Step 5: Render.
    lines: list[str] = []

    for display_name, full_name, bal in accounts:
        amt_lines = _format_amount_lines(bal)
        lines.append(f"{amt_lines[0]}  {display_name}")
        for extra in amt_lines[1:]:
            lines.append(extra)

    # Compute grand total from leaf balances (avoids double-counting in
    # tree mode where parent and child are both displayed).
    grand_total = Balance()
    for bal in leaf_balances.values():
        grand_total.add(bal)

    # If patterns are active, compute total only from matching accounts.
    if patterns:
        grand_total = Balance()
        for display_name, full_name, bal in accounts:
            # In flat mode, each entry is a leaf -- safe to sum.
            # In tree mode, we only sum entries that have no displayed
            # children to avoid double-counting.
            if opts.flat:
                grand_total.add(bal)
            else:
                # Use leaf balances for matching accounts.
                if full_name in leaf_balances:
                    grand_total.add(leaf_balances[full_name])

    # Total line.
    if not no_total and len(accounts) > 0:
        lines.append(SEPARATOR)
        if grand_total.is_empty() or grand_total.is_zero():
            lines.append(str(0).rjust(AMOUNT_WIDTH))
        else:
            total_lines = _format_amount_lines(grand_total)
            for tl in total_lines:
                lines.append(tl)

    if not lines:
        return ""

    return "\n".join(lines) + "\n"


def _apply_depth(
    rolled: dict[str, Balance], depth: int
) -> dict[str, Balance]:
    """Truncate account names to *depth* segments and re-merge."""
    result: dict[str, Balance] = {}
    for name, bal in rolled.items():
        parts = name.split(":")
        if len(parts) <= depth:
            result[name] = Balance(bal)
    return result


def _flat_accounts(
    leaf_balances: dict[str, Balance],
    rolled: dict[str, Balance],
    patterns: list[str],
    show_empty: bool,
    depth: int,
) -> list[tuple[str, str, Balance]]:
    """Collect accounts for flat display."""
    result: list[tuple[str, str, Balance]] = []
    for name in sorted(leaf_balances.keys()):
        bal = leaf_balances[name]
        if not show_empty and not bal.is_nonzero():
            continue
        if patterns and not _matches(name, patterns):
            continue
        if depth > 0 and len(name.split(":")) > depth:
            continue
        result.append((name, name, bal))
    return result


def _tree_accounts(
    leaf_balances: dict[str, Balance],
    rolled: dict[str, Balance],
    patterns: list[str],
    show_empty: bool,
    depth: int,
    journal: Journal,
) -> list[tuple[str, str, Balance]]:
    """Collect accounts for tree (default) display."""
    entries = _collect_tree_accounts(
        rolled, leaf_balances, show_empty, depth, journal
    )

    if patterns:
        matching_full = set()
        for _, full, _ in entries:
            if _matches(full, patterns):
                matching_full.add(full)
        ancestor_names = set()
        for fn in matching_full:
            parts = fn.split(":")
            for i in range(1, len(parts)):
                ancestor_names.add(":".join(parts[:i]))

        filtered = []
        for display, full, bal in entries:
            if full in matching_full or full in ancestor_names:
                filtered.append((display, full, bal))
        entries = filtered

    return entries


def _matches(name: str, patterns: list[str]) -> bool:
    """Simple substring match: True if *name* contains any pattern."""
    name_lower = name.lower()
    return any(p.lower() in name_lower for p in patterns)
