"""Tests for the expression parser (expr_ast + expr_parser)."""

from __future__ import annotations

import pytest

from muonledger.expr_ast import ExprNode, OpKind
from muonledger.expr_parser import ExprParser, ParseError, compile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(source: str) -> ExprNode:
    """Shorthand for parsing an expression string into an AST."""
    return compile(source)


# ---------------------------------------------------------------------------
# Simple literals
# ---------------------------------------------------------------------------

class TestLiterals:
    def test_integer(self):
        node = _parse("42")
        assert node.kind == OpKind.VALUE
        assert node.value == 42

    def test_float(self):
        node = _parse("3.14")
        assert node.kind == OpKind.VALUE
        assert node.value == 3.14

    def test_string_single_quote(self):
        node = _parse("'hello'")
        assert node.kind == OpKind.VALUE
        assert node.value == "hello"

    def test_string_double_quote(self):
        node = _parse('"world"')
        assert node.kind == OpKind.VALUE
        assert node.value == "world"

    def test_true(self):
        node = _parse("true")
        assert node.kind == OpKind.VALUE
        assert node.value is True

    def test_false(self):
        node = _parse("false")
        assert node.kind == OpKind.VALUE
        assert node.value is False

    def test_identifier(self):
        node = _parse("amount")
        assert node.kind == OpKind.IDENT
        assert node.value == "amount"


# ---------------------------------------------------------------------------
# Simple arithmetic
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_addition(self):
        node = _parse("1 + 2")
        assert node.kind == OpKind.O_ADD
        assert node.left.kind == OpKind.VALUE
        assert node.left.value == 1
        assert node.right.kind == OpKind.VALUE
        assert node.right.value == 2

    def test_subtraction(self):
        node = _parse("5 - 3")
        assert node.kind == OpKind.O_SUB
        assert node.left.value == 5
        assert node.right.value == 3

    def test_multiplication(self):
        node = _parse("3 * 4")
        assert node.kind == OpKind.O_MUL
        assert node.left.value == 3
        assert node.right.value == 4

    def test_division(self):
        node = _parse("10 / 2")
        assert node.kind == OpKind.O_DIV
        assert node.left.value == 10
        assert node.right.value == 2

    def test_chained_addition(self):
        # 1 + 2 + 3 -> O_ADD(O_ADD(1, 2), 3) -- left-associative
        node = _parse("1 + 2 + 3")
        assert node.kind == OpKind.O_ADD
        assert node.left.kind == OpKind.O_ADD
        assert node.left.left.value == 1
        assert node.left.right.value == 2
        assert node.right.value == 3


# ---------------------------------------------------------------------------
# Operator precedence
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_mul_before_add(self):
        # 1 + 2 * 3 -> O_ADD(1, O_MUL(2, 3))
        node = _parse("1 + 2 * 3")
        assert node.kind == OpKind.O_ADD
        assert node.left.value == 1
        assert node.right.kind == OpKind.O_MUL
        assert node.right.left.value == 2
        assert node.right.right.value == 3

    def test_mul_before_sub(self):
        # 3 * 4 + 5 -> O_ADD(O_MUL(3, 4), 5)
        node = _parse("3 * 4 + 5")
        assert node.kind == OpKind.O_ADD
        assert node.left.kind == OpKind.O_MUL
        assert node.left.left.value == 3
        assert node.left.right.value == 4
        assert node.right.value == 5

    def test_and_before_or(self):
        # a and b or c -> O_OR(O_AND(a, b), c)
        node = _parse("a and b or c")
        assert node.kind == OpKind.O_OR
        assert node.left.kind == OpKind.O_AND
        assert node.left.left.value == "a"
        assert node.left.right.value == "b"
        assert node.right.value == "c"

    def test_comparison_before_and(self):
        # x > 1 and y < 2 -> O_AND(O_GT(x,1), O_LT(y,2))
        node = _parse("x > 1 and y < 2")
        assert node.kind == OpKind.O_AND
        assert node.left.kind == OpKind.O_GT
        assert node.right.kind == OpKind.O_LT

    def test_add_before_comparison(self):
        # a + b > c -> O_GT(O_ADD(a, b), c)
        node = _parse("a + b > c")
        assert node.kind == OpKind.O_GT
        assert node.left.kind == OpKind.O_ADD


# ---------------------------------------------------------------------------
# Parentheses
# ---------------------------------------------------------------------------

class TestParentheses:
    def test_override_precedence(self):
        # (1 + 2) * 3 -> O_MUL(O_ADD(1, 2), 3)
        node = _parse("(1 + 2) * 3")
        assert node.kind == OpKind.O_MUL
        assert node.left.kind == OpKind.O_ADD
        assert node.left.left.value == 1
        assert node.left.right.value == 2
        assert node.right.value == 3

    def test_nested_parens(self):
        node = _parse("((42))")
        assert node.kind == OpKind.VALUE
        assert node.value == 42


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------

class TestUnary:
    def test_negate_literal(self):
        # Constant folding: -42 becomes VALUE(-42)
        node = _parse("-42")
        assert node.kind == OpKind.VALUE
        assert node.value == -42

    def test_negate_ident(self):
        node = _parse("-amount")
        assert node.kind == OpKind.O_NEG
        assert node.left.kind == OpKind.IDENT
        assert node.left.value == "amount"

    def test_not_literal(self):
        # Constant folding: not true becomes VALUE(False)
        node = _parse("not true")
        assert node.kind == OpKind.VALUE
        assert node.value is False

    def test_not_ident(self):
        node = _parse("not flag")
        assert node.kind == OpKind.O_NOT
        assert node.left.kind == OpKind.IDENT
        assert node.left.value == "flag"

    def test_exclamation_mark(self):
        node = _parse("!flag")
        assert node.kind == OpKind.O_NOT
        assert node.left.value == "flag"

    def test_double_negate(self):
        # --42 -> constant fold: -(-42) = 42
        node = _parse("--42")
        assert node.kind == OpKind.VALUE
        assert node.value == 42


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class TestComparison:
    def test_greater_than(self):
        node = _parse("amount > 100")
        assert node.kind == OpKind.O_GT
        assert node.left.value == "amount"
        assert node.right.value == 100

    def test_less_than(self):
        node = _parse("x < 5")
        assert node.kind == OpKind.O_LT

    def test_equality(self):
        node = _parse("a == b")
        assert node.kind == OpKind.O_EQ

    def test_not_equal(self):
        # != is desugared as O_NOT(O_EQ(...))
        node = _parse("a != b")
        assert node.kind == OpKind.O_NOT
        assert node.left.kind == OpKind.O_EQ

    def test_less_equal(self):
        node = _parse("x <= 10")
        assert node.kind == OpKind.O_LTE

    def test_greater_equal(self):
        node = _parse("x >= 10")
        assert node.kind == OpKind.O_GTE


# ---------------------------------------------------------------------------
# Logical operators
# ---------------------------------------------------------------------------

class TestLogical:
    def test_and(self):
        node = _parse("a and b")
        assert node.kind == OpKind.O_AND
        assert node.left.value == "a"
        assert node.right.value == "b"

    def test_or(self):
        node = _parse("a or b")
        assert node.kind == OpKind.O_OR
        assert node.left.value == "a"
        assert node.right.value == "b"

    def test_chained_or(self):
        # a or b or c -> O_OR(O_OR(a, b), c)
        node = _parse("a or b or c")
        assert node.kind == OpKind.O_OR
        assert node.left.kind == OpKind.O_OR
        assert node.right.value == "c"

    def test_complex_logical(self):
        # a and b or c and d -> O_OR(O_AND(a,b), O_AND(c,d))
        node = _parse("a and b or c and d")
        assert node.kind == OpKind.O_OR
        assert node.left.kind == OpKind.O_AND
        assert node.right.kind == OpKind.O_AND


# ---------------------------------------------------------------------------
# Function calls
# ---------------------------------------------------------------------------

class TestFunctionCall:
    def test_simple_call(self):
        node = _parse("abs(amount)")
        assert node.kind == OpKind.O_CALL
        assert node.left.kind == OpKind.IDENT
        assert node.left.value == "abs"
        # Right child is the parenthesized arg.
        assert node.right.kind == OpKind.IDENT
        assert node.right.value == "amount"

    def test_call_with_literal(self):
        node = _parse("round(3.14)")
        assert node.kind == OpKind.O_CALL
        assert node.left.value == "round"
        assert node.right.kind == OpKind.VALUE
        assert node.right.value == 3.14

    def test_call_with_expression_arg(self):
        node = _parse("abs(x + 1)")
        assert node.kind == OpKind.O_CALL
        assert node.right.kind == OpKind.O_ADD

    def test_call_multiple_args(self):
        # max(a, b) -> O_CALL(max, O_CONS(a, O_CONS(b)))
        node = _parse("max(a, b)")
        assert node.kind == OpKind.O_CALL
        assert node.right.kind == OpKind.O_CONS
        assert node.right.left.value == "a"
        assert node.right.right.kind == OpKind.O_CONS
        assert node.right.right.left.value == "b"


# ---------------------------------------------------------------------------
# Dot / member access
# ---------------------------------------------------------------------------

class TestDotAccess:
    def test_simple_dot(self):
        node = _parse("post.amount")
        assert node.kind == OpKind.O_LOOKUP
        assert node.left.value == "post"
        assert node.right.value == "amount"

    def test_chained_dot(self):
        # a.b.c -> O_LOOKUP(O_LOOKUP(a, b), c)
        node = _parse("a.b.c")
        assert node.kind == OpKind.O_LOOKUP
        assert node.left.kind == OpKind.O_LOOKUP
        assert node.left.left.value == "a"
        assert node.left.right.value == "b"
        assert node.right.value == "c"


# ---------------------------------------------------------------------------
# Match operators
# ---------------------------------------------------------------------------

class TestMatch:
    def test_regex_match(self):
        node = _parse("account =~ /Expenses/")
        assert node.kind == OpKind.O_MATCH
        assert node.left.value == "account"
        assert node.right.kind == OpKind.VALUE
        assert node.right.value == "Expenses"

    def test_negative_match(self):
        # !~ desugars as O_NOT(O_MATCH(...))
        node = _parse("account !~ /Income/")
        assert node.kind == OpKind.O_NOT
        assert node.left.kind == OpKind.O_MATCH


# ---------------------------------------------------------------------------
# Ternary / conditional
# ---------------------------------------------------------------------------

class TestTernary:
    def test_ternary(self):
        node = _parse("x ? 1 : 2")
        assert node.kind == OpKind.O_QUERY
        assert node.left.value == "x"
        assert node.right.kind == OpKind.O_COLON
        assert node.right.left.value == 1
        assert node.right.right.value == 2

    def test_postfix_if(self):
        # value if cond -> O_QUERY(cond, O_COLON(value, null))
        node = _parse("amount if has_amount")
        assert node.kind == OpKind.O_QUERY
        assert node.left.value == "has_amount"
        assert node.right.kind == OpKind.O_COLON
        assert node.right.left.value == "amount"

    def test_postfix_if_else(self):
        node = _parse("amount if has_amount else 0")
        assert node.kind == OpKind.O_QUERY
        assert node.left.value == "has_amount"
        assert node.right.kind == OpKind.O_COLON
        assert node.right.left.value == "amount"
        assert node.right.right.value == 0


# ---------------------------------------------------------------------------
# Assignment and definition
# ---------------------------------------------------------------------------

class TestAssignment:
    def test_simple_assign(self):
        node = _parse("x = 42")
        assert node.kind == OpKind.O_DEFINE
        assert node.left.value == "x"
        assert node.right.kind == OpKind.SCOPE
        assert node.right.left.kind == OpKind.VALUE
        assert node.right.left.value == 42


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

class TestSequence:
    def test_semicolon_sequence(self):
        node = _parse("x = 1; x + 2")
        assert node.kind == OpKind.O_SEQ
        assert node.left.kind == OpKind.O_DEFINE
        assert node.right.kind == OpKind.O_ADD


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

class TestLambda:
    def test_simple_lambda(self):
        node = _parse("x -> x + 1")
        assert node.kind == OpKind.O_LAMBDA
        assert node.left.value == "x"
        assert node.right.kind == OpKind.SCOPE
        assert node.right.left.kind == OpKind.O_ADD


# ---------------------------------------------------------------------------
# AST node properties
# ---------------------------------------------------------------------------

class TestExprNodeProperties:
    def test_is_value(self):
        node = _parse("42")
        assert node.is_value
        assert not node.is_ident
        assert node.is_terminal

    def test_is_ident(self):
        node = _parse("amount")
        assert node.is_ident
        assert not node.is_value
        assert node.is_terminal

    def test_is_binary_op(self):
        node = _parse("1 + 2")
        assert node.is_binary_op
        assert not node.is_terminal

    def test_is_unary_op(self):
        node = _parse("-x")
        assert node.is_unary_op


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------

class TestTraversal:
    def test_walk_pre_order(self):
        node = _parse("1 + 2")
        visited = []
        node.walk(lambda n: visited.append(n.kind))
        assert visited == [OpKind.O_ADD, OpKind.VALUE, OpKind.VALUE]

    def test_walk_post_order(self):
        node = _parse("1 + 2")
        visited = []
        node.walk_post(lambda n: visited.append(n.kind))
        assert visited == [OpKind.VALUE, OpKind.VALUE, OpKind.O_ADD]

    def test_iter_nodes(self):
        node = _parse("1 + 2 * 3")
        kinds = [n.kind for n in node.iter_nodes()]
        # O_ADD -> VALUE(1), O_MUL -> VALUE(2), VALUE(3)
        assert kinds == [
            OpKind.O_ADD, OpKind.VALUE,
            OpKind.O_MUL, OpKind.VALUE, OpKind.VALUE,
        ]


# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------

class TestDump:
    def test_dump_value(self):
        node = _parse("42")
        text = node.dump()
        assert "VALUE" in text
        assert "42" in text

    def test_dump_tree(self):
        node = _parse("1 + 2")
        text = node.dump()
        assert "O_ADD" in text
        assert "VALUE" in text


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_empty_expression(self):
        with pytest.raises(ParseError, match="Empty expression"):
            _parse("")

    def test_unexpected_token(self):
        with pytest.raises(ParseError):
            _parse("1 +")

    def test_unmatched_paren(self):
        with pytest.raises(ParseError):
            _parse("(1 + 2")

    def test_extra_tokens(self):
        with pytest.raises(ParseError, match="Unexpected token"):
            _parse("1 2")


# ---------------------------------------------------------------------------
# Compile convenience function
# ---------------------------------------------------------------------------

class TestCompileFunction:
    def test_compile_returns_ast(self):
        node = compile("1 + 2")
        assert isinstance(node, ExprNode)
        assert node.kind == OpKind.O_ADD
