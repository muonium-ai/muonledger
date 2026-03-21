# MuonLedger Parity Report

Comprehensive parity assessment of the Rust and Python ports of C++ Ledger.

**Date**: 2026-03-21
**C++ Ledger baseline**: ledger 3.x (double-entry accounting tool)
**Rust port**: `port/rust/` -- 1,101 tests
**Python port**: `port/python/` -- 2,410+ tests (2 xfail)

---

## Executive Summary

MuonLedger provides two independent ports of the C++ Ledger accounting engine:

- **Python port** -- A full-featured port targeting ease of use and extensibility. It covers the widest feature surface including 10 CLI commands, 39 built-in expression functions, a price history graph with BFS shortest-path conversion, CSV import, and a complete filter pipeline. Implemented as an installable Python package (`muonledger`) with CLI entry point.

- **Rust port** -- A performance-oriented port using arena-based allocation for zero-cost account/commodity references. It implements the core accounting engine, 3 CLI commands, expression system, query parser, format strings, and full filter pipeline. Uses `BigRational` for exact arithmetic (mirroring GMP's `mpq_t`).

Both ports faithfully reproduce Ledger's double-entry semantics: exact rational arithmetic, automatic amount inference, multi-commodity balances, cost tracking, lot annotations, automated transactions, periodic transactions, and the expression/query language.

---

## Architecture Comparison

| Aspect | C++ Ledger | Rust Port | Python Port |
|--------|-----------|-----------|-------------|
| Memory model | Raw pointers, manual management | Arena-based (`Vec<Account>`, `AccountId` indices) | Class-based with Python GC |
| Arithmetic | GMP `mpq_t` (exact rational) | `num_rational::BigRational` (exact rational) | `fractions.Fraction` (exact rational) |
| Commodity styles | Bitflags | `bitflags` crate | `IntFlag` enum |
| Account tree | Pointer-based hierarchy | Arena indices (`AccountId`) | Object references |
| CLI framework | Custom | `clap` (derive) | `argparse` |
| Date handling | Boost.DateTime | `chrono::NaiveDate` | `datetime.date` + `dateutil` |
| Regex | Boost.Regex | `regex` crate | `re` module |
| Build system | CMake | Cargo | Hatch (PEP 621) |

---

## Feature Matrix

### Core Data Types

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Amount (exact rational) | Y | Y | Y | BigRational / Fraction |
| Amount parsing (prefix/suffix commodity) | Y | Y | Y | |
| Amount display style learning | Y | Y | Y | Learned from first usage |
| Thousands separators | Y | Y | Y | Comma and apostrophe |
| European decimal comma | Y | Y | Y | |
| Balance (multi-commodity) | Y | Y | Y | BTreeMap / dict keyed by symbol |
| Value (polymorphic type) | Y | Y | Y | Type promotion hierarchy |
| Value type promotion (INT -> AMOUNT -> BALANCE) | Y | Y | Y | |
| Commodity | Y | Y | Y | Style flags, precision, symbol |
| CommodityPool (registry) | Y | Y | Y | Singleton registry with style learning |
| Commodity quoting | Y | Y | Y | Quoted symbols for special chars |

### Account System

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Hierarchical account tree | Y | Y | Y | Colon-separated paths |
| Root account (invisible) | Y | Y | Y | Depth 0 |
| Account fullname (cached) | Y | Y | Y | Lazily computed |
| Account depth tracking | Y | Y | Y | |
| Account notes | Y | Y | Y | |
| Account xdata (extended data) | Y | -- | Y | Python has `_xdata` dict |
| find_or_create child accounts | Y | Y | Y | |

### Transaction / Posting Model

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Transaction with payee | Y | Y | Y | |
| Transaction code `(CODE)` | Y | Y | Y | |
| Clearing state (`*`, `!`) | Y | Y | Y | Cleared, Pending, Uncleared |
| Per-posting state | Y | Y | Y | |
| Auxiliary dates `=DATE` | Y | Y | Y | |
| Transaction finalize (balance check) | Y | Y | Y | |
| Null-amount inference | Y | Y | Y | Single missing amount inferred |
| Multi-commodity balance check | Y | Y | Y | |
| Cost annotations `@` / `@@` | Y | Y | Y | Per-unit and total cost |
| Virtual postings `(Account)` | Y | Y | Y | Non-balancing |
| Balanced virtual postings `[Account]` | Y | Y | Y | Must balance within brackets |
| Balance assertions `= AMOUNT` | Y | Y | Y | |
| Item metadata (key: value) | Y | Y | Y | |
| Item tags `:tag1:tag2:` | Y | Y | Y | |
| Position tracking (file/line) | Y | Y | Y | Source attribution |

### Lot Annotations

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Lot price `{$150.00}` | Y | Y | Y | |
| Lot date `[2024-01-15]` | Y | Y | Y | |
| Lot tag `(description)` | Y | Y | Y | |
| AnnotatedCommodity | Y | -- | Y | Python has full `AnnotatedCommodity` class |
| KeepDetails (display control) | Y | -- | Y | `--lot-prices`, `--lot-dates`, `--lot-tags` |

### Journal

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Regular transactions | Y | Y | Y | |
| Automated transactions `=` | Y | Y | Y | Predicate matching + template posts |
| Periodic transactions `~` | Y | Y | Y | Budget support |
| Price entries (from `P` directives) | Y | Y | Y | |
| Account aliases | Y | Y | Y | |
| Default account (bucket) | Y | Y | Y | `A` directive |
| Default year | Y | Y | Y | `Y`/`year` directive |
| Tag declarations | Y | Y | Y | `tag` directive |
| Payee declarations | Y | Y | Y | `payee` directive |
| Apply account stack | Y | Y | Y | `apply account` / `end apply account` |
| Apply tag stack | Y | Y | Y | `apply tag` / `end apply tag` |
| No-market commodities | Y | Y | Y | `N` directive |
| Variable definitions | Y | Y | Y | `define` directive |
| Price history (graph-based) | Y | -- | Y | Python has BFS shortest-path conversion |

### Parser (Textual Journal)

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Transaction header parsing | Y | Y | Y | Date, state, code, payee, note |
| Posting line parsing | Y | Y | Y | Account, amount, cost, note |
| Comment lines (`;`, `#`, `%`, `\|`, `*`) | Y | Y | Y | |
| Metadata parsing (`; key: value`) | Y | Y | Y | |
| Tag parsing (`; :tag1:tag2:`) | Y | Y | Y | |
| `account` directive | Y | Y | Y | Pre-declare accounts |
| `commodity` directive | Y | Y | Y | Pre-declare commodities |
| `P` price directive | Y | Y | Y | Historical prices |
| `D` default commodity | Y | Y | Y | |
| `Y`/`year` default year | Y | Y | Y | |
| `include` directive | Y | Y | Y | Include other files |
| `comment`/`end comment` block | Y | Y | Y | |
| `A`/`bucket` directive | Y | Y | Y | Default account |
| `alias` directive | Y | Y | Y | Account aliases |
| `apply account`/`end apply account` | Y | Y | Y | Account prefix stack |
| `apply tag`/`end apply tag` | Y | Y | Y | Tag stack |
| `N` no-market directive | Y | Y | Y | |
| `define` directive | Y | Y | Y | Variable definitions |
| `tag` directive | Y | Y | Y | Tag declarations |
| `payee` directive | Y | Y | Y | Payee declarations |
| Automated transaction parsing `=` | Y | Y | Y | |
| Periodic transaction parsing `~` | Y | Y | Y | |
| Lot annotation parsing `{} [] ()` | Y | Y | Y | |
| Cost parsing `@ @@` | Y | Y | Y | |
| Virtual posting parsing `() []` | Y | Y | Y | |
| Balance assertion parsing `= AMOUNT` | Y | Y | Y | |
| File parsing (from path) | Y | Y | Y | |
| String parsing (in-memory) | Y | Y | Y | |

### Expression System

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Tokenizer | Y | Y | Y | All Ledger token types |
| Pratt parser (precedence climbing) | Y | Y | Y | 14 precedence levels |
| AST node types | Y | Y | Y | Full OpKind enum |
| Arithmetic ops (`+`, `-`, `*`, `/`) | Y | Y | Y | |
| Comparison ops (`==`, `!=`, `<`, `>`, `<=`, `>=`) | Y | Y | Y | |
| Logical ops (`and`, `or`, `not`) | Y | Y | Y | |
| Ternary (`? :`) | Y | Y | Y | |
| Regex match (`=~`) | Y | Y | Y | |
| Lambda (`->`) | Y | Y | Y | |
| Function call | Y | Y | Y | |
| Member access (`.`) | Y | Y | Y | |
| Format strings (`%[-][width](expr)`) | Y | Y | Y | Printf-inspired |

### Query Language

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Account term (bare word) | Y | Y | Y | `food` -> `account =~ /food/` |
| Payee term (`@term`) | Y | Y | Y | |
| Code term (`#term`) | Y | Y | Y | |
| Note term (`=term`) | Y | Y | Y | |
| Tag term (`%term`) | Y | Y | Y | |
| Regex pattern (`/regex/`) | Y | Y | Y | |
| Boolean connectives | Y | Y | Y | `and`/`&`, `or`/`\|`, `not`/`!` |
| Parenthesized grouping | Y | Y | Y | |
| Implicit AND | Y | Y | Y | |

### Scope / Symbol Resolution

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Scope trait/ABC | Y | Y | Y | `lookup(name)` protocol |
| ChildScope (delegation) | Y | Y | Y | |
| SymbolScope (local dict) | Y | Y | Y | |
| CallScope (positional args) | Y | Y | Y | |
| BindScope (dual-scope join) | Y | Y | Y | |

### Built-in Functions

| Function | C++ Ledger | Rust | Python | Category |
|----------|:----------:|:----:|:------:|----------|
| abs | Y | -- | Y | Math |
| round / roundto | Y | -- | Y | Math |
| ceil | Y | -- | Y | Math |
| floor | Y | -- | Y | Math |
| min / max | Y | -- | Y | Math |
| str | Y | -- | Y | String |
| strip / trim | Y | -- | Y | String |
| join | Y | -- | Y | String |
| quoted | Y | -- | Y | String |
| justify | Y | -- | Y | String |
| truncated | Y | -- | Y | String |
| format | Y | -- | Y | String |
| now / today / date | Y | -- | Y | Date |
| format_date | Y | -- | Y | Date |
| int / quantity / commodity | Y | -- | Y | Type conversion |
| is_seq / to_amount / to_balance | Y | -- | Y | Type conversion |
| amount / account / payee / total | Y | -- | Y | Posting query |
| display_amount / display_total | Y | -- | Y | Posting query |
| has_tag / tag | Y | -- | Y | Posting query |
| lot_date / lot_price / lot_tag | Y | -- | Y | Lot query |
| true / false | Y | -- | Y | Boolean constants |

### Filter Pipeline

| Filter | C++ Ledger | Rust | Python | Notes |
|--------|:----------:|:----:|:------:|-------|
| PassThroughPosts | Y | -- | Y | Identity |
| CollectPosts | Y | Y | Y | Accumulate into list |
| FilterPosts | Y | Y | Y | Predicate-based filtering |
| SortPosts | Y | Y | Y | Sort by key |
| TruncatePosts | Y | Y | Y | Head/tail limiting |
| CalcPosts | Y | Y | Y | Running totals |
| CollapsePosts | Y | Y | Y | Collapse per-transaction |
| SubtotalPosts | Y | Y | Y | Subtotals by account |
| IntervalPosts | Y | Y | Y | Date interval grouping |
| InvertPosts | Y | Y | Y | Negate amounts |
| RelatedPosts | Y | Y | Y | Other-side postings |
| DisplayFilter | Y | Y | Y | Display predicate |
| MarketConvertPosts | Y | -- | Y | Market price conversion |

### Report Options

| Option | C++ Ledger | Rust | Python | Notes |
|--------|:----------:|:----:|:------:|-------|
| `--begin` / `--end` | Y | Y | Y | Date range filtering |
| `--period` | Y | Y | Y | Period expressions |
| `--current` | Y | Y | Y | Exclude future |
| `--amount` / `--total` expressions | Y | Y | Y | |
| `--display` expression | Y | Y | Y | |
| `--sort` expression | Y | Y | Y | |
| `--subtotal` | Y | Y | Y | |
| `--collapse` | Y | Y | Y | |
| `--daily`/`--weekly`/`--monthly`/`--quarterly`/`--yearly` | Y | Y | Y | |
| `--flat` | Y | Y | Y | |
| `--depth` | Y | Y | Y | |
| `--related` | Y | Y | Y | |
| `--invert` | Y | Y | Y | |
| `--head` / `--tail` | Y | Y | Y | |
| `--no-total` | Y | Y | Y | |
| `--empty` | Y | Y | Y | |
| `--cleared`/`--uncleared`/`--pending` | Y | Y | Y | |
| `--real` (exclude virtual) | Y | Y | Y | |
| `--market` / `--exchange` | Y | -- | Y | Market conversion |

### CLI Commands

| Command | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| `balance` (`bal`, `b`) | Y | Y | Y | Account balances |
| `register` (`reg`, `r`) | Y | Y | Y | Chronological postings |
| `print` | Y | Y | Y | Round-trip journal output |
| `prices` | Y | -- | Y | List price entries |
| `pricedb` | Y | -- | Y | Output in P directive format |
| `pricemap` | Y | -- | Y | Commodity price graph |
| `accounts` | Y | -- | Y | List unique accounts |
| `payees` | Y | -- | Y | List unique payees |
| `tags` | Y | -- | Y | List unique tags |
| `commodities` | Y | -- | Y | List unique commodities |
| `stats` | Y | -- | Y | Journal statistics |
| `equity` | Y | -- | Y | Opening balance generation |
| `convert` (`csv`) | Y | -- | Y | CSV import to journal |
| `select` (SQL-like) | Y | -- | -- | Not implemented in either port |
| `budget` | Y | -- | -- | `--budget` option partially via periodic xacts |
| `cleared` | Y | -- | -- | |
| `xact` | Y | -- | -- | Transaction auto-generation |

### Date/Time System

| Feature | C++ Ledger | Rust | Python | Notes |
|---------|:----------:|:----:|:------:|-------|
| Date parsing (YYYY/MM/DD) | Y | Y | Y | |
| Multiple date formats | Y | -- | Y | Python: YYYY-MM-DD, MM/DD, etc. |
| Period expression parsing | Y | -- | Y | "monthly", "weekly", etc. |
| DateInterval iteration | Y | -- | Y | Generates interval boundaries |
| Smart date terms ("this month") | Y | -- | Partial | |

---

## Test Coverage Summary

### Rust Port: 1,101 Tests

| Category | Tests | Source Files |
|----------|------:|-------------|
| Parser (textual journal) | 102 | `src/parser.rs` |
| Balance (multi-commodity) | 43 | `src/balance.rs` |
| Value (polymorphic type) | 68 | `src/value.rs` |
| Amount (exact arithmetic) | 62 | `src/amount.rs` |
| Parity tests (phase 1-6) | 446 | `tests/parity*.rs` |
| Expression parser | 44 | `src/expr_parser.rs` |
| Query parser | 38 | `src/query.rs` |
| Format strings | 33 | `src/format.rs` |
| Filters | 29 | `src/filters.rs` |
| Commodity/CommodityPool | 26 | `src/commodity.rs` |
| Expression tokenizer | 22 | `src/expr_token.rs` |
| Lot annotations | 22 | `src/lot.rs` |
| Report options | 20 | `src/report.rs` |
| Scope/symbol resolution | 18 | `src/scope.rs` |
| Automated transactions | 15 | `src/auto_xact.rs` |
| Journal | 13 | `src/journal.rs` |
| Balance command | 13 | `src/commands/balance.rs` |
| Register command | 12 | `src/commands/register.rs` |
| Account | 12 | `src/account.rs` |
| AST nodes | 11 | `src/expr_ast.rs` |
| Transaction | 11 | `src/xact.rs` |
| Item | 11 | `src/item.rs` |
| Periodic transactions | 11 | `src/periodic_xact.rs` |
| Post | 9 | `src/post.rs` |
| Print command | 9 | `src/commands/print.rs` |

### Python Port: 2,410+ Tests

| Test File | Scope |
|-----------|-------|
| `test_parser.py` | Journal parsing, all directives |
| `test_amount.py` | Amount parsing, arithmetic, display |
| `test_balance.py` | Multi-commodity balance operations |
| `test_value.py` | Polymorphic value type promotion |
| `test_commodity.py` | Commodity styles, pool, quoting |
| `test_account.py` | Account tree, hierarchy, fullname |
| `test_journal.py` | Journal container, iteration |
| `test_xact.py` | Transaction finalize, balance check |
| `test_filters.py` | Full filter pipeline |
| `test_format.py` | Format string parsing/evaluation |
| `test_expr_parser.py` | Expression parser, AST |
| `test_expr_token.py` | Expression tokenizer |
| `test_query.py` | Query language parser |
| `test_scope.py` | Scope chain, symbol resolution |
| `test_functions.py` | 39 built-in functions |
| `test_auto_xact.py` | Automated transaction matching |
| `test_periodic_xact.py` | Periodic transactions, budgets |
| `test_annotate.py` | Lot annotations, AnnotatedCommodity |
| `test_lot_annotations.py` | Lot parsing and tracking |
| `test_price_history.py` | Price graph, BFS conversion |
| `test_cmd_balance.py` | Balance command output |
| `test_cmd_register.py` | Register command output |
| `test_cmd_print.py` | Print command (round-trip) |
| `test_cmd_equity.py` | Equity command |
| `test_cmd_listing.py` | accounts/payees/tags/commodities |
| `test_cmd_stats.py` | Stats command |
| `test_price_commands.py` | prices/pricedb/pricemap |
| `test_virtual_postings.py` | Virtual and balanced-virtual |
| `test_balance_assertions.py` | Balance assertion checking |
| `test_directives.py` | All parser directives |
| `test_report_options.py` | Report option handling |
| `test_report_options_ext.py` | Extended report options |
| `test_format_output.py` | Format output edge cases |
| `test_times.py` | Date parsing, periods, intervals |
| `test_smoke.py` | End-to-end smoke tests |
| `test_regression_fixes.py` | Regression fixes |
| `test_regression_triage.py` | Regression triage |
| `test_error_messages.py` | Error message quality |
| `test_arithmetic_edge.py` | Arithmetic edge cases |
| `test_parity_phase2.py` | Phase 2 parity verification |
| `test_parity_phase3.py` | Phase 3 parity verification |

---

## Known Gaps and Limitations

### Rust Port

1. **Commands**: Only `balance`, `register`, and `print` are implemented. Missing: `prices`, `pricedb`, `pricemap`, `accounts`, `payees`, `tags`, `commodities`, `stats`, `equity`, `convert`.
2. **Built-in functions**: The 39 built-in functions (`abs`, `round`, `amount`, `account`, `payee`, etc.) are not yet registered in the expression evaluator.
3. **Price history**: No graph-based price conversion engine (BFS shortest-path). Price entries are stored but not used for market valuations.
4. **Market conversion**: The `MarketConvertPosts` filter and `--market`/`--exchange` options are not implemented.
5. **Date system**: No period expression parsing or `DateInterval` iteration. Date filtering in reports uses `NaiveDate` directly.
6. **Annotated commodities**: `LotAnnotation` exists but there is no `AnnotatedCommodity` wrapper or `KeepDetails` control.
7. **CSV import**: No `convert` command.
8. **Listing commands**: No `accounts`, `payees`, `tags`, `commodities` commands.
9. **Statistics**: No `stats` command.
10. **Equity**: No `equity` command.

### Python Port

1. **`select` command**: SQL-like query interface not implemented.
2. **`budget` reporting**: Periodic transactions are parsed and `BudgetPosts` filter exists, but full `--budget` reporting is not end-to-end wired.
3. **`xact` command**: Automatic transaction generation not implemented.
4. **`cleared` command**: Not implemented as a separate command.
5. **Performance**: Python's interpreted nature means large journals (100k+ transactions) will be slower than C++ or Rust.
6. **2 xfail tests**: Two tests are marked as expected failures, indicating minor known issues.

### Both Ports

1. **Timeclock/timelog**: Time tracking features (`i`/`o`/`I`/`O` entries) not implemented.
2. **Python expressions in values**: C++ Ledger's `--import` and Python scripting extensions not ported.
3. **Session management**: Multi-session/multi-file management is simplified compared to C++ Ledger.
4. **Output colorization**: Terminal color output not implemented.
5. **Emacs integration**: Ledger-mode compatibility features not ported.

---

## Recommendations

1. **Rust port next steps**: Implement built-in expression functions, price history graph, and the remaining CLI commands to reach Python-port parity.
2. **Python port next steps**: Wire up `--budget` end-to-end, resolve the 2 xfail tests, and add performance benchmarks for large journals.
3. **Cross-port testing**: The existing parity test suites (phases 1-6) provide a shared verification framework. Expanding these to cover newly added features ensures both ports stay synchronized.
