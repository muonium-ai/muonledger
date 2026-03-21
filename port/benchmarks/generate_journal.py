#!/usr/bin/env python3
"""Generate synthetic ledger journal files for benchmarking.

Creates realistic-looking journal files with configurable transaction counts,
random payees, accounts, amounts, and transaction states.

Usage:
    python generate_journal.py --count 1000 --output bench_1k.ledger
    python generate_journal.py --generate-all --output-dir .
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Payee pool (~50 common payees)
# ---------------------------------------------------------------------------

PAYEES = [
    "Whole Foods Market", "Trader Joe's", "Costco", "Walmart", "Target",
    "Amazon.com", "Netflix", "Spotify", "AT&T", "Verizon",
    "Shell Gas Station", "Chevron", "ExxonMobil", "BP", "Texaco",
    "Starbucks", "McDonald's", "Chipotle", "Subway", "Pizza Hut",
    "Home Depot", "Lowe's", "IKEA", "Bed Bath & Beyond", "Williams-Sonoma",
    "CVS Pharmacy", "Walgreens", "Rite Aid", "Kaiser Permanente", "Blue Cross",
    "State Farm Insurance", "Allstate", "Progressive", "GEICO",
    "Con Edison", "Pacific Gas & Electric", "Water Utility",
    "City Parking", "Uber", "Lyft", "Delta Airlines", "United Airlines",
    "Hilton Hotels", "Marriott", "Airbnb",
    "Chase Bank", "Wells Fargo", "Bank of America", "Citibank",
    "Apple Store", "Best Buy",
]

# ---------------------------------------------------------------------------
# Account pool (~30 accounts)
# ---------------------------------------------------------------------------

EXPENSE_ACCOUNTS = [
    "Expenses:Food:Groceries",
    "Expenses:Food:Dining",
    "Expenses:Food:Coffee",
    "Expenses:Transport:Gas",
    "Expenses:Transport:Public",
    "Expenses:Transport:Rideshare",
    "Expenses:Transport:Parking",
    "Expenses:Housing:Rent",
    "Expenses:Housing:Utilities",
    "Expenses:Housing:Maintenance",
    "Expenses:Health:Insurance",
    "Expenses:Health:Pharmacy",
    "Expenses:Entertainment:Streaming",
    "Expenses:Entertainment:Dining",
    "Expenses:Shopping:Clothes",
    "Expenses:Shopping:Electronics",
    "Expenses:Shopping:Home",
    "Expenses:Insurance:Auto",
    "Expenses:Insurance:Home",
    "Expenses:Travel:Flights",
    "Expenses:Travel:Hotels",
    "Expenses:Travel:Meals",
]

ASSET_ACCOUNTS = [
    "Assets:Bank:Checking",
    "Assets:Bank:Savings",
    "Assets:Cash",
    "Assets:Investments:Brokerage",
]

INCOME_ACCOUNTS = [
    "Income:Salary",
    "Income:Bonus",
    "Income:Interest",
    "Income:Dividends",
]

LIABILITY_ACCOUNTS = [
    "Liabilities:CreditCard:Visa",
    "Liabilities:CreditCard:Mastercard",
    "Liabilities:Mortgage",
]

ALL_ACCOUNTS = EXPENSE_ACCOUNTS + ASSET_ACCOUNTS + INCOME_ACCOUNTS + LIABILITY_ACCOUNTS

# ---------------------------------------------------------------------------
# Tags and notes pools
# ---------------------------------------------------------------------------

TAGS = [
    "business", "personal", "reimbursable", "tax-deductible",
    "vacation", "medical", "charitable", "recurring", "one-time",
]

NOTES = [
    "weekly grocery run",
    "monthly subscription",
    "quarterly payment",
    "annual renewal",
    "reimbursement pending",
    "split with roommate",
    "birthday gift",
    "office supplies",
    "client dinner",
    "team lunch",
]


def generate_transaction(
    rng: random.Random,
    tx_date: date,
    tx_index: int,
) -> str:
    """Generate a single ledger transaction string.

    Returns a valid, balanced transaction with 2-4 postings.
    """
    # Choose state: 80% unmarked, 10% cleared, 10% pending
    state_roll = rng.random()
    if state_roll < 0.80:
        state_marker = ""
    elif state_roll < 0.90:
        state_marker = "* "
    else:
        state_marker = "! "

    payee = rng.choice(PAYEES)
    date_str = tx_date.strftime("%Y/%m/%d")

    # Optional code (15% of transactions)
    code = ""
    if rng.random() < 0.15:
        code = f" (#{tx_index})"

    # Header line
    header = f"{date_str} {state_marker}{code}{payee}"

    # Optional note on header (20% of transactions)
    if rng.random() < 0.20:
        note = rng.choice(NOTES)
        header += f"  ; {note}"

    lines = [header]

    # Decide number of postings: 80% have 2, 15% have 3, 5% have 4
    posting_roll = rng.random()
    if posting_roll < 0.80:
        num_expense_postings = 1
    elif posting_roll < 0.95:
        num_expense_postings = 2
    else:
        num_expense_postings = 3

    # Pick a funding source
    funding_account = rng.choice(ASSET_ACCOUNTS + LIABILITY_ACCOUNTS)

    total_amount = 0
    for _ in range(num_expense_postings):
        account = rng.choice(EXPENSE_ACCOUNTS)
        # Amount between $1.00 and $5000.00, with realistic distribution
        # Use log-normal-ish distribution: most purchases small, some large
        base = rng.uniform(1.0, 100.0)
        multiplier = rng.choice([1, 1, 1, 1, 1, 10, 10, 50])
        amount = round(min(base * multiplier, 5000.0), 2)
        total_amount += amount

        posting_line = f"    {account}  ${amount:.2f}"

        # Optional tag on posting (10% chance)
        if rng.random() < 0.10:
            tag = rng.choice(TAGS)
            posting_line += f"  ; :{tag}:"

        lines.append(posting_line)

    # Balancing posting (no explicit amount -- let ledger infer, or explicit negative)
    # Use explicit amount for safety in parsing
    lines.append(f"    {funding_account}  ${-total_amount:.2f}")

    return "\n".join(lines)


def generate_journal(
    count: int,
    seed: int = 42,
    start_date: date | None = None,
) -> str:
    """Generate a complete journal with *count* transactions.

    Parameters
    ----------
    count:
        Number of transactions to generate.
    seed:
        Random seed for reproducibility.
    start_date:
        First transaction date. Defaults to 2020-01-01.

    Returns
    -------
    str
        Complete journal content as a string.
    """
    if count == 0:
        return ""

    rng = random.Random(seed)
    if start_date is None:
        start_date = date(2020, 1, 1)

    # Spread transactions across time: roughly count/365 per day
    # but with some randomness
    if count <= 365:
        day_span = count  # ~1 tx per day
    else:
        day_span = max(count // 3, 365)  # spread out but not too thin

    lines: list[str] = []

    # Header comment
    lines.append(f"; Synthetic benchmark journal: {count} transactions")
    lines.append(f"; Generated with seed={seed}")
    lines.append("")

    for i in range(count):
        # Sequential dates with some random gaps
        day_offset = int((i / max(count - 1, 1)) * day_span)
        tx_date = start_date + timedelta(days=day_offset)
        tx_str = generate_transaction(rng, tx_date, i)
        lines.append(tx_str)
        lines.append("")

    return "\n".join(lines)


def write_journal(count: int, output_path: Path, seed: int = 42) -> None:
    """Generate and write a journal file."""
    content = generate_journal(count, seed=seed)
    output_path.write_text(content, encoding="utf-8")


def generate_all(output_dir: Path, seed: int = 42) -> None:
    """Generate all standard benchmark journal sizes."""
    sizes = {
        "bench_1k.ledger": 1_000,
        "bench_10k.ledger": 10_000,
        "bench_100k.ledger": 100_000,
        "bench_1m.ledger": 1_000_000,
    }
    for filename, count in sizes.items():
        path = output_dir / filename
        print(f"Generating {filename} ({count:,} transactions)...")
        write_journal(count, path, seed=seed)
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  -> {path} ({size_mb:.1f} MB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic ledger journal files for benchmarking."
    )
    parser.add_argument(
        "--count", type=int, default=1000,
        help="Number of transactions to generate (default: 1000)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--generate-all", action="store_true",
        help="Generate all standard sizes (1K, 10K, 100K, 1M)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=".",
        help="Output directory for --generate-all (default: .)",
    )

    args = parser.parse_args(argv)

    if args.generate_all:
        generate_all(Path(args.output_dir), seed=args.seed)
        return 0

    content = generate_journal(args.count, seed=args.seed)

    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"Wrote {args.count} transactions to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(content)

    return 0


if __name__ == "__main__":
    sys.exit(main())
