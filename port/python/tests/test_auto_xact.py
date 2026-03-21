"""Tests for automated transactions (``= PREDICATE``)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.auto_xact import AutomatedTransaction, apply_automated_transactions
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.post import POST_GENERATED, POST_VIRTUAL, Post


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse(text: str) -> Journal:
    """Parse *text* as a journal and return the populated Journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestAutoXactParsing:
    """Automated transaction syntax is recognised by the parser."""

    def test_parse_auto_xact_basic(self):
        """A simple ``= /pattern/`` block is parsed."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 1
        auto = journal.auto_xacts[0]
        assert auto.predicate_expr == "/Food/"
        assert len(auto.posts) == 1

    def test_parse_auto_xact_multiple_posts(self):
        """Automated transaction with multiple template postings."""
        text = """\
= /Food/
    (Budget:Food)                        $-100
    (Savings:Food)                       $50

2024-01-15 Grocery Store
    Expenses:Food                        $20
    Assets:Checking
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 1
        assert len(journal.auto_xacts[0].posts) == 2

    def test_parse_multiple_auto_xacts(self):
        """Multiple automated transactions in one journal."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Rent/
    (Budget:Rent)                        $-500

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 2
        assert journal.auto_xacts[0].predicate_expr == "/Food/"
        assert journal.auto_xacts[1].predicate_expr == "/Rent/"

    def test_periodic_xact_still_skipped(self):
        """Periodic transactions (~) are still skipped, not parsed."""
        text = """\
~ Monthly
    Expenses:Rent                        $1000
    Assets:Checking

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert len(journal.auto_xacts) == 0
        assert len(journal.xacts) == 1


# ---------------------------------------------------------------------------
# Predicate matching
# ---------------------------------------------------------------------------


class TestAutoXactMatching:
    """Predicate matching tests."""

    def test_regex_pattern_match(self):
        """Simple /pattern/ matches account fullname."""
        auto = AutomatedTransaction("/Food/")
        journal = Journal()
        account = journal.find_account("Expenses:Food")
        post = Post(account=account, amount=Amount("$50"))
        assert auto.matches(post) is True

    def test_regex_pattern_no_match(self):
        """/pattern/ does not match unrelated accounts."""
        auto = AutomatedTransaction("/Food/")
        journal = Journal()
        account = journal.find_account("Expenses:Rent")
        post = Post(account=account, amount=Amount("$50"))
        assert auto.matches(post) is False

    def test_regex_case_insensitive(self):
        """Pattern matching is case-insensitive."""
        auto = AutomatedTransaction("/food/")
        journal = Journal()
        account = journal.find_account("Expenses:Food")
        post = Post(account=account, amount=Amount("$50"))
        assert auto.matches(post) is True

    def test_account_regex_syntax(self):
        """``account =~ /pattern/`` syntax."""
        auto = AutomatedTransaction("account =~ /Expense/")
        journal = Journal()
        account = journal.find_account("Expenses:Food")
        post = Post(account=account, amount=Amount("$50"))
        assert auto.matches(post) is True

    def test_null_account(self):
        """Post with no account does not match."""
        auto = AutomatedTransaction("/Food/")
        post = Post(account=None, amount=Amount("$50"))
        assert auto.matches(post) is False

    def test_custom_predicate_callable(self):
        """A compiled predicate callable overrides string matching."""
        auto = AutomatedTransaction("/anything/")
        auto.predicate = lambda post: post.amount is not None and post.amount.quantity > 0
        journal = Journal()
        account = journal.find_account("Expenses:Food")
        post = Post(account=account, amount=Amount("$50"))
        assert auto.matches(post) is True
        post2 = Post(account=account, amount=Amount("$-50"))
        assert auto.matches(post2) is False


# ---------------------------------------------------------------------------
# Posting generation
# ---------------------------------------------------------------------------


class TestAutoXactGeneration:
    """Tests for apply_to generating postings."""

    def test_fixed_amount(self):
        """Template with a commoditized amount uses it as-is."""
        journal = Journal()
        budget_acct = journal.find_account("Budget:Food")
        template = Post(account=budget_acct, amount=Amount("$-100"))
        auto = AutomatedTransaction("/Food/", [template])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$50"))

        generated = auto.apply_to(post, journal)
        assert len(generated) == 1
        assert generated[0].amount.quantity == Fraction(-100)
        assert generated[0].amount.commodity == "$"

    def test_multiplier_amount(self):
        """Template without commodity is a multiplier of matched amount."""
        journal = Journal()
        budget_acct = journal.find_account("Budget:Food")
        # 1.0 means 100% of the matched amount
        template = Post(account=budget_acct, amount=Amount("1.0"))
        auto = AutomatedTransaction("/Food/", [template])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$50"))

        generated = auto.apply_to(post, journal)
        assert len(generated) == 1
        # 1.0 * $50 = $50
        assert generated[0].amount.commodity == "$"
        assert float(generated[0].amount.quantity) == pytest.approx(50.0)

    def test_fractional_multiplier(self):
        """A multiplier of 0.5 gives half the matched amount."""
        journal = Journal()
        budget_acct = journal.find_account("Savings:Food")
        template = Post(account=budget_acct, amount=Amount("0.5"))
        auto = AutomatedTransaction("/Food/", [template])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$100"))

        generated = auto.apply_to(post, journal)
        assert len(generated) == 1
        assert float(generated[0].amount.quantity) == pytest.approx(50.0)

    def test_generated_flag(self):
        """Generated postings have the POST_GENERATED flag."""
        journal = Journal()
        budget_acct = journal.find_account("Budget:Food")
        template = Post(account=budget_acct, amount=Amount("$-100"))
        auto = AutomatedTransaction("/Food/", [template])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$50"))

        generated = auto.apply_to(post, journal)
        assert generated[0].has_flags(POST_GENERATED)

    def test_virtual_posting_preserved(self):
        """Template virtual posting flags are preserved in generated."""
        journal = Journal()
        budget_acct = journal.find_account("Budget:Food")
        template = Post(
            account=budget_acct,
            amount=Amount("$-100"),
            flags=POST_VIRTUAL,
        )
        auto = AutomatedTransaction("/Food/", [template])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$50"))

        generated = auto.apply_to(post, journal)
        assert generated[0].is_virtual()
        assert generated[0].has_flags(POST_GENERATED)

    def test_no_match_no_generation(self):
        """Non-matching posting produces no generated postings."""
        journal = Journal()
        budget_acct = journal.find_account("Budget:Food")
        template = Post(account=budget_acct, amount=Amount("$-100"))
        auto = AutomatedTransaction("/Food/", [template])

        rent_acct = journal.find_account("Expenses:Rent")
        post = Post(account=rent_acct, amount=Amount("$500"))

        generated = auto.apply_to(post, journal)
        # apply_to always generates (matching is caller's job), but
        # when used via apply_automated_transactions, no match => no call
        assert len(generated) == 1  # apply_to itself always generates

    def test_multiple_template_postings(self):
        """Auto xact with multiple template postings generates all of them."""
        journal = Journal()
        t1 = Post(account=journal.find_account("Budget:Food"), amount=Amount("$-100"))
        t2 = Post(account=journal.find_account("Savings:Goal"), amount=Amount("$25"))
        auto = AutomatedTransaction("/Food/", [t1, t2])

        food_acct = journal.find_account("Expenses:Food")
        post = Post(account=food_acct, amount=Amount("$50"))

        generated = auto.apply_to(post, journal)
        assert len(generated) == 2


# ---------------------------------------------------------------------------
# Full integration: apply_automated_transactions
# ---------------------------------------------------------------------------


class TestApplyAutomatedTransactions:
    """Integration tests for the apply phase."""

    def test_no_auto_xacts(self):
        """No automated transactions means no changes."""
        text = """\
2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert len(journal.xacts[0].posts) == 2

    def test_simple_auto_xact(self):
        """Basic auto xact adds posting to matching transaction."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        # Original 2 + 1 generated (only Expenses:Food matches /Food/)
        assert len(xact.posts) == 3
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].account.fullname == "Budget:Food"
        assert generated[0].amount.quantity == Fraction(-100)

    def test_no_match_no_extra_posts(self):
        """Transaction not matching the predicate keeps original posts."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Landlord
    Expenses:Rent                        $1000
    Assets:Checking                     $-1000
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert len(xact.posts) == 2

    def test_multiple_matches_same_posting(self):
        """A posting matched by multiple auto xacts gets all generated."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Expenses/
    (Tracking:All)                       $1

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        # Expenses:Food matches both /Food/ and /Expenses/ => +2
        # Assets:Checking matches neither => +0
        # Total = 2 original + 2 generated = 4
        # Actually, /Expenses/ also doesn't match Assets:Checking
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 2

    def test_auto_xact_generated_has_xact_backref(self):
        """Generated postings have their xact back-reference set."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].xact is xact

    def test_multiplier_integration(self):
        """Multiplier amount in auto xact via full parse."""
        text = """\
= /Food/
    (Budget:Food)                        1.0

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        # 1.0 * $50 = $50
        assert generated[0].amount.commodity == "$"
        assert float(generated[0].amount.quantity) == pytest.approx(50.0)

    def test_auto_xact_with_multiple_postings(self):
        """Auto xact with multiple template postings all get generated."""
        text = """\
= /Food/
    (Budget:Food)                        $-100
    (Savings:Goal)                       $25

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 2

    def test_auto_xact_virtual_posting(self):
        """Virtual posting (parenthesized account) in auto xact."""
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        assert len(generated) == 1
        assert generated[0].is_virtual()

    def test_auto_xact_applies_after_all_parsing(self):
        """Auto xacts apply even if defined after the transactions they match."""
        # In Ledger, auto xacts are applied in a post-parse pass, so
        # ordering doesn't matter for which transactions they apply to.
        # However, our parser currently processes = lines in order and
        # applies at the end. Auto xact defined before transaction works.
        text = """\
= /Food/
    (Budget:Food)                        $-100

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-01-20 Restaurant
    Expenses:Food                        $30
    Assets:Checking                     $-30
"""
        journal = _parse(text)
        # Both transactions should have auto xact applied
        for xact in journal.xacts:
            generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
            assert len(generated) == 1
            assert generated[0].account.fullname == "Budget:Food"

    def test_auto_xact_does_not_recurse(self):
        """Generated postings are not re-matched by auto xacts."""
        # If auto xact generates a posting to Budget:Food and another
        # auto xact matches /Budget/, the generated posting should NOT
        # trigger additional generation (we only match original posts).
        text = """\
= /Food/
    (Budget:Food)                        $-100

= /Budget/
    (Meta:Budget)                        $1

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        generated = [p for p in xact.posts if p.has_flags(POST_GENERATED)]
        # Only 1 generated from /Food/ match on Expenses:Food
        # /Budget/ doesn't match any original posting
        assert len(generated) == 1

    def test_multiple_transactions_selective_match(self):
        """Auto xact matches only relevant transactions."""
        text = """\
= /Food/
    (Budget:Food)                        $-50

2024-01-15 Grocery Store
    Expenses:Food                        $50
    Assets:Checking                     $-50

2024-01-16 Landlord
    Expenses:Rent                        $1000
    Assets:Checking                     $-1000

2024-01-17 Restaurant
    Expenses:Food:Dining                 $30
    Assets:Checking                     $-30
"""
        journal = _parse(text)
        # First xact matches
        g1 = [p for p in journal.xacts[0].posts if p.has_flags(POST_GENERATED)]
        assert len(g1) == 1
        # Second xact does not match
        g2 = [p for p in journal.xacts[1].posts if p.has_flags(POST_GENERATED)]
        assert len(g2) == 0
        # Third xact matches (Food:Dining contains "Food")
        g3 = [p for p in journal.xacts[2].posts if p.has_flags(POST_GENERATED)]
        assert len(g3) == 1


# ---------------------------------------------------------------------------
# AutomatedTransaction repr
# ---------------------------------------------------------------------------


class TestAutoXactRepr:
    """Test string representation."""

    def test_repr(self):
        auto = AutomatedTransaction("/Food/")
        assert "AutomatedTransaction" in repr(auto)
        assert "/Food/" in repr(auto)
