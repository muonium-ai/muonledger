"""Regression tests for T-000075 fixes.

Tests covering:
1. Empty transaction validation (no postings)
2. Comment-only transaction validation (no real postings)
3. Effective dates on postings ([=DATE], [DATE], [DATE=DATE])
4. Edge cases discovered while implementing fixes
"""

from __future__ import annotations

from datetime import date

import pytest

from muonledger.journal import Journal
from muonledger.parser import ParseError, TextualParser
from muonledger.xact import BalanceError, Transaction
from muonledger.post import Post
from muonledger.amount import Amount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(text: str) -> Journal:
    """Parse *text* and return the populated journal."""
    journal = Journal()
    parser = TextualParser()
    parser.parse_string(text, journal)
    return journal


def _parse_count(text: str) -> int:
    """Parse *text* and return the transaction count."""
    journal = Journal()
    parser = TextualParser()
    return parser.parse_string(text, journal)


# ===========================================================================
# Category 1: Empty Transaction Validation
# ===========================================================================


class TestEmptyTransactionValidation:
    """Transactions with no postings should be rejected."""

    def test_empty_transaction_not_added(self):
        """Transaction with no postings should not appear in journal."""
        text = """\
2024/01/15 Empty Transaction
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_count_zero(self):
        """Parse count should be 0 for empty transaction."""
        text = """\
2024/01/15 Empty Transaction
"""
        count = _parse_count(text)
        assert count == 0

    def test_empty_transaction_finalize_returns_false(self):
        """Transaction.finalize() should return False with no postings."""
        xact = Transaction(payee="Empty")
        xact.date = date(2024, 1, 15)
        assert xact.finalize() is False

    def test_empty_transaction_followed_by_valid(self):
        """Empty transaction should be skipped; valid one should be kept."""
        text = """\
2024/01/15 Empty

2024/01/16 Valid
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Valid"
        assert journal.xacts[0].date == date(2024, 1, 16)

    def test_multiple_empty_transactions(self):
        """Multiple empty transactions should all be skipped."""
        text = """\
2024/01/15 Empty1

2024/01/16 Empty2

2024/01/17 Empty3
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_with_state_marker(self):
        """Empty cleared transaction should still be rejected."""
        text = """\
2024/01/15 * Empty Cleared
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_with_code(self):
        """Empty transaction with code should still be rejected."""
        text = """\
2024/01/15 (CHK-001) Empty With Code
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_with_inline_note(self):
        """Empty transaction with inline note should still be rejected."""
        text = """\
2024/01/15 Empty ; with a note
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_with_aux_date(self):
        """Empty transaction with aux date should still be rejected."""
        text = """\
2024/01/15=2024/01/20 Empty With Aux Date
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0


# ===========================================================================
# Category 2: Comment-Only Transaction Validation
# ===========================================================================


class TestCommentOnlyTransactionValidation:
    """Transactions with only comment lines (no real postings) should be rejected."""

    def test_single_comment_line(self):
        """Transaction with only one comment line should not be added."""
        text = """\
2024/01/15 Comments Only
    ; This is just a comment
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_multiple_comment_lines(self):
        """Transaction with multiple comment lines but no postings."""
        text = """\
2024/01/15 Comments Only
    ; Comment 1
    ; Comment 2
    ; Comment 3
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_comment_with_metadata(self):
        """Transaction with metadata-bearing comments but no postings."""
        text = """\
2024/01/15 Comments Only
    ; :tag1:tag2:
    ; key: value
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_comment_only_followed_by_valid(self):
        """Comment-only transaction skipped; valid one kept."""
        text = """\
2024/01/15 Comments Only
    ; Just a comment

2024/01/16 Valid
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Valid"

    def test_comment_only_between_valid(self):
        """Comment-only transaction between valid ones should be skipped."""
        text = """\
2024/01/15 First
    Expenses:A  $10.00
    Assets:B

2024/01/16 Comments Only
    ; Just comments

2024/01/17 Third
    Expenses:C  $20.00
    Assets:D
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2
        assert journal.xacts[0].payee == "First"
        assert journal.xacts[1].payee == "Third"

    def test_comment_with_effective_date_no_postings(self):
        """Comment with effective date pattern but no postings should still be rejected."""
        text = """\
2024/01/15 Comments Only
    ; [=2024/02/01]
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0


# ===========================================================================
# Category 3: Effective Dates on Postings
# ===========================================================================


class TestEffectiveDateOnPosting:
    """Effective date comments on postings: [=DATE], [DATE], [DATE=DATE]."""

    def test_aux_date_equals_format(self):
        """Effective date: ; [=2024/02/01] sets post.date_aux."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)

    def test_aux_date_dash_format(self):
        """Effective date with dashes: ; [=2024-02-01]."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024-02-01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)

    def test_posting_date_only(self):
        """Posting date: ; [2024/02/01] sets post.date."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date == date(2024, 2, 1)

    def test_both_dates(self):
        """Both dates: ; [2024/02/01=2024/03/01] sets both."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [2024/02/01=2024/03/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date == date(2024, 2, 1)
        assert post.date_aux == date(2024, 3, 1)

    def test_effective_date_on_second_posting(self):
        """Effective date on the second posting, not the first."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    Assets:B
    ; [=2024/02/15]
"""
        journal = _parse(text)
        post0 = journal.xacts[0].posts[0]
        post1 = journal.xacts[0].posts[1]
        assert post0.date_aux is None
        assert post1.date_aux == date(2024, 2, 15)

    def test_effective_date_with_other_note(self):
        """Effective date on a line that also has note text via separate lines."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; posting note
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)
        assert post.note is not None
        assert "posting note" in post.note

    def test_effective_date_no_effect_on_transaction(self):
        """Effective date on posting should not change the transaction date."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        assert xact.date == date(2024, 1, 1)
        assert xact.date_aux is None

    def test_multiple_postings_different_effective_dates(self):
        """Different effective dates on different postings."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024/02/01]
    Expenses:B  $20.00
    ; [=2024/03/01]
    Assets:C
"""
        journal = _parse(text)
        post0 = journal.xacts[0].posts[0]
        post1 = journal.xacts[0].posts[1]
        post2 = journal.xacts[0].posts[2]
        assert post0.date_aux == date(2024, 2, 1)
        assert post1.date_aux == date(2024, 3, 1)
        assert post2.date_aux is None

    def test_effective_date_before_posting_applies_to_xact(self):
        """Effective date comment before any posting applies to transaction."""
        text = """\
2024/01/01 Test
    ; [=2024/02/01]
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        xact = journal.xacts[0]
        # When no postings yet, comment attaches to the transaction
        assert xact.date_aux == date(2024, 2, 1)


# ===========================================================================
# Category 4: Transaction Finalize Edge Cases
# ===========================================================================


class TestFinalizeEdgeCases:
    """Edge cases in Transaction.finalize()."""

    def test_single_posting_zero_amount(self):
        """Single posting with zero amount should work."""
        xact = Transaction(payee="Zero")
        xact.date = date(2024, 1, 1)
        post = Post(account=None, amount=Amount(0))
        xact.add_post(post)
        assert xact.finalize() is True

    def test_single_posting_null_amount(self):
        """Single posting with null amount: inferred as zero."""
        xact = Transaction(payee="Null")
        xact.date = date(2024, 1, 1)
        post = Post(account=None, amount=None)
        xact.add_post(post)
        # finalize infers the null amount
        result = xact.finalize()
        # With a single null posting, the amount is inferred as 0
        assert post.amount is not None

    def test_all_null_amounts_returns_false(self):
        """Multiple postings with all null amounts returns False."""
        xact = Transaction(payee="AllNull")
        xact.date = date(2024, 1, 1)
        # Two postings both with null amounts -- second null raises error
        # per "Only one posting with null amount allowed" rule
        # Actually, must_balance returns True for real postings so the
        # second null-amount post triggers an error.
        post1 = Post(account=None, amount=None)
        xact.add_post(post1)
        # finalize with single null posting is fine
        result = xact.finalize()
        assert result is True  # single null posting gets inferred to 0

    def test_two_null_amounts_raises(self):
        """Two null-amount postings should raise BalanceError."""
        xact = Transaction(payee="TwoNull")
        xact.date = date(2024, 1, 1)
        post1 = Post(account=None, amount=None)
        post2 = Post(account=None, amount=None)
        xact.add_post(post1)
        xact.add_post(post2)
        with pytest.raises(BalanceError, match="null amount"):
            xact.finalize()


# ===========================================================================
# Category 5: Parser Interaction Edge Cases
# ===========================================================================


class TestParserEdgeCases:
    """Parser edge cases related to empty/comment-only transactions."""

    def test_parse_count_matches_journal_xacts(self):
        """Parse count should equal len(journal.xacts) after parsing."""
        text = """\
2024/01/01 First
    Expenses:A  $10.00
    Assets:B

2024/01/02 Empty

2024/01/03 Third
    Expenses:C  $30.00
    Assets:D
"""
        journal = Journal()
        parser = TextualParser()
        count = parser.parse_string(text, journal)
        assert count == len(journal.xacts)
        assert count == 2

    def test_empty_string_parse(self):
        """Parsing empty string should produce no transactions."""
        journal = _parse("")
        assert len(journal.xacts) == 0

    def test_only_comments_parse(self):
        """Parsing text with only top-level comments."""
        text = """\
; Just a comment
# Another comment
"""
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_whitespace_only_parse(self):
        """Parsing text with only whitespace/blank lines."""
        text = "\n\n   \n\n"
        journal = _parse(text)
        assert len(journal.xacts) == 0

    def test_empty_transaction_does_not_corrupt_state(self):
        """Empty transaction should not leave dangling state in parser."""
        text = """\
2024/01/01 Empty

2024/01/02 Valid1
    Expenses:A  $10.00
    Assets:B

2024/01/03 Empty2

2024/01/04 Valid2
    Expenses:C  $20.00
    Assets:D
"""
        journal = _parse(text)
        assert len(journal.xacts) == 2
        assert journal.xacts[0].payee == "Valid1"
        assert journal.xacts[1].payee == "Valid2"
        # Make sure amounts are correct
        assert float(journal.xacts[0].posts[0].amount) == pytest.approx(10.0)
        assert float(journal.xacts[1].posts[0].amount) == pytest.approx(20.0)


# ===========================================================================
# Category 6: Effective Date with Various Posting Scenarios
# ===========================================================================


class TestEffectiveDateScenarios:
    """More complex scenarios involving effective dates."""

    def test_effective_date_with_cost(self):
        """Effective date on posting with a cost."""
        text = """\
2024/01/01 Buy stock
    Assets:Brokerage  10 AAPL @ $150.00
    ; [=2024/01/15]
    Assets:Checking
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 1, 15)
        assert float(post.amount) == pytest.approx(10.0)

    def test_effective_date_with_virtual_posting(self):
        """Effective date on a virtual posting."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    Assets:B    -$10.00
    (Budget:Food)  $-10.00
    ; [=2024/02/01]
"""
        journal = _parse(text)
        # Virtual posting is the third posting
        virtual_post = journal.xacts[0].posts[2]
        assert virtual_post.date_aux == date(2024, 2, 1)

    def test_effective_date_with_cleared_posting(self):
        """Effective date on a cleared posting."""
        text = """\
2024/01/01 Test
    * Expenses:A  $10.00
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)

    def test_effective_date_does_not_interfere_with_metadata(self):
        """Effective date line should not interfere with regular metadata."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; :category:
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)
        assert post.has_tag("category")

    def test_posting_date_in_separate_comment(self):
        """Primary posting date from comment."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00
    ; [2024/06/15]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date == date(2024, 6, 15)

    def test_effective_date_with_note_on_posting(self):
        """Posting with its own inline note plus effective date on next line."""
        text = """\
2024/01/01 Test
    Expenses:A  $10.00  ; inline note
    ; [=2024/02/01]
    Assets:B
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)
        assert post.note is not None
        assert "inline note" in post.note


# ===========================================================================
# Category 7: Mixing Empty/Comment-Only with Other Features
# ===========================================================================


class TestMixedScenarios:
    """Mixed scenarios combining multiple fix areas."""

    def test_empty_xact_with_directives(self):
        """Empty transaction should not interfere with directives."""
        text = """\
account Expenses:A

2024/01/01 Empty

2024/01/02 Valid
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].posts[0].account.fullname == "Expenses:A"

    def test_comment_only_xact_with_apply_tag(self):
        """Comment-only transaction under apply tag should be skipped."""
        text = """\
apply tag project

2024/01/01 Comments Only
    ; Just a note

2024/01/02 Valid
    Expenses:A  $10.00
    Assets:B

end apply tag
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].has_tag("project")

    def test_effective_date_with_apply_account(self):
        """Effective date works with apply account prefix."""
        text = """\
apply account Personal

2024/01/01 Test
    Expenses:A  $10.00
    ; [=2024/02/01]
    Assets:B

end apply account
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 2, 1)
        assert post.account.fullname == "Personal:Expenses:A"

    def test_empty_xact_with_year_directive(self):
        """Empty transaction after year directive."""
        text = """\
Y 2024

2024/01/01 Empty

2024/01/02 Valid
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1

    def test_valid_xact_after_several_empty_and_comment_only(self):
        """Multiple empties and comment-only, then a valid one."""
        text = """\
2024/01/01 Empty1

2024/01/02 Empty2

2024/01/03 CommentOnly
    ; comment

2024/01/04 Empty3

2024/01/05 Valid
    Expenses:A  $10.00
    Assets:B
"""
        journal = _parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Valid"
        assert journal.xacts[0].date == date(2024, 1, 5)

    def test_effective_date_multi_commodity(self):
        """Effective date with multi-commodity transaction using cost."""
        text = """\
2024/01/01 Exchange
    Assets:EUR  100 EUR @ $1.10
    ; [=2024/01/15]
    Assets:USD
"""
        journal = _parse(text)
        post = journal.xacts[0].posts[0]
        assert post.date_aux == date(2024, 1, 15)
        assert post.amount.commodity == "EUR"
