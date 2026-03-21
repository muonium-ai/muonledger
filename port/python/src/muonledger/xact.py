"""
Transaction class for Ledger's journal entries.

This module provides the ``Transaction`` class, a Python port of Ledger's
``xact_t`` type.  A transaction is a dated entry with a payee and two or
more postings that must balance (double-entry invariant).

The critical method is :meth:`Transaction.finalize`, which:
  1. Scans all postings, sums amounts, tracks null-amount postings
  2. Infers the missing amount if exactly one posting has a null amount
  3. Verifies that the transaction balances (sum equals zero)
"""

from __future__ import annotations

from typing import Iterator, Optional

from muonledger.amount import Amount
from muonledger.item import ITEM_INFERRED, ITEM_NORMAL, Item
from muonledger.post import POST_CALCULATED, POST_VIRTUAL, Post
from muonledger.value import Value

__all__ = ["Transaction", "BalanceError", "BalanceAssertionError"]


class BalanceAssertionError(Exception):
    """Raised when a balance assertion on a posting fails.

    A balance assertion (``= AMOUNT`` after a posting) declares what
    the running balance of the account should be after this posting.
    If the actual running balance does not match, this error is raised.
    """

    def __init__(
        self,
        message: str,
        post: Optional[Post] = None,
    ):
        self._message = message
        self._post = post
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self._message]
        post = self._post
        if post is not None:
            acct_obj = post.account
            if acct_obj is not None:
                acct = acct_obj.fullname if hasattr(acct_obj, 'fullname') else str(acct_obj)
                parts.append(f"  Account: {acct}")
            if post._position is not None:
                loc = ""
                if post._position.pathname:
                    loc += post._position.pathname + ":"
                if post._position.beg_line:
                    loc += str(post._position.beg_line)
                if loc:
                    parts.append(f"  At: {loc}")
        return "\n".join(parts)


class BalanceError(Exception):
    """Raised when a transaction does not balance.

    Includes the transaction date, payee, each posting's contribution,
    and the remaining imbalance to help users locate and fix the error.
    """

    def __init__(
        self,
        message: str,
        xact: Optional["Transaction"] = None,
    ):
        self._message = message
        self._xact = xact
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self._message]
        xact = self._xact
        if xact is not None:
            # Show date and payee
            header_parts = []
            if xact.date is not None:
                header_parts.append(str(xact.date))
            if xact.payee:
                header_parts.append(xact.payee)
            if header_parts:
                parts.append(f"  In transaction: {' '.join(header_parts)}")
            # Show each posting
            for post in xact.posts:
                acct_obj = post.account
                if acct_obj is None:
                    acct = "<unknown>"
                elif isinstance(acct_obj, str):
                    acct = acct_obj
                else:
                    acct = acct_obj.fullname
                amt_str = str(post.amount) if post.amount and not post.amount.is_null() else "<null>"
                parts.append(f"    {acct}  {amt_str}")
            # Show source location if available
            if xact.position is not None:
                loc = ""
                if xact.position.pathname:
                    loc += xact.position.pathname + ":"
                if xact.position.beg_line:
                    loc += str(xact.position.beg_line)
                if loc:
                    parts.append(f"  At: {loc}")
        return "\n".join(parts)


class Transaction(Item):
    """A regular dated transaction -- the primary journal entry.

    In journal syntax::

        2024/01/15 * (1042) Grocery Store
            Expenses:Food       $42.50
            Assets:Checking

    Here ``*`` is the clearing state (CLEARED), ``(1042)`` is the code,
    and ``Grocery Store`` is the payee.

    Parameters
    ----------
    payee : str
        The payee/description of the transaction.
    flags : int
        Bit flags.
    note : str | None
        Free-form note text.
    """

    __slots__ = ("payee", "posts", "code")

    def __init__(
        self,
        payee: str = "",
        flags: int = ITEM_NORMAL,
        note: Optional[str] = None,
    ) -> None:
        super().__init__(flags=flags, note=note)
        self.payee: str = payee
        self.posts: list[Post] = []
        self.code: Optional[str] = None

    # ---- post management ---------------------------------------------------

    def add_post(self, post: Post) -> None:
        """Add a posting to this transaction and set its back-reference."""
        post._xact = self
        self.posts.append(post)

    def remove_post(self, post: Post) -> bool:
        """Remove a posting from this transaction.

        Returns True if the post was found and removed, False otherwise.
        """
        try:
            self.posts.remove(post)
            post._xact = None
            return True
        except ValueError:
            return False

    # ---- iteration ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self.posts)

    def __iter__(self) -> Iterator[Post]:
        return iter(self.posts)

    # ---- magnitude ---------------------------------------------------------

    def magnitude(self) -> Value:
        """Compute the absolute value of the positive side of the transaction.

        Sums the cost (or amount, if no cost) of all postings with
        positive amounts.  Used in error messages to give context about
        the transaction's overall size.
        """
        mag = Value()
        for post in self.posts:
            amt = post.cost if post.cost is not None else post.amount
            if amt is not None and not amt.is_null() and amt.is_positive():
                if mag.is_null():
                    mag = Value(amt)
                else:
                    mag = mag + Value(amt)
        return mag

    # ---- finalize ----------------------------------------------------------

    def finalize(self) -> bool:
        """Finalize the transaction: infer amounts and check balance.

        This is the core of double-entry accounting enforcement.  Called
        after all postings have been added.  The algorithm:

        1. Scan all postings that must balance, accumulate their amounts.
        2. Track the single posting (if any) with a null amount.
        3. If exactly one null-amount posting exists, set its amount to
           negate the running balance (auto-balance).
        4. Verify the final balance is zero.
        5. Raise ``BalanceError`` if the transaction does not balance.

        Returns
        -------
        bool
            True if the transaction is valid, False if all amounts are
            null (indicating the transaction should be ignored).

        Raises
        ------
        BalanceError
            If the transaction does not balance or has multiple null-amount
            postings.
        """
        # Reject transactions with no postings (C++ ledger rejects these)
        if not self.posts:
            return False

        # Phase 1: Scan postings, accumulate balance, find null-amount posts.
        balance = Value()
        null_post: Optional[Post] = None

        for post in self.posts:
            if not post.must_balance():
                continue

            # Use cost if available, otherwise the posting amount.
            amt = post.cost if post.cost is not None else post.amount

            if amt is not None and not amt.is_null():
                # Add to running balance.
                reduced = amt.rounded() if amt.keep_precision else amt
                if balance.is_null():
                    balance = Value(reduced)
                else:
                    balance = balance + Value(reduced)
            elif null_post is not None:
                raise BalanceError(
                    "Only one posting with null amount allowed per transaction",
                    xact=self,
                )
            else:
                null_post = post

        # Phase 2: Infer null-amount posting.
        if null_post is not None:
            if balance.is_null() or balance.is_realzero():
                # All other amounts are null or zero; set to zero.
                null_post.amount = Amount(0)
            else:
                # Set the null posting's amount to negate the balance.
                neg_balance = -balance
                null_post.amount = neg_balance.to_amount()
            null_post.add_flags(POST_CALCULATED | ITEM_INFERRED)
            # Reset balance to zero since we just balanced it.
            balance = Value()

        # Phase 3: Final balance verification.
        if not balance.is_null() and not balance.is_zero():
            raise BalanceError(
                f"Transaction does not balance: remainder is {balance}",
                xact=self,
            )

        # Check if all amounts were null (degenerate transaction).
        all_null = all(
            post.amount is None or post.amount.is_null()
            for post in self.posts
        )
        if all_null and len(self.posts) > 0:
            return False

        return True

    # ---- description -------------------------------------------------------

    def description(self) -> str:
        if self._position is not None:
            return f"transaction at line {self._position.beg_line}"
        return "generated transaction"
