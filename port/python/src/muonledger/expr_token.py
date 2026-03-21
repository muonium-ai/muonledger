"""
Expression tokenizer for the Ledger expression language.

This module provides the ``ExprTokenizer`` class, a Python port of Ledger's
``token_t`` type from ``token.h`` / ``token.cc``.  It breaks an expression
string like ``amount > 100 and account =~ /Expenses/`` into a sequence of
typed ``Token`` objects that the expression parser can consume.

The tokenizer handles:
  - Single- and multi-character operators (+, -, ==, !=, ->, &&, etc.)
  - Reserved words (and, or, not, div, if, else, true, false)
  - Bracketed date literals ([2024/01/01])
  - Quoted strings ('hello', "world")
  - Regular expression masks (/pattern/)
  - Numeric literals (42, 3.14)
  - Identifiers (amount, payee, account)
  - Grouping delimiters and punctuation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator, Optional, Union


__all__ = [
    "TokenKind",
    "Token",
    "ExprTokenizer",
    "TokenizeError",
]


class TokenizeError(Exception):
    """Raised when the tokenizer encounters invalid input."""


class TokenKind(Enum):
    """Enumeration of all token kinds in the expression grammar.

    Mirrors ``expr_t::token_t::kind_t`` from the C++ Ledger source.
    """
    # Errors and special markers
    ERROR = auto()
    VALUE = auto()
    IDENT = auto()
    MASK = auto()

    # Grouping delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()

    # Comparison operators
    EQUAL = auto()       # ==
    NEQUAL = auto()      # !=
    LESS = auto()        # <
    LESSEQ = auto()      # <=
    GREATER = auto()     # >
    GREATEREQ = auto()   # >=

    # Assignment and matching
    ASSIGN = auto()      # =
    MATCH = auto()       # =~
    NMATCH = auto()      # !~

    # Arithmetic operators
    MINUS = auto()       # -
    PLUS = auto()        # +
    STAR = auto()        # *
    SLASH = auto()       # /
    ARROW = auto()       # ->
    KW_DIV = auto()      # div (integer division)

    # Logical operators
    EXCLAM = auto()      # ! or 'not'
    KW_AND = auto()      # & or && or 'and'
    KW_OR = auto()       # | or || or 'or'
    KW_MOD = auto()      # %

    # Control-flow keywords
    KW_IF = auto()       # if
    KW_ELSE = auto()     # else

    # Ternary operators
    QUERY = auto()       # ?
    COLON = auto()       # :

    # Punctuation
    DOT = auto()         # .
    COMMA = auto()       # ,
    SEMI = auto()        # ;

    # End markers
    TOK_EOF = auto()
    UNKNOWN = auto()


@dataclass
class Token:
    """A single lexical token produced by the expression tokenizer.

    Attributes
    ----------
    kind : TokenKind
        The type of this token.
    value : object
        The parsed value (string for IDENT, numeric for VALUE, etc.).
    position : int
        The character offset in the source string where this token starts.
    length : int
        The number of characters consumed from the input.
    symbol : str
        Short textual representation for diagnostics.
    """
    kind: TokenKind
    value: object = None
    position: int = 0
    length: int = 0
    symbol: str = ""

    def __repr__(self) -> str:
        if self.kind in (TokenKind.VALUE, TokenKind.IDENT, TokenKind.MASK):
            return f"Token({self.kind.name}, {self.value!r})"
        return f"Token({self.kind.name})"


# ---------------------------------------------------------------------------
# Reserved word table
# ---------------------------------------------------------------------------

_RESERVED_WORDS: dict[str, tuple[TokenKind, object]] = {
    "and": (TokenKind.KW_AND, None),
    "or": (TokenKind.KW_OR, None),
    "not": (TokenKind.EXCLAM, None),
    "div": (TokenKind.KW_DIV, None),
    "if": (TokenKind.KW_IF, None),
    "else": (TokenKind.KW_ELSE, None),
    "true": (TokenKind.VALUE, True),
    "false": (TokenKind.VALUE, False),
    "null": (TokenKind.VALUE, None),
}

# Regex for numeric literals: integers and decimals
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")


class ExprTokenizer:
    """Lexical tokenizer for Ledger expressions.

    Takes a string expression and yields ``Token`` objects.  The tokenizer
    supports a context flag ``op_context`` that controls whether ``/`` is
    interpreted as division (operator context) or as a regex delimiter
    (terminal context).

    Parameters
    ----------
    source : str
        The expression string to tokenize.
    """

    def __init__(self, source: str) -> None:
        self._source = source
        self._pos = 0
        self._op_context = False

    @property
    def source(self) -> str:
        return self._source

    def _peek(self) -> Optional[str]:
        """Return the next character without consuming it, or None at EOF."""
        if self._pos >= len(self._source):
            return None
        return self._source[self._pos]

    def _advance(self) -> str:
        """Consume and return the next character."""
        ch = self._source[self._pos]
        self._pos += 1
        return ch

    def _skip_whitespace(self) -> None:
        """Skip over whitespace characters."""
        while self._pos < len(self._source) and self._source[self._pos].isspace():
            self._pos += 1

    def _read_while(self, predicate) -> str:
        """Read characters while predicate(ch) is true."""
        start = self._pos
        while self._pos < len(self._source) and predicate(self._source[self._pos]):
            self._pos += 1
        return self._source[start:self._pos]

    def _make_token(
        self,
        kind: TokenKind,
        start: int,
        value: object = None,
        symbol: str = "",
    ) -> Token:
        return Token(
            kind=kind,
            value=value,
            position=start,
            length=self._pos - start,
            symbol=symbol,
        )

    def _read_string(self, delim: str, start: int) -> Token:
        """Read a string literal delimited by *delim*."""
        buf: list[str] = []
        while self._pos < len(self._source):
            ch = self._advance()
            if ch == delim:
                return self._make_token(
                    TokenKind.VALUE, start, "".join(buf), symbol=delim,
                )
            if ch == "\\" and self._pos < len(self._source):
                next_ch = self._advance()
                buf.append(next_ch)
            else:
                buf.append(ch)
        raise TokenizeError(
            f"Unterminated string literal starting at position {start}"
        )

    def _read_date_literal(self, start: int) -> Token:
        """Read a bracketed date literal ``[...]``."""
        buf: list[str] = []
        while self._pos < len(self._source):
            ch = self._advance()
            if ch == "]":
                return self._make_token(
                    TokenKind.VALUE, start, "".join(buf), symbol="[",
                )
            buf.append(ch)
        raise TokenizeError(
            f"Unterminated date literal starting at position {start}"
        )

    def _read_regex(self, start: int) -> Token:
        """Read a regex literal ``/pattern/``."""
        pat: list[str] = []
        while self._pos < len(self._source):
            ch = self._advance()
            if ch == "\\":
                # Escaped delimiter: strip backslash, keep /
                if self._pos < len(self._source) and self._source[self._pos] == "/":
                    pat.append(self._advance())
                else:
                    # Pass other escape sequences through for the regex engine
                    pat.append("\\")
            elif ch == "/":
                return self._make_token(
                    TokenKind.VALUE, start, "".join(pat), symbol="/",
                )
            else:
                pat.append(ch)
        raise TokenizeError(
            f"Unterminated regex literal starting at position {start}"
        )

    def _read_identifier(self, start: int) -> Token:
        """Read an identifier ([A-Za-z_][A-Za-z0-9_]*)."""
        word = self._read_while(lambda ch: ch.isalnum() or ch == "_")

        # Check for reserved words
        if word in _RESERVED_WORDS:
            kind, val = _RESERVED_WORDS[word]
            return self._make_token(kind, start, val, symbol=word)

        return self._make_token(TokenKind.IDENT, start, word, symbol=word)

    def _read_number(self, start: int) -> Token:
        """Read a numeric literal (integer or decimal)."""
        m = _NUMERIC_RE.match(self._source, start)
        if m:
            self._pos = m.end()
            text = m.group(0)
            if "." in text:
                return self._make_token(TokenKind.VALUE, start, float(text))
            else:
                return self._make_token(TokenKind.VALUE, start, int(text))
        raise TokenizeError(f"Invalid numeric literal at position {start}")

    def next_token(self) -> Token:
        """Read and return the next token from the source.

        After yielding a VALUE, IDENT, RPAREN, or RBRACE token the tokenizer
        automatically enters operator context (``/`` = division).  After
        other tokens it enters terminal context (``/`` = regex).
        """
        self._skip_whitespace()

        if self._pos >= len(self._source):
            return Token(kind=TokenKind.TOK_EOF, position=self._pos)

        start = self._pos
        ch = self._advance()

        tok: Token

        if ch == "(":
            tok = self._make_token(TokenKind.LPAREN, start, symbol="(")
        elif ch == ")":
            tok = self._make_token(TokenKind.RPAREN, start, symbol=")")
        elif ch == "{":
            tok = self._make_token(TokenKind.LBRACE, start, symbol="{")
        elif ch == "}":
            tok = self._make_token(TokenKind.RBRACE, start, symbol="}")

        elif ch == "&":
            if self._peek() == "&":
                self._advance()
            tok = self._make_token(TokenKind.KW_AND, start, symbol="&")
        elif ch == "|":
            if self._peek() == "|":
                self._advance()
            tok = self._make_token(TokenKind.KW_OR, start, symbol="|")

        elif ch == "!":
            if self._peek() == "=":
                self._advance()
                tok = self._make_token(TokenKind.NEQUAL, start, symbol="!=")
            elif self._peek() == "~":
                self._advance()
                tok = self._make_token(TokenKind.NMATCH, start, symbol="!~")
            else:
                tok = self._make_token(TokenKind.EXCLAM, start, symbol="!")

        elif ch == "=":
            if self._peek() == "~":
                self._advance()
                tok = self._make_token(TokenKind.MATCH, start, symbol="=~")
            elif self._peek() == "=":
                self._advance()
                tok = self._make_token(TokenKind.EQUAL, start, symbol="==")
            else:
                tok = self._make_token(TokenKind.ASSIGN, start, symbol="=")

        elif ch == "<":
            if self._peek() == "=":
                self._advance()
                tok = self._make_token(TokenKind.LESSEQ, start, symbol="<=")
            else:
                tok = self._make_token(TokenKind.LESS, start, symbol="<")

        elif ch == ">":
            if self._peek() == "=":
                self._advance()
                tok = self._make_token(TokenKind.GREATEREQ, start, symbol=">=")
            else:
                tok = self._make_token(TokenKind.GREATER, start, symbol=">")

        elif ch == "-":
            if self._peek() == ">":
                self._advance()
                tok = self._make_token(TokenKind.ARROW, start, symbol="->")
            else:
                tok = self._make_token(TokenKind.MINUS, start, symbol="-")

        elif ch == "+":
            tok = self._make_token(TokenKind.PLUS, start, symbol="+")
        elif ch == "*":
            tok = self._make_token(TokenKind.STAR, start, symbol="*")
        elif ch == "%":
            tok = self._make_token(TokenKind.KW_MOD, start, symbol="%")
        elif ch == "?":
            tok = self._make_token(TokenKind.QUERY, start, symbol="?")
        elif ch == ":":
            tok = self._make_token(TokenKind.COLON, start, symbol=":")
        elif ch == ".":
            tok = self._make_token(TokenKind.DOT, start, symbol=".")
        elif ch == ",":
            tok = self._make_token(TokenKind.COMMA, start, symbol=",")
        elif ch == ";":
            tok = self._make_token(TokenKind.SEMI, start, symbol=";")

        elif ch == "/":
            if self._op_context:
                tok = self._make_token(TokenKind.SLASH, start, symbol="/")
            else:
                tok = self._read_regex(start)

        elif ch == "[":
            tok = self._read_date_literal(start)

        elif ch in ("'", '"'):
            tok = self._read_string(ch, start)

        elif ch.isdigit():
            self._pos = start  # reset so _read_number can match from start
            tok = self._read_number(start)

        elif ch.isalpha() or ch == "_":
            self._pos = start  # reset so _read_identifier can match from start
            tok = self._read_identifier(start)

        else:
            raise TokenizeError(
                f"Unexpected character {ch!r} at position {start}"
            )

        # Update operator context: after a value, identifier, or closing
        # delimiter we expect an operator next (so / means division).
        self._op_context = tok.kind in (
            TokenKind.VALUE,
            TokenKind.IDENT,
            TokenKind.RPAREN,
            TokenKind.RBRACE,
        )

        return tok

    def tokenize(self) -> list[Token]:
        """Tokenize the entire source and return a list of tokens.

        The returned list does *not* include the final ``TOK_EOF`` token.
        """
        tokens: list[Token] = []
        while True:
            tok = self.next_token()
            if tok.kind == TokenKind.TOK_EOF:
                break
            tokens.append(tok)
        return tokens

    def __iter__(self) -> Iterator[Token]:
        """Iterate over tokens, including the final ``TOK_EOF``."""
        while True:
            tok = self.next_token()
            yield tok
            if tok.kind == TokenKind.TOK_EOF:
                break
