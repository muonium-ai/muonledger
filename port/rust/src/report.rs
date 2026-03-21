//! Core report options for controlling how reports are filtered and displayed.
//!
//! Ported from the Python reference implementation's `report.py`.
//! The [`ReportOptions`] struct collects all user-configurable options that
//! influence report generation: date filtering, amount expressions, sorting,
//! grouping, subtotals, display controls, commodity handling, and clearing-state
//! filters.
//!
//! Two key functions operate on a populated [`ReportOptions`]:
//!
//! - [`build_filter_chain`] -- constructs the posting filter pipeline.
//! - [`apply_to_journal`] -- pre-filters a journal's transactions by date
//!   and clearing state, returning enriched postings.

use chrono::NaiveDate;

use crate::filters::{
    CalcPosts, CollapsePosts, DisplayFilter, EnrichedPost, FilterPosts,
    InvertPosts, PostHandler, RelatedPosts, SortPosts, SortKey,
    SubtotalPosts, TruncatePosts,
};
use crate::item::ItemState;
use crate::journal::Journal;
use crate::post::POST_VIRTUAL;

// ---------------------------------------------------------------------------
// ReportOptions
// ---------------------------------------------------------------------------

/// Collects all report options that control filtering and display.
///
/// Each field corresponds to a command-line option from ledger.
/// Options left at their default (`None` or `false`) are inactive.
#[derive(Debug, Clone)]
pub struct ReportOptions {
    // -- Date filtering -------------------------------------------------------
    /// Restrict to transactions on or after this date.
    pub begin: Option<NaiveDate>,
    /// Restrict to transactions before this date (exclusive).
    pub end: Option<NaiveDate>,
    /// Period expression string (e.g. "monthly").
    pub period: Option<String>,
    /// Exclude future-dated transactions.
    pub current: bool,

    // -- Amount display -------------------------------------------------------
    /// Expression string controlling the displayed amount.
    pub amount_expr: Option<String>,
    /// Expression string controlling the displayed total.
    pub total_expr: Option<String>,
    /// Expression controlling which posts to display.
    pub display_expr: Option<String>,

    // -- Sorting --------------------------------------------------------------
    /// Sort key expression string.
    pub sort_expr: Option<String>,
    /// Sort transactions rather than postings.
    pub sort_xacts: bool,

    // -- Grouping intervals ---------------------------------------------------
    /// Group by day.
    pub daily: bool,
    /// Group by week.
    pub weekly: bool,
    /// Group by month.
    pub monthly: bool,
    /// Group by quarter.
    pub quarterly: bool,
    /// Group by year.
    pub yearly: bool,
    /// Collapse postings per transaction into one.
    pub collapse: bool,

    // -- Subtotal -------------------------------------------------------------
    /// Produce subtotals by account.
    pub subtotal: bool,
    /// Show related (other-side) postings.
    pub related: bool,

    // -- Display --------------------------------------------------------------
    /// Flat account display (no tree indentation).
    pub flat: bool,
    /// Suppress the total line.
    pub no_total: bool,
    /// Maximum account depth to display (0 = unlimited).
    pub depth: usize,
    /// Predicate controlling which posts enter the pipeline.
    pub limit_expr: Option<String>,

    // -- Output ---------------------------------------------------------------
    /// Custom format string.
    pub format_string: Option<String>,
    /// Show only the first N postings.
    pub head: Option<usize>,
    /// Show only the last N postings.
    pub tail: Option<usize>,

    // -- Width ----------------------------------------------------------------
    /// Account column width.
    pub account_width: usize,
    /// Amount column width.
    pub amount_width: usize,
    /// Total columns available.
    pub columns: usize,
    /// Use wide (132-column) layout.
    pub wide: bool,

    // -- Commodity -------------------------------------------------------------
    /// Convert to market value.
    pub market: bool,
    /// Target commodity for conversion.
    pub exchange: Option<String>,

    // -- Clearing state -------------------------------------------------------
    /// Show only cleared items.
    pub cleared: bool,
    /// Show only uncleared items.
    pub uncleared: bool,
    /// Show only pending items.
    pub pending: bool,
    /// Show only real (non-virtual) postings.
    pub real: bool,

    // -- Display modes --------------------------------------------------------
    /// Negate all amounts.
    pub invert: bool,
    /// Compute running average.
    pub average: bool,
    /// Show percentage of total.
    pub percent: bool,
    /// Show accounts with zero balances.
    pub empty: bool,
    /// Group by payee.
    pub by_payee: bool,
    /// Show posting count.
    pub count: bool,

    // -- Filtering ------------------------------------------------------------
    /// Payee substring filter (case-insensitive).
    pub payee_filter: Option<String>,
    /// Account substring filter (case-insensitive).
    pub account_filter: Option<String>,
}

impl Default for ReportOptions {
    fn default() -> Self {
        Self {
            begin: None,
            end: None,
            period: None,
            current: false,

            amount_expr: None,
            total_expr: None,
            display_expr: None,

            sort_expr: None,
            sort_xacts: false,

            daily: false,
            weekly: false,
            monthly: false,
            quarterly: false,
            yearly: false,
            collapse: false,

            subtotal: false,
            related: false,

            flat: false,
            no_total: false,
            depth: 0,
            limit_expr: None,

            format_string: None,
            head: None,
            tail: None,

            account_width: 0,
            amount_width: 0,
            columns: 80,
            wide: false,

            market: false,
            exchange: None,

            cleared: false,
            uncleared: false,
            pending: false,
            real: false,

            invert: false,
            average: false,
            percent: false,
            empty: false,
            by_payee: false,
            count: false,

            payee_filter: None,
            account_filter: None,
        }
    }
}

impl ReportOptions {
    /// Create new default report options.
    pub fn new() -> Self {
        Self::default()
    }

    /// Return the clearing state filter, if any single state is requested.
    pub fn clearing_state_filter(&self) -> Option<ItemState> {
        if self.cleared {
            Some(ItemState::Cleared)
        } else if self.pending {
            Some(ItemState::Pending)
        } else if self.uncleared {
            Some(ItemState::Uncleared)
        } else {
            None
        }
    }

    /// Return the effective begin date.
    pub fn effective_begin(&self) -> Option<NaiveDate> {
        self.begin
    }

    /// Return the effective end date, considering `current`.
    pub fn effective_end(&self) -> Option<NaiveDate> {
        if self.current {
            let today = chrono::Local::now().date_naive();
            let tomorrow = today + chrono::Duration::days(1);
            match self.end {
                Some(end) if end < tomorrow => Some(end),
                _ => Some(tomorrow),
            }
        } else {
            self.end
        }
    }

    /// Return the interval duration in days implied by the grouping flags.
    /// Returns `None` if no grouping flag is set.
    pub fn interval_days(&self) -> Option<i64> {
        if self.daily {
            Some(1)
        } else if self.weekly {
            Some(7)
        } else if self.monthly {
            Some(30)
        } else if self.quarterly {
            Some(91)
        } else if self.yearly {
            Some(365)
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// build_filter_chain
// ---------------------------------------------------------------------------

/// Construct a filter pipeline from options, terminating at the given handler.
///
/// The chain is built inside-out: `handler` is the innermost (terminal)
/// handler and filters wrap around it. The returned handler is the
/// outermost -- callers should feed postings into it.
///
/// Assembly order mirrors ledger's `report_t::chain_post_handlers`:
///
/// 1. Display filter (`--display`)
/// 2. Truncation (`--head`)
/// 3. Sorting (`--sort`)
/// 4. Running-total calculation
/// 5. Invert (negate amounts)
/// 6. Interval grouping (`--daily`, `--monthly`, etc.)
/// 7. Subtotal (`--subtotal`)
/// 8. Collapse (`--collapse`)
/// 9. Related postings (`--related`)
/// 10. Limit filter (`--limit`)
pub fn build_filter_chain(
    options: &ReportOptions,
    handler: Box<dyn PostHandler>,
) -> Box<dyn PostHandler> {
    let mut chain: Box<dyn PostHandler> = handler;

    // -- Display filter -------------------------------------------------------
    if let Some(ref expr) = options.display_expr {
        let pred = make_predicate(expr);
        chain = Box::new(DisplayFilter::new(chain, pred));
    }

    // -- Truncation -----------------------------------------------------------
    if let Some(head) = options.head {
        if head > 0 {
            chain = Box::new(TruncatePosts::new(chain, head));
        }
    }

    // -- Sorting --------------------------------------------------------------
    if let Some(ref expr) = options.sort_expr {
        let key_fn = make_sort_key(expr);
        chain = Box::new(SortPosts::new(chain, key_fn, false));
    }

    // -- Running-total calculation --------------------------------------------
    chain = Box::new(CalcPosts::new(chain, None, true));

    // -- Invert (negate amounts) ----------------------------------------------
    if options.invert {
        chain = Box::new(InvertPosts::new(chain));
    }

    // -- Interval grouping ----------------------------------------------------
    if let Some(days) = options.interval_days() {
        chain = Box::new(crate::filters::IntervalPosts::new(
            chain,
            days,
            options.begin,
            options.empty,
        ));
    }

    // -- Subtotal -------------------------------------------------------------
    if options.subtotal || options.by_payee {
        chain = Box::new(SubtotalPosts::new(chain));
    }

    // -- Collapse -------------------------------------------------------------
    if options.collapse {
        chain = Box::new(CollapsePosts::new(chain));
    }

    // -- Related postings -----------------------------------------------------
    if options.related {
        chain = Box::new(RelatedPosts::new(chain, false));
    }

    // -- Limit filter ---------------------------------------------------------
    if let Some(ref expr) = options.limit_expr {
        let pred = make_predicate(expr);
        chain = Box::new(FilterPosts::new(chain, pred));
    }

    chain
}

// ---------------------------------------------------------------------------
// apply_to_journal
// ---------------------------------------------------------------------------

/// Filter a journal's transactions and return qualifying enriched postings.
///
/// Applies the following filters in order:
/// 1. Date range (`begin` / `end` / `current`)
/// 2. Clearing state (`cleared` / `uncleared` / `pending`)
/// 3. Real-posting filter (`real`)
/// 4. Account depth restriction (`depth`)
/// 5. Payee filter (`payee_filter`)
/// 6. Account filter (`account_filter`)
pub fn apply_to_journal(
    options: &ReportOptions,
    journal: &Journal,
) -> Vec<EnrichedPost> {
    let begin = options.effective_begin();
    let end = options.effective_end();
    let state_filter = options.clearing_state_filter();

    let payee_filter_lower = options.payee_filter.as_ref().map(|s| s.to_lowercase());
    let account_filter_lower = options.account_filter.as_ref().map(|s| s.to_lowercase());

    let mut posts = Vec::new();

    for (xi, xact) in journal.xacts.iter().enumerate() {
        let xact_date = match xact.item.date {
            Some(d) => d,
            None => continue,
        };

        // Date filtering
        if let Some(b) = begin {
            if xact_date < b {
                continue;
            }
        }
        if let Some(e) = end {
            if xact_date >= e {
                continue;
            }
        }

        // Payee filter (transaction-level)
        if let Some(ref pat) = payee_filter_lower {
            if !xact.payee.to_lowercase().contains(pat.as_str()) {
                continue;
            }
        }

        for (pi, post) in xact.posts.iter().enumerate() {
            // Per-posting clearing state
            if let Some(required_state) = state_filter {
                let effective_state = if post.item.state != ItemState::Uncleared {
                    post.item.state
                } else {
                    xact.item.state
                };
                if effective_state != required_state {
                    continue;
                }
            }

            // Real-posting filter
            if options.real && post.item.has_flags(POST_VIRTUAL) {
                continue;
            }

            // Depth filter
            if options.depth > 0 {
                if let Some(acct_id) = post.account_id {
                    let fullname = journal.account_fullname(acct_id);
                    let acct_depth = fullname.matches(':').count() + 1;
                    if acct_depth > options.depth {
                        continue;
                    }
                }
            }

            // Account filter
            if let Some(ref pat) = account_filter_lower {
                if let Some(acct_id) = post.account_id {
                    let fullname = journal.account_fullname(acct_id);
                    if !fullname.to_lowercase().contains(pat.as_str()) {
                        continue;
                    }
                } else {
                    continue;
                }
            }

            posts.push(EnrichedPost::from_journal(journal, xi, pi));
        }
    }

    posts
}

// ---------------------------------------------------------------------------
// Predicate and sort-key builders
// ---------------------------------------------------------------------------

/// Build a predicate closure from a simple expression string.
fn make_predicate(expr: &str) -> Box<dyn Fn(&EnrichedPost) -> bool> {
    let expr = expr.trim().to_string();

    // "true" -- always pass
    if expr.eq_ignore_ascii_case("true") {
        return Box::new(|_| true);
    }

    // "false" -- never pass
    if expr.eq_ignore_ascii_case("false") {
        return Box::new(|_| false);
    }

    // Clearing state predicates
    if expr == "cleared" {
        return Box::new(|p| p.state == ItemState::Cleared);
    }
    if expr == "pending" {
        return Box::new(|p| p.state == ItemState::Pending);
    }
    if expr == "uncleared" {
        return Box::new(|p| p.state == ItemState::Uncleared);
    }

    // "real" predicate
    if expr == "real" {
        return Box::new(|p| (p.flags & POST_VIRTUAL) == 0);
    }

    // Default: treat as account name substring match (case-insensitive)
    let lower_expr = expr.to_lowercase();
    Box::new(move |_p| {
        // Without journal access, we can't resolve account names here.
        // For now, always pass. Full implementation needs account resolution.
        let _ = &lower_expr;
        true
    })
}

/// Build a sort-key function from a simple expression string.
fn make_sort_key(expr: &str) -> Box<dyn Fn(&EnrichedPost) -> SortKey> {
    let expr = expr.trim().to_lowercase();

    if expr == "date" {
        return Box::new(|p| SortKey::Date(p.date));
    }
    if expr == "payee" {
        return Box::new(|p| SortKey::String(p.payee.clone()));
    }
    if expr == "account" {
        return Box::new(|p| {
            SortKey::Integer(p.account_id.map(|id| id.index() as i64).unwrap_or(0))
        });
    }

    // Default: sort by date
    Box::new(|p| SortKey::Date(p.date))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::filters::CollectPosts;
    use crate::item::ItemState;
    use crate::journal::Journal;
    use crate::post::Post;
    use crate::xact::Transaction;

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }

    fn make_test_journal() -> Journal {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();
        let rent = journal.find_account("Expenses:Rent", true).unwrap();
        let checking = journal.find_account("Assets:Checking", true).unwrap();

        // Transaction 1: Jan 15
        let mut xact1 = Transaction::with_payee("Grocery Store");
        xact1.item.date = Some(d(2024, 1, 15));
        xact1.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$50.00").unwrap(),
        ));
        xact1.add_post(Post::with_account(cash));
        xact1.finalize().unwrap();
        journal.xacts.push(xact1);

        // Transaction 2: Feb 1
        let mut xact2 = Transaction::with_payee("Landlord");
        xact2.item.date = Some(d(2024, 2, 1));
        xact2.item.state = ItemState::Cleared;
        xact2.add_post(Post::with_account_and_amount(
            rent,
            Amount::parse("$1000.00").unwrap(),
        ));
        xact2.add_post(Post::with_account(checking));
        xact2.finalize().unwrap();
        journal.xacts.push(xact2);

        // Transaction 3: Mar 10
        let mut xact3 = Transaction::with_payee("Restaurant");
        xact3.item.date = Some(d(2024, 3, 10));
        xact3.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$30.00").unwrap(),
        ));
        xact3.add_post(Post::with_account(cash));
        xact3.finalize().unwrap();
        journal.xacts.push(xact3);

        journal
    }

    // ---- ReportOptions defaults ---------------------------------------------

    #[test]
    fn report_options_defaults() {
        let opts = ReportOptions::default();
        assert!(opts.begin.is_none());
        assert!(opts.end.is_none());
        assert!(!opts.current);
        assert!(!opts.cleared);
        assert!(!opts.invert);
        assert!(!opts.subtotal);
        assert!(!opts.collapse);
        assert_eq!(opts.depth, 0);
        assert!(opts.head.is_none());
        assert!(opts.tail.is_none());
        assert_eq!(opts.columns, 80);
    }

    #[test]
    fn report_options_clearing_state_filter() {
        let mut opts = ReportOptions::default();
        assert!(opts.clearing_state_filter().is_none());

        opts.cleared = true;
        assert_eq!(opts.clearing_state_filter(), Some(ItemState::Cleared));

        opts.cleared = false;
        opts.pending = true;
        assert_eq!(opts.clearing_state_filter(), Some(ItemState::Pending));

        opts.pending = false;
        opts.uncleared = true;
        assert_eq!(opts.clearing_state_filter(), Some(ItemState::Uncleared));
    }

    #[test]
    fn report_options_interval_days() {
        let mut opts = ReportOptions::default();
        assert!(opts.interval_days().is_none());

        opts.daily = true;
        assert_eq!(opts.interval_days(), Some(1));

        opts.daily = false;
        opts.weekly = true;
        assert_eq!(opts.interval_days(), Some(7));

        opts.weekly = false;
        opts.monthly = true;
        assert_eq!(opts.interval_days(), Some(30));

        opts.monthly = false;
        opts.quarterly = true;
        assert_eq!(opts.interval_days(), Some(91));

        opts.quarterly = false;
        opts.yearly = true;
        assert_eq!(opts.interval_days(), Some(365));
    }

    // ---- apply_to_journal ---------------------------------------------------

    #[test]
    fn apply_to_journal_no_filters() {
        let journal = make_test_journal();
        let opts = ReportOptions::default();
        let posts = apply_to_journal(&opts, &journal);
        // 3 transactions x 2 postings = 6
        assert_eq!(posts.len(), 6);
    }

    #[test]
    fn apply_to_journal_date_begin() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.begin = Some(d(2024, 2, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Xact2 (Feb 1) and Xact3 (Mar 10) = 4 postings
        assert_eq!(posts.len(), 4);
    }

    #[test]
    fn apply_to_journal_date_end() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.end = Some(d(2024, 2, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Only Xact1 (Jan 15) = 2 postings
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn apply_to_journal_date_range() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.begin = Some(d(2024, 1, 20));
        opts.end = Some(d(2024, 3, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Only Xact2 (Feb 1) = 2 postings
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn apply_to_journal_cleared_filter() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.cleared = true;
        let posts = apply_to_journal(&opts, &journal);
        // Only Xact2 is cleared = 2 postings
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Landlord");
    }

    #[test]
    fn apply_to_journal_payee_filter() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.payee_filter = Some("grocery".to_string());
        let posts = apply_to_journal(&opts, &journal);
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Grocery Store");
    }

    #[test]
    fn apply_to_journal_account_filter() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.account_filter = Some("food".to_string());
        let posts = apply_to_journal(&opts, &journal);
        // Expenses:Food appears in Xact1 and Xact3
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn apply_to_journal_depth_filter() {
        let journal = make_test_journal();
        let mut opts = ReportOptions::default();
        opts.depth = 1;
        let posts = apply_to_journal(&opts, &journal);
        // All accounts are depth 2 (Expenses:Food, Assets:Cash, etc.)
        // Depth 1 means only top-level accounts pass
        assert_eq!(posts.len(), 0);
    }

    // ---- build_filter_chain -------------------------------------------------

    #[test]
    fn build_filter_chain_default_options() {
        let opts = ReportOptions::default();
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        // Feed some posts through
        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // Default chain just adds CalcPosts, so all 6 posts should pass
        assert_eq!(chain.collected().len(), 6);
    }

    #[test]
    fn build_filter_chain_with_head() {
        let mut opts = ReportOptions::default();
        opts.head = Some(3);
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), 3);
    }

    #[test]
    fn build_filter_chain_with_invert() {
        let mut opts = ReportOptions::default();
        opts.invert = true;
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        let collected = chain.collected();
        assert_eq!(collected.len(), 6);
        // First post was $50.00, should now be $-50.00
        let first_amt = collected[0].amount.as_ref().unwrap();
        assert!(first_amt.is_negative());
    }

    #[test]
    fn build_filter_chain_with_collapse() {
        let mut opts = ReportOptions::default();
        opts.collapse = true;
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // 3 transactions collapsed to 3 postings (each xact -> 1 collapsed post)
        let collected = chain.collected();
        assert_eq!(collected.len(), 3);
    }

    #[test]
    fn build_filter_chain_with_subtotal() {
        let mut opts = ReportOptions::default();
        opts.subtotal = true;
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // Subtotal groups by account. We have 4 distinct accounts:
        // Expenses:Food, Assets:Cash, Expenses:Rent, Assets:Checking
        let collected = chain.collected();
        assert_eq!(collected.len(), 4);
    }

    #[test]
    fn build_filter_chain_with_sort() {
        let mut opts = ReportOptions::default();
        opts.sort_expr = Some("payee".to_string());
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        let collected = chain.collected();
        assert_eq!(collected.len(), 6);
        // Should be sorted by payee: Grocery Store, Grocery Store, Landlord, Landlord, Restaurant, Restaurant
        assert_eq!(collected[0].payee, "Grocery Store");
        assert_eq!(collected[2].payee, "Landlord");
        assert_eq!(collected[4].payee, "Restaurant");
    }

    #[test]
    fn build_filter_chain_display_filter() {
        let mut opts = ReportOptions::default();
        opts.display_expr = Some("true".to_string());
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), 6);
    }

    #[test]
    fn build_filter_chain_display_filter_false() {
        let mut opts = ReportOptions::default();
        opts.display_expr = Some("false".to_string());
        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let journal = make_test_journal();
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), 0);
    }

    // ---- End-to-end: apply_to_journal + build_filter_chain ------------------

    #[test]
    fn end_to_end_register_pipeline() {
        let journal = make_test_journal();
        let opts = ReportOptions::default();

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        let collected = chain.collected();
        assert_eq!(collected.len(), 6);

        // Check running totals are present
        for post in collected {
            assert!(post.xdata.total.is_some());
            assert!(post.xdata.visited_value.is_some());
        }
    }
}
