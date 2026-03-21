# Migration Guide: C++ Ledger to MuonLedger (Rust)

This guide helps users of C++ Ledger transition to the Rust port of MuonLedger. The Rust port provides a high-performance, memory-safe implementation of the core Ledger accounting engine.

---

## Installation

### Requirements

- Rust 1.70 or later (stable)
- Cargo (included with Rust)

### Build from source

```bash
cd port/rust
cargo build --release
```

The binary is placed at `target/release/muonledger`.

### Run directly

```bash
cargo run -- -f journal.dat balance
```

### Dependencies

The Rust port uses minimal, well-established dependencies:

| Crate | Purpose |
|-------|---------|
| `num-rational` + `num-bigint` | Exact rational arithmetic (mirrors GMP `mpq_t`) |
| `chrono` | Date handling |
| `clap` | CLI argument parsing (derive macros) |
| `regex` | Regular expression matching |
| `bitflags` | Commodity style flags |
| `lazy_static` | Lazy regex initialization |

---

## Command Mapping

| C++ Ledger | MuonLedger (Rust) | Notes |
|-----------|-------------------|-------|
| `ledger -f FILE bal` | `muonledger -f FILE balance` | Alias: `bal` |
| `ledger -f FILE reg` | `muonledger -f FILE register` | Alias: `reg` |
| `ledger -f FILE print` | `muonledger -f FILE print` | Pass-through format |

### CLI Usage

```bash
# Balance report
muonledger -f journal.dat balance

# Balance with account filter
muonledger -f journal.dat balance Expenses

# Flat balance (no hierarchy)
muonledger -f journal.dat balance --flat

# Balance with depth limit
muonledger -f journal.dat balance --depth 2

# Suppress total line
muonledger -f journal.dat balance --no-total

# Show empty accounts
muonledger -f journal.dat balance -E

# Register report
muonledger -f journal.dat register

# Wide register (132 columns)
muonledger -f journal.dat register -w

# Register with head/tail
muonledger -f journal.dat register --head 10
muonledger -f journal.dat register --tail 5

# Print transactions
muonledger -f journal.dat print
```

---

## Supported Journal File Format

The Rust port reads standard Ledger journal files with full support for:

### Transactions

```ledger
2024/01/15 * (1042) Grocery Store  ; note
    ; :food:grocery:
    Expenses:Food:Groceries          $42.50  ; posting note
    Assets:Checking
```

All transaction features: dates (`YYYY/MM/DD`, `YYYY-MM-DD`), clearing states (`*`, `!`), codes, auxiliary dates, notes, metadata tags, and key-value metadata.

### Virtual Postings

```ledger
2024/01/15 Budget
    (Budget:Food)                   $-500.00   ; non-balancing virtual
    [Equity:Budget]                  $500.00   ; balanced virtual
```

### Cost Annotations

```ledger
2024/01/15 Buy stock
    Assets:Brokerage    10 AAPL @ $150.00     ; per-unit cost
    Assets:Brokerage    5 AAPL @@ $800.00     ; total cost
    Assets:Checking
```

### Lot Annotations

```ledger
2024/01/15 Buy stock
    Assets:Brokerage    10 AAPL {$150.00} [2024-01-15] (initial purchase)
    Assets:Checking     $-1,500.00
```

### Balance Assertions

```ledger
2024/01/15 Reconcile
    Assets:Checking     $0.00 = $1,234.56
    Equity:Adjustments
```

### Automated and Periodic Transactions

```ledger
= /^Expenses:Food/
    (Budget:Food)                   -1.0

~ Monthly
    Expenses:Food                    $500.00
    Assets:Checking
```

### All Directives

`account`, `commodity`, `P` (price), `D` (default commodity), `Y`/`year`, `include`, `comment`/`end comment`, `A`/`bucket`, `alias`, `apply account`/`end apply account`, `apply tag`/`end apply tag`, `N`, `define`, `tag`, `payee`.

---

## Library API Overview

The Rust port is both a CLI tool and a library crate. You can use it programmatically in your own Rust projects:

```toml
# Cargo.toml
[dependencies]
muonledger = { path = "../port/rust" }
```

### Basic Usage

```rust
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;
use muonledger::commands::balance::{balance_command, BalanceOptions};

fn main() {
    // Parse a journal file
    let mut journal = Journal::new();
    let parser = TextualParser::new();
    parser.parse_file("journal.dat".as_ref(), &mut journal).unwrap();

    // Run a balance report
    let opts = BalanceOptions {
        flat: false,
        no_total: false,
        show_empty: false,
        depth: 0,
        patterns: vec![],
    };
    let output = balance_command(&journal, &opts);
    println!("{}", output);
}
```

### Working with Amounts

```rust
use muonledger::amount::Amount;

// Parse amounts from strings
let a = Amount::parse("$100.00").unwrap();
let b = Amount::parse("$50.00").unwrap();

// Arithmetic
let sum = (&a + &b).unwrap();    // $150.00
let diff = (&a - &b).unwrap();   // $50.00
let product = (&a * &b).unwrap();
let neg = a.negated();            // $-100.00

// Display (preserves learned style)
println!("{}", sum);  // $150.00
```

### Working with Balances

```rust
use muonledger::amount::Amount;
use muonledger::balance::Balance;

let mut bal = Balance::new();
bal.add_amount(&Amount::parse("$100.00").unwrap());
bal.add_amount(&Amount::parse("10 AAPL").unwrap());

// Multi-commodity display
for (symbol, amount) in bal.amounts() {
    println!("{}: {}", symbol, amount);
}
```

### Accessing the Account Tree

```rust
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;

let mut journal = Journal::new();
let parser = TextualParser::new();
parser.parse_file("journal.dat".as_ref(), &mut journal).unwrap();

// Walk the account tree
let root = journal.accounts.root();
for child_id in journal.accounts.children(root) {
    let name = journal.accounts.fullname(child_id);
    println!("Top-level account: {}", name);
}
```

### Report Pipeline

```rust
use muonledger::report::{ReportOptions, apply_to_journal};
use muonledger::journal::Journal;

let journal: Journal = /* ... parsed ... */;

let opts = ReportOptions {
    begin: Some(chrono::NaiveDate::from_ymd_opt(2024, 1, 1).unwrap()),
    end: Some(chrono::NaiveDate::from_ymd_opt(2024, 2, 1).unwrap()),
    subtotal: true,
    ..ReportOptions::default()
};

let posts = apply_to_journal(&journal, &opts);
// Process enriched posts through the filter chain...
```

---

## Architecture: Arena-Based Design

The Rust port avoids `Rc<RefCell<...>>` and complex lifetime annotations by using arena-based allocation:

- **AccountArena**: All `Account` nodes live in a `Vec<Account>`. References use `AccountId(usize)` indices.
- **CommodityPool**: All `Commodity` objects live in a `Vec<Commodity>`. References use `CommodityId(usize)` indices.
- **Journal**: Owns the account arena, commodity pool, and all transactions. This is the single owner of all data.

This design provides O(1) account/commodity access, avoids reference counting overhead, and makes the borrow checker happy.

---

## Known Differences from C++ Ledger

### Currently Implemented

- **3 CLI commands**: `balance`, `register`, `print` (C++ Ledger has 15+)
- **Full parser**: All directives, transaction syntax, and annotations
- **Expression system**: Tokenizer, Pratt parser, AST, query language, format strings
- **Filter pipeline**: CollectPosts, FilterPosts, SortPosts, TruncatePosts, CalcPosts, CollapsePosts, SubtotalPosts, IntervalPosts, InvertPosts, RelatedPosts, DisplayFilter
- **Report options**: Date filtering, sorting, grouping intervals, subtotals, head/tail, flat, depth, clearing state filters

### Not Yet Implemented

1. **Price commands**: `prices`, `pricedb`, `pricemap`
2. **Listing commands**: `accounts`, `payees`, `tags`, `commodities`
3. **Equity command**: Opening balance generation
4. **Stats command**: Journal statistics
5. **Convert command**: CSV import
6. **Built-in functions**: The 39 built-in expression functions (abs, round, amount, account, etc.)
7. **Price history graph**: BFS shortest-path commodity conversion
8. **Market conversion**: `--market`/`--exchange` report options
9. **DateInterval iteration**: Period expression parsing for interval grouping
10. **Timeclock entries**: `i`/`o`/`I`/`O` not supported

### Performance

The Rust port should be significantly faster than C++ Ledger for parsing and reporting, thanks to arena-based allocation, zero-copy parsing where possible, and Rust's compilation optimizations. Exact-precision arithmetic uses `num_rational::BigRational`, which is comparable to GMP's `mpq_t`.

---

## File Format Compatibility

The Rust port reads the same `.dat` / `.ledger` / `.journal` files as C++ Ledger. You can use the same journal files with both tools.

If you encounter a journal file that C++ Ledger accepts but MuonLedger rejects, please file an issue with the journal snippet.
