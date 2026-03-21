"""Source command -- parse and validate a journal file.

Ported from ledger's ``source`` command.  Reads and parses a journal file,
reporting any errors found or confirming the file is valid.

Usage::

    muonledger source myfile.ledger

"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from muonledger.journal import Journal
from muonledger.parser import TextualParser, ParseError

__all__ = ["source_command"]


def source_command(
    filepath: str,
    options: Optional[dict] = None,
) -> str:
    """Parse the given journal file and report errors or success.

    Parameters
    ----------
    filepath : str
        Path to the journal file to validate.
    options : dict | None
        Reserved for future options.

    Returns
    -------
    str
        A report string describing the result of parsing.
    """
    path = Path(filepath)

    if not path.exists():
        return f"Error: file not found: {filepath}\n"

    if not path.is_file():
        return f"Error: not a regular file: {filepath}\n"

    # Read the file to check for empty / comment-only content
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"Error reading file: {exc}\n"

    journal = Journal()
    parser = TextualParser()

    try:
        parser.parse(path, journal)
    except ParseError as exc:
        return f"Error: {exc}\n"
    except Exception as exc:
        return f"Error parsing {filepath}: {exc}\n"

    xact_count = len(journal.xacts)
    post_count = sum(len(x.posts) for x in journal.xacts)

    lines: list[str] = []
    lines.append(f"No errors found in {filepath}")
    lines.append(f"  Transactions: {xact_count}")
    lines.append(f"  Postings: {post_count}")

    return "\n".join(lines) + "\n"
