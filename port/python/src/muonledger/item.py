"""
Base class for all journal items (transactions and postings).

This module provides the ``Item`` class, a Python port of Ledger's
``item_t`` type.  Every entry in a journal -- whether a full transaction
or an individual posting -- inherits from Item.  This base class provides:

  - **Clearing state**: UNCLEARED, CLEARED, PENDING
  - **Dates**: a primary date and an optional auxiliary/effective date
  - **Notes and metadata**: free-form comments plus structured key/value tags
  - **Source position**: file path and line range for error reporting
  - **Flags**: bit flags for generated, temporary, inferred items
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from typing import Any, Optional


__all__ = [
    "Item",
    "ItemState",
    "Position",
    "ITEM_NORMAL",
    "ITEM_GENERATED",
    "ITEM_TEMP",
    "ITEM_NOTE_ON_NEXT_LINE",
    "ITEM_INFERRED",
]

# ---------------------------------------------------------------------------
# Item flags (matching C++ #defines)
# ---------------------------------------------------------------------------

ITEM_NORMAL = 0x00
ITEM_GENERATED = 0x01
ITEM_TEMP = 0x02
ITEM_NOTE_ON_NEXT_LINE = 0x04
ITEM_INFERRED = 0x08


# ---------------------------------------------------------------------------
# ItemState enum
# ---------------------------------------------------------------------------


class ItemState(IntEnum):
    """Clearing state for a journal item.

    In Ledger's journal syntax, a transaction or posting may carry a
    clearing mark: ``*`` for CLEARED, ``!`` for PENDING, or no mark for
    UNCLEARED.
    """

    UNCLEARED = 0
    CLEARED = 1
    PENDING = 2


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """Records the source file location of a parsed journal item.

    Attributes
    ----------
    pathname : str
        Filesystem path of the journal file.
    beg_line : int
        Line number where the item begins (1-based).
    end_line : int
        Line number where the item ends (inclusive).
    beg_pos : int
        Stream offset where the item begins.
    end_pos : int
        Stream offset just past the item's last byte.
    sequence : int
        Global parse-order sequence number.
    """

    pathname: str = ""
    beg_line: int = 0
    end_line: int = 0
    beg_pos: int = 0
    end_pos: int = 0
    sequence: int = 0


# ---------------------------------------------------------------------------
# Item base class
# ---------------------------------------------------------------------------


class Item:
    """Base class for all journal items: transactions and postings.

    Both ``Transaction`` and ``Post`` derive from ``Item``.  This class
    provides shared properties: flags, clearing state, dates, notes,
    metadata tags, and source position.

    Parameters
    ----------
    flags : int
        Bit flags (ITEM_NORMAL, ITEM_GENERATED, etc.).
    note : str | None
        Free-form note text from ``;`` comment lines.
    """

    __slots__ = (
        "flags",
        "_state",
        "_date",
        "_date_aux",
        "note",
        "_position",
        "_metadata",
    )

    def __init__(
        self,
        flags: int = ITEM_NORMAL,
        note: Optional[str] = None,
    ) -> None:
        self.flags: int = flags
        self._state: ItemState = ItemState.UNCLEARED
        self._date: Optional[date] = None
        self._date_aux: Optional[date] = None
        self.note: Optional[str] = note
        self._position: Optional[Position] = None
        self._metadata: Optional[dict[str, Any]] = None

    # ---- date properties ---------------------------------------------------

    @property
    def date(self) -> Optional[date]:
        """Primary date of the item."""
        return self._date

    @date.setter
    def date(self, value: Optional[date]) -> None:
        self._date = value

    @property
    def date_aux(self) -> Optional[date]:
        """Auxiliary (effective) date."""
        return self._date_aux

    @date_aux.setter
    def date_aux(self, value: Optional[date]) -> None:
        self._date_aux = value

    def has_date(self) -> bool:
        """Return True if a primary date is set."""
        return self._date is not None

    # ---- state property ----------------------------------------------------

    @property
    def state(self) -> ItemState:
        """Current clearing state."""
        return self._state

    @state.setter
    def state(self, value: ItemState) -> None:
        self._state = value

    # ---- position property -------------------------------------------------

    @property
    def position(self) -> Optional[Position]:
        return self._position

    @position.setter
    def position(self, value: Optional[Position]) -> None:
        self._position = value

    # ---- flag helpers ------------------------------------------------------

    def has_flags(self, flag: int) -> bool:
        """Return True if all bits in *flag* are set."""
        return (self.flags & flag) == flag

    def add_flags(self, flag: int) -> None:
        """Set the given flag bits."""
        self.flags |= flag

    def drop_flags(self, flag: int) -> None:
        """Clear the given flag bits."""
        self.flags &= ~flag

    # ---- metadata / tag system ---------------------------------------------

    def has_tag(self, tag: str) -> bool:
        """Return True if the metadata contains *tag* (case-sensitive)."""
        if self._metadata is None:
            return False
        return tag in self._metadata

    def get_tag(self, tag: str) -> Optional[Any]:
        """Return the value associated with *tag*, or None."""
        if self._metadata is None:
            return None
        return self._metadata.get(tag)

    def tag(self, tag: str) -> Optional[Any]:
        """Alias for :meth:`get_tag`."""
        return self.get_tag(tag)

    def set_tag(self, tag: str, value: Any = True) -> None:
        """Set a metadata tag.

        If *value* is not provided it defaults to ``True`` (a bare tag).
        """
        if self._metadata is None:
            self._metadata = {}
        self._metadata[tag] = value

    # ---- copy details ------------------------------------------------------

    def copy_details(self, other: Item) -> None:
        """Copy all mutable fields from *other*.

        Used by copy constructors and when duplicating postings for
        automated transactions.
        """
        self.flags = other.flags
        self._state = other._state
        self._date = other._date
        self._date_aux = other._date_aux
        self.note = other.note
        self._position = other._position
        if other._metadata is not None:
            self._metadata = dict(other._metadata)
        else:
            self._metadata = None

    # ---- description -------------------------------------------------------

    def description(self) -> str:
        if self._position is not None:
            return f"item at line {self._position.beg_line}"
        return "generated item"
