"""Select command: SQL-like querying of posting data.

Ported from ledger's ``select`` command.  Allows users to query journal
data with SQL-like syntax::

    select date, payee, account, amount
    select date, payee, amount where account =~ /Expenses/
    select date, payee, display_amount from postings where account =~ /Food/

The command parses a select expression into a list of fields and an
optional where clause, then iterates over all postings, extracts the
requested fields, applies the filter, and formats the output as aligned
columns.
"""

from __future__ import annotations

import re
from datetime import date as Date
from typing import Any, Optional

from muonledger.amount import Amount
from muonledger.item import ItemState
from muonledger.journal import Journal
from muonledger.post import Post

__all__ = ["select_command", "SelectError"]


class SelectError(Exception):
    """Raised when the select query is malformed."""


# ---------------------------------------------------------------------------
# Supported fields and their resolvers
# ---------------------------------------------------------------------------

# Maps field name (lowercase) to a callable (post) -> value.
# Also supports aliases.

_FIELD_ALIASES: dict[str, str] = {
    "display_amount": "amount",
    "display_total": "total",
    "desc": "payee",
    "description": "payee",
    "state": "status",
    "cleared": "status",
}

# Canonical field names
_CANONICAL_FIELDS = frozenset({
    "date",
    "payee",
    "account",
    "amount",
    "total",
    "note",
    "status",
    "commodity",
    "quantity",
    "code",
})


def _resolve_field_name(name: str) -> str:
    """Resolve a field name to its canonical form."""
    lower = name.strip().lower()
    return _FIELD_ALIASES.get(lower, lower)


def _format_date(dt: Optional[Date]) -> str:
    """Format a date as YYYY/MM/DD."""
    if dt is None:
        return ""
    return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}"


def _format_status(post: Post) -> str:
    """Format the clearing status of a posting."""
    state = post.state
    if state == ItemState.CLEARED:
        return "*"
    if state == ItemState.PENDING:
        return "!"
    # Check transaction state if post state is uncleared
    xact = post.xact
    if xact is not None:
        xact_state = xact.state
        if xact_state == ItemState.CLEARED:
            return "*"
        if xact_state == ItemState.PENDING:
            return "!"
    return ""


def _extract_field(post: Post, field: str, running_total: dict[str, Amount]) -> str:
    """Extract a single field value from a posting, returned as string.

    Parameters
    ----------
    post : Post
        The posting to extract from.
    field : str
        Canonical field name.
    running_total : dict
        Mutable dict tracking running total by commodity for 'total' field.

    Returns
    -------
    str
        The formatted field value.
    """
    xact = post.xact

    if field == "date":
        dt = xact.date if xact is not None else None
        return _format_date(dt)

    if field == "payee":
        return xact.payee if xact is not None else ""

    if field == "account":
        if post.account is not None:
            return post.account.fullname if hasattr(post.account, "fullname") else str(post.account)
        return ""

    if field == "amount":
        amt = post.amount
        if amt is None or amt.is_null():
            return "0"
        return str(amt)

    if field == "total":
        # Running total across all postings seen so far
        amt = post.amount
        if amt is not None and not amt.is_null():
            commodity_key = amt.commodity if amt.commodity else ""
            if commodity_key in running_total:
                running_total[commodity_key] = running_total[commodity_key] + amt
            else:
                running_total[commodity_key] = Amount(amt)
        # Format the total -- show all commodities
        parts = []
        for key in sorted(running_total.keys()):
            parts.append(str(running_total[key]))
        return ", ".join(parts) if parts else "0"

    if field == "note":
        # Post note, falling back to transaction note
        if post.note:
            return post.note
        if xact is not None and xact.note:
            return xact.note
        return ""

    if field == "status":
        return _format_status(post)

    if field == "commodity":
        amt = post.amount
        if amt is not None and not amt.is_null():
            sym = amt.commodity  # returns str or None
            return sym if sym else ""
        return ""

    if field == "quantity":
        amt = post.amount
        if amt is not None and not amt.is_null():
            return str(amt.quantity)
        return "0"

    if field == "code":
        if xact is not None and xact.code:
            return xact.code
        return ""

    return ""


# ---------------------------------------------------------------------------
# Where clause parsing and evaluation
# ---------------------------------------------------------------------------

_WHERE_RE_ACCOUNT = re.compile(
    r"account\s*=~\s*/([^/]*)/", re.IGNORECASE
)
_WHERE_RE_PAYEE = re.compile(
    r"payee\s*=~\s*/([^/]*)/", re.IGNORECASE
)
_WHERE_RE_NOTE = re.compile(
    r"note\s*=~\s*/([^/]*)/", re.IGNORECASE
)


class _WhereClause:
    """Represents a parsed where clause as a list of conditions combined
    with AND/OR logic."""

    def __init__(self) -> None:
        self.conditions: list[tuple[str, str, Any]] = []
        # Each condition: (field, op, value)
        #   op: "=~" (regex match), "==" (equality), "!=" (not equal),
        #       "<", ">", "<=", ">="
        self.connectives: list[str] = []  # "and" or "or" between conditions

    def matches(self, post: Post) -> bool:
        """Evaluate whether a posting matches this where clause."""
        if not self.conditions:
            return True

        results: list[bool] = []
        for field, op, value in self.conditions:
            result = self._eval_condition(post, field, op, value)
            results.append(result)

        if not results:
            return True

        # Combine with connectives; default is AND
        combined = results[0]
        for i, conn in enumerate(self.connectives):
            if i + 1 < len(results):
                if conn == "or":
                    combined = combined or results[i + 1]
                else:  # "and"
                    combined = combined and results[i + 1]
        return combined

    def _eval_condition(self, post: Post, field: str, op: str, value: Any) -> bool:
        """Evaluate a single condition."""
        field = _resolve_field_name(field)
        running_total: dict[str, Amount] = {}
        field_val = _extract_field(post, field, running_total)

        if op == "=~":
            # Regex match
            pattern = value if isinstance(value, re.Pattern) else re.compile(str(value), re.IGNORECASE)
            return bool(pattern.search(field_val))

        if op == "!~":
            pattern = value if isinstance(value, re.Pattern) else re.compile(str(value), re.IGNORECASE)
            return not bool(pattern.search(field_val))

        if op == "==":
            return field_val == str(value)

        if op == "!=":
            return field_val != str(value)

        # Numeric comparisons for amount/quantity fields
        if op in ("<", ">", "<=", ">="):
            try:
                numeric_val = _parse_numeric(field_val)
                compare_val = _parse_numeric(str(value))
                if op == "<":
                    return numeric_val < compare_val
                if op == ">":
                    return numeric_val > compare_val
                if op == "<=":
                    return numeric_val <= compare_val
                if op == ">=":
                    return numeric_val >= compare_val
            except (ValueError, TypeError):
                return False

        return False


def _parse_numeric(s: str) -> float:
    """Extract numeric value from a possibly commodity-prefixed string."""
    s = s.strip()
    if not s:
        return 0.0
    # Remove common commodity prefixes/suffixes
    cleaned = re.sub(r"[^\d.\-+]", "", s)
    if not cleaned:
        return 0.0
    return float(cleaned)


def _parse_where_clause(where_str: str) -> _WhereClause:
    """Parse a where clause string into a _WhereClause object.

    Supports:
    - ``account =~ /pattern/``
    - ``payee =~ /pattern/``
    - ``amount > 100``
    - ``field == value``
    - Multiple conditions joined by ``and`` / ``or``
    """
    clause = _WhereClause()
    if not where_str.strip():
        return clause

    # Split on " and " / " or " while preserving which connective
    parts: list[str] = []
    connectives: list[str] = []

    # Use regex to split on and/or, keeping delimiters
    tokens = re.split(r"\s+(and|or)\s+", where_str, flags=re.IGNORECASE)

    for i, tok in enumerate(tokens):
        if i % 2 == 0:
            # This is a condition
            parts.append(tok.strip())
        else:
            # This is a connective
            connectives.append(tok.strip().lower())

    for part in parts:
        cond = _parse_single_condition(part)
        if cond is not None:
            clause.conditions.append(cond)

    clause.connectives = connectives
    return clause


def _parse_single_condition(cond_str: str) -> Optional[tuple[str, str, Any]]:
    """Parse a single condition like ``account =~ /Expenses/``."""
    cond_str = cond_str.strip()
    if not cond_str:
        return None

    # Try regex match: field =~ /pattern/
    m = re.match(r"(\w+)\s*=~\s*/([^/]*)/", cond_str)
    if m:
        return (m.group(1), "=~", re.compile(m.group(2), re.IGNORECASE))

    # Try negative regex match: field !~ /pattern/
    m = re.match(r"(\w+)\s*!~\s*/([^/]*)/", cond_str)
    if m:
        return (m.group(1), "!~", re.compile(m.group(2), re.IGNORECASE))

    # Try comparison operators: field op value
    m = re.match(r"(\w+)\s*(==|!=|<=|>=|<|>)\s*(.+)", cond_str)
    if m:
        return (m.group(1), m.group(2), m.group(3).strip())

    # Bare term: treat as account =~ /term/
    if cond_str:
        return ("account", "=~", re.compile(re.escape(cond_str), re.IGNORECASE))

    return None


# ---------------------------------------------------------------------------
# Select query parsing
# ---------------------------------------------------------------------------

def _parse_select_query(query_str: str) -> tuple[list[str], Optional[str]]:
    """Parse a select query string into (fields, where_clause_str).

    Grammar::

        select FIELDS [from postings] [where CONDITION]

    Returns
    -------
    tuple[list[str], str | None]
        (list of canonical field names, where clause string or None)
    """
    query_str = query_str.strip()

    # Strip leading "select" keyword if present
    if query_str.lower().startswith("select"):
        query_str = query_str[6:].strip()

    if not query_str:
        raise SelectError("Empty select query: no fields specified")

    # Split on "where" (case-insensitive)
    where_str: Optional[str] = None
    where_match = re.search(r"\bwhere\b", query_str, re.IGNORECASE)
    if where_match:
        fields_part = query_str[:where_match.start()].strip()
        where_str = query_str[where_match.end():].strip()
    else:
        fields_part = query_str

    # Strip "from postings" if present
    from_match = re.search(r"\bfrom\s+postings\b", fields_part, re.IGNORECASE)
    if from_match:
        fields_part = fields_part[:from_match.start()].strip()

    # Parse field list
    if not fields_part:
        raise SelectError("No fields specified in select query")

    # Handle "select *" - return all fields
    if fields_part.strip() == "*":
        fields = ["date", "payee", "account", "amount"]
    else:
        raw_fields = [f.strip() for f in fields_part.split(",")]
        fields = []
        for f in raw_fields:
            if not f:
                continue
            canonical = _resolve_field_name(f)
            if canonical not in _CANONICAL_FIELDS:
                raise SelectError(f"Unknown field: {f}")
            fields.append(canonical)

    if not fields:
        raise SelectError("No valid fields specified in select query")

    return fields, where_str


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format rows as an aligned table with headers.

    Parameters
    ----------
    headers : list[str]
        Column headers.
    rows : list[list[str]]
        Data rows, each a list of string values.

    Returns
    -------
    str
        The formatted table with aligned columns.
    """
    if not rows:
        return ""

    num_cols = len(headers)

    # Compute column widths (minimum of header width and max data width)
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < num_cols:
                col_widths[i] = max(col_widths[i], len(val))

    # Build separator
    sep_parts = ["-" * w for w in col_widths]
    separator = "  ".join(sep_parts)

    # Build header line
    header_parts = []
    for i, h in enumerate(headers):
        header_parts.append(h.ljust(col_widths[i]))
    header_line = "  ".join(header_parts)

    # Build data lines
    lines = [header_line, separator]
    for row in rows:
        parts = []
        for i in range(num_cols):
            val = row[i] if i < len(row) else ""
            parts.append(val.ljust(col_widths[i]))
        lines.append("  ".join(parts))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

def select_command(
    journal: Journal,
    query_str: str | list[str],
    options: Optional[dict[str, Any]] = None,
) -> str:
    """Execute a select query against a journal.

    Parameters
    ----------
    journal : Journal
        A populated journal with transactions and postings.
    query_str : str or list[str]
        The select query, e.g. ``"date, payee, amount where account =~ /Expenses/"``.
        If a list, the elements are joined with spaces.
    options : dict | None
        Optional settings (reserved for future use).

    Returns
    -------
    str
        The formatted tabular output.

    Raises
    ------
    SelectError
        If the query is malformed.
    """
    if isinstance(query_str, list):
        query_str = " ".join(query_str)

    fields, where_str = _parse_select_query(query_str)

    # Parse where clause if present
    where_clause: Optional[_WhereClause] = None
    if where_str:
        where_clause = _parse_where_clause(where_str)

    # Collect rows
    rows: list[list[str]] = []
    running_total: dict[str, Amount] = {}

    for xact in journal.xacts:
        for post in xact.posts:
            # Apply where filter
            if where_clause is not None and not where_clause.matches(post):
                continue

            row: list[str] = []
            for field in fields:
                val = _extract_field(post, field, running_total)
                row.append(val)
            rows.append(row)

    # Format headers from field names
    headers = [f.capitalize() if f != "display_amount" else "Amount" for f in fields]

    return _format_table(headers, rows)
