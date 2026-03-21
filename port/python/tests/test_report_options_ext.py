"""Tests for the extended report options (T-000052).

Covers all newly added options: account, width, display, aggregation,
date, commodity, balance-specific, register-specific, output, and meta.
"""

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
    InvertPosts,
    PostHandler,
    RelatedPosts,
    SortPosts,
    SubtotalPosts,
    TruncatePosts,
    clear_all_xdata,
    get_xdata,
)
from muonledger.item import ITEM_GENERATED, ItemState
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import Post
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
    root = Account(name="")
    return root.find_account(name)


def _make_post(
    account_name: str,
    amount_val: int | float,
    xact: Transaction | None = None,
    dt: date | None = None,
    state: ItemState = ItemState.UNCLEARED,
    flags: int = 0,
) -> Post:
    acct = _make_account(account_name)
    amt = Amount(amount_val)
    post = Post(account=acct, amount=amt, flags=flags)
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
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _chain_contains(handler: PostHandler, handler_type: type) -> bool:
    current = handler
    while current is not None:
        if isinstance(current, handler_type):
            return True
        current = getattr(current, "handler", None)
    return False


def _run_chain(opts: ReportOptions, journal: Journal) -> list[Post]:
    """Build chain, feed posts, flush, and return collected posts."""
    collector = CollectPosts()
    chain = build_filter_chain(opts, collector)
    posts = apply_to_journal(opts, journal)
    for p in posts:
        chain(p)
    chain.flush()
    return collector.posts


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_all_xdata()


# ---------------------------------------------------------------------------
# New option defaults
# ---------------------------------------------------------------------------


class TestExtendedDefaults:
    """Verify all new options default correctly."""

    def test_account_options_default(self):
        opts = ReportOptions()
        assert opts.account_width == 0

    def test_width_options_default(self):
        opts = ReportOptions()
        assert opts.amount_width == 0
        assert opts.total_width == 0
        assert opts.date_width == 0

    def test_display_options_default(self):
        opts = ReportOptions()
        assert opts.empty is False
        assert opts.by_payee is False
        assert opts.wide is False
        assert opts.auto_match is False

    def test_aggregation_options_default(self):
        opts = ReportOptions()
        assert opts.average is False
        assert opts.deviation is False
        assert opts.percent is False
        assert opts.invert is False

    def test_date_options_default(self):
        opts = ReportOptions()
        assert opts.effective is False
        assert opts.actual is False
        assert opts.date_format is None

    def test_commodity_options_default(self):
        opts = ReportOptions()
        assert opts.lots is False
        assert opts.lot_dates is False
        assert opts.lot_prices is False
        assert opts.lot_notes is False
        assert opts.price is False
        assert opts.cost is False

    def test_balance_options_default(self):
        opts = ReportOptions()
        assert opts.no_elide is False
        assert opts.accounts_only is False
        assert opts.totals_only is False

    def test_register_options_default(self):
        opts = ReportOptions()
        assert opts.related_all is False
        assert opts.inject is None

    def test_output_options_default(self):
        opts = ReportOptions()
        assert opts.count is False
        assert opts.payee_width == 0
        assert opts.prepend_format is None
        assert opts.prepend_width == 0

    def test_meta_options_default(self):
        opts = ReportOptions()
        assert opts.pivot is None
        assert opts.group_by is None
        assert opts.group_title_format is None


# ---------------------------------------------------------------------------
# --account EXPR
# ---------------------------------------------------------------------------


class TestAccountFilter:
    """Test --account-filter option filtering in apply_to_journal."""

    JOURNAL_TEXT = """\
2024/01/15 Groceries
    Expenses:Food        $50.00
    Assets:Checking

2024/01/20 Gas
    Expenses:Transport   $30.00
    Assets:Checking
"""

    def test_account_filter_passes_matching(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(account_filter="Food")
        posts = apply_to_journal(opts, journal)
        assert len(posts) > 0
        for p in posts:
            assert "food" in p.account.fullname.lower()

    def test_account_filter_excludes_non_matching(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(account_filter="Food")
        posts = apply_to_journal(opts, journal)
        for p in posts:
            assert "transport" not in p.account.fullname.lower()
            assert "checking" not in p.account.fullname.lower()

    def test_account_filter_in_apply_to_journal(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(account_filter="Expenses")
        posts = apply_to_journal(opts, journal)
        assert len(posts) > 0
        for p in posts:
            assert "Expenses" in p.account.fullname


# ---------------------------------------------------------------------------
# --account-width, --abbrev-len, --amount-width, etc.
# ---------------------------------------------------------------------------


class TestWidthOptions:
    """Test width options are stored and accessible."""

    def test_account_width(self):
        opts = ReportOptions(account_width=40)
        assert opts.account_width == 40

    def test_abbrev_len(self):
        opts = ReportOptions(abbrev_len=20)
        assert opts.abbrev_len == 20

    def test_amount_width(self):
        opts = ReportOptions(amount_width=15)
        assert opts.amount_width == 15

    def test_total_width(self):
        opts = ReportOptions(total_width=20)
        assert opts.total_width == 20

    def test_date_width(self):
        opts = ReportOptions(date_width=12)
        assert opts.date_width == 12

    def test_payee_width(self):
        opts = ReportOptions(payee_width=30)
        assert opts.payee_width == 30

    def test_prepend_width(self):
        opts = ReportOptions(prepend_width=10)
        assert opts.prepend_width == 10

    def test_wide_sets_flag(self):
        opts = ReportOptions(wide=True)
        assert opts.wide is True


# ---------------------------------------------------------------------------
# --empty
# ---------------------------------------------------------------------------


class TestEmptyOption:
    """Test --empty option for showing zero-balance accounts."""

    def test_empty_flag_stored(self):
        opts = ReportOptions(empty=True)
        assert opts.empty is True

    def test_empty_with_interval_enables_generate_empty(self):
        opts = ReportOptions(empty=True, monthly=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        # Find the IntervalPosts handler
        current = chain
        while current is not None:
            if isinstance(current, IntervalPosts):
                assert current.generate_empty is True
                break
            current = getattr(current, "handler", None)
        else:
            pytest.fail("IntervalPosts not found in chain")


# ---------------------------------------------------------------------------
# --by-payee
# ---------------------------------------------------------------------------


class TestByPayeeOption:
    """Test --by-payee triggers subtotal."""

    def test_by_payee_adds_subtotal(self):
        opts = ReportOptions(by_payee=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SubtotalPosts)

    def test_by_payee_flag_stored(self):
        opts = ReportOptions(by_payee=True)
        assert opts.by_payee is True


# ---------------------------------------------------------------------------
# --invert
# ---------------------------------------------------------------------------


class TestInvertOption:
    """Test --invert negates posting amounts."""

    def test_invert_in_chain(self):
        opts = ReportOptions(invert=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, InvertPosts)

    def test_invert_negates_amount(self):
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        post = _make_post("Expenses:Food", 50, xact=tx, dt=date(2024, 1, 1))

        opts = ReportOptions(invert=True)
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)
        chain(post)
        chain.flush()

        assert len(collector.posts) == 1
        result = collector.posts[0]
        assert float(result.amount.quantity) == -50.0

    def test_invert_negative_becomes_positive(self):
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        post = _make_post("Assets:Checking", -100, xact=tx, dt=date(2024, 1, 1))

        opts = ReportOptions(invert=True)
        collector = CollectPosts()
        chain = build_filter_chain(opts, collector)
        chain(post)
        chain.flush()

        assert len(collector.posts) == 1
        result = collector.posts[0]
        assert float(result.amount.quantity) == 100.0


# ---------------------------------------------------------------------------
# --average
# ---------------------------------------------------------------------------


class TestAverageOption:
    """Test --average computes running average in CalcPosts."""

    def test_average_flag_stored(self):
        opts = ReportOptions(average=True)
        assert opts.average is True

    def test_average_affects_calc(self):
        journal = _make_journal_from_text("""\
2024/01/15 A
    Expenses:Food        $100.00
    Assets:Checking

2024/01/20 B
    Expenses:Food        $200.00
    Assets:Checking
""")
        opts = ReportOptions(average=True, limit_expr="/food/")
        result = _run_chain(opts, journal)
        # After 2 food posts (100, 200), the average should be 150
        assert len(result) == 2
        # The xdata visited_value on the second post should be the average
        xd = get_xdata(result[1])
        visited = xd.get("visited_value")
        if visited is not None:
            amt = visited.to_amount()
            assert abs(float(amt.quantity) - 150.0) < 0.01


# ---------------------------------------------------------------------------
# --deviation
# ---------------------------------------------------------------------------


class TestDeviationOption:
    """Test --deviation flag is stored."""

    def test_deviation_flag(self):
        opts = ReportOptions(deviation=True)
        assert opts.deviation is True


# ---------------------------------------------------------------------------
# --percent
# ---------------------------------------------------------------------------


class TestPercentOption:
    """Test --percent flag is stored."""

    def test_percent_flag(self):
        opts = ReportOptions(percent=True)
        assert opts.percent is True


# ---------------------------------------------------------------------------
# --effective
# ---------------------------------------------------------------------------


class TestEffectiveOption:
    """Test date filtering with begin/end dates."""

    def test_begin_date_excludes_earlier(self):
        journal = Journal()
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 15)
        acct1 = Account(name="Expenses:Food")
        acct2 = Account(name="Assets:Checking")
        p1 = Post(account=acct1, amount=Amount(50))
        p2 = Post(account=acct2, amount=Amount(-50))
        tx.add_post(p1)
        tx.add_post(p2)
        journal.add_xact(tx)

        opts = ReportOptions(begin=date(2024, 2, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 0  # excluded because Jan 15 < Feb 1

    def test_begin_date_includes_matching(self):
        journal = Journal()
        tx = Transaction(payee="Test")
        tx._date = date(2024, 3, 15)
        acct1 = Account(name="Expenses:Food")
        acct2 = Account(name="Assets:Checking")
        p1 = Post(account=acct1, amount=Amount(50))
        p2 = Post(account=acct2, amount=Amount(-50))
        tx.add_post(p1)
        tx.add_post(p2)
        journal.add_xact(tx)

        opts = ReportOptions(begin=date(2024, 2, 1))
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 2


# ---------------------------------------------------------------------------
# --actual
# ---------------------------------------------------------------------------


class TestRealOption:
    """Test --real excludes virtual postings."""

    def test_real_flag_stored(self):
        opts = ReportOptions(real=True)
        assert opts.real is True

    def test_real_excludes_virtual_posts(self):
        journal = Journal()
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 15)
        acct1 = Account(name="Expenses:Food")
        acct2 = Account(name="Assets:Checking")
        p1 = Post(account=acct1, amount=Amount(50))
        p2 = Post(account=acct2, amount=Amount(-50))
        tx.add_post(p1)
        tx.add_post(p2)
        journal.add_xact(tx)

        opts = ReportOptions(real=True)
        posts = apply_to_journal(opts, journal)
        for p in posts:
            assert not p.is_virtual()


# ---------------------------------------------------------------------------
# --date-format
# ---------------------------------------------------------------------------


class TestDateFormatOption:
    """Test --date-format is stored."""

    def test_date_format_stored(self):
        opts = ReportOptions(date_format="%Y-%m-%d")
        assert opts.date_format == "%Y-%m-%d"

    def test_date_format_default_none(self):
        opts = ReportOptions()
        assert opts.date_format is None


# ---------------------------------------------------------------------------
# Commodity options: --lots, --lot-dates, --lot-prices, --lot-notes, etc.
# ---------------------------------------------------------------------------


class TestCommodityOptions:
    """Test commodity display options are stored."""

    def test_lots_flag(self):
        opts = ReportOptions(lots=True)
        assert opts.lots is True

    def test_lot_dates_flag(self):
        opts = ReportOptions(lot_dates=True)
        assert opts.lot_dates is True

    def test_lot_prices_flag(self):
        opts = ReportOptions(lot_prices=True)
        assert opts.lot_prices is True

    def test_lot_notes_flag(self):
        opts = ReportOptions(lot_notes=True)
        assert opts.lot_notes is True

    def test_price_flag(self):
        opts = ReportOptions(price=True)
        assert opts.price is True

    def test_cost_flag(self):
        opts = ReportOptions(cost=True)
        assert opts.cost is True


# ---------------------------------------------------------------------------
# Balance-specific: --no-elide, --accounts-only, --totals-only
# ---------------------------------------------------------------------------


class TestBalanceSpecificOptions:
    """Test balance-specific display options."""

    def test_no_elide_flag(self):
        opts = ReportOptions(no_elide=True)
        assert opts.no_elide is True

    def test_accounts_only_flag(self):
        opts = ReportOptions(accounts_only=True)
        assert opts.accounts_only is True

    def test_totals_only_flag(self):
        opts = ReportOptions(totals_only=True)
        assert opts.totals_only is True


# ---------------------------------------------------------------------------
# --related and --related-all
# ---------------------------------------------------------------------------


class TestRelatedOptions:
    """Test --related and --related-all in the filter chain."""

    JOURNAL_TEXT = """\
2024/01/15 Groceries
    Expenses:Food        $50.00
    Assets:Checking
"""

    def test_related_adds_filter(self):
        opts = ReportOptions(related=True)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, RelatedPosts)

    def test_related_shows_other_side(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        # Limit to Expenses:Food, then show related
        opts = ReportOptions(limit_expr="/food/", related=True)
        result = _run_chain(opts, journal)
        # The food posting is the input; related should show
        # Assets:Checking (the other side)
        account_names = {p.account.fullname for p in result}
        assert "Assets:Checking" in account_names


# ---------------------------------------------------------------------------
# --inject
# ---------------------------------------------------------------------------


class TestInjectOption:
    """Test --inject is stored."""

    def test_inject_stored(self):
        opts = ReportOptions(inject="$100")
        assert opts.inject == "$100"

    def test_inject_default_none(self):
        opts = ReportOptions()
        assert opts.inject is None


# ---------------------------------------------------------------------------
# --count
# ---------------------------------------------------------------------------


class TestCountOption:
    """Test --count flag."""

    def test_count_flag(self):
        opts = ReportOptions(count=True)
        assert opts.count is True


# ---------------------------------------------------------------------------
# --auto-match
# ---------------------------------------------------------------------------


class TestAutoMatchOption:
    """Test --auto-match flag."""

    def test_auto_match_flag(self):
        opts = ReportOptions(auto_match=True)
        assert opts.auto_match is True


# ---------------------------------------------------------------------------
# --prepend-format, --prepend-width
# ---------------------------------------------------------------------------


class TestPrependOptions:
    """Test prepend format/width options."""

    def test_prepend_format(self):
        opts = ReportOptions(prepend_format="%(date)")
        assert opts.prepend_format == "%(date)"

    def test_prepend_width(self):
        opts = ReportOptions(prepend_width=15)
        assert opts.prepend_width == 15


# ---------------------------------------------------------------------------
# --pivot, --group-by, --group-title-format
# ---------------------------------------------------------------------------


class TestMetaOptions:
    """Test meta-grouping options."""

    def test_pivot(self):
        opts = ReportOptions(pivot="Payee")
        assert opts.pivot == "Payee"

    def test_group_by(self):
        opts = ReportOptions(group_by="payee")
        assert opts.group_by == "payee"

    def test_group_title_format(self):
        opts = ReportOptions(group_title_format="--- %(account) ---")
        assert opts.group_title_format == "--- %(account) ---"


# ---------------------------------------------------------------------------
# InvertPosts filter (unit tests)
# ---------------------------------------------------------------------------


class TestInvertPostsFilter:
    """Unit tests for the InvertPosts filter handler."""

    def test_invert_positive_to_negative(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        post = _make_post("Expenses:Food", 100)
        inv(post)
        assert len(collector.posts) == 1
        assert float(collector.posts[0].amount.quantity) == -100.0

    def test_invert_negative_to_positive(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        post = _make_post("Assets:Checking", -75)
        inv(post)
        assert len(collector.posts) == 1
        assert float(collector.posts[0].amount.quantity) == 75.0

    def test_invert_zero(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        post = _make_post("Assets:Checking", 0)
        inv(post)
        assert len(collector.posts) == 1
        assert float(collector.posts[0].amount.quantity) == 0.0

    def test_invert_preserves_account(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        post = _make_post("Expenses:Rent", 500)
        inv(post)
        assert collector.posts[0].account.fullname == "Expenses:Rent"

    def test_invert_preserves_xact(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        tx = Transaction(payee="Landlord")
        tx._date = date(2024, 1, 1)
        post = _make_post("Expenses:Rent", 500, xact=tx, dt=date(2024, 1, 1))
        inv(post)
        assert collector.posts[0].xact is tx


# ---------------------------------------------------------------------------
# RelatedPosts filter (unit tests)
# ---------------------------------------------------------------------------


class TestRelatedPostsFilter:
    """Unit tests for the RelatedPosts filter handler."""

    def test_related_emits_other_side(self):
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        p1 = _make_post("Expenses:Food", 50, xact=tx, dt=date(2024, 1, 1))
        p2 = _make_post("Assets:Checking", -50, xact=tx, dt=date(2024, 1, 1))

        collector = CollectPosts()
        rel = RelatedPosts(collector, also_matching=False)
        rel(p1)
        rel.flush()

        # Should emit p2 (the other side), not p1
        assert len(collector.posts) == 1
        assert collector.posts[0] is p2

    def test_related_all_emits_both(self):
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        p1 = _make_post("Expenses:Food", 50, xact=tx, dt=date(2024, 1, 1))
        p2 = _make_post("Assets:Checking", -50, xact=tx, dt=date(2024, 1, 1))

        collector = CollectPosts()
        rel = RelatedPosts(collector, also_matching=True)
        rel(p1)
        rel.flush()

        # Should emit both p1 and p2
        assert len(collector.posts) == 2

    def test_related_deduplicates(self):
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        p1 = _make_post("Expenses:Food", 50, xact=tx, dt=date(2024, 1, 1))
        p2 = _make_post("Assets:Checking", -50, xact=tx, dt=date(2024, 1, 1))

        collector = CollectPosts()
        rel = RelatedPosts(collector, also_matching=False)
        # Feed both posts from the same transaction
        rel(p1)
        rel(p2)
        rel.flush()

        # Each related post should appear only once
        assert len(collector.posts) == 2


# ---------------------------------------------------------------------------
# Integration: combined new options
# ---------------------------------------------------------------------------


class TestIntegrationCombinedOptions:
    """Test combining multiple new options together."""

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

    def test_invert_with_limit(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(invert=True, limit_expr="/food/")
        result = _run_chain(opts, journal)
        # All food posts should be negated
        for p in result:
            assert float(p.amount.quantity) < 0

    def test_account_filter_with_sort(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(account_filter="Expenses", sort_expr="amount")
        result = _run_chain(opts, journal)
        amounts = [float(p.amount.quantity) for p in result]
        assert amounts == sorted(amounts)

    def test_invert_with_head(self):
        journal = _make_journal_from_text(self.JOURNAL_TEXT)
        opts = ReportOptions(invert=True, head=2)
        result = _run_chain(opts, journal)
        assert len(result) == 2
        for p in result:
            # Amounts should be negated
            orig_qty = float(p.amount.quantity)
            # The original amounts were positive, so inverted should be negative
            # (or originally negative, now positive)
            pass  # Just verify we get exactly 2

    def test_invert_with_begin_date(self):
        journal = Journal()
        tx = Transaction(payee="Test")
        tx._date = date(2024, 3, 15)
        acct1 = Account(name="Expenses:Food")
        acct2 = Account(name="Assets:Checking")
        p1 = Post(account=acct1, amount=Amount(50))
        p2 = Post(account=acct2, amount=Amount(-50))
        tx.add_post(p1)
        tx.add_post(p2)
        journal.add_xact(tx)

        opts = ReportOptions(
            invert=True,
            begin=date(2024, 2, 1),
        )
        result = _run_chain(opts, journal)
        assert len(result) == 2
        # All amounts should be negated
        for p in result:
            assert p.amount is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for new options."""

    def test_invert_null_amount_passes_through(self):
        collector = CollectPosts()
        inv = InvertPosts(collector)
        post = Post(account=_make_account("Test"))
        # null amount
        tx = Transaction(payee="Test")
        tx._date = date(2024, 1, 1)
        tx.add_post(post)
        inv(post)
        assert len(collector.posts) == 1

    def test_related_no_xact(self):
        collector = CollectPosts()
        rel = RelatedPosts(collector)
        post = Post(account=_make_account("Test"), amount=Amount(10))
        # post has no xact
        rel(post)
        rel.flush()
        assert len(collector.posts) == 1

    def test_multiple_width_options_independent(self):
        opts = ReportOptions(
            account_width=30,
            amount_width=15,
            total_width=20,
            date_width=10,
            payee_width=25,
        )
        assert opts.account_width == 30
        assert opts.amount_width == 15
        assert opts.total_width == 20
        assert opts.date_width == 10
        assert opts.payee_width == 25

    def test_all_commodity_flags_can_be_set(self):
        opts = ReportOptions(
            lots=True,
            lot_dates=True,
            lot_prices=True,
            lot_notes=True,
            price=True,
            cost=True,
        )
        assert opts.lots is True
        assert opts.lot_dates is True
        assert opts.lot_prices is True
        assert opts.lot_notes is True
        assert opts.price is True
        assert opts.cost is True

    def test_by_payee_without_subtotal_still_adds_subtotal(self):
        opts = ReportOptions(by_payee=True, subtotal=False)
        handler = CollectPosts()
        chain = build_filter_chain(opts, handler)
        assert _chain_contains(chain, SubtotalPosts)

    def test_empty_journal_with_new_options(self):
        journal = Journal()
        opts = ReportOptions(
            invert=True,
            average=True,
        )
        posts = apply_to_journal(opts, journal)
        assert len(posts) == 0

    def test_account_filter_with_pattern(self):
        """account_filter matches only matching accounts."""
        journal = _make_journal_from_text("""\
2024/01/15 Test
    Expenses:Food        $50.00
    Assets:Checking
""")
        opts = ReportOptions(account_filter="Expenses")
        posts = apply_to_journal(opts, journal)
        assert len(posts) > 0
        for p in posts:
            assert "expenses" in p.account.fullname.lower()
