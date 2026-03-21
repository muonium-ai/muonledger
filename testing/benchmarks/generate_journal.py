#!/usr/bin/env python3
"""Generate a realistic ledger-format journal file for benchmarking.

Outputs a valid double-entry journal to stdout.  Accounts, commodities,
dates and amounts are randomised but structurally sound.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Realistic account taxonomy
# ---------------------------------------------------------------------------

_ASSET_ACCOUNTS = [
    "Assets:Bank:Checking",
    "Assets:Bank:Savings",
    "Assets:Cash",
    "Assets:Investments:Brokerage",
    "Assets:Receivable",
]

_LIABILITY_ACCOUNTS = [
    "Liabilities:CreditCard:Visa",
    "Liabilities:CreditCard:Amex",
    "Liabilities:Mortgage",
    "Liabilities:StudentLoan",
]

_EXPENSE_ACCOUNTS = [
    "Expenses:Food:Groceries",
    "Expenses:Food:Restaurants",
    "Expenses:Housing:Rent",
    "Expenses:Housing:Utilities",
    "Expenses:Transport:Fuel",
    "Expenses:Transport:PublicTransit",
    "Expenses:Health:Insurance",
    "Expenses:Health:Pharmacy",
    "Expenses:Entertainment:Streaming",
    "Expenses:Entertainment:Books",
    "Expenses:Clothing",
    "Expenses:Travel:Flights",
    "Expenses:Travel:Hotels",
    "Expenses:Education:Tuition",
    "Expenses:Education:Supplies",
    "Expenses:Taxes:Federal",
    "Expenses:Taxes:State",
    "Expenses:Insurance:Auto",
    "Expenses:Insurance:Home",
    "Expenses:Gifts",
    "Expenses:Charity",
    "Expenses:Subscriptions",
    "Expenses:PersonalCare",
    "Expenses:Pets:Food",
    "Expenses:Pets:Vet",
    "Expenses:HomeImprovement",
]

_INCOME_ACCOUNTS = [
    "Income:Salary",
    "Income:Freelance",
    "Income:Dividends",
    "Income:Interest",
    "Income:Refunds",
]

_EQUITY_ACCOUNTS = [
    "Equity:OpeningBalances",
]

_ALL_ACCOUNTS = (
    _ASSET_ACCOUNTS
    + _LIABILITY_ACCOUNTS
    + _EXPENSE_ACCOUNTS
    + _INCOME_ACCOUNTS
    + _EQUITY_ACCOUNTS
)

_DEFAULT_COMMODITIES = ["USD", "EUR", "GBP"]

_PAYEES = [
    "Whole Foods Market",
    "Trader Joe's",
    "Amazon.com",
    "Shell Gas Station",
    "Netflix",
    "Spotify",
    "United Airlines",
    "Hilton Hotels",
    "Target",
    "Costco",
    "Starbucks",
    "Uber",
    "Lyft",
    "Walgreens",
    "CVS Pharmacy",
    "Home Depot",
    "IKEA",
    "Apple Store",
    "Electric Company",
    "Water Utility",
    "City Transit Authority",
    "State Farm Insurance",
    "University Bookstore",
    "Local Charity Fund",
    "Employer Inc.",
    "Freelance Client Co.",
    "Vanguard",
    "Bank of America",
]


def _pick_accounts(accounts: list[str], n: int) -> list[str]:
    """Return *n* unique accounts drawn from *accounts*."""
    return random.sample(accounts, min(n, len(accounts)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _generate_transaction(
    tx_date: date,
    accounts: list[str],
    commodities: list[str],
) -> str:
    """Return a single ledger transaction string."""

    payee = random.choice(_PAYEES)
    commodity = random.choice(commodities)

    # Pick an expense/income account and a funding account.
    expense_pool = [a for a in accounts if a.startswith(("Expenses:", "Liabilities:"))]
    funding_pool = [a for a in accounts if a.startswith(("Assets:", "Income:", "Equity:"))]

    if not expense_pool:
        expense_pool = accounts[:1]
    if not funding_pool:
        funding_pool = accounts[1:2] if len(accounts) > 1 else accounts[:1]

    debit_account = random.choice(expense_pool)
    credit_account = random.choice(funding_pool)

    # Avoid posting to the same account on both sides.
    if debit_account == credit_account:
        credit_account = funding_pool[0] if funding_pool[0] != debit_account else accounts[0]

    amount = _quantize(Decimal(random.uniform(1.00, 5000.00)))

    lines = [
        f"{tx_date.isoformat()} {payee}",
        f"    {debit_account}    {amount} {commodity}",
        f"    {credit_account}    {-amount} {commodity}",
        "",
    ]
    return "\n".join(lines)


def generate_journal(
    *,
    num_transactions: int = 1000,
    num_accounts: int = 50,
    num_commodities: int = 3,
    seed: int | None = None,
) -> str:
    """Return a complete journal as a string."""

    rng_seed = seed if seed is not None else 42
    random.seed(rng_seed)

    # Build account and commodity lists sized to the request.
    accounts = _pick_accounts(_ALL_ACCOUNTS, num_accounts)
    commodities = _DEFAULT_COMMODITIES[:num_commodities]
    # If the caller wants more commodities than our defaults, synthesise some.
    while len(commodities) < num_commodities:
        commodities.append(f"CUR{len(commodities) + 1}")

    parts: list[str] = []

    # Header comment.
    parts.append(
        f"; Auto-generated benchmark journal\n"
        f"; Transactions: {num_transactions}  "
        f"Accounts: {len(accounts)}  "
        f"Commodities: {len(commodities)}\n"
        f"; Seed: {rng_seed}\n"
    )

    # Spread transactions across roughly two years.
    start_date = date(2024, 1, 1)
    day_span = max(1, (365 * 2) // num_transactions)

    for i in range(num_transactions):
        tx_date = start_date + timedelta(days=i * day_span + random.randint(0, max(day_span - 1, 0)))
        parts.append(_generate_transaction(tx_date, accounts, commodities))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic ledger journal for benchmarking.",
    )
    parser.add_argument(
        "--transactions",
        type=int,
        default=1000,
        metavar="N",
        help="Number of transactions to generate (default: 1000).",
    )
    parser.add_argument(
        "--accounts",
        type=int,
        default=50,
        metavar="M",
        help="Number of distinct accounts to use (default: 50).",
    )
    parser.add_argument(
        "--commodities",
        type=int,
        default=3,
        metavar="C",
        help="Number of commodities / currencies (default: 3).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    journal = generate_journal(
        num_transactions=args.transactions,
        num_accounts=args.accounts,
        num_commodities=args.commodities,
        seed=args.seed,
    )
    sys.stdout.write(journal)


if __name__ == "__main__":
    main()
