"""Textual journal parser for Ledger-format files.

Ported from ledger's ``textual.cc`` / ``textual_xacts.cc`` /
``textual_directives.cc``.  The :class:`TextualParser` reads plain-text
journal files (or strings) and populates a :class:`Journal` with
:class:`Transaction` and :class:`Post` objects.

The parser handles the core Ledger grammar:

  - Transaction header lines: ``DATE [=AUX_DATE] [STATE] [(CODE)] PAYEE [; NOTE]``
  - Posting lines: ``  [STATE] ACCOUNT  AMOUNT [@ COST] [; NOTE]``
  - Comments: lines starting with ``;``, ``#``, ``%``, ``|``, or ``*``
  - Metadata in comments: ``; key: value`` and ``; :tag1:tag2:``
  - Directives: ``account``, ``commodity``, ``include``, ``comment``/``end comment``,
    ``P`` (price), ``D`` (default commodity), ``Y``/``year`` (default year)
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Iterator, Optional, Union

from muonledger.amount import Amount
from muonledger.item import ItemState, Position
from muonledger.journal import Journal
from muonledger.post import (
    POST_COST_IN_FULL,
    POST_MUST_BALANCE,
    POST_VIRTUAL,
    Post,
)
from muonledger.xact import Transaction
from muonledger.auto_xact import AutomatedTransaction, apply_automated_transactions

__all__ = ["TextualParser", "ParseError"]


class ParseError(Exception):
    """Raised when the parser encounters invalid journal syntax."""

    def __init__(self, message: str, line_num: int = 0, source: str = ""):
        self.line_num = line_num
        self.source = source
        loc = f"{source}:{line_num}" if source else f"line {line_num}"
        super().__init__(f"{loc}: {message}")


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})"
)


def _parse_date(text: str) -> date:
    """Parse a date in YYYY/MM/DD or YYYY-MM-DD format."""
    m = _DATE_RE.match(text.strip())
    if not m:
        raise ValueError(f"Cannot parse date: {text!r}")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ---------------------------------------------------------------------------
# Cost splitting helper
# ---------------------------------------------------------------------------

def _split_amount_and_cost(text: str) -> tuple[str, Optional[str], bool]:
    """Split an amount+cost string at ``@`` or ``@@``.

    Returns (amount_text, cost_text_or_None, is_total_cost).

    We must be careful not to split inside a quoted commodity name or
    at an ``@`` that is part of a commodity symbol.
    """
    # Walk character by character, respecting quotes
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote and ch == '@':
            # Check for @@
            if i + 1 < len(text) and text[i + 1] == '@':
                return text[:i].rstrip(), text[i + 2:].lstrip(), True
            else:
                return text[:i].rstrip(), text[i + 1:].lstrip(), False
        i += 1
    return text, None, False


# ---------------------------------------------------------------------------
# Tag parsing in comments
# ---------------------------------------------------------------------------

_TAG_LINE_RE = re.compile(r"^:(.+):$")
_META_RE = re.compile(r"^(\S+?):\s*(.*)$")


def _parse_comment_metadata(
    comment: str,
) -> tuple[Optional[str], dict[str, object]]:
    """Parse metadata from a comment string.

    Returns (clean_note_or_None, metadata_dict).
    Tags like ``:tag1:tag2:`` produce ``{tag1: True, tag2: True}``.
    Key-value pairs like ``key: value`` produce ``{key: value}``.
    """
    text = comment.strip()
    if not text:
        return None, {}

    metadata: dict[str, object] = {}

    # Check for tag line: :tag1:tag2:
    tag_match = _TAG_LINE_RE.match(text)
    if tag_match:
        tags = tag_match.group(1).split(":")
        for tag in tags:
            tag = tag.strip()
            if tag:
                metadata[tag] = True
        return None, metadata

    # Check for key: value metadata
    meta_match = _META_RE.match(text)
    if meta_match:
        key = meta_match.group(1)
        value = meta_match.group(2).strip()
        metadata[key] = value if value else True
        return None, metadata

    # Plain note text
    return text, {}


# ---------------------------------------------------------------------------
# TextualParser
# ---------------------------------------------------------------------------


class TextualParser:
    """Parse Ledger-format textual journal files.

    Usage::

        journal = Journal()
        parser = TextualParser()
        count = parser.parse(Path("ledger.dat"), journal)
        # or
        count = parser.parse_string(text, journal)
    """

    def parse(self, source: Union[str, Path], journal: Journal) -> int:
        """Parse a journal file and populate *journal*.

        Parameters
        ----------
        source : str | Path
            Path to the journal file.
        journal : Journal
            The journal to populate.

        Returns
        -------
        int
            Number of transactions parsed.
        """
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        journal.sources.append(str(path))
        return self._parse_text(text, journal, source_name=str(path))

    def parse_string(self, text: str, journal: Journal) -> int:
        """Parse journal data from a string.

        Parameters
        ----------
        text : str
            The journal text.
        journal : Journal
            The journal to populate.

        Returns
        -------
        int
            Number of transactions parsed.
        """
        return self._parse_text(text, journal, source_name="<string>")

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _parse_text(
        self, text: str, journal: Journal, source_name: str = ""
    ) -> int:
        """Core parse loop: iterate lines and build transactions."""
        lines = text.split("\n")
        count = 0
        i = 0

        while i < len(lines):
            line = lines[i]
            line_num = i + 1  # 1-based

            # Strip trailing whitespace/CR
            line = line.rstrip("\r\n")

            # Empty line - skip
            if not line or line.isspace():
                i += 1
                continue

            first_char = line[0]

            # Comment lines
            if first_char in ";#%|*":
                i += 1
                continue

            # Multi-line comment block: comment ... end comment
            if line.rstrip() == "comment" or line.startswith("comment "):
                i += 1
                while i < len(lines):
                    cline = lines[i].rstrip("\r\n")
                    if cline.strip() == "end comment":
                        i += 1
                        break
                    i += 1
                continue

            # Test blocks: skip "test ..." through "end test"
            if line.startswith("test ") or line.rstrip() == "test":
                i += 1
                while i < len(lines):
                    tline = lines[i].rstrip("\r\n")
                    if tline.strip() == "end test":
                        i += 1
                        break
                    i += 1
                continue

            # Prefix characters ! and @ are ignored (ledger compatibility)
            if first_char in "!@":
                line = line[1:]
                first_char = line[0] if line else ""
                if not line or line.isspace():
                    i += 1
                    continue

            # apply account / apply tag directives
            if line.startswith("apply account "):
                prefix = line[len("apply account "):].strip()
                if prefix:
                    journal.apply_account_stack.append(prefix)
                i += 1
                continue
            if line.startswith("apply tag "):
                tag = line[len("apply tag "):].strip()
                if tag:
                    journal.apply_tag_stack.append(tag)
                i += 1
                continue

            # end apply account / end apply tag
            if line.startswith("end apply account"):
                if journal.apply_account_stack:
                    journal.apply_account_stack.pop()
                i += 1
                continue
            if line.startswith("end apply tag"):
                if journal.apply_tag_stack:
                    journal.apply_tag_stack.pop()
                i += 1
                continue
            if line.startswith("end apply"):
                # Generic end apply - pop whichever stack was last used
                i += 1
                continue

            # alias directive
            if line.startswith("alias "):
                self._alias_directive(line, journal)
                i += 1
                continue

            # bucket directive
            if line.startswith("bucket "):
                self._bucket_directive(line, journal)
                i += 1
                continue

            # tag directive (block)
            if line.startswith("tag "):
                i = self._tag_directive(lines, i, journal)
                continue

            # payee directive (block)
            if line.startswith("payee "):
                i = self._payee_directive(lines, i, journal)
                continue

            # define directive
            if line.startswith("define "):
                self._define_directive(line, journal)
                i += 1
                continue

            # account directive
            if line.startswith("account "):
                i = self._account_directive(lines, i, journal)
                continue

            # commodity directive
            if line.startswith("commodity "):
                i = self._commodity_directive(lines, i, journal)
                continue

            # include directive
            if line.startswith("include "):
                i = self._include_directive(lines, i, journal, source_name)
                continue

            # P price directive
            if first_char == "P" and len(line) > 1 and line[1] == " ":
                self._price_xact_directive(line, journal, line_num, source_name)
                i += 1
                continue

            # D default commodity directive
            if first_char == "D" and len(line) > 1 and line[1] == " ":
                self._default_commodity_directive(line, journal)
                i += 1
                continue

            # Y / year directive
            if first_char == "Y" and len(line) > 1 and line[1] == " ":
                self._year_directive(line, journal)
                i += 1
                continue
            if line.startswith("year "):
                self._year_directive(line, journal)
                i += 1
                continue

            # N directive: no-market commodity
            if first_char in "Nn" and len(line) > 1 and line[1] == " ":
                self._no_market_directive(line, journal)
                i += 1
                continue

            # A directive: bucket (short form)
            if first_char in "Aa" and len(line) > 1 and line[1] == " ":
                self._bucket_directive(line, journal)
                i += 1
                continue

            # C directive: currency conversion (skip for now)
            if first_char in "Cc" and len(line) > 1 and line[1] == " ":
                i += 1
                continue

            # Periodic transactions (~) - skip for now
            if first_char == "~":
                i += 1
                while i < len(lines) and lines[i] and (
                    lines[i][0] in " \t" or lines[i][0] == ";"
                ):
                    i += 1
                continue

            # Automated transactions (=)
            if first_char == "=":
                auto_xact, end_i = self._parse_auto_xact(
                    lines, i, journal, source_name
                )
                if auto_xact is not None:
                    journal.auto_xacts.append(auto_xact)
                i = end_i
                continue

            # Transaction: starts with a digit (date)
            if first_char.isdigit():
                xact, end_i = self._parse_xact(
                    lines, i, journal, source_name
                )
                if xact is not None:
                    if journal.add_xact(xact):
                        count += 1
                i = end_i
                continue

            # Indented line outside a transaction context - skip
            if first_char in " \t":
                i += 1
                continue

            # Unknown line - skip
            i += 1

        # Apply automated transactions after all parsing is complete
        apply_automated_transactions(journal)

        journal.was_loaded = True
        return count

    # ------------------------------------------------------------------
    # Directive handlers
    # ------------------------------------------------------------------

    def _consume_sub_directives(
        self, lines: list[str], start: int
    ) -> tuple[list[tuple[str, str]], int]:
        """Consume indented sub-directive lines after a block directive.

        Returns a list of (keyword, argument) pairs and the next line index.
        """
        sub_directives: list[tuple[str, str]] = []
        i = start
        while i < len(lines):
            sline = lines[i].rstrip("\r\n")
            if not sline or sline[0] not in " \t":
                break
            stripped = sline.lstrip()
            if not stripped or stripped.startswith(";"):
                i += 1
                continue
            # Split into keyword and argument
            parts = stripped.split(None, 1)
            keyword = parts[0]
            argument = parts[1] if len(parts) > 1 else ""
            sub_directives.append((keyword, argument))
            i += 1
        return sub_directives, i

    def _account_directive(
        self, lines: list[str], start: int, journal: Journal
    ) -> int:
        """Parse an ``account`` directive with optional sub-directives.

        Registers the account in the journal and processes sub-directives
        like ``note``, ``alias``, and ``default``.

        Returns the next line index.
        """
        line = lines[start].rstrip("\r\n")
        account_name = line[len("account "):].strip()
        account = journal.find_account(account_name)

        sub_directives, next_i = self._consume_sub_directives(lines, start + 1)

        for keyword, argument in sub_directives:
            if keyword == "note":
                account.note = argument
            elif keyword == "alias":
                alias_name = argument.strip()
                if alias_name:
                    journal.account_aliases[alias_name] = account
            elif keyword == "default":
                journal.bucket = account

        return next_i

    def _commodity_directive(
        self, lines: list[str], start: int, journal: Journal
    ) -> int:
        """Parse a ``commodity`` directive with optional sub-directives.

        Registers the commodity in the pool and processes sub-directives
        like ``format``, ``note``, and ``default``.

        Returns the next line index.
        """
        line = lines[start].rstrip("\r\n")
        symbol = line[len("commodity "):].strip()
        commodity = journal.commodity_pool.find_or_create(symbol)

        sub_directives, next_i = self._consume_sub_directives(lines, start + 1)

        for keyword, argument in sub_directives:
            if keyword == "format":
                # Store the format string; parse it to learn display style
                commodity.note = commodity.note  # preserve existing note
                # Learn style from the format amount
                fmt_amount = Amount(argument.strip())
                if fmt_amount.commodity:
                    learned = journal.commodity_pool.find_or_create(
                        fmt_amount.commodity
                    )
                    learned.precision = fmt_amount.precision
            elif keyword == "note":
                commodity.note = argument
            elif keyword == "default":
                journal.commodity_pool.default_commodity = commodity
            elif keyword == "alias":
                alias_name = argument.strip()
                if alias_name:
                    # Register alias as pointing to the same commodity
                    journal.commodity_pool._commodities[alias_name] = commodity

        return next_i

    def _include_directive(
        self,
        lines: list[str],
        start: int,
        journal: Journal,
        source_name: str,
    ) -> int:
        """Parse an ``include`` directive.

        Resolves the path relative to the current file and recursively
        parses the included file.

        Returns the next line index.
        """
        line = lines[start].rstrip("\r\n")
        include_path = line[len("include "):].strip()

        # Strip surrounding quotes
        if (
            len(include_path) >= 2
            and include_path[0] in ('"', "'")
            and include_path[-1] == include_path[0]
        ):
            include_path = include_path[1:-1]

        # Resolve relative to current file's directory
        if source_name and source_name != "<string>":
            parent_dir = Path(source_name).parent
            resolved = parent_dir / include_path
        else:
            resolved = Path(include_path)

        resolved = resolved.resolve()

        if not resolved.exists():
            raise ParseError(
                f"File to include was not found: {resolved}",
                start + 1,
                source_name,
            )

        self.parse(resolved, journal)
        return start + 1

    def _price_xact_directive(
        self,
        line: str,
        journal: Journal,
        line_num: int,
        source_name: str,
    ) -> None:
        """Parse a ``P`` price directive.

        Format: ``P DATE COMMODITY PRICE``

        Stores (date, commodity_symbol, price_amount) in ``journal.prices``.
        """
        rest = line[1:].lstrip()
        # Parse the date
        date_match = _DATE_RE.match(rest)
        if not date_match:
            raise ParseError("Expected date in P directive", line_num, source_name)

        price_date = date(
            int(date_match.group(1)),
            int(date_match.group(2)),
            int(date_match.group(3)),
        )
        rest = rest[date_match.end():].lstrip()

        # Parse the commodity symbol (word until whitespace)
        parts = rest.split(None, 1)
        if len(parts) < 2:
            raise ParseError(
                "Expected commodity and price in P directive",
                line_num,
                source_name,
            )
        commodity_symbol = parts[0]
        price_text = parts[1].strip()
        price_amount = Amount(price_text)

        journal.prices.append((price_date, commodity_symbol, price_amount))

    def _default_commodity_directive(
        self, line: str, journal: Journal
    ) -> None:
        """Parse a ``D`` default commodity directive.

        Format: ``D AMOUNT`` where AMOUNT defines the default commodity format.
        """
        rest = line[1:].lstrip()
        if rest:
            amt = Amount(rest)
            if amt.commodity:
                commodity = journal.commodity_pool.find_or_create(amt.commodity)
                commodity.precision = amt.precision
                journal.commodity_pool.default_commodity = commodity

    def _year_directive(self, line: str, journal: Journal) -> None:
        """Parse a ``Y`` or ``year`` directive.

        Format: ``Y YEAR`` or ``year YEAR``
        """
        if line.startswith("year "):
            rest = line[len("year "):].strip()
        else:
            rest = line[1:].lstrip()
        try:
            journal.default_year = int(rest)
        except ValueError:
            pass  # silently ignore invalid year

    def _alias_directive(self, line: str, journal: Journal) -> None:
        """Parse an ``alias`` directive: ``alias ALIAS=ACCOUNT``."""
        rest = line[len("alias "):].strip()
        if "=" in rest:
            alias_name, account_name = rest.split("=", 1)
            alias_name = alias_name.strip()
            account_name = account_name.strip()
            if alias_name and account_name:
                account = journal.find_account(account_name, auto_create=True)
                journal.account_aliases[alias_name] = account

    def _bucket_directive(self, line: str, journal: Journal) -> None:
        """Parse a ``bucket`` or ``A`` directive."""
        parts = line.split(None, 1)
        account_name = parts[1].strip() if len(parts) > 1 else ""
        if account_name:
            journal.bucket = journal.find_account(
                account_name, auto_create=True
            )

    def _tag_directive(
        self, lines: list[str], start: int, journal: Journal
    ) -> int:
        """Parse a ``tag`` directive with optional sub-directives."""
        line = lines[start].rstrip("\r\n")
        tag_name = line[len("tag "):].strip()
        if tag_name:
            journal.tag_declarations.append(tag_name)
        _, next_i = self._consume_sub_directives(lines, start + 1)
        return next_i

    def _payee_directive(
        self, lines: list[str], start: int, journal: Journal
    ) -> int:
        """Parse a ``payee`` directive with optional sub-directives."""
        line = lines[start].rstrip("\r\n")
        payee_name = line[len("payee "):].strip()
        if payee_name:
            journal.payee_declarations.append(payee_name)
        _, next_i = self._consume_sub_directives(lines, start + 1)
        return next_i

    def _no_market_directive(self, line: str, journal: Journal) -> None:
        """Parse an ``N`` no-market commodity directive."""
        symbol = line[1:].strip()
        if symbol:
            journal.no_market_commodities.append(symbol)

    def _define_directive(self, line: str, journal: Journal) -> None:
        """Parse a ``define`` directive: ``define VAR=EXPR``."""
        rest = line[len("define "):].strip()
        if "=" in rest:
            var_name, expr = rest.split("=", 1)
            var_name = var_name.strip()
            expr = expr.strip()
            if var_name:
                journal.defines[var_name] = expr

    def _parse_auto_xact(
        self,
        lines: list[str],
        start: int,
        journal: Journal,
        source_name: str,
    ) -> tuple[Optional[AutomatedTransaction], int]:
        """Parse an automated transaction starting at line index *start*.

        The header line has the form ``= PREDICATE``.
        Returns (auto_xact_or_None, next_line_index).
        """
        line = lines[start].rstrip("\r\n")
        line_num = start + 1

        # Strip the '=' prefix and get the predicate expression
        predicate_expr = line[1:].strip()
        if not predicate_expr:
            # Empty predicate - skip
            i = start + 1
            while i < len(lines) and lines[i] and (
                lines[i][0] in " \t" or lines[i][0] == ";"
            ):
                i += 1
            return None, i

        auto_xact = AutomatedTransaction(predicate_expr)

        # Parse posting lines
        i = start + 1
        while i < len(lines):
            pline = lines[i].rstrip("\r\n")

            # Blank line or non-indented line ends the block
            if not pline or pline[0] not in " \t":
                break

            pline_stripped = pline.lstrip()

            # Comment line - skip
            if pline_stripped.startswith(";"):
                i += 1
                continue

            # Parse as posting
            post = self._parse_post(pline, i + 1, journal, source_name)
            if post is not None:
                auto_xact.posts.append(post)

            i += 1

        return auto_xact, i

    def _parse_xact(
        self,
        lines: list[str],
        start: int,
        journal: Journal,
        source_name: str,
    ) -> tuple[Optional[Transaction], int]:
        """Parse a complete transaction starting at line index *start*.

        Returns (transaction_or_None, next_line_index).
        """
        line = lines[start].rstrip("\r\n")
        line_num = start + 1

        # -- Parse the header line --
        rest = line

        # 1. Parse date(s): DATE[=AUX_DATE]
        date_match = _DATE_RE.match(rest)
        if not date_match:
            raise ParseError("Expected date", line_num, source_name)

        primary_date = date(
            int(date_match.group(1)),
            int(date_match.group(2)),
            int(date_match.group(3)),
        )
        rest = rest[date_match.end():]

        aux_date: Optional[date] = None
        if rest.startswith("="):
            rest = rest[1:]
            aux_match = _DATE_RE.match(rest)
            if not aux_match:
                raise ParseError(
                    "Expected auxiliary date after '='", line_num, source_name
                )
            aux_date = date(
                int(aux_match.group(1)),
                int(aux_match.group(2)),
                int(aux_match.group(3)),
            )
            rest = rest[aux_match.end():]

        rest = rest.lstrip()

        # 2. Parse optional state marker
        state = ItemState.UNCLEARED
        if rest and rest[0] == "*":
            state = ItemState.CLEARED
            rest = rest[1:].lstrip()
        elif rest and rest[0] == "!":
            state = ItemState.PENDING
            rest = rest[1:].lstrip()

        # 3. Parse optional code: (CODE)
        code: Optional[str] = None
        if rest and rest[0] == "(":
            close = rest.find(")")
            if close != -1:
                code = rest[1:close]
                rest = rest[close + 1:].lstrip()

        # 4. Parse payee and optional inline note
        xact_note: Optional[str] = None
        xact_metadata: dict[str, object] = {}
        semi_pos = rest.find(";")
        if semi_pos != -1:
            payee = rest[:semi_pos].rstrip()
            comment_text = rest[semi_pos + 1:].strip()
            note_text, meta = _parse_comment_metadata(comment_text)
            xact_note = note_text if note_text else comment_text
            xact_metadata.update(meta)
        else:
            payee = rest.rstrip()

        # Build the transaction
        xact = Transaction(payee=payee)
        xact.date = primary_date
        xact.date_aux = aux_date
        xact.state = state
        xact.code = code
        xact.note = xact_note
        xact.position = Position(
            pathname=source_name,
            beg_line=line_num,
        )
        for k, v in xact_metadata.items():
            xact.set_tag(k, v)

        # Apply tags from apply tag stack
        for tag in journal.apply_tag_stack:
            xact.set_tag(tag, True)

        # -- Parse posting lines --
        i = start + 1
        while i < len(lines):
            pline = lines[i].rstrip("\r\n")

            # Blank line or non-indented line ends the transaction
            if not pline or not pline[0] in " \t":
                # But check for comment lines that are part of the transaction
                # (comments between postings, starting with ; after whitespace)
                break

            pline_stripped = pline.lstrip()

            # Comment line attached to the transaction or previous posting
            if pline_stripped.startswith(";"):
                comment_text = pline_stripped[1:].strip()
                note_text, meta = _parse_comment_metadata(comment_text)

                # Apply metadata to the last posting if one exists,
                # otherwise to the transaction
                if xact.posts:
                    target = xact.posts[-1]
                else:
                    target = xact

                for k, v in meta.items():
                    target.set_tag(k, v)

                if note_text:
                    if target.note:
                        target.note += "\n" + note_text
                    else:
                        target.note = note_text

                i += 1
                continue

            # Parse as posting
            post = self._parse_post(pline, i + 1, journal, source_name)
            if post is not None:
                xact.add_post(post)

            i += 1

        # Set end line
        if xact.position is not None:
            xact.position.end_line = i

        return xact, i

    def _parse_post(
        self,
        line: str,
        line_num: int,
        journal: Journal,
        source_name: str,
    ) -> Optional[Post]:
        """Parse a single posting line.

        The line starts with whitespace (already confirmed by caller).
        """
        rest = line.lstrip()
        if not rest:
            return None

        # 1. Optional state marker on the posting itself
        post_state = ItemState.UNCLEARED
        if rest[0] == "*":
            post_state = ItemState.CLEARED
            rest = rest[1:].lstrip()
        elif rest[0] == "!":
            post_state = ItemState.PENDING
            rest = rest[1:].lstrip()

        # 2. Detect virtual account brackets
        is_virtual = False
        must_balance = True  # real postings must balance
        if rest[0] == "(":
            # Virtual posting (does not need to balance)
            is_virtual = True
            must_balance = False
            close = rest.find(")")
            if close == -1:
                raise ParseError(
                    "Expected ')' for virtual account", line_num, source_name
                )
            account_name = rest[1:close].strip()
            rest = rest[close + 1:]
        elif rest[0] == "[":
            # Balanced virtual posting (must balance)
            is_virtual = True
            must_balance = True
            close = rest.find("]")
            if close == -1:
                raise ParseError(
                    "Expected ']' for balanced virtual account",
                    line_num,
                    source_name,
                )
            account_name = rest[1:close].strip()
            rest = rest[close + 1:]
        else:
            # Real account: name ends at two consecutive spaces, tab, or
            # semicolon.  We scan for these delimiters.
            account_name, rest = self._split_account_and_rest(rest)

        # Apply account prefix from apply account stack
        if journal.apply_account_stack:
            prefix = ":".join(journal.apply_account_stack)
            account_name = f"{prefix}:{account_name}"

        # Resolve alias or look up/create the account in the journal
        if account_name in journal.account_aliases:
            account = journal.account_aliases[account_name]
        else:
            account = journal.find_account(account_name)

        # 3. Parse inline comment (if rest starts with ;)
        rest = rest.lstrip()
        post_note: Optional[str] = None
        post_metadata: dict[str, object] = {}

        # Separate amount portion from inline comment
        amount_text = ""
        if rest:
            semi_pos = self._find_comment_start(rest)
            if semi_pos != -1:
                amount_text = rest[:semi_pos].rstrip()
                comment_text = rest[semi_pos + 1:].strip()
                note_text, meta = _parse_comment_metadata(comment_text)
                post_note = note_text if note_text else (comment_text if comment_text else None)
                post_metadata.update(meta)
            else:
                amount_text = rest.rstrip()

        # 4. Parse amount and optional cost
        amount: Optional[Amount] = None
        cost: Optional[Amount] = None
        cost_is_total = False
        post_flags = 0

        if is_virtual:
            post_flags |= POST_VIRTUAL
            if must_balance:
                post_flags |= POST_MUST_BALANCE

        if amount_text:
            # Split off cost (@, @@)
            amt_part, cost_part, cost_is_total = _split_amount_and_cost(
                amount_text
            )

            if amt_part:
                amount = Amount(amt_part)

            if cost_part:
                cost_amount = Amount(cost_part)
                if cost_is_total:
                    post_flags |= POST_COST_IN_FULL
                    # For total cost, compute per-unit cost for the cost field
                    # The cost stored is the total cost
                    cost = cost_amount
                else:
                    # Per-unit cost: total cost = amount * cost_per_unit
                    if amount is not None and not amount.is_null():
                        qty = abs(amount.quantity)
                        total_cost = Amount(cost_amount)
                        total_cost._quantity = cost_amount._require_quantity() * qty
                        cost = total_cost
                    else:
                        cost = cost_amount

        # Build the Post
        post = Post(
            account=account,
            amount=amount,
            flags=post_flags,
            note=post_note,
        )
        post.state = post_state
        post.cost = cost
        post.position = Position(
            pathname=source_name,
            beg_line=line_num,
        )
        for k, v in post_metadata.items():
            post.set_tag(k, v)

        # Register the posting with the account
        if account is not None:
            account.add_post(post)

        return post

    @staticmethod
    def _split_account_and_rest(text: str) -> tuple[str, str]:
        """Split a posting line into account name and the remainder.

        Account names end at:
        - Two consecutive spaces
        - A tab character
        - A semicolon (inline comment)
        - End of line
        """
        i = 0
        while i < len(text):
            ch = text[i]
            # Tab separates account from amount
            if ch == "\t":
                return text[:i].rstrip(), text[i + 1:]
            # Two consecutive spaces
            if ch == " " and i + 1 < len(text) and text[i + 1] == " ":
                return text[:i].rstrip(), text[i + 2:]
            # Semicolon starts a comment
            if ch == ";":
                return text[:i].rstrip(), text[i:]
            i += 1
        # Entire line is the account name (no amount)
        return text.rstrip(), ""

    @staticmethod
    def _find_comment_start(text: str) -> int:
        """Find the position of an inline comment ``;`` in amount text.

        Returns -1 if no comment found. Respects quoted strings.
        """
        in_quote = False
        for i, ch in enumerate(text):
            if ch == '"':
                in_quote = not in_quote
            elif not in_quote and ch == ";":
                return i
        return -1
