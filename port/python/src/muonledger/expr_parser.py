"""
Pratt / precedence-climbing parser for the Ledger expression language.

This module provides the ``ExprParser`` class, a Python port of Ledger's
``parser_t`` type from ``parser.h`` / ``parser.cc``.  It takes a sequence
of tokens produced by ``ExprTokenizer`` and builds an ``ExprNode`` AST.

The parser uses recursive descent with operator-precedence climbing.
Each ``_parse_*`` method handles one precedence level and delegates to the
next-tighter level for its operands.  The precedence levels, from lowest
to highest, are:

  1. value_expr   -- semicolons (``;``) / O_SEQ
  2. assign_expr  -- assignment (``=``) / O_DEFINE
  3. lambda_expr  -- arrow (``->``) / O_LAMBDA
  4. comma_expr   -- comma (``,``) / O_CONS
  5. query_expr   -- ternary (``? :``) and postfix ``if``/``else`` / O_QUERY
  6. or_expr      -- logical OR (``or``, ``|``, ``||``) / O_OR
  7. and_expr     -- logical AND (``and``, ``&``, ``&&``) / O_AND
  8. logic_expr   -- comparisons (``==``, ``!=``, ``<``, ``<=``, etc.) / O_EQ, ...
  9. add_expr     -- addition/subtraction (``+``, ``-``) / O_ADD, O_SUB
 10. mul_expr     -- multiplication/division (``*``, ``/``) / O_MUL, O_DIV
 11. unary_expr   -- unary prefix (``!``, ``-``, ``not``) / O_NOT, O_NEG
 12. dot_expr     -- member access (``.``) / O_LOOKUP
 13. call_expr    -- function call (``func(...)``) / O_CALL
 14. value_term   -- literals, identifiers, parenthesized sub-expressions
"""

from __future__ import annotations

from typing import Optional

from muonledger.expr_ast import ExprNode, OpKind
from muonledger.expr_token import ExprTokenizer, Token, TokenKind, TokenizeError


__all__ = [
    "ExprParser",
    "ParseError",
    "compile",
]


class ParseError(Exception):
    """Raised when the parser encounters invalid syntax."""


class ExprParser:
    """Recursive-descent, precedence-climbing parser for Ledger expressions.

    The parser consumes tokens from an ``ExprTokenizer`` and builds an
    ``ExprNode`` AST.  It supports one level of token look-ahead via an
    internal push-back mechanism.

    Parameters
    ----------
    source : str
        The expression string to parse.
    """

    def __init__(self, source: str) -> None:
        self._tokenizer = ExprTokenizer(source)
        self._source = source
        self._lookahead: Optional[Token] = None

    def _next_token(self) -> Token:
        """Return the next token, consuming from look-ahead if available."""
        if self._lookahead is not None:
            tok = self._lookahead
            self._lookahead = None
            return tok
        return self._tokenizer.next_token()

    def _push_token(self, tok: Token) -> None:
        """Push a token back so the next ``_next_token`` call returns it."""
        assert self._lookahead is None, "Cannot push more than one token"
        self._lookahead = tok

    def _peek_token(self) -> Token:
        """Peek at the next token without consuming it."""
        tok = self._next_token()
        self._push_token(tok)
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        """Consume the next token and raise if it is not *kind*."""
        tok = self._next_token()
        if tok.kind != kind:
            raise ParseError(
                f"Expected {kind.name} but got {tok.kind.name} "
                f"at position {tok.position}"
            )
        return tok

    # ------------------------------------------------------------------
    # Precedence levels (lowest to highest)
    # ------------------------------------------------------------------

    def parse(self) -> ExprNode:
        """Parse the entire expression and return the root AST node.

        Raises ``ParseError`` if the expression is empty or malformed.
        """
        node = self._parse_value_expr()
        if node is None:
            raise ParseError("Empty expression")
        # Verify we consumed everything.
        tok = self._next_token()
        if tok.kind != TokenKind.TOK_EOF:
            raise ParseError(
                f"Unexpected token {tok.kind.name} at position {tok.position}"
            )
        return node

    # --- Level 1: semicolon sequences ---

    def _parse_value_expr(self) -> Optional[ExprNode]:
        node = self._parse_assign_expr()
        if node is None:
            return None

        chain: Optional[ExprNode] = None
        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.SEMI:
                seq = ExprNode(kind=OpKind.O_SEQ)
                if chain is None:
                    seq.left = node
                    node = seq
                else:
                    seq.left = chain.right
                    chain.right = seq
                seq.right = self._parse_assign_expr()
                chain = seq
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 2: assignment ---

    def _parse_assign_expr(self) -> Optional[ExprNode]:
        node = self._parse_lambda_expr()
        if node is None:
            return None

        tok = self._next_token()
        if tok.kind == TokenKind.ASSIGN:
            prev = node
            node = ExprNode(kind=OpKind.O_DEFINE)
            node.left = prev
            scope = ExprNode(kind=OpKind.SCOPE)
            scope.left = self._parse_lambda_expr()
            node.right = scope
        else:
            self._push_token(tok)
        return node

    # --- Level 3: lambda ---

    def _parse_lambda_expr(self) -> Optional[ExprNode]:
        node = self._parse_comma_expr()
        if node is None:
            return None

        tok = self._next_token()
        if tok.kind == TokenKind.ARROW:
            prev = node
            node = ExprNode(kind=OpKind.O_LAMBDA)
            node.left = prev
            scope = ExprNode(kind=OpKind.SCOPE)
            scope.left = self._parse_querycolon_expr()
            node.right = scope
        else:
            self._push_token(tok)
        return node

    # --- Level 4: comma lists ---

    def _parse_comma_expr(self) -> Optional[ExprNode]:
        node = self._parse_querycolon_expr()
        if node is None:
            return None

        tail: Optional[ExprNode] = None
        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.COMMA:
                # Peek to see if we have a closing paren (trailing comma).
                peek = self._next_token()
                self._push_token(peek)
                if peek.kind == TokenKind.RPAREN:
                    break

                if tail is None:
                    prev = node
                    node = ExprNode(kind=OpKind.O_CONS)
                    node.left = prev
                    tail = node

                chain = ExprNode(kind=OpKind.O_CONS)
                chain.left = self._parse_querycolon_expr()
                tail.right = chain
                tail = chain
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 5: ternary / postfix if ---

    def _parse_querycolon_expr(self) -> Optional[ExprNode]:
        node = self._parse_or_expr()
        if node is None:
            return None

        tok = self._next_token()
        if tok.kind == TokenKind.QUERY:
            # Traditional ternary: cond ? then : else
            prev = node
            node = ExprNode(kind=OpKind.O_QUERY)
            node.left = prev
            then_expr = self._parse_or_expr()
            if then_expr is None:
                raise ParseError("'?' operator not followed by argument")
            self._expect(TokenKind.COLON)
            else_expr = self._parse_or_expr()
            if else_expr is None:
                raise ParseError("':' operator not followed by argument")
            colon = ExprNode(kind=OpKind.O_COLON)
            colon.left = then_expr
            colon.right = else_expr
            node.right = colon
        elif tok.kind == TokenKind.KW_IF:
            # Postfix: value_expr if cond [else alt]
            cond = self._parse_or_expr()
            if cond is None:
                raise ParseError("'if' keyword not followed by argument")
            tok2 = self._next_token()
            if tok2.kind == TokenKind.KW_ELSE:
                alt = self._parse_or_expr()
                if alt is None:
                    raise ParseError("'else' keyword not followed by argument")
            else:
                self._push_token(tok2)
                alt = ExprNode(kind=OpKind.VALUE, value=None)
            colon = ExprNode(kind=OpKind.O_COLON)
            colon.left = node
            colon.right = alt
            node = ExprNode(kind=OpKind.O_QUERY)
            node.left = cond
            node.right = colon
        else:
            self._push_token(tok)
        return node

    # --- Level 6: logical OR ---

    def _parse_or_expr(self) -> Optional[ExprNode]:
        node = self._parse_and_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.KW_OR:
                prev = node
                node = ExprNode(kind=OpKind.O_OR)
                node.left = prev
                node.right = self._parse_and_expr()
                if node.right is None:
                    raise ParseError(
                        f"'{tok.symbol}' operator not followed by argument"
                    )
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 7: logical AND ---

    def _parse_and_expr(self) -> Optional[ExprNode]:
        node = self._parse_logic_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.KW_AND:
                prev = node
                node = ExprNode(kind=OpKind.O_AND)
                node.left = prev
                node.right = self._parse_logic_expr()
                if node.right is None:
                    raise ParseError(
                        f"'{tok.symbol}' operator not followed by argument"
                    )
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 8: comparison / match ---

    def _parse_logic_expr(self) -> Optional[ExprNode]:
        node = self._parse_add_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            kind: Optional[OpKind] = None
            negate = False

            if tok.kind == TokenKind.EQUAL:
                kind = OpKind.O_EQ
            elif tok.kind == TokenKind.NEQUAL:
                kind = OpKind.O_EQ
                negate = True
            elif tok.kind == TokenKind.MATCH:
                kind = OpKind.O_MATCH
            elif tok.kind == TokenKind.NMATCH:
                kind = OpKind.O_MATCH
                negate = True
            elif tok.kind == TokenKind.LESS:
                kind = OpKind.O_LT
            elif tok.kind == TokenKind.LESSEQ:
                kind = OpKind.O_LTE
            elif tok.kind == TokenKind.GREATER:
                kind = OpKind.O_GT
            elif tok.kind == TokenKind.GREATEREQ:
                kind = OpKind.O_GTE
            else:
                self._push_token(tok)
                break

            if kind is not None:
                prev = node
                node = ExprNode(kind=kind)
                node.left = prev
                node.right = self._parse_add_expr()
                if node.right is None:
                    raise ParseError(
                        f"'{tok.symbol}' operator not followed by argument"
                    )
                if negate:
                    prev = node
                    node = ExprNode(kind=OpKind.O_NOT)
                    node.left = prev
        return node

    # --- Level 9: addition / subtraction ---

    def _parse_add_expr(self) -> Optional[ExprNode]:
        node = self._parse_mul_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.PLUS:
                op_kind = OpKind.O_ADD
            elif tok.kind == TokenKind.MINUS:
                op_kind = OpKind.O_SUB
            else:
                self._push_token(tok)
                break

            prev = node
            node = ExprNode(kind=op_kind)
            node.left = prev
            node.right = self._parse_mul_expr()
            if node.right is None:
                raise ParseError(
                    f"'{tok.symbol}' operator not followed by argument"
                )
        return node

    # --- Level 10: multiplication / division ---

    def _parse_mul_expr(self) -> Optional[ExprNode]:
        node = self._parse_unary_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind in (TokenKind.STAR, TokenKind.SLASH, TokenKind.KW_DIV):
                op_kind = OpKind.O_MUL if tok.kind == TokenKind.STAR else OpKind.O_DIV
            else:
                self._push_token(tok)
                break

            prev = node
            node = ExprNode(kind=op_kind)
            node.left = prev
            node.right = self._parse_unary_expr()
            if node.right is None:
                raise ParseError(
                    f"'{tok.symbol}' operator not followed by argument"
                )
        return node

    # --- Level 11: unary prefix ---

    def _parse_unary_expr(self) -> Optional[ExprNode]:
        tok = self._next_token()

        if tok.kind == TokenKind.EXCLAM:
            operand = self._parse_unary_expr()
            if operand is None:
                raise ParseError("'!' operator not followed by argument")
            # Constant folding for literal booleans.
            if operand.kind == OpKind.VALUE and isinstance(operand.value, bool):
                operand.value = not operand.value
                return operand
            node = ExprNode(kind=OpKind.O_NOT)
            node.left = operand
            return node

        if tok.kind == TokenKind.MINUS:
            operand = self._parse_unary_expr()
            if operand is None:
                raise ParseError("'-' operator not followed by argument")
            # Constant folding for numeric literals.
            if operand.kind == OpKind.VALUE and isinstance(operand.value, (int, float)):
                operand.value = -operand.value
                return operand
            node = ExprNode(kind=OpKind.O_NEG)
            node.left = operand
            return node

        self._push_token(tok)
        return self._parse_dot_expr()

    # --- Level 12: dot / member access ---

    def _parse_dot_expr(self) -> Optional[ExprNode]:
        node = self._parse_call_expr()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.DOT:
                prev = node
                node = ExprNode(kind=OpKind.O_LOOKUP)
                node.left = prev
                node.right = self._parse_call_expr()
                if node.right is None:
                    raise ParseError("'.' operator not followed by argument")
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 13: function call ---

    def _parse_call_expr(self) -> Optional[ExprNode]:
        node = self._parse_value_term()
        if node is None:
            return None

        while True:
            tok = self._next_token()
            if tok.kind == TokenKind.LPAREN:
                prev = node
                node = ExprNode(kind=OpKind.O_CALL)
                node.left = prev
                # Parse the argument list as a single parenthesized expression.
                # Push the LPAREN back so _parse_value_term sees it.
                self._push_token(tok)
                node.right = self._parse_value_term()
            else:
                self._push_token(tok)
                break
        return node

    # --- Level 14: primary values ---

    def _parse_value_term(self) -> Optional[ExprNode]:
        tok = self._next_token()

        if tok.kind == TokenKind.VALUE:
            return ExprNode(kind=OpKind.VALUE, value=tok.value)

        if tok.kind == TokenKind.IDENT:
            return ExprNode(kind=OpKind.IDENT, value=tok.value)

        if tok.kind == TokenKind.LPAREN:
            node = self._parse_value_expr()
            self._expect(TokenKind.RPAREN)
            return node

        # Nothing matched -- push back and return None.
        self._push_token(tok)
        return None


def compile(expr_string: str) -> ExprNode:
    """Convenience function: parse an expression string into an AST.

    Parameters
    ----------
    expr_string : str
        The expression to parse.

    Returns
    -------
    ExprNode
        The root of the parsed AST.

    Raises
    ------
    ParseError
        If the expression is empty or contains syntax errors.
    """
    return ExprParser(expr_string).parse()
