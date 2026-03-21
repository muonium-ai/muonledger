"""
Format string parser and evaluator for report output.

This module provides the ``Format`` class, a Python port of Ledger's
``format_t`` type from ``format.h`` / ``format.cc``.  Ledger uses
printf-inspired format strings to control how report lines are rendered.

A format string such as ``"%-20(account)  %12(total)\\n"`` is parsed into
a list of ``FormatElement`` objects -- some holding literal text, others
holding compiled expressions.  When the format is evaluated against a scope,
each element is rendered in sequence and the results are concatenated.

Supported syntax:
  - Literal text (passed through verbatim)
  - Backslash escapes (``\\n``, ``\\t``, etc.)
  - ``%[-][width][.maxwidth](expr)`` -- expression with optional formatting
  - ``%%`` -- literal percent sign

Width and alignment:
  - ``%20(expr)`` -- right-aligned, minimum 20 characters wide
  - ``%-20(expr)`` -- left-aligned, minimum 20 characters wide
  - ``%.20(expr)`` -- truncate to 20 characters (also sets min_width to 20)
  - ``%20.30(expr)`` -- minimum 20, maximum 30 characters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

from muonledger.expr_ast import ExprNode, OpKind
from muonledger.expr_parser import ExprParser, ParseError
from muonledger.scope import Scope, SymbolScope, CallScope
from muonledger.value import Value

__all__ = [
    "FormatElement",
    "Format",
    "FormatError",
    "ElisionStyle",
]


class FormatError(Exception):
    """Raised when a format string cannot be parsed."""


class ElisionStyle(Enum):
    """Controls how overlong strings are shortened to fit max_width."""
    TRUNCATE_TRAILING = auto()
    TRUNCATE_MIDDLE = auto()
    TRUNCATE_LEADING = auto()
    ABBREVIATE = auto()


class ElementKind(Enum):
    """Whether a format element holds literal text or a compiled expression."""
    STRING = auto()
    EXPR = auto()


# Backslash escape mapping
_ESCAPE_MAP = {
    'b': '\b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
    'v': '\v',
    '\\': '\\',
}


@dataclass
class FormatElement:
    """A single element in the parsed format string.

    Each element is either a literal STRING or a compiled EXPR.  Elements
    carry optional min_width and max_width constraints plus an alignment flag.

    Attributes
    ----------
    kind : ElementKind
        Whether this element holds literal text or an expression.
    data : str | ExprNode
        The element payload: literal string or compiled expression AST.
    min_width : int
        Minimum display width (pad with spaces if shorter).
    max_width : int
        Maximum display width (truncate if longer; 0 means unlimited).
    align_left : bool
        If True, left-justify within the min_width field.
    """
    kind: ElementKind
    data: object = None
    min_width: int = 0
    max_width: int = 0
    align_left: bool = False
    expr_text: str = ""


def _evaluate_expr(node: ExprNode, scope: Scope) -> Value:
    """Walk the AST and evaluate it against a scope.

    This is a minimal expression evaluator sufficient for the format system.
    It handles identifiers, literal values, function calls, basic arithmetic,
    string concatenation, comparisons, logical operators, ternary expressions,
    and comma lists.
    """
    if node.kind == OpKind.VALUE:
        return Value(node.value)

    if node.kind == OpKind.IDENT:
        result = scope.resolve(node.value)
        if result is None:
            return Value()
        if callable(result) and not isinstance(result, Value):
            # Call zero-arg function
            call_scope = CallScope(scope)
            return Value(result(call_scope))
        return result if isinstance(result, Value) else Value(result)

    if node.kind == OpKind.FUNCTION:
        if callable(node.value):
            call_scope = CallScope(scope)
            return Value(node.value(call_scope))
        return Value()

    if node.kind == OpKind.O_CALL:
        fn_node = node.left
        fn_result = _evaluate_expr(fn_node, scope)

        call_scope = CallScope(scope)
        if node.right is not None:
            _collect_args(node.right, scope, call_scope)

        if callable(fn_result._data if isinstance(fn_result, Value) else fn_result):
            fn = fn_result._data if isinstance(fn_result, Value) else fn_result
            return Value(fn(call_scope))

        # Try looking up as identifier for callable
        if fn_node.kind == OpKind.IDENT:
            fn = scope.resolve(fn_node.value)
            if callable(fn):
                return Value(fn(call_scope))

        return Value()

    if node.kind == OpKind.O_ADD:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return left + right

    if node.kind == OpKind.O_SUB:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return left - right

    if node.kind == OpKind.O_MUL:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return left * right

    if node.kind == OpKind.O_DIV:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return left / right

    if node.kind == OpKind.O_NEG:
        return -_evaluate_expr(node.left, scope)

    if node.kind == OpKind.O_NOT:
        val = _evaluate_expr(node.left, scope)
        return Value(not bool(val))

    if node.kind == OpKind.O_EQ:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return Value(left == right)

    if node.kind == OpKind.O_LT:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return Value(left < right)

    if node.kind == OpKind.O_LTE:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return Value(left <= right)

    if node.kind == OpKind.O_GT:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return Value(left > right)

    if node.kind == OpKind.O_GTE:
        left = _evaluate_expr(node.left, scope)
        right = _evaluate_expr(node.right, scope)
        return Value(left >= right)

    if node.kind == OpKind.O_AND:
        left = _evaluate_expr(node.left, scope)
        if not bool(left):
            return Value(False)
        right = _evaluate_expr(node.right, scope)
        return Value(bool(right))

    if node.kind == OpKind.O_OR:
        left = _evaluate_expr(node.left, scope)
        if bool(left):
            return Value(True)
        right = _evaluate_expr(node.right, scope)
        return Value(bool(right))

    if node.kind == OpKind.O_QUERY:
        cond = _evaluate_expr(node.left, scope)
        if node.right and node.right.kind == OpKind.O_COLON:
            if bool(cond):
                return _evaluate_expr(node.right.left, scope)
            else:
                return _evaluate_expr(node.right.right, scope)
        return Value()

    if node.kind == OpKind.O_CONS:
        # Comma list -- evaluate the last element (for simple cases)
        # or collect into a sequence
        left = _evaluate_expr(node.left, scope)
        if node.right is not None:
            right = _evaluate_expr(node.right, scope)
            return right
        return left

    if node.kind == OpKind.SCOPE:
        if node.left is not None:
            return _evaluate_expr(node.left, scope)
        return Value()

    if node.kind == OpKind.O_LOOKUP:
        # Member access: left.right
        left_val = _evaluate_expr(node.left, scope)
        if node.right and node.right.kind == OpKind.IDENT:
            member_name = node.right.value
            # Try to look up the member on the value
            result = scope.resolve(f"{node.left.value}.{member_name}" if node.left.kind == OpKind.IDENT else member_name)
            if result is not None:
                return result if isinstance(result, Value) else Value(result)
        return Value()

    if node.kind == OpKind.O_DEFINE:
        # Assignment
        if node.left and node.left.kind == OpKind.IDENT:
            val = _evaluate_expr(node.right, scope) if node.right else Value()
            scope.define(node.left.value, val)
            return val
        return Value()

    if node.kind == OpKind.O_SEQ:
        # Semicolon sequence -- evaluate left, then right, return right
        _evaluate_expr(node.left, scope)
        if node.right is not None:
            return _evaluate_expr(node.right, scope)
        return Value()

    return Value()


def _collect_args(node: ExprNode, scope: Scope, call_scope: CallScope) -> None:
    """Collect function call arguments from an O_CONS tree into call_scope."""
    if node.kind == OpKind.O_CONS:
        _collect_args(node.left, scope, call_scope)
        if node.right is not None:
            _collect_args(node.right, scope, call_scope)
    else:
        call_scope.push_back(_evaluate_expr(node, scope))


def _parse_expression_from_format(fmt: str, pos: int) -> tuple[ExprNode, int]:
    """Parse an expression starting after '(' in the format string.

    Returns the parsed AST node and the position after the closing ')'.
    """
    # Find the matching closing paren, respecting nesting
    depth = 1
    start = pos
    i = pos
    while i < len(fmt) and depth > 0:
        ch = fmt[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '"' or ch == "'":
            # Skip quoted strings
            quote = ch
            i += 1
            while i < len(fmt) and fmt[i] != quote:
                if fmt[i] == '\\':
                    i += 1
                i += 1
        i += 1

    if depth != 0:
        raise FormatError(f"Unmatched '(' in format string at position {start}")

    expr_text = fmt[start:i - 1]  # exclude closing paren
    if not expr_text:
        raise FormatError(f"Empty expression in format string at position {start}")

    try:
        parser = ExprParser(expr_text)
        node = parser.parse()
    except (ParseError, Exception) as e:
        raise FormatError(f"Error parsing expression '{expr_text}': {e}") from e

    return node, i  # i is past the closing paren


class Format:
    """Compiles and evaluates printf-style format strings for report output.

    A format string is parsed into a list of FormatElement objects.  When
    evaluated against a scope, each element is rendered and concatenated
    into the final output string.

    Parameters
    ----------
    fmt : str
        The format string to parse (e.g., ``"%-20(account)  %12(total)\\n"``).

    Attributes
    ----------
    elements : list[FormatElement]
        The parsed element list.
    default_style : ElisionStyle
        The truncation style used when text exceeds max_width.
    """

    default_style: ElisionStyle = ElisionStyle.TRUNCATE_TRAILING

    def __init__(self, fmt: str = "") -> None:
        self.elements: List[FormatElement] = []
        self._format_string = fmt
        if fmt:
            self._parse(fmt)

    @property
    def format_string(self) -> str:
        """Return the original format string."""
        return self._format_string

    def _parse(self, fmt: str) -> None:
        """Parse a format string into a list of FormatElement objects."""
        elements: List[FormatElement] = []
        literal_buf: List[str] = []
        i = 0

        while i < len(fmt):
            ch = fmt[i]

            if ch != '%' and ch != '\\':
                literal_buf.append(ch)
                i += 1
                continue

            # Flush any accumulated literal text
            if literal_buf:
                elements.append(FormatElement(
                    kind=ElementKind.STRING,
                    data=''.join(literal_buf),
                ))
                literal_buf.clear()

            if ch == '\\':
                # Backslash escape
                i += 1
                if i >= len(fmt):
                    elements.append(FormatElement(
                        kind=ElementKind.STRING,
                        data='\\',
                    ))
                    break

                esc_char = fmt[i]
                elements.append(FormatElement(
                    kind=ElementKind.STRING,
                    data=_ESCAPE_MAP.get(esc_char, esc_char),
                ))
                i += 1
                continue

            # ch == '%'
            i += 1
            if i >= len(fmt):
                raise FormatError("Format string ends with bare '%'")

            # Check for %%
            if fmt[i] == '%':
                elements.append(FormatElement(
                    kind=ElementKind.STRING,
                    data='%',
                ))
                i += 1
                continue

            # Parse flags
            align_left = False
            while i < len(fmt) and fmt[i] == '-':
                align_left = True
                i += 1

            # Parse min_width
            min_width = 0
            while i < len(fmt) and fmt[i].isdigit():
                min_width = min_width * 10 + int(fmt[i])
                i += 1

            # Parse max_width
            max_width = 0
            if i < len(fmt) and fmt[i] == '.':
                i += 1
                while i < len(fmt) and fmt[i].isdigit():
                    max_width = max_width * 10 + int(fmt[i])
                    i += 1

            # Now expect '('
            if i >= len(fmt):
                raise FormatError("Format string ends before expression specifier")

            if fmt[i] == '(':
                i += 1  # skip '('
                node, i = _parse_expression_from_format(fmt, i)
                elements.append(FormatElement(
                    kind=ElementKind.EXPR,
                    data=node,
                    min_width=min_width,
                    max_width=max_width,
                    align_left=align_left,
                    expr_text=fmt[fmt.rindex('(', 0, i) + 1:i - 1] if '(' in fmt[:i] else "",
                ))
            else:
                raise FormatError(
                    f"Unrecognized formatting character: {fmt[i]!r} at position {i}"
                )

        # Flush remaining literal text
        if literal_buf:
            elements.append(FormatElement(
                kind=ElementKind.STRING,
                data=''.join(literal_buf),
            ))

        self.elements = elements

    def __call__(self, scope: Scope) -> str:
        """Evaluate the format string against a scope, producing a string.

        Parameters
        ----------
        scope : Scope
            The scope providing variable bindings.

        Returns
        -------
        str
            The fully rendered output string.
        """
        return self.calc(scope)

    def calc(self, scope: Scope) -> str:
        """Evaluate the format string against a scope, producing a string."""
        parts: List[str] = []

        for elem in self.elements:
            if elem.kind == ElementKind.STRING:
                text = str(elem.data)
            elif elem.kind == ElementKind.EXPR:
                try:
                    value = _evaluate_expr(elem.data, scope)
                    text = value.to_string()
                except Exception:
                    text = ""
            else:
                text = ""

            # Apply width constraints
            if elem.max_width > 0 or elem.min_width > 0:
                text_len = len(text)

                if elem.max_width > 0 and text_len > elem.max_width:
                    text = self.truncate(text, elem.max_width)
                elif elem.min_width > 0 and text_len < elem.min_width:
                    if elem.align_left:
                        text = text.ljust(elem.min_width)
                    else:
                        text = text.rjust(elem.min_width)

            parts.append(text)

        return ''.join(parts)

    @classmethod
    def truncate(
        cls,
        text: str,
        width: int,
        style: Optional[ElisionStyle] = None,
    ) -> str:
        """Shorten a string to fit within the given display width.

        Parameters
        ----------
        text : str
            The string to truncate.
        width : int
            The target display width.
        style : ElisionStyle, optional
            Override the default truncation style.

        Returns
        -------
        str
            The truncated string, guaranteed to fit within *width* columns.
        """
        if width == 0 or len(text) <= width:
            return text

        if style is None:
            style = cls.default_style

        if style == ElisionStyle.TRUNCATE_LEADING:
            if width <= 2:
                return ".." [:width]
            return ".." + text[len(text) - (width - 2):]

        if style == ElisionStyle.TRUNCATE_MIDDLE:
            if width <= 2:
                return ".."[:width]
            left_len = (width - 2) // 2
            right_len = (width - 2) // 2 + (width - 2) % 2
            return text[:left_len] + ".." + text[len(text) - right_len:]

        # Default: TRUNCATE_TRAILING
        if width <= 2:
            return ".."[:width]
        return text[:width - 2] + ".."

    def dump(self) -> str:
        """Return a human-readable dump of all elements for debugging."""
        lines = []
        for i, elem in enumerate(self.elements):
            kind_str = "STRING" if elem.kind == ElementKind.STRING else "  EXPR"
            flags = "LEFT" if elem.align_left else "RIGHT"
            line = (
                f"Element {i}: {kind_str}  flags: {flags}"
                f"  min: {elem.min_width:2d}  max: {elem.max_width:2d}"
            )
            if elem.kind == ElementKind.STRING:
                line += f"   str: '{elem.data}'"
            else:
                line += f"  expr: {elem.expr_text}"
            lines.append(line)
        return '\n'.join(lines)

    def __repr__(self) -> str:
        return f"Format({self._format_string!r})"
