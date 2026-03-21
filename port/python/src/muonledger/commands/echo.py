"""Echo command -- evaluate an expression and print the result.

Ported from ledger's ``echo`` command.  Evaluates a Ledger expression
string and prints the result.  Useful for testing expressions.

Usage::

    muonledger echo "2 + 3"       -> 5
    muonledger echo "(4 + 6) * 2" -> 20
    muonledger echo "true"        -> true

"""

from __future__ import annotations

from datetime import date
from typing import Optional

from muonledger.amount import Amount
from muonledger.expr_ast import ExprNode, OpKind
from muonledger.expr_parser import ExprParser, ParseError
from muonledger.expr_token import TokenizeError
from muonledger.value import Value, ValueType

__all__ = ["echo_command"]


def echo_command(
    expression_str: str,
    journal=None,
    options: Optional[dict] = None,
) -> str:
    """Evaluate an expression string and return the result as text.

    Parameters
    ----------
    expression_str : str
        The expression to evaluate.
    journal : Journal | None
        Optional journal context (reserved for future use).
    options : dict | None
        Reserved for future options.

    Returns
    -------
    str
        The formatted result of the expression evaluation.
    """
    if not expression_str or not expression_str.strip():
        return "Error: empty expression\n"

    try:
        parser = ExprParser(expression_str)
        ast = parser.parse()
    except (ParseError, TokenizeError) as exc:
        return f"Error: {exc}\n"
    except Exception as exc:
        return f"Error: {exc}\n"

    try:
        result = _evaluate(ast)
    except Exception as exc:
        return f"Error evaluating expression: {exc}\n"

    return str(result) + "\n"


def _evaluate(node: ExprNode) -> Value:
    """Walk the AST and evaluate it, returning a Value.

    Supports literals, arithmetic (+, -, *, /), unary negation and
    logical not, comparisons, parenthesized grouping, and ternary
    expressions.
    """
    if node.kind == OpKind.VALUE:
        return _to_value(node.value)

    if node.kind == OpKind.IDENT:
        return _resolve_ident(node.value)

    # Unary operators
    if node.kind == OpKind.O_NEG:
        operand = _evaluate(node.left)
        return -operand

    if node.kind == OpKind.O_NOT:
        operand = _evaluate(node.left)
        if operand.is_zero():
            return Value(True)
        return Value(False)

    # Binary arithmetic
    if node.kind == OpKind.O_ADD:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return left + right

    if node.kind == OpKind.O_SUB:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return left - right

    if node.kind == OpKind.O_MUL:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return left * right

    if node.kind == OpKind.O_DIV:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return left / right

    # Comparison
    if node.kind == OpKind.O_EQ:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return Value(left == right)

    if node.kind == OpKind.O_LT:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return Value(left < right)

    if node.kind == OpKind.O_LTE:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return Value(left <= right)

    if node.kind == OpKind.O_GT:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return Value(left > right)

    if node.kind == OpKind.O_GTE:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return Value(left >= right)

    # Logical
    if node.kind == OpKind.O_AND:
        left = _evaluate(node.left)
        if left.is_zero():
            return Value(False)
        right = _evaluate(node.right)
        return Value(not right.is_zero())

    if node.kind == OpKind.O_OR:
        left = _evaluate(node.left)
        if not left.is_zero():
            return Value(True)
        right = _evaluate(node.right)
        return Value(not right.is_zero())

    # Ternary
    if node.kind == OpKind.O_QUERY:
        cond = _evaluate(node.left)
        colon = node.right
        if colon is None or colon.kind != OpKind.O_COLON:
            raise ValueError("Malformed ternary expression")
        if not cond.is_zero():
            return _evaluate(colon.left)
        return _evaluate(colon.right)

    # Sequence (semicolons) -- evaluate all, return last
    if node.kind == OpKind.O_SEQ:
        _evaluate(node.left)
        return _evaluate(node.right)

    raise ValueError(f"Unsupported expression node: {node.kind.name}")


def _to_value(raw) -> Value:
    """Convert a raw Python value from the AST into a Value."""
    if raw is None:
        return Value()
    if isinstance(raw, Value):
        return raw
    if isinstance(raw, bool):
        return Value(raw)
    if isinstance(raw, int):
        return Value(raw)
    if isinstance(raw, float):
        return Value(raw)
    if isinstance(raw, str):
        return Value(raw)
    if isinstance(raw, Amount):
        return Value(raw)
    if isinstance(raw, date):
        return Value(raw)
    return Value(raw)


def _resolve_ident(name: str) -> Value:
    """Resolve a built-in identifier name to a value."""
    lower = name.lower() if name else ""

    if lower == "today":
        return Value(date.today())
    if lower == "now":
        from datetime import datetime
        return Value(datetime.now())
    if lower == "true":
        return Value(True)
    if lower == "false":
        return Value(False)
    if lower == "null" or lower == "nil":
        return Value()

    raise ValueError(f"Unknown identifier: {name}")
