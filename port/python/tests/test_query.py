"""Tests for the query language parser (muonledger.query).

Covers:
  - Simple account matching
  - Payee matching (@)
  - Code matching (#)
  - Note matching (=)
  - Tag/meta matching (%)
  - Regex matching (/.../)
  - Boolean operators: and, or, not
  - Implicit AND between consecutive terms
  - Parenthesized grouping
  - Combined queries
  - Error handling
"""

from __future__ import annotations

import re

import pytest

from muonledger.expr_ast import ExprNode, OpKind
from muonledger.query import QueryParseError, QueryParser, parse_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_match_node(node: ExprNode, field: str, pattern_fragment: str) -> None:
    """Assert node is an O_MATCH with the given field and pattern substring."""
    assert node is not None
    assert node.kind == OpKind.O_MATCH
    assert node.left is not None
    assert node.left.kind == OpKind.IDENT
    assert node.left.value == field
    assert node.right is not None
    assert node.right.kind == OpKind.VALUE
    assert isinstance(node.right.value, re.Pattern)
    assert pattern_fragment.lower() in node.right.value.pattern.lower()


def _assert_call_node(node: ExprNode, func_name: str) -> None:
    """Assert node is an O_CALL with the given function name."""
    assert node is not None
    assert node.kind == OpKind.O_CALL
    assert node.left is not None
    assert node.left.kind == OpKind.IDENT
    assert node.left.value == func_name


# ---------------------------------------------------------------------------
# Simple account matching
# ---------------------------------------------------------------------------

class TestSimpleAccountMatch:
    def test_bare_term_matches_account(self):
        """Bare term 'Expenses' produces account =~ /Expenses/."""
        node = parse_query("Expenses")
        _assert_match_node(node, "account", "Expenses")

    def test_bare_term_case_insensitive_regex(self):
        """The regex should be compiled with IGNORECASE."""
        node = parse_query("expenses")
        assert node.right.value.flags & re.IGNORECASE

    def test_account_keyword(self):
        """'account Food' should match account names."""
        node = parse_query("account Food")
        _assert_match_node(node, "account", "Food")

    def test_empty_query_returns_none(self):
        assert parse_query("") is None
        assert parse_query("   ") is None


# ---------------------------------------------------------------------------
# Payee matching
# ---------------------------------------------------------------------------

class TestPayeeMatch:
    def test_at_prefix(self):
        """'@Grocery' matches payee containing 'Grocery'."""
        node = parse_query("@Grocery")
        _assert_match_node(node, "payee", "Grocery")

    def test_payee_keyword(self):
        """'payee Grocery' matches payee."""
        node = parse_query("payee Grocery")
        _assert_match_node(node, "payee", "Grocery")

    def test_desc_keyword(self):
        """'desc Grocery' matches payee (desc is alias for payee)."""
        node = parse_query("desc Grocery")
        _assert_match_node(node, "payee", "Grocery")


# ---------------------------------------------------------------------------
# Code matching
# ---------------------------------------------------------------------------

class TestCodeMatch:
    def test_hash_prefix(self):
        """'#1234' matches code '1234'."""
        node = parse_query("#1234")
        _assert_match_node(node, "code", "1234")

    def test_code_keyword(self):
        """'code 1234' matches code."""
        node = parse_query("code 1234")
        _assert_match_node(node, "code", "1234")


# ---------------------------------------------------------------------------
# Note matching
# ---------------------------------------------------------------------------

class TestNoteMatch:
    def test_equals_prefix(self):
        """'=vacation' matches note containing 'vacation'."""
        node = parse_query("=vacation")
        _assert_match_node(node, "note", "vacation")

    def test_note_keyword(self):
        """'note vacation' matches note."""
        node = parse_query("note vacation")
        _assert_match_node(node, "note", "vacation")


# ---------------------------------------------------------------------------
# Tag / meta matching
# ---------------------------------------------------------------------------

class TestTagMatch:
    def test_percent_prefix(self):
        """'%project' matches tag 'project' via has_tag()."""
        node = parse_query("%project")
        _assert_call_node(node, "has_tag")
        assert isinstance(node.right.value, re.Pattern)
        assert "project" in node.right.value.pattern.lower()

    def test_tag_keyword(self):
        """'tag receipt' matches tag via has_tag()."""
        node = parse_query("tag receipt")
        _assert_call_node(node, "has_tag")

    def test_meta_keyword(self):
        """'meta receipt' matches tag via has_tag()."""
        node = parse_query("meta receipt")
        _assert_call_node(node, "has_tag")


# ---------------------------------------------------------------------------
# Regex matching
# ---------------------------------------------------------------------------

class TestRegexMatch:
    def test_regex_on_account(self):
        """'/^Exp/' matches account with regex pattern."""
        node = parse_query("/^Exp/")
        _assert_match_node(node, "account", "^Exp")

    def test_regex_with_payee_prefix(self):
        """'@/store/' matches payee with regex."""
        node = parse_query("@/store/")
        _assert_match_node(node, "payee", "store")


# ---------------------------------------------------------------------------
# Boolean operators
# ---------------------------------------------------------------------------

class TestBooleanOperators:
    def test_explicit_and(self):
        """'Expenses and Food' produces O_AND node."""
        node = parse_query("Expenses and Food")
        assert node.kind == OpKind.O_AND
        _assert_match_node(node.left, "account", "Expenses")
        _assert_match_node(node.right, "account", "Food")

    def test_explicit_and_symbol(self):
        """'Expenses & Food' produces O_AND node."""
        node = parse_query("Expenses & Food")
        assert node.kind == OpKind.O_AND

    def test_explicit_or(self):
        """'Expenses or Income' produces O_OR node."""
        node = parse_query("Expenses or Income")
        assert node.kind == OpKind.O_OR
        _assert_match_node(node.left, "account", "Expenses")
        _assert_match_node(node.right, "account", "Income")

    def test_explicit_or_symbol(self):
        """'Expenses | Income' produces O_OR node."""
        node = parse_query("Expenses | Income")
        assert node.kind == OpKind.O_OR

    def test_not_operator(self):
        """'not Food' produces O_NOT node."""
        node = parse_query("not Food")
        assert node.kind == OpKind.O_NOT
        _assert_match_node(node.left, "account", "Food")

    def test_not_symbol(self):
        """'!Food' produces O_NOT node."""
        node = parse_query("!Food")
        assert node.kind == OpKind.O_NOT
        _assert_match_node(node.left, "account", "Food")

    def test_and_not_combined(self):
        """'Expenses and not Food' produces O_AND with O_NOT on right."""
        node = parse_query("Expenses and not Food")
        assert node.kind == OpKind.O_AND
        _assert_match_node(node.left, "account", "Expenses")
        assert node.right.kind == OpKind.O_NOT
        _assert_match_node(node.right.left, "account", "Food")

    def test_precedence_not_binds_tighter_than_and(self):
        """'not A and B' is '(not A) and B', not 'not (A and B)'."""
        node = parse_query("not A and B")
        assert node.kind == OpKind.O_AND
        assert node.left.kind == OpKind.O_NOT

    def test_precedence_and_binds_tighter_than_or(self):
        """'A or B and C' is 'A or (B and C)'."""
        node = parse_query("A or B and C")
        assert node.kind == OpKind.O_OR
        _assert_match_node(node.left, "account", "A")
        assert node.right.kind == OpKind.O_AND


# ---------------------------------------------------------------------------
# Implicit AND
# ---------------------------------------------------------------------------

class TestImplicitAnd:
    def test_two_bare_terms(self):
        """'Expenses Food' is implicit AND."""
        node = parse_query("Expenses Food")
        assert node.kind == OpKind.O_AND
        _assert_match_node(node.left, "account", "Expenses")
        _assert_match_node(node.right, "account", "Food")

    def test_three_bare_terms(self):
        """'A B C' chains as ((A and B) and C)."""
        node = parse_query("A B C")
        assert node.kind == OpKind.O_AND
        assert node.left.kind == OpKind.O_AND
        _assert_match_node(node.left.left, "account", "A")
        _assert_match_node(node.left.right, "account", "B")
        _assert_match_node(node.right, "account", "C")


# ---------------------------------------------------------------------------
# Parenthesized grouping
# ---------------------------------------------------------------------------

class TestParentheses:
    def test_grouped_or(self):
        """'(A or B) and C' groups the OR first."""
        node = parse_query("(A or B) and C")
        assert node.kind == OpKind.O_AND
        assert node.left.kind == OpKind.O_OR
        _assert_match_node(node.right, "account", "C")

    def test_missing_rparen_raises(self):
        with pytest.raises(QueryParseError, match="Missing '\\)'"):
            parse_query("(A or B")


# ---------------------------------------------------------------------------
# Combined queries
# ---------------------------------------------------------------------------

class TestCombinedQueries:
    def test_payee_and_account(self):
        """'@Grocery Expenses' is implicit AND of payee and account match."""
        node = parse_query("@Grocery Expenses")
        assert node.kind == OpKind.O_AND
        _assert_match_node(node.left, "payee", "Grocery")
        _assert_match_node(node.right, "account", "Expenses")

    def test_payee_and_account_explicit(self):
        """'@Grocery and Expenses' produces same structure."""
        node = parse_query("@Grocery and Expenses")
        assert node.kind == OpKind.O_AND
        _assert_match_node(node.left, "payee", "Grocery")
        _assert_match_node(node.right, "account", "Expenses")

    def test_complex_query(self):
        """'@Grocery Expenses or Income' parses with correct precedence."""
        # This is: (@Grocery AND Expenses) OR Income
        node = parse_query("@Grocery Expenses or Income")
        assert node.kind == OpKind.O_OR
        assert node.left.kind == OpKind.O_AND
        _assert_match_node(node.right, "account", "Income")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_not_without_argument(self):
        with pytest.raises(QueryParseError, match="not followed by argument"):
            parse_query("not")

    def test_and_without_right(self):
        with pytest.raises(QueryParseError, match="not followed by argument"):
            parse_query("Expenses and")

    def test_or_without_right(self):
        with pytest.raises(QueryParseError, match="not followed by argument"):
            parse_query("Expenses or")

    def test_field_prefix_without_term(self):
        with pytest.raises(QueryParseError, match="not followed by"):
            parse_query("@")

    def test_empty_regex_raises(self):
        with pytest.raises(QueryParseError, match="empty"):
            parse_query("//")


# ---------------------------------------------------------------------------
# AST structure verification
# ---------------------------------------------------------------------------

class TestASTStructure:
    def test_match_node_structure(self):
        """Verify the full structure of a simple match node."""
        node = parse_query("Expenses")
        assert node.kind == OpKind.O_MATCH
        assert node.left.kind == OpKind.IDENT
        assert node.left.value == "account"
        assert node.right.kind == OpKind.VALUE
        assert isinstance(node.right.value, re.Pattern)
        assert node.right.value.search("Expenses")
        assert node.right.value.search("expenses")  # case insensitive

    def test_meta_node_structure(self):
        """Verify has_tag() call node structure."""
        node = parse_query("%project")
        assert node.kind == OpKind.O_CALL
        assert node.left.kind == OpKind.IDENT
        assert node.left.value == "has_tag"
        assert node.right.kind == OpKind.VALUE
        assert isinstance(node.right.value, re.Pattern)
        assert node.right.value.search("project")

    def test_dump_does_not_crash(self):
        """Ensure dump() works on query-generated nodes."""
        node = parse_query("@Grocery and Expenses")
        text = node.dump()
        assert "O_AND" in text
        assert "O_MATCH" in text
