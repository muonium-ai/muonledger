"""
Multi-commodity balance for double-entry accounting.

This module provides the ``Balance`` class, a Python port of Ledger's
``balance_t`` type.  A balance holds amounts across multiple commodities
simultaneously -- something that ``Amount`` cannot do (it raises if you
add two amounts with different commodities).

Internally the amounts are stored in a dict keyed by commodity symbol.
Arithmetic operators delegate to the per-commodity Amount operations, so
all precision and rounding rules of Amount are preserved.
"""

from __future__ import annotations

from typing import Iterator, Optional, Union

from muonledger.amount import Amount, AmountError

__all__ = ["Balance", "BalanceError"]


class BalanceError(Exception):
    """Raised for invalid balance operations."""


class Balance:
    """Multi-commodity balance.

    Stores one ``Amount`` per commodity symbol.  Adding amounts of the
    same commodity accumulates them; adding amounts of different commodities
    creates separate entries.

    Parameters
    ----------
    value : Amount | Balance | dict[str, Amount] | None
        Initial value.  If an ``Amount``, the balance starts with that
        single commodity.  If a ``dict``, each entry is adopted directly.
        If another ``Balance``, a copy is made.
    """

    __slots__ = ("_amounts",)

    # ---- construction ------------------------------------------------------

    def __init__(
        self,
        value: Union[Amount, "Balance", dict[str, Amount], None] = None,
    ) -> None:
        self._amounts: dict[str, Amount] = {}

        if value is None:
            return

        if isinstance(value, Amount):
            if value.is_null():
                raise BalanceError(
                    "Cannot initialize a balance from an uninitialized amount"
                )
            if not value.is_realzero():
                key = value.commodity or ""
                self._amounts[key] = Amount(value)
            return

        if isinstance(value, Balance):
            self._amounts = {k: Amount(v) for k, v in value._amounts.items()}
            return

        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(v, Amount):
                    raise TypeError(
                        f"Expected Amount values in dict, got {type(v).__name__}"
                    )
                if not v.is_realzero():
                    self._amounts[k] = Amount(v)
            return

        raise TypeError(f"Cannot construct Balance from {type(value).__name__}")

    # ---- internal helpers --------------------------------------------------

    @staticmethod
    def _commodity_key(amt: Amount) -> str:
        """Return the dict key for an Amount's commodity."""
        return amt.commodity or ""

    def _add_amount(self, amt: Amount) -> None:
        """Add a single Amount into this balance (in-place)."""
        if amt.is_null():
            raise BalanceError(
                "Cannot add an uninitialized amount to a balance"
            )
        if amt.is_realzero():
            return

        key = self._commodity_key(amt)
        if key in self._amounts:
            self._amounts[key] = self._amounts[key] + amt
            # Remove if the result is exactly zero.
            if self._amounts[key].is_realzero():
                del self._amounts[key]
        else:
            self._amounts[key] = Amount(amt)

    def _subtract_amount(self, amt: Amount) -> None:
        """Subtract a single Amount from this balance (in-place)."""
        if amt.is_null():
            raise BalanceError(
                "Cannot subtract an uninitialized amount from a balance"
            )
        if amt.is_realzero():
            return

        key = self._commodity_key(amt)
        if key in self._amounts:
            self._amounts[key] = self._amounts[key] - amt
            if self._amounts[key].is_realzero():
                del self._amounts[key]
        else:
            self._amounts[key] = amt.negated()

    # ---- public add / subtract ---------------------------------------------

    def add(self, other: Union[Amount, "Balance"]) -> "Balance":
        """Add an Amount or Balance to this balance (in-place). Returns self."""
        if isinstance(other, Balance):
            for amt in other._amounts.values():
                self._add_amount(amt)
        elif isinstance(other, Amount):
            self._add_amount(other)
        else:
            raise TypeError(
                f"Cannot add {type(other).__name__} to a Balance"
            )
        return self

    def subtract(self, other: Union[Amount, "Balance"]) -> "Balance":
        """Subtract an Amount or Balance from this balance (in-place). Returns self."""
        if isinstance(other, Balance):
            for amt in other._amounts.values():
                self._subtract_amount(amt)
        elif isinstance(other, Amount):
            self._subtract_amount(other)
        else:
            raise TypeError(
                f"Cannot subtract {type(other).__name__} from a Balance"
            )
        return self

    # ---- in-place arithmetic operators -------------------------------------

    def __iadd__(self, other: Union[Amount, "Balance"]) -> "Balance":
        return self.add(other)

    def __isub__(self, other: Union[Amount, "Balance"]) -> "Balance":
        return self.subtract(other)

    # ---- binary arithmetic operators ---------------------------------------

    def __add__(self, other: Union[Amount, "Balance"]) -> "Balance":
        result = Balance(self)
        result.add(other)
        return result

    def __radd__(self, other: Union[Amount, int]) -> "Balance":
        # Support sum() which starts with 0.
        if isinstance(other, int) and other == 0:
            return Balance(self)
        if isinstance(other, Amount):
            result = Balance(self)
            result.add(other)
            return result
        return NotImplemented

    def __sub__(self, other: Union[Amount, "Balance"]) -> "Balance":
        result = Balance(self)
        result.subtract(other)
        return result

    def __rsub__(self, other: Union[Amount, int]) -> "Balance":
        if isinstance(other, int) and other == 0:
            return -self
        if isinstance(other, Amount):
            result = Balance(other)
            result.subtract(self)
            return result
        return NotImplemented

    def __mul__(self, other: Union[int, float, Amount]) -> "Balance":
        """Multiply all component amounts by a scalar."""
        if isinstance(other, (int, float)):
            scalar = Amount(other)
        elif isinstance(other, Amount):
            if other.has_commodity():
                raise BalanceError(
                    "Cannot multiply a balance by a commoditized amount"
                )
            scalar = other
        else:
            return NotImplemented

        result = Balance()
        for key, amt in self._amounts.items():
            product = amt * scalar
            if not product.is_realzero():
                result._amounts[key] = product
        return result

    def __rmul__(self, other: Union[int, float, Amount]) -> "Balance":
        return self.__mul__(other)

    def __truediv__(self, other: Union[int, float, Amount]) -> "Balance":
        """Divide all component amounts by a scalar."""
        if isinstance(other, (int, float)):
            scalar = Amount(other)
        elif isinstance(other, Amount):
            if other.has_commodity():
                raise BalanceError(
                    "Cannot divide a balance by a commoditized amount"
                )
            scalar = other
        else:
            return NotImplemented

        if scalar.is_realzero():
            raise BalanceError("Divide by zero")

        result = Balance()
        for key, amt in self._amounts.items():
            quotient = amt / scalar
            if not quotient.is_realzero():
                result._amounts[key] = quotient
        return result

    # ---- unary operations --------------------------------------------------

    def __neg__(self) -> "Balance":
        result = Balance()
        for key, amt in self._amounts.items():
            result._amounts[key] = amt.negated()
        return result

    def __abs__(self) -> "Balance":
        result = Balance()
        for amt in self._amounts.values():
            result.add(abs(amt))
        return result

    def negate(self) -> None:
        """Negate all component amounts in-place."""
        for key in self._amounts:
            self._amounts[key] = self._amounts[key].negated()

    def negated(self) -> "Balance":
        """Return a negated copy."""
        return -self

    # ---- truth tests -------------------------------------------------------

    def is_zero(self) -> bool:
        """True if all commodity amounts are zero (at display precision)."""
        if not self._amounts:
            return True
        return all(amt.is_zero() for amt in self._amounts.values())

    def is_empty(self) -> bool:
        """True if no amounts are stored."""
        return len(self._amounts) == 0

    def is_nonzero(self) -> bool:
        """True if any commodity amount is non-zero."""
        if not self._amounts:
            return False
        return any(amt.is_nonzero() for amt in self._amounts.values())

    def __bool__(self) -> bool:
        return self.is_nonzero()

    # ---- commodity queries -------------------------------------------------

    def single_amount(self) -> Optional[Amount]:
        """Return the Amount if exactly one commodity, else None."""
        if len(self._amounts) == 1:
            return next(iter(self._amounts.values()))
        return None

    def to_amount(self) -> Amount:
        """Convert to a single Amount.

        Raises
        ------
        BalanceError
            If the balance is empty or contains multiple commodities.
        """
        if self.is_empty():
            raise BalanceError(
                "Cannot convert an empty balance to an amount"
            )
        if len(self._amounts) == 1:
            return Amount(next(iter(self._amounts.values())))
        raise BalanceError(
            "Cannot convert a balance with multiple commodities to an amount"
        )

    def number_of_commodities(self) -> int:
        """Return the number of distinct commodities."""
        return len(self._amounts)

    def commodity_count(self) -> int:
        """Return the number of distinct commodities (alias)."""
        return len(self._amounts)

    def amounts(self) -> dict[str, Amount]:
        """Return a copy of the internal commodity-to-Amount mapping."""
        return dict(self._amounts)

    # ---- container protocol ------------------------------------------------

    def __iter__(self) -> Iterator[Amount]:
        """Iterate over the Amounts in sorted commodity order."""
        for key in sorted(self._amounts.keys()):
            yield self._amounts[key]

    def __len__(self) -> int:
        """Number of commodities in the balance."""
        return len(self._amounts)

    def __contains__(self, commodity: Union[str, None]) -> bool:
        """Check if a commodity is present."""
        key = commodity if commodity is not None else ""
        return key in self._amounts

    def __getitem__(self, commodity: Union[str, None]) -> Amount:
        """Get the Amount for a given commodity symbol."""
        key = commodity if commodity is not None else ""
        if key not in self._amounts:
            raise KeyError(f"Commodity {commodity!r} not in balance")
        return self._amounts[key]

    # ---- rounding ----------------------------------------------------------

    def round(self) -> "Balance":
        """Return a copy with all amounts rounded to their display precision."""
        result = Balance()
        for key, amt in self._amounts.items():
            result._amounts[key] = amt.rounded()
        return result

    def roundto(self, precision: int) -> "Balance":
        """Return a copy with all amounts rounded to *precision* places."""
        result = Balance()
        for key, amt in self._amounts.items():
            result._amounts[key] = amt.roundto(precision)
        return result

    # ---- stubs -------------------------------------------------------------

    def strip_annotations(self) -> "Balance":
        """Return a copy with annotations stripped (stub -- returns self copy)."""
        return Balance(self)

    # ---- comparison --------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Balance):
            return self._amounts == other._amounts
        if isinstance(other, Amount):
            if other.is_realzero():
                return self.is_empty()
            if len(self._amounts) == 1:
                key = self._commodity_key(other)
                return key in self._amounts and self._amounts[key] == other
            return False
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    # ---- string representation ---------------------------------------------

    def __str__(self) -> str:
        if not self._amounts:
            return "0"
        parts = [str(self._amounts[k]) for k in sorted(self._amounts.keys())]
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"Balance({self._amounts!r})"
