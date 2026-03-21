"""muonledger CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from muonledger import __version__
from muonledger.journal import Journal
from muonledger.parser import TextualParser
from muonledger.commands.balance import balance_command
from muonledger.commands.prices import prices_command
from muonledger.commands.pricedb import pricedb_command
from muonledger.commands.pricemap import pricemap_command
from muonledger.commands.convert import convert_command
from muonledger.commands.register import register_command
from muonledger.commands.select import select_command
from muonledger.commands.draft import draft_command
from muonledger.commands.source import source_command
from muonledger.commands.echo import echo_command
from muonledger.commands.script import script_command
from muonledger.commands.cleared import cleared_command


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
        help="Command to run: balance (bal), register (reg), prices, pricedb, pricemap, convert, select, xact (entry, draft), source, echo, script",
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
    "prices": "prices",
    "pricedb": "pricedb",
    "pricemap": "pricemap",
    "convert": "convert",
    "csv": "convert",
    "select": "select",
    "xact": "draft",
    "entry": "draft",
    "draft": "draft",
    "source": "source",
    "echo": "echo",
    "script": "script",
    "cleared": "cleared",
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

    cmd_args = args.remaining or []

    # Commands that don't require journal parsing.
    if command == "convert":
        output = convert_command(argv=cmd_args)
        if output:
            sys.stdout.write(output)
        return 0

    if command == "echo":
        expr_str = " ".join(cmd_args) if cmd_args else ""
        output = echo_command(expr_str)
        if output:
            sys.stdout.write(output)
        return 0

    if command == "source":
        filepath = cmd_args[0] if cmd_args else args.journal_file
        output = source_command(filepath)
        if output:
            sys.stdout.write(output)
        return 0

    if command == "script":
        if not cmd_args:
            print("Error: script command requires a script file path", file=sys.stderr)
            return 1
        output = script_command(cmd_args[0], journal_file=args.journal_file)
        if output:
            sys.stdout.write(output)
        return 0

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

    if command == "balance":
        output = balance_command(journal, cmd_args)
    elif command == "register":
        output = register_command(journal, cmd_args)
    elif command == "prices":
        output = prices_command(journal, cmd_args)
    elif command == "pricedb":
        output = pricedb_command(journal, cmd_args)
    elif command == "pricemap":
        output = pricemap_command(journal, cmd_args)
    elif command == "select":
        output = select_command(journal, cmd_args)
    elif command == "draft":
        output = draft_command(journal, cmd_args)
    elif command == "cleared":
        output = cleared_command(journal, cmd_args)
    else:
        print(f"Command not yet implemented: {command}", file=sys.stderr)
        return 1

    if output:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
