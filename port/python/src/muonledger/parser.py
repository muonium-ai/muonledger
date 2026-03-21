"""Textual journal parser for Ledger-format files.

Ported from ledger's ``textual.cc`` / ``textual_xacts.cc``.  The
:class:`TextualParser` reads plain-text journal files (or strings) and
populates a :class:`Journal` with :class:`Transaction` and :class:`Post`
objects.

The parser handles the core Ledger grammar:

  - Transaction header lines: ``DATE [=AUX_DATE] [STATE] [(CODE)] PAYEE [; NOTE]``
  - Posting lines: ``  [STATE] ACCOUNT  AMOUNT [@ COST] [; NOTE]``
  - Comments: lines starting with ``;``, ``#``, ``%``, ``|``, or ``*``
  - Metadata in comments: ``; key: value`` and ``; :tag1:tag2:``
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

            # Directives we skip for now (apply tag, end apply, etc.)
            if first_char in "!@" or line.startswith("apply ") or line.startswith("end "):
                i += 1
                continue

            # Skip other directives: N, D, P, Y, A, C, etc.
            if first_char in "NDPYACndpyac" and len(line) > 1 and line[1] == " ":
                i += 1
                continue

            # Automated transactions (=) and periodic transactions (~)
            if first_char in "=~":
                # Skip the header line and all indented lines
                i += 1
                while i < len(lines) and lines[i] and (
                    lines[i][0] in " \t" or lines[i][0] == ";"
                ):
                    i += 1
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

        journal.was_loaded = True
        return count

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

        # Look up or create the account in the journal
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
