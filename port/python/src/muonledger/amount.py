"""
Exact-precision commoditized amounts for double-entry accounting.

This module provides the ``Amount`` class, a Python port of Ledger's
``amount_t`` type.  It uses ``fractions.Fraction`` for exact rational
arithmetic (mirroring GMP's ``mpq_t`` semantics) so that addition,
subtraction, multiplication, and division never introduce rounding error.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import TYPE_CHECKING, Optional, Union

from muonledger.commodity import Commodity, CommodityPool, CommodityStyle

if TYPE_CHECKING:
    pass

__all__ = ["Amount", "AmountError"]


class AmountError(Exception):
    """Raised for invalid amount operations."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Regex for quoted commodity names: "MUTUAL FUND"
_QUOTED_COMMODITY_RE = re.compile(r'"([^"]+)"')

# Characters that look like a commodity symbol when they appear as a prefix
# (non-digit, non-sign, non-whitespace, non-quote).
_PREFIX_SYMBOL_CHARS = re.compile(
    r'^([^\d\s\-+.,\'"]+|"[^"]+")'
)

_SUFFIX_SYMBOL_CHARS = re.compile(
    r'([^\d\s\-+.,\'"]+|"[^"]+")$'
)


def _count_decimal_places(numeric_str: str) -> int:
    """Return the number of decimal digits after the decimal point."""
    if "." in numeric_str:
        return len(numeric_str) - numeric_str.index(".") - 1
    return 0


def _parse_amount_string(
    text: str,
    pool: Optional[CommodityPool] = None,
) -> tuple[Fraction, int, Optional[Commodity], dict]:
    """Parse an amount string into (quantity, precision, commodity, style).

    Parameters
    ----------
    text : str
        The raw amount string (e.g., ``"$1,000.00"``, ``"10 EUR"``).
    pool : CommodityPool | None
        If provided, commodities are looked up / created in this pool and
        style information is learned.

    Returns
    -------
    quantity : Fraction
        The exact rational value.
    precision : int
        Number of decimal places parsed.
    commodity : Commodity | None
        Commodity object, or None.
    style : dict
        Dict with display style hints (prefix, separated, thousands,
        decimal_comma).
    """
    text = text.strip()
    if not text:
        raise AmountError("No quantity specified for amount")

    commodity_symbol: Optional[str] = None
    style: dict = {
        "prefix": False,
        "separated": False,
        "thousands": False,
        "decimal_comma": False,
    }

    negative = False
    rest = text

    # Handle leading sign
    if rest.startswith("-"):
        negative = True
        rest = rest[1:].lstrip()
    elif rest.startswith("+"):
        rest = rest[1:].lstrip()

    # Determine if commodity is prefix or suffix
    # Check for prefix commodity: starts with non-digit, non-sign
    first_char = rest[0] if rest else ""

    if first_char and not first_char.isdigit() and first_char not in ".":
        # Prefix commodity
        m = _PREFIX_SYMBOL_CHARS.match(rest)
        if m:
            raw_sym = m.group(1)
            commodity_symbol = raw_sym.strip('"')
            rest = rest[len(raw_sym):]
            # Check for space separation
            if rest and rest[0] == " ":
                style["separated"] = True
                rest = rest.lstrip()
            style["prefix"] = True
    else:
        # Number comes first; commodity may be suffix
        # Find where the number ends
        num_end = 0
        for i, ch in enumerate(rest):
            if ch in "0123456789.,-'":
                num_end = i + 1
            else:
                break
        else:
            num_end = len(rest)

        num_part = rest[:num_end]
        suffix_part = rest[num_end:]
        if suffix_part:
            if suffix_part[0] == " ":
                style["separated"] = True
                suffix_part = suffix_part.lstrip()
            if suffix_part:
                commodity_symbol = suffix_part.strip('"')
        rest = num_part

    # Now parse the numeric part from `rest`
    numeric_str = rest.strip()

    if not numeric_str:
        raise AmountError("No quantity specified for amount")

    # Detect decimal mark convention
    # Rules:
    #   - If both comma and period present, the LAST one is the decimal mark
    #   - Apostrophe is always a thousands separator
    #   - A single comma with >3 digits after it is a decimal mark
    #   - A trailing period with no digits after is 0 decimal places

    has_comma = "," in numeric_str
    has_period = "." in numeric_str
    has_apostrophe = "'" in numeric_str

    decimal_places = 0

    if has_comma and has_period:
        last_comma = numeric_str.rfind(",")
        last_period = numeric_str.rfind(".")
        if last_period > last_comma:
            # Period is decimal mark, comma is thousands
            style["thousands"] = True
            clean = numeric_str.replace(",", "")
            decimal_places = _count_decimal_places(clean)
        else:
            # Comma is decimal mark, period is thousands
            style["thousands"] = True
            style["decimal_comma"] = True
            clean = numeric_str.replace(".", "").replace(",", ".")
            decimal_places = _count_decimal_places(clean)
    elif has_comma:
        # Determine if comma is decimal or thousands
        last_comma = numeric_str.rfind(",")
        after_comma = numeric_str[last_comma + 1:]
        comma_count = numeric_str.count(",")
        # Integer part before first comma
        first_comma = numeric_str.index(",")
        int_part = numeric_str[:first_comma]

        if comma_count > 1:
            # Multiple commas = thousands separators
            style["thousands"] = True
            clean = numeric_str.replace(",", "")
            decimal_places = 0
        elif len(after_comma) != 3:
            # Not exactly 3 digits after = decimal comma
            style["decimal_comma"] = True
            clean = numeric_str.replace(",", ".")
            decimal_places = len(after_comma)
        elif int_part.lstrip("-") == "0":
            # 0,xxx = decimal comma (European style)
            style["decimal_comma"] = True
            clean = numeric_str.replace(",", ".")
            decimal_places = len(after_comma)
        else:
            # Ambiguous: 3 digits after single comma. Treat as thousands.
            style["thousands"] = True
            clean = numeric_str.replace(",", "")
            decimal_places = 0
    elif has_period:
        clean = numeric_str
        decimal_places = _count_decimal_places(clean)
    elif has_apostrophe:
        style["thousands"] = True
        clean = numeric_str.replace("'", "")
        decimal_places = 0
    else:
        clean = numeric_str
        decimal_places = 0

    if has_apostrophe:
        clean = clean.replace("'", "")

    # Convert to Fraction
    try:
        quantity = Fraction(clean).limit_denominator(10**30)
        # Actually use exact conversion
        quantity = Fraction(clean)
    except (ValueError, ZeroDivisionError) as e:
        raise AmountError(f"Cannot parse numeric value: {clean!r}") from e

    if negative:
        quantity = -quantity

    # Resolve commodity through the pool (with style learning).
    commodity_obj: Optional[Commodity] = None
    if commodity_symbol is not None:
        if pool is None:
            pool = CommodityPool.get_current()
        commodity_obj = pool.learn_style(
            commodity_symbol,
            prefix=style["prefix"],
            precision=decimal_places,
            thousands=style["thousands"],
            decimal_comma=style.get("decimal_comma", False),
            separated=style["separated"],
        )

    return quantity, decimal_places, commodity_obj, style


# ---------------------------------------------------------------------------
# Amount class
# ---------------------------------------------------------------------------

def _resolve_commodity(
    value: Union[str, Commodity, None],
) -> Optional[Commodity]:
    """Convert a string or Commodity to a Commodity object (or None)."""
    if value is None:
        return None
    if isinstance(value, Commodity):
        return value
    # String -- look up or create in the current pool.
    if isinstance(value, str):
        if value == "":
            return None
        pool = CommodityPool.get_current()
        return pool.find_or_create(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Commodity")


class Amount:
    """Exact-precision commoditized amount.

    Uses ``fractions.Fraction`` for internal storage, matching the
    infinite-precision rational arithmetic of Ledger's GMP-backed
    ``amount_t``.

    Parameters
    ----------
    value : str | int | float | Fraction | Amount | None
        The value to initialise from.  Strings are parsed for an
        optional commodity symbol (prefix or suffix).
    commodity : str | None
        Explicit commodity override.  Ignored when *value* is a string
        that already contains a commodity.
    """

    #: Extra decimal places added on division to avoid precision loss.
    extend_by_digits: int = 6

    __slots__ = (
        "_quantity",
        "_precision",
        "_commodity",
        "_style",
        "_keep_precision",
    )

    # ---- construction -----------------------------------------------------

    def __init__(
        self,
        value: Union[str, int, float, Fraction, "Amount", None] = None,
        commodity: Union[str, Commodity, None] = None,
    ) -> None:
        if value is None:
            # Null / uninitialised amount
            self._quantity: Optional[Fraction] = None
            self._precision: int = 0
            self._commodity: Optional[Commodity] = None
            self._style: dict = {"prefix": False, "separated": False, "thousands": False, "decimal_comma": False}
            self._keep_precision: bool = False
            return

        if isinstance(value, Amount):
            self._quantity = value._quantity
            self._precision = value._precision
            if commodity is None:
                self._commodity = value._commodity
            else:
                self._commodity = _resolve_commodity(commodity)
            self._style = dict(value._style)
            self._keep_precision = value._keep_precision
            return

        if isinstance(value, str):
            q, prec, parsed_comm, style = _parse_amount_string(value)
            self._quantity = q
            self._precision = prec
            if parsed_comm is not None:
                self._commodity = parsed_comm
            else:
                self._commodity = _resolve_commodity(commodity)
            self._style = style
            self._keep_precision = False
            return

        if isinstance(value, int):
            self._quantity = Fraction(value)
            self._precision = 0
        elif isinstance(value, float):
            self._quantity = Fraction(value).limit_denominator(10**15)
            self._precision = self.extend_by_digits
        elif isinstance(value, Fraction):
            self._quantity = value
            self._precision = 0
        else:
            raise TypeError(f"Cannot construct Amount from {type(value).__name__}")

        self._commodity = _resolve_commodity(commodity)
        self._style = {"prefix": False, "separated": False, "thousands": False, "decimal_comma": False}
        self._keep_precision = False

    # ---- factory methods --------------------------------------------------

    @classmethod
    def exact(cls, value: str) -> "Amount":
        """Create an amount that keeps full parsed precision for display."""
        amt = cls(value)
        amt._keep_precision = True
        return amt

    # ---- null / truth tests -----------------------------------------------

    def is_null(self) -> bool:
        """True if no value has been set (uninitialised)."""
        return self._quantity is None

    def _require_quantity(self) -> Fraction:
        if self._quantity is None:
            raise AmountError("Cannot use an uninitialized amount")
        return self._quantity

    def is_realzero(self) -> bool:
        """True if the exact rational value is zero."""
        return self._require_quantity() == 0

    def is_zero(self) -> bool:
        """True if the amount displays as zero at its display precision."""
        q = self._require_quantity()
        if q == 0:
            return True
        # Round to display precision and check
        dp = self.display_precision()
        rounded = round(float(q), dp)
        return rounded == 0.0

    def is_nonzero(self) -> bool:
        return not self.is_zero()

    def __bool__(self) -> bool:
        return self.is_nonzero()

    def is_negative(self) -> bool:
        return self.sign() < 0

    def is_positive(self) -> bool:
        return self.sign() > 0

    def sign(self) -> int:
        """Return -1, 0, or 1."""
        q = self._require_quantity()
        if q > 0:
            return 1
        elif q < 0:
            return -1
        return 0

    # ---- properties -------------------------------------------------------

    @property
    def quantity(self) -> Fraction:
        """The raw Fraction value."""
        return self._require_quantity()

    @property
    def commodity(self) -> Optional[str]:
        """The commodity symbol string (for backward compatibility)."""
        if self._commodity is None:
            return None
        return self._commodity.symbol

    @commodity.setter
    def commodity(self, value: Union[str, Commodity, None]) -> None:
        self._commodity = _resolve_commodity(value)

    @property
    def commodity_ptr(self) -> Optional[Commodity]:
        """The underlying Commodity object (None if no commodity)."""
        return self._commodity

    def has_commodity(self) -> bool:
        return self._commodity is not None and self._commodity.symbol != ""

    @property
    def precision(self) -> int:
        return self._precision

    @property
    def keep_precision(self) -> bool:
        return self._keep_precision

    def display_precision(self) -> int:
        """Return the precision used for display output.

        If the amount has a commodity and the commodity's learned precision
        is greater, use that instead (matching Ledger's behaviour where the
        commodity's precision applies to all amounts of that commodity).
        When ``keep_precision`` is set, the amount's own precision is used.

        For amounts without a commodity, use 0 precision if the value is
        a whole number (matching C++ ledger's behaviour of stripping
        trailing zeros for commodity-less amounts).
        """
        if self._keep_precision:
            return self._precision
        if self._commodity is not None and self._commodity.precision > self._precision:
            return self._commodity.precision
        # For commodity-less amounts, if the value is a whole number,
        # display as integer (no decimal places).
        if self._commodity is None or self._commodity.symbol == "":
            q = self._quantity
            if q is not None and q == int(q):
                return 0
        return self._precision

    # ---- unary operations -------------------------------------------------

    def negated(self) -> "Amount":
        result = Amount(self)
        result._quantity = -self._require_quantity()
        return result

    def __neg__(self) -> "Amount":
        return self.negated()

    def __pos__(self) -> "Amount":
        return Amount(self)

    def __abs__(self) -> "Amount":
        if self.sign() < 0:
            return self.negated()
        return Amount(self)

    def abs(self) -> "Amount":
        return self.__abs__()

    def negate(self) -> "Amount":
        """Return a negated copy (same as negated())."""
        return self.negated()

    def in_place_negate(self) -> None:
        self._quantity = -self._require_quantity()

    # ---- rounding ---------------------------------------------------------

    def rounded(self) -> "Amount":
        result = Amount(self)
        result._keep_precision = False
        return result

    def in_place_round(self, precision: Optional[int] = None) -> None:
        """Round to *precision* decimal places (modifies the rational value)."""
        if precision is not None:
            self.in_place_roundto(precision)
        else:
            self._keep_precision = False

    def roundto(self, places: int) -> "Amount":
        result = Amount(self)
        result.in_place_roundto(places)
        return result

    def in_place_roundto(self, places: int) -> None:
        """Round to exactly *places* decimal digits (half away from zero)."""
        q = self._require_quantity()
        if places >= 0:
            factor = Fraction(10) ** places
        else:
            factor = Fraction(1, 10 ** (-places))

        scaled = q * factor
        # Round half away from zero
        if scaled >= 0:
            rounded_val = int(scaled + Fraction(1, 2))
        else:
            rounded_val = -int(-scaled + Fraction(1, 2))
        self._quantity = Fraction(rounded_val) / factor
        self._precision = max(places, 0)

    def truncated(self) -> "Amount":
        result = Amount(self)
        result.in_place_truncate()
        return result

    def in_place_truncate(self) -> None:
        """Truncate toward zero to display precision."""
        q = self._require_quantity()
        dp = self.display_precision()
        factor = Fraction(10) ** dp
        scaled = q * factor
        truncated_val = int(scaled)  # truncates toward zero
        self._quantity = Fraction(truncated_val) / factor

    def floored(self) -> "Amount":
        result = Amount(self)
        result.in_place_floor()
        return result

    def in_place_floor(self) -> None:
        import math
        q = self._require_quantity()
        self._quantity = Fraction(math.floor(q))

    def ceilinged(self) -> "Amount":
        result = Amount(self)
        result.in_place_ceiling()
        return result

    def in_place_ceiling(self) -> None:
        import math
        q = self._require_quantity()
        self._quantity = Fraction(math.ceil(q))

    def unrounded(self) -> "Amount":
        result = Amount(self)
        result._keep_precision = True
        return result

    def in_place_unround(self) -> None:
        self._keep_precision = True

    def round(self, precision: Optional[int] = None) -> "Amount":
        """Return a rounded copy.

        If *precision* is given, round to that many decimal places.
        Otherwise, clear the keep_precision flag (display rounding only).
        """
        if precision is not None:
            return self.roundto(precision)
        return self.rounded()

    def unround(self) -> "Amount":
        return self.unrounded()

    # ---- reduce / unreduce (stubs) ----------------------------------------

    def reduce(self) -> "Amount":
        """Return a reduced copy (no-op without commodity scaling)."""
        return Amount(self)

    def in_place_reduce(self) -> None:
        pass  # no-op without commodity scaling chains

    # ---- number (strip commodity) -----------------------------------------

    def number(self) -> "Amount":
        """Return a copy with the commodity stripped."""
        result = Amount(self)
        result._commodity = None
        return result

    def clear_commodity(self) -> None:
        """Remove the commodity from this amount (in-place)."""
        self._commodity = None

    # ---- comparison -------------------------------------------------------

    def _coerce(self, other: object) -> "Amount":
        """Coerce *other* to an Amount for binary operations."""
        if isinstance(other, Amount):
            return other
        if isinstance(other, (int, float, Fraction)):
            return Amount(other)
        return NotImplemented  # type: ignore[return-value]

    def compare(self, other: object) -> int:
        """Three-way comparison (like C++ compare)."""
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            raise TypeError(f"Cannot compare Amount with {type(other).__name__}")

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if self.has_commodity() and other_amt.has_commodity() and self._commodity != other_amt._commodity:
            raise AmountError(
                f"Cannot compare amounts with different commodities: "
                f"'{self.commodity}' and '{other_amt.commodity}'"
            )

        if lq < rq:
            return -1
        elif lq > rq:
            return 1
        return 0

    def __eq__(self, other: object) -> bool:
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        if self.is_null() and other_amt.is_null():
            return True
        if self.is_null() or other_amt.is_null():
            return False
        if self.has_commodity() and other_amt.has_commodity() and self._commodity != other_amt._commodity:
            return False
        return self._quantity == other_amt._quantity

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    def __lt__(self, other: object) -> bool:
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return self.compare(other_amt) < 0

    def __le__(self, other: object) -> bool:
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return self.compare(other_amt) <= 0

    def __gt__(self, other: object) -> bool:
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return self.compare(other_amt) > 0

    def __ge__(self, other: object) -> bool:
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return self.compare(other_amt) >= 0

    def __hash__(self) -> int:
        comm_key = self._commodity.symbol if self._commodity is not None else None
        return hash((self._quantity, comm_key))

    # ---- arithmetic -------------------------------------------------------

    def __add__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if self.has_commodity() and other_amt.has_commodity() and self._commodity != other_amt._commodity:
            raise AmountError(
                f"Adding amounts with different commodities: "
                f"'{self.commodity}' != '{other_amt.commodity}'"
            )

        result = Amount(self)
        result._quantity = lq + rq
        result._precision = max(self._precision, other_amt._precision)
        # Propagate commodity if one side has it
        if not self.has_commodity() and other_amt.has_commodity():
            result._commodity = other_amt._commodity
            result._style = dict(other_amt._style)
        return result

    def __radd__(self, other: object) -> "Amount":
        return self.__add__(other)

    def __sub__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if self.has_commodity() and other_amt.has_commodity() and self._commodity != other_amt._commodity:
            raise AmountError(
                f"Subtracting amounts with different commodities: "
                f"'{self.commodity}' != '{other_amt.commodity}'"
            )

        result = Amount(self)
        result._quantity = lq - rq
        result._precision = max(self._precision, other_amt._precision)
        if not self.has_commodity() and other_amt.has_commodity():
            result._commodity = other_amt._commodity
            result._style = dict(other_amt._style)
        return result

    def __rsub__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return other_amt.__sub__(self)

    def __mul__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        result = Amount(self)
        result._quantity = lq * rq
        result._precision = self._precision + other_amt._precision
        if not self.has_commodity() and other_amt.has_commodity():
            result._commodity = other_amt._commodity
            result._style = dict(other_amt._style)
        return result

    def __rmul__(self, other: object) -> "Amount":
        return self.__mul__(other)

    def __truediv__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if rq == 0:
            raise AmountError("Divide by zero")

        result = Amount(self)
        result._quantity = lq / rq
        result._precision = self._precision + other_amt._precision + self.extend_by_digits
        if not self.has_commodity() and other_amt.has_commodity():
            result._commodity = other_amt._commodity
            result._style = dict(other_amt._style)
        return result

    def __rtruediv__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return other_amt.__truediv__(self)

    def __floordiv__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if rq == 0:
            raise AmountError("Divide by zero")

        result = Amount(self)
        result._quantity = Fraction(int(lq / rq))
        result._precision = 0
        return result

    def __rfloordiv__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return other_amt.__floordiv__(self)

    def __mod__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented

        lq = self._require_quantity()
        rq = other_amt._require_quantity()

        if rq == 0:
            raise AmountError("Divide by zero")

        result = Amount(self)
        quotient = int(lq / rq)
        result._quantity = lq - Fraction(quotient) * rq
        result._precision = max(self._precision, other_amt._precision)
        return result

    def __rmod__(self, other: object) -> "Amount":
        other_amt = self._coerce(other)
        if other_amt is NotImplemented:
            return NotImplemented
        return other_amt.__mod__(self)

    # ---- conversion -------------------------------------------------------

    def to_double(self) -> float:
        return float(self._require_quantity())

    def to_long(self) -> int:
        return int(round(float(self._require_quantity())))

    def __float__(self) -> float:
        return self.to_double()

    def __int__(self) -> int:
        return self.to_long()

    # ---- string formatting ------------------------------------------------

    def _use_thousands(self) -> bool:
        """Whether to apply thousands separators."""
        if self._commodity is not None and self._commodity.has_flags(CommodityStyle.THOUSANDS):
            return True
        return self._style.get("thousands", False)

    def _use_decimal_comma(self) -> bool:
        """Whether to use comma as decimal point."""
        if self._commodity is not None and self._commodity.has_flags(CommodityStyle.DECIMAL_COMMA):
            return True
        return self._style.get("decimal_comma", False)

    def _format_quantity(self, prec: int) -> str:
        """Format the numeric part to *prec* decimal places."""
        q = self._require_quantity()
        if prec <= 0:
            # Integer display
            if q >= 0:
                return str(int(q + Fraction(1, 2)))
            else:
                return str(-int(-q + Fraction(1, 2)))

        factor = Fraction(10) ** prec
        scaled = q * factor
        # Round half away from zero
        if scaled >= 0:
            int_val = int(scaled + Fraction(1, 2))
        else:
            int_val = -int(-scaled + Fraction(1, 2))

        negative = int_val < 0
        int_val = abs(int_val)

        int_str = str(int_val).zfill(prec + 1)
        integer_part = int_str[:-prec]
        decimal_part = int_str[-prec:]

        # Determine thousands separator character.
        use_thousands = self._use_thousands()
        use_decimal_comma = self._use_decimal_comma()
        thousands_sep = "." if use_decimal_comma else ","
        decimal_sep = "," if use_decimal_comma else "."

        # Apply thousands separators if needed
        if use_thousands and len(integer_part) > 3:
            groups = []
            while len(integer_part) > 3:
                groups.append(integer_part[-3:])
                integer_part = integer_part[:-3]
            groups.append(integer_part)
            groups.reverse()
            integer_part = thousands_sep.join(groups)

        result = f"{integer_part}{decimal_sep}{decimal_part}"
        if negative:
            result = "-" + result
        return result

    def quantity_string(self) -> str:
        """Return the display value without commodity."""
        if self._quantity is None:
            return "<null>"
        dp = self.display_precision()
        return self._format_quantity(dp)

    def to_string(self) -> str:
        """Return the display value with commodity."""
        if self._quantity is None:
            return "<null>"
        dp = self.display_precision()
        num_str = self._format_quantity(dp)
        return self._apply_commodity(num_str)

    def to_fullstring(self) -> str:
        """Return the full-precision value with commodity."""
        if self._quantity is None:
            return "<null>"
        # Use internal precision
        prec = self._precision
        num_str = self._format_quantity(prec)
        return self._apply_commodity(num_str)

    def _apply_commodity(self, num_str: str) -> str:
        if not self.has_commodity():
            return num_str
        comm = self._commodity
        assert comm is not None

        # Determine display symbol.
        sym = comm.qualified_symbol

        # Determine separation and prefix/suffix from commodity flags.
        is_separated = comm.has_flags(CommodityStyle.SEPARATED) or self._style.get("separated", False)
        is_prefix = comm.is_prefix  # not SUFFIXED

        sep = " " if is_separated else ""
        if is_prefix:
            return f"{sym}{sep}{num_str}"
        else:
            return f"{num_str}{sep}{sym}"

    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return f"Amount({self.to_string()!r})"
