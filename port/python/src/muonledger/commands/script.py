"""Script command -- execute a batch of ledger commands from a file.

Ported from ledger's ``script`` command.  Reads commands from a file
and executes them sequentially, reporting results for each.

Each line in the script file is a command to execute (e.g., ``echo 2 + 3``,
``balance``, ``register``).  Empty lines and lines starting with ``#`` are
skipped.

Usage::

    muonledger script commands.txt -f journal.ledger

"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = ["script_command"]


def script_command(
    script_file: str,
    journal_file: Optional[str] = None,
    options: Optional[dict] = None,
) -> str:
    """Read and execute commands from a script file.

    Parameters
    ----------
    script_file : str
        Path to the script file containing commands (one per line).
    journal_file : str | None
        Path to a journal file to use as context for commands that need it.
    options : dict | None
        Reserved for future options.

    Returns
    -------
    str
        Combined output of all executed commands.
    """
    path = Path(script_file)

    if not path.exists():
        return f"Error: script file not found: {script_file}\n"

    if not path.is_file():
        return f"Error: not a regular file: {script_file}\n"

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"Error reading script file: {exc}\n"

    lines = content.splitlines()
    output_parts: list[str] = []

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        result = _execute_line(line, journal_file, line_num)
        if result:
            output_parts.append(result)

    if not output_parts:
        return ""

    return "".join(output_parts)


def _execute_line(
    line: str,
    journal_file: Optional[str],
    line_num: int,
) -> str:
    """Execute a single command line and return its output."""
    # Split into command and arguments
    parts = line.split(None, 1)
    command = parts[0].lower()
    args_str = parts[1] if len(parts) > 1 else ""

    if command == "echo":
        from muonledger.commands.echo import echo_command
        return echo_command(args_str)

    if command == "source":
        from muonledger.commands.source import source_command
        filepath = args_str.strip()
        if filepath:
            return source_command(filepath)
        return f"Error on line {line_num}: source command requires a file path\n"

    # Commands that need a journal
    if command in ("balance", "bal", "b", "register", "reg", "r",
                   "print", "p", "stats", "prices", "pricedb",
                   "pricemap", "equity", "select"):
        if journal_file is None:
            return (
                f"Error on line {line_num}: "
                f"'{command}' requires a journal file (use -f option)\n"
            )
        return _run_journal_command(command, args_str, journal_file, line_num)

    return f"Error on line {line_num}: unknown command '{command}'\n"


def _run_journal_command(
    command: str,
    args_str: str,
    journal_file: str,
    line_num: int,
) -> str:
    """Execute a command that requires a parsed journal."""
    from muonledger.journal import Journal
    from muonledger.parser import TextualParser, ParseError

    journal_path = Path(journal_file)
    if not journal_path.exists():
        return f"Error on line {line_num}: journal file not found: {journal_file}\n"

    journal = Journal()
    parser = TextualParser()
    try:
        parser.parse(journal_path, journal)
    except ParseError as exc:
        return f"Error on line {line_num}: failed to parse journal: {exc}\n"
    except Exception as exc:
        return f"Error on line {line_num}: {exc}\n"

    cmd_args = args_str.split() if args_str else []

    try:
        if command in ("balance", "bal", "b"):
            from muonledger.commands.balance import balance_command
            return balance_command(journal, cmd_args)

        if command in ("register", "reg", "r"):
            from muonledger.commands.register import register_command
            return register_command(journal, cmd_args)

        if command == "stats":
            from muonledger.commands.stats import stats_command
            return stats_command(journal, cmd_args)

        if command == "prices":
            from muonledger.commands.prices import prices_command
            return prices_command(journal, cmd_args)

        if command == "pricedb":
            from muonledger.commands.pricedb import pricedb_command
            return pricedb_command(journal, cmd_args)

        if command == "pricemap":
            from muonledger.commands.pricemap import pricemap_command
            return pricemap_command(journal, cmd_args)

        if command == "equity":
            from muonledger.commands.equity import equity_command
            return equity_command(journal, cmd_args)

        if command == "select":
            from muonledger.commands.select import select_command
            return select_command(journal, cmd_args)

        if command in ("print", "p"):
            from muonledger.commands.print_cmd import print_command
            return print_command(journal, cmd_args)

    except Exception as exc:
        return f"Error on line {line_num}: {command} failed: {exc}\n"

    return f"Error on line {line_num}: command '{command}' not yet implemented\n"
