"""Tests for Item, Post, and Transaction classes."""

from datetime import date

import pytest

from muonledger.amount import Amount
from muonledger.item import (
    ITEM_GENERATED,
    ITEM_INFERRED,
    ITEM_NORMAL,
    Item,
    ItemState,
    Position,
)
from muonledger.post import POST_CALCULATED, POST_MUST_BALANCE, POST_VIRTUAL, Post
from muonledger.xact import BalanceError, Transaction


# ---------------------------------------------------------------------------
# Item metadata and tags
# ---------------------------------------------------------------------------


class TestItemMetadata:
    def test_initial_state(self):
        item = Item()
        assert item.flags == ITEM_NORMAL
        assert item.state == ItemState.UNCLEARED
        assert item.date is None
        assert item.date_aux is None
        assert item.note is None
        assert item.position is None

    def test_set_date(self):
        item = Item()
        d = date(2024, 1, 15)
        item.date = d
        assert item.date == d
        assert item.has_date()

    def test_set_state(self):
        item = Item()
        item.state = ItemState.CLEARED
        assert item.state == ItemState.CLEARED

    def test_flags(self):
        item = Item(flags=ITEM_GENERATED)
        assert item.has_flags(ITEM_GENERATED)
        assert not item.has_flags(ITEM_INFERRED)
        item.add_flags(ITEM_INFERRED)
        assert item.has_flags(ITEM_GENERATED)
        assert item.has_flags(ITEM_INFERRED)
        item.drop_flags(ITEM_GENERATED)
        assert not item.has_flags(ITEM_GENERATED)
        assert item.has_flags(ITEM_INFERRED)

    def test_tag_operations(self):
        item = Item()
        assert not item.has_tag("Payee")
        assert item.get_tag("Payee") is None

        item.set_tag("Payee", "Grocery Store")
        assert item.has_tag("Payee")
        assert item.get_tag("Payee") == "Grocery Store"
        assert item.tag("Payee") == "Grocery Store"

    def test_bare_tag(self):
        item = Item()
        item.set_tag("Receipt")
        assert item.has_tag("Receipt")
        assert item.get_tag("Receipt") is True

    def test_copy_details(self):
        src = Item(flags=ITEM_GENERATED, note="test note")
        src.date = date(2024, 6, 1)
        src.state = ItemState.PENDING
        src.set_tag("Color", "blue")
        src.position = Position(pathname="test.dat", beg_line=10, end_line=12)

        dst = Item()
        dst.copy_details(src)
        assert dst.flags == ITEM_GENERATED
        assert dst.state == ItemState.PENDING
        assert dst.date == date(2024, 6, 1)
        assert dst.note == "test note"
        assert dst.get_tag("Color") == "blue"
        assert dst.position is src.position

        # Metadata dict is a copy, not a reference
        dst.set_tag("Color", "red")
        assert src.get_tag("Color") == "blue"

    def test_position(self):
        pos = Position(pathname="ledger.dat", beg_line=5, end_line=8)
        assert pos.pathname == "ledger.dat"
        assert pos.beg_line == 5
        assert pos.end_line == 8

    def test_note_constructor(self):
        item = Item(note="a comment")
        assert item.note == "a comment"


# ---------------------------------------------------------------------------
# Post creation
# ---------------------------------------------------------------------------


class TestPost:
    def test_basic_creation(self):
        post = Post(account="Expenses:Food", amount=Amount("$50.00"))
        assert post.account == "Expenses:Food"
        assert post.amount == Amount("$50.00")
        assert post.cost is None
        assert post.xact is None
        assert post.must_balance()

    def test_virtual_posting(self):
        post = Post(account="(Budget:Food)", flags=POST_VIRTUAL)
        assert post.is_virtual()
        assert not post.must_balance()

    def test_balanced_virtual_posting(self):
        post = Post(
            account="[Budget:Food]",
            flags=POST_VIRTUAL | POST_MUST_BALANCE,
        )
        assert post.is_virtual()
        assert post.must_balance()

    def test_null_amount_posting(self):
        post = Post(account="Assets:Checking")
        assert post.amount is None

    def test_tag_inheritance(self):
        xact = Transaction(payee="Store")
        xact.set_tag("Source", "import")
        post = Post(account="Expenses:Food", amount=Amount("$10"))
        xact.add_post(post)

        # Post inherits tag from transaction
        assert post.has_tag("Source")
        assert post.get_tag("Source") == "import"

        # Post's own tag overrides
        post.set_tag("Source", "manual")
        assert post.get_tag("Source") == "manual"

    def test_tag_no_inherit(self):
        xact = Transaction(payee="Store")
        xact.set_tag("Source", "import")
        post = Post(account="Expenses:Food", amount=Amount("$10"))
        xact.add_post(post)

        assert not post.has_tag("Source", inherit=False)
        assert post.get_tag("Source", inherit=False) is None

    def test_cost(self):
        post = Post(account="Assets:Broker", amount=Amount("10 AAPL"))
        post.cost = Amount("$1500.00")
        assert post.cost == Amount("$1500.00")


# ---------------------------------------------------------------------------
# Transaction creation
# ---------------------------------------------------------------------------


class TestTransaction:
    def test_basic_creation(self):
        xact = Transaction(payee="Grocery Store")
        assert xact.payee == "Grocery Store"
        assert len(xact) == 0
        assert xact.code is None

    def test_add_posts(self):
        xact = Transaction(payee="Store")
        p1 = Post(account="Expenses:Food", amount=Amount("$42.50"))
        p2 = Post(account="Assets:Checking", amount=Amount("$-42.50"))
        xact.add_post(p1)
        xact.add_post(p2)

        assert len(xact) == 2
        assert p1.xact is xact
        assert p2.xact is xact

    def test_remove_post(self):
        xact = Transaction(payee="Store")
        p1 = Post(account="Expenses:Food", amount=Amount("$42.50"))
        xact.add_post(p1)
        assert len(xact) == 1

        result = xact.remove_post(p1)
        assert result is True
        assert len(xact) == 0
        assert p1.xact is None

    def test_remove_nonexistent_post(self):
        xact = Transaction(payee="Store")
        p1 = Post(account="Expenses:Food", amount=Amount("$42.50"))
        assert xact.remove_post(p1) is False

    def test_iterate_posts(self):
        xact = Transaction(payee="Store")
        p1 = Post(account="Expenses:Food", amount=Amount("$10"))
        p2 = Post(account="Assets:Checking", amount=Amount("$-10"))
        xact.add_post(p1)
        xact.add_post(p2)

        posts = list(xact)
        assert posts == [p1, p2]

    def test_code(self):
        xact = Transaction(payee="Store")
        xact.code = "1042"
        assert xact.code == "1042"

    def test_date_and_state(self):
        xact = Transaction(payee="Store")
        xact.date = date(2024, 1, 15)
        xact.state = ItemState.CLEARED
        assert xact.date == date(2024, 1, 15)
        assert xact.state == ItemState.CLEARED


# ---------------------------------------------------------------------------
# Transaction.finalize()
# ---------------------------------------------------------------------------


class TestFinalize:
    def test_balanced_transaction(self):
        """Two postings that already balance should finalize cleanly."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-42.50")))

        result = xact.finalize()
        assert result is True

    def test_auto_balance_null_amount(self):
        """One null-amount posting should be auto-filled to balance."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        null_post = Post(account="Assets:Checking")
        xact.add_post(null_post)

        result = xact.finalize()
        assert result is True
        assert null_post.amount is not None
        assert not null_post.amount.is_null()
        # The null post should get -$42.50
        assert null_post.amount == Amount("$-42.50")
        assert null_post.has_flags(POST_CALCULATED)

    def test_auto_balance_three_posts(self):
        """Auto-balance with three postings, one null."""
        xact = Transaction(payee="Dinner")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$30.00")))
        xact.add_post(Post(account="Expenses:Drinks", amount=Amount("$12.50")))
        null_post = Post(account="Assets:Checking")
        xact.add_post(null_post)

        result = xact.finalize()
        assert result is True
        assert null_post.amount == Amount("$-42.50")

    def test_unbalanced_transaction_raises(self):
        """A transaction with no null post that doesn't balance should raise."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-40.00")))

        with pytest.raises(BalanceError, match="does not balance"):
            xact.finalize()

    def test_multiple_null_amounts_raises(self):
        """Two null-amount postings should raise an error."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking"))
        xact.add_post(Post(account="Liabilities:CreditCard"))

        with pytest.raises(BalanceError, match="Only one posting with null amount"):
            xact.finalize()

    def test_zero_balance_transaction(self):
        """A single posting of zero should finalize."""
        xact = Transaction(payee="Zero")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$0.00")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$0.00")))

        result = xact.finalize()
        assert result is True

    def test_virtual_post_not_balanced(self):
        """Virtual postings (parenthesized) do not participate in balancing."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-42.50")))
        # Virtual posting with arbitrary amount -- should not affect balance
        virtual = Post(
            account="(Budget:Food)",
            amount=Amount("$100"),
            flags=POST_VIRTUAL,
        )
        xact.add_post(virtual)

        result = xact.finalize()
        assert result is True

    def test_magnitude(self):
        """magnitude() sums positive posting amounts."""
        xact = Transaction(payee="Store")
        xact.add_post(Post(account="Expenses:Food", amount=Amount("$42.50")))
        xact.add_post(Post(account="Assets:Checking", amount=Amount("$-42.50")))

        mag = xact.magnitude()
        assert not mag.is_null()
        assert mag.to_amount() == Amount("$42.50")

    def test_finalize_with_integers(self):
        """Finalize with integer amounts (no commodity)."""
        xact = Transaction(payee="Transfer")
        xact.add_post(Post(account="A", amount=Amount(100)))
        null_post = Post(account="B")
        xact.add_post(null_post)

        result = xact.finalize()
        assert result is True
        assert null_post.amount == Amount(-100)
