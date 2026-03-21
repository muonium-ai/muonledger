"""
Built-in functions for the Ledger expression evaluator.

This module provides the 39 built-in functions that the expression engine
makes available by default.  Call ``register_builtins(scope)`` to populate
a ``SymbolScope`` with all of them.

The functions are grouped by category:

- **Math**: abs, round/roundto, ceil, floor, min, max
- **String**: str, strip, trim, join, quoted, justify, truncated, format
- **Date**: now, today, date, format_date
- **Type conversion/query**: int, quantity, commodity, is_seq, to_amount,
  to_balance, to_string, to_int, to_date, to_boolean
- **Posting/account query**: amount, account, payee, total, display_amount,
  display_total, has_tag, tag, post, lot_date, lot_price, lot_tag
- **Boolean constants**: true, false
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import TYPE_CHECKING

from muonledger.amount import Amount
from muonledger.value import Value, ValueType

if TYPE_CHECKING:
    from muonledger.scope import CallScope, SymbolScope

__all__ = ["register_builtins"]


# ---------------------------------------------------------------------------
# Math functions
# ---------------------------------------------------------------------------

def _fn_abs(call_scope: CallScope) -> Value:
    """Return the absolute value of the argument."""
    arg = call_scope[0]
    return abs(arg)


def _fn_round(call_scope: CallScope) -> Value:
    """Round a value.  Optional second argument specifies decimal places."""
    arg = call_scope[0]
    if arg._type == ValueType.AMOUNT:
        if call_scope.has(1):
            places = call_scope[1].to_int()
            return Value(arg._data.roundto(places))
        return Value(arg._data.rounded())
    if arg._type == ValueType.INTEGER:
        if call_scope.has(1):
            places = call_scope[1].to_int()
            return Value(Amount(arg._data).roundto(places))
        return Value(arg._data)
    return arg


def _fn_ceil(call_scope: CallScope) -> Value:
    """Return the ceiling of a numeric value."""
    arg = call_scope[0]
    if arg._type == ValueType.AMOUNT:
        return Value(arg._data.ceilinged())
    if arg._type == ValueType.INTEGER:
        return Value(arg._data)
    return arg


def _fn_floor(call_scope: CallScope) -> Value:
    """Return the floor of a numeric value."""
    arg = call_scope[0]
    if arg._type == ValueType.AMOUNT:
        return Value(arg._data.floored())
    if arg._type == ValueType.INTEGER:
        return Value(arg._data)
    return arg


def _fn_min(call_scope: CallScope) -> Value:
    """Return the minimum of two values."""
    a = call_scope[0]
    b = call_scope[1]
    return Value(a) if a <= b else Value(b)


def _fn_max(call_scope: CallScope) -> Value:
    """Return the maximum of two values."""
    a = call_scope[0]
    b = call_scope[1]
    return Value(a) if a >= b else Value(b)


# ---------------------------------------------------------------------------
# String functions
# ---------------------------------------------------------------------------

def _fn_str(call_scope: CallScope) -> Value:
    """Convert a value to its string representation."""
    arg = call_scope[0]
    return Value(arg.to_string())


def _fn_strip(call_scope: CallScope) -> Value:
    """Strip leading and trailing whitespace from a string."""
    arg = call_scope[0]
    return Value(arg.to_string().strip())


def _fn_trim(call_scope: CallScope) -> Value:
    """Trim whitespace (alias for strip)."""
    return _fn_strip(call_scope)


def _fn_join(call_scope: CallScope) -> Value:
    """Join a sequence of values with a separator string."""
    arg = call_scope[0]
    sep = call_scope[1].to_string() if call_scope.has(1) else ""
    if arg._type == ValueType.SEQUENCE:
        parts = [str(v) for v in arg._data]
        return Value(sep.join(parts))
    return Value(arg.to_string())


def _fn_quoted(call_scope: CallScope) -> Value:
    """Wrap a string value in double quotes."""
    arg = call_scope[0]
    s = arg.to_string()
    return Value(f'"{s}"')


def _fn_justify(call_scope: CallScope) -> Value:
    """Left- or right-justify a string to a given width.

    justify(str, width) -- left-justify
    justify(str, width, true) -- right-justify
    """
    s = call_scope[0].to_string()
    width = call_scope[1].to_int()
    right = False
    if call_scope.has(2):
        right = call_scope[2].to_boolean()
    if right:
        return Value(s.rjust(width))
    return Value(s.ljust(width))


def _fn_truncated(call_scope: CallScope) -> Value:
    """Truncate a string to a given width, appending '..' if truncated.

    truncated(str, width)
    truncated(str, width, account_abbrev_length)
    """
    s = call_scope[0].to_string()
    width = call_scope[1].to_int()
    if width <= 0:
        return Value("")
    if len(s) <= width:
        return Value(s)
    if width <= 2:
        return Value("." * width)
    return Value(s[: width - 2] + "..")


def _fn_format(call_scope: CallScope) -> Value:
    """Format a value using a Python format string.

    format(format_str, value) -- e.g. format("%.2f", 3.14)
    """
    fmt = call_scope[0].to_string()
    val = call_scope[1]
    if val._type == ValueType.INTEGER:
        return Value(fmt % val._data)
    if val._type == ValueType.AMOUNT:
        return Value(fmt % float(val._data.quantity))
    return Value(fmt % val.to_string())


# ---------------------------------------------------------------------------
# Date functions
# ---------------------------------------------------------------------------

def _fn_now(call_scope: CallScope) -> Value:
    """Return the current datetime."""
    return Value(datetime.now())


def _fn_today(call_scope: CallScope) -> Value:
    """Return the current date."""
    return Value(date.today())


def _fn_date(call_scope: CallScope) -> Value:
    """Extract the date portion from a datetime or return a date value."""
    arg = call_scope[0]
    if arg._type == ValueType.DATETIME:
        return Value(arg._data.date())
    if arg._type == ValueType.DATE:
        return Value(arg)
    if arg._type == ValueType.STRING:
        # Try parsing common date formats
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return Value(datetime.strptime(arg._data, fmt).date())
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date from string: {arg._data}")
    return arg


def _fn_format_date(call_scope: CallScope) -> Value:
    """Format a date using a strftime format string."""
    arg = call_scope[0]
    fmt = call_scope[1].to_string()
    d = arg.to_date()
    return Value(d.strftime(fmt))


# ---------------------------------------------------------------------------
# Type conversion / query functions
# ---------------------------------------------------------------------------

def _fn_int(call_scope: CallScope) -> Value:
    """Convert a value to an integer."""
    arg = call_scope[0]
    return Value(arg.to_int())


def _fn_quantity(call_scope: CallScope) -> Value:
    """Extract the numeric quantity from an Amount."""
    arg = call_scope[0]
    if arg._type == ValueType.AMOUNT:
        return Value(Amount(arg._data.quantity))
    if arg._type == ValueType.INTEGER:
        return Value(arg._data)
    return arg


def _fn_commodity(call_scope: CallScope) -> Value:
    """Extract the commodity symbol from an Amount."""
    arg = call_scope[0]
    if arg._type == ValueType.AMOUNT:
        sym = arg._data.commodity
        return Value(sym if sym else "")
    return Value("")


def _fn_is_seq(call_scope: CallScope) -> Value:
    """Return true if the argument is a sequence."""
    arg = call_scope[0]
    return Value(arg._type == ValueType.SEQUENCE)


def _fn_to_amount(call_scope: CallScope) -> Value:
    """Convert a value to an Amount."""
    arg = call_scope[0]
    return Value(arg.to_amount())


def _fn_to_balance(call_scope: CallScope) -> Value:
    """Convert a value to a Balance."""
    arg = call_scope[0]
    return Value(arg.to_balance())


def _fn_to_string(call_scope: CallScope) -> Value:
    """Convert a value to a string."""
    return _fn_str(call_scope)


def _fn_to_int(call_scope: CallScope) -> Value:
    """Convert a value to an integer."""
    return _fn_int(call_scope)


def _fn_to_date(call_scope: CallScope) -> Value:
    """Convert a value to a date."""
    arg = call_scope[0]
    return Value(arg.to_date())


def _fn_to_boolean(call_scope: CallScope) -> Value:
    """Convert a value to a boolean."""
    arg = call_scope[0]
    return Value(arg.to_boolean())


# ---------------------------------------------------------------------------
# Posting / account query functions
#
# These are property-like accessors.  When no posting context is available
# in the scope they return sensible defaults (VOID or empty string).  The
# actual posting/account objects are expected to be supplied via scope
# symbols named ``__post__``, ``__xact__``, etc. by the reporting layer.
# ---------------------------------------------------------------------------

def _fn_amount(call_scope: CallScope) -> Value:
    """Return the posting amount from scope context."""
    result = call_scope.lookup("__post_amount__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


def _fn_account(call_scope: CallScope) -> Value:
    """Return the posting account name from scope context."""
    result = call_scope.lookup("__post_account__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value("")


def _fn_payee(call_scope: CallScope) -> Value:
    """Return the transaction payee from scope context."""
    result = call_scope.lookup("__xact_payee__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value("")


def _fn_total(call_scope: CallScope) -> Value:
    """Return the running total from scope context."""
    result = call_scope.lookup("__post_total__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


def _fn_display_amount(call_scope: CallScope) -> Value:
    """Return the display-formatted posting amount from scope context."""
    result = call_scope.lookup("__display_amount__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    # Fall back to regular amount
    return _fn_amount(call_scope)


def _fn_display_total(call_scope: CallScope) -> Value:
    """Return the display-formatted running total from scope context."""
    result = call_scope.lookup("__display_total__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    # Fall back to regular total
    return _fn_total(call_scope)


def _fn_has_tag(call_scope: CallScope) -> Value:
    """Check if the current posting has a given tag."""
    tag_name = call_scope[0].to_string()
    tags = call_scope.lookup("__post_tags__")
    if tags is not None:
        if callable(tags):
            tags = tags(call_scope)
        if isinstance(tags, Value) and tags._type == ValueType.SEQUENCE:
            for item in tags._data:
                if item.to_string() == tag_name:
                    return Value(True)
        elif isinstance(tags, dict):
            return Value(tag_name in tags)
    return Value(False)


def _fn_tag(call_scope: CallScope) -> Value:
    """Get the value of a tag on the current posting."""
    tag_name = call_scope[0].to_string()
    tags = call_scope.lookup("__post_tags__")
    if tags is not None:
        if callable(tags):
            tags = tags(call_scope)
        if isinstance(tags, dict):
            val = tags.get(tag_name)
            if val is not None:
                return Value(val) if not isinstance(val, Value) else val
    return Value()


def _fn_post(call_scope: CallScope) -> Value:
    """Return a reference to the current posting."""
    result = call_scope.lookup("__post__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


def _fn_lot_date(call_scope: CallScope) -> Value:
    """Return the lot date annotation from the posting amount."""
    result = call_scope.lookup("__lot_date__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


def _fn_lot_price(call_scope: CallScope) -> Value:
    """Return the lot price annotation from the posting amount."""
    result = call_scope.lookup("__lot_price__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


def _fn_lot_tag(call_scope: CallScope) -> Value:
    """Return the lot tag annotation from the posting amount."""
    result = call_scope.lookup("__lot_tag__")
    if result is not None:
        if callable(result):
            return result(call_scope)
        return result
    return Value()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_builtins(scope: SymbolScope) -> None:
    """Populate *scope* with all 39 built-in functions and constants.

    After calling this, the scope will contain every built-in identifier that
    the Ledger expression evaluator provides by default.
    """
    # Math
    scope.define("abs", _fn_abs)
    scope.define("round", _fn_round)
    scope.define("roundto", _fn_round)       # alias
    scope.define("ceil", _fn_ceil)
    scope.define("floor", _fn_floor)
    scope.define("min", _fn_min)
    scope.define("max", _fn_max)

    # String
    scope.define("str", _fn_str)
    scope.define("strip", _fn_strip)
    scope.define("trim", _fn_trim)
    scope.define("join", _fn_join)
    scope.define("quoted", _fn_quoted)
    scope.define("justify", _fn_justify)
    scope.define("truncated", _fn_truncated)
    scope.define("format", _fn_format)

    # Date
    scope.define("now", _fn_now)
    scope.define("today", _fn_today)
    scope.define("date", _fn_date)
    scope.define("format_date", _fn_format_date)

    # Type conversion / query
    scope.define("int", _fn_int)
    scope.define("quantity", _fn_quantity)
    scope.define("commodity", _fn_commodity)
    scope.define("is_seq", _fn_is_seq)
    scope.define("to_amount", _fn_to_amount)
    scope.define("to_balance", _fn_to_balance)
    scope.define("to_string", _fn_to_string)
    scope.define("to_int", _fn_to_int)
    scope.define("to_date", _fn_to_date)
    scope.define("to_boolean", _fn_to_boolean)

    # Posting / account query (property-like)
    scope.define("amount", _fn_amount)
    scope.define("account", _fn_account)
    scope.define("payee", _fn_payee)
    scope.define("total", _fn_total)
    scope.define("display_amount", _fn_display_amount)
    scope.define("display_total", _fn_display_total)
    scope.define("has_tag", _fn_has_tag)
    scope.define("tag", _fn_tag)
    scope.define("post", _fn_post)
    scope.define("lot_date", _fn_lot_date)
    scope.define("lot_price", _fn_lot_price)
    scope.define("lot_tag", _fn_lot_tag)

    # Boolean constants
    scope.define("true", Value(True))
    scope.define("false", Value(False))
