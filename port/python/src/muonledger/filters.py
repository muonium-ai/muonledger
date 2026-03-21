"""
Chain-of-responsibility filter pipeline for processing postings.

Ported from ledger's ``filters.h`` / ``filters.cc``.  Each filter is a
handler that receives postings one at a time via :meth:`__call__`, optionally
transforms or accumulates them, and forwards results to a downstream handler.

The pipeline is built by linking handlers: the outermost handler receives
postings first and passes them inward toward the terminal handler.

Base class hierarchy
--------------------
``PostHandler`` is the base for all posting filters.  It holds a reference
to the next (downstream) handler and provides default pass-through
implementations of ``flush``, ``__call__``, and ``clear``.

Filter inventory
----------------
- **PassThroughPosts** -- identity filter, forwards everything unchanged.
- **CollectPosts** -- accumulates postings into a list without forwarding.
- **FilterPosts** -- forwards only postings matching a predicate callable.
- **SortPosts** -- accumulates all postings, sorts on flush, then forwards.
- **TruncatePosts** -- limits output to the first N postings.
- **CalcPosts** -- computes running totals for each posting.
- **CollapsePosts** -- collapses multiple postings per transaction into one.
- **SubtotalPosts** -- accumulates subtotals by account.
- **IntervalPosts** -- groups postings by date intervals and subtotals each.
- **DisplayFilter** -- filters which posts to display based on a predicate.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.item import ITEM_GENERATED, ITEM_TEMP, Item
from muonledger.post import POST_CALCULATED, POST_GENERATED, Post
from muonledger.times import DateInterval
from muonledger.value import Value
from muonledger.xact import Transaction

__all__ = [
    "PostHandler",
    "PassThroughPosts",
    "CollectPosts",
    "FilterPosts",
    "SortPosts",
    "TruncatePosts",
    "CalcPosts",
    "CollapsePosts",
    "SubtotalPosts",
    "IntervalPosts",
    "DisplayFilter",
    "InvertPosts",
    "RelatedPosts",
    "MarketConvertPosts",
    "get_xdata",
    "clear_all_xdata",
    "build_chain",
]


# ---------------------------------------------------------------------------
# Base handler
# ---------------------------------------------------------------------------


class PostHandler:
    """Base class for all handlers in the posting filter pipeline.

    Implements the Chain of Responsibility pattern.  Each handler wraps
    an optional downstream handler.  The default implementations simply
    delegate to the downstream handler.

    Lifecycle
    ---------
    1. ``__call__(post)`` is called once per posting entering this stage.
    2. ``flush()`` is called after all postings have been submitted,
       giving accumulating filters a chance to emit their results.
    3. ``clear()`` resets mutable state for reuse.
    """

    def __init__(self, handler: Optional[PostHandler] = None) -> None:
        self.handler: Optional[PostHandler] = handler

    def __call__(self, post: Post) -> None:
        """Process a single posting.  Default: forward downstream."""
        if self.handler is not None:
            self.handler(post)

    def flush(self) -> None:
        """Emit any accumulated results, then flush downstream."""
        if self.handler is not None:
            self.handler.flush()

    def clear(self) -> None:
        """Reset mutable state for reuse."""
        if self.handler is not None:
            self.handler.clear()


# ---------------------------------------------------------------------------
# Pass-through / collection
# ---------------------------------------------------------------------------


class PassThroughPosts(PostHandler):
    """Identity filter -- forwards every posting unchanged."""
    pass


class CollectPosts(PostHandler):
    """Accumulates postings into a list without forwarding downstream."""

    def __init__(self) -> None:
        super().__init__(handler=None)
        self.posts: list[Post] = []

    def __call__(self, post: Post) -> None:
        self.posts.append(post)

    def flush(self) -> None:
        pass  # No downstream handler

    def clear(self) -> None:
        self.posts.clear()

    def __len__(self) -> int:
        return len(self.posts)

    def __iter__(self):
        return iter(self.posts)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class FilterPosts(PostHandler):
    """Forwards only postings that match a predicate.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    predicate : callable
        A callable that takes a :class:`Post` and returns a truthy value.
        Only postings for which the predicate returns True are forwarded.
    """

    def __init__(
        self,
        handler: PostHandler,
        predicate: Callable[[Post], bool],
    ) -> None:
        super().__init__(handler)
        self.predicate = predicate

    def __call__(self, post: Post) -> None:
        if self.predicate(post):
            assert self.handler is not None
            self.handler(post)


class DisplayFilter(PostHandler):
    """Filters which postings to display based on a predicate.

    Identical in structure to FilterPosts but named distinctly to match
    the C++ pipeline where display filtering is a separate stage from
    limit filtering.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    predicate : callable
        A callable that takes a :class:`Post` and returns True if the
        posting should be displayed.
    """

    def __init__(
        self,
        handler: PostHandler,
        predicate: Callable[[Post], bool],
    ) -> None:
        super().__init__(handler)
        self.predicate = predicate

    def __call__(self, post: Post) -> None:
        if self.predicate(post):
            assert self.handler is not None
            self.handler(post)


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class SortPosts(PostHandler):
    """Accumulates all postings, sorts on flush, then forwards in order.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    sort_key : callable
        A callable that takes a :class:`Post` and returns a sort key.
        Postings are sorted by this key using a stable sort.
    reverse : bool
        If True, sort in descending order.
    """

    def __init__(
        self,
        handler: PostHandler,
        sort_key: Callable[[Post], Any],
        reverse: bool = False,
    ) -> None:
        super().__init__(handler)
        self.sort_key = sort_key
        self.reverse = reverse
        self._posts: list[Post] = []

    def __call__(self, post: Post) -> None:
        self._posts.append(post)

    def post_accumulated_posts(self) -> None:
        """Sort accumulated postings and forward them downstream."""
        self._posts.sort(key=self.sort_key, reverse=self.reverse)
        for post in self._posts:
            assert self.handler is not None
            self.handler(post)
        self._posts.clear()

    def flush(self) -> None:
        self.post_accumulated_posts()
        super().flush()

    def clear(self) -> None:
        self._posts.clear()
        super().clear()


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TruncatePosts(PostHandler):
    """Limits output to the first *head_count* postings.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    head_count : int
        Maximum number of postings to forward.
    """

    def __init__(self, handler: PostHandler, head_count: int) -> None:
        super().__init__(handler)
        self.head_count = head_count
        self._count = 0

    def __call__(self, post: Post) -> None:
        if self._count < self.head_count:
            assert self.handler is not None
            self.handler(post)
            self._count += 1

    def clear(self) -> None:
        self._count = 0
        super().clear()


# ---------------------------------------------------------------------------
# Calculation (running totals)
# ---------------------------------------------------------------------------


class CalcPosts(PostHandler):
    """Computes running totals for the register report.

    For each posting, the handler evaluates the posting's amount (via
    *amount_fn*) and maintains a running total across all postings.
    The results are stored in ``post.xdata`` as ``visited_value`` and
    ``total``.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    amount_fn : callable, optional
        A callable ``(Post) -> Value`` that extracts the amount from a
        posting.  Defaults to ``lambda p: Value(p.amount)``.
    calc_running_total : bool
        Whether to maintain a running total across postings.
    """

    def __init__(
        self,
        handler: PostHandler,
        amount_fn: Optional[Callable[[Post], Value]] = None,
        calc_running_total: bool = True,
    ) -> None:
        super().__init__(handler)
        if amount_fn is None:
            self.amount_fn: Callable[[Post], Value] = lambda p: Value(p.amount)
        else:
            self.amount_fn = amount_fn
        self.calc_running_total = calc_running_total
        self._running_total: Value = Value()
        self._count: int = 0

    def __call__(self, post: Post) -> None:
        self._count += 1

        # Evaluate the posting amount.
        amount_value = self.amount_fn(post)

        # Store visited value in post xdata.
        xdata = _ensure_xdata(post)
        xdata["visited_value"] = amount_value
        xdata["count"] = self._count

        if self.calc_running_total:
            if self._running_total.is_null():
                self._running_total = Value(amount_value)
            else:
                self._running_total = self._running_total + amount_value
            xdata["total"] = Value(self._running_total)

        assert self.handler is not None
        self.handler(post)

    def clear(self) -> None:
        self._running_total = Value()
        self._count = 0
        super().clear()


# ---------------------------------------------------------------------------
# Collapse
# ---------------------------------------------------------------------------


class CollapsePosts(PostHandler):
    """Collapses multiple postings per transaction into one.

    When postings from the same transaction are received, they are
    accumulated.  When a new transaction is encountered (or on flush),
    a single synthetic posting representing the net amount is emitted.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    amount_fn : callable, optional
        Extracts the amount value from a posting.
    """

    def __init__(
        self,
        handler: PostHandler,
        amount_fn: Optional[Callable[[Post], Value]] = None,
    ) -> None:
        super().__init__(handler)
        if amount_fn is None:
            self.amount_fn: Callable[[Post], Value] = lambda p: Value(p.amount)
        else:
            self.amount_fn = amount_fn
        self._last_xact: Optional[Transaction] = None
        self._subtotal: Value = Value()
        self._count: int = 0
        self._last_post: Optional[Post] = None
        self._component_posts: list[Post] = []

    def _report_subtotal(self) -> None:
        """Emit the collapsed posting for the accumulated transaction."""
        if self._count == 0:
            return

        if self._count == 1 and self._last_post is not None:
            # Single posting: pass through directly.
            assert self.handler is not None
            self.handler(self._last_post)
        else:
            # Multiple postings: emit a synthetic collapsed posting.
            if self._last_post is not None:
                collapsed = Post(
                    account=self._last_post.account,
                    amount=self._subtotal.to_amount() if not self._subtotal.is_null() else Amount(0),
                    flags=ITEM_GENERATED,
                )
                collapsed._xact = self._last_xact
                if self._last_xact is not None and self._last_xact._date is not None:
                    collapsed._date = self._last_xact._date
                xdata = _ensure_xdata(collapsed)
                xdata["component_count"] = self._count
                assert self.handler is not None
                self.handler(collapsed)

        self._subtotal = Value()
        self._count = 0
        self._last_post = None
        self._component_posts.clear()

    def __call__(self, post: Post) -> None:
        if self._last_xact is not None and post.xact is not self._last_xact:
            self._report_subtotal()

        amount_value = self.amount_fn(post)
        if self._subtotal.is_null():
            self._subtotal = Value(amount_value)
        else:
            self._subtotal = self._subtotal + amount_value

        self._count += 1
        self._last_post = post
        self._last_xact = post.xact
        self._component_posts.append(post)

    def flush(self) -> None:
        self._report_subtotal()
        super().flush()

    def clear(self) -> None:
        self._last_xact = None
        self._subtotal = Value()
        self._count = 0
        self._last_post = None
        self._component_posts.clear()
        super().clear()


# ---------------------------------------------------------------------------
# Subtotal
# ---------------------------------------------------------------------------


class SubtotalPosts(PostHandler):
    """Accumulates subtotals by account for the balance report.

    All incoming postings are grouped by their account's fullname.
    On flush, a single synthetic posting per account is emitted with
    the accumulated total.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    amount_fn : callable, optional
        Extracts the amount value from a posting.
    """

    def __init__(
        self,
        handler: PostHandler,
        amount_fn: Optional[Callable[[Post], Value]] = None,
    ) -> None:
        super().__init__(handler)
        if amount_fn is None:
            self.amount_fn: Callable[[Post], Value] = lambda p: Value(p.amount)
        else:
            self.amount_fn = amount_fn
        # Map from account fullname -> (account, accumulated value)
        self._values: dict[str, tuple[Account, Value]] = {}
        self._component_posts: list[Post] = []

    def __call__(self, post: Post) -> None:
        self._component_posts.append(post)
        acct = post.account
        key = acct.fullname if acct is not None else ""

        amount_value = self.amount_fn(post)

        if key in self._values:
            existing_acct, existing_val = self._values[key]
            if existing_val.is_null():
                self._values[key] = (existing_acct, Value(amount_value))
            else:
                self._values[key] = (existing_acct, existing_val + amount_value)
        else:
            self._values[key] = (acct, Value(amount_value))

    def report_subtotal(self) -> None:
        """Emit synthetic postings for each account subtotal."""
        if not self._values:
            return

        # Determine date range from component posts
        if self._component_posts:
            min_date = None
            max_date = None
            for p in self._component_posts:
                d = p._date
                if d is not None:
                    if min_date is None or d < min_date:
                        min_date = d
                    if max_date is None or d > max_date:
                        max_date = d
        else:
            min_date = None
            max_date = None

        # Create a synthetic transaction
        xact = Transaction(payee="- Subtotal")
        if min_date is not None:
            xact._date = min_date

        for key in sorted(self._values.keys()):
            acct, value = self._values[key]
            amt = value.to_amount() if not value.is_null() else Amount(0)
            synth_post = Post(
                account=acct,
                amount=amt,
                flags=ITEM_GENERATED,
            )
            synth_post._xact = xact
            if min_date is not None:
                synth_post._date = min_date
            xdata = _ensure_xdata(synth_post)
            xdata["subtotal_value"] = value
            assert self.handler is not None
            self.handler(synth_post)

        self._values.clear()
        self._component_posts.clear()

    def flush(self) -> None:
        if self._values:
            self.report_subtotal()
        super().flush()

    def clear(self) -> None:
        self._values.clear()
        self._component_posts.clear()
        super().clear()


# ---------------------------------------------------------------------------
# Interval posts
# ---------------------------------------------------------------------------


class IntervalPosts(PostHandler):
    """Groups postings by date intervals and subtotals each period.

    Used for periodic reports (e.g. monthly, weekly).  When a duration
    is specified in the interval, postings are accumulated, sorted by
    date, then walked through the intervals -- each period is subtotaled
    and emitted as a synthetic posting per account.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    interval : DateInterval
        The interval specification (quantum, length, optional start/end).
    amount_fn : callable, optional
        Extracts the amount value from a posting.
    generate_empty : bool
        If True, emit zero-amount postings for empty periods.
    """

    def __init__(
        self,
        handler: PostHandler,
        interval: DateInterval,
        amount_fn: Optional[Callable[[Post], Value]] = None,
        generate_empty: bool = False,
    ) -> None:
        super().__init__(handler)
        self.interval = interval
        if amount_fn is None:
            self.amount_fn: Callable[[Post], Value] = lambda p: Value(p.amount)
        else:
            self.amount_fn = amount_fn
        self.generate_empty = generate_empty
        self._all_posts: list[Post] = []

    def __call__(self, post: Post) -> None:
        self._all_posts.append(post)

    def flush(self) -> None:
        if not self._all_posts:
            super().flush()
            return

        # Sort all posts by date
        self._all_posts.sort(key=lambda p: p._date or date.min)

        # Determine period boundaries
        dur = self.interval.duration

        # Determine the starting point
        if self.interval.start is not None:
            period_start = self.interval.start
        else:
            first_date = self._all_posts[0]._date
            if first_date is None:
                first_date = date.min
            period_start = first_date

        period_end = period_start + dur

        # Walk through postings, grouping by period
        # Use a subtotaler per period
        idx = 0
        n = len(self._all_posts)

        while idx < n or self.generate_empty:
            # Check if we've passed the interval's end bound
            if self.interval.end is not None and period_start >= self.interval.end:
                break

            # Collect postings in this period
            period_values: dict[str, tuple[Account, Value]] = {}
            saw_posts = False

            while idx < n:
                post = self._all_posts[idx]
                post_date = post._date or date.min
                if post_date >= period_end:
                    break
                # Accumulate
                acct = post.account
                key = acct.fullname if acct is not None else ""
                amount_value = self.amount_fn(post)

                if key in period_values:
                    existing_acct, existing_val = period_values[key]
                    if existing_val.is_null():
                        period_values[key] = (existing_acct, Value(amount_value))
                    else:
                        period_values[key] = (existing_acct, existing_val + amount_value)
                else:
                    period_values[key] = (acct, Value(amount_value))

                saw_posts = True
                idx += 1

            if saw_posts or self.generate_empty:
                # Emit subtotal for this period
                xact = Transaction(payee=f"- {period_start}")
                xact._date = period_start

                if period_values:
                    for key in sorted(period_values.keys()):
                        acct, value = period_values[key]
                        amt = value.to_amount() if not value.is_null() else Amount(0)
                        synth_post = Post(
                            account=acct,
                            amount=amt,
                            flags=ITEM_GENERATED,
                        )
                        synth_post._xact = xact
                        synth_post._date = period_start
                        xdata = _ensure_xdata(synth_post)
                        xdata["period_start"] = period_start
                        xdata["period_end"] = period_end
                        assert self.handler is not None
                        self.handler(synth_post)
                elif self.generate_empty:
                    # Emit a zero posting for empty period
                    empty_account = Account(name="<None>")
                    synth_post = Post(
                        account=empty_account,
                        amount=Amount(0),
                        flags=ITEM_GENERATED | POST_CALCULATED,
                    )
                    synth_post._xact = xact
                    synth_post._date = period_start
                    xdata = _ensure_xdata(synth_post)
                    xdata["period_start"] = period_start
                    xdata["period_end"] = period_end
                    assert self.handler is not None
                    self.handler(synth_post)

            # Advance period
            period_start = period_end
            period_end = period_start + dur

            # If no more posts and not generating empty, stop
            if idx >= n and not self.generate_empty:
                break

        self._all_posts.clear()
        super().flush()

    def clear(self) -> None:
        self._all_posts.clear()
        super().clear()


# ---------------------------------------------------------------------------
# Invert (negate amounts)
# ---------------------------------------------------------------------------


class InvertPosts(PostHandler):
    """Negates the amount of each posting before forwarding.

    Used to implement ``--invert``.  Creates a copy of the posting
    with the negated amount so the original is not mutated.
    """

    def __call__(self, post: Post) -> None:
        if post.amount is not None and not post.amount.is_null():
            inverted = Post(
                account=post.account,
                amount=Amount(-float(post.amount.quantity), post.amount.commodity),
                flags=post.flags,
                note=post.note,
            )
            inverted._xact = post._xact
            inverted._date = post._date
            inverted._date_aux = post._date_aux
            inverted._state = post._state
            assert self.handler is not None
            self.handler(inverted)
        else:
            assert self.handler is not None
            self.handler(post)


# ---------------------------------------------------------------------------
# Related postings
# ---------------------------------------------------------------------------


class RelatedPosts(PostHandler):
    """Replaces each posting with the related (other-side) postings.

    For each incoming posting, emits the other postings from the same
    transaction.  Used to implement ``--related`` and ``--related-all``.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    also_matching : bool
        If True (``--related-all``), also emit the original posting
        alongside the related ones.
    """

    def __init__(
        self,
        handler: PostHandler,
        also_matching: bool = False,
    ) -> None:
        super().__init__(handler)
        self.also_matching = also_matching
        self._seen: set[int] = set()

    def __call__(self, post: Post) -> None:
        if post.xact is None:
            assert self.handler is not None
            self.handler(post)
            return

        for other in post.xact.posts:
            if other is post and not self.also_matching:
                continue
            pid = id(other)
            if pid not in self._seen:
                self._seen.add(pid)
                assert self.handler is not None
                self.handler(other)

    def flush(self) -> None:
        self._seen.clear()
        super().flush()

    def clear(self) -> None:
        self._seen.clear()
        super().clear()


# ---------------------------------------------------------------------------
# Market / Exchange conversion
# ---------------------------------------------------------------------------


class MarketConvertPosts(PostHandler):
    """Convert posting amounts to a target commodity using a price history.

    When ``--market`` is used, amounts are converted to their market value
    using the most recent price.  When ``--exchange COMMODITY`` is used,
    amounts are converted to the specified target commodity.

    Parameters
    ----------
    handler : PostHandler
        Downstream handler.
    price_history : PriceHistory
        The price history to use for conversions.
    target_commodity : str or None
        If given, convert to this specific commodity (``--exchange``).
        If ``None``, convert to the price commodity of each amount (``--market``).
    """

    def __init__(
        self,
        handler: PostHandler,
        price_history: "PriceHistory",
        target_commodity: Optional[str] = None,
    ) -> None:
        super().__init__(handler)
        self.price_history = price_history
        self.target_commodity = target_commodity

    def __call__(self, post: Post) -> None:
        if post.amount is not None and not post.amount.is_null():
            source_comm = post.amount.commodity or ""
            if source_comm:
                target = self.target_commodity
                if target is None:
                    # --market: convert to whatever the price is denominated in
                    # Find the first direct price target for this commodity
                    target = self._find_market_target(source_comm)
                if target and target != source_comm:
                    converted = self.price_history.convert(
                        post.amount, target,
                        as_of=self._post_date(post),
                    )
                    if converted is not post.amount:
                        post.amount = converted
        if self.handler is not None:
            self.handler(post)

    def _find_market_target(self, commodity: str) -> Optional[str]:
        """Find the default market target for a commodity.

        Returns the commodity that this commodity has a direct price to,
        or None if no price exists.
        """
        from muonledger.price_history import PriceHistory

        for key in self.price_history._price_map:
            if key[0] == commodity:
                return key[1]
        return None

    @staticmethod
    def _post_date(post: Post) -> Optional["date"]:
        """Extract the effective date from a posting."""
        if post._date is not None:
            return post._date
        if post.xact is not None:
            return post.xact.date
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


import weakref

# Module-level storage for extended posting data (xdata).
# The Python Post class uses __slots__ without an xdata field, so we
# store extended data externally keyed by object id.  We use a plain
# dict since Post objects don't support weakref by default.
_post_xdata: dict[int, dict[str, Any]] = {}


def _ensure_xdata(post: Post) -> dict[str, Any]:
    """Ensure a posting has an xdata dict and return it.

    The Python Post class uses __slots__ and has no xdata field.  We
    store extended data in a module-level dict keyed by the post's id.
    """
    pid = id(post)
    if pid not in _post_xdata:
        _post_xdata[pid] = {}
    return _post_xdata[pid]


def get_xdata(post: Post) -> dict[str, Any]:
    """Get the xdata dict for a posting, or an empty dict if none exists."""
    return _post_xdata.get(id(post), {})


def clear_all_xdata() -> None:
    """Clear all stored xdata.  Useful for cleanup between test runs."""
    _post_xdata.clear()


def build_chain(*handlers: PostHandler) -> PostHandler:
    """Link handlers into a chain, returning the outermost handler.

    Handlers are specified from outermost (first to receive postings) to
    innermost (terminal handler).  Each handler's ``handler`` attribute
    is set to the next handler in the list.

    Example::

        chain = build_chain(
            SortPosts(None, key_fn),
            CalcPosts(None),
            CollectPosts(),
        )
        # Equivalent to: SortPosts -> CalcPosts -> CollectPosts

    Returns the first handler in the chain.
    """
    if not handlers:
        raise ValueError("At least one handler is required")

    for i in range(len(handlers) - 1):
        handlers[i].handler = handlers[i + 1]

    return handlers[0]
