//! Central container for all financial data in a Ledger session.
//!
//! Ported from ledger's `journal.h` / `journal.cc`. The `Journal` owns the
//! account arena (rooted at master), all parsed transactions, and a reference
//! to the shared `CommodityPool`.
//!
//! There is exactly one journal per session. Parsing populates it and the
//! reporting engine reads from it.

use std::collections::HashMap;
use std::fmt;

use chrono::NaiveDate;

use crate::account::{AccountArena, AccountId};
use crate::amount::Amount;
use crate::auto_xact::AutomatedTransaction;
use crate::commodity::{CommodityId, CommodityPool};
use crate::periodic_xact::PeriodicTransaction;
use crate::xact::Transaction;

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------

/// The central container for all financial data.
///
/// On construction an invisible root `Account` (with an empty name) is
/// created as master, mirroring ledger's `journal_t` constructor.
pub struct Journal {
    /// The account arena (owns all accounts; root is at index 0).
    pub accounts: AccountArena,
    /// Regular transactions in parse order.
    pub xacts: Vec<Transaction>,
    /// Automated transactions (`= PREDICATE` entries).
    pub auto_xacts: Vec<AutomatedTransaction>,
    /// Periodic transactions (`~ PERIOD` entries).
    pub periodic_xacts: Vec<PeriodicTransaction>,
    /// The shared commodity pool.
    pub commodity_pool: CommodityPool,
    /// Source file paths that were loaded.
    pub sources: Vec<String>,
    /// Whether any data has been loaded.
    pub was_loaded: bool,
    /// Default account for unbalanced postings (set by `A`/`bucket` directive).
    pub bucket: Option<AccountId>,
    /// Default year for date parsing.
    pub default_year: Option<i32>,
    /// Account aliases: map from alias name to account id.
    pub account_aliases: HashMap<String, AccountId>,
    /// Price history entries: (date, commodity_symbol, price_amount).
    pub prices: Vec<(NaiveDate, String, Amount)>,
    /// Tag declarations (from `tag` directive).
    pub tag_declarations: Vec<String>,
    /// Payee declarations (from `payee` directive).
    pub payee_declarations: Vec<String>,
    /// Stack of account prefixes from `apply account` directives.
    pub apply_account_stack: Vec<String>,
    /// Stack of tags from `apply tag` directives.
    pub apply_tag_stack: Vec<String>,
    /// No-market commodity symbols (from `N` directive).
    pub no_market_commodities: Vec<String>,
    /// Variable definitions (from `define` directive).
    pub defines: HashMap<String, String>,
}

impl Journal {
    /// Create a new empty journal.
    pub fn new() -> Self {
        Self {
            accounts: AccountArena::new(),
            xacts: Vec::new(),
            auto_xacts: Vec::new(),
            periodic_xacts: Vec::new(),
            commodity_pool: CommodityPool::new(),
            sources: Vec::new(),
            was_loaded: false,
            bucket: None,
            default_year: None,
            account_aliases: HashMap::new(),
            prices: Vec::new(),
            tag_declarations: Vec::new(),
            payee_declarations: Vec::new(),
            apply_account_stack: Vec::new(),
            apply_tag_stack: Vec::new(),
            no_market_commodities: Vec::new(),
            defines: HashMap::new(),
        }
    }

    /// Create a new journal with an existing commodity pool.
    pub fn with_commodity_pool(pool: CommodityPool) -> Self {
        Self {
            accounts: AccountArena::new(),
            xacts: Vec::new(),
            auto_xacts: Vec::new(),
            periodic_xacts: Vec::new(),
            commodity_pool: pool,
            sources: Vec::new(),
            was_loaded: false,
            bucket: None,
            default_year: None,
            account_aliases: HashMap::new(),
            prices: Vec::new(),
            tag_declarations: Vec::new(),
            payee_declarations: Vec::new(),
            apply_account_stack: Vec::new(),
            apply_tag_stack: Vec::new(),
            no_market_commodities: Vec::new(),
            defines: HashMap::new(),
        }
    }

    // ---- transaction management ---------------------------------------------

    /// Add a transaction to the journal after finalizing it.
    ///
    /// Calls `Transaction::finalize()` to infer missing amounts and verify
    /// double-entry balance. Returns `Ok(true)` if the transaction was
    /// successfully added, `Ok(false)` if finalization indicated the
    /// transaction should be skipped (e.g. all-null amounts).
    ///
    /// Propagates `BalanceError` from `finalize()` if the transaction does
    /// not balance.
    pub fn add_xact(&mut self, mut xact: Transaction) -> Result<bool, crate::xact::BalanceError> {
        if !xact.finalize()? {
            return Ok(false);
        }
        self.xacts.push(xact);
        Ok(true)
    }

    /// Remove a transaction by index.
    ///
    /// Panics if the index is out of bounds.
    pub fn remove_xact(&mut self, index: usize) -> Transaction {
        self.xacts.remove(index)
    }

    /// Return the number of transactions.
    pub fn xact_count(&self) -> usize {
        self.xacts.len()
    }

    // ---- account helpers ----------------------------------------------------

    /// The root account id (always 0).
    pub fn master(&self) -> AccountId {
        self.accounts.root_id()
    }

    /// Look up or create an account by colon-separated path.
    ///
    /// Delegates to `AccountArena::find_account` on the root.
    pub fn find_account(&mut self, path: &str, auto_create: bool) -> Option<AccountId> {
        let root = self.accounts.root_id();
        self.accounts.find_account(root, path, auto_create)
    }

    /// Get the full account name for an account id.
    pub fn account_fullname(&self, id: AccountId) -> String {
        self.accounts.fullname(id)
    }

    // ---- commodity helpers --------------------------------------------------

    /// Find or create a commodity in the shared pool.
    pub fn register_commodity(&mut self, symbol: &str) -> CommodityId {
        self.commodity_pool.find_or_create(symbol)
    }

    // ---- iteration ----------------------------------------------------------

    /// Iterate over transactions in parse order.
    pub fn iter(&self) -> impl Iterator<Item = &Transaction> {
        self.xacts.iter()
    }

    /// Iterate mutably over transactions.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = &mut Transaction> {
        self.xacts.iter_mut()
    }

    // ---- reset --------------------------------------------------------------

    /// Reset the journal to its initial (empty) state.
    pub fn clear(&mut self) {
        self.accounts = AccountArena::new();
        self.xacts.clear();
        self.auto_xacts.clear();
        self.periodic_xacts.clear();
        self.commodity_pool = CommodityPool::new();
        self.sources.clear();
        self.was_loaded = false;
        self.bucket = None;
        self.default_year = None;
        self.account_aliases.clear();
        self.prices.clear();
        self.tag_declarations.clear();
        self.payee_declarations.clear();
        self.apply_account_stack.clear();
        self.apply_tag_stack.clear();
        self.no_market_commodities.clear();
        self.defines.clear();
    }
}

impl Default for Journal {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Debug for Journal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let account_count = self.accounts.len() - 1; // exclude root
        f.debug_struct("Journal")
            .field("xacts", &self.xacts.len())
            .field("accounts", &account_count)
            .finish()
    }
}

impl fmt::Display for Journal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let account_count = self.accounts.len() - 1;
        write!(
            f,
            "Journal(xacts={}, accounts={})",
            self.xacts.len(),
            account_count
        )
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::post::Post;
    use crate::xact::Transaction;

    fn make_balanced_xact(
        journal: &mut Journal,
        payee: &str,
        acct1: &str,
        amt1: &str,
        acct2: &str,
    ) -> Transaction {
        let id1 = journal.find_account(acct1, true).unwrap();
        let id2 = journal.find_account(acct2, true).unwrap();

        let mut xact = Transaction::with_payee(payee);
        xact.add_post(Post::with_account_and_amount(
            id1,
            Amount::parse(amt1).unwrap(),
        ));
        xact.add_post(Post::with_account(id2));
        xact
    }

    #[test]
    fn journal_new() {
        let journal = Journal::new();
        assert_eq!(journal.xact_count(), 0);
        assert_eq!(journal.accounts.len(), 1); // just root
        assert!(!journal.was_loaded);
        assert!(journal.bucket.is_none());
    }

    #[test]
    fn journal_find_account() {
        let mut journal = Journal::new();
        let id = journal.find_account("Expenses:Food", true).unwrap();
        assert_eq!(journal.account_fullname(id), "Expenses:Food");

        // Should reuse existing.
        let id2 = journal.find_account("Expenses:Food", true).unwrap();
        assert_eq!(id, id2);
    }

    #[test]
    fn journal_find_account_no_create() {
        let mut journal = Journal::new();
        let result = journal.find_account("Nonexistent", false);
        assert!(result.is_none());
    }

    #[test]
    fn journal_add_xact_balanced() {
        let mut journal = Journal::new();
        let xact = make_balanced_xact(
            &mut journal,
            "Grocery Store",
            "Expenses:Food",
            "$42.50",
            "Assets:Checking",
        );
        let result = journal.add_xact(xact);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);
        assert_eq!(journal.xact_count(), 1);
    }

    #[test]
    fn journal_add_xact_unbalanced() {
        let mut journal = Journal::new();
        let id1 = journal.find_account("Expenses:Food", true).unwrap();
        let id2 = journal.find_account("Assets:Checking", true).unwrap();

        let mut xact = Transaction::with_payee("Bad");
        xact.add_post(Post::with_account_and_amount(
            id1,
            Amount::parse("$42.50").unwrap(),
        ));
        xact.add_post(Post::with_account_and_amount(
            id2,
            Amount::parse("$-10.00").unwrap(),
        ));

        let result = journal.add_xact(xact);
        assert!(result.is_err());
        assert_eq!(journal.xact_count(), 0);
    }

    #[test]
    fn journal_multiple_xacts() {
        let mut journal = Journal::new();

        let xact1 = make_balanced_xact(
            &mut journal,
            "Xact 1",
            "Expenses:Food",
            "$10.00",
            "Assets:Cash",
        );
        let xact2 = make_balanced_xact(
            &mut journal,
            "Xact 2",
            "Expenses:Rent",
            "$1000.00",
            "Assets:Checking",
        );

        journal.add_xact(xact1).unwrap();
        journal.add_xact(xact2).unwrap();
        assert_eq!(journal.xact_count(), 2);

        // Iterate
        let payees: Vec<&str> = journal.iter().map(|x| x.payee.as_str()).collect();
        assert_eq!(payees, vec!["Xact 1", "Xact 2"]);
    }

    #[test]
    fn journal_remove_xact() {
        let mut journal = Journal::new();
        let xact = make_balanced_xact(
            &mut journal,
            "ToRemove",
            "Expenses:Food",
            "$10.00",
            "Assets:Cash",
        );
        journal.add_xact(xact).unwrap();
        assert_eq!(journal.xact_count(), 1);

        let removed = journal.remove_xact(0);
        assert_eq!(removed.payee, "ToRemove");
        assert_eq!(journal.xact_count(), 0);
    }

    #[test]
    fn journal_register_commodity() {
        let mut journal = Journal::new();
        let id = journal.register_commodity("$");
        let id2 = journal.register_commodity("$");
        assert_eq!(id, id2);
    }

    #[test]
    fn journal_clear() {
        let mut journal = Journal::new();
        journal.find_account("Assets:Cash", true);
        let xact = make_balanced_xact(
            &mut journal,
            "Test",
            "Expenses:Food",
            "$10.00",
            "Assets:Cash",
        );
        journal.add_xact(xact).unwrap();
        journal.was_loaded = true;

        journal.clear();
        assert_eq!(journal.xact_count(), 0);
        assert_eq!(journal.accounts.len(), 1); // only root
        assert!(!journal.was_loaded);
    }

    #[test]
    fn journal_display() {
        let journal = Journal::new();
        let s = format!("{}", journal);
        assert!(s.contains("xacts=0"));
        assert!(s.contains("accounts=0"));
    }

    #[test]
    fn journal_debug() {
        let journal = Journal::new();
        let s = format!("{:?}", journal);
        assert!(s.contains("Journal"));
    }

    #[test]
    fn journal_with_commodity_pool() {
        let mut pool = CommodityPool::new();
        pool.find_or_create("BTC");
        let journal = Journal::with_commodity_pool(pool);
        assert!(journal.commodity_pool.contains("BTC"));
    }

    #[test]
    fn journal_bucket() {
        let mut journal = Journal::new();
        let id = journal.find_account("Assets:Checking", true).unwrap();
        journal.bucket = Some(id);
        assert_eq!(journal.bucket, Some(id));
    }
}
