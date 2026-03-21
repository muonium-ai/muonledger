# Migration Guide: C++ Ledger to MuonLedger (Python)

This guide helps users of C++ Ledger transition to the Python port of MuonLedger. The Python port aims for high compatibility with Ledger's journal file format and command-line interface.

---

## Installation

### Requirements

- Python 3.11 or later
- pip (or uv, pipx, etc.)

### Install from source

```bash
cd port/python
pip install -e .
```

### Install dependencies only

```bash
pip install mpmath python-dateutil
```

### Verify installation

```bash
muonledger --version
# muonledger 0.1.0
```

---

## Command Mapping

| C++ Ledger | MuonLedger (Python) | Notes |
|-----------|---------------------|-------|
| `ledger -f FILE bal` | `muonledger -f FILE balance` | Aliases: `bal`, `b` |
| `ledger -f FILE reg` | `muonledger -f FILE register` | Aliases: `reg`, `r` |
| `ledger -f FILE print` | `muonledger -f FILE print` | Round-trip output |
| `ledger -f FILE prices` | `muonledger -f FILE prices` | List price entries |
| `ledger -f FILE pricedb` | `muonledger -f FILE pricedb` | P directive format |
| `ledger -f FILE accounts` | Programmatic only | Via `listing.accounts_command()` |
| `ledger -f FILE payees` | Programmatic only | Via `listing.payees_command()` |
| `ledger -f FILE tags` | Programmatic only | Via `listing.tags_command()` |
| `ledger -f FILE commodities` | Programmatic only | Via `listing.commodities_command()` |
| `ledger -f FILE stats` | Programmatic only | Via `stats.stats_command()` |
| `ledger -f FILE equity` | Programmatic only | Via `equity.equity_command()` |
| `ledger convert FILE.csv` | `muonledger -f /dev/null convert FILE.csv` | CSV import |
| `ledger -f FILE pricemap` | `muonledger -f FILE pricemap` | Price graph |

### CLI Usage

```bash
# Balance report
muonledger -f journal.dat balance

# Balance with account filter
muonledger -f journal.dat balance Expenses

# Flat balance (no hierarchy)
muonledger -f journal.dat balance --flat

# Register report
muonledger -f journal.dat register

# Register with filter
muonledger -f journal.dat register Food

# Prices list
muonledger -f journal.dat prices

# CSV import
muonledger -f /dev/null convert bank.csv --account "Assets:Bank:Checking"
```

---

## Supported Journal File Format

MuonLedger reads standard Ledger journal files. The following syntax is fully supported:

### Transactions

```ledger
2024/01/15 * (1042) Grocery Store  ; Transaction note
    ; :food:grocery:
    Expenses:Food:Groceries          $42.50  ; Posting note
    Assets:Checking
```

- Date formats: `YYYY/MM/DD`, `YYYY-MM-DD`
- Clearing states: `*` (cleared), `!` (pending), or blank (uncleared)
- Transaction codes: `(1042)`
- Auxiliary dates: `2024/01/15=2024/01/20`
- Notes on transaction headers and postings
- Metadata tags: `; :tag1:tag2:`
- Metadata key-value: `; Key: Value`

### Virtual Postings

```ledger
2024/01/15 Budget allocation
    (Budget:Food)                   $-500.00   ; non-balancing virtual
    [Equity:Budget]                  $500.00   ; balanced virtual (must balance)
```

### Cost Annotations

```ledger
2024/01/15 Buy stock
    Assets:Brokerage    10 AAPL @ $150.00     ; per-unit cost
    Assets:Checking     $-1,500.00

2024/02/01 Buy more stock
    Assets:Brokerage    5 AAPL @@ $800.00     ; total cost
    Assets:Checking     $-800.00
```

### Lot Annotations

```ledger
2024/01/15 Buy stock
    Assets:Brokerage    10 AAPL {$150.00} [2024-01-15] (initial)
    Assets:Checking     $-1,500.00
```

### Balance Assertions

```ledger
2024/01/15 Reconcile
    Assets:Checking     $0.00 = $1,234.56
    Equity:Adjustments
```

### Automated Transactions

```ledger
= /^Expenses:Food/
    (Budget:Food)                   -1.0

2024/01/15 Grocery Store
    Expenses:Food                    $50.00
    Assets:Checking
```

### Periodic Transactions

```ledger
~ Monthly
    Expenses:Food                    $500.00
    Expenses:Rent                  $1,500.00
    Assets:Checking
```

### Directives

```ledger
; Account declarations
account Expenses:Food
account Assets:Checking

; Commodity declarations
commodity $
    format $1,000.00

; Price history
P 2024/01/15 AAPL $150.00
P 2024/01/15 EUR $1.10

; Default commodity
D $1,000.00

; Default year
Y 2024
year 2024

; Include other files
include other-journal.dat

; Account aliases
alias food = Expenses:Food:Groceries

; Default account (bucket)
A Assets:Checking
bucket Assets:Checking

; Apply prefix to all accounts
apply account Personal
; ... transactions here use Personal: prefix ...
end apply account

; Apply tags to all transactions
apply tag project:home
; ... transactions here get :project:home: tag ...
end apply tag

; No-market commodity
N EUR

; Comments
; This is a comment
# This is also a comment
% And this too
| And this

; Block comments
comment
    This entire block is ignored.
end comment
```

---

## Known Differences from C++ Ledger

### Behavioral Differences

1. **Arithmetic precision**: MuonLedger uses Python's `fractions.Fraction` for exact rational arithmetic. Results are mathematically identical to C++ Ledger's GMP-based arithmetic, but display rounding may differ in edge cases.

2. **Error messages**: Error messages include source file and line number but use a slightly different format than C++ Ledger.

3. **Column widths**: Default column widths match C++ Ledger (80-column layout for register, 20-char amount column for balance). The `--columns` option adjusts width.

4. **Sort stability**: Python's `sorted()` is stable, matching C++ Ledger's `std::stable_sort`.

### Missing Features

1. **`select` command** (SQL-like queries) is not implemented.
2. **`xact` command** (auto-generate transactions) is not implemented.
3. **Timeclock entries** (`i`/`o`/`I`/`O`) are not supported.
4. **Terminal colors** are not supported.
5. **Emacs ledger-mode** integration is not specifically targeted.
6. **`--budget` reporting** is partially implemented (periodic transactions are parsed, budget filter exists, but not fully wired to CLI).

### Performance

For journals with fewer than 10,000 transactions, performance is comparable. For very large journals (100k+), the Python port will be noticeably slower than C++ Ledger. Consider the Rust port for performance-critical use cases.

---

## Common Workflows

### Monthly Expense Report

```bash
# C++ Ledger
ledger -f journal.dat bal Expenses --begin 2024/01/01 --end 2024/02/01

# MuonLedger (Python)
muonledger -f journal.dat balance Expenses --begin 2024/01/01 --end 2024/02/01
```

### Register with Sorting

```bash
# C++ Ledger
ledger -f journal.dat reg --sort amount

# MuonLedger (Python) -- programmatic
from muonledger.parser import TextualParser
from muonledger.journal import Journal
from muonledger.report import ReportOptions, apply_to_journal, build_filter_chain

journal = Journal()
TextualParser().parse("journal.dat", journal)
opts = ReportOptions(sort_expr="amount")
posts = apply_to_journal(journal, opts)
# ... process posts through filter chain
```

### Programmatic Journal Access

```python
from muonledger.journal import Journal
from muonledger.parser import TextualParser

# Parse a journal file
journal = Journal()
parser = TextualParser()
parser.parse("journal.dat", journal)

# Iterate transactions
for xact in journal.xacts:
    print(f"{xact.item.date} {xact.payee}")
    for post in xact.posts:
        print(f"  {post.account.fullname}  {post.amount}")

# Access the account tree
for name, child in journal.master.children.items():
    print(f"Top-level account: {name}")

# Check commodity pool
for symbol, commodity in journal.commodity_pool.commodities.items():
    print(f"Commodity: {symbol} (precision={commodity.precision})")
```

### Price Conversion

```python
from muonledger.price_history import PriceHistory
from muonledger.amount import Amount
from datetime import date

ph = PriceHistory()
ph.add_price(date(2024, 1, 15), "AAPL", Amount("$150.00"))
ph.add_price(date(2024, 1, 15), "EUR", Amount("$1.10"))

# Direct conversion
converted = ph.convert(Amount("10 AAPL"), "$")
print(converted)  # $1,500.00

# Transitive conversion (AAPL -> $ -> EUR)
converted = ph.convert(Amount("10 AAPL"), "EUR")
print(converted)  # 1363.636363... EUR
```

### Expression Evaluation

```python
from muonledger.expr_parser import compile
from muonledger.scope import SymbolScope
from muonledger.functions import register_builtins
from muonledger.value import Value

# Set up scope with built-in functions
scope = SymbolScope()
register_builtins(scope)

# Compile and evaluate an expression
expr = compile("2 + 3 * 4")
result = expr.calc(scope)
print(result)  # 14
```

---

## File Format Compatibility

MuonLedger reads the same `.dat` / `.ledger` / `.journal` files as C++ Ledger. You can use the same journal files with both tools. The `print` command produces output that is valid Ledger input (round-trippable).

If you encounter a journal file that C++ Ledger accepts but MuonLedger rejects, please file an issue with the journal snippet.
