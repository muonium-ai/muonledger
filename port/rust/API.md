# MuonLedger Rust API Documentation

API reference for the `muonledger` Rust crate -- a port of C++ Ledger's double-entry accounting engine.

---

## Crate Overview

The crate is organized into focused modules that mirror Ledger's C++ architecture:

| Module | Description |
|--------|-------------|
| `account` | Hierarchical account tree with arena-based allocation |
| `amount` | Exact-precision commoditized amounts (`BigRational`) |
| `auto_xact` | Automated transactions (`= PREDICATE` entries) |
| `balance` | Multi-commodity balances |
| `commands` | CLI command implementations (balance, register, print) |
| `commodity` | Commodity registry and display styles |
| `expr_ast` | Expression AST node types |
| `expr_parser` | Pratt/precedence-climbing expression parser |
| `expr_token` | Expression tokenizer |
| `filters` | Posting filter pipeline |
| `format` | Printf-inspired format string parser/evaluator |
| `item` | Base fields for transactions and postings |
| `journal` | Central data container |
| `lot` | Lot annotations for cost basis tracking |
| `parser` | Textual journal file parser |
| `periodic_xact` | Periodic/budget transactions (`~ PERIOD` entries) |
| `post` | Posting (line item within a transaction) |
| `query` | Query language parser |
| `report` | Report options and filter chain builder |
| `scope` | Scope chain for expression symbol resolution |
| `value` | Polymorphic value type with auto-promotion |
| `xact` | Transaction (dated journal entry) |

---

## Key Structs

### `Amount` (`amount.rs`)

Exact-precision commoditized amount using `num_rational::BigRational`.

```rust
use muonledger::amount::Amount;

// Parse from string
let a = Amount::parse("$100.00").unwrap();
let b = Amount::parse("10 AAPL").unwrap();

// Properties
a.quantity();          // &BigRational -- exact rational value
a.commodity_symbol();  // Option<&str> -- "$"
a.precision();         // u32 -- 2
a.is_null();           // bool
a.is_zero();           // bool
a.is_negative();       // bool

// Arithmetic (returns Result<Amount, AmountError>)
let sum = (&a + &b).unwrap();
let diff = (&a - &b).unwrap();
let product = (&a * &b).unwrap();
let quotient = (&a / &b).unwrap();
let neg = a.negated();
let abs_val = a.abs();

// Comparison
a.cmp(&b);             // Ordering (same-commodity only)

// Display (preserves learned style)
format!("{}", a);       // "$100.00"
```

**Error type**: `AmountError(String)`

---

### `Balance` (`balance.rs`)

Multi-commodity balance stored in a `BTreeMap<String, Amount>`.

```rust
use muonledger::balance::Balance;
use muonledger::amount::Amount;

// Construction
let mut bal = Balance::new();
let bal = Balance::from_amount(Amount::parse("$100.00").unwrap());

// Adding amounts
bal.add_amount(&Amount::parse("$50.00").unwrap());   // Accumulates
bal.add_amount(&Amount::parse("10 AAPL").unwrap());  // New entry

// Arithmetic
let sum = &bal1 + &bal2;
let diff = &bal1 - &bal2;
let neg = -&bal;

// Iteration
for (symbol, amount) in bal.amounts() {
    println!("{}: {}", symbol, amount);
}

// Properties
bal.is_zero();           // bool
bal.is_empty();          // bool
bal.commodity_count();   // usize
bal.single_amount();     // Option<&Amount>
```

---

### `Value` (`value.rs`)

Polymorphic value type supporting: Void, Boolean, Integer, Amount, Balance, String, Date, DateTime, Mask, Sequence.

```rust
use muonledger::value::Value;

// Construction
let v1 = Value::from_integer(42);
let v2 = Value::from_amount(amount);
let v3 = Value::from_string("hello");
let v4 = Value::from_boolean(true);
let v5 = Value::from_date(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap());

// Arithmetic (auto-promotes: INTEGER -> AMOUNT -> BALANCE)
let sum = (&v1 + &v2).unwrap();

// Type checking
v1.is_integer();
v1.is_amount();
v1.is_zero();

// Type conversion
v1.to_integer();        // Option<i64>
v1.to_amount();         // Option<Amount>
v1.to_string_val();     // String
v1.to_boolean();        // bool
```

---

### `Commodity` and `CommodityPool` (`commodity.rs`)

```rust
use muonledger::commodity::{Commodity, CommodityPool, CommodityId, CommodityStyle};

// Pool manages all commodities
let mut pool = CommodityPool::new();

// Find or create
let id: CommodityId = pool.find_or_create("$");

// Access commodity data
let c: &Commodity = pool.get(id);
c.symbol();              // &str
c.precision();           // u32
c.style();               // CommodityStyle (bitflags)

// Style flags
CommodityStyle::DEFAULTS             // 0x000
CommodityStyle::SUFFIXED             // 0x001
CommodityStyle::SEPARATED            // 0x002
CommodityStyle::DECIMAL_COMMA        // 0x004
CommodityStyle::THOUSANDS            // 0x008
CommodityStyle::NOMARKET             // 0x010
CommodityStyle::BUILTIN              // 0x020
CommodityStyle::KNOWN                // 0x080
CommodityStyle::THOUSANDS_APOSTROPHE // 0x4000
```

---

### `Account` and `AccountArena` (`account.rs`)

Arena-based hierarchical account tree. All accounts live in a `Vec<Account>` and are referenced by `AccountId(usize)`.

```rust
use muonledger::account::{AccountArena, AccountId};

let mut arena = AccountArena::new();
let root: AccountId = arena.root();

// Find or create accounts
let id = arena.find_or_create("Expenses:Food:Dining");

// Access account data
let name = arena.name(id);            // &str -- "Dining"
let fullname = arena.fullname(id);    // String -- "Expenses:Food:Dining"
let depth = arena.depth(id);          // usize -- 3
let parent = arena.parent(id);        // Option<AccountId>

// Children
let children = arena.children(id);    // impl Iterator<Item = AccountId>
let has_children = arena.has_children(id);
```

---

### `Post` (`post.rs`)

```rust
use muonledger::post::{Post, POST_VIRTUAL, POST_MUST_BALANCE, POST_COST_IN_FULL};

let mut post = Post::new();
post.account_id;          // Option<AccountId>
post.amount;              // Option<Amount>
post.cost;                // Option<Amount> -- from @ or @@
post.assigned_amount;     // Option<Amount> -- balance assertion
post.xact_index;          // Option<usize>
post.item;                // Item (flags, state, dates, notes, metadata)

// Convenience constructor
let post = Post::with_account_and_amount(account_id, amount);

// Flags
post.item.has_flag(POST_VIRTUAL);       // (Account) virtual posting
post.item.has_flag(POST_MUST_BALANCE);  // [Account] balanced virtual
post.item.has_flag(POST_COST_IN_FULL);  // @@ total cost
```

---

### `Transaction` (`xact.rs`)

```rust
use muonledger::xact::Transaction;

let mut xact = Transaction::new();
xact.payee = "Grocery Store".to_string();
xact.code = Some("1042".to_string());
xact.item.date = Some(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap());
xact.item.state = ItemState::Cleared;
xact.posts.push(post1);
xact.posts.push(post2);

// Finalize: infer missing amounts, verify balance
xact.finalize()?;  // Returns Result<(), BalanceError>
```

---

### `Journal` (`journal.rs`)

```rust
use muonledger::journal::Journal;

let mut journal = Journal::new();

// After parsing:
journal.accounts;           // AccountArena
journal.xacts;              // Vec<Transaction>
journal.auto_xacts;         // Vec<AutomatedTransaction>
journal.periodic_xacts;     // Vec<PeriodicTransaction>
journal.commodity_pool;     // CommodityPool
journal.sources;            // Vec<String>
journal.prices;             // Vec<(NaiveDate, String, Amount)>
journal.bucket;             // Option<AccountId>
journal.account_aliases;    // HashMap<String, AccountId>
journal.default_year;       // Option<i32>
journal.tag_declarations;   // Vec<String>
journal.payee_declarations; // Vec<String>
journal.apply_account_stack; // Vec<String>
journal.apply_tag_stack;    // Vec<String>
journal.no_market_commodities; // Vec<String>
journal.defines;            // HashMap<String, String>
```

---

### `TextualParser` (`parser.rs`)

```rust
use muonledger::parser::{TextualParser, ParseError};
use muonledger::journal::Journal;

let mut journal = Journal::new();
let parser = TextualParser::new();

// Parse from file
parser.parse_file(Path::new("journal.dat"), &mut journal)?;

// Parse from string
parser.parse_string("2024/01/15 Test\n    Expenses  $10\n    Assets\n", &mut journal)?;

// ParseError includes source and line number
match parser.parse_file(path, &mut journal) {
    Ok(()) => {},
    Err(e) => {
        eprintln!("{}:{}: {}", e.source, e.line_num, e.message);
    }
}
```

---

## Expression System

### `ExprTokenizer` (`expr_token.rs`)

```rust
use muonledger::expr_token::{ExprTokenizer, Token, TokenKind};

let mut tokenizer = ExprTokenizer::new("amount + $100");
while let Some(token) = tokenizer.next_token()? {
    // token.kind: TokenKind
    // token.value: Option<String>
}
```

### `ExprParser` (`expr_parser.rs`)

```rust
use muonledger::expr_parser::ExprParser;

let mut parser = ExprParser::new("2 + 3 * 4");
let ast = parser.parse()?;  // ExprNode
```

### `ExprNode` / `OpKind` (`expr_ast.rs`)

| OpKind | Description |
|--------|-------------|
| `O_ADD`, `O_SUB`, `O_MUL`, `O_DIV` | Arithmetic operators |
| `O_EQ`, `O_NE`, `O_LT`, `O_LTE`, `O_GT`, `O_GTE` | Comparison operators |
| `O_AND`, `O_OR`, `O_NOT` | Logical operators |
| `O_MATCH` | Regex match (`=~`) |
| `O_QUERY`, `O_COLON` | Ternary (`? :`) |
| `O_CALL` | Function call |
| `O_LOOKUP` | Member access (`.`) |
| `O_LAMBDA` | Lambda (`->`) |
| `O_DEFINE` | Assignment (`=`) |
| `O_CONS` | Comma-separated |
| `O_SEQ` | Semicolon-separated |
| `O_VALUE` | Literal value |
| `O_IDENT` | Identifier reference |

---

## Query Language (`query.rs`)

```rust
use muonledger::query::{parse_query, QueryParseError};

// Parse query to expression AST
let node = parse_query("food and @grocery")?;
// Equivalent to: (account =~ /food/) and (payee =~ /grocery/)

let node = parse_query("Expenses not @Amazon")?;
// Equivalent to: (account =~ /Expenses/) and not (payee =~ /Amazon/)

// Query prefixes:
//   (bare)  -> account match
//   @term   -> payee match
//   #term   -> code match
//   =term   -> note match
//   %term   -> tag match
//   /regex/ -> regex account match
```

---

## Filter Pipeline (`filters.rs`)

The filter pipeline processes postings through a chain of handlers. Each filter implements the `PostHandler` trait.

### `PostHandler` trait

```rust
pub trait PostHandler {
    fn handle(&mut self, post: EnrichedPost);
    fn flush(&mut self);
}
```

### Available Filters

| Filter | Description |
|--------|-------------|
| `CollectPosts` | Accumulates posts into a `Vec` |
| `FilterPosts` | Forwards posts matching a predicate |
| `SortPosts` | Sorts by key on flush |
| `TruncatePosts` | Head/tail limiting |
| `CalcPosts` | Computes running totals |
| `CollapsePosts` | Collapses per transaction |
| `SubtotalPosts` | Subtotals by account |
| `IntervalPosts` | Groups by date intervals |
| `InvertPosts` | Negates amounts |
| `RelatedPosts` | Other-side postings |
| `DisplayFilter` | Display predicate |

### `EnrichedPost`

```rust
pub struct EnrichedPost {
    pub date: NaiveDate,
    pub payee: String,
    pub account_name: String,
    pub account_id: Option<AccountId>,
    pub amount: Option<Amount>,
    pub cost: Option<Amount>,
    pub state: ItemState,
    pub flags: u32,
    pub note: Option<String>,
    pub metadata: HashMap<String, String>,
    pub tags: HashSet<String>,
    pub xdata: PostXData,
    pub xact_idx: usize,
    pub post_idx: usize,
}
```

---

## Report Options (`report.rs`)

```rust
use muonledger::report::{ReportOptions, apply_to_journal, build_filter_chain};

let opts = ReportOptions {
    begin: Some(NaiveDate::from_ymd_opt(2024, 1, 1).unwrap()),
    end: Some(NaiveDate::from_ymd_opt(2024, 2, 1).unwrap()),
    subtotal: true,
    sort_expr: Some("account".to_string()),
    flat: true,
    ..ReportOptions::default()
};

// Get qualifying enriched posts
let posts = apply_to_journal(&journal, &opts);
```

### ReportOptions Fields

| Field | Type | Description |
|-------|------|-------------|
| `begin` | `Option<NaiveDate>` | Start date (inclusive) |
| `end` | `Option<NaiveDate>` | End date (exclusive) |
| `period` | `Option<String>` | Period expression |
| `current` | `bool` | Exclude future dates |
| `amount_expr` | `Option<String>` | Amount display expression |
| `total_expr` | `Option<String>` | Total display expression |
| `display_expr` | `Option<String>` | Display predicate |
| `sort_expr` | `Option<String>` | Sort key |
| `sort_xacts` | `bool` | Sort by transaction |
| `daily/weekly/monthly/quarterly/yearly` | `bool` | Interval grouping |
| `collapse` | `bool` | Collapse per transaction |
| `subtotal` | `bool` | Subtotal by account |
| `related` | `bool` | Show other-side postings |
| `flat` | `bool` | Non-hierarchical output |
| `depth` | `usize` | Limit display depth |
| `head` / `tail` | `Option<usize>` | Limit output count |
| `no_total` | `bool` | Suppress total line |
| `empty` | `bool` | Show zero-balance accounts |
| `invert` | `bool` | Negate amounts |
| `cleared_only/uncleared_only/pending_only` | `bool` | State filters |
| `real` | `bool` | Exclude virtual postings |

---

## Format Strings (`format.rs`)

```rust
use muonledger::format::{Format, FormatError};

// Parse a format string
let fmt = Format::parse("%-20(account)  %12(total)\n")?;

// Format syntax:
//   Literal text         -- passed through verbatim
//   %(expr)              -- evaluate expression
//   %-20(expr)           -- left-aligned, 20 chars wide
//   %20(expr)            -- right-aligned, 20 chars wide
//   %.30(expr)           -- truncate to 30 chars
//   %20.30(expr)         -- min 20, max 30 chars
//   %%                   -- literal %
//   \n, \t               -- escape sequences
```

---

## Lot Annotations (`lot.rs`)

```rust
use muonledger::lot::LotAnnotation;

let ann = LotAnnotation::new();
let ann = LotAnnotation::with_price(Amount::parse("$150.00").unwrap());

ann.price;    // Option<Amount>  -- {$150.00}
ann.date;     // Option<NaiveDate> -- [2024-01-15]
ann.tag;      // Option<String> -- (description)
```

---

## Scope System (`scope.rs`)

```rust
use muonledger::scope::{Scope, SymbolScope, ChildScope, CallScope, BindScope, ScopeValue};

// SymbolScope: local name -> ScopeValue dictionary
let mut scope = SymbolScope::new(None);  // No parent
scope.define("x", ScopeValue::from_node(NodeValue::Integer(42)));

// Lookup
let val = scope.lookup("x");  // Some(ScopeValue)

// ChildScope: delegates to parent
let child = ChildScope::new(&scope);

// CallScope: positional arguments for function calls
let mut call = CallScope::new(&scope);
call.push(ScopeValue::from_node(NodeValue::Integer(10)));

// BindScope: joins two scopes
let bind = BindScope::new(&parent, &grandchild);
```

---

## Command Functions

### Balance Command

```rust
use muonledger::commands::balance::{balance_command, BalanceOptions};

let opts = BalanceOptions {
    flat: false,
    no_total: false,
    show_empty: false,
    depth: 0,            // 0 = unlimited
    patterns: vec![],    // Account filter patterns
};

let output: String = balance_command(&journal, &opts);
```

### Register Command

```rust
use muonledger::commands::register::{register_command, RegisterOptions};

let opts = RegisterOptions {
    wide: false,                  // 132-column layout
    head: None,                   // Limit to first N
    tail: None,                   // Limit to last N
    account_patterns: vec![],     // Account filters
};

let output: String = register_command(&journal, &opts);
```

### Print Command

```rust
use muonledger::commands::print::{print_command, PrintOptions};

let opts = PrintOptions::default();
let output: String = print_command(&journal, &opts);
```

---

## Automated Transactions (`auto_xact.rs`)

```rust
use muonledger::auto_xact::AutomatedTransaction;

let auto = AutomatedTransaction::new("/^Expenses:Food/");
auto.predicate_expr;   // String -- the predicate
auto.posts;            // Vec<Post> -- template postings

// Apply to a journal (matches and generates postings)
apply_auto_xacts(&mut journal);
```

---

## Periodic Transactions (`periodic_xact.rs`)

```rust
use muonledger::periodic_xact::PeriodicTransaction;

let periodic = PeriodicTransaction::new("Monthly");
periodic.period_expr;  // String -- "Monthly"
periodic.posts;        // Vec<Post> -- budget template postings
```

---

## Item (Base Fields) (`item.rs`)

```rust
use muonledger::item::{Item, ItemState, Position};

let mut item = Item::new();
item.date;             // Option<NaiveDate>
item.aux_date;         // Option<NaiveDate>
item.state;            // ItemState::Uncleared | Pending | Cleared
item.note;             // Option<String>
item.metadata;         // HashMap<String, String>
item.tags;             // HashSet<String>
item.position;         // Option<Position> { source, beg_line, end_line }
item.flags;            // u32 (bitfield)

// Flag constants
ITEM_GENERATED         // Generated (not from source file)
ITEM_TEMP              // Temporary (not persisted)
ITEM_INFERRED          // Inferred (e.g., null-amount inference)
```
