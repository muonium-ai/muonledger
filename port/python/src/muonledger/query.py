"""
Query language parser for user-friendly command-line queries.

This module provides ``QueryParser`` and ``parse_query()``, a Python port of
Ledger's ``query_t`` from ``query.h`` / ``query.cc``.  It translates
user-facing shorthand like::

    food and @grocery

into expression AST nodes equivalent to::

    (account =~ /food/) and (payee =~ /grocery/)

The query language supports:
  - Bare terms match account names: ``food`` becomes ``account =~ /food/``
  - ``@term`` matches payees: ``@grocery`` becomes ``payee =~ /grocery/``
  - ``#term`` matches codes: ``#1234`` becomes ``code =~ /1234/``
  - ``=term`` matches notes: ``=vacation`` becomes ``note =~ /vacation/``
  - ``%term`` matches tags: ``%project`` becomes ``has_tag(/project/)``
  - ``/regex/`` matches account names with a regex pattern
  - Boolean connectives: ``and``/``&``, ``or``/``|``, ``not``/``!``
  - Parenthesized grouping: ``(food or drinks) and @store``
  - Implicit AND between consecutive terms: ``Expenses Food`` is
    ``(account =~ /Expenses/) and (account =~ /Food/)``

Operator precedence (lowest to highest): ``or``, ``and``/implicit, ``not``, atoms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from muonledger.expr_ast import ExprNode, OpKind


__all__ = [
    "QueryParser",
    "QueryParseError",
    "parse_query",
]


class QueryParseError(Exception):
    """Raised when the query parser encounters invalid input."""


# ---------------------------------------------------------------------------
# Query token types (distinct from expr_token.py's TokenKind)
# ---------------------------------------------------------------------------

class _QTokenKind(Enum):
    """Token kinds specific to the query lexer."""
    UNKNOWN = auto()
    LPAREN = auto()
    RPAREN = auto()
    TOK_NOT = auto()
    TOK_AND = auto()
    TOK_OR = auto()
    TOK_EQ = auto()
    TOK_CODE = auto()
    TOK_PAYEE = auto()
    TOK_NOTE = auto()
    TOK_ACCOUNT = auto()
    TOK_META = auto()
    TERM = auto()
    END_REACHED = auto()


@dataclass
class _QToken:
    """A single token produced by the query lexer."""
    kind: _QTokenKind
    value: Optional[str] = None

    def __bool__(self) -> bool:
        return self.kind != _QTokenKind.END_REACHED


# ---------------------------------------------------------------------------
# Query keywords
# ---------------------------------------------------------------------------

_KEYWORDS: dict[str, _QTokenKind] = {
    "and": _QTokenKind.TOK_AND,
    "or": _QTokenKind.TOK_OR,
    "not": _QTokenKind.TOK_NOT,
    "code": _QTokenKind.TOK_CODE,
    "desc": _QTokenKind.TOK_PAYEE,
    "payee": _QTokenKind.TOK_PAYEE,
    "note": _QTokenKind.TOK_NOTE,
    "account": _QTokenKind.TOK_ACCOUNT,
    "tag": _QTokenKind.TOK_META,
    "meta": _QTokenKind.TOK_META,
    "data": _QTokenKind.TOK_META,
}

# Characters that act as operator boundaries when scanning bare-word identifiers
_BOUNDARY_CHARS = frozenset("()&|!@#%=")


# ---------------------------------------------------------------------------
# Query Lexer
# ---------------------------------------------------------------------------

class _QueryLexer:
    """Tokenizes a query string into ``_QToken`` values.

    Handles:
      - Quoted patterns ('...', "...", /.../)
      - Single-character operators (@, #, %, =, &, |, !)
      - Keyword recognition (and, or, not, payee, code, etc.)
      - Bare-word identifiers (accumulated until an operator boundary)
    """

    def __init__(self, source: str) -> None:
        self._source = source
        self._pos = 0
        self._cache: Optional[_QToken] = None

    def push_token(self, tok: _QToken) -> None:
        assert self._cache is None, "Cannot push more than one token"
        self._cache = tok

    def peek_token(self) -> _QToken:
        if self._cache is None:
            self._cache = self.next_token()
        return self._cache

    def next_token(self) -> _QToken:
        if self._cache is not None:
            tok = self._cache
            self._cache = None
            return tok

        # Skip whitespace
        while self._pos < len(self._source) and self._source[self._pos].isspace():
            self._pos += 1

        if self._pos >= len(self._source):
            return _QToken(_QTokenKind.END_REACHED)

        ch = self._source[self._pos]

        # Quoted / delimited patterns
        if ch in ("'", '"', '/'):
            return self._scan_quoted_pattern()

        # Single-character operators
        if ch == '(':
            self._pos += 1
            return _QToken(_QTokenKind.LPAREN)
        if ch == ')':
            self._pos += 1
            return _QToken(_QTokenKind.RPAREN)
        if ch == '&':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_AND)
        if ch == '|':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_OR)
        if ch == '!':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_NOT)
        if ch == '@':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_PAYEE)
        if ch == '#':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_CODE)
        if ch == '%':
            self._pos += 1
            return _QToken(_QTokenKind.TOK_META)
        if ch == '=':
            self._pos += 1
            # Check if this is a metadata value comparator (TOK_EQ) or note prefix.
            # At the start of a token sequence or after whitespace, '=' is a note prefix.
            # We treat leading '=' as TOK_NOTE (note matching).
            # The parser handles '=' after a meta tag as a value match via peek.
            return _QToken(_QTokenKind.TOK_NOTE)

        # Bare-word identifier: accumulate until boundary
        return self._scan_identifier()

    def _scan_quoted_pattern(self) -> _QToken:
        closing = self._source[self._pos]
        is_regex = (closing == '/')
        self._pos += 1  # skip opening delimiter
        buf: list[str] = []
        while self._pos < len(self._source):
            ch = self._source[self._pos]
            self._pos += 1
            if ch == '\\' and self._pos < len(self._source):
                next_ch = self._source[self._pos]
                self._pos += 1
                if is_regex and next_ch != closing:
                    buf.append('\\')
                buf.append(next_ch)
            elif ch == closing:
                if not buf:
                    raise QueryParseError("Match pattern is empty")
                return _QToken(_QTokenKind.TERM, "".join(buf))
            else:
                buf.append(ch)
        raise QueryParseError(f"Expected '{closing}' at end of pattern")

    def _scan_identifier(self) -> _QToken:
        start = self._pos
        while self._pos < len(self._source):
            ch = self._source[self._pos]
            if ch.isspace() or ch in _BOUNDARY_CHARS:
                break
            self._pos += 1
        ident = self._source[start:self._pos].strip()
        if not ident:
            raise QueryParseError(f"Unexpected character at position {start}")

        # Match against keywords
        lower = ident.lower()
        if lower in _KEYWORDS:
            return _QToken(_KEYWORDS[lower])
        return _QToken(_QTokenKind.TERM, ident)


# ---------------------------------------------------------------------------
# Query Parser
# ---------------------------------------------------------------------------

class QueryParser:
    """Recursive-descent parser that builds ExprNode trees from query strings.

    The parser implements the standard precedence hierarchy:
      - parse_or_expr: ``or`` / ``|`` (lowest precedence)
      - parse_and_expr: ``and`` / ``&``, plus implicit AND between adjacent terms
      - parse_unary_expr: ``not`` / ``!``
      - parse_query_term: atoms (patterns, field prefixes, parenthesized groups)

    The ``tok_context`` parameter tracks which field current terms should match
    against.  It starts as TOK_ACCOUNT (bare terms match account names) and
    changes when the user writes a field prefix like ``@`` (payee) or ``#`` (code).
    """

    MAX_PARSE_DEPTH = 256

    def __init__(self, query_string: str) -> None:
        self._lexer = _QueryLexer(query_string)
        self._parse_depth = 0

    def parse(self) -> Optional[ExprNode]:
        """Parse the query and return the root ExprNode, or None if empty."""
        return self._parse_or_expr(_QTokenKind.TOK_ACCOUNT)

    def _parse_query_term(
        self, tok_context: _QTokenKind
    ) -> Optional[ExprNode]:
        """Parse a single atomic query term."""
        tok = self._lexer.next_token()

        if tok.kind == _QTokenKind.END_REACHED:
            self._lexer.push_token(tok)
            return None

        # Field context switches
        if tok.kind in (
            _QTokenKind.TOK_CODE,
            _QTokenKind.TOK_PAYEE,
            _QTokenKind.TOK_NOTE,
            _QTokenKind.TOK_ACCOUNT,
            _QTokenKind.TOK_META,
        ):
            node = self._parse_query_term(tok.kind)
            if node is None:
                raise QueryParseError(
                    f"Field prefix not followed by a search term"
                )
            return node

        # TERM: build the appropriate match node
        if tok.kind == _QTokenKind.TERM:
            assert tok.value is not None
            if tok_context == _QTokenKind.TOK_META:
                return self._make_meta_node(tok.value)
            return self._make_match_node(tok_context, tok.value)

        # Parenthesized sub-expression
        if tok.kind == _QTokenKind.LPAREN:
            self._parse_depth += 1
            if self._parse_depth > self.MAX_PARSE_DEPTH:
                raise QueryParseError("Query expression nested too deeply")
            node = self._parse_or_expr(tok_context)
            self._parse_depth -= 1
            closing = self._lexer.next_token()
            if closing.kind != _QTokenKind.RPAREN:
                raise QueryParseError("Missing ')'")
            return node

        # Anything else: push back and return None
        self._lexer.push_token(tok)
        return None

    def _parse_unary_expr(
        self, tok_context: _QTokenKind
    ) -> Optional[ExprNode]:
        """Parse a unary expression: ``not <term>`` or a plain query term."""
        tok = self._lexer.next_token()
        if tok.kind == _QTokenKind.TOK_NOT:
            term = self._parse_query_term(tok_context)
            if term is None:
                raise QueryParseError("'not' operator not followed by argument")
            node = ExprNode(kind=OpKind.O_NOT)
            node.left = term
            return node
        self._lexer.push_token(tok)
        return self._parse_query_term(tok_context)

    def _parse_and_expr(
        self, tok_context: _QTokenKind
    ) -> Optional[ExprNode]:
        """Parse AND-connected unary expressions, including implicit AND."""
        node = self._parse_unary_expr(tok_context)
        if node is None:
            return None

        while True:
            tok = self._lexer.next_token()
            if tok.kind == _QTokenKind.TOK_AND:
                # Explicit AND
                right = self._parse_unary_expr(tok_context)
                if right is None:
                    raise QueryParseError(
                        "'and' operator not followed by argument"
                    )
                prev = node
                node = ExprNode(kind=OpKind.O_AND)
                node.left = prev
                node.right = right
            else:
                self._lexer.push_token(tok)
                # Implicit AND: if the next token can start a unary_expr,
                # treat it as an implicit AND.
                peek = self._lexer.peek_token()
                if peek.kind in (
                    _QTokenKind.TERM,
                    _QTokenKind.TOK_NOT,
                    _QTokenKind.LPAREN,
                    _QTokenKind.TOK_CODE,
                    _QTokenKind.TOK_PAYEE,
                    _QTokenKind.TOK_NOTE,
                    _QTokenKind.TOK_ACCOUNT,
                    _QTokenKind.TOK_META,
                ):
                    right = self._parse_unary_expr(tok_context)
                    if right is not None:
                        prev = node
                        node = ExprNode(kind=OpKind.O_AND)
                        node.left = prev
                        node.right = right
                        continue
                break
        return node

    def _parse_or_expr(
        self, tok_context: _QTokenKind
    ) -> Optional[ExprNode]:
        """Parse OR-connected AND expressions."""
        node = self._parse_and_expr(tok_context)
        if node is None:
            return None

        while True:
            tok = self._lexer.next_token()
            if tok.kind == _QTokenKind.TOK_OR:
                right = self._parse_and_expr(tok_context)
                if right is None:
                    raise QueryParseError(
                        "'or' operator not followed by argument"
                    )
                prev = node
                node = ExprNode(kind=OpKind.O_OR)
                node.left = prev
                node.right = right
            else:
                self._lexer.push_token(tok)
                break
        return node

    # ------------------------------------------------------------------
    # Node construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_match_node(
        tok_context: _QTokenKind, pattern: str
    ) -> ExprNode:
        """Build an O_MATCH node: ``field =~ /pattern/``.

        Maps tok_context to the appropriate field identifier:
          - TOK_ACCOUNT -> "account"
          - TOK_PAYEE   -> "payee"
          - TOK_CODE    -> "code"
          - TOK_NOTE    -> "note"
        """
        field_map = {
            _QTokenKind.TOK_ACCOUNT: "account",
            _QTokenKind.TOK_PAYEE: "payee",
            _QTokenKind.TOK_CODE: "code",
            _QTokenKind.TOK_NOTE: "note",
        }
        field_name = field_map.get(tok_context, "account")

        ident = ExprNode(kind=OpKind.IDENT, value=field_name)
        mask = ExprNode(kind=OpKind.VALUE, value=re.compile(pattern, re.IGNORECASE))
        node = ExprNode(kind=OpKind.O_MATCH)
        node.left = ident
        node.right = mask
        return node

    @staticmethod
    def _make_meta_node(tag_pattern: str) -> ExprNode:
        """Build a function-call node: ``has_tag(/pattern/)``.

        The resulting AST is:
            O_CALL
              left: IDENT("has_tag")
              right: VALUE(compiled_regex)
        """
        ident = ExprNode(kind=OpKind.IDENT, value="has_tag")
        arg = ExprNode(kind=OpKind.VALUE, value=re.compile(tag_pattern, re.IGNORECASE))
        node = ExprNode(kind=OpKind.O_CALL)
        node.left = ident
        node.right = arg
        return node


def parse_query(query_string: str) -> Optional[ExprNode]:
    """Parse a user-facing query string into an ExprNode tree.

    Parameters
    ----------
    query_string : str
        The query expression, e.g. ``"Expenses and @Grocery"``.

    Returns
    -------
    ExprNode or None
        The root of the expression tree, or None if the query is empty.

    Raises
    ------
    QueryParseError
        If the query contains syntax errors.

    Examples
    --------
    >>> node = parse_query("Expenses")
    >>> node.kind
    <OpKind.O_MATCH: ...>
    >>> node.left.value
    'account'

    >>> node = parse_query("@Grocery")
    >>> node.left.value
    'payee'
    """
    query_string = query_string.strip()
    if not query_string:
        return None
    return QueryParser(query_string).parse()
