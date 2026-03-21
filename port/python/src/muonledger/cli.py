"""muonledger CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from muonledger import __version__
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.commands.balance import balance_command
from muonledger.commands.register import register_command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muonledger",
        description="Double-entry accounting tool (Python port of ledger)",
    )
    parser.add_argument(
        "--version", action="version", version=f"muonledger {__version__}"
    )
    parser.add_argument(
        "-f", "--file", dest="journal_file", required=True,
        help="Path to the journal file",
    )
    parser.add_argument(
        "--args-only", action="store_true",
        help="Parse arguments only from command line (for parity testing)",
    )
    parser.add_argument(
        "--columns", type=int, default=80,
        help="Output column width (default: 80)",
    )
    parser.add_argument(
        "command", nargs="?", default=None,
        help="Command to run: balance (bal), register (reg)",
    )
    parser.add_argument(
        "remaining", nargs=argparse.REMAINDER,
        help="Additional arguments passed to the command",
    )
    return parser


COMMAND_ALIASES = {
    "balance": "balance",
    "bal": "balance",
    "b": "balance",
    "register": "register",
    "reg": "register",
    "r": "register",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    command = COMMAND_ALIASES.get(args.command)
    if command is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    journal_path = Path(args.journal_file)
    if not journal_path.exists():
        print(f"Error: file not found: {journal_path}", file=sys.stderr)
        return 1

    journal = Journal()
    text_parser = TextualParser()
    try:
        text_parser.parse(journal_path, journal)
    except Exception as e:
        print(f"Error parsing journal: {e}", file=sys.stderr)
        return 1

    cmd_args = args.remaining or []

    if command == "balance":
        output = balance_command(journal, cmd_args)
    elif command == "register":
        output = register_command(journal, cmd_args)
    else:
        print(f"Command not yet implemented: {command}", file=sys.stderr)
        return 1

    if output:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
