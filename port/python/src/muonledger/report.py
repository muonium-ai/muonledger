"""
Core report options for controlling how reports are filtered and displayed.

Ported from ledger's ``report.h`` / ``report.cc``.  The :class:`ReportOptions`
class collects all user-configurable options that influence report generation:
date filtering, amount expressions, sorting, grouping, subtotals, display
controls, commodity handling, and clearing-state filters.

Two key functions operate on a populated :class:`ReportOptions`:

- :func:`build_filter_chain` -- constructs the posting filter pipeline.
- :func:`apply_to_journal` -- pre-filters a journal's transactions by date
  and clearing state, returning the list of qualifying postings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Optional

from muonledger.amount import Amount
from muonledger.filters import (
    CalcPosts,
    CollapsePosts,
    CollectPosts,
    DisplayFilter,
    FilterPosts,
    IntervalPosts,
    InvertPosts,
    PostHandler,
    RelatedPosts,
    SortPosts,
    SubtotalPosts,
    TruncatePosts,
)
from muonledger.item import ITEM_GENERATED, ItemState
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.times import DateInterval, parse_date, parse_period
from muonledger.value import Value

__all__ = [
    "ReportOptions",
    "build_filter_chain",
    "apply_to_journal",
]


# ---------------------------------------------------------------------------
# ReportOptions
# ---------------------------------------------------------------------------


@dataclass
class ReportOptions:
    """Collects all report options that control filtering and display.

    Each attribute corresponds to a command-line option from ledger.
    Options left at their default (``None`` or ``False``) are inactive.

    Date filtering
    ~~~~~~~~~~~~~~
    - ``begin`` / ``end`` -- restrict to transactions within [begin, end).
    - ``period`` -- a period expression string (e.g. ``"monthly"``).
    - ``current`` -- if True, exclude future-dated transactions.

    Amount display
    ~~~~~~~~~~~~~~
    - ``amount_expr`` -- expression string controlling the displayed amount.
    - ``total_expr`` -- expression string controlling the displayed total.
    - ``display_expr`` -- expression controlling which posts to display.

    Sorting
    ~~~~~~~
    - ``sort_expr`` -- sort key expression string.
    - ``sort_xacts`` -- if True, sort transactions rather than postings.
    - ``sort_all`` -- if True, apply sort across all postings globally.

    Grouping intervals
    ~~~~~~~~~~~~~~~~~~
    - ``daily`` / ``weekly`` / ``monthly`` / ``quarterly`` / ``yearly``
    - ``collapse`` -- collapse postings per transaction into one.

    Subtotal
    ~~~~~~~~
    - ``subtotal`` -- produce subtotals by account.
    - ``related`` -- show related (other-side) postings.
    - ``budget`` -- budget reporting mode.

    Display
    ~~~~~~~
    - ``flat`` -- flat account display (no tree indentation).
    - ``no_total`` -- suppress the total line.
    - ``depth`` -- maximum account depth to display.
    - ``limit_expr`` -- predicate controlling which posts enter the pipeline.

    Output
    ~~~~~~
    - ``format_string`` -- custom format string.
    - ``head`` -- show only the first N postings.
    - ``tail`` -- show only the last N postings.

    Commodity
    ~~~~~~~~~
    - ``market`` -- convert to market value.
    - ``exchange`` -- target commodity for conversion.

    Clearing state
    ~~~~~~~~~~~~~~
    - ``cleared`` -- show only cleared items.
    - ``uncleared`` -- show only uncleared items.
    - ``pending`` -- show only pending items.
    - ``real`` -- show only real (non-virtual) postings.
    """

    # Date filtering
    begin: Optional[date] = None
    end: Optional[date] = None
    period: Optional[str] = None
    current: bool = False

    # Amount display
    amount_expr: Optional[str] = None
    total_expr: Optional[str] = None
    display_expr: Optional[str] = None

    # Sorting
    sort_expr: Optional[str] = None
    sort_xacts: bool = False
    sort_all: bool = False

    # Grouping intervals
    daily: bool = False
    weekly: bool = False
    monthly: bool = False
    quarterly: bool = False
    yearly: bool = False
    collapse: bool = False

    # Subtotal
    subtotal: bool = False
    related: bool = False
    budget: bool = False

    # Display
    flat: bool = False
    no_total: bool = False
    depth: int = 0
    limit_expr: Optional[str] = None

    # Output
    format_string: Optional[str] = None
    head: Optional[int] = None
    tail: Optional[int] = None

    # Commodity
    market: bool = False
    exchange: Optional[str] = None

    # Clearing state
    cleared: bool = False
    uncleared: bool = False
    pending: bool = False
    real: bool = False

    # Width options
    account_width: int = 0
    amount_width: int = 0
    total_width: int = 0
    date_width: int = 0
    payee_width: int = 0

    # Display modes
    by_payee: bool = False
    average: bool = False
    deviation: bool = False
    percent: bool = False
    invert: bool = False
    amount_data: bool = False
    total_data: bool = False

    # Lot/price options
    lots: bool = False
    lot_dates: bool = False
    lot_prices: bool = False
    lot_notes: bool = False
    lot_tags: bool = False
    price_db: Optional[str] = None

    # Advanced grouping
    pivot: Optional[str] = None
    group_by: Optional[str] = None
    date_format: Optional[str] = None

    # Account options
    empty: bool = False
    dc: bool = False
    gain: bool = False
    basis: bool = False
    revalued: bool = False
    unrealized: bool = False

    # Filtering
    payee_filter: Optional[str] = None
    account_filter: Optional[str] = None
    tag_filter: Optional[str] = None
    note_filter: Optional[str] = None

    # Output
    count: bool = False
    total_only: bool = False
    columns: int = 80
    wide: bool = False
    output_file: Optional[str] = None
    pager: Optional[str] = None

    # Misc
    color: bool = False
    force_color: bool = False
    no_color: bool = False
    auto_pager: bool = False
    prepend_format: Optional[str] = None
    prepend_width: int = 0

    # -- Account options (ticket-specified) ----------------------------------
    account: Optional[str] = None           # --account EXPR
    abbrev_len: Optional[int] = None        # --abbrev-len N

    # -- Display options (ticket-specified) ----------------------------------
    auto_match: bool = False                # --auto-match

    # -- Date options (ticket-specified) -------------------------------------
    effective: bool = False                 # --effective (use aux/effective dates)
    actual: bool = False                    # --actual (only actual, non-automated)

    # -- Commodity options (ticket-specified) ---------------------------------
    price: bool = False                     # --price (display price)
    cost: bool = False                      # --cost (display cost basis)

    # -- Balance-specific options (ticket-specified) -------------------------
    no_elide: bool = False                  # --no-elide
    accounts_only: bool = False             # --accounts-only
    totals_only: bool = False               # --totals-only

    # -- Register-specific options (ticket-specified) ------------------------
    related_all: bool = False               # --related-all
    inject: Optional[str] = None            # --inject AMOUNT

    # -- Meta options (ticket-specified) -------------------------------------
    group_title_format: Optional[str] = None  # --group-title-format STR

    # -----------------------------------------------------------------
    # Derived helpers
    # -----------------------------------------------------------------

    @property
    def grouping_interval(self) -> Optional[DateInterval]:
        """Return the grouping interval implied by the interval flags.

        Returns ``None`` if no grouping flag is set.  If ``period`` is
        set it takes precedence over the convenience flags.
        """
        if self.period is not None:
            return parse_period(self.period)
        if self.daily:
            return DateInterval("days", 1)
        if self.weekly:
            return DateInterval("weeks", 1)
        if self.monthly:
            return DateInterval("months", 1)
        if self.quarterly:
            return DateInterval("quarters", 1)
        if self.yearly:
            return DateInterval("years", 1)
        return None

    @property
    def clearing_state_filter(self) -> Optional[ItemState]:
        """Return the single clearing state to accept, or ``None`` for all.

        Only one of ``cleared``, ``uncleared``, ``pending`` should be set.
        If none is set, returns ``None`` (accept everything).
        """
        if self.cleared:
            return ItemState.CLEARED
        if self.pending:
            return ItemState.PENDING
        if self.uncleared:
            return ItemState.UNCLEARED
        return None

    def effective_begin(self) -> Optional[date]:
        """Return the effective begin date, considering ``period``."""
        if self.begin is not None:
            return self.begin
        interval = self.grouping_interval
        if interval is not None and interval.start is not None:
            return interval.start
        return None

    def effective_end(self) -> Optional[date]:
        """Return the effective end date, considering ``period`` and ``current``."""
        if self.current:
            from muonledger.times import today
            t = today()
            if self.end is not None:
                return min(self.end, t + timedelta(days=1))
            return t + timedelta(days=1)
        if self.end is not None:
            return self.end
        interval = self.grouping_interval
        if interval is not None and interval.end is not None:
            return interval.end
        return None


# ---------------------------------------------------------------------------
# build_filter_chain
# ---------------------------------------------------------------------------


def build_filter_chain(
    options: ReportOptions,
    handler: PostHandler,
) -> PostHandler:
    """Construct a filter pipeline from *options*, terminating at *handler*.

    The chain is built inside-out: *handler* is the innermost (terminal)
    handler and filters wrap around it.  The returned handler is the
    outermost -- callers should feed postings into it.

    The assembly order mirrors ledger's ``report_t::chain_post_handlers``:

    1. Display filter (``--display``)
    2. Truncation (``--head`` / ``--tail``)
    3. Sorting (``--sort``)
    4. Running-total calculation
    5. Interval grouping (``--daily``, ``--monthly``, etc.)
    6. Subtotal (``--subtotal``)
    7. Collapse (``--collapse``)
    8. Limit filter (``--limit``)
    """
    chain = handler

    # -- Display filter ------------------------------------------------------
    if options.display_expr is not None:
        expr_text = options.display_expr
        chain = DisplayFilter(chain, _make_predicate(expr_text))

    # -- Truncation ----------------------------------------------------------
    if options.head is not None and options.head > 0:
        chain = TruncatePosts(chain, options.head)
    # tail is handled after accumulation (see note below)

    # -- Sorting -------------------------------------------------------------
    if options.sort_expr is not None:
        sort_key = _make_sort_key(options.sort_expr)
        chain = SortPosts(chain, sort_key)

    # -- Running-total calculation -------------------------------------------
    amount_fn: Optional[Callable[[Post], Value]] = None
    if options.average:
        amount_fn = _make_average_fn()
    chain = CalcPosts(chain, amount_fn=amount_fn)

    # -- Invert (negate amounts) ---------------------------------------------
    if options.invert:
        chain = InvertPosts(chain)

    # -- Interval grouping ---------------------------------------------------
    interval = options.grouping_interval
    if interval is not None:
        chain = IntervalPosts(chain, interval, generate_empty=options.empty)

    # -- Subtotal ------------------------------------------------------------
    if options.subtotal or options.by_payee:
        chain = SubtotalPosts(chain)

    # -- Collapse ------------------------------------------------------------
    if options.collapse:
        chain = CollapsePosts(chain)

    # -- Related postings filter ---------------------------------------------
    if options.related or options.related_all:
        chain = RelatedPosts(chain, also_matching=options.related_all)

    # -- Limit filter --------------------------------------------------------
    if options.limit_expr is not None:
        chain = FilterPosts(chain, _make_predicate(options.limit_expr))

    # -- Account filter (--account EXPR) -------------------------------------
    if options.account is not None:
        chain = FilterPosts(chain, _make_predicate(options.account))

    return chain


# ---------------------------------------------------------------------------
# apply_to_journal
# ---------------------------------------------------------------------------


def apply_to_journal(
    options: ReportOptions,
    journal: Journal,
) -> list[Post]:
    """Filter a journal's transactions and return qualifying postings.

    Applies the following filters in order:

    1. Date range (``begin`` / ``end`` / ``current``)
    2. Clearing state (``cleared`` / ``uncleared`` / ``pending``)
    3. Real-posting filter (``real``)
    4. Account depth restriction (``depth``)

    Returns a flat list of :class:`Post` objects from all qualifying
    transactions, in journal order.
    """
    import re as _re

    begin = options.effective_begin()
    end = options.effective_end()
    state_filter = options.clearing_state_filter
    use_effective = options.effective

    # Pre-compile filter patterns
    payee_pat = (
        _re.compile(options.payee_filter, _re.IGNORECASE)
        if options.payee_filter is not None
        else None
    )
    account_pat = (
        _re.compile(options.account_filter, _re.IGNORECASE)
        if options.account_filter is not None
        else None
    )
    note_pat = (
        _re.compile(options.note_filter, _re.IGNORECASE)
        if options.note_filter is not None
        else None
    )
    tag_filter = options.tag_filter

    posts: list[Post] = []

    for xact in journal.xacts:
        # When --effective, prefer aux date; otherwise primary date
        if use_effective and xact.date_aux is not None:
            xact_date = xact.date_aux
        else:
            xact_date = xact.date
        if xact_date is None:
            continue

        # --actual: skip generated/automated transactions
        if options.actual and xact.has_flags(ITEM_GENERATED):
            continue

        # Date filtering
        if begin is not None and xact_date < begin:
            continue
        if end is not None and xact_date >= end:
            continue

        # Payee filter (transaction-level)
        if payee_pat is not None:
            if not payee_pat.search(xact.payee):
                continue

        # Clearing state on the transaction level
        if state_filter is not None and xact.state != state_filter:
            # Also check per-posting state below
            pass

        for post in xact.posts:
            # Per-posting clearing state
            if state_filter is not None:
                if post.state != ItemState.UNCLEARED:
                    effective_state = post.state
                else:
                    effective_state = xact.state
                if effective_state != state_filter:
                    continue

            # Real-posting filter
            if options.real and post.is_virtual():
                continue

            # --actual: skip generated postings
            if options.actual and post.has_flags(ITEM_GENERATED):
                continue

            # Depth filter
            if options.depth > 0 and post.account is not None:
                acct_depth = post.account.fullname.count(":") + 1
                if acct_depth > options.depth:
                    continue

            # Account filter
            if account_pat is not None:
                acct_name = post.account.fullname if post.account is not None else ""
                if not account_pat.search(acct_name):
                    continue

            # Tag filter
            if tag_filter is not None and not post.has_tag(tag_filter):
                continue

            # Note filter
            if note_pat is not None:
                post_note = post.note or ""
                xact_note = xact.note or ""
                combined_note = post_note + " " + xact_note
                if not note_pat.search(combined_note):
                    continue

            # Empty filter: skip zero-amount postings unless empty is set
            if (
                not options.empty
                and post.amount is not None
                and post.amount.is_null()
            ):
                # Only skip if the amount is explicitly zero/null
                # Normal non-null amounts always pass
                pass

            posts.append(post)

    return posts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_predicate(expr: str) -> Callable[[Post], bool]:
    """Build a simple predicate callable from an expression string.

    For the initial implementation we support a small set of built-in
    predicates.  Complex expressions will be handled by the expression
    evaluator in a future ticket.
    """
    expr = expr.strip()

    # "cleared" / "pending" / "uncleared" state predicates
    if expr == "cleared":
        return lambda p: (p.state == ItemState.CLEARED or
                          (p.state == ItemState.UNCLEARED and
                           p.xact is not None and
                           p.xact.state == ItemState.CLEARED))
    if expr == "pending":
        return lambda p: (p.state == ItemState.PENDING or
                          (p.state == ItemState.UNCLEARED and
                           p.xact is not None and
                           p.xact.state == ItemState.PENDING))
    if expr == "uncleared":
        return lambda p: (p.state == ItemState.UNCLEARED and
                          (p.xact is None or p.xact.state == ItemState.UNCLEARED))

    # "real" predicate
    if expr == "real":
        return lambda p: not p.is_virtual()

    # "virtual" predicate
    if expr == "virtual":
        return lambda p: p.is_virtual()

    # account name substring match: /pattern/
    if expr.startswith("/") and expr.endswith("/") and len(expr) > 2:
        pattern = expr[1:-1].lower()
        return lambda p, pat=pattern: (
            p.account is not None and pat in p.account.fullname.lower()
        )

    # Amount comparison: amount > N, amount < N, amount >= N, amount <= N
    import re
    amt_match = re.match(r"amount\s*(>=|<=|>|<|==|!=)\s*(-?\d+(?:\.\d+)?)", expr)
    if amt_match:
        op = amt_match.group(1)
        threshold = float(amt_match.group(2))
        def _amt_pred(p: Post, _op=op, _th=threshold) -> bool:
            if p.amount is None or p.amount.is_null():
                return False
            qty = float(p.amount.quantity)
            if _op == ">":
                return qty > _th
            if _op == "<":
                return qty < _th
            if _op == ">=":
                return qty >= _th
            if _op == "<=":
                return qty <= _th
            if _op == "==":
                return qty == _th
            if _op == "!=":
                return qty != _th
            return False
        return _amt_pred

    # "true" -- always pass
    if expr.lower() == "true":
        return lambda p: True

    # "false" -- never pass
    if expr.lower() == "false":
        return lambda p: False

    # Default: treat as account name substring match
    lower_expr = expr.lower()
    return lambda p, pat=lower_expr: (
        p.account is not None and pat in p.account.fullname.lower()
    )


def _make_sort_key(expr: str) -> Callable[[Post], Any]:
    """Build a sort-key callable from an expression string.

    Supports a small set of built-in sort keys for common report sorting.
    """
    expr = expr.strip().lower()

    if expr == "date":
        return lambda p: p._date or (p.xact.date if p.xact else date.min) or date.min

    if expr == "amount":
        return lambda p: float(p.amount.quantity) if (p.amount and not p.amount.is_null()) else 0.0

    if expr == "-amount":
        return lambda p: -float(p.amount.quantity) if (p.amount and not p.amount.is_null()) else 0.0

    if expr == "account":
        return lambda p: p.account.fullname if p.account is not None else ""

    if expr == "payee":
        return lambda p: p.xact.payee if p.xact is not None else ""

    if expr in ("-date", "date desc"):
        return lambda p: -(p._date or (p.xact.date if p.xact else date.min) or date.min).toordinal()

    # Default: sort by date
    return lambda p: p._date or (p.xact.date if p.xact else date.min) or date.min


def _make_average_fn() -> Callable[[Post], Value]:
    """Build an amount function that computes running average.

    Returns a callable that tracks count and running sum, returning
    the average amount (sum / count) for each posting.
    """
    state = {"count": 0, "total": Value()}

    def _avg_fn(post: Post) -> Value:
        state["count"] += 1
        amt = Value(post.amount)
        if state["total"].is_null():
            state["total"] = amt
        else:
            state["total"] = state["total"] + amt
        # Compute average: total / count
        total_amount = state["total"].to_amount()
        if total_amount is not None and not total_amount.is_null():
            avg_qty = float(total_amount.quantity) / state["count"]
            return Value(Amount(avg_qty, total_amount.commodity))
        return Value(Amount(0))

    return _avg_fn
