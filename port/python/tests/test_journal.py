"""Tests for the Journal container."""

from datetime import date

import pytest

from muonledger.account import Account
from muonledger.amount import Amount
from muonledger.commodity import Commodity, CommodityPool
from muonledger.journal import Journal
from muonledger.post import Post
from muonledger.xact import BalanceError, Transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_balanced_xact(journal: Journal, payee: str = "Test") -> Transaction:
    """Create a simple balanced 2-posting transaction."""
    xact = Transaction(payee=payee)
    xact._date = date(2024, 1, 15)

    p1 = Post(account=journal.find_account("Expenses:Food"))
    p1.amount = Amount("42.50")

    p2 = Post(account=journal.find_account("Assets:Checking"))
    # null amount -- will be inferred by finalize

    xact.add_post(p1)
    xact.add_post(p2)
    return xact


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

class TestJournalCreation:
    def test_master_account_exists(self):
        j = Journal()
        assert j.master is not None
        assert isinstance(j.master, Account)
        assert j.master.name == ""

    def test_empty_journal(self):
        j = Journal()
        assert len(j) == 0
        assert j.xacts == []
        assert j.auto_xacts == []
        assert j.period_xacts == []
        assert j.sources == []
        assert j.was_loaded is False

    def test_custom_commodity_pool(self):
        pool = CommodityPool()
        j = Journal(commodity_pool=pool)
        assert j.commodity_pool is pool

    def test_default_commodity_pool(self):
        j = Journal()
        assert isinstance(j.commodity_pool, CommodityPool)


# ---------------------------------------------------------------------------
# add_xact / remove_xact
# ---------------------------------------------------------------------------

class TestAddRemoveXact:
    def test_add_xact_success(self):
        j = Journal()
        xact = _make_balanced_xact(j)
        result = j.add_xact(xact)
        assert result is True
        assert len(j) == 1
        assert j.xacts[0] is xact

    def test_add_xact_auto_finalizes(self):
        """The null-amount posting should be inferred after add_xact."""
        j = Journal()
        xact = _make_balanced_xact(j)
        j.add_xact(xact)
        # The second posting should now have an inferred amount.
        p2 = xact.posts[1]
        assert p2.amount is not None
        assert not p2.amount.is_null()

    def test_add_multiple_xacts(self):
        j = Journal()
        x1 = _make_balanced_xact(j, "Store A")
        x2 = _make_balanced_xact(j, "Store B")
        j.add_xact(x1)
        j.add_xact(x2)
        assert len(j) == 2

    def test_remove_xact(self):
        j = Journal()
        xact = _make_balanced_xact(j)
        j.add_xact(xact)
        j.remove_xact(xact)
        assert len(j) == 0

    def test_remove_missing_xact_raises(self):
        j = Journal()
        xact = _make_balanced_xact(j)
        with pytest.raises(ValueError):
            j.remove_xact(xact)

    def test_add_unbalanced_xact_raises(self):
        j = Journal()
        xact = Transaction(payee="Bad")
        xact._date = date(2024, 1, 1)
        p1 = Post(account=j.find_account("Expenses:Food"))
        p1.amount = Amount(100)
        p2 = Post(account=j.find_account("Assets:Checking"))
        p2.amount = Amount(50)
        xact.add_post(p1)
        xact.add_post(p2)
        with pytest.raises(BalanceError):
            j.add_xact(xact)
        # Transaction should not have been added.
        assert len(j) == 0


# ---------------------------------------------------------------------------
# find_account
# ---------------------------------------------------------------------------

class TestFindAccount:
    def test_find_account_creates(self):
        j = Journal()
        acct = j.find_account("Expenses:Food:Dining")
        assert acct is not None
        assert acct.fullname == "Expenses:Food:Dining"

    def test_find_account_returns_same(self):
        j = Journal()
        a1 = j.find_account("Assets:Cash")
        a2 = j.find_account("Assets:Cash")
        assert a1 is a2

    def test_find_account_no_auto_create(self):
        j = Journal()
        result = j.find_account("NonExistent", auto_create=False)
        assert result is None

    def test_find_account_lives_under_master(self):
        j = Journal()
        j.find_account("Expenses:Food")
        assert "Expenses" in j.master


# ---------------------------------------------------------------------------
# register_commodity
# ---------------------------------------------------------------------------

class TestRegisterCommodity:
    def test_register_creates_commodity(self):
        j = Journal()
        c = j.register_commodity("USD")
        assert isinstance(c, Commodity)
        assert c.symbol == "USD"

    def test_register_returns_same(self):
        j = Journal()
        c1 = j.register_commodity("EUR")
        c2 = j.register_commodity("EUR")
        assert c1 is c2


# ---------------------------------------------------------------------------
# Iteration and length
# ---------------------------------------------------------------------------

class TestIteration:
    def test_len(self):
        j = Journal()
        assert len(j) == 0
        j.add_xact(_make_balanced_xact(j))
        assert len(j) == 1

    def test_iter(self):
        j = Journal()
        x1 = _make_balanced_xact(j, "A")
        x2 = _make_balanced_xact(j, "B")
        j.add_xact(x1)
        j.add_xact(x2)
        payees = [x.payee for x in j]
        assert payees == ["A", "B"]

    def test_list_conversion(self):
        j = Journal()
        j.add_xact(_make_balanced_xact(j))
        assert len(list(j)) == 1


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_resets_everything(self):
        j = Journal()
        j.add_xact(_make_balanced_xact(j))
        j.sources.append("test.dat")
        j.was_loaded = True
        j.register_commodity("USD")

        j.clear()

        assert len(j) == 0
        assert j.master.name == ""
        assert len(j.master) == 0  # no children
        assert j.sources == []
        assert j.was_loaded is False
        assert j.auto_xacts == []
        assert j.period_xacts == []

    def test_clear_allows_reuse(self):
        j = Journal()
        j.add_xact(_make_balanced_xact(j))
        j.clear()
        # Should be able to add new transactions after clear.
        j.add_xact(_make_balanced_xact(j, "After Clear"))
        assert len(j) == 1
        assert j.xacts[0].payee == "After Clear"


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_empty(self):
        j = Journal()
        r = repr(j)
        assert "Journal" in r
        assert "xacts=0" in r
