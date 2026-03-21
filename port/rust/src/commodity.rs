//! Commodity and CommodityPool for double-entry accounting.
//!
//! This module provides the `Commodity` and `CommodityPool` types, a Rust port
//! of Ledger's `commodity_t` and `commodity_pool_t`. Commodities represent
//! currencies, stocks, mutual funds, and any other unit of value. The pool is a
//! registry that manages creation, lookup, and style learning.
//!
//! A key design principle (inherited from Ledger) is that display formatting is
//! *learned* from usage: the first time a commodity like "$" is seen with two
//! decimal places and a thousands separator, those style flags are recorded and
//! applied to all future output of that commodity.

use std::cell::RefCell;
use std::collections::HashMap;
use std::fmt;

use bitflags::bitflags;
use regex::Regex;

use lazy_static::lazy_static;

// ---------------------------------------------------------------------------
// CommodityStyle (bitflags)
// ---------------------------------------------------------------------------

bitflags! {
    /// Bit-flags controlling how a commodity is displayed.
    ///
    /// Mirrors the `COMMODITY_STYLE_*` constants from Ledger's `commodity.h`.
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub struct CommodityStyle: u32 {
        const DEFAULTS             = 0x000;
        const SUFFIXED             = 0x001;
        const SEPARATED            = 0x002;
        const DECIMAL_COMMA        = 0x004;
        const THOUSANDS            = 0x008;
        const NOMARKET             = 0x010;
        const BUILTIN              = 0x020;
        const KNOWN                = 0x080;
        const THOUSANDS_APOSTROPHE = 0x4000;
    }
}

impl Default for CommodityStyle {
    fn default() -> Self {
        CommodityStyle::DEFAULTS
    }
}

// ---------------------------------------------------------------------------
// CommodityId
// ---------------------------------------------------------------------------

/// An opaque handle into a `CommodityPool`.
///
/// This is a lightweight, copyable index. All actual commodity data lives in
/// the pool and is accessed through this id.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct CommodityId(pub(crate) usize);

impl CommodityId {
    /// Return the raw index value.
    pub fn index(self) -> usize {
        self.0
    }
}

// ---------------------------------------------------------------------------
// Commodity
// ---------------------------------------------------------------------------

lazy_static! {
    /// Characters that require a symbol to be quoted.
    static ref NEEDS_QUOTING: Regex =
        Regex::new(r#"[\s\d+\-*/=<>!@#%^&|?;,.\[\]{}()~]"#).unwrap();
}

/// A commodity (currency / stock / unit of value).
#[derive(Debug, Clone)]
pub struct Commodity {
    symbol: String,
    pub precision: u32,
    flags: CommodityStyle,
    pub note: Option<String>,
}

impl Commodity {
    /// Create a new commodity.
    pub fn new(
        symbol: &str,
        precision: u32,
        flags: CommodityStyle,
        note: Option<String>,
    ) -> Self {
        Self {
            symbol: symbol.to_string(),
            precision,
            flags,
            note,
        }
    }

    // ---- symbol -----------------------------------------------------------

    /// The canonical commodity name (e.g., `"$"`, `"EUR"`, `"AAPL"`).
    pub fn symbol(&self) -> &str {
        &self.symbol
    }

    // ---- flags ------------------------------------------------------------

    /// Get the style flags.
    pub fn flags(&self) -> CommodityStyle {
        self.flags
    }

    /// Set the style flags.
    pub fn set_flags(&mut self, flags: CommodityStyle) {
        self.flags = flags;
    }

    /// Return `true` if all bits in `flag` are set.
    pub fn has_flags(&self, flag: CommodityStyle) -> bool {
        self.flags.contains(flag)
    }

    /// Set the given flag bits.
    pub fn add_flags(&mut self, flag: CommodityStyle) {
        self.flags |= flag;
    }

    /// Clear the given flag bits.
    pub fn drop_flags(&mut self, flag: CommodityStyle) {
        self.flags &= !flag;
    }

    // ---- derived properties -----------------------------------------------

    /// `true` when the symbol is printed before the quantity.
    pub fn is_prefix(&self) -> bool {
        !self.has_flags(CommodityStyle::SUFFIXED)
    }

    /// The symbol, quoted if it contains special characters.
    pub fn qualified_symbol(&self) -> String {
        if NEEDS_QUOTING.is_match(&self.symbol) {
            format!("\"{}\"", self.symbol)
        } else {
            self.symbol.clone()
        }
    }

    /// A commodity is truthy unless it is the null commodity (empty symbol).
    pub fn is_valid(&self) -> bool {
        !self.symbol.is_empty()
    }
}

impl fmt::Display for Commodity {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.qualified_symbol())
    }
}

impl PartialEq for Commodity {
    fn eq(&self, other: &Self) -> bool {
        self.symbol == other.symbol
    }
}

impl Eq for Commodity {}

impl std::hash::Hash for Commodity {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.symbol.hash(state);
    }
}

// ---------------------------------------------------------------------------
// CommodityPool
// ---------------------------------------------------------------------------

/// Registry of all known commodities.
///
/// Mirrors Ledger's `commodity_pool_t`. Uses interior mutability (`RefCell`)
/// since Ledger's pool is a process-wide mutable singleton.
///
/// Commodities are stored in a `Vec` and referenced by `CommodityId` (index).
/// A `HashMap` provides O(1) lookup by symbol string.
pub struct CommodityPool {
    commodities: Vec<Commodity>,
    index: HashMap<String, CommodityId>,
    pub default_commodity: Option<CommodityId>,
    pub null_commodity: CommodityId,
}

impl fmt::Debug for CommodityPool {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CommodityPool")
            .field("len", &self.commodities.len())
            .finish()
    }
}

impl CommodityPool {
    /// Create a new pool with the null commodity pre-registered.
    pub fn new() -> Self {
        let null = Commodity::new(
            "",
            0,
            CommodityStyle::BUILTIN | CommodityStyle::NOMARKET,
            None,
        );
        let mut pool = Self {
            commodities: vec![null],
            index: HashMap::new(),
            default_commodity: None,
            null_commodity: CommodityId(0),
        };
        pool.index.insert(String::new(), CommodityId(0));
        pool
    }

    // ---- lookup / creation ------------------------------------------------

    /// Look up an existing commodity by symbol. Returns `None` if not found.
    pub fn find(&self, symbol: &str) -> Option<CommodityId> {
        self.index.get(symbol).copied()
    }

    /// Create a new commodity and register it in the pool.
    ///
    /// Returns an error if the symbol already exists.
    pub fn create(
        &mut self,
        symbol: &str,
        precision: u32,
        flags: CommodityStyle,
        note: Option<String>,
    ) -> Result<CommodityId, String> {
        if self.index.contains_key(symbol) {
            return Err(format!("Commodity {:?} already exists in pool", symbol));
        }
        let id = CommodityId(self.commodities.len());
        let comm = Commodity::new(symbol, precision, flags, note);
        self.commodities.push(comm);
        self.index.insert(symbol.to_string(), id);
        Ok(id)
    }

    /// Look up a commodity by symbol, creating it if it does not exist.
    pub fn find_or_create(&mut self, symbol: &str) -> CommodityId {
        if let Some(id) = self.find(symbol) {
            return id;
        }
        self.create(symbol, 0, CommodityStyle::DEFAULTS, None)
            .expect("find_or_create: symbol should not already exist after find() returned None")
    }

    // ---- commodity access -------------------------------------------------

    /// Get a reference to the commodity for the given id.
    ///
    /// # Panics
    /// Panics if the id is out of range (should never happen with valid ids).
    pub fn get(&self, id: CommodityId) -> &Commodity {
        &self.commodities[id.0]
    }

    /// Get a mutable reference to the commodity for the given id.
    pub fn get_mut(&mut self, id: CommodityId) -> &mut Commodity {
        &mut self.commodities[id.0]
    }

    // ---- style learning ---------------------------------------------------

    /// Record display-style information learned from a parsed amount.
    ///
    /// When an amount like `$1,000.00` is first seen, the parser calls this
    /// method to teach the pool that `$` is a prefix symbol with 2-decimal
    /// precision and comma thousands separators.
    ///
    /// If the commodity already exists, the precision is updated to the maximum
    /// of the current and incoming values, and any new flags are added (flags
    /// are never removed by learning).
    pub fn learn_style(
        &mut self,
        symbol: &str,
        prefix: bool,
        precision: u32,
        thousands: bool,
        decimal_comma: bool,
        separated: bool,
    ) -> CommodityId {
        let id = self.find_or_create(symbol);

        // Build the learned flag set.
        let mut learned = CommodityStyle::DEFAULTS;
        if !prefix {
            learned |= CommodityStyle::SUFFIXED;
        }
        if separated {
            learned |= CommodityStyle::SEPARATED;
        }
        if thousands {
            learned |= CommodityStyle::THOUSANDS;
        }
        if decimal_comma {
            learned |= CommodityStyle::DECIMAL_COMMA;
        }

        let comm = self.get_mut(id);

        // Merge: flags grow monotonically; precision takes the max.
        comm.add_flags(learned);
        if precision > comm.precision {
            comm.precision = precision;
        }

        // If the caller says prefix=true and SUFFIXED was previously set,
        // drop SUFFIXED (prefix wins).
        if prefix && comm.has_flags(CommodityStyle::SUFFIXED) {
            comm.drop_flags(CommodityStyle::SUFFIXED);
        }

        id
    }

    // ---- iteration --------------------------------------------------------

    /// Number of commodities in the pool (including null).
    pub fn len(&self) -> usize {
        self.commodities.len()
    }

    /// Whether the pool is empty (it never truly is because of null commodity).
    pub fn is_empty(&self) -> bool {
        self.commodities.is_empty()
    }

    /// Check whether a symbol is registered.
    pub fn contains(&self, symbol: &str) -> bool {
        self.index.contains_key(symbol)
    }

    /// Iterate over all commodities.
    pub fn iter(&self) -> impl Iterator<Item = (CommodityId, &Commodity)> {
        self.commodities
            .iter()
            .enumerate()
            .map(|(i, c)| (CommodityId(i), c))
    }
}

impl Default for CommodityPool {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Thread-local current pool (mirrors Python's CommodityPool.current_pool)
// ---------------------------------------------------------------------------

thread_local! {
    static CURRENT_POOL: RefCell<Option<CommodityPool>> = RefCell::new(None);
}

/// Execute a closure with a reference to the current (thread-local) pool.
///
/// If no pool exists yet, one is created automatically.
pub fn with_current_pool<F, R>(f: F) -> R
where
    F: FnOnce(&CommodityPool) -> R,
{
    CURRENT_POOL.with(|cell| {
        let mut borrow = cell.borrow_mut();
        if borrow.is_none() {
            *borrow = Some(CommodityPool::new());
        }
        f(borrow.as_ref().unwrap())
    })
}

/// Execute a closure with a mutable reference to the current pool.
pub fn with_current_pool_mut<F, R>(f: F) -> R
where
    F: FnOnce(&mut CommodityPool) -> R,
{
    CURRENT_POOL.with(|cell| {
        let mut borrow = cell.borrow_mut();
        if borrow.is_none() {
            *borrow = Some(CommodityPool::new());
        }
        f(borrow.as_mut().unwrap())
    })
}

/// Reset the current (thread-local) pool. Useful in tests.
pub fn reset_current_pool() {
    CURRENT_POOL.with(|cell| {
        *cell.borrow_mut() = None;
    });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---- CommodityStyle ---------------------------------------------------

    #[test]
    fn style_defaults_is_empty() {
        let s = CommodityStyle::DEFAULTS;
        assert!(s.is_empty());
        assert!(!s.contains(CommodityStyle::SUFFIXED));
    }

    #[test]
    fn style_bitwise_ops() {
        let mut s = CommodityStyle::SUFFIXED | CommodityStyle::SEPARATED;
        assert!(s.contains(CommodityStyle::SUFFIXED));
        assert!(s.contains(CommodityStyle::SEPARATED));
        assert!(!s.contains(CommodityStyle::THOUSANDS));

        s |= CommodityStyle::THOUSANDS;
        assert!(s.contains(CommodityStyle::THOUSANDS));

        s &= !CommodityStyle::SUFFIXED;
        assert!(!s.contains(CommodityStyle::SUFFIXED));
    }

    // ---- Commodity --------------------------------------------------------

    #[test]
    fn commodity_basic() {
        let c = Commodity::new("$", 2, CommodityStyle::DEFAULTS, None);
        assert_eq!(c.symbol(), "$");
        assert_eq!(c.precision, 2);
        assert!(c.is_prefix());
        assert!(c.is_valid());
    }

    #[test]
    fn commodity_suffixed() {
        let c = Commodity::new("EUR", 2, CommodityStyle::SUFFIXED, None);
        assert!(!c.is_prefix());
        assert!(c.has_flags(CommodityStyle::SUFFIXED));
    }

    #[test]
    fn commodity_qualified_symbol_plain() {
        let c = Commodity::new("USD", 2, CommodityStyle::DEFAULTS, None);
        assert_eq!(c.qualified_symbol(), "USD");
    }

    #[test]
    fn commodity_qualified_symbol_needs_quoting() {
        let c = Commodity::new("Mutual Fund A", 4, CommodityStyle::DEFAULTS, None);
        assert_eq!(c.qualified_symbol(), "\"Mutual Fund A\"");
    }

    #[test]
    fn commodity_null_is_not_valid() {
        let c = Commodity::new("", 0, CommodityStyle::BUILTIN, None);
        assert!(!c.is_valid());
    }

    #[test]
    fn commodity_equality() {
        let a = Commodity::new("$", 2, CommodityStyle::DEFAULTS, None);
        let b = Commodity::new("$", 4, CommodityStyle::SUFFIXED, None);
        assert_eq!(a, b); // equality is by symbol only
    }

    #[test]
    fn commodity_display() {
        let c = Commodity::new("$", 2, CommodityStyle::DEFAULTS, None);
        assert_eq!(format!("{}", c), "$");
    }

    #[test]
    fn commodity_flags_mutation() {
        let mut c = Commodity::new("$", 2, CommodityStyle::DEFAULTS, None);
        assert!(!c.has_flags(CommodityStyle::THOUSANDS));

        c.add_flags(CommodityStyle::THOUSANDS);
        assert!(c.has_flags(CommodityStyle::THOUSANDS));

        c.drop_flags(CommodityStyle::THOUSANDS);
        assert!(!c.has_flags(CommodityStyle::THOUSANDS));
    }

    // ---- CommodityId ------------------------------------------------------

    #[test]
    fn commodity_id_is_copy() {
        let id = CommodityId(42);
        let id2 = id; // Copy
        assert_eq!(id, id2);
        assert_eq!(id.index(), 42);
    }

    // ---- CommodityPool ---------------------------------------------------

    #[test]
    fn pool_has_null_commodity() {
        let pool = CommodityPool::new();
        assert_eq!(pool.len(), 1);
        let null = pool.get(pool.null_commodity);
        assert_eq!(null.symbol(), "");
        assert!(!null.is_valid());
        assert!(null.has_flags(CommodityStyle::BUILTIN));
        assert!(null.has_flags(CommodityStyle::NOMARKET));
    }

    #[test]
    fn pool_find_or_create() {
        let mut pool = CommodityPool::new();
        let id1 = pool.find_or_create("$");
        let id2 = pool.find_or_create("$");
        assert_eq!(id1, id2);
        assert_eq!(pool.len(), 2); // null + $
        assert_eq!(pool.get(id1).symbol(), "$");
    }

    #[test]
    fn pool_create_duplicate_errors() {
        let mut pool = CommodityPool::new();
        pool.create("$", 2, CommodityStyle::DEFAULTS, None).unwrap();
        let result = pool.create("$", 4, CommodityStyle::DEFAULTS, None);
        assert!(result.is_err());
    }

    #[test]
    fn pool_find_nonexistent() {
        let pool = CommodityPool::new();
        assert!(pool.find("NOPE").is_none());
    }

    #[test]
    fn pool_contains() {
        let mut pool = CommodityPool::new();
        pool.find_or_create("USD");
        assert!(pool.contains("USD"));
        assert!(!pool.contains("GBP"));
    }

    #[test]
    fn pool_learn_style_basic() {
        let mut pool = CommodityPool::new();
        let id = pool.learn_style("$", true, 2, true, false, false);
        let c = pool.get(id);
        assert!(c.is_prefix());
        assert_eq!(c.precision, 2);
        assert!(c.has_flags(CommodityStyle::THOUSANDS));
        assert!(!c.has_flags(CommodityStyle::DECIMAL_COMMA));
    }

    #[test]
    fn pool_learn_style_suffix() {
        let mut pool = CommodityPool::new();
        let id = pool.learn_style("EUR", false, 2, false, true, true);
        let c = pool.get(id);
        assert!(!c.is_prefix());
        assert!(c.has_flags(CommodityStyle::SUFFIXED));
        assert!(c.has_flags(CommodityStyle::SEPARATED));
        assert!(c.has_flags(CommodityStyle::DECIMAL_COMMA));
    }

    #[test]
    fn pool_learn_style_precision_max() {
        let mut pool = CommodityPool::new();
        pool.learn_style("$", true, 2, false, false, false);
        pool.learn_style("$", true, 4, false, false, false);
        let id = pool.find("$").unwrap();
        assert_eq!(pool.get(id).precision, 4);

        // Learning with lower precision should not reduce it.
        pool.learn_style("$", true, 1, false, false, false);
        assert_eq!(pool.get(id).precision, 4);
    }

    #[test]
    fn pool_learn_style_flags_grow_monotonically() {
        let mut pool = CommodityPool::new();
        pool.learn_style("$", true, 2, true, false, false);
        pool.learn_style("$", true, 2, false, false, true);
        let id = pool.find("$").unwrap();
        let c = pool.get(id);
        // THOUSANDS from first call should still be set.
        assert!(c.has_flags(CommodityStyle::THOUSANDS));
        // SEPARATED from second call should now be set.
        assert!(c.has_flags(CommodityStyle::SEPARATED));
    }

    #[test]
    fn pool_learn_style_prefix_overrides_suffix() {
        let mut pool = CommodityPool::new();
        // First learn as suffix.
        pool.learn_style("CHF", false, 2, false, false, false);
        let id = pool.find("CHF").unwrap();
        assert!(pool.get(id).has_flags(CommodityStyle::SUFFIXED));

        // Then learn as prefix — should drop SUFFIXED.
        pool.learn_style("CHF", true, 2, false, false, false);
        assert!(!pool.get(id).has_flags(CommodityStyle::SUFFIXED));
        assert!(pool.get(id).is_prefix());
    }

    #[test]
    fn pool_iterate() {
        let mut pool = CommodityPool::new();
        pool.find_or_create("$");
        pool.find_or_create("EUR");

        let symbols: Vec<&str> = pool.iter().map(|(_, c)| c.symbol()).collect();
        assert!(symbols.contains(&""));
        assert!(symbols.contains(&"$"));
        assert!(symbols.contains(&"EUR"));
        assert_eq!(symbols.len(), 3);
    }

    #[test]
    fn pool_default_commodity() {
        let mut pool = CommodityPool::new();
        assert!(pool.default_commodity.is_none());

        let id = pool.find_or_create("USD");
        pool.default_commodity = Some(id);
        assert_eq!(pool.default_commodity, Some(id));
    }

    // ---- Thread-local pool ------------------------------------------------

    #[test]
    fn current_pool_auto_creates() {
        reset_current_pool();
        let len = with_current_pool(|p| p.len());
        assert_eq!(len, 1); // just the null commodity
    }

    #[test]
    fn current_pool_mut_and_read() {
        reset_current_pool();
        let id = with_current_pool_mut(|p| p.find_or_create("BTC"));
        let sym = with_current_pool(|p| p.get(id).symbol().to_string());
        assert_eq!(sym, "BTC");
    }

    #[test]
    fn current_pool_reset() {
        reset_current_pool();
        with_current_pool_mut(|p| {
            p.find_or_create("XYZ");
        });
        reset_current_pool();
        let found = with_current_pool(|p| p.find("XYZ"));
        assert!(found.is_none());
    }
}
