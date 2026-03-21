"""Core CSV parsing and conversion logic for importing bank statements.

Reads CSV files and converts rows into ledger-format transaction dicts,
then formats them as standard journal text.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


__all__ = [
    "CsvRules",
    "parse_csv",
    "format_transaction",
    "format_transactions",
    "clean_amount",
    "parse_date",
    "auto_detect_columns",
]

# Common header names mapped to field roles.
_HEADER_PATTERNS: dict[str, list[str]] = {
    "date": ["date", "trans date", "transaction date", "posted", "post date", "posting date"],
    "payee": ["description", "payee", "memo", "name", "merchant", "narrative"],
    "amount": ["amount", "sum", "total", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "out", "charge"],
    "credit": ["credit", "deposit", "deposits", "in", "payment"],
    "account": ["account", "category", "type"],
    "note": ["note", "notes", "reference", "ref", "check", "check number"],
}


@dataclass
class CsvRules:
    """Configuration for mapping CSV columns to ledger fields.

    Fields can be set as column indices (int) or column header names (str).
    When set to ``None``, auto-detection from headers is attempted.
    """

    date_field: int | str | None = None
    payee_field: int | str | None = None
    amount_field: int | str | None = None
    debit_field: int | str | None = None
    credit_field: int | str | None = None
    account_field: int | str | None = None
    note_field: int | str | None = None

    skip_lines: int = 0
    date_format: str | None = None
    default_account: str = "Expenses:Unknown"
    bank_account: str = "Assets:Bank:Checking"
    currency: str = ""
    invert_amount: bool = False


def auto_detect_columns(headers: list[str]) -> dict[str, int]:
    """Detect field-to-column-index mapping from header names.

    Returns a dict like ``{"date": 0, "payee": 1, "amount": 2, ...}``.
    """
    mapping: dict[str, int] = {}
    normalised = [h.strip().lower() for h in headers]
    for field_name, patterns in _HEADER_PATTERNS.items():
        for idx, header in enumerate(normalised):
            if header in patterns:
                mapping[field_name] = idx
                break
    return mapping


def _resolve_field(field_spec: int | str | None, headers: list[str] | None) -> int | None:
    """Resolve a field spec (int index, str header name, or None) to an index."""
    if field_spec is None:
        return None
    if isinstance(field_spec, int):
        return field_spec
    if headers is not None:
        normalised = [h.strip().lower() for h in headers]
        target = field_spec.strip().lower()
        for idx, h in enumerate(normalised):
            if h == target:
                return idx
    return None


def clean_amount(raw: str) -> str:
    """Clean a raw amount string: strip currency symbols, commas, handle parens.

    Returns a string suitable for ``float()`` conversion.

    Examples:
        >>> clean_amount("$1,234.56")
        '1234.56'
        >>> clean_amount("($50.00)")
        '-50.00'
        >>> clean_amount("-$100")
        '-100'
    """
    s = raw.strip()
    if not s:
        return "0"

    # Detect negative from parentheses: (123.45) -> -123.45
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    # Detect leading minus before currency symbol
    if s.startswith("-"):
        negative = not negative
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    # Strip currency symbols and whitespace
    s = re.sub(r"[^\d.,\-+]", "", s)

    # Remove commas (thousands separators)
    s = s.replace(",", "")

    # Handle trailing minus (some formats)
    if s.endswith("-"):
        negative = not negative
        s = s[:-1]

    if not s:
        return "0"

    if negative:
        s = "-" + s

    return s


# Common date formats to try when auto-detecting.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y%m%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
]


def parse_date(raw: str, fmt: str | None = None) -> datetime:
    """Parse a date string using the given format, or try common formats.

    Returns a :class:`datetime` object.

    Raises:
        ValueError: if no format matches.
    """
    s = raw.strip()
    if fmt:
        return datetime.strptime(s, fmt)

    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: {raw!r}")


def _get_cell(row: list[str], idx: int | None) -> str:
    """Safely retrieve a cell value by index, returning empty string if missing."""
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return row[idx].strip()


def parse_csv(
    file_content: str,
    rules: CsvRules | None = None,
) -> list[dict[str, Any]]:
    """Parse CSV content into a list of transaction dicts.

    Each dict has keys: ``date`` (datetime), ``payee`` (str),
    ``amount`` (str, cleaned number), ``account`` (str or empty),
    ``note`` (str or empty).
    """
    if rules is None:
        rules = CsvRules()

    lines = file_content.splitlines(keepends=True)

    # Skip leading lines as configured.
    if rules.skip_lines > 0:
        lines = lines[rules.skip_lines:]

    if not lines:
        return []

    content = "".join(lines)
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        return []

    # Determine if first row is a header by checking if any field spec is a
    # string, or by attempting auto-detection.
    headers: list[str] | None = None
    data_start = 0

    # Check if the first row looks like headers (non-numeric first cell).
    first_row = rows[0]
    has_string_fields = any(
        isinstance(getattr(rules, f), str)
        for f in [
            "date_field", "payee_field", "amount_field",
            "debit_field", "credit_field", "account_field", "note_field",
        ]
    )

    # Auto-detect: treat first row as headers if any cell matches known header names
    first_row_lower = [c.strip().lower() for c in first_row]
    looks_like_header = any(
        cell in patterns
        for patterns in _HEADER_PATTERNS.values()
        for cell in first_row_lower
    )

    if has_string_fields or looks_like_header:
        headers = first_row
        data_start = 1

    # Resolve field indices.
    auto = auto_detect_columns(headers) if headers else {}

    def resolve(field_attr: str, auto_key: str) -> int | None:
        spec = getattr(rules, field_attr)
        if spec is not None:
            return _resolve_field(spec, headers)
        return auto.get(auto_key)

    date_idx = resolve("date_field", "date")
    payee_idx = resolve("payee_field", "payee")
    amount_idx = resolve("amount_field", "amount")
    debit_idx = resolve("debit_field", "debit")
    credit_idx = resolve("credit_field", "credit")
    account_idx = resolve("account_field", "account")
    note_idx = resolve("note_field", "note")

    transactions: list[dict[str, Any]] = []

    for row in rows[data_start:]:
        # Skip empty rows.
        if not row or all(c.strip() == "" for c in row):
            continue

        # Date
        raw_date = _get_cell(row, date_idx)
        if not raw_date:
            continue  # skip rows without a date
        try:
            dt = parse_date(raw_date, rules.date_format)
        except ValueError:
            continue  # skip unparseable dates

        # Payee
        payee = _get_cell(row, payee_idx) or "Unknown"

        # Amount: prefer amount_field, else compute from debit/credit.
        raw_amount = _get_cell(row, amount_idx)
        if raw_amount:
            amount_str = clean_amount(raw_amount)
        else:
            debit_raw = _get_cell(row, debit_idx)
            credit_raw = _get_cell(row, credit_idx)
            debit_val = float(clean_amount(debit_raw)) if debit_raw else 0.0
            credit_val = float(clean_amount(credit_raw)) if credit_raw else 0.0
            # Debits are negative (money out), credits are positive (money in).
            net = credit_val - debit_val
            amount_str = f"{net:.2f}"

        if rules.invert_amount:
            val = float(amount_str)
            amount_str = f"{-val:.2f}" if val != 0 else amount_str

        # Account
        account = _get_cell(row, account_idx) or ""

        # Note
        note = _get_cell(row, note_idx) or ""

        transactions.append({
            "date": dt,
            "payee": payee,
            "amount": amount_str,
            "account": account,
            "note": note,
        })

    return transactions


def format_transaction(
    txn: dict[str, Any],
    default_account: str = "Expenses:Unknown",
    bank_account: str = "Assets:Bank:Checking",
    currency: str = "",
) -> str:
    """Format a transaction dict as a ledger journal entry.

    Returns a string like::

        2024/01/15 Grocery Store
            Expenses:Unknown              $50.00
            Assets:Bank:Checking

    """
    dt: datetime = txn["date"]
    date_str = dt.strftime("%Y/%m/%d")
    payee = txn["payee"]
    amount_str = txn["amount"]
    account = txn.get("account") or default_account
    note = txn.get("note", "")

    # Build amount display.
    try:
        amount_val = float(amount_str)
    except (ValueError, TypeError):
        amount_val = 0.0

    if currency:
        if amount_val < 0:
            display_amount = f"-{currency}{abs(amount_val):.2f}"
        else:
            display_amount = f"{currency}{amount_val:.2f}"
    else:
        display_amount = f"{amount_val:.2f}"

    lines = [f"{date_str} {payee}"]
    if note:
        lines.append(f"    ; {note}")
    lines.append(f"    {account}  {display_amount}")
    lines.append(f"    {bank_account}")
    return "\n".join(lines)


def format_transactions(
    transactions: list[dict[str, Any]],
    default_account: str = "Expenses:Unknown",
    bank_account: str = "Assets:Bank:Checking",
    currency: str = "",
) -> str:
    """Format a list of transactions into a complete journal string."""
    entries = [
        format_transaction(txn, default_account, bank_account, currency)
        for txn in transactions
    ]
    return "\n\n".join(entries) + "\n" if entries else ""
