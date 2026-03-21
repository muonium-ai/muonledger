"""Tests for periodic transactions (~ PERIOD) and budget support."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.filters import CollectPosts
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.periodic_xact import BudgetPosts, PeriodicTransaction
from muonledger.post import POST_GENERATED, Post
from muonledger.times import DateInterval
from muonledger.xact import Transaction


# ---------------------------------------------------------------------------
# PeriodicTransaction unit tests
# ---------------------------------------------------------------------------


class TestPeriodicTransactionInit:
    """Test PeriodicTransaction construction."""

    def test_basic_construction(self):
        pxact = PeriodicTransaction("Monthly")
        assert pxact.period_expr == "Monthly"
        assert pxact.posts == []
        assert pxact.interval is None

    def test_construction_with_posts(self):
        p = Post(account=Account(name="Expenses:Food"), amount=Amount(500, "$"))
        pxact = PeriodicTransaction("Weekly", posts=[p])
        assert len(pxact.posts) == 1
        assert pxact.posts[0].account.name == "Expenses:Food"

    def test_repr(self):
        pxact = PeriodicTransaction("Monthly")
        r = repr(pxact)
        assert "Monthly" in r
        assert "posts=0" in r


class TestPeriodicTransactionParsePeriod:
    """Test period expression parsing."""

    def test_monthly(self):
        pxact = PeriodicTransaction("Monthly")
        interval = pxact.parse_period()
        assert interval.quantum == "months"
        assert interval.length == 1

    def test_weekly(self):
        pxact = PeriodicTransaction("Weekly")
        interval = pxact.parse_period()
        assert interval.quantum == "weeks"
        assert interval.length == 1

    def test_yearly(self):
        pxact = PeriodicTransaction("Yearly")
        interval = pxact.parse_period()
        assert interval.quantum == "years"
        assert interval.length == 1

    def test_daily(self):
        pxact = PeriodicTransaction("Daily")
        interval = pxact.parse_period()
        assert interval.quantum == "days"
        assert interval.length == 1

    def test_every_2_weeks(self):
        pxact = PeriodicTransaction("Every 2 weeks")
        interval = pxact.parse_period()
        assert interval.quantum == "weeks"
        assert interval.length == 2

    def test_every_3_months(self):
        pxact = PeriodicTransaction("Every 3 months")
        interval = pxact.parse_period()
        assert interval.quantum == "months"
        assert interval.length == 3

    def test_quarterly(self):
        pxact = PeriodicTransaction("Quarterly")
        interval = pxact.parse_period()
        assert interval.quantum == "quarters"
        assert interval.length == 1

    def test_biweekly(self):
        pxact = PeriodicTransaction("Biweekly")
        interval = pxact.parse_period()
        assert interval.quantum == "weeks"
        assert interval.length == 2

    def test_interval_cached(self):
        pxact = PeriodicTransaction("Monthly")
        i1 = pxact.parse_period()
        i2 = pxact.parse_period()
        assert i1 is i2

    def test_invalid_period_raises(self):
        pxact = PeriodicTransaction("SomeRandomThing")
        with pytest.raises(ValueError):
            pxact.parse_period()


class TestPeriodicTransactionGenerate:
    """Test generating transactions from periodic templates."""

    def _make_pxact(self, period="Monthly", accounts_amounts=None):
        """Helper to create a PeriodicTransaction with template postings."""
        if accounts_amounts is None:
            accounts_amounts = [
                ("Expenses:Food", Amount(500, "$")),
                ("Assets:Checking", Amount(-500, "$")),
            ]
        posts = []
        for acct_name, amt in accounts_amounts:
            acct = Account(name=acct_name)
            posts.append(Post(account=acct, amount=amt))
        return PeriodicTransaction(period, posts=posts)

    def test_generate_monthly(self):
        pxact = self._make_pxact("Monthly")
        begin = date(2024, 1, 1)
        end = date(2024, 4, 1)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 3  # Jan, Feb, Mar
        assert xacts[0]._date == date(2024, 1, 1)
        assert xacts[1]._date == date(2024, 2, 1)
        assert xacts[2]._date == date(2024, 3, 1)

    def test_generate_weekly(self):
        pxact = self._make_pxact("Weekly")
        begin = date(2024, 1, 1)
        end = date(2024, 1, 22)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 3  # 3 full weeks

    def test_generate_daily(self):
        pxact = self._make_pxact("Daily")
        begin = date(2024, 1, 1)
        end = date(2024, 1, 4)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 3

    def test_generate_yearly(self):
        pxact = self._make_pxact("Yearly")
        begin = date(2024, 1, 1)
        end = date(2027, 1, 1)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 3

    def test_generated_posts_have_flag(self):
        pxact = self._make_pxact("Monthly")
        begin = date(2024, 1, 1)
        end = date(2024, 2, 1)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 1
        for post in xacts[0].posts:
            assert post.has_flags(POST_GENERATED)

    def test_generated_posts_linked_to_xact(self):
        pxact = self._make_pxact("Monthly")
        begin = date(2024, 1, 1)
        end = date(2024, 2, 1)
        xacts = pxact.generate_xacts(begin, end)
        for xact in xacts:
            for post in xact.posts:
                assert post.xact is xact

    def test_generated_xact_payee(self):
        pxact = self._make_pxact("Monthly")
        xacts = pxact.generate_xacts(date(2024, 1, 1), date(2024, 2, 1))
        assert xacts[0].payee == "Budget: Monthly"

    def test_multiple_postings_per_xact(self):
        pxact = self._make_pxact(
            "Monthly",
            [
                ("Expenses:Food", Amount(500, "$")),
                ("Expenses:Rent", Amount(1500, "$")),
                ("Assets:Checking", Amount(-2000, "$")),
            ],
        )
        xacts = pxact.generate_xacts(date(2024, 1, 1), date(2024, 2, 1))
        assert len(xacts[0].posts) == 3

    def test_empty_range_generates_nothing(self):
        pxact = self._make_pxact("Monthly")
        xacts = pxact.generate_xacts(date(2024, 3, 1), date(2024, 1, 1))
        assert xacts == []

    def test_same_begin_end_generates_nothing(self):
        pxact = self._make_pxact("Monthly")
        xacts = pxact.generate_xacts(date(2024, 1, 1), date(2024, 1, 1))
        assert xacts == []

    def test_every_2_weeks_generation(self):
        pxact = self._make_pxact("Every 2 weeks")
        begin = date(2024, 1, 1)
        end = date(2024, 2, 12)
        xacts = pxact.generate_xacts(begin, end)
        assert len(xacts) == 3  # Jan 1, Jan 15, Jan 29
        assert xacts[0]._date == date(2024, 1, 1)
        assert xacts[1]._date == date(2024, 1, 15)
        assert xacts[2]._date == date(2024, 1, 29)

    def test_template_amounts_are_copied(self):
        """Generated posts should have independent amounts from templates."""
        pxact = self._make_pxact("Monthly")
        xacts = pxact.generate_xacts(date(2024, 1, 1), date(2024, 3, 1))
        # Modify a generated amount
        xacts[0].posts[0].amount = Amount(999, "$")
        # Template should be unaffected
        assert float(pxact.posts[0].amount.quantity) == 500


# ---------------------------------------------------------------------------
# Parser integration tests
# ---------------------------------------------------------------------------


class TestPeriodicXactParsing:
    """Test parsing periodic transactions from journal text."""

    def test_parse_monthly(self):
        text = """\
~ Monthly
    Expenses:Food                        $500
    Assets:Checking                     $-500
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        pxact = journal.period_xacts[0]
        assert pxact.period_expr == "Monthly"
        assert len(pxact.posts) == 2

    def test_parse_weekly(self):
        text = """\
~ Weekly
    Expenses:Food                        $100
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert journal.period_xacts[0].period_expr == "Weekly"

    def test_parse_yearly(self):
        text = """\
~ Yearly
    Expenses:Insurance                   $1200
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert journal.period_xacts[0].period_expr == "Yearly"

    def test_parse_daily(self):
        text = """\
~ Daily
    Expenses:Coffee                      $5
    Assets:Wallet
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert journal.period_xacts[0].period_expr == "Daily"

    def test_parse_every_2_weeks(self):
        text = """\
~ Every 2 weeks
    Expenses:Food                        $200
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert journal.period_xacts[0].period_expr == "Every 2 weeks"

    def test_parse_multiple_periodic_xacts(self):
        text = """\
~ Monthly
    Expenses:Food                        $500
    Assets:Checking

~ Weekly
    Expenses:Transport                   $50
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 2
        assert journal.period_xacts[0].period_expr == "Monthly"
        assert journal.period_xacts[1].period_expr == "Weekly"

    def test_parse_periodic_with_regular_xact(self):
        text = """\
~ Monthly
    Expenses:Food                        $500
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert len(journal.xacts) == 1

    def test_periodic_xact_does_not_affect_regular_balance(self):
        """Periodic xacts should not appear in regular transaction list."""
        text = """\
~ Monthly
    Expenses:Food                        $500
    Assets:Checking                     $-500

2024/01/15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        # Only 1 regular transaction
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Grocery Store"
        # Periodic xact stored separately
        assert len(journal.period_xacts) == 1

    def test_parse_periodic_with_comment(self):
        text = """\
~ Monthly
    ; Budget for food
    Expenses:Food                        $500
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        # The comment line is skipped, so we should have 2 postings
        assert len(journal.period_xacts[0].posts) == 2

    def test_parse_empty_period_skipped(self):
        text = """\
~
    Expenses:Food                        $500
    Assets:Checking

2024/01/15 Test
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 0
        assert len(journal.xacts) == 1

    def test_parse_posting_amounts(self):
        text = """\
~ Monthly
    Expenses:Food                        $500
    Expenses:Rent                      $1,500
    Assets:Checking
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        pxact = journal.period_xacts[0]
        assert len(pxact.posts) == 3
        assert float(pxact.posts[0].amount.quantity) == 500
        commodity = pxact.posts[0].amount.commodity
        sym = commodity.symbol if hasattr(commodity, "symbol") else str(commodity)
        assert sym == "$"
        assert float(pxact.posts[1].amount.quantity) == 1500

    def test_periodic_with_auto_xact(self):
        """Periodic and automated transactions coexist."""
        text = """\
~ Monthly
    Expenses:Food                        $500
    Assets:Checking

= /Food/
    (Budget:Food)                       $-100

2024/01/15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        assert len(journal.period_xacts) == 1
        assert len(journal.auto_xacts) == 1
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# BudgetPosts filter tests
# ---------------------------------------------------------------------------


class TestBudgetPosts:
    """Test the BudgetPosts filter."""

    def _make_pxact(self, period="Monthly", accounts_amounts=None):
        if accounts_amounts is None:
            accounts_amounts = [
                ("Expenses:Food", Amount(500, "$")),
                ("Assets:Checking", Amount(-500, "$")),
            ]
        posts = []
        for acct_name, amt in accounts_amounts:
            acct = Account(name=acct_name)
            posts.append(Post(account=acct, amount=amt))
        return PeriodicTransaction(period, posts=posts)

    def test_budget_totals_generated(self):
        pxact = self._make_pxact("Monthly")
        collector = CollectPosts()
        bp = BudgetPosts(
            collector,
            [pxact],
            date(2024, 1, 1),
            date(2024, 4, 1),
        )
        # 3 months of budget
        food_total = bp.get_budget_total("Expenses:Food")
        assert food_total is not None
        assert float(food_total.quantity) == 1500  # 500 * 3

    def test_budget_accounts(self):
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(
            None,
            [pxact],
            date(2024, 1, 1),
            date(2024, 2, 1),
        )
        assert "Expenses:Food" in bp.budget_accounts
        assert "Assets:Checking" in bp.budget_accounts

    def test_actual_tracking(self):
        pxact = self._make_pxact("Monthly")
        collector = CollectPosts()
        bp = BudgetPosts(
            collector,
            [pxact],
            date(2024, 1, 1),
            date(2024, 2, 1),
        )
        # Simulate posting a real transaction
        acct = Account(name="Expenses:Food")
        post = Post(account=acct, amount=Amount(50, "$"))
        bp(post)
        actual = bp.get_actual_total("Expenses:Food")
        assert actual is not None
        assert float(actual.quantity) == 50

    def test_actual_forwarded_to_handler(self):
        collector = CollectPosts()
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(
            collector,
            [pxact],
            date(2024, 1, 1),
            date(2024, 2, 1),
        )
        acct = Account(name="Expenses:Food")
        post = Post(account=acct, amount=Amount(50, "$"))
        bp(post)
        assert len(collector.posts) == 1

    def test_budget_xacts_property(self):
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(
            None,
            [pxact],
            date(2024, 1, 1),
            date(2024, 4, 1),
        )
        assert len(bp.budget_xacts) == 3

    def test_no_budget_total_for_unknown_account(self):
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(
            None,
            [pxact],
            date(2024, 1, 1),
            date(2024, 2, 1),
        )
        assert bp.get_budget_total("Expenses:Entertainment") is None

    def test_empty_range_no_budget(self):
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(
            None,
            [pxact],
            date(2024, 3, 1),
            date(2024, 1, 1),
        )
        assert len(bp.budget_xacts) == 0
        assert bp.get_budget_total("Expenses:Food") is None

    def test_multiple_periodic_xacts(self):
        pxact1 = self._make_pxact(
            "Monthly",
            [("Expenses:Food", Amount(500, "$")), ("Assets:Checking", Amount(-500, "$"))],
        )
        pxact2 = self._make_pxact(
            "Monthly",
            [
                ("Expenses:Rent", Amount(1500, "$")),
                ("Assets:Checking", Amount(-1500, "$")),
            ],
        )
        bp = BudgetPosts(
            None,
            [pxact1, pxact2],
            date(2024, 1, 1),
            date(2024, 2, 1),
        )
        food = bp.get_budget_total("Expenses:Food")
        rent = bp.get_budget_total("Expenses:Rent")
        assert food is not None
        assert float(food.quantity) == 500
        assert rent is not None
        assert float(rent.quantity) == 1500

    def test_flush_delegates(self):
        collector = CollectPosts()
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(collector, [pxact], date(2024, 1, 1), date(2024, 2, 1))
        # Should not raise
        bp.flush()

    def test_clear_resets_state(self):
        collector = CollectPosts()
        pxact = self._make_pxact("Monthly")
        bp = BudgetPosts(collector, [pxact], date(2024, 1, 1), date(2024, 2, 1))
        acct = Account(name="Expenses:Food")
        post = Post(account=acct, amount=Amount(50, "$"))
        bp(post)
        bp.clear()
        assert bp.get_actual_total("Expenses:Food") is None
        assert bp.get_budget_total("Expenses:Food") is None
