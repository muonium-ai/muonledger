"""
Polymorphic value type for the expression engine.

This module provides the ``Value`` class, a Python port of Ledger's
``value_t`` type.  A Value wraps any of the supported types (boolean,
integer, amount, balance, string, date, datetime, sequence, mask) and
performs automatic type promotion during arithmetic so that mixed-type
operations "just work".

The promotion hierarchy for numeric types is:
    INTEGER -> AMOUNT -> BALANCE

For example, adding an INTEGER Value to an AMOUNT Value first promotes
the integer to an Amount, then performs the addition.  Adding amounts
with different commodities promotes to a Balance.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import IntEnum
from typing import Any, Iterator, Optional, Union

from muonledger.amount import Amount
from muonledger.balance import Balance

__all__ = ["Value", "ValueType", "ValueError_"]


class ValueError_(Exception):
    """Raised for invalid value operations."""


class ValueType(IntEnum):
    """Type tag for the data stored inside a Value."""
    VOID = 0
    BOOLEAN = 1
    DATETIME = 2
    DATE = 3
    INTEGER = 4
    AMOUNT = 5
    BALANCE = 6
    STRING = 7
    MASK = 8
    SEQUENCE = 9


# Promotion rank for numeric types only.
_NUMERIC_RANK = {
    ValueType.INTEGER: 0,
    ValueType.AMOUNT: 1,
    ValueType.BALANCE: 2,
}


class Value:
    """Polymorphic value type with automatic type promotion.

    Wraps one of several Python types and transparently promotes during
    arithmetic and comparison so that the caller does not need to worry
    about the inner representation.

    Parameters
    ----------
    val : object
        The value to store.  The type is auto-detected:
        - ``None`` -> VOID
        - ``bool`` -> BOOLEAN  (must be checked before int!)
        - ``int`` -> INTEGER
        - ``float`` -> AMOUNT  (converted via Amount)
        - ``Amount`` -> AMOUNT
        - ``Balance`` -> BALANCE
        - ``str`` -> STRING
        - ``date`` -> DATE
        - ``datetime`` -> DATETIME
        - ``list`` -> SEQUENCE (elements wrapped in Value)
        - ``re.Pattern`` -> MASK
        - ``Value`` -> copy
    """

    __slots__ = ("_type", "_data")

    # ---- construction -------------------------------------------------------

    def __init__(self, val: Any = None) -> None:
        if val is None:
            self._type = ValueType.VOID
            self._data: Any = None
            return

        if isinstance(val, Value):
            self._type = val._type
            # Mutable types need copies
            if val._type == ValueType.SEQUENCE:
                self._data = list(val._data)
            elif val._type == ValueType.BALANCE:
                self._data = Balance(val._data)
            else:
                self._data = val._data
            return

        if isinstance(val, bool):
            self._type = ValueType.BOOLEAN
            self._data = val
            return

        if isinstance(val, int):
            self._type = ValueType.INTEGER
            self._data = val
            return

        if isinstance(val, float):
            self._type = ValueType.AMOUNT
            self._data = Amount(val)
            return

        if isinstance(val, Amount):
            self._type = ValueType.AMOUNT
            self._data = Amount(val)
            return

        if isinstance(val, Balance):
            self._type = ValueType.BALANCE
            self._data = Balance(val)
            return

        if isinstance(val, str):
            self._type = ValueType.STRING
            self._data = val
            return

        if isinstance(val, datetime):
            # datetime before date since datetime is a subclass of date
            self._type = ValueType.DATETIME
            self._data = val
            return

        if isinstance(val, date):
            self._type = ValueType.DATE
            self._data = val
            return

        if isinstance(val, list):
            self._type = ValueType.SEQUENCE
            self._data = [v if isinstance(v, Value) else Value(v) for v in val]
            return

        if isinstance(val, re.Pattern):
            self._type = ValueType.MASK
            self._data = val
            return

        raise TypeError(f"Cannot construct Value from {type(val).__name__}")

    # ---- type queries -------------------------------------------------------

    @property
    def type(self) -> ValueType:
        """Return the ValueType tag."""
        return self._type

    def is_null(self) -> bool:
        """True if the value is VOID (uninitialised)."""
        return self._type == ValueType.VOID

    def is_zero(self) -> bool:
        """True if the value is numerically zero or empty."""
        t = self._type
        if t == ValueType.VOID:
            return True
        if t == ValueType.BOOLEAN:
            return not self._data
        if t == ValueType.INTEGER:
            return self._data == 0
        if t == ValueType.AMOUNT:
            return self._data.is_zero()
        if t == ValueType.BALANCE:
            return self._data.is_zero()
        if t == ValueType.STRING:
            return len(self._data) == 0
        if t == ValueType.SEQUENCE:
            return len(self._data) == 0
        return False

    def is_nonzero(self) -> bool:
        return not self.is_zero()

    def is_realzero(self) -> bool:
        """True if the value is exactly zero (no display-precision rounding)."""
        t = self._type
        if t == ValueType.VOID:
            return True
        if t == ValueType.BOOLEAN:
            return not self._data
        if t == ValueType.INTEGER:
            return self._data == 0
        if t == ValueType.AMOUNT:
            return self._data.is_realzero()
        if t == ValueType.BALANCE:
            # A balance is realzero if empty or all components are realzero.
            return self._data.is_empty() or all(
                a.is_realzero() for a in self._data
            )
        if t == ValueType.STRING:
            return len(self._data) == 0
        if t == ValueType.SEQUENCE:
            return len(self._data) == 0
        return False

    def __bool__(self) -> bool:
        t = self._type
        if t == ValueType.VOID:
            return False
        if t == ValueType.BOOLEAN:
            return self._data
        if t == ValueType.INTEGER:
            return self._data != 0
        if t == ValueType.AMOUNT:
            return bool(self._data)
        if t == ValueType.BALANCE:
            return bool(self._data)
        if t == ValueType.STRING:
            return len(self._data) > 0
        if t == ValueType.DATE or t == ValueType.DATETIME:
            return self._data is not None
        if t == ValueType.SEQUENCE:
            # True if any element is true (matches C++ semantics).
            return any(bool(v) for v in self._data)
        if t == ValueType.MASK:
            return True
        return False

    # ---- type coercion (to_*) -----------------------------------------------

    def to_boolean(self) -> bool:
        """Convert to bool."""
        return bool(self)

    def to_int(self) -> int:
        """Convert to int."""
        t = self._type
        if t == ValueType.INTEGER:
            return self._data
        if t == ValueType.BOOLEAN:
            return 1 if self._data else 0
        if t == ValueType.AMOUNT:
            return int(self._data)
        if t == ValueType.VOID:
            return 0
        raise ValueError_(f"Cannot convert {self._type.name} to int")

    def to_long(self) -> int:
        """Convert to long (alias for to_int in Python)."""
        return self.to_int()

    def to_amount(self) -> Amount:
        """Convert to Amount."""
        t = self._type
        if t == ValueType.AMOUNT:
            return Amount(self._data)
        if t == ValueType.INTEGER:
            return Amount(self._data)
        if t == ValueType.BOOLEAN:
            return Amount(1 if self._data else 0)
        if t == ValueType.VOID:
            return Amount(0)
        raise ValueError_(f"Cannot convert {self._type.name} to Amount")

    def to_balance(self) -> Balance:
        """Convert to Balance."""
        t = self._type
        if t == ValueType.BALANCE:
            return Balance(self._data)
        if t == ValueType.AMOUNT:
            return Balance(self._data)
        if t == ValueType.INTEGER:
            return Balance(Amount(self._data))
        if t == ValueType.VOID:
            return Balance()
        raise ValueError_(f"Cannot convert {self._type.name} to Balance")

    def to_string(self) -> str:
        """Convert to str."""
        t = self._type
        if t == ValueType.STRING:
            return self._data
        if t == ValueType.VOID:
            return ""
        if t == ValueType.BOOLEAN:
            return "true" if self._data else "false"
        if t == ValueType.INTEGER:
            return str(self._data)
        if t == ValueType.AMOUNT:
            return str(self._data)
        if t == ValueType.BALANCE:
            return str(self._data)
        if t == ValueType.DATE:
            return str(self._data)
        if t == ValueType.DATETIME:
            return str(self._data)
        if t == ValueType.MASK:
            return self._data.pattern
        if t == ValueType.SEQUENCE:
            return str([str(v) for v in self._data])
        raise ValueError_(f"Cannot convert {self._type.name} to str")

    def to_date(self) -> date:
        """Convert to date."""
        t = self._type
        if t == ValueType.DATE:
            return self._data
        if t == ValueType.DATETIME:
            return self._data.date()
        raise ValueError_(f"Cannot convert {self._type.name} to date")

    def to_datetime(self) -> datetime:
        """Convert to datetime."""
        t = self._type
        if t == ValueType.DATETIME:
            return self._data
        if t == ValueType.DATE:
            return datetime(self._data.year, self._data.month, self._data.day)
        raise ValueError_(f"Cannot convert {self._type.name} to datetime")

    def to_sequence(self) -> list[Value]:
        """Convert to a list of Values."""
        t = self._type
        if t == ValueType.SEQUENCE:
            return list(self._data)
        if t == ValueType.VOID:
            return []
        # Wrap scalar in a single-element list.
        return [Value(self)]

    # ---- internal promotion helpers -----------------------------------------

    @staticmethod
    def _coerce_pair(left: Value, right: Value) -> tuple[Any, Any, ValueType]:
        """Promote two numeric Values to a common type for arithmetic.

        Returns (left_native, right_native, result_type).
        """
        lt, rt = left._type, right._type

        # Fast path: same type
        if lt == rt:
            return left._data, right._data, lt

        # Both must be numeric for promotion
        lr = _NUMERIC_RANK.get(lt)
        rr = _NUMERIC_RANK.get(rt)

        if lr is None or rr is None:
            raise ValueError_(
                f"Cannot perform arithmetic between {lt.name} and {rt.name}"
            )

        # Promote to the higher rank
        if lr < rr:
            target = rt
        else:
            target = lt

        lv = left._promote_to(target)
        rv = right._promote_to(target)
        return lv, rv, target

    def _promote_to(self, target: ValueType) -> Any:
        """Return the native data promoted to *target* type."""
        if self._type == target:
            return self._data

        if target == ValueType.INTEGER:
            return self.to_int()
        if target == ValueType.AMOUNT:
            return self.to_amount()
        if target == ValueType.BALANCE:
            return self.to_balance()

        raise ValueError_(
            f"Cannot promote {self._type.name} to {target.name}"
        )

    @staticmethod
    def _wrap(val: Any, vtype: ValueType) -> Value:
        """Wrap a native value back into a Value with the given type tag."""
        v = Value.__new__(Value)
        v._type = vtype
        v._data = val
        return v

    # ---- arithmetic ---------------------------------------------------------

    def __add__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented

        # VOID acts as identity
        if self._type == ValueType.VOID:
            return Value(other_val)
        if other_val._type == ValueType.VOID:
            return Value(self)

        # STRING concatenation
        if self._type == ValueType.STRING:
            return Value(self._data + other_val.to_string())

        # SEQUENCE + SEQUENCE -> element-wise (same length) or append
        if self._type == ValueType.SEQUENCE and other_val._type == ValueType.SEQUENCE:
            if len(self._data) == len(other_val._data):
                return Value([a + b for a, b in zip(self._data, other_val._data)])
            # Different lengths: append
            return Value(self._data + other_val._data)
        if self._type == ValueType.SEQUENCE:
            result = list(self._data)
            result.append(Value(other_val))
            return Value(result)

        # Numeric promotion
        lv, rv, rt = self._coerce_pair(self, other_val)
        if rt == ValueType.INTEGER:
            return Value(lv + rv)
        if rt == ValueType.AMOUNT:
            # If different commodities, promote to Balance
            if (isinstance(lv, Amount) and isinstance(rv, Amount)
                    and lv.has_commodity() and rv.has_commodity()
                    and lv.commodity != rv.commodity):
                bal = Balance(lv)
                bal.add(rv)
                return Value(bal)
            return Value(lv + rv)
        if rt == ValueType.BALANCE:
            return Value(lv + rv)

        raise ValueError_(f"Cannot add {self._type.name} and {other_val._type.name}")

    def __radd__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return Value(other_val).__add__(self)

    def __sub__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented

        if self._type == ValueType.VOID:
            return -Value(other_val)
        if other_val._type == ValueType.VOID:
            return Value(self)

        # SEQUENCE - SEQUENCE -> element-wise
        if self._type == ValueType.SEQUENCE and other_val._type == ValueType.SEQUENCE:
            if len(self._data) == len(other_val._data):
                return Value([a - b for a, b in zip(self._data, other_val._data)])
            raise ValueError_("Cannot subtract sequences of different lengths")

        lv, rv, rt = self._coerce_pair(self, other_val)
        if rt == ValueType.INTEGER:
            return Value(lv - rv)
        if rt == ValueType.AMOUNT:
            if (isinstance(lv, Amount) and isinstance(rv, Amount)
                    and lv.has_commodity() and rv.has_commodity()
                    and lv.commodity != rv.commodity):
                bal = Balance(lv)
                bal.subtract(rv)
                return Value(bal)
            return Value(lv - rv)
        if rt == ValueType.BALANCE:
            return Value(lv - rv)

        raise ValueError_(f"Cannot subtract {other_val._type.name} from {self._type.name}")

    def __rsub__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return Value(other_val).__sub__(self)

    def __mul__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented

        # STRING * INTEGER -> repeat
        if self._type == ValueType.STRING and other_val._type == ValueType.INTEGER:
            return Value(self._data * other_val._data)

        # For multiplication, BALANCE can only be multiplied by a scalar
        # (INTEGER or uncommoditised AMOUNT).  Don't promote both to BALANCE.
        if self._type == ValueType.BALANCE and other_val._type == ValueType.BALANCE:
            raise ValueError_("Cannot multiply two balances")
        if self._type == ValueType.BALANCE:
            # Multiply balance by scalar (keep other as Amount or int)
            if other_val._type == ValueType.INTEGER:
                return Value(self._data * other_val._data)
            if other_val._type == ValueType.AMOUNT:
                return Value(self._data * other_val._data)
            raise ValueError_(f"Cannot multiply BALANCE by {other_val._type.name}")
        if other_val._type == ValueType.BALANCE:
            if self._type == ValueType.INTEGER:
                return Value(other_val._data * self._data)
            if self._type == ValueType.AMOUNT:
                return Value(other_val._data * self._data)
            raise ValueError_(f"Cannot multiply {self._type.name} by BALANCE")

        lv, rv, rt = self._coerce_pair(self, other_val)
        if rt == ValueType.INTEGER:
            return Value(lv * rv)
        if rt == ValueType.AMOUNT:
            return Value(lv * rv)

        raise ValueError_(f"Cannot multiply {self._type.name} and {other_val._type.name}")

    def __rmul__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return Value(other_val).__mul__(self)

    def __truediv__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented

        # BALANCE can only be divided by a scalar.
        if self._type == ValueType.BALANCE and other_val._type == ValueType.BALANCE:
            raise ValueError_("Cannot divide two balances")
        if self._type == ValueType.BALANCE:
            if other_val._type == ValueType.INTEGER:
                return Value(self._data / other_val._data)
            if other_val._type == ValueType.AMOUNT:
                return Value(self._data / other_val._data)
            raise ValueError_(f"Cannot divide BALANCE by {other_val._type.name}")

        lv, rv, rt = self._coerce_pair(self, other_val)
        if rt == ValueType.INTEGER:
            if rv == 0:
                raise ValueError_("Divide by zero")
            # Integer division produces an Amount to preserve precision.
            return Value(Amount(lv) / Amount(rv))
        if rt == ValueType.AMOUNT:
            return Value(lv / rv)

        raise ValueError_(f"Cannot divide {self._type.name} by {other_val._type.name}")

    def __rtruediv__(self, other: object) -> Value:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return Value(other_val).__truediv__(self)

    # ---- unary operations ---------------------------------------------------

    def __neg__(self) -> Value:
        t = self._type
        if t == ValueType.VOID:
            return Value()
        if t == ValueType.INTEGER:
            return Value(-self._data)
        if t == ValueType.AMOUNT:
            return Value(self._data.negated())
        if t == ValueType.BALANCE:
            return Value(-self._data)
        if t == ValueType.BOOLEAN:
            return Value(not self._data)
        raise ValueError_(f"Cannot negate {self._type.name}")

    def __abs__(self) -> Value:
        t = self._type
        if t == ValueType.INTEGER:
            return Value(abs(self._data))
        if t == ValueType.AMOUNT:
            return Value(abs(self._data))
        if t == ValueType.BALANCE:
            return Value(abs(self._data))
        raise ValueError_(f"Cannot take abs of {self._type.name}")

    # ---- comparison ---------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented

        lt, rt = self._type, other_val._type
        if lt == ValueType.VOID and rt == ValueType.VOID:
            return True
        if lt == ValueType.VOID or rt == ValueType.VOID:
            return False

        # Same type fast path
        if lt == rt:
            return self._data == other_val._data

        # Cross-type numeric comparison
        lr = _NUMERIC_RANK.get(lt)
        rr = _NUMERIC_RANK.get(rt)
        if lr is not None and rr is not None:
            lv, rv, _ = self._coerce_pair(self, other_val)
            return lv == rv

        # STRING comparisons
        if lt == ValueType.STRING or rt == ValueType.STRING:
            return self.to_string() == other_val.to_string()

        return False

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    def __lt__(self, other: object) -> bool:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return self._compare(other_val) < 0

    def __le__(self, other: object) -> bool:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return self._compare(other_val) <= 0

    def __gt__(self, other: object) -> bool:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return self._compare(other_val) > 0

    def __ge__(self, other: object) -> bool:
        other_val = self._as_value(other)
        if other_val is NotImplemented:
            return NotImplemented
        return self._compare(other_val) >= 0

    def _compare(self, other: Value) -> int:
        """Three-way comparison returning -1, 0, or 1."""
        lt, rt = self._type, other._type

        if lt == rt:
            if lt == ValueType.VOID:
                return 0
            if lt == ValueType.BOOLEAN:
                return (self._data > other._data) - (self._data < other._data)
            if lt == ValueType.INTEGER:
                a, b = self._data, other._data
                return (a > b) - (a < b)
            if lt == ValueType.AMOUNT:
                return self._data.compare(other._data)
            if lt == ValueType.STRING:
                a, b = self._data, other._data
                return (a > b) - (a < b)
            if lt == ValueType.DATE or lt == ValueType.DATETIME:
                a, b = self._data, other._data
                return (a > b) - (a < b)

        # Cross-type numeric
        lr = _NUMERIC_RANK.get(lt)
        rr = _NUMERIC_RANK.get(rt)
        if lr is not None and rr is not None:
            lv, rv, target = self._coerce_pair(self, other)
            if target == ValueType.INTEGER:
                return (lv > rv) - (lv < rv)
            if target == ValueType.AMOUNT:
                return lv.compare(rv)
            # Balance comparison not well-defined; compare string forms
            return (str(lv) > str(rv)) - (str(lv) < str(rv))

        raise ValueError_(f"Cannot compare {lt.name} and {rt.name}")

    # ---- sequence operations ------------------------------------------------

    def push_back(self, val: Any) -> None:
        """Append a value to the sequence.

        If this Value is VOID, it becomes a SEQUENCE.
        If it is not already a SEQUENCE, it is wrapped into one first.
        """
        if self._type == ValueType.VOID:
            self._type = ValueType.SEQUENCE
            self._data = []
        elif self._type != ValueType.SEQUENCE:
            self._type = ValueType.SEQUENCE
            self._data = [Value(self._data)]

        self._data.append(val if isinstance(val, Value) else Value(val))

    def pop_back(self) -> None:
        """Remove the last element from the sequence."""
        if self._type == ValueType.VOID:
            raise ValueError_("Cannot pop from a VOID value")
        if self._type != ValueType.SEQUENCE:
            # Non-sequence becomes VOID when popped
            self._type = ValueType.VOID
            self._data = None
            return

        self._data.pop()
        if len(self._data) == 0:
            self._type = ValueType.VOID
            self._data = None
        elif len(self._data) == 1:
            # Unwrap single-element sequence (matches C++ behaviour)
            solo = self._data[0]
            self._type = solo._type
            self._data = solo._data

    def __len__(self) -> int:
        if self._type == ValueType.VOID:
            return 0
        if self._type == ValueType.SEQUENCE:
            return len(self._data)
        return 1

    def __getitem__(self, index: int) -> Value:
        if self._type == ValueType.SEQUENCE:
            return self._data[index]
        if index == 0:
            return self
        raise IndexError(f"Value index {index} out of range")

    def __iter__(self) -> Iterator[Value]:
        if self._type == ValueType.SEQUENCE:
            return iter(self._data)
        if self._type == ValueType.VOID:
            return iter([])
        return iter([self])

    # ---- string conversion --------------------------------------------------

    def __str__(self) -> str:
        t = self._type
        if t == ValueType.VOID:
            return ""
        if t == ValueType.BOOLEAN:
            return "true" if self._data else "false"
        if t == ValueType.INTEGER:
            return str(self._data)
        if t == ValueType.AMOUNT:
            return str(self._data)
        if t == ValueType.BALANCE:
            return str(self._data)
        if t == ValueType.STRING:
            return self._data
        if t == ValueType.DATE:
            return str(self._data)
        if t == ValueType.DATETIME:
            return str(self._data)
        if t == ValueType.MASK:
            return self._data.pattern
        if t == ValueType.SEQUENCE:
            return "(" + ", ".join(str(v) for v in self._data) + ")"
        return ""

    def __repr__(self) -> str:
        return f"Value({self._data!r})"

    def __hash__(self) -> int:
        if self._type == ValueType.VOID:
            return hash(None)
        if self._type in (ValueType.SEQUENCE, ValueType.BALANCE):
            return id(self)
        return hash((self._type, self._data))

    # ---- helper -------------------------------------------------------------

    @staticmethod
    def _as_value(other: object) -> Union[Value, type(NotImplemented)]:
        """Coerce *other* to a Value, or return NotImplemented."""
        if isinstance(other, Value):
            return other
        if isinstance(other, (bool, int, float, str, Amount, Balance,
                              date, datetime, list)):
            return Value(other)
        if isinstance(other, re.Pattern):
            return Value(other)
        return NotImplemented
