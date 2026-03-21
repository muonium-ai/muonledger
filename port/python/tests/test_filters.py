"""Tests for the posting filter pipeline."""

from __future__ import annotations

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.filters import (
    CalcPosts,
    CollapsePosts,
    CollectPosts,
    DisplayFilter,
    FilterPosts,
    IntervalPosts,
    PassThroughPosts,
    PostHandler,
    SortPosts,
    SubtotalPosts,
    TruncatePosts,
    build_chain,
    clear_all_xdata,
    get_xdata,
)
from muonledger.item import ITEM_GENERATED
from muonledger.post import Post
from muonledger.times import DateInterval
from muonledger.value import Value
from muonledger.xact import Transaction


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_account(name: str) -> Account:
    """Create a standalone account with the given name."""
    root = Account(name="")
    return root.find_account(name)


def _make_post(
    account_name: str,
    amount_val: int | float,
    xact: Transaction | None = None,
    dt: date | None = None,
) -> Post:
    """Create a posting with the given account and amount."""
    acct = _make_account(account_name)
    amt = Amount(amount_val)
    post = Post(account=acct, amount=amt)
    if dt is not None:
        post._date = dt
    if xact is not None:
        xact.add_post(post)
    else:
        # Create a dummy transaction
        t = Transaction(payee="Test")
        if dt is not None:
            t._date = dt
        t.add_post(post)
    return post


def _make_xact(payee: str, dt: date | None = None) -> Transaction:
    """Create a transaction."""
    t = Transaction(payee=payee)
    if dt is not None:
        t._date = dt
    return t


@pytest.fixture(autouse=True)
def _cleanup_xdata():
    """Clear xdata between tests."""
    clear_all_xdata()
    yield
    clear_all_xdata()


# ---------------------------------------------------------------------------
# PostHandler base class
# ---------------------------------------------------------------------------


class TestPostHandler:
    def test_base_handler_forwards_to_downstream(self):
        collector = CollectPosts()
        handler = PostHandler(handler=collector)
        post = _make_post("Expenses:Food", 42)
        handler(post)
        assert len(collector) == 1

    def test_base_handler_without_downstream(self):
        handler = PostHandler()
        post = _make_post("Expenses:Food", 42)
        # Should not raise
        handler(post)

    def test_flush_propagates(self):
        collector = CollectPosts()
        handler = PostHandler(handler=collector)
        handler.flush()
        # flush should not raise

    def test_clear_propagates(self):
        collector = CollectPosts()
        handler = PostHandler(handler=collector)
        post = _make_post("Expenses:Food", 10)
        collector(post)
        assert len(collector) == 1
        handler.clear()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# PassThroughPosts
# ---------------------------------------------------------------------------


class TestPassThroughPosts:
    def test_forwards_all_posts(self):
        collector = CollectPosts()
        passthrough = PassThroughPosts(handler=collector)
        for i in range(5):
            passthrough(_make_post("Expenses", i + 1))
        assert len(collector) == 5

    def test_empty_input(self):
        collector = CollectPosts()
        passthrough = PassThroughPosts(handler=collector)
        passthrough.flush()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# CollectPosts
# ---------------------------------------------------------------------------


class TestCollectPosts:
    def test_collects_posts(self):
        collector = CollectPosts()
        p1 = _make_post("A", 10)
        p2 = _make_post("B", 20)
        collector(p1)
        collector(p2)
        assert len(collector) == 2
        assert list(collector) == [p1, p2]

    def test_clear(self):
        collector = CollectPosts()
        collector(_make_post("A", 10))
        collector.clear()
        assert len(collector) == 0

    def test_flush_is_noop(self):
        collector = CollectPosts()
        collector(_make_post("A", 10))
        collector.flush()
        # Posts should still be there
        assert len(collector) == 1


# ---------------------------------------------------------------------------
# FilterPosts
# ---------------------------------------------------------------------------


class TestFilterPosts:
    def test_filters_by_predicate(self):
        collector = CollectPosts()
        # Only pass through postings with amount > 20
        filt = FilterPosts(
            collector,
            predicate=lambda p: p.amount is not None and p.amount.quantity > 20,
        )
        filt(_make_post("A", 10))
        filt(_make_post("B", 30))
        filt(_make_post("C", 50))
        assert len(collector) == 2

    def test_all_filtered_out(self):
        collector = CollectPosts()
        filt = FilterPosts(collector, predicate=lambda p: False)
        filt(_make_post("A", 10))
        filt(_make_post("B", 20))
        assert len(collector) == 0

    def test_all_pass_through(self):
        collector = CollectPosts()
        filt = FilterPosts(collector, predicate=lambda p: True)
        filt(_make_post("A", 10))
        filt(_make_post("B", 20))
        assert len(collector) == 2

    def test_filter_by_account(self):
        collector = CollectPosts()
        filt = FilterPosts(
            collector,
            predicate=lambda p: p.account is not None
            and p.account.fullname.startswith("Expenses"),
        )
        filt(_make_post("Expenses:Food", 10))
        filt(_make_post("Assets:Cash", 20))
        filt(_make_post("Expenses:Rent", 30))
        assert len(collector) == 2


# ---------------------------------------------------------------------------
# DisplayFilter
# ---------------------------------------------------------------------------


class TestDisplayFilter:
    def test_display_filter_by_predicate(self):
        collector = CollectPosts()
        df = DisplayFilter(
            collector,
            predicate=lambda p: p.amount is not None and p.amount.quantity > 0,
        )
        df(_make_post("A", 10))
        df(_make_post("B", -5))
        df(_make_post("C", 20))
        assert len(collector) == 2

    def test_empty_input(self):
        collector = CollectPosts()
        df = DisplayFilter(collector, predicate=lambda p: True)
        df.flush()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# SortPosts
# ---------------------------------------------------------------------------


class TestSortPosts:
    def test_sort_by_amount(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
        )
        sorter(_make_post("A", 30))
        sorter(_make_post("B", 10))
        sorter(_make_post("C", 20))
        sorter.flush()
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [10, 20, 30]

    def test_sort_by_date(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p._date or date.min,
        )
        sorter(_make_post("A", 1, dt=date(2024, 3, 15)))
        sorter(_make_post("B", 2, dt=date(2024, 1, 1)))
        sorter(_make_post("C", 3, dt=date(2024, 2, 10)))
        sorter.flush()
        dates = [p._date for p in collector.posts]
        assert dates == [date(2024, 1, 1), date(2024, 2, 10), date(2024, 3, 15)]

    def test_sort_by_account_name(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.account.fullname if p.account is not None else "",
        )
        # Use a shared root so account hierarchy is consistent.
        root = Account(name="")
        acct_rent = root.find_account("Expenses:Rent")
        acct_cash = root.find_account("Assets:Cash")
        acct_sal = root.find_account("Income:Salary")

        p1 = Post(account=acct_rent, amount=Amount(500))
        p2 = Post(account=acct_cash, amount=Amount(100))
        p3 = Post(account=acct_sal, amount=Amount(3000))
        for p in (p1, p2, p3):
            t = Transaction(payee="Test")
            t.add_post(p)
            sorter(p)

        sorter.flush()
        names = [p.account.fullname for p in collector.posts]
        assert names == ["Assets:Cash", "Expenses:Rent", "Income:Salary"]

    def test_sort_reverse(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
            reverse=True,
        )
        sorter(_make_post("A", 10))
        sorter(_make_post("B", 30))
        sorter(_make_post("C", 20))
        sorter.flush()
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [30, 20, 10]

    def test_sort_stable(self):
        """Postings with equal keys maintain their insertion order."""
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: 1,  # all equal keys
        )
        posts = [_make_post(f"Account{i}", 10) for i in range(5)]
        for p in posts:
            sorter(p)
        sorter.flush()
        assert collector.posts == posts

    def test_sort_empty(self):
        collector = CollectPosts()
        sorter = SortPosts(collector, sort_key=lambda p: 0)
        sorter.flush()
        assert len(collector) == 0

    def test_sort_single(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
        )
        sorter(_make_post("A", 42))
        sorter.flush()
        assert len(collector) == 1

    def test_clear_resets(self):
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
        )
        sorter(_make_post("A", 10))
        sorter.clear()
        sorter.flush()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# TruncatePosts
# ---------------------------------------------------------------------------


class TestTruncatePosts:
    def test_truncate_to_n(self):
        collector = CollectPosts()
        truncator = TruncatePosts(collector, head_count=3)
        for i in range(10):
            truncator(_make_post("A", i))
        assert len(collector) == 3

    def test_truncate_more_than_available(self):
        collector = CollectPosts()
        truncator = TruncatePosts(collector, head_count=100)
        for i in range(5):
            truncator(_make_post("A", i))
        assert len(collector) == 5

    def test_truncate_zero(self):
        collector = CollectPosts()
        truncator = TruncatePosts(collector, head_count=0)
        truncator(_make_post("A", 10))
        assert len(collector) == 0

    def test_clear_resets_count(self):
        collector = CollectPosts()
        truncator = TruncatePosts(collector, head_count=2)
        truncator(_make_post("A", 1))
        truncator(_make_post("B", 2))
        truncator(_make_post("C", 3))
        assert len(collector) == 2
        collector.clear()
        truncator.clear()
        truncator(_make_post("D", 4))
        truncator(_make_post("E", 5))
        assert len(collector) == 2


# ---------------------------------------------------------------------------
# CalcPosts
# ---------------------------------------------------------------------------


class TestCalcPosts:
    def test_running_total(self):
        collector = CollectPosts()
        calc = CalcPosts(collector, calc_running_total=True)
        p1 = _make_post("A", 10)
        p2 = _make_post("A", 20)
        p3 = _make_post("A", 30)
        calc(p1)
        calc(p2)
        calc(p3)
        # Check running totals
        assert get_xdata(p1)["total"].to_amount().quantity == 10
        assert get_xdata(p2)["total"].to_amount().quantity == 30
        assert get_xdata(p3)["total"].to_amount().quantity == 60

    def test_visited_value(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        p1 = _make_post("A", 42)
        calc(p1)
        xd = get_xdata(p1)
        assert xd["visited_value"].to_amount().quantity == 42

    def test_count(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        posts = [_make_post("A", i + 1) for i in range(5)]
        for p in posts:
            calc(p)
        for i, p in enumerate(posts):
            assert get_xdata(p)["count"] == i + 1

    def test_no_running_total(self):
        collector = CollectPosts()
        calc = CalcPosts(collector, calc_running_total=False)
        p1 = _make_post("A", 10)
        calc(p1)
        xd = get_xdata(p1)
        assert "total" not in xd

    def test_custom_amount_fn(self):
        collector = CollectPosts()
        # Double the amount
        calc = CalcPosts(
            collector,
            amount_fn=lambda p: Value(Amount(p.amount.quantity * 2)),
            calc_running_total=True,
        )
        p1 = _make_post("A", 10)
        p2 = _make_post("A", 20)
        calc(p1)
        calc(p2)
        assert get_xdata(p1)["total"].to_amount().quantity == 20
        assert get_xdata(p2)["total"].to_amount().quantity == 60

    def test_forwards_downstream(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        calc(_make_post("A", 10))
        calc(_make_post("B", 20))
        assert len(collector) == 2

    def test_clear_resets(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        calc(_make_post("A", 10))
        calc.clear()
        p = _make_post("B", 20)
        calc(p)
        # After clear, running total should start fresh
        assert get_xdata(p)["total"].to_amount().quantity == 20
        assert get_xdata(p)["count"] == 1

    def test_empty_input(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        calc.flush()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# CollapsePosts
# ---------------------------------------------------------------------------


class TestCollapsePosts:
    def test_single_post_passthrough(self):
        collector = CollectPosts()
        collapse = CollapsePosts(collector)
        xact = _make_xact("Grocery", dt=date(2024, 1, 1))
        p = _make_post("Expenses:Food", 42, xact=xact, dt=date(2024, 1, 1))
        collapse(p)
        collapse.flush()
        assert len(collector) == 1
        # Single post is passed through directly
        assert collector.posts[0] is p

    def test_collapse_multiple_posts(self):
        collector = CollectPosts()
        collapse = CollapsePosts(collector)
        xact = _make_xact("Grocery", dt=date(2024, 1, 1))
        p1 = _make_post("Expenses:Food", 10, xact=xact, dt=date(2024, 1, 1))
        p2 = _make_post("Expenses:Drink", 20, xact=xact, dt=date(2024, 1, 1))
        p3 = _make_post("Assets:Cash", -30, xact=xact, dt=date(2024, 1, 1))
        collapse(p1)
        collapse(p2)
        collapse(p3)
        collapse.flush()
        # Should produce a single collapsed posting
        assert len(collector) == 1
        collapsed = collector.posts[0]
        assert collapsed.has_flags(ITEM_GENERATED)
        # Net amount should be 10 + 20 - 30 = 0
        assert collapsed.amount.quantity == 0

    def test_collapse_across_transactions(self):
        collector = CollectPosts()
        collapse = CollapsePosts(collector)

        xact1 = _make_xact("Store A", dt=date(2024, 1, 1))
        p1 = _make_post("Expenses:Food", 10, xact=xact1, dt=date(2024, 1, 1))
        p2 = _make_post("Assets:Cash", -10, xact=xact1, dt=date(2024, 1, 1))

        xact2 = _make_xact("Store B", dt=date(2024, 1, 2))
        p3 = _make_post("Expenses:Rent", 500, xact=xact2, dt=date(2024, 1, 2))

        collapse(p1)
        collapse(p2)
        collapse(p3)
        collapse.flush()

        # Two transactions -> two collapsed results
        assert len(collector) == 2

    def test_empty_input(self):
        collector = CollectPosts()
        collapse = CollapsePosts(collector)
        collapse.flush()
        assert len(collector) == 0

    def test_clear_resets(self):
        collector = CollectPosts()
        collapse = CollapsePosts(collector)
        xact = _make_xact("Test", dt=date(2024, 1, 1))
        collapse(_make_post("A", 10, xact=xact))
        collapse.clear()
        collapse.flush()
        # After clear, accumulated data is gone
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# SubtotalPosts
# ---------------------------------------------------------------------------


class TestSubtotalPosts:
    def test_subtotal_by_account(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal(_make_post("Expenses:Food", 10, dt=date(2024, 1, 1)))
        subtotal(_make_post("Expenses:Food", 20, dt=date(2024, 1, 2)))
        subtotal(_make_post("Expenses:Rent", 500, dt=date(2024, 1, 3)))
        subtotal.flush()

        # Should emit one posting per account
        assert len(collector) == 2
        amounts_by_account = {
            p.account.fullname: p.amount.quantity for p in collector.posts
        }
        assert amounts_by_account["Expenses:Food"] == 30
        assert amounts_by_account["Expenses:Rent"] == 500

    def test_subtotal_single_account(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal(_make_post("A", 10, dt=date(2024, 1, 1)))
        subtotal(_make_post("A", 20, dt=date(2024, 1, 2)))
        subtotal(_make_post("A", 30, dt=date(2024, 1, 3)))
        subtotal.flush()

        assert len(collector) == 1
        assert collector.posts[0].amount.quantity == 60

    def test_subtotal_empty(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal.flush()
        assert len(collector) == 0

    def test_subtotal_generated_flag(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal(_make_post("A", 10, dt=date(2024, 1, 1)))
        subtotal.flush()
        assert collector.posts[0].has_flags(ITEM_GENERATED)

    def test_subtotal_clear(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal(_make_post("A", 10, dt=date(2024, 1, 1)))
        subtotal.clear()
        subtotal.flush()
        assert len(collector) == 0

    def test_subtotal_negative_amounts(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        subtotal(_make_post("A", 100, dt=date(2024, 1, 1)))
        subtotal(_make_post("A", -30, dt=date(2024, 1, 2)))
        subtotal.flush()
        assert len(collector) == 1
        assert collector.posts[0].amount.quantity == 70

    def test_subtotal_custom_amount_fn(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(
            collector,
            amount_fn=lambda p: Value(Amount(p.amount.quantity * 2)),
        )
        subtotal(_make_post("A", 10, dt=date(2024, 1, 1)))
        subtotal(_make_post("A", 20, dt=date(2024, 1, 2)))
        subtotal.flush()
        assert collector.posts[0].amount.quantity == 60  # (10+20)*2


# ---------------------------------------------------------------------------
# IntervalPosts
# ---------------------------------------------------------------------------


class TestIntervalPosts:
    def test_monthly_grouping(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months",
            length=1,
            start=date(2024, 1, 1),
            end=date(2024, 4, 1),
        )
        ip = IntervalPosts(collector, interval)

        ip(_make_post("Expenses:Food", 10, dt=date(2024, 1, 5)))
        ip(_make_post("Expenses:Food", 20, dt=date(2024, 1, 15)))
        ip(_make_post("Expenses:Food", 30, dt=date(2024, 2, 10)))
        ip(_make_post("Expenses:Food", 40, dt=date(2024, 3, 20)))
        ip.flush()

        # 3 months with data
        assert len(collector) == 3
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [30, 30, 40]  # Jan: 10+20=30, Feb: 30, Mar: 40

    def test_weekly_grouping(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="weeks",
            length=1,
            start=date(2024, 1, 1),  # Monday
            end=date(2024, 1, 22),
        )
        ip = IntervalPosts(collector, interval)

        ip(_make_post("A", 10, dt=date(2024, 1, 2)))   # Week 1
        ip(_make_post("A", 20, dt=date(2024, 1, 3)))   # Week 1
        ip(_make_post("A", 30, dt=date(2024, 1, 9)))   # Week 2
        ip(_make_post("A", 40, dt=date(2024, 1, 16)))  # Week 3
        ip.flush()

        assert len(collector) == 3
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [30, 30, 40]

    def test_interval_multiple_accounts(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months",
            length=1,
            start=date(2024, 1, 1),
            end=date(2024, 2, 1),
        )
        ip = IntervalPosts(collector, interval)

        ip(_make_post("Expenses:Food", 10, dt=date(2024, 1, 5)))
        ip(_make_post("Expenses:Rent", 500, dt=date(2024, 1, 10)))
        ip.flush()

        # Two accounts in one period
        assert len(collector) == 2
        amounts_by_account = {
            p.account.fullname: p.amount.quantity for p in collector.posts
        }
        assert amounts_by_account["Expenses:Food"] == 10
        assert amounts_by_account["Expenses:Rent"] == 500

    def test_interval_empty_input(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months", length=1, start=date(2024, 1, 1),
        )
        ip = IntervalPosts(collector, interval)
        ip.flush()
        assert len(collector) == 0

    def test_interval_generate_empty(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months",
            length=1,
            start=date(2024, 1, 1),
            end=date(2024, 4, 1),
        )
        ip = IntervalPosts(collector, interval, generate_empty=True)

        # Only post in February
        ip(_make_post("A", 50, dt=date(2024, 2, 15)))
        ip.flush()

        # Should have 3 months: Jan (empty), Feb (50), Mar (empty)
        assert len(collector) == 3
        # Jan: empty
        assert collector.posts[0].amount.quantity == 0
        # Feb: 50
        assert collector.posts[1].amount.quantity == 50
        # Mar: empty
        assert collector.posts[2].amount.quantity == 0

    def test_interval_no_start(self):
        """When interval has no start, use the first posting's date."""
        collector = CollectPosts()
        interval = DateInterval(quantum="months", length=1)
        ip = IntervalPosts(collector, interval)

        ip(_make_post("A", 10, dt=date(2024, 3, 5)))
        ip(_make_post("A", 20, dt=date(2024, 3, 25)))
        ip(_make_post("A", 30, dt=date(2024, 4, 10)))
        ip.flush()

        assert len(collector) == 2
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [30, 30]

    def test_interval_xdata(self):
        """Synthetic posts should have period_start and period_end in xdata."""
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months",
            length=1,
            start=date(2024, 1, 1),
            end=date(2024, 2, 1),
        )
        ip = IntervalPosts(collector, interval)
        ip(_make_post("A", 10, dt=date(2024, 1, 15)))
        ip.flush()

        assert len(collector) == 1
        xd = get_xdata(collector.posts[0])
        assert xd["period_start"] == date(2024, 1, 1)
        assert xd["period_end"] == date(2024, 2, 1)

    def test_interval_clear(self):
        collector = CollectPosts()
        interval = DateInterval(
            quantum="months", length=1, start=date(2024, 1, 1),
        )
        ip = IntervalPosts(collector, interval)
        ip(_make_post("A", 10, dt=date(2024, 1, 5)))
        ip.clear()
        ip.flush()
        assert len(collector) == 0


# ---------------------------------------------------------------------------
# Filter chain composition
# ---------------------------------------------------------------------------


class TestFilterChain:
    def test_sort_then_truncate(self):
        """Sort by amount descending, then take only top 2."""
        collector = CollectPosts()
        truncator = TruncatePosts(collector, head_count=2)
        sorter = SortPosts(
            truncator,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
            reverse=True,
        )

        sorter(_make_post("A", 10))
        sorter(_make_post("B", 50))
        sorter(_make_post("C", 30))
        sorter(_make_post("D", 20))
        sorter.flush()

        assert len(collector) == 2
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [50, 30]

    def test_filter_then_sort(self):
        """Filter positive amounts, then sort ascending."""
        collector = CollectPosts()
        sorter = SortPosts(
            collector,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
        )
        filt = FilterPosts(
            sorter,
            predicate=lambda p: p.amount is not None and p.amount.quantity > 0,
        )

        filt(_make_post("A", -10))
        filt(_make_post("B", 30))
        filt(_make_post("C", -5))
        filt(_make_post("D", 10))
        filt.flush()

        assert len(collector) == 2
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [10, 30]

    def test_sort_then_calc(self):
        """Sort by date, then compute running totals."""
        collector = CollectPosts()
        calc = CalcPosts(collector)
        sorter = SortPosts(
            calc,
            sort_key=lambda p: p._date or date.min,
        )

        p1 = _make_post("A", 30, dt=date(2024, 3, 1))
        p2 = _make_post("A", 10, dt=date(2024, 1, 1))
        p3 = _make_post("A", 20, dt=date(2024, 2, 1))

        sorter(p1)
        sorter(p2)
        sorter(p3)
        sorter.flush()

        assert len(collector) == 3
        # After sorting by date: p2(10), p3(20), p1(30)
        # Running totals: 10, 30, 60
        totals = [get_xdata(p)["total"].to_amount().quantity for p in collector.posts]
        assert totals == [10, 30, 60]

    def test_build_chain_helper(self):
        """Test the build_chain convenience function."""
        collector = CollectPosts()
        sorter = SortPosts(
            None,
            sort_key=lambda p: p.amount.quantity if p.amount else 0,
        )
        truncator = TruncatePosts(None, head_count=2)

        chain = build_chain(sorter, truncator, collector)
        assert chain is sorter
        assert sorter.handler is truncator
        assert truncator.handler is collector

        chain(_make_post("A", 30))
        chain(_make_post("B", 10))
        chain(_make_post("C", 20))
        chain.flush()

        assert len(collector) == 2
        amounts = [p.amount.quantity for p in collector.posts]
        assert amounts == [10, 20]

    def test_build_chain_single(self):
        """build_chain with a single handler returns it unchanged."""
        collector = CollectPosts()
        chain = build_chain(collector)
        assert chain is collector

    def test_build_chain_empty(self):
        with pytest.raises(ValueError):
            build_chain()

    def test_three_stage_pipeline(self):
        """Filter -> Sort -> Calc -> Collect."""
        collector = CollectPosts()
        calc = CalcPosts(None)
        sorter = SortPosts(None, sort_key=lambda p: p._date or date.min)
        filt = FilterPosts(
            None,
            predicate=lambda p: p.amount is not None and p.amount.quantity > 0,
        )
        chain = build_chain(filt, sorter, calc, collector)

        chain(_make_post("A", -10, dt=date(2024, 1, 1)))
        chain(_make_post("B", 20, dt=date(2024, 3, 1)))
        chain(_make_post("C", 30, dt=date(2024, 2, 1)))
        chain.flush()

        assert len(collector) == 2
        # Sorted by date: C(30, Feb), B(20, Mar)
        # Running totals: 30, 50
        totals = [get_xdata(p)["total"].to_amount().quantity for p in collector.posts]
        assert totals == [30, 50]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_post_through_full_pipeline(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        sorter = SortPosts(calc, sort_key=lambda p: 0)
        filt = FilterPosts(sorter, predicate=lambda p: True)

        p = _make_post("A", 42, dt=date(2024, 1, 1))
        filt(p)
        filt.flush()

        assert len(collector) == 1
        assert get_xdata(collector.posts[0])["total"].to_amount().quantity == 42

    def test_zero_amount(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        p = _make_post("A", 0)
        calc(p)
        assert get_xdata(p)["total"].to_amount().quantity == 0

    def test_negative_amounts(self):
        collector = CollectPosts()
        calc = CalcPosts(collector)
        p1 = _make_post("A", -10)
        p2 = _make_post("A", -20)
        calc(p1)
        calc(p2)
        assert get_xdata(p2)["total"].to_amount().quantity == -30

    def test_subtotal_with_all_same_account(self):
        collector = CollectPosts()
        subtotal = SubtotalPosts(collector)
        for i in range(100):
            subtotal(_make_post("SingleAccount", 1, dt=date(2024, 1, 1)))
        subtotal.flush()
        assert len(collector) == 1
        assert collector.posts[0].amount.quantity == 100
