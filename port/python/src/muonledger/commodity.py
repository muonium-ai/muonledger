"""
Commodity and CommodityPool for double-entry accounting.

This module provides the ``Commodity`` and ``CommodityPool`` classes, a
Python port of Ledger's ``commodity_t`` and ``commodity_pool_t``.
Commodities represent currencies, stocks, mutual funds, and any other unit
of value.  The pool is a singleton registry that manages creation, lookup,
and style learning.

A key design principle (inherited from Ledger) is that display formatting
is *learned* from usage: the first time a commodity like "$" is seen with
two decimal places and a thousands separator, those style flags are recorded
and applied to all future output of that commodity.
"""

from __future__ import annotations

import re
from enum import IntFlag
from typing import Optional

__all__ = [
    "CommodityStyle",
    "Commodity",
    "CommodityPool",
]


# ---------------------------------------------------------------------------
# Style flags
# ---------------------------------------------------------------------------

class CommodityStyle(IntFlag):
    """Bit-flags controlling how a commodity is displayed.

    Mirrors the COMMODITY_STYLE_* constants from Ledger's commodity.h.
    """
    DEFAULTS = 0x000
    SUFFIXED = 0x001          # Symbol follows the amount (e.g., "100 EUR").
    SEPARATED = 0x002         # A space separates symbol from quantity.
    DECIMAL_COMMA = 0x004     # Use comma as decimal point (European style).
    THOUSANDS = 0x008         # Insert grouping separators (e.g., "1,000").
    NOMARKET = 0x010          # Exclude from market-price valuations.
    BUILTIN = 0x020           # Internally created (e.g., the null commodity).
    KNOWN = 0x080             # Explicitly declared via a commodity directive.
    THOUSANDS_APOSTROPHE = 0x4000  # Use apostrophe as thousands separator.


# Characters that require a symbol to be quoted (spaces, digits, operators).
_NEEDS_QUOTING = re.compile(r'[\s\d+\-*/=<>!@#%^&|?;,.\[\]{}()~]')


# ---------------------------------------------------------------------------
# Commodity
# ---------------------------------------------------------------------------

class Commodity:
    """A commodity (currency / stock / unit of value).

    Attributes
    ----------
    symbol : str
        The canonical commodity name (e.g., ``"$"``, ``"EUR"``, ``"AAPL"``).
    precision : int
        Number of decimal places for display.
    flags : CommodityStyle
        Display style flags.
    note : str | None
        Optional user-supplied note.
    """

    __slots__ = ("_symbol", "precision", "_flags", "note")

    def __init__(
        self,
        symbol: str = "",
        precision: int = 0,
        flags: CommodityStyle = CommodityStyle.DEFAULTS,
        note: Optional[str] = None,
    ) -> None:
        self._symbol = symbol
        self.precision = precision
        self._flags = flags
        self.note = note

    # ---- symbol -----------------------------------------------------------

    @property
    def symbol(self) -> str:
        return self._symbol

    # ---- flags ------------------------------------------------------------

    @property
    def flags(self) -> CommodityStyle:
        return self._flags

    @flags.setter
    def flags(self, value: CommodityStyle) -> None:
        self._flags = value

    def has_flags(self, flag: CommodityStyle) -> bool:
        """Return True if all bits in *flag* are set."""
        return (self._flags & flag) == flag

    def add_flags(self, flag: CommodityStyle) -> None:
        """Set the given flag bits."""
        self._flags = CommodityStyle(self._flags | flag)

    def drop_flags(self, flag: CommodityStyle) -> None:
        """Clear the given flag bits."""
        self._flags = CommodityStyle(self._flags & ~flag)

    # ---- derived properties -----------------------------------------------

    @property
    def is_prefix(self) -> bool:
        """True when the symbol is printed before the quantity."""
        return not self.has_flags(CommodityStyle.SUFFIXED)

    @property
    def qualified_symbol(self) -> str:
        """The symbol, quoted if it contains special characters."""
        if _NEEDS_QUOTING.search(self._symbol):
            return f'"{self._symbol}"'
        return self._symbol

    # ---- identity / equality ----------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Commodity):
            return self._symbol == other._symbol
        if isinstance(other, str):
            return self._symbol == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._symbol)

    def __repr__(self) -> str:
        return f"Commodity({self._symbol!r})"

    def __str__(self) -> str:
        return self.qualified_symbol

    def __bool__(self) -> bool:
        """A commodity is truthy unless it is the null commodity (empty symbol)."""
        return self._symbol != ""


# ---------------------------------------------------------------------------
# CommodityPool
# ---------------------------------------------------------------------------

class CommodityPool:
    """Singleton-like registry of all known commodities.

    Mirrors Ledger's ``commodity_pool_t``.  Call :meth:`find_or_create` to
    obtain a :class:`Commodity` for a given symbol string.

    Class attribute ``current_pool`` holds the process-wide default pool.
    """

    current_pool: Optional["CommodityPool"] = None

    def __init__(self) -> None:
        self._commodities: dict[str, Commodity] = {}
        self.default_commodity: Optional[Commodity] = None
        # Create the null commodity (empty symbol, builtin, nomarket).
        self.null_commodity: Commodity = self.create(
            "", flags=CommodityStyle.BUILTIN | CommodityStyle.NOMARKET
        )

    # ---- lookup / creation ------------------------------------------------

    def find(self, symbol: str) -> Optional[Commodity]:
        """Look up an existing commodity by symbol.  Returns None if not found."""
        return self._commodities.get(symbol)

    def create(
        self,
        symbol: str,
        *,
        precision: int = 0,
        flags: CommodityStyle = CommodityStyle.DEFAULTS,
        note: Optional[str] = None,
    ) -> Commodity:
        """Create a new commodity and register it in the pool.

        Raises ``ValueError`` if the symbol already exists.
        """
        if symbol in self._commodities:
            raise ValueError(f"Commodity {symbol!r} already exists in pool")
        comm = Commodity(symbol=symbol, precision=precision, flags=flags, note=note)
        self._commodities[symbol] = comm
        return comm

    def find_or_create(self, symbol: str, **kwargs) -> Commodity:
        """Look up a commodity by symbol, creating it if it does not exist."""
        comm = self.find(symbol)
        if comm is not None:
            return comm
        return self.create(symbol, **kwargs)

    # ---- style learning ---------------------------------------------------

    def learn_style(
        self,
        symbol: str,
        *,
        prefix: bool = False,
        precision: int = 0,
        thousands: bool = False,
        decimal_comma: bool = False,
        separated: bool = False,
    ) -> Commodity:
        """Record display-style information learned from a parsed amount.

        When an amount like ``$1,000.00`` is first seen, the parser calls
        this method to teach the pool that ``$`` is a prefix symbol with
        2-decimal precision and comma thousands separators.

        If the commodity already exists, the precision is updated to the
        maximum of the current and incoming values, and any new flags are
        added (flags are never removed by learning).

        Returns the commodity.
        """
        comm = self.find_or_create(symbol)

        # Build the learned flag set.
        learned = CommodityStyle.DEFAULTS
        if not prefix:
            learned |= CommodityStyle.SUFFIXED
        if separated:
            learned |= CommodityStyle.SEPARATED
        if thousands:
            learned |= CommodityStyle.THOUSANDS
        if decimal_comma:
            learned |= CommodityStyle.DECIMAL_COMMA

        # Merge: flags grow monotonically; precision takes the max.
        comm.add_flags(learned)
        if precision > comm.precision:
            comm.precision = precision

        # If the commodity was previously created without explicit prefix/suffix
        # information, ensure the SUFFIXED flag is correctly set.  If the caller
        # now says prefix=True and SUFFIXED was on by default, drop it.
        if prefix and comm.has_flags(CommodityStyle.SUFFIXED):
            # Only drop SUFFIXED if it was set by a *previous* learn_style
            # call that said suffix.  Since flags grow monotonically, we
            # special-case: if `prefix` is True, remove SUFFIXED.
            comm.drop_flags(CommodityStyle.SUFFIXED)

        return comm

    # ---- iteration --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._commodities)

    def __iter__(self):
        return iter(self._commodities.values())

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._commodities

    # ---- default pool convenience -----------------------------------------

    @classmethod
    def get_current(cls) -> "CommodityPool":
        """Return the current (global) pool, creating one if needed."""
        if cls.current_pool is None:
            cls.current_pool = CommodityPool()
        return cls.current_pool

    @classmethod
    def reset_current(cls) -> None:
        """Reset the global pool (useful in tests)."""
        cls.current_pool = None
