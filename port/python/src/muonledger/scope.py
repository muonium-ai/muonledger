"""
Scope hierarchy for expression variable and function resolution.

This module provides the scope chain used by the expression evaluator to
resolve identifiers.  It is a Python port of Ledger's ``scope_t`` hierarchy
from ``scope.h``.

The chain-of-responsibility pattern allows each scope in the hierarchy to
either handle a lookup itself or delegate to its parent::

    SymbolScope  -->  SymbolScope  -->  (root, no parent)
    (inner)          (outer)

Scope types:
- **Scope**: Abstract base with ``lookup(name)`` protocol.
- **ChildScope**: Delegates ``lookup`` and ``define`` to a parent.
- **SymbolScope**: Maintains a local ``dict`` mapping names to Values or
  callables, checking locally first then delegating to the parent.
- **CallScope**: Provides positional function-call arguments.
- **BindScope**: Joins two scopes -- grandchild searched first, then parent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

from muonledger.value import Value

__all__ = [
    "Scope",
    "ChildScope",
    "SymbolScope",
    "CallScope",
    "BindScope",
]


class Scope(ABC):
    """Abstract base class for all scopes in the expression evaluation chain.

    Every scope must implement ``lookup(name)`` to resolve symbol names.
    The ``define`` method is a no-op by default (most scopes delegate to a
    parent or a ``SymbolScope``).
    """

    @abstractmethod
    def lookup(self, name: str) -> Optional[Union[Value, Callable]]:
        """Resolve *name* to a Value or callable, or return ``None``."""

    def define(self, name: str, value: Union[Value, Callable]) -> None:
        """Define a symbol in this scope.  Default is a no-op."""

    def resolve(self, name: str) -> Optional[Union[Value, Callable]]:
        """Resolve *name* by walking the scope chain.

        The default implementation simply calls ``lookup``.  Subclasses with
        parent references override this to walk up the chain.
        """
        return self.lookup(name)

    def description(self) -> str:
        """Return a human-readable description of this scope (for debugging)."""
        return "<scope>"


class ChildScope(Scope):
    """A scope that delegates both ``define`` and ``lookup`` to a parent.

    This is the base class for most scope types in the hierarchy.  If a
    lookup is not handled by a derived class, it automatically propagates
    to the parent.
    """

    def __init__(self, parent: Optional[Scope] = None) -> None:
        self.parent = parent

    def lookup(self, name: str) -> Optional[Union[Value, Callable]]:
        """Delegate symbol lookup to the parent scope."""
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, value: Union[Value, Callable]) -> None:
        """Delegate symbol definition to the parent scope."""
        if self.parent is not None:
            self.parent.define(name, value)

    def resolve(self, name: str) -> Optional[Union[Value, Callable]]:
        """Resolve *name* by looking locally (via ``lookup``) then walking up."""
        result = self.lookup(name)
        if result is not None:
            return result
        if self.parent is not None:
            return self.parent.resolve(name)
        return None

    def description(self) -> str:
        if self.parent is not None:
            return self.parent.description()
        return "<child_scope>"


class SymbolScope(ChildScope):
    """A scope with a local symbol table for user-defined variables and functions.

    When ``define`` is called, the symbol is stored locally.  When ``lookup``
    is called, the local table is checked first; if the symbol is not found,
    the lookup delegates to the parent via ``ChildScope``.
    """

    def __init__(self, parent: Optional[Scope] = None) -> None:
        super().__init__(parent)
        self._symbols: Dict[str, Union[Value, Callable]] = {}

    def define(self, name: str, value: Union[Value, Callable]) -> None:
        """Define a symbol in the local table."""
        self._symbols[name] = value

    def lookup(self, name: str) -> Optional[Union[Value, Callable]]:
        """Look up in local table first, then delegate to parent."""
        result = self._symbols.get(name)
        if result is not None:
            return result
        return super().lookup(name)

    def description(self) -> str:
        if self.parent is not None:
            return self.parent.description()
        return "<symbol_scope>"


class CallScope(ChildScope):
    """Scope for function/method calls, providing positional arguments.

    When the expression engine encounters a function call, it creates a
    ``CallScope`` that holds the function arguments as a list of Values.
    """

    def __init__(self, parent: Scope, args: Optional[List[Value]] = None) -> None:
        super().__init__(parent)
        self.args: List[Value] = args if args is not None else []

    def push_back(self, val: Any) -> None:
        """Append an argument value."""
        self.args.append(val if isinstance(val, Value) else Value(val))

    def push_front(self, val: Any) -> None:
        """Prepend an argument value."""
        self.args.insert(0, val if isinstance(val, Value) else Value(val))

    def pop_back(self) -> None:
        """Remove the last argument."""
        self.args.pop()

    def __getitem__(self, index: int) -> Value:
        return self.args[index]

    def __len__(self) -> int:
        return len(self.args)

    def __iter__(self):
        return iter(self.args)

    def empty(self) -> bool:
        return len(self.args) == 0

    def has(self, index: int) -> bool:
        """Return True if argument *index* exists and is not null."""
        return index < len(self.args) and not self.args[index].is_null()

    def description(self) -> str:
        return self.parent.description() if self.parent else "<call_scope>"


class BindScope(ChildScope):
    """Joins two scopes: lookups check the grandchild first, then the parent.

    ``BindScope`` is used when evaluating an expression that needs access to
    two independent scope chains.  Lookups try the grandchild scope first;
    if not found, they fall through to the parent.  Definitions propagate
    to both scopes.
    """

    def __init__(self, parent: Scope, grandchild: Scope) -> None:
        super().__init__(parent)
        self.grandchild = grandchild

    def define(self, name: str, value: Union[Value, Callable]) -> None:
        """Propagate definitions to both parent and grandchild scopes."""
        if self.parent is not None:
            self.parent.define(name, value)
        self.grandchild.define(name, value)

    def lookup(self, name: str) -> Optional[Union[Value, Callable]]:
        """Look up in grandchild first, then fall through to parent."""
        result = self.grandchild.lookup(name)
        if result is not None:
            return result
        return super().lookup(name)

    def description(self) -> str:
        return self.grandchild.description()
