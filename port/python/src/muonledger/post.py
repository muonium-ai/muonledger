"""
Postings: the line items within transactions that affect accounts.

A posting is the fundamental unit of accounting change in Ledger.  Each
transaction contains one or more postings, and each posting records a
debit or credit to a specific account.

This module provides the ``Post`` class, a Python port of Ledger's
``post_t`` type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from muonledger.amount import Amount
from muonledger.item import ITEM_NORMAL, Item

if TYPE_CHECKING:
    from muonledger.xact import Transaction

__all__ = [
    "Post",
    "POST_VIRTUAL",
    "POST_MUST_BALANCE",
    "POST_CALCULATED",
    "POST_GENERATED",
    "POST_COST_CALCULATED",
    "POST_COST_IN_FULL",
    "POST_COST_FIXATED",
    "POST_COST_VIRTUAL",
]

# ---------------------------------------------------------------------------
# Post flags (matching C++ #defines, offset into the upper bits)
# ---------------------------------------------------------------------------

POST_VIRTUAL = 0x0010
POST_MUST_BALANCE = 0x0020
POST_CALCULATED = 0x0040
POST_GENERATED = 0x0080  # Mirrors ITEM_GENERATED usage for posts
POST_COST_CALCULATED = 0x0080
POST_COST_IN_FULL = 0x0100
POST_COST_FIXATED = 0x0200
POST_COST_VIRTUAL = 0x0400


# ---------------------------------------------------------------------------
# Post class
# ---------------------------------------------------------------------------


class Post(Item):
    """A single line item within a transaction, recording a debit or credit
    to an account.

    Parameters
    ----------
    account : object | None
        The target account this posting debits or credits.
    amount : Amount | None
        The posting amount; can be None until finalization infers it.
    flags : int
        Bit flags (ITEM_NORMAL, POST_VIRTUAL, etc.).
    note : str | None
        Free-form note text.
    """

    __slots__ = (
        "account",
        "amount",
        "cost",
        "assigned_amount",
        "_xact",
    )

    def __init__(
        self,
        account: Any = None,
        amount: Optional[Amount] = None,
        flags: int = ITEM_NORMAL,
        note: Optional[str] = None,
    ) -> None:
        super().__init__(flags=flags, note=note)
        self.account: Any = account  # Account reference (avoids circular import)
        self.amount: Optional[Amount] = amount
        self.cost: Optional[Amount] = None
        self.assigned_amount: Optional[Amount] = None
        self._xact: Optional[Transaction] = None

    # ---- transaction back-reference ----------------------------------------

    @property
    def xact(self) -> Optional[Transaction]:
        """The parent transaction that owns this posting."""
        return self._xact

    @xact.setter
    def xact(self, value: Optional[Transaction]) -> None:
        self._xact = value

    # ---- query helpers -----------------------------------------------------

    def must_balance(self) -> bool:
        """Return True if this posting participates in balance checking.

        Plain virtual postings ``(Account)`` do not need to balance.
        Real postings and balanced-virtual postings ``[Account]`` must.
        """
        if self.has_flags(POST_VIRTUAL):
            return self.has_flags(POST_MUST_BALANCE)
        return True

    def is_virtual(self) -> bool:
        """Return True if this is a virtual posting (parenthesized account)."""
        return self.has_flags(POST_VIRTUAL)

    # ---- tag inheritance ---------------------------------------------------

    def has_tag(self, tag: str, inherit: bool = True) -> bool:
        """Check whether this posting (or its parent transaction) has a tag.

        If *inherit* is True and the tag is not found on the posting,
        the parent transaction's metadata is checked as well.
        """
        if super().has_tag(tag):
            return True
        if inherit and self._xact is not None:
            return self._xact.has_tag(tag)
        return False

    def get_tag(self, tag: str, inherit: bool = True) -> Optional[Any]:
        """Retrieve a tag value, falling back to the parent transaction."""
        value = super().get_tag(tag)
        if value is not None:
            return value
        if inherit and self._xact is not None:
            return self._xact.get_tag(tag)
        return None

    # ---- description -------------------------------------------------------

    def description(self) -> str:
        if self._position is not None:
            return f"posting at line {self._position.beg_line}"
        return "generated posting"
