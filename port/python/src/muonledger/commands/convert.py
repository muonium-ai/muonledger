"""Convert command -- reads CSV bank statements and outputs ledger journal entries.

Ported from ledger's ``convert`` command.  Reads a CSV file with a rules
configuration and produces standard ledger-format transactions.

Usage (CLI)::

    muonledger -f /dev/null convert bank.csv --account "Assets:Bank:Checking"

Or programmatically::

    from muonledger.commands.convert import convert_command
    output = convert_command("bank.csv")
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from muonledger.csv_import import (
    CsvRules,
    format_transactions,
    parse_csv,
)

__all__ = ["convert_command"]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="convert", add_help=False)
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument(
        "--account", dest="bank_account", default="Assets:Bank:Checking",
        help="Bank account name for the balancing posting",
    )
    parser.add_argument(
        "--default-account", dest="default_account", default="Expenses:Unknown",
        help="Default expense/income account",
    )
    parser.add_argument(
        "--currency", default="",
        help="Currency symbol to prepend to amounts (e.g. '$')",
    )
    parser.add_argument(
        "--date-format", dest="date_format", default=None,
        help="Date format string (e.g. '%%m/%%d/%%Y')",
    )
    parser.add_argument(
        "--skip-lines", dest="skip_lines", type=int, default=0,
        help="Number of leading lines to skip before CSV data",
    )
    parser.add_argument(
        "--invert", action="store_true", default=False,
        help="Invert amount signs",
    )
    # Field overrides by column index.
    parser.add_argument("--date-field", dest="date_field", type=int, default=None)
    parser.add_argument("--payee-field", dest="payee_field", type=int, default=None)
    parser.add_argument("--amount-field", dest="amount_field", type=int, default=None)
    parser.add_argument("--debit-field", dest="debit_field", type=int, default=None)
    parser.add_argument("--credit-field", dest="credit_field", type=int, default=None)
    parser.add_argument("--account-field", dest="account_field", type=int, default=None)
    parser.add_argument("--note-field", dest="note_field", type=int, default=None)
    return parser.parse_args(argv)


def convert_command(
    csv_file: str | Path | None = None,
    rules: CsvRules | dict[str, Any] | None = None,
    argv: list[str] | None = None,
) -> str:
    """Read a CSV file and return ledger-format journal text.

    Can be called with explicit ``csv_file`` and ``rules``, or from the CLI
    where ``argv`` is parsed for options.
    """
    if argv is not None:
        args = _parse_args(argv)
        csv_file = args.csv_file
        rules_obj = CsvRules(
            date_field=args.date_field,
            payee_field=args.payee_field,
            amount_field=args.amount_field,
            debit_field=args.debit_field,
            credit_field=args.credit_field,
            account_field=args.account_field,
            note_field=args.note_field,
            skip_lines=args.skip_lines,
            date_format=args.date_format,
            default_account=args.default_account,
            bank_account=args.bank_account,
            currency=args.currency,
            invert_amount=args.invert,
        )
    elif isinstance(rules, dict):
        rules_obj = CsvRules(**rules)
    elif isinstance(rules, CsvRules):
        rules_obj = rules
    else:
        rules_obj = CsvRules()

    if csv_file is None:
        return ""

    path = Path(csv_file)
    content = path.read_text(encoding="utf-8")

    transactions = parse_csv(content, rules_obj)
    return format_transactions(
        transactions,
        default_account=rules_obj.default_account,
        bank_account=rules_obj.bank_account,
        currency=rules_obj.currency,
    )
