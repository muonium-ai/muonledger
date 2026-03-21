"""
AST node types for the Ledger expression engine.

This module provides the ``OpKind`` enum and ``ExprNode`` dataclass, a Python
port of Ledger's ``op_t`` type from ``op.h``.  Every parsed expression is
represented as a tree of ``ExprNode`` objects, each carrying a ``kind`` tag
that identifies it as a constant, terminal, or operator, plus a polymorphic
``value`` field for node-specific data.

The tree is processed in phases:
  1. **Parse** (``ExprParser``) -- text to AST
  2. **Compile** -- resolve identifiers, fold constants (future ticket)
  3. **Evaluate** (``calc``) -- walk the AST to produce a result (future ticket)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Iterator, Optional


__all__ = [
    "OpKind",
    "ExprNode",
]


class OpKind(Enum):
    """Discriminator for the kind of AST node an ``ExprNode`` represents.

    Mirrors ``op_t::kind_t`` from the C++ Ledger source.  The enum is
    partitioned into logical groups: constant terminals, callable terminals,
    unary operators, and binary operators.
    """

    # --- Constant Terminals ---
    PLUG = auto()       # Internal sentinel: declared-but-unassigned variable.
    VALUE = auto()      # Literal constant (integer, amount, string, date, etc.).
    IDENT = auto()      # Named identifier, resolved at compile or eval time.

    # --- Callable / Scope Terminals ---
    FUNCTION = auto()   # Native callable.
    SCOPE = auto()      # Lexical scope capture wrapping a sub-expression.

    # --- Unary Operators ---
    O_NOT = auto()      # Logical negation (``not expr`` or ``! expr``).
    O_NEG = auto()      # Arithmetic negation (``- expr``).

    # --- Comparison Operators ---
    O_EQ = auto()       # Equality test (``==``).
    O_LT = auto()       # Less than (``<``).
    O_LTE = auto()      # Less than or equal (``<=``).
    O_GT = auto()       # Greater than (``>``).
    O_GTE = auto()      # Greater than or equal (``>=``).

    # --- Logical Connectives ---
    O_AND = auto()      # Short-circuit logical AND.
    O_OR = auto()       # Short-circuit logical OR.

    # --- Arithmetic Operators ---
    O_ADD = auto()      # Addition (``+``).
    O_SUB = auto()      # Subtraction (``-``).
    O_MUL = auto()      # Multiplication (``*``).
    O_DIV = auto()      # Division (``/``).

    # --- Ternary Conditional ---
    O_QUERY = auto()    # Ternary condition (``expr ? a : b``).
    O_COLON = auto()    # Ternary branches holder.

    # --- Structural Operators ---
    O_CONS = auto()     # Comma-separated list constructor.
    O_SEQ = auto()      # Semicolon-separated sequence.

    # --- Definition / Invocation ---
    O_DEFINE = auto()   # Variable or function definition (``name = expr``).
    O_LOOKUP = auto()   # Member access / dot operator (``obj.member``).
    O_LAMBDA = auto()   # Lambda expression (``params -> body``).
    O_CALL = auto()     # Function call (``func(args)``).
    O_MATCH = auto()    # Regex match operator (``expr =~ /pattern/``).

    UNKNOWN = auto()    # Default-constructed, not yet assigned a real kind.


# Sets for classification helpers.
_UNARY_KINDS = frozenset({OpKind.O_NOT, OpKind.O_NEG})
_BINARY_KINDS = frozenset({
    OpKind.O_EQ, OpKind.O_LT, OpKind.O_LTE, OpKind.O_GT, OpKind.O_GTE,
    OpKind.O_AND, OpKind.O_OR,
    OpKind.O_ADD, OpKind.O_SUB, OpKind.O_MUL, OpKind.O_DIV,
    OpKind.O_QUERY, OpKind.O_COLON,
    OpKind.O_CONS, OpKind.O_SEQ,
    OpKind.O_DEFINE, OpKind.O_LOOKUP, OpKind.O_LAMBDA, OpKind.O_CALL,
    OpKind.O_MATCH,
})
_TERMINAL_KINDS = frozenset({
    OpKind.PLUG, OpKind.VALUE, OpKind.IDENT,
    OpKind.FUNCTION, OpKind.SCOPE,
})


@dataclass
class ExprNode:
    """A single node in the expression abstract syntax tree.

    Attributes
    ----------
    kind : OpKind
        Discriminator tag identifying this node's role in the AST.
    left : ExprNode | None
        Left child (operand) or sole operand for unary operators.
    right : ExprNode | None
        Right child for binary operators.
    value : object
        Polymorphic payload -- the active content depends on ``kind``:
        - VALUE nodes: the literal Python value (int, float, str, bool, etc.)
        - IDENT nodes: the identifier name (str)
        - FUNCTION nodes: a callable
        - Operators: None (children carry the data)
    """

    kind: OpKind
    left: Optional[ExprNode] = None
    right: Optional[ExprNode] = None
    value: Any = None

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @property
    def is_value(self) -> bool:
        """True if this node is a literal VALUE constant."""
        return self.kind == OpKind.VALUE

    @property
    def is_ident(self) -> bool:
        """True if this node is an identifier reference."""
        return self.kind == OpKind.IDENT

    @property
    def is_unary_op(self) -> bool:
        """True if this node is a unary operator."""
        return self.kind in _UNARY_KINDS

    @property
    def is_binary_op(self) -> bool:
        """True if this node is a binary operator."""
        return self.kind in _BINARY_KINDS

    @property
    def is_terminal(self) -> bool:
        """True if this node is a terminal (constant or callable)."""
        return self.kind in _TERMINAL_KINDS

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def walk(self, visitor: Callable[[ExprNode], None]) -> None:
        """Pre-order depth-first traversal calling *visitor* on each node."""
        visitor(self)
        if self.left is not None:
            self.left.walk(visitor)
        if self.right is not None:
            self.right.walk(visitor)

    def walk_post(self, visitor: Callable[[ExprNode], None]) -> None:
        """Post-order depth-first traversal calling *visitor* on each node."""
        if self.left is not None:
            self.left.walk_post(visitor)
        if self.right is not None:
            self.right.walk_post(visitor)
        visitor(self)

    def iter_nodes(self) -> Iterator[ExprNode]:
        """Yield all nodes in the tree via pre-order traversal."""
        yield self
        if self.left is not None:
            yield from self.left.iter_nodes()
        if self.right is not None:
            yield from self.right.iter_nodes()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def dump(self, depth: int = 0) -> str:
        """Return a multi-line hierarchical dump for debugging."""
        indent = "  " * depth
        parts = [f"{indent}{self.kind.name}"]
        if self.value is not None:
            parts[0] += f" ({self.value!r})"
        if self.left is not None:
            parts.append(self.left.dump(depth + 1))
        if self.right is not None:
            parts.append(self.right.dump(depth + 1))
        return "\n".join(parts)

    def __repr__(self) -> str:
        if self.kind in (OpKind.VALUE, OpKind.IDENT):
            return f"ExprNode({self.kind.name}, {self.value!r})"
        children = []
        if self.left is not None:
            children.append(f"left={self.left!r}")
        if self.right is not None:
            children.append(f"right={self.right!r}")
        if children:
            return f"ExprNode({self.kind.name}, {', '.join(children)})"
        return f"ExprNode({self.kind.name})"
