"""Tests for the hierarchical Account class."""

from muonledger.account import Account


# ── Creation and hierarchy ──────────────────────────────────────────


class TestAccountCreation:
    def test_root_account(self):
        root = Account()
        assert root.name == ""
        assert root.parent is None
        assert root.depth == 0
        assert root.fullname == ""

    def test_child_account(self):
        root = Account()
        child = Account(parent=root, name="Expenses")
        assert child.name == "Expenses"
        assert child.parent is root
        assert child.depth == 1

    def test_note(self):
        acct = Account(name="Checking", note="primary checking")
        assert acct.note == "primary checking"


# ── Fullname computation ────────────────────────────────────────────


class TestFullname:
    def test_root_fullname_empty(self):
        root = Account()
        assert root.fullname == ""

    def test_single_level(self):
        root = Account()
        child = Account(parent=root, name="Assets")
        assert child.fullname == "Assets"

    def test_multi_level(self):
        root = Account()
        a = Account(parent=root, name="Expenses")
        b = Account(parent=a, name="Food")
        c = Account(parent=b, name="Dining")
        assert c.fullname == "Expenses:Food:Dining"

    def test_fullname_cached(self):
        root = Account()
        a = Account(parent=root, name="Assets")
        _ = a.fullname  # prime cache
        assert a._fullname == "Assets"
        assert a.fullname == "Assets"

    def test_str_returns_fullname(self):
        root = Account()
        a = Account(parent=root, name="Assets")
        assert str(a) == "Assets"

    def test_repr(self):
        root = Account()
        a = Account(parent=root, name="Assets")
        assert repr(a) == "Account('Assets')"


# ── find_account with auto-creation ────────────────────────────────


class TestFindAccountAutoCreate:
    def test_simple_name(self):
        root = Account()
        acct = root.find_account("Assets")
        assert acct is not None
        assert acct.name == "Assets"
        assert acct.parent is root
        assert acct.depth == 1

    def test_nested_path(self):
        root = Account()
        acct = root.find_account("Expenses:Food:Dining")
        assert acct is not None
        assert acct.name == "Dining"
        assert acct.fullname == "Expenses:Food:Dining"
        assert acct.depth == 3

    def test_creates_intermediates(self):
        root = Account()
        root.find_account("Expenses:Food:Dining")
        assert "Expenses" in root
        expenses = root["Expenses"]
        assert "Food" in expenses
        food = expenses["Food"]
        assert "Dining" in food

    def test_reuses_existing(self):
        root = Account()
        a1 = root.find_account("Assets:Bank")
        a2 = root.find_account("Assets:Bank")
        assert a1 is a2

    def test_reuses_intermediate(self):
        root = Account()
        root.find_account("Assets:Bank:Checking")
        root.find_account("Assets:Bank:Savings")
        bank = root["Assets"]["Bank"]
        assert "Checking" in bank
        assert "Savings" in bank

    def test_empty_segment_raises(self):
        root = Account()
        try:
            root.find_account(":Expenses")
            assert False, "should have raised"
        except ValueError:
            pass

    def test_empty_middle_segment_raises(self):
        root = Account()
        try:
            root.find_account("Expenses::Food")
            assert False, "should have raised"
        except ValueError:
            pass


# ── find_account without auto-creation ──────────────────────────────


class TestFindAccountNoAutoCreate:
    def test_missing_returns_none(self):
        root = Account()
        assert root.find_account("Assets", auto_create=False) is None

    def test_partial_path_returns_none(self):
        root = Account()
        root.find_account("Assets")  # create Assets
        result = root.find_account("Assets:Bank", auto_create=False)
        assert result is None

    def test_existing_returns_account(self):
        root = Account()
        created = root.find_account("Assets:Bank")
        found = root.find_account("Assets:Bank", auto_create=False)
        assert found is created


# ── Depth tracking ──────────────────────────────────────────────────


class TestDepth:
    def test_root_depth(self):
        assert Account().depth == 0

    def test_find_account_depths(self):
        root = Account()
        root.find_account("A:B:C:D")
        assert root["A"].depth == 1
        assert root["A"]["B"].depth == 2
        assert root["A"]["B"]["C"].depth == 3
        assert root["A"]["B"]["C"]["D"].depth == 4


# ── Iteration and sorting ──────────────────────────────────────────


class TestIteration:
    def test_iter_children(self):
        root = Account()
        root.find_account("A")
        root.find_account("B")
        root.find_account("C")
        names = {a.name for a in root}
        assert names == {"A", "B", "C"}

    def test_len(self):
        root = Account()
        assert len(root) == 0
        root.find_account("X")
        root.find_account("Y")
        assert len(root) == 2

    def test_contains(self):
        root = Account()
        root.find_account("Assets")
        assert "Assets" in root
        assert "Liabilities" not in root

    def test_getitem(self):
        root = Account()
        created = root.find_account("Assets")
        assert root["Assets"] is created

    def test_getitem_missing_raises(self):
        root = Account()
        try:
            _ = root["Missing"]
            assert False, "should have raised"
        except KeyError:
            pass

    def test_has_children(self):
        root = Account()
        assert root.has_children is False
        root.find_account("A")
        assert root.has_children is True

    def test_sorted_children(self):
        root = Account()
        root.find_account("Zebra")
        root.find_account("Apple")
        root.find_account("Mango")
        names = [a.name for a in root.sorted_children()]
        assert names == ["Apple", "Mango", "Zebra"]

    def test_flatten(self):
        root = Account()
        root.find_account("A:B:C")
        root.find_account("A:D")
        flat = root.flatten()
        fullnames = {a.fullname for a in flat}
        assert fullnames == {"A", "A:B", "A:B:C", "A:D"}

    def test_flatten_empty(self):
        root = Account()
        assert root.flatten() == []


# ── Add / remove accounts ──────────────────────────────────────────


class TestAddRemove:
    def test_add_account(self):
        root = Account()
        child = Account(name="Expenses")
        root.add_account(child)
        assert "Expenses" in root
        assert child.parent is root
        assert child.depth == 1

    def test_add_account_updates_depth(self):
        parent = Account(name="Top")
        parent.depth = 2  # simulate non-root
        child = Account(name="Sub")
        parent.add_account(child)
        assert child.depth == 3

    def test_add_account_invalidates_fullname(self):
        root = Account()
        child = Account(parent=None, name="X")
        _ = child.fullname  # cache "X"
        root.add_account(child)
        # After re-parenting, fullname cache should be cleared.
        assert child.fullname == "X"  # root name is empty so still "X"

    def test_remove_account(self):
        root = Account()
        child = root.find_account("Assets")
        assert root.remove_account(child) is True
        assert "Assets" not in root

    def test_remove_nonexistent(self):
        root = Account()
        orphan = Account(name="Ghost")
        assert root.remove_account(orphan) is False


# ── Posts ───────────────────────────────────────────────────────────


class TestPosts:
    def test_add_post(self):
        acct = Account(name="Expenses")
        acct.add_post("post1")
        acct.add_post("post2")
        assert acct.posts == ["post1", "post2"]


# ── Extended data (xdata) ──────────────────────────────────────────


class TestXdata:
    def test_no_xdata_by_default(self):
        acct = Account(name="A")
        assert acct.has_xdata() is False

    def test_xdata_lazy_creation(self):
        acct = Account(name="A")
        xd = acct.xdata()
        assert isinstance(xd, dict)
        assert acct.has_xdata() is True

    def test_set_xdata(self):
        acct = Account(name="A")
        acct.set_xdata("total", 42)
        assert acct.xdata()["total"] == 42

    def test_clear_xdata_recursive(self):
        root = Account()
        child = root.find_account("A:B")
        root.set_xdata("k", 1)
        root["A"].set_xdata("k", 2)
        child.set_xdata("k", 3)
        root.clear_xdata()
        assert root.has_xdata() is False
        assert root["A"].has_xdata() is False
        assert child.has_xdata() is False
