"""Tests for the core report options module."""

from __future__ import annotations

from datetime import date, timedelta

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
    PostHandler,
    SortPosts,
    SubtotalPosts,
    TruncatePosts,
    clear_all_xdata,
    get_xdata,
)
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import POST_VIRTUAL, Post
from muonledger.report import (
    ReportOptions,
    apply_to_journal,
    build_filter_chain,
)
from muonledger.times import DateInterval
from muonledger.value import Value
from muonledger.xact import Transaction


# ---------------------------------------------------------------------------
# Helpers
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
    state: ItemState = ItemState.UNCLEARED,
) -> Post:
    """Create a posting with the given account and amount."""
    acct = _make_account(account_name)
    amt = Amount(amount_val)
    post = Post(account=acct, amount=amt)
    if dt is not None:
        post._date = dt
    post._state = state
    if xact is not None:
        xact.add_post(post)
    else:
        tx = Transaction(payee="Test")
        tx._date = dt or date(2024, 1, 1)
        tx._state = state
        tx.add_post(post)
    return post


def _make_journal_from_text(text: str) -> Journal:
    """Parse a journal text string and return the Journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


@pytest.fixture(autouse=True)
def _cleanup():
    """Clear xdata between tests."""
    yield
    clear_all_xdata()


# ---------------------------------------------------------------------------
# Option parsing and defaults
# ---------------------------------------------------------------------------


class TestReportOptionsDefaults:
    """Test that default option values are correct."""

    def test_default_dates_are_none(self):
        opts = ReportOptions()
        assert opts.begin is None
        assert opts.end is None

    def test_default_period_is_none(self):
        opts = ReportOptions()
        assert opts.period is None

    def test_default_current_is_false(self):
        opts = ReportOptions()
        assert opts.current is False

    def test_default_sort_expr_is_none(self):
        opts = ReportOptions()
        assert opts.sort_expr is None

    def test_default_grouping_flags_are_false(self):
        opts = ReportOptions()
        assert opts.daily is False
        assert opts.weekly is False
        assert opts.monthly is False
        assert opts.quarterly is False
        assert opts.yearly is False

    def test_default_display_flags(self):
        opts = ReportOptions()
        assert opts.flat is False
        assert opts.no_total is False
        assert opts.depth == 0

    def test_default_clearing_flags(self):
        opts = ReportOptions()
        assert opts.cleared is False
        assert opts.uncleared is False
        assert opts.pending is False
        assert opts.real is False

    def test_default_head_tail_are_none(self):
        opts = ReportOptions()
        assert opts.head is None
        assert opts.tail is None

    def test_default_subtotal_and_collapse(self):
        opts = ReportOptions()
        assert opts.subtotal is False
        assert opts.collapse is False

    def test_default_commodity_flags(self):
        opts = ReportOptions()
        assert opts.market is False
        assert opts.exchange is None


# ---------------------------------------------------------------------------
# Date filtering (begin / end)
# ---------------------------------------------------------------------------


class TestDateFiltering:
    """Test date-based transaction filtering."""

    JOURNAL_TEXT = """\
2024/01/15 Groceries
    Expenses:Food        $50.00
    Assets:Checking

2024/02/10 Utilities
    Expenses:Utilities   $100.00
    Assets:Checking

2024/03/20 Rent
    Expenses:Rent        $1200.00
    Assets:Checking
"""

    def test_no_date_filter_returns_all(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions()
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 6  # 3 xacts * 2 posts each

    def test_begin_date_excludes_earlier(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(begin=date(2024, 2, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 4  # Feb + Mar xacts

    def test_end_date_excludes_later(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(end=date(2024, 3, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 4  # Jan + Feb xacts

    def test_begin_and_end_date_range(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(begin=date(2024, 2, 1), end=date(2024, 3, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 2  # Only Feb xact

    def test_begin_after_all_returns_empty(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(begin=date(2025, 1, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 0

    def test_end_before_all_returns_empty(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(end=date(2024, 1, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 0


# ---------------------------------------------------------------------------
# Sorting options
# ---------------------------------------------------------------------------


class TestSortingOptions:
    """Test sort-related option properties."""

    def test_no_sort_expr_means_no_sorting(self):
        opts = ReportOptions()
        assert opts.sort_expr is None

    def test_sort_by_date(self):
        opts = ReportOptions(sort_expr="date")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        # The chain should contain a SortPosts handler
        assert _chain_contains(chain, SortPosts)

    def test_sort_by_amount(self):
        opts = ReportOptions(sort_expr="amount")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SortPosts)

    def test_sort_by_account(self):
        opts = ReportOptions(sort_expr="account")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SortPosts)

    def test_sort_xacts_flag(self):
        opts = ReportOptions(sort_expr="date", sort_xacts=True)
        assert opts.sort_xacts is True

    def test_sort_all_flag(self):
        opts = ReportOptions(sort_expr="date", sort_all=True)
        assert opts.sort_all is True


# ---------------------------------------------------------------------------
# Grouping intervals
# ---------------------------------------------------------------------------


class TestGroupingIntervals:
    """Test grouping interval derivation from option flags."""

    def test_daily_interval(self):
        opts = ReportOptions(daily=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "days"
        assert interval.length == 1

    def test_weekly_interval(self):
        opts = ReportOptions(weekly=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "weeks"
        assert interval.length == 1

    def test_monthly_interval(self):
        opts = ReportOptions(monthly=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "months"
        assert interval.length == 1

    def test_quarterly_interval(self):
        opts = ReportOptions(quarterly=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "quarters"
        assert interval.length == 1

    def test_yearly_interval(self):
        opts = ReportOptions(yearly=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "years"
        assert interval.length == 1

    def test_no_grouping_returns_none(self):
        opts = ReportOptions()
        assert opts.grouping_interval is None

    def test_period_overrides_flags(self):
        opts = ReportOptions(period="weekly", monthly=True)
        interval = opts.grouping_interval
        assert interval is not None
        assert interval.quantum == "weeks"  # period wins


# ---------------------------------------------------------------------------
# Display options (flat, depth, head/tail)
# ---------------------------------------------------------------------------


class TestDisplayOptions:
    """Test display-related options."""

    def test_flat_flag(self):
        opts = ReportOptions(flat=True)
        assert opts.flat is True

    def test_depth_filter(self):
        journal = _make_journal_from_text("""\
2024/01/15 Test
    Expenses:Food:Groceries    $50.00
    Assets:Checking
""")
        # depth=1 should exclude Expenses:Food:Groceries (depth 3)
        opts = ReportOptions(depth=1)
        posts = apply_to_journal(opts, journal)
        # Only Assets:Checking (depth 1) should pass
        account_names = [p.account.fullname for p in posts]
        for name in account_names:
            assert name.count(":") + 1 <= 1

    def test_depth_zero_means_no_limit(self):
        journal = _make_journal_from_text("""\
2024/01/15 Test
    Expenses:Food:Groceries    $50.00
    Assets:Checking
""")
        opts = ReportOptions(depth=0)
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 2

    def test_head_filter_in_chain(self):
        opts = ReportOptions(head=3)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, TruncatePosts)

    def test_no_total_flag(self):
        opts = ReportOptions(no_total=True)
        assert opts.no_total is True


# ---------------------------------------------------------------------------
# Clearing state filters
# ---------------------------------------------------------------------------


class TestClearingStateFilters:
    """Test clearing-state filtering options."""

    JOURNAL_TEXT = """\
2024/01/15 * Cleared Purchase
    Expenses:Food        $30.00
    Assets:Checking

2024/01/20 ! Pending Purchase
    Expenses:Food        $20.00
    Assets:Checking

2024/01/25 Uncleared Purchase
    Expenses:Food        $10.00
    Assets:Checking
"""

    def test_cleared_filter(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(cleared=True)
        posts = apply_to_journal(opts, journal)
        # Only the cleared transaction's posts
        assert len(posts) == 2
        for p in posts:
            assert p.xact.state == ItemState.CLEARED

    def test_pending_filter(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(pending=True)
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 2
        for p in posts:
            assert p.xact.state == ItemState.PENDING

    def test_uncleared_filter(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(uncleared=True)
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 2
        for p in posts:
            assert p.xact.state == ItemState.UNCLEARED

    def test_no_clearing_filter_returns_all(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions()
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 6

    def test_clearing_state_filter_property(self):
        opts = ReportOptions(cleared=True)
        assert opts.clearing_state_filter == ItemState.CLEARED
        opts2 = ReportOptions(pending=True)
        assert opts2.clearing_state_filter == ItemState.PENDING
        opts3 = ReportOptions(uncleared=True)
        assert opts3.clearing_state_filter == ItemState.UNCLEARED
        opts4 = ReportOptions()
        assert opts4.clearing_state_filter is None


# ---------------------------------------------------------------------------
# Real posting filter
# ---------------------------------------------------------------------------


class TestRealPostingFilter:
    """Test the --real option that filters out virtual postings."""

    JOURNAL_TEXT = """\
2024/01/15 Test
    Expenses:Food        $50.00
    Assets:Checking     $-50.00
    (Budget:Food)        $50.00
"""

    def test_real_filter_excludes_virtual(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(real=True)
        posts = apply_to_journal(opts, journal)
        for p in posts:
            assert not p.is_virtual()

    def test_no_real_filter_includes_virtual(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions()
        posts = apply_to_journal(opts, journal)
        assert any(p.is_virtual() for p in posts)


# ---------------------------------------------------------------------------
# Filter chain construction
# ---------------------------------------------------------------------------


class TestFilterChainConstruction:
    """Test that build_filter_chain assembles the correct pipeline."""

    def test_default_options_produce_calc_chain(self):
        opts = ReportOptions()
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        # Should at minimum contain CalcPosts
        assert _chain_contains(chain, CalcPosts)

    def test_subtotal_option_adds_subtotal_filter(self):
        opts = ReportOptions(subtotal=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SubtotalPosts)

    def test_collapse_option_adds_collapse_filter(self):
        opts = ReportOptions(collapse=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, CollapsePosts)

    def test_monthly_option_adds_interval_filter(self):
        opts = ReportOptions(monthly=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, IntervalPosts)

    def test_sort_option_adds_sort_filter(self):
        opts = ReportOptions(sort_expr="date")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SortPosts)

    def test_limit_expr_adds_filter_posts(self):
        opts = ReportOptions(limit_expr="true")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, FilterPosts)

    def test_display_expr_adds_display_filter(self):
        opts = ReportOptions(display_expr="true")
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, DisplayFilter)

    def test_head_option_adds_truncate(self):
        opts = ReportOptions(head=5)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, TruncatePosts)

    def test_combined_options_build_full_chain(self):
        opts = ReportOptions(
            sort_expr="date",
            monthly=True,
            subtotal=True,
            collapse=True,
            limit_expr="true",
            display_expr="true",
            head=10,
        )
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SortPosts)
        assert _chain_contains(chain, IntervalPosts)
        assert _chain_contains(chain, SubtotalPosts)
        assert _chain_contains(chain, CollapsePosts)
        assert _chain_contains(chain, FilterPosts)
        assert _chain_contains(chain, DisplayFilter)
        assert _chain_contains(chain, TruncatePosts)
        assert _chain_contains(chain, CalcPosts)


# ---------------------------------------------------------------------------
# Integration: filter chain actually processes postings
# ---------------------------------------------------------------------------


class TestFilterChainIntegration:
    """Test that the filter chain correctly processes postings end-to-end."""

    JOURNAL_TEXT = """\
2024/01/15 Groceries
    Expenses:Food        $50.00
    Assets:Checking

2024/02/10 More Groceries
    Expenses:Food        $30.00
    Assets:Checking

2024/03/20 Rent
    Expenses:Rent        $1200.00
    Assets:Checking
"""

    def test_default_chain_passes_all_through(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions()
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)

        posts = apply_to_journal(opts, journal)
        for p in posts:
            chain(p)
        chain.flush()

        assert len(collector.posts) == 6

    def test_head_truncates_output(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(head=2)
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)

        posts = apply_to_journal(opts, journal)
        for p in posts:
            chain(p)
        chain.flush()

        assert len(collector.posts) == 2

    def test_date_filter_with_chain(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(begin=date(2024, 2, 1), end=date(2024, 3, 1))
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)

        posts = apply_to_journal(opts, journal)
        for p in posts:
            chain(p)
        chain.flush()

        assert len(collector.posts) == 2

    def test_sort_by_amount_orders_correctly(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(sort_expr="amount")
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)

        posts = apply_to_journal(opts, journal)
        for p in posts:
            chain(p)
        chain.flush()

        # Verify sorted by amount
        amounts = []
        for p in collector.posts:
            if p.amount and not p.amount.is_null():
                amounts.append(float(p.amount.quantity))
        # Should be in ascending order
        assert amounts == sorted(amounts)

    def test_limit_expr_filters_posts(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(limit_expr="/food/")
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)

        posts = apply_to_journal(opts, journal)
        for p in posts:
            chain(p)
        chain.flush()

        # Only Expenses:Food posts should pass
        for p in collector.posts:
            assert "Food" in p.account.fullname


# ---------------------------------------------------------------------------
# Effective date helpers
# ---------------------------------------------------------------------------


class TestEffectiveDates:
    """Test effective_begin and effective_end helpers."""

    def test_effective_begin_from_begin(self):
        opts = ReportOptions(begin=date(2024, 3, 1))
        assert opts.effective_begin() == date(2024, 3, 1)

    def test_effective_begin_none_when_no_option(self):
        opts = ReportOptions()
        assert opts.effective_begin() is None

    def test_effective_end_from_end(self):
        opts = ReportOptions(end=date(2024, 6, 1))
        assert opts.effective_end() == date(2024, 6, 1)

    def test_effective_end_none_when_no_option(self):
        opts = ReportOptions()
        assert opts.effective_end() is None

    def test_effective_end_with_current(self):
        opts = ReportOptions(current=True)
        result = opts.effective_end()
        assert result is not None
        from muonledger.times import today
        assert result == today() + timedelta(days=1)

    def test_effective_begin_from_period(self):
        opts = ReportOptions(
            period="monthly from 2024/01/01 to 2024/06/01"
        )
        assert opts.effective_begin() == date(2024, 1, 1)

    def test_effective_end_from_period(self):
        opts = ReportOptions(
            period="monthly from 2024/01/01 to 2024/06/01"
        )
        assert opts.effective_end() == date(2024, 6, 1)


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


class TestPredicateHelpers:
    """Test the internal predicate builders."""

    def test_amount_greater_than(self):
        from muonledger.report import _make_predicate
        pred = _make_predicate("amount > 100")
        p1 = _make_post("Expenses:Food", 150)
        p2 = _make_post("Expenses:Food", 50)
        assert pred(p1) is True
        assert pred(p2) is False

    def test_amount_less_than(self):
        from muonledger.report import _make_predicate
        pred = _make_predicate("amount < 100")
        p1 = _make_post("Expenses:Food", 50)
        p2 = _make_post("Expenses:Food", 150)
        assert pred(p1) is True
        assert pred(p2) is False

    def test_account_pattern(self):
        from muonledger.report import _make_predicate
        pred = _make_predicate("/food/")
        p1 = _make_post("Expenses:Food", 50)
        p2 = _make_post("Assets:Checking", 50)
        assert pred(p1) is True
        assert pred(p2) is False

    def test_true_predicate(self):
        from muonledger.report import _make_predicate
        pred = _make_predicate("true")
        p = _make_post("Expenses:Food", 50)
        assert pred(p) is True

    def test_false_predicate(self):
        from muonledger.report import _make_predicate
        pred = _make_predicate("false")
        p = _make_post("Expenses:Food", 50)
        assert pred(p) is False


# ---------------------------------------------------------------------------
# Sort key helpers
# ---------------------------------------------------------------------------


class TestSortKeyHelpers:
    """Test the internal sort key builders."""

    def test_sort_by_date_key(self):
        from muonledger.report import _make_sort_key
        key_fn = _make_sort_key("date")
        p1 = _make_post("A", 10, dt=date(2024, 3, 1))
        p2 = _make_post("B", 20, dt=date(2024, 1, 1))
        assert key_fn(p2) < key_fn(p1)

    def test_sort_by_account_key(self):
        from muonledger.report import _make_sort_key
        key_fn = _make_sort_key("account")
        p1 = _make_post("Expenses:Food", 10)
        p2 = _make_post("Assets:Bank", 20)
        assert key_fn(p2) < key_fn(p1)

    def test_sort_by_amount_key(self):
        from muonledger.report import _make_sort_key
        key_fn = _make_sort_key("amount")
        p1 = _make_post("A", 100)
        p2 = _make_post("B", 50)
        assert key_fn(p2) < key_fn(p1)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _chain_contains(handler: PostHandler, handler_type: type) -> bool:
    """Walk the handler chain and return True if any handler is of the given type."""
    current = handler
    while current is not None:
        if isinstance(current, handler_type):
            return True
        current = getattr(current, "handler", None)
    return False
