# MuonLedger Python API Documentation

API reference for the `muonledger` Python package -- a port of C++ Ledger's double-entry accounting engine.

---

## Module Overview

| Module | Description |
|--------|-------------|
| `muonledger.amount` | Exact-precision commoditized amounts (`Amount`) |
| `muonledger.balance` | Multi-commodity balances (`Balance`) |
| `muonledger.value` | Polymorphic value type with auto-promotion (`Value`) |
| `muonledger.commodity` | Commodity registry and display styles (`Commodity`, `CommodityPool`) |
| `muonledger.account` | Hierarchical account tree (`Account`) |
| `muonledger.item` | Base fields shared by transactions and postings (`Item`) |
| `muonledger.post` | Posting (line item within a transaction) (`Post`) |
| `muonledger.xact` | Transaction (dated journal entry) (`Transaction`) |
| `muonledger.journal` | Central data container (`Journal`) |
| `muonledger.parser` | Textual journal file parser (`TextualParser`) |
| `muonledger.annotate` | Lot annotation types (`Annotation`, `AnnotatedCommodity`) |
| `muonledger.auto_xact` | Automated transactions (`AutomatedTransaction`) |
| `muonledger.periodic_xact` | Periodic/budget transactions (`PeriodicTransaction`) |
| `muonledger.price_history` | Price graph with BFS conversion (`PriceHistory`) |
| `muonledger.expr_token` | Expression tokenizer (`ExprTokenizer`) |
| `muonledger.expr_parser` | Pratt expression parser (`ExprParser`) |
| `muonledger.expr_ast` | Expression AST nodes (`ExprNode`, `OpKind`) |
| `muonledger.query` | Query language parser (`QueryParser`) |
| `muonledger.scope` | Scope chain for symbol resolution (`Scope`, `SymbolScope`) |
| `muonledger.functions` | 39 built-in expression functions |
| `muonledger.format` | Format string parser and evaluator (`Format`) |
| `muonledger.filters` | Posting filter pipeline |
| `muonledger.report` | Report options and filter chain builder (`ReportOptions`) |
| `muonledger.times` | Date/time parsing and period intervals (`DateInterval`) |
| `muonledger.cli` | CLI entry point |
| `muonledger.commands.*` | Command implementations |

---

## Core Types

### `Amount` (`muonledger.amount`)

Exact-precision commoditized amount using `fractions.Fraction`.

```python
from muonledger.amount import Amount

# Parsing
a = Amount("$100.00")
b = Amount("10 AAPL")
c = Amount.parse("EUR 1,234.56")

# Properties
a.quantity        # Fraction(10000, 100) -- exact rational
a.commodity       # Commodity object (or None)
a.precision       # 2 (decimal places)
a.is_null()       # False
a.is_zero()       # False
a.is_negative()   # False

# Arithmetic (returns new Amount)
a + Amount("$50.00")    # $150.00
a - Amount("$30.00")    # $70.00
a * Amount("2")         # $200.00
a / Amount("4")         # $25.00
-a                      # $-100.00
abs(a)                  # $100.00

# Comparison
a == Amount("$100.00")  # True
a < Amount("$200.00")   # True
a > Amount("$50.00")    # True

# Display (preserves learned style: prefix/suffix, thousands, precision)
str(a)                  # "$100.00"
```

**Exceptions**: `AmountError` for parse failures or commodity mismatches in arithmetic.

---

### `Balance` (`muonledger.balance`)

Multi-commodity balance -- holds one `Amount` per commodity.

```python
from muonledger.balance import Balance
from muonledger.amount import Amount

# Construction
bal = Balance()
bal = Balance(Amount("$100.00"))
bal = Balance({"$": Amount("$100.00"), "EUR": Amount("10 EUR")})

# Adding amounts
bal += Amount("$50.00")        # Accumulates same-commodity
bal += Amount("10 AAPL")       # Adds new commodity entry

# Arithmetic
bal2 = bal + Balance(Amount("$25.00"))
bal3 = bal - Balance(Amount("$10.00"))
bal4 = -bal                    # Negate all amounts

# Iteration
for symbol, amount in bal:
    print(f"{symbol}: {amount}")

# Properties
bal.is_zero()                  # True if all amounts are zero
bal.is_empty()                 # True if no amounts
len(bal)                       # Number of commodity entries
bal.single_amount()            # Returns Amount if exactly one commodity, else None
bal.commodity_count()          # Number of distinct commodities
```

---

### `Value` (`muonledger.value`)

Polymorphic value type with automatic type promotion.

```python
from muonledger.value import Value, ValueType

# Construction from various types
v1 = Value(42)                        # INTEGER
v2 = Value(Amount("$100.00"))         # AMOUNT
v3 = Value(Balance(...))              # BALANCE
v4 = Value("hello")                   # STRING
v5 = Value(True)                      # BOOLEAN
v6 = Value(date(2024, 1, 15))         # DATE
v7 = Value(datetime.now())            # DATETIME
v8 = Value([v1, v2])                  # SEQUENCE

# Type checking
v1._type                              # ValueType.INTEGER
v1.is_type(ValueType.INTEGER)         # True

# Type conversion
v1.to_int()                           # 42
v1.to_amount()                        # Amount("42")
v2.to_string()                        # "$100.00"

# Arithmetic (auto-promotes: INTEGER -> AMOUNT -> BALANCE)
v1 + Value(Amount("$10.00"))          # Promotes int to Amount
v2 + Value(Amount("10 EUR"))          # Promotes to Balance

# Comparison
v1 == Value(42)                       # True
v1 < Value(100)                       # True

# Boolean
v1.to_boolean()                       # True (non-zero)
Value(0).to_boolean()                 # False
```

**Type promotion hierarchy**: `INTEGER -> AMOUNT -> BALANCE`. Adding an integer to an amount promotes the integer first. Adding amounts of different commodities promotes to a balance.

---

### `Commodity` and `CommodityPool` (`muonledger.commodity`)

```python
from muonledger.commodity import Commodity, CommodityPool, CommodityStyle

# Pool manages all commodities
pool = CommodityPool()

# Find or create a commodity
usd = pool.find_or_create("$")
eur = pool.find_or_create("EUR")

# Commodity properties
usd.symbol                     # "$"
usd.precision                  # 2 (learned from usage)
usd.style                      # CommodityStyle flags
usd.has_flag(CommodityStyle.SUFFIXED)    # False ($ is prefix)
eur.has_flag(CommodityStyle.SUFFIXED)    # True (EUR is suffix)

# Style flags
CommodityStyle.DEFAULTS        # 0x000
CommodityStyle.SUFFIXED        # 0x001 -- symbol after amount
CommodityStyle.SEPARATED       # 0x002 -- space between symbol and quantity
CommodityStyle.DECIMAL_COMMA   # 0x004 -- comma as decimal separator
CommodityStyle.THOUSANDS       # 0x008 -- grouping separators
CommodityStyle.NOMARKET        # 0x010 -- exclude from market valuations
CommodityStyle.BUILTIN         # 0x020 -- internally created
CommodityStyle.KNOWN           # 0x080 -- declared via directive
```

---

### `Account` (`muonledger.account`)

```python
from muonledger.account import Account

# Root account (created by Journal)
root = Account()                       # name="", depth=0

# Child accounts
child = root.find_or_create("Expenses:Food:Dining")

# Properties
child.name                             # "Dining"
child.fullname                         # "Expenses:Food:Dining"
child.depth                            # 3
child.parent                           # Account("Food")
child.note                             # Optional note

# Children
child.children                         # dict[str, Account]
child.has_children()                   # True/False

# Iteration
for name, acct in root.children.items():
    print(name)                        # "Expenses", "Assets", etc.

# Walk the tree
def walk(acct, indent=0):
    print("  " * indent + acct.name)
    for name, child in sorted(acct.children.items()):
        walk(child, indent + 1)

walk(root)
```

---

### `Post` (`muonledger.post`)

```python
from muonledger.post import Post, POST_VIRTUAL, POST_MUST_BALANCE

post = Post()
post.account                          # Account reference
post.amount                           # Amount (or None if inferred)
post.cost                             # Amount (from @ or @@)
post.assigned_amount                  # Amount (balance assertion)
post.item.date                        # date (from transaction or override)
post.item.state                       # ItemState.CLEARED / PENDING / UNCLEARED
post.item.note                        # Optional note
post.item.metadata                    # dict of key-value metadata
post.item.tags                        # set of tags

# Flags
post.has_flag(POST_VIRTUAL)           # True for (Account) postings
post.has_flag(POST_MUST_BALANCE)      # True for [Account] postings
```

---

### `Transaction` (`muonledger.xact`)

```python
from muonledger.xact import Transaction

xact = Transaction()
xact.payee                            # "Grocery Store"
xact.code                             # "1042" (optional)
xact.posts                            # list[Post]
xact.item.date                        # date(2024, 1, 15)
xact.item.aux_date                    # Optional auxiliary date
xact.item.state                       # ItemState
xact.item.note                        # Optional note
xact.item.metadata                    # dict
xact.item.tags                        # set

# Finalize: infer missing amounts, verify balance
xact.finalize(journal)                # Raises BalanceError if unbalanced
```

---

### `Journal` (`muonledger.journal`)

```python
from muonledger.journal import Journal

journal = Journal()

# After parsing:
journal.master                        # Root Account
journal.xacts                         # list[Transaction]
journal.auto_xacts                    # list[AutomatedTransaction]
journal.period_xacts                  # list[PeriodicTransaction]
journal.commodity_pool                # CommodityPool
journal.sources                       # list[str] -- source file paths
journal.prices                        # list[tuple] -- (date, commodity, amount)
journal.bucket                        # Optional default Account
journal.account_aliases               # dict[str, Account]
journal.price_history                 # PriceHistory

# Iteration helpers
for post in journal.all_posts():
    print(post.account.fullname, post.amount)

for xact in journal.xacts:
    print(xact.item.date, xact.payee)
```

---

## Parser

### `TextualParser` (`muonledger.parser`)

```python
from muonledger.parser import TextualParser, ParseError
from muonledger.journal import Journal

journal = Journal()
parser = TextualParser()

# Parse from file
parser.parse("journal.dat", journal)
parser.parse(Path("journal.dat"), journal)

# Parse from string
parser.parse_string("""
2024/01/15 Grocery Store
    Expenses:Food          $42.50
    Assets:Checking
""", journal)

# Parse errors include source and line number
try:
    parser.parse_string("invalid data", journal)
except ParseError as e:
    print(e.message)        # Description
    print(e.line_num)       # Line number
    print(e.source)         # Source file
    print(e.line_content)   # Offending line
```

---

## Expression System

### `ExprParser` (`muonledger.expr_parser`)

```python
from muonledger.expr_parser import ExprParser, compile

# Compile an expression to an AST
node = compile("2 + 3 * 4")
node = compile("amount > $100 and account =~ /Expenses/")
node = compile("format_date(date, '%Y/%m/%d')")

# Evaluate against a scope
from muonledger.scope import SymbolScope
from muonledger.functions import register_builtins

scope = SymbolScope()
register_builtins(scope)
result = node.calc(scope)
```

### `ExprTokenizer` (`muonledger.expr_token`)

```python
from muonledger.expr_token import ExprTokenizer, TokenKind

tokenizer = ExprTokenizer("amount + $100")
for token in tokenizer:
    print(token.kind, token.value)
    # TokenKind.IDENT "amount"
    # TokenKind.PLUS None
    # TokenKind.AMOUNT "$100"
```

### `ExprNode` / `OpKind` (`muonledger.expr_ast`)

The AST node types mirror C++ Ledger's expression tree:

| OpKind | Description |
|--------|-------------|
| `O_ADD`, `O_SUB`, `O_MUL`, `O_DIV` | Arithmetic |
| `O_EQ`, `O_NE`, `O_LT`, `O_LTE`, `O_GT`, `O_GTE` | Comparison |
| `O_AND`, `O_OR`, `O_NOT` | Logical |
| `O_MATCH` | Regex match (`=~`) |
| `O_QUERY`, `O_COLON` | Ternary (`? :`) |
| `O_CALL` | Function call |
| `O_LOOKUP` | Member access (`.`) |
| `O_LAMBDA` | Lambda (`->`) |
| `O_DEFINE` | Assignment (`=`) |
| `O_CONS` | Comma-separated sequence |
| `O_SEQ` | Semicolon-separated sequence |
| `O_VALUE` | Literal value |
| `O_IDENT` | Identifier reference |

---

## Query Language

### `QueryParser` (`muonledger.query`)

```python
from muonledger.query import parse_query, QueryParser

# Parse a query string into an AST
node = parse_query("food and @grocery")
# Equivalent to: (account =~ /food/) and (payee =~ /grocery/)

node = parse_query("Expenses not @Amazon")
# Equivalent to: (account =~ /Expenses/) and not (payee =~ /Amazon/)

# Query prefixes:
#   (bare)  -> account match
#   @term   -> payee match
#   #term   -> code match
#   =term   -> note match
#   %term   -> tag match
#   /regex/ -> regex account match
```

---

## Filter Pipeline

### Filter Classes (`muonledger.filters`)

The filter pipeline processes postings through a chain of handlers:

```python
from muonledger.filters import (
    CollectPosts,
    FilterPosts,
    SortPosts,
    CalcPosts,
    SubtotalPosts,
    IntervalPosts,
    CollapsePosts,
    TruncatePosts,
    InvertPosts,
    RelatedPosts,
    DisplayFilter,
    MarketConvertPosts,
)

# Build a pipeline (inner to outer)
collector = CollectPosts()
calc = CalcPosts(collector)
sort = SortPosts(calc, key_fn=lambda p: p.account.fullname)
filt = FilterPosts(sort, predicate=lambda p: p.amount and not p.amount.is_zero())

# Feed postings
for post in journal.all_posts():
    filt(post)
filt.flush()

# Retrieve results
for post in collector.posts:
    print(post.account.fullname, post.amount, post.xdata.get("total"))
```

### `ReportOptions` and `build_filter_chain` (`muonledger.report`)

```python
from muonledger.report import ReportOptions, build_filter_chain, apply_to_journal

opts = ReportOptions(
    begin=date(2024, 1, 1),
    end=date(2024, 2, 1),
    subtotal=True,
    sort_expr="account",
    flat=True,
    cleared_only=True,
)

# Get qualifying postings
posts = apply_to_journal(journal, opts)

# Or build the full filter chain
collector = CollectPosts()
chain = build_filter_chain(opts, collector, journal)
for post in posts:
    chain(post)
chain.flush()
```

---

## Built-in Functions (`muonledger.functions`)

Register all 39 built-in functions into a scope:

```python
from muonledger.scope import SymbolScope
from muonledger.functions import register_builtins

scope = SymbolScope()
register_builtins(scope)
```

### Function Reference

| Function | Signature | Description |
|----------|-----------|-------------|
| **Math** | | |
| `abs` | `abs(value)` | Absolute value |
| `round` | `round(value [, places])` | Round to N decimal places |
| `roundto` | `roundto(value, places)` | Round to N decimal places |
| `ceil` | `ceil(value)` | Ceiling |
| `floor` | `floor(value)` | Floor |
| `min` | `min(a, b)` | Minimum of two values |
| `max` | `max(a, b)` | Maximum of two values |
| **String** | | |
| `str` | `str(value)` | Convert to string |
| `strip` | `strip(string)` | Remove whitespace |
| `trim` | `trim(string)` | Remove whitespace |
| `join` | `join(seq, sep)` | Join sequence with separator |
| `quoted` | `quoted(string)` | Wrap in double quotes |
| `justify` | `justify(str, width, left)` | Justify to width |
| `truncated` | `truncated(str, width)` | Truncate to width |
| `format` | `format(fmt, value)` | Format with format string |
| **Date** | | |
| `now` | `now()` | Current datetime |
| `today` | `today()` | Current date |
| `date` | `date(value)` | Extract date from value |
| `format_date` | `format_date(date, fmt)` | Format date as string |
| **Type** | | |
| `int` | `int(value)` | Convert to integer |
| `quantity` | `quantity(amount)` | Numeric quantity (no commodity) |
| `commodity` | `commodity(amount)` | Commodity symbol string |
| `is_seq` | `is_seq(value)` | True if value is a sequence |
| `to_amount` | `to_amount(value)` | Convert to Amount |
| `to_balance` | `to_balance(value)` | Convert to Balance |
| `to_string` | `to_string(value)` | Convert to string |
| `to_int` | `to_int(value)` | Convert to integer |
| `to_date` | `to_date(value)` | Convert to date |
| `to_boolean` | `to_boolean(value)` | Convert to boolean |
| **Posting/Account** | | |
| `amount` | `amount` | Current posting amount |
| `account` | `account` | Current account name |
| `payee` | `payee` | Current transaction payee |
| `total` | `total` | Running total |
| `display_amount` | `display_amount` | Displayed amount value |
| `display_total` | `display_total` | Displayed total value |
| `has_tag` | `has_tag(pattern)` | True if post has matching tag |
| `tag` | `tag(name)` | Get tag value |
| `post` | `post` | Current post object |
| `lot_date` | `lot_date` | Lot acquisition date |
| `lot_price` | `lot_price` | Lot acquisition price |
| `lot_tag` | `lot_tag` | Lot tag string |
| **Constants** | | |
| `true` | | Boolean true |
| `false` | | Boolean false |

---

## Price History (`muonledger.price_history`)

```python
from muonledger.price_history import PriceHistory
from muonledger.amount import Amount
from datetime import date

ph = PriceHistory()

# Add price entries
ph.add_price(date(2024, 1, 15), "AAPL", Amount("$150.00"))
ph.add_price(date(2024, 1, 15), "EUR", Amount("$1.10"))
ph.add_price(date(2024, 2, 1), "AAPL", Amount("$155.00"))

# Find a direct price
rate, when = ph.find_price("AAPL", "$")
# rate = Fraction(15500, 100), when = date(2024, 2, 1)

# Find price as of a specific date
rate, when = ph.find_price("AAPL", "$", date=date(2024, 1, 20))

# Convert an amount (uses BFS shortest-path for transitive conversions)
converted = ph.convert(Amount("10 AAPL"), "$")
# $1,550.00

# Transitive: AAPL -> $ -> EUR
converted = ph.convert(Amount("10 AAPL"), "EUR")
```

---

## Format Strings (`muonledger.format`)

```python
from muonledger.format import Format

# Parse a format string
fmt = Format("%-20(account)  %12(total)\n")

# Evaluate against a scope
output = fmt.format(scope)

# Format syntax:
#   Literal text         -- passed through
#   %(expr)              -- evaluate expression
#   %-20(expr)           -- left-aligned, 20 chars wide
#   %20(expr)            -- right-aligned, 20 chars wide
#   %.30(expr)           -- truncate to 30 chars
#   %20.30(expr)         -- min 20, max 30 chars
#   %%                   -- literal %
#   \n, \t               -- escape sequences
```

---

## Lot Annotations (`muonledger.annotate`)

```python
from muonledger.annotate import Annotation, KeepDetails, AnnotatedCommodity

# Annotation fields
ann = Annotation(
    price=Amount("$150.00"),         # {$150.00}
    date=date(2024, 1, 15),          # [2024-01-15]
    tag="initial purchase",          # (initial purchase)
    value_expr=None,                 # ((expr)) -- optional
)

# KeepDetails controls which fields are preserved
keep = KeepDetails(
    keep_price=True,
    keep_date=True,
    keep_tag=False,
)

# AnnotatedCommodity pairs a base commodity with an annotation
acm = AnnotatedCommodity(commodity, annotation)
```

---

## Command Functions

All command functions accept a `Journal` and optional argument list, returning a string:

```python
from muonledger.commands.balance import balance_command
from muonledger.commands.register import register_command
from muonledger.commands.print_cmd import print_command
from muonledger.commands.equity import equity_command
from muonledger.commands.stats import stats_command
from muonledger.commands.prices import prices_command
from muonledger.commands.pricedb import pricedb_command
from muonledger.commands.pricemap import pricemap_command
from muonledger.commands.listing import (
    accounts_command,
    payees_command,
    tags_command,
    commodities_command,
)
from muonledger.commands.convert import convert_command

# Example: balance report
output = balance_command(journal, ["Expenses", "--flat"])
print(output)

# Example: register report
output = register_command(journal, ["Food"])
print(output)

# Example: equity (opening balances)
output = equity_command(journal)
print(output)

# Example: stats
output = stats_command(journal)
print(output)
```

---

## Date/Time Utilities (`muonledger.times`)

```python
from muonledger.times import (
    parse_date,
    parse_datetime,
    parse_period,
    DateInterval,
    today,
    now,
    format_date,
)

# Parse dates
d = parse_date("2024/01/15")        # date(2024, 1, 15)
d = parse_date("2024-01-15")        # date(2024, 1, 15)

# Parse period expressions
interval = parse_period("monthly")
interval = parse_period("weekly")
interval = parse_period("quarterly")

# DateInterval iteration
di = DateInterval(start=date(2024, 1, 1), finish=date(2024, 6, 1), period="monthly")
for start, end in di:
    print(f"{start} to {end}")
    # 2024-01-01 to 2024-02-01
    # 2024-02-01 to 2024-03-01
    # ...

# Current date/time
today()                              # date.today()
now()                                # datetime.now()
```
