"""Tests for the expression tokenizer."""

from __future__ import annotations

import pytest

from muonledger.expr_token import (
    ExprTokenizer,
    Token,
    TokenKind,
    TokenizeError,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _kinds(expr: str) -> list[TokenKind]:
    """Return the list of token kinds for *expr* (excluding EOF)."""
    return [t.kind for t in ExprTokenizer(expr).tokenize()]


def _values(expr: str) -> list[object]:
    """Return the list of token values for *expr* (excluding EOF)."""
    return [t.value for t in ExprTokenizer(expr).tokenize()]


# ---------------------------------------------------------------------------
# Basic operator tokenization
# ---------------------------------------------------------------------------

class TestOperators:
    def test_arithmetic(self):
        assert _kinds("+ - * %") == [
            TokenKind.PLUS, TokenKind.MINUS, TokenKind.STAR, TokenKind.KW_MOD,
        ]

    def test_comparison(self):
        assert _kinds("== != < <= > >=") == [
            TokenKind.EQUAL, TokenKind.NEQUAL,
            TokenKind.LESS, TokenKind.LESSEQ,
            TokenKind.GREATER, TokenKind.GREATEREQ,
        ]

    def test_assignment(self):
        assert _kinds("=") == [TokenKind.ASSIGN]

    def test_match(self):
        assert _kinds("=~ !~") == [TokenKind.MATCH, TokenKind.NMATCH]

    def test_logical(self):
        assert _kinds("! & && | ||") == [
            TokenKind.EXCLAM,
            TokenKind.KW_AND, TokenKind.KW_AND,
            TokenKind.KW_OR, TokenKind.KW_OR,
        ]

    def test_arrow(self):
        assert _kinds("->") == [TokenKind.ARROW]

    def test_ternary(self):
        assert _kinds("? :") == [TokenKind.QUERY, TokenKind.COLON]

    def test_punctuation(self):
        assert _kinds(". , ;") == [TokenKind.DOT, TokenKind.COMMA, TokenKind.SEMI]

    def test_grouping(self):
        assert _kinds("( ) { }") == [
            TokenKind.LPAREN, TokenKind.RPAREN,
            TokenKind.LBRACE, TokenKind.RBRACE,
        ]


# ---------------------------------------------------------------------------
# String literal tokenization
# ---------------------------------------------------------------------------

class TestStringLiterals:
    def test_single_quoted(self):
        tokens = ExprTokenizer("'hello world'").tokenize()
        assert len(tokens) == 1
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == "hello world"

    def test_double_quoted(self):
        tokens = ExprTokenizer('"foo bar"').tokenize()
        assert len(tokens) == 1
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == "foo bar"

    def test_escaped_quote(self):
        tokens = ExprTokenizer(r"'it\'s'").tokenize()
        assert tokens[0].value == "it's"

    def test_empty_string(self):
        tokens = ExprTokenizer("''").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == ""

    def test_unterminated_string(self):
        with pytest.raises(TokenizeError, match="Unterminated string"):
            ExprTokenizer("'hello").tokenize()


# ---------------------------------------------------------------------------
# Numeric literal tokenization
# ---------------------------------------------------------------------------

class TestNumericLiterals:
    def test_integer(self):
        tokens = ExprTokenizer("42").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == 42

    def test_decimal(self):
        tokens = ExprTokenizer("3.14").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == 3.14

    def test_zero(self):
        tokens = ExprTokenizer("0").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == 0

    def test_large_number(self):
        tokens = ExprTokenizer("1000000").tokenize()
        assert tokens[0].value == 1000000


# ---------------------------------------------------------------------------
# Identifier tokenization
# ---------------------------------------------------------------------------

class TestIdentifiers:
    def test_simple_ident(self):
        tokens = ExprTokenizer("amount").tokenize()
        assert tokens[0].kind == TokenKind.IDENT
        assert tokens[0].value == "amount"

    def test_ident_with_underscore(self):
        tokens = ExprTokenizer("total_cost").tokenize()
        assert tokens[0].kind == TokenKind.IDENT
        assert tokens[0].value == "total_cost"

    def test_ident_starts_with_underscore(self):
        tokens = ExprTokenizer("_private").tokenize()
        assert tokens[0].kind == TokenKind.IDENT
        assert tokens[0].value == "_private"

    def test_multiple_idents(self):
        tokens = ExprTokenizer("a b c").tokenize()
        assert [t.value for t in tokens] == ["a", "b", "c"]
        assert all(t.kind == TokenKind.IDENT for t in tokens)


# ---------------------------------------------------------------------------
# Reserved words
# ---------------------------------------------------------------------------

class TestReservedWords:
    def test_and(self):
        assert _kinds("and") == [TokenKind.KW_AND]

    def test_or(self):
        assert _kinds("or") == [TokenKind.KW_OR]

    def test_not(self):
        assert _kinds("not") == [TokenKind.EXCLAM]

    def test_div(self):
        assert _kinds("div") == [TokenKind.KW_DIV]

    def test_if_else(self):
        assert _kinds("if else") == [TokenKind.KW_IF, TokenKind.KW_ELSE]

    def test_true(self):
        tokens = ExprTokenizer("true").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value is True

    def test_false(self):
        tokens = ExprTokenizer("false").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value is False

    def test_null(self):
        tokens = ExprTokenizer("null").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value is None

    def test_ident_starting_with_keyword_prefix(self):
        """Words like 'android' should be identifiers, not parsed as 'and'."""
        tokens = ExprTokenizer("android").tokenize()
        assert tokens[0].kind == TokenKind.IDENT
        assert tokens[0].value == "android"

    def test_ident_starting_with_not(self):
        tokens = ExprTokenizer("nothing").tokenize()
        assert tokens[0].kind == TokenKind.IDENT
        assert tokens[0].value == "nothing"


# ---------------------------------------------------------------------------
# Date literals
# ---------------------------------------------------------------------------

class TestDateLiterals:
    def test_date(self):
        tokens = ExprTokenizer("[2024/01/01]").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == "2024/01/01"

    def test_date_range(self):
        tokens = ExprTokenizer("[2024/01/01]").tokenize()
        assert tokens[0].kind == TokenKind.VALUE

    def test_unterminated_date(self):
        with pytest.raises(TokenizeError, match="Unterminated date"):
            ExprTokenizer("[2024/01/01").tokenize()


# ---------------------------------------------------------------------------
# Regex literals
# ---------------------------------------------------------------------------

class TestRegexLiterals:
    def test_simple_regex(self):
        tokens = ExprTokenizer("/Expenses/").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[0].value == "Expenses"

    def test_regex_with_escaped_slash(self):
        tokens = ExprTokenizer(r"/a\/b/").tokenize()
        assert tokens[0].value == "a/b"

    def test_regex_with_pipe(self):
        tokens = ExprTokenizer(r"/foo\|bar/").tokenize()
        assert tokens[0].value == r"foo\|bar"

    def test_unterminated_regex(self):
        with pytest.raises(TokenizeError, match="Unterminated regex"):
            ExprTokenizer("/pattern").tokenize()

    def test_slash_in_op_context_is_division(self):
        """After a value token, / should be SLASH (division)."""
        tokens = ExprTokenizer("10 / 2").tokenize()
        assert tokens[0].kind == TokenKind.VALUE
        assert tokens[1].kind == TokenKind.SLASH
        assert tokens[2].kind == TokenKind.VALUE


# ---------------------------------------------------------------------------
# Complex expressions
# ---------------------------------------------------------------------------

class TestComplexExpressions:
    def test_comparison_expression(self):
        tokens = ExprTokenizer("amount > 100").tokenize()
        assert _kinds("amount > 100") == [
            TokenKind.IDENT, TokenKind.GREATER, TokenKind.VALUE,
        ]
        assert tokens[0].value == "amount"
        assert tokens[2].value == 100

    def test_logical_expression(self):
        assert _kinds("amount > 100 and account == 'Expenses'") == [
            TokenKind.IDENT, TokenKind.GREATER, TokenKind.VALUE,
            TokenKind.KW_AND,
            TokenKind.IDENT, TokenKind.EQUAL, TokenKind.VALUE,
        ]

    def test_regex_match_expression(self):
        tokens = ExprTokenizer("account =~ /Expenses/").tokenize()
        assert [t.kind for t in tokens] == [
            TokenKind.IDENT, TokenKind.MATCH, TokenKind.VALUE,
        ]
        assert tokens[0].value == "account"
        assert tokens[2].value == "Expenses"

    def test_parenthesized_expression(self):
        assert _kinds("(a + b) * c") == [
            TokenKind.LPAREN, TokenKind.IDENT, TokenKind.PLUS, TokenKind.IDENT,
            TokenKind.RPAREN, TokenKind.STAR, TokenKind.IDENT,
        ]

    def test_ternary_expression(self):
        assert _kinds("a ? b : c") == [
            TokenKind.IDENT, TokenKind.QUERY, TokenKind.IDENT,
            TokenKind.COLON, TokenKind.IDENT,
        ]

    def test_function_call(self):
        assert _kinds("fn(a, b)") == [
            TokenKind.IDENT, TokenKind.LPAREN, TokenKind.IDENT,
            TokenKind.COMMA, TokenKind.IDENT, TokenKind.RPAREN,
        ]

    def test_member_access(self):
        assert _kinds("post.amount") == [
            TokenKind.IDENT, TokenKind.DOT, TokenKind.IDENT,
        ]

    def test_lambda(self):
        assert _kinds("x -> x + 1") == [
            TokenKind.IDENT, TokenKind.ARROW, TokenKind.IDENT,
            TokenKind.PLUS, TokenKind.VALUE,
        ]

    def test_negation(self):
        assert _kinds("!active") == [
            TokenKind.EXCLAM, TokenKind.IDENT,
        ]

    def test_not_keyword_in_expression(self):
        assert _kinds("not cleared") == [
            TokenKind.EXCLAM, TokenKind.IDENT,
        ]

    def test_if_else_expression(self):
        assert _kinds("if a else b") == [
            TokenKind.KW_IF, TokenKind.IDENT,
            TokenKind.KW_ELSE, TokenKind.IDENT,
        ]

    def test_division_after_ident(self):
        """/ after an identifier should be division (op context)."""
        tokens = ExprTokenizer("amount / 2").tokenize()
        assert tokens[1].kind == TokenKind.SLASH

    def test_division_after_rparen(self):
        """/ after ) should be division."""
        tokens = ExprTokenizer("(a + b) / c").tokenize()
        slash = [t for t in tokens if t.kind == TokenKind.SLASH]
        assert len(slash) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        tokens = ExprTokenizer("").tokenize()
        assert tokens == []

    def test_whitespace_only(self):
        tokens = ExprTokenizer("   ").tokenize()
        assert tokens == []

    def test_single_token(self):
        tokens = ExprTokenizer("x").tokenize()
        assert len(tokens) == 1

    def test_eof_token_in_iterator(self):
        toks = list(ExprTokenizer("x"))
        assert toks[-1].kind == TokenKind.TOK_EOF

    def test_unexpected_character(self):
        with pytest.raises(TokenizeError, match="Unexpected character"):
            ExprTokenizer("~").tokenize()

    def test_position_tracking(self):
        tokens = ExprTokenizer("a + b").tokenize()
        assert tokens[0].position == 0
        assert tokens[1].position == 2
        assert tokens[2].position == 4

    def test_length_tracking(self):
        tokens = ExprTokenizer("==").tokenize()
        assert tokens[0].length == 2

    def test_token_repr(self):
        tok = Token(kind=TokenKind.IDENT, value="amount")
        assert "IDENT" in repr(tok)
        assert "amount" in repr(tok)

    def test_token_repr_operator(self):
        tok = Token(kind=TokenKind.PLUS)
        assert "PLUS" in repr(tok)

    def test_consecutive_operators(self):
        assert _kinds("!=") == [TokenKind.NEQUAL]
        assert _kinds("!") == [TokenKind.EXCLAM]

    def test_multiple_statements(self):
        assert _kinds("a; b") == [
            TokenKind.IDENT, TokenKind.SEMI, TokenKind.IDENT,
        ]
