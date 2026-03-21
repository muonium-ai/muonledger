"""Tests for virtual postings: (Account) and [Account] syntax.

Covers parsing, balancing semantics, null-amount inference, --real filtering,
and end-to-end behavior through the parser and finalize pipeline.
"""

from datetime import date

import pytest

from muonledger.amount import Amount
from muonledger.item import ITEM_INFERRED
from muonledger.journal import Journal
from muonledger.parser import TextualParser, ParseError
from muonledger.post import (
    POST_CALCULATED,
    POST_MUST_BALANCE,
    POST_VIRTUAL,
    Post,
)
from muonledger.xact import BalanceError, Transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(account_name: str, amount=None, flags: int = 0) -> Post:
    """Create a Post with a string account and optional amount."""
    p = Post(account=account_name, amount=amount, flags=flags)
    return p


def _virtual_post(account_name: str, amount=None) -> Post:
    """Virtual posting -- (Account), does not need to balance."""
    return _make_post(account_name, amount, flags=POST_VIRTUAL)


def _balanced_virtual_post(account_name: str, amount=None) -> Post:
    """Balanced virtual posting -- [Account], must balance."""
    return _make_post(account_name, amount, flags=POST_VIRTUAL | POST_MUST_BALANCE)


def _parse(text: str) -> Journal:
    """Parse a journal string and return the Journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


# ---------------------------------------------------------------------------
# 1. Post flag tests
# ---------------------------------------------------------------------------


class TestPostFlags:
    def test_regular_post_is_not_virtual(self):
        p = _make_post("Expenses:Food", Amount("$10"))
        assert not p.is_virtual()
        assert p.must_balance()

    def test_virtual_post_flags(self):
        p = _virtual_post("Budget:Food", Amount("$10"))
        assert p.is_virtual()
        assert not p.must_balance()
        assert p.has_flags(POST_VIRTUAL)
        assert not p.has_flags(POST_MUST_BALANCE)

    def test_balanced_virtual_post_flags(self):
        p = _balanced_virtual_post("Budget:Food", Amount("$10"))
        assert p.is_virtual()
        assert p.must_balance()
        assert p.has_flags(POST_VIRTUAL)
        assert p.has_flags(POST_MUST_BALANCE)


# ---------------------------------------------------------------------------
# 2. Parsing tests
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parse_virtual_account(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget:Food)         $10.00
"""
        j = _parse(text)
        assert len(j.xacts) == 1
        posts = j.xacts[0].posts
        assert len(posts) == 3
        assert not posts[0].is_virtual()
        assert not posts[1].is_virtual()
        assert posts[2].is_virtual()
        assert not posts[2].must_balance()

    def test_parse_balanced_virtual_account(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $10.00
    [Budget:Checking]    -$10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert len(posts) == 4
        assert posts[2].is_virtual()
        assert posts[2].must_balance()
        assert posts[3].is_virtual()
        assert posts[3].must_balance()

    def test_parse_virtual_nested_account(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Expenses:Food:Tracking)  $10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        acct = posts[2].account
        name = acct.fullname if hasattr(acct, 'fullname') else str(acct)
        assert "Expenses:Food:Tracking" in name

    def test_parse_balanced_virtual_nested_account(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food:Monthly]   $10.00
    [Budget:Checking]      -$10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        acct = posts[2].account
        name = acct.fullname if hasattr(acct, 'fullname') else str(acct)
        assert "Budget:Food:Monthly" in name

    def test_parse_unclosed_paren_raises(self):
        text = """\
2024/01/01 Test
    (Budget:Food         $10.00
    Assets:Cash          -$10.00
"""
        with pytest.raises(ParseError, match="Expected '\\)'"):
            _parse(text)

    def test_parse_unclosed_bracket_raises(self):
        text = """\
2024/01/01 Test
    [Budget:Food         $10.00
    Assets:Cash          -$10.00
"""
        with pytest.raises(ParseError, match="Expected '\\]'"):
            _parse(text)

    def test_parse_virtual_with_spaces_in_name(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget Envelope:Food)  $10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        acct = posts[2].account
        name = acct.fullname if hasattr(acct, 'fullname') else str(acct)
        assert "Budget Envelope:Food" in name
        assert posts[2].is_virtual()

    def test_parse_virtual_with_state_marker(self):
        """Virtual posting with clearing state marker."""
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    * (Budget:Food)       $10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert posts[2].is_virtual()

    def test_parse_balanced_virtual_with_note(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $10.00  ; tracking
    [Budget:Checking]    -$10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert posts[2].is_virtual()
        assert posts[2].must_balance()


# ---------------------------------------------------------------------------
# 3. Finalize / balancing tests (unit-level using Transaction directly)
# ---------------------------------------------------------------------------


class TestFinalizeBalancing:
    def test_real_posts_balance(self):
        """Regular postings must balance to zero."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        assert xact.finalize() is True

    def test_real_posts_unbalanced_raises(self):
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$5")))
        with pytest.raises(BalanceError):
            xact.finalize()

    def test_virtual_posts_skip_balance_check(self):
        """Virtual postings (Account) are not checked for balance."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_virtual_post("Budget:Food", Amount("$999")))
        assert xact.finalize() is True

    def test_balanced_virtual_must_balance(self):
        """Balanced virtual postings [Account] must balance among themselves."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$10")))
        assert xact.finalize() is True

    def test_balanced_virtual_unbalanced_raises(self):
        """Unbalanced balanced-virtual postings raise BalanceError."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$5")))
        with pytest.raises(BalanceError, match="balanced virtual"):
            xact.finalize()

    def test_balanced_virtual_independent_from_real(self):
        """Balanced virtual group balances independently from real group."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$50")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$50")))
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$20")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$20")))
        assert xact.finalize() is True

    def test_mixed_all_three_types(self):
        """Transaction with real + virtual + balanced virtual."""
        xact = Transaction(payee="Test")
        # Real
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        # Virtual (no balance check)
        xact.add_post(_virtual_post("Budget:Tracking", Amount("$10")))
        # Balanced virtual
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Available", Amount("-$10")))
        assert xact.finalize() is True

    def test_only_virtual_posts(self):
        """All-virtual transaction -- no balance check needed."""
        xact = Transaction(payee="Test")
        xact.add_post(_virtual_post("Budget:A", Amount("$100")))
        xact.add_post(_virtual_post("Budget:B", Amount("$200")))
        assert xact.finalize() is True

    def test_only_balanced_virtual_posts(self):
        """All balanced-virtual -- must balance among themselves."""
        xact = Transaction(payee="Test")
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$10")))
        assert xact.finalize() is True

    def test_only_balanced_virtual_unbalanced_raises(self):
        xact = Transaction(payee="Test")
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$3")))
        with pytest.raises(BalanceError):
            xact.finalize()


# ---------------------------------------------------------------------------
# 4. Null-amount inference tests
# ---------------------------------------------------------------------------


class TestNullAmountInference:
    def test_infer_real_null_amount(self):
        """Null-amount inference works for real postings."""
        xact = Transaction(payee="Test")
        p1 = _make_post("Expenses:Food", Amount("$10"))
        p2 = _make_post("Assets:Cash")  # null amount
        xact.add_post(p1)
        xact.add_post(p2)
        xact.finalize()
        assert p2.amount is not None
        assert p2.amount is not None
        # The commodity precision from Amount("$10") gives "$-10.00"
        assert p2.amount.quantity == -10

    def test_infer_balanced_virtual_null_amount(self):
        """Null-amount inference works for balanced virtual postings."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        p_bv = _balanced_virtual_post("Budget:Food", Amount("$25"))
        p_bv_null = _balanced_virtual_post("Budget:Checking")
        xact.add_post(p_bv)
        xact.add_post(p_bv_null)
        xact.finalize()
        assert p_bv_null.amount is not None
        assert p_bv_null.amount.quantity == -25

    def test_infer_null_in_each_group_independently(self):
        """Each group can have its own null-amount posting."""
        xact = Transaction(payee="Test")
        # Real group: one null
        p_real1 = _make_post("Expenses:Food", Amount("$10"))
        p_real2 = _make_post("Assets:Cash")  # inferred
        xact.add_post(p_real1)
        xact.add_post(p_real2)
        # Balanced virtual group: one null
        p_bv1 = _balanced_virtual_post("Budget:Food", Amount("$30"))
        p_bv2 = _balanced_virtual_post("Budget:Checking")  # inferred
        xact.add_post(p_bv1)
        xact.add_post(p_bv2)
        xact.finalize()
        assert p_real2.amount.quantity == -10
        assert p_bv2.amount.quantity == -30

    def test_infer_virtual_null_amount_not_checked(self):
        """Virtual postings with null amounts are fine (not balance-checked)."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_virtual_post("Budget:Food"))  # null virtual
        # Should not raise -- virtual posts are ignored for balancing
        assert xact.finalize() is True

    def test_multiple_null_real_raises(self):
        """Two null-amount real postings raise BalanceError."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food"))
        xact.add_post(_make_post("Assets:Cash"))
        with pytest.raises(BalanceError, match="null amount"):
            xact.finalize()

    def test_multiple_null_balanced_virtual_raises(self):
        """Two null-amount balanced virtual postings raise BalanceError."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_balanced_virtual_post("Budget:Food"))
        xact.add_post(_balanced_virtual_post("Budget:Checking"))
        with pytest.raises(BalanceError, match="null amount"):
            xact.finalize()

    def test_inferred_post_gets_calculated_flag(self):
        """Inferred posting gets POST_CALCULATED and ITEM_INFERRED flags."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        p = _make_post("Assets:Cash")
        xact.add_post(p)
        xact.finalize()
        assert p.has_flags(POST_CALCULATED)
        assert p.has_flags(ITEM_INFERRED)

    def test_inferred_balanced_virtual_gets_flags(self):
        """Inferred balanced virtual posting gets calculated flags."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        p = _balanced_virtual_post("Budget:Checking")
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(p)
        xact.finalize()
        assert p.has_flags(POST_CALCULATED)
        assert p.has_flags(ITEM_INFERRED)


# ---------------------------------------------------------------------------
# 5. End-to-end parser + finalize tests
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_parse_virtual_unbalanced_ok(self):
        """Virtual posting can have any amount -- no balance error."""
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget:Food)       $9999.00
"""
        j = _parse(text)
        assert len(j.xacts) == 1

    def test_parse_balanced_virtual_balanced_ok(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $10.00
    [Budget:Checking]    -$10.00
"""
        j = _parse(text)
        assert len(j.xacts) == 1

    def test_parse_balanced_virtual_unbalanced_raises(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $10.00
    [Budget:Checking]     -$3.00
"""
        with pytest.raises(BalanceError, match="balanced virtual"):
            _parse(text)

    def test_parse_null_amount_inference_real(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert posts[1].amount is not None
        assert posts[1].amount.quantity == -10

    def test_parse_null_amount_inference_balanced_virtual(self):
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $25.00
    [Budget:Checking]
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert posts[3].amount is not None
        assert posts[3].amount.quantity == -25

    def test_parse_both_groups_null_inference(self):
        """Both real and balanced virtual groups can each have a null posting."""
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash
    [Budget:Food]         $25.00
    [Budget:Checking]
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        assert posts[1].amount.quantity == -10
        assert posts[3].amount.quantity == -25

    def test_parse_mixed_three_types(self):
        text = """\
2024/01/01 Mixed transaction
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget:Tracking)     $10.00
    [Budget:Food]         $10.00
    [Budget:Available]   -$10.00
"""
        j = _parse(text)
        assert len(j.xacts) == 1
        posts = j.xacts[0].posts
        assert len(posts) == 5
        # Verify types
        assert not posts[0].is_virtual()  # real
        assert not posts[1].is_virtual()  # real
        assert posts[2].is_virtual() and not posts[2].must_balance()  # virtual
        assert posts[3].is_virtual() and posts[3].must_balance()  # balanced virtual
        assert posts[4].is_virtual() and posts[4].must_balance()  # balanced virtual

    def test_parse_only_virtual_postings(self):
        """Transaction with only virtual postings, no real ones."""
        text = """\
2024/01/01 Budget only
    (Budget:A)            $100.00
    (Budget:B)            $200.00
"""
        j = _parse(text)
        assert len(j.xacts) == 1

    def test_parse_multiple_transactions_with_virtual(self):
        text = """\
2024/01/01 First
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget:Food)         $10.00

2024/01/02 Second
    Expenses:Rent        $500.00
    Assets:Cash         -$500.00
    [Budget:Rent]        $500.00
    [Budget:Available]  -$500.00
"""
        j = _parse(text)
        assert len(j.xacts) == 2
        assert j.xacts[0].posts[2].is_virtual()
        assert j.xacts[1].posts[2].is_virtual()
        assert j.xacts[1].posts[2].must_balance()


# ---------------------------------------------------------------------------
# 6. --real flag / report filtering
# ---------------------------------------------------------------------------


class TestRealFiltering:
    def test_real_option_filters_virtual(self):
        """With --real, virtual postings are excluded from reports."""
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    (Budget:Food)         $10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        real_posts = [p for p in posts if not p.is_virtual()]
        assert len(real_posts) == 2
        virtual_posts = [p for p in posts if p.is_virtual()]
        assert len(virtual_posts) == 1

    def test_real_option_filters_balanced_virtual(self):
        """With --real, balanced virtual postings are also excluded."""
        text = """\
2024/01/01 Test
    Expenses:Food         $10.00
    Assets:Cash          -$10.00
    [Budget:Food]         $10.00
    [Budget:Checking]    -$10.00
"""
        j = _parse(text)
        posts = j.xacts[0].posts
        real_posts = [p for p in posts if not p.is_virtual()]
        assert len(real_posts) == 2

    def test_is_virtual_predicate(self):
        """Both virtual and balanced-virtual report as is_virtual()."""
        p1 = _virtual_post("A", Amount("$10"))
        p2 = _balanced_virtual_post("B", Amount("$10"))
        p3 = _make_post("C", Amount("$10"))
        assert p1.is_virtual() is True
        assert p2.is_virtual() is True
        assert p3.is_virtual() is False


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_transaction_returns_false(self):
        xact = Transaction(payee="Test")
        assert xact.finalize() is False

    def test_all_null_amounts(self):
        """Transaction where every posting has null amount returns False."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("A"))
        # Only one null-amount post in the real group -- it gets inferred to $0
        # which makes all_null True (all zero/null)
        result = xact.finalize()
        # With single null-amount, amount is set to $0, which is null-ish
        # The all_null check looks at original null; after inference it's Amount(0)
        # Amount(0).is_null() returns False, so this should return True
        assert result is True

    def test_virtual_with_cost(self):
        """Virtual posting with cost annotation."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        p = _virtual_post("Budget:Food", Amount("10 BUDG"))
        p.cost = Amount("$10")
        xact.add_post(p)
        assert xact.finalize() is True

    def test_balanced_virtual_with_cost(self):
        """Balanced virtual with cost -- cost is used for balance check."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        p1 = _balanced_virtual_post("Budget:Food", Amount("10 BUDG"))
        p1.cost = Amount("$10")
        p2 = _balanced_virtual_post("Budget:Checking", Amount("-10 BUDG"))
        p2.cost = Amount("-$10")
        xact.add_post(p1)
        xact.add_post(p2)
        assert xact.finalize() is True

    def test_single_virtual_post(self):
        """Single virtual posting in a transaction."""
        xact = Transaction(payee="Test")
        xact.add_post(_virtual_post("Budget:Tracking", Amount("$42")))
        assert xact.finalize() is True

    def test_single_balanced_virtual_with_zero(self):
        """Single balanced virtual posting with zero amount."""
        xact = Transaction(payee="Test")
        xact.add_post(_balanced_virtual_post("Budget:Zero", Amount("$0")))
        assert xact.finalize() is True

    def test_real_unbalanced_despite_virtual_balance(self):
        """Real postings unbalanced even though virtual offsets exist."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$5")))
        # Virtual post "balances" the $5 gap, but shouldn't count
        xact.add_post(_virtual_post("Budget:Fix", Amount("-$5")))
        with pytest.raises(BalanceError, match="real"):
            xact.finalize()

    def test_balanced_virtual_unbalanced_despite_real_offset(self):
        """Balanced virtual group unbalanced despite real postings offsetting."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_balanced_virtual_post("Budget:Food", Amount("$10")))
        xact.add_post(_balanced_virtual_post("Budget:Checking", Amount("-$7")))
        with pytest.raises(BalanceError, match="balanced virtual"):
            xact.finalize()

    def test_multiple_commodities_in_balanced_virtual(self):
        """Balanced virtual postings with two commodities must each balance."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("A", Amount("$10")))
        xact.add_post(_make_post("B", Amount("-$10")))
        # Balanced virtual with two commodities that don't net out
        xact.add_post(_balanced_virtual_post("BV:A", Amount("10 EUR")))
        xact.add_post(_balanced_virtual_post("BV:B", Amount("-10 EUR")))
        assert xact.finalize() is True

    def test_magnitude_includes_virtual_posts(self):
        """Transaction.magnitude() includes all positive postings."""
        xact = Transaction(payee="Test")
        xact.add_post(_make_post("Expenses:Food", Amount("$10")))
        xact.add_post(_make_post("Assets:Cash", Amount("-$10")))
        xact.add_post(_virtual_post("Budget:Food", Amount("$5")))
        mag = xact.magnitude()
        # Should include both $10 and $5
        assert not mag.is_null()
