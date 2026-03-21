"""Automated transactions (``= PREDICATE``).

Ported from ledger's ``auto_xact_t``.  An automated transaction uses the
``=`` prefix followed by a predicate expression.  When a regular posting
matches the predicate, the automated transaction's template postings are
generated and appended to the matching transaction.

Example journal syntax::

    = /Food/
        (Budget:Food)                        $-100

    2024-01-15 Grocery Store
        Expenses:Food                        $50
        Assets:Checking                     $-50

When any posting matches ``/Food/``, the template posting is generated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional

from muonledger.amount import Amount
from muonledger.post import POST_GENERATED, Post

if TYPE_CHECKING:
    from muonledger.journal import Journal

__all__ = ["AutomatedTransaction", "apply_automated_transactions"]


class AutomatedTransaction:
    """An automated transaction (``= PREDICATE``).

    Parameters
    ----------
    predicate_expr : str
        The predicate expression string, e.g. ``/Food/`` or
        ``account =~ /Expense/``.
    posts : list[Post]
        Template postings to generate when a match occurs.
    """

    __slots__ = ("predicate_expr", "posts", "predicate")

    def __init__(
        self, predicate_expr: str, posts: Optional[List[Post]] = None
    ) -> None:
        self.predicate_expr: str = predicate_expr
        self.posts: List[Post] = posts if posts is not None else []
        self.predicate = None  # Optional compiled predicate callable

    def matches(self, post: Post) -> bool:
        """Test if *post* matches this automated transaction's predicate.

        If a compiled :attr:`predicate` callable is set, it is used.
        Otherwise the predicate expression is interpreted as a simple
        regex pattern (``/pattern/``) matched against the account's
        full name.
        """
        if self.predicate is not None:
            return self.predicate(post)

        expr = self.predicate_expr.strip()

        # Simple regex: /pattern/
        if expr.startswith("/") and expr.endswith("/") and len(expr) > 1:
            pattern = expr[1:-1]
            if post.account is None:
                return False
            fullname = post.account.fullname
            try:
                return bool(re.search(pattern, fullname, re.IGNORECASE))
            except re.error:
                return False

        # account =~ /pattern/
        m = re.match(r"account\s*=~\s*/(.+)/", expr)
        if m:
            pattern = m.group(1)
            if post.account is None:
                return False
            fullname = post.account.fullname
            try:
                return bool(re.search(pattern, fullname, re.IGNORECASE))
            except re.error:
                return False

        # Bare string: treat as substring match on account name
        if post.account is not None:
            return expr.lower() in post.account.fullname.lower()

        return False

    def apply_to(self, post: Post, journal: "Journal") -> List[Post]:
        """Generate postings to add based on the matching *post*.

        For each template posting:
        - If the template has an amount with a commodity, use it as-is
          (fixed amount).
        - If the template has an amount without a commodity, treat it
          as a multiplier of the matched posting's amount (e.g. ``1.0``
          means 100%).

        Every generated posting gets the ``POST_GENERATED`` flag.
        """
        generated: List[Post] = []
        for template in self.posts:
            new_post = Post(
                account=template.account,
                amount=None,
                flags=template.flags,
                note=template.note,
            )

            if template.amount is not None and not template.amount.is_null():
                if not template.amount.has_commodity() and post.amount is not None:
                    # Multiplier: multiply the matched post's amount
                    multiplier = template.amount
                    new_amount = post.amount * multiplier
                    new_post.amount = new_amount
                else:
                    # Fixed amount: copy it
                    new_post.amount = Amount(template.amount)
            else:
                new_post.amount = template.amount

            new_post.cost = template.cost
            new_post.add_flags(POST_GENERATED)
            generated.append(new_post)
        return generated

    def __repr__(self) -> str:
        return (
            f"AutomatedTransaction(predicate={self.predicate_expr!r}, "
            f"posts={len(self.posts)})"
        )


def apply_automated_transactions(journal: "Journal") -> None:
    """Apply all automated transactions in *journal* to matching postings.

    Iterates over every posting in every regular transaction.  For each
    posting that matches an automated transaction's predicate, the
    template postings are generated and appended to the owning
    transaction.

    Generated postings are marked with ``POST_GENERATED`` and their
    ``xact`` back-reference is set to the owning transaction.
    """
    if not journal.auto_xacts:
        return

    for xact in journal.xacts:
        new_posts: List[Post] = []
        # Only check original postings, not ones we generate
        original_posts = list(xact.posts)
        for post in original_posts:
            for auto_xact in journal.auto_xacts:
                if auto_xact.matches(post):
                    generated = auto_xact.apply_to(post, journal)
                    new_posts.extend(generated)
        # Add generated posts to the transaction
        for new_post in new_posts:
            xact.add_post(new_post)
