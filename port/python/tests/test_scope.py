"""Tests for the scope chain and symbol resolution."""

from __future__ import annotations

import pytest

from muonledger.scope import BindScope, CallScope, ChildScope, Scope, SymbolScope
from muonledger.value import Value


# ---------------------------------------------------------------------------
# Basic symbol lookup
# ---------------------------------------------------------------------------

class TestSymbolScope:
    def test_define_and_lookup(self):
        scope = SymbolScope()
        scope.define("amount", Value(42))
        result = scope.lookup("amount")
        assert result is not None
        assert result == Value(42)

    def test_lookup_missing_returns_none(self):
        scope = SymbolScope()
        assert scope.lookup("nonexistent") is None

    def test_define_overwrites(self):
        scope = SymbolScope()
        scope.define("x", Value(1))
        scope.define("x", Value(2))
        assert scope.lookup("x") == Value(2)

    def test_multiple_symbols(self):
        scope = SymbolScope()
        scope.define("a", Value(10))
        scope.define("b", Value(20))
        scope.define("c", Value(30))
        assert scope.lookup("a") == Value(10)
        assert scope.lookup("b") == Value(20)
        assert scope.lookup("c") == Value(30)

    def test_string_value(self):
        scope = SymbolScope()
        scope.define("payee", Value("Grocery Store"))
        result = scope.lookup("payee")
        assert result == Value("Grocery Store")


# ---------------------------------------------------------------------------
# Scope chain delegation (child -> parent)
# ---------------------------------------------------------------------------

class TestScopeChain:
    def test_child_delegates_to_parent(self):
        parent = SymbolScope()
        parent.define("total", Value(100))
        child = SymbolScope(parent)
        assert child.lookup("total") == Value(100)

    def test_resolve_walks_chain(self):
        grandparent = SymbolScope()
        grandparent.define("root_var", Value("from_root"))
        parent = SymbolScope(grandparent)
        child = SymbolScope(parent)
        assert child.resolve("root_var") == Value("from_root")

    def test_child_without_parent_returns_none(self):
        child = SymbolScope()
        assert child.lookup("anything") is None

    def test_three_level_chain(self):
        root = SymbolScope()
        root.define("global", Value(1))
        mid = SymbolScope(root)
        mid.define("session", Value(2))
        leaf = SymbolScope(mid)
        leaf.define("local", Value(3))

        assert leaf.lookup("local") == Value(3)
        assert leaf.lookup("session") == Value(2)
        assert leaf.lookup("global") == Value(1)


# ---------------------------------------------------------------------------
# Symbol shadowing
# ---------------------------------------------------------------------------

class TestShadowing:
    def test_child_shadows_parent(self):
        parent = SymbolScope()
        parent.define("x", Value(10))
        child = SymbolScope(parent)
        child.define("x", Value(20))
        assert child.lookup("x") == Value(20)
        # Parent still has original
        assert parent.lookup("x") == Value(10)

    def test_shadowing_does_not_modify_parent(self):
        parent = SymbolScope()
        parent.define("val", Value("original"))
        child = SymbolScope(parent)
        child.define("val", Value("shadowed"))
        assert parent.lookup("val") == Value("original")

    def test_unshadowed_names_still_resolve(self):
        parent = SymbolScope()
        parent.define("a", Value(1))
        parent.define("b", Value(2))
        child = SymbolScope(parent)
        child.define("a", Value(99))
        assert child.lookup("a") == Value(99)
        assert child.lookup("b") == Value(2)


# ---------------------------------------------------------------------------
# CallScope argument access
# ---------------------------------------------------------------------------

class TestCallScope:
    def test_empty_args(self):
        parent = SymbolScope()
        cs = CallScope(parent)
        assert len(cs) == 0
        assert cs.empty()

    def test_push_back(self):
        parent = SymbolScope()
        cs = CallScope(parent)
        cs.push_back(Value(42))
        cs.push_back(Value("hello"))
        assert len(cs) == 2
        assert cs[0] == Value(42)
        assert cs[1] == Value("hello")

    def test_push_front(self):
        parent = SymbolScope()
        cs = CallScope(parent)
        cs.push_back(Value(2))
        cs.push_front(Value(1))
        assert cs[0] == Value(1)
        assert cs[1] == Value(2)

    def test_pop_back(self):
        parent = SymbolScope()
        cs = CallScope(parent, [Value(1), Value(2), Value(3)])
        cs.pop_back()
        assert len(cs) == 2
        assert cs[1] == Value(2)

    def test_has(self):
        parent = SymbolScope()
        cs = CallScope(parent, [Value(10), Value()])
        assert cs.has(0) is True
        assert cs.has(1) is False   # null value
        assert cs.has(2) is False   # out of range

    def test_iteration(self):
        parent = SymbolScope()
        cs = CallScope(parent, [Value(1), Value(2), Value(3)])
        values = list(cs)
        assert len(values) == 3
        assert values[0] == Value(1)

    def test_auto_wraps_non_value(self):
        parent = SymbolScope()
        cs = CallScope(parent)
        cs.push_back(42)
        assert isinstance(cs[0], Value)
        assert cs[0] == Value(42)

    def test_delegates_lookup_to_parent(self):
        parent = SymbolScope()
        parent.define("name", Value("test"))
        cs = CallScope(parent)
        assert cs.lookup("name") == Value("test")


# ---------------------------------------------------------------------------
# SymbolScope with callables
# ---------------------------------------------------------------------------

class TestCallableSymbols:
    def test_define_callable(self):
        scope = SymbolScope()
        fn = lambda cs: Value(cs[0].to_int() * 2)
        scope.define("double", fn)
        result = scope.lookup("double")
        assert callable(result)

    def test_invoke_callable(self):
        scope = SymbolScope()
        fn = lambda cs: Value(cs[0].to_int() + cs[1].to_int())
        scope.define("add", fn)

        add_fn = scope.lookup("add")
        cs = CallScope(scope, [Value(3), Value(4)])
        assert add_fn(cs) == Value(7)

    def test_callable_in_chain(self):
        parent = SymbolScope()
        parent.define("greet", lambda cs: Value("hello"))
        child = SymbolScope(parent)
        fn = child.lookup("greet")
        assert callable(fn)
        cs = CallScope(child)
        assert fn(cs) == Value("hello")


# ---------------------------------------------------------------------------
# BindScope
# ---------------------------------------------------------------------------

class TestBindScope:
    def test_grandchild_searched_first(self):
        parent = SymbolScope()
        parent.define("x", Value(1))
        grandchild = SymbolScope()
        grandchild.define("x", Value(2))
        bound = BindScope(parent, grandchild)
        assert bound.lookup("x") == Value(2)

    def test_falls_through_to_parent(self):
        parent = SymbolScope()
        parent.define("only_in_parent", Value(99))
        grandchild = SymbolScope()
        bound = BindScope(parent, grandchild)
        assert bound.lookup("only_in_parent") == Value(99)

    def test_define_propagates_to_both(self):
        parent = SymbolScope()
        grandchild = SymbolScope()
        bound = BindScope(parent, grandchild)
        bound.define("shared", Value(42))
        assert parent.lookup("shared") == Value(42)
        assert grandchild.lookup("shared") == Value(42)

    def test_missing_returns_none(self):
        parent = SymbolScope()
        grandchild = SymbolScope()
        bound = BindScope(parent, grandchild)
        assert bound.lookup("nonexistent") is None

    def test_description_from_grandchild(self):
        parent = SymbolScope()
        grandchild = SymbolScope()
        bound = BindScope(parent, grandchild)
        assert bound.description() == grandchild.description()


# ---------------------------------------------------------------------------
# ChildScope (bare delegation)
# ---------------------------------------------------------------------------

class TestChildScope:
    def test_bare_child_delegates_define(self):
        parent = SymbolScope()
        child = ChildScope(parent)
        child.define("x", Value(5))
        assert parent.lookup("x") == Value(5)

    def test_bare_child_no_parent(self):
        child = ChildScope()
        assert child.lookup("anything") is None

    def test_description(self):
        scope = SymbolScope()
        assert scope.description() == "<symbol_scope>"
        child = ChildScope(scope)
        assert child.description() == "<symbol_scope>"
        orphan = ChildScope()
        assert orphan.description() == "<child_scope>"
