//! Chain-of-responsibility filter pipeline for processing postings.
//!
//! Ported from the Python reference implementation's `filters.py`.
//! Each filter is a handler that receives postings one at a time,
//! optionally transforms or accumulates them, and forwards results
//! to a downstream handler.
//!
//! The pipeline is built by linking handlers: the outermost handler
//! receives postings first and passes them inward toward the terminal
//! handler.
//!
//! # Filter inventory
//!
//! - **CollectPosts** -- accumulates postings into a list without forwarding.
//! - **FilterPosts** -- forwards only postings matching a predicate.
//! - **SortPosts** -- accumulates all postings, sorts on flush, then forwards.
//! - **TruncatePosts** -- limits output to the first N postings.
//! - **CalcPosts** -- computes running totals for each posting.
//! - **CollapsePosts** -- collapses multiple postings per transaction into one.
//! - **SubtotalPosts** -- accumulates subtotals by account.
//! - **IntervalPosts** -- groups postings by date intervals and subtotals each.
//! - **InvertPosts** -- negates the amount of each posting.
//! - **RelatedPosts** -- replaces each posting with the other-side postings.
//! - **DisplayFilter** -- filters which posts to display based on a predicate.

use std::collections::BTreeMap;

use chrono::NaiveDate;

use crate::account::AccountId;
use crate::amount::Amount;
use crate::item::{ItemState, ITEM_GENERATED};
use crate::journal::Journal;

// ---------------------------------------------------------------------------
// PostRef — a reference to a posting within a journal
// ---------------------------------------------------------------------------

/// A reference to a posting within a journal, identified by transaction
/// index and posting index within that transaction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PostRef {
    /// Index into `journal.xacts`.
    pub xact_idx: usize,
    /// Index into `journal.xacts[xact_idx].posts`.
    pub post_idx: usize,
}

impl PostRef {
    pub fn new(xact_idx: usize, post_idx: usize) -> Self {
        Self { xact_idx, post_idx }
    }
}

// ---------------------------------------------------------------------------
// Extended data for postings (xdata)
// ---------------------------------------------------------------------------

/// Extended posting data computed during filter pipeline processing.
#[derive(Debug, Clone, Default)]
pub struct PostXData {
    /// The computed amount value for this posting.
    pub visited_value: Option<Amount>,
    /// Running total up to and including this posting.
    pub total: Option<Amount>,
    /// Number of postings processed so far (ordinal position).
    pub count: usize,
    /// Number of component postings (for collapsed postings).
    pub component_count: usize,
}

// ---------------------------------------------------------------------------
// Enriched posting — carries all data needed by the pipeline
// ---------------------------------------------------------------------------

/// An enriched posting that carries its own data rather than referencing
/// a journal. This allows synthetic postings (from collapse, subtotal,
/// interval) to flow through the pipeline alongside real postings.
#[derive(Debug, Clone)]
pub struct EnrichedPost {
    /// Account id for this posting.
    pub account_id: Option<AccountId>,
    /// The posting amount.
    pub amount: Option<Amount>,
    /// The date of this posting (from the transaction or overridden).
    pub date: Option<NaiveDate>,
    /// The payee (from the transaction).
    pub payee: String,
    /// The clearing state.
    pub state: ItemState,
    /// Item flags.
    pub flags: u32,
    /// Optional note.
    pub note: Option<String>,
    /// Cost amount.
    pub cost: Option<Amount>,
    /// Transaction code.
    pub code: Option<String>,
    /// Back-reference to the original transaction (if any).
    pub xact_idx: Option<usize>,
    /// Back-reference to the original posting index (if any).
    pub post_idx: Option<usize>,
    /// Extended data computed by filter stages.
    pub xdata: PostXData,
    /// Indices of related postings in the same transaction.
    pub related_post_indices: Vec<usize>,
}

impl EnrichedPost {
    /// Create an enriched post from a journal posting reference.
    pub fn from_journal(journal: &Journal, xact_idx: usize, post_idx: usize) -> Self {
        let xact = &journal.xacts[xact_idx];
        let post = &xact.posts[post_idx];
        Self {
            account_id: post.account_id,
            amount: post.amount.clone(),
            date: xact.item.date,
            payee: xact.payee.clone(),
            state: xact.item.state,
            flags: post.item.flags,
            note: post.item.note.clone(),
            cost: post.cost.clone(),
            code: xact.code.clone(),
            xact_idx: Some(xact_idx),
            post_idx: Some(post_idx),
            xdata: PostXData::default(),
            related_post_indices: (0..xact.posts.len())
                .filter(|&i| i != post_idx)
                .collect(),
        }
    }

    /// Create a synthetic enriched post (e.g. for subtotal/collapse).
    pub fn synthetic(
        account_id: Option<AccountId>,
        amount: Amount,
        date: Option<NaiveDate>,
        payee: &str,
    ) -> Self {
        Self {
            account_id,
            amount: Some(amount),
            date,
            payee: payee.to_string(),
            state: ItemState::Uncleared,
            flags: ITEM_GENERATED,
            note: None,
            cost: None,
            code: None,
            xact_idx: None,
            post_idx: None,
            xdata: PostXData::default(),
            related_post_indices: Vec::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// PostHandler trait
// ---------------------------------------------------------------------------

/// Trait for all handlers in the posting filter pipeline.
///
/// Implements the Chain of Responsibility pattern. Each handler
/// receives postings via `handle()`, optionally transforms them,
/// and forwards results to a downstream handler.
pub trait PostHandler {
    /// Process a single enriched posting.
    fn handle(&mut self, post: EnrichedPost);

    /// Called after all postings have been submitted, giving
    /// accumulating filters a chance to emit their results.
    fn flush(&mut self);

    /// Reset mutable state for reuse.
    fn clear(&mut self);

    /// Retrieve the collected posts (only meaningful for CollectPosts).
    fn collected(&self) -> &[EnrichedPost] {
        &[]
    }
}

// ---------------------------------------------------------------------------
// CollectPosts
// ---------------------------------------------------------------------------

/// Terminal handler that accumulates postings into a Vec.
pub struct CollectPosts {
    pub posts: Vec<EnrichedPost>,
}

impl CollectPosts {
    pub fn new() -> Self {
        Self { posts: Vec::new() }
    }
}

impl PostHandler for CollectPosts {
    fn handle(&mut self, post: EnrichedPost) {
        self.posts.push(post);
    }

    fn flush(&mut self) {
        // No downstream handler -- nothing to do.
    }

    fn clear(&mut self) {
        self.posts.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        &self.posts
    }
}

// ---------------------------------------------------------------------------
// FilterPosts
// ---------------------------------------------------------------------------

/// Forwards only postings that match a predicate.
pub struct FilterPosts {
    handler: Box<dyn PostHandler>,
    predicate: Box<dyn Fn(&EnrichedPost) -> bool>,
}

impl FilterPosts {
    pub fn new(
        handler: Box<dyn PostHandler>,
        predicate: Box<dyn Fn(&EnrichedPost) -> bool>,
    ) -> Self {
        Self { handler, predicate }
    }
}

impl PostHandler for FilterPosts {
    fn handle(&mut self, post: EnrichedPost) {
        if (self.predicate)(&post) {
            self.handler.handle(post);
        }
    }

    fn flush(&mut self) {
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// DisplayFilter
// ---------------------------------------------------------------------------

/// Filters which posts to display based on a predicate.
///
/// Structurally identical to FilterPosts but named distinctly to match
/// the C++ pipeline where display filtering is a separate stage.
pub struct DisplayFilter {
    handler: Box<dyn PostHandler>,
    predicate: Box<dyn Fn(&EnrichedPost) -> bool>,
}

impl DisplayFilter {
    pub fn new(
        handler: Box<dyn PostHandler>,
        predicate: Box<dyn Fn(&EnrichedPost) -> bool>,
    ) -> Self {
        Self { handler, predicate }
    }
}

impl PostHandler for DisplayFilter {
    fn handle(&mut self, post: EnrichedPost) {
        if (self.predicate)(&post) {
            self.handler.handle(post);
        }
    }

    fn flush(&mut self) {
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// SortPosts
// ---------------------------------------------------------------------------

/// Accumulates all postings, sorts on flush, then forwards in order.
pub struct SortPosts {
    handler: Box<dyn PostHandler>,
    sort_key: Box<dyn Fn(&EnrichedPost) -> SortKey>,
    reverse: bool,
    posts: Vec<EnrichedPost>,
}

/// Sort key for ordering postings.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum SortKey {
    Date(Option<NaiveDate>),
    String(String),
    Integer(i64),
}

impl SortPosts {
    pub fn new(
        handler: Box<dyn PostHandler>,
        sort_key: Box<dyn Fn(&EnrichedPost) -> SortKey>,
        reverse: bool,
    ) -> Self {
        Self {
            handler,
            sort_key,
            reverse,
            posts: Vec::new(),
        }
    }
}

impl PostHandler for SortPosts {
    fn handle(&mut self, post: EnrichedPost) {
        self.posts.push(post);
    }

    fn flush(&mut self) {
        let key_fn = &self.sort_key;
        self.posts.sort_by(|a, b| {
            let ka = key_fn(a);
            let kb = key_fn(b);
            ka.cmp(&kb)
        });
        if self.reverse {
            self.posts.reverse();
        }
        let posts: Vec<EnrichedPost> = self.posts.drain(..).collect();
        for post in posts {
            self.handler.handle(post);
        }
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.posts.clear();
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// TruncatePosts
// ---------------------------------------------------------------------------

/// Limits output to the first N postings.
pub struct TruncatePosts {
    handler: Box<dyn PostHandler>,
    head_count: usize,
    count: usize,
}

impl TruncatePosts {
    pub fn new(handler: Box<dyn PostHandler>, head_count: usize) -> Self {
        Self {
            handler,
            head_count,
            count: 0,
        }
    }
}

impl PostHandler for TruncatePosts {
    fn handle(&mut self, post: EnrichedPost) {
        if self.count < self.head_count {
            self.handler.handle(post);
            self.count += 1;
        }
    }

    fn flush(&mut self) {
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.count = 0;
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// CalcPosts
// ---------------------------------------------------------------------------

/// Computes running totals for the register report.
///
/// For each posting, maintains a running total across all postings.
/// The results are stored in the enriched post's xdata.
pub struct CalcPosts {
    handler: Box<dyn PostHandler>,
    amount_fn: Box<dyn Fn(&EnrichedPost) -> Option<Amount>>,
    calc_running_total: bool,
    running_total: Option<Amount>,
    count: usize,
}

impl CalcPosts {
    pub fn new(
        handler: Box<dyn PostHandler>,
        amount_fn: Option<Box<dyn Fn(&EnrichedPost) -> Option<Amount>>>,
        calc_running_total: bool,
    ) -> Self {
        let amount_fn = amount_fn.unwrap_or_else(|| {
            Box::new(|post: &EnrichedPost| post.amount.clone())
        });
        Self {
            handler,
            amount_fn,
            calc_running_total,
            running_total: None,
            count: 0,
        }
    }
}

impl PostHandler for CalcPosts {
    fn handle(&mut self, mut post: EnrichedPost) {
        self.count += 1;

        let amount_value = (self.amount_fn)(&post);
        post.xdata.visited_value = amount_value.clone();
        post.xdata.count = self.count;

        if self.calc_running_total {
            if let Some(amt) = &amount_value {
                match &self.running_total {
                    None => {
                        self.running_total = Some(amt.clone());
                    }
                    Some(existing) => {
                        // Try to add; if commodities differ, just keep latest
                        if existing.commodity() == amt.commodity() {
                            self.running_total = Some(existing.clone() + amt.clone());
                        } else {
                            self.running_total = Some(amt.clone());
                        }
                    }
                }
            }
            post.xdata.total = self.running_total.clone();
        }

        self.handler.handle(post);
    }

    fn flush(&mut self) {
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.running_total = None;
        self.count = 0;
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// CollapsePosts
// ---------------------------------------------------------------------------

/// Collapses multiple postings per transaction into one.
///
/// When postings from the same transaction are received, they are
/// accumulated. When a new transaction is encountered (or on flush),
/// a single synthetic posting representing the net amount is emitted.
pub struct CollapsePosts {
    handler: Box<dyn PostHandler>,
    last_xact_idx: Option<usize>,
    subtotal: Option<Amount>,
    count: usize,
    last_post: Option<EnrichedPost>,
}

impl CollapsePosts {
    pub fn new(handler: Box<dyn PostHandler>) -> Self {
        Self {
            handler,
            last_xact_idx: None,
            subtotal: None,
            count: 0,
            last_post: None,
        }
    }

    fn report_subtotal(&mut self) {
        if self.count == 0 {
            return;
        }

        if self.count == 1 {
            // Single posting: pass through directly.
            if let Some(post) = self.last_post.take() {
                self.handler.handle(post);
            }
        } else {
            // Multiple postings: emit a synthetic collapsed posting.
            if let Some(ref last) = self.last_post {
                let amt = match &self.subtotal {
                    Some(a) => a.clone(),
                    None => Amount::from_int(0),
                };
                let mut collapsed = EnrichedPost::synthetic(
                    last.account_id,
                    amt,
                    last.date,
                    &last.payee,
                );
                collapsed.xdata.component_count = self.count;
                self.handler.handle(collapsed);
            }
        }

        self.subtotal = None;
        self.count = 0;
        self.last_post = None;
    }
}

impl PostHandler for CollapsePosts {
    fn handle(&mut self, post: EnrichedPost) {
        // If different transaction, emit previous subtotal.
        if let Some(last_idx) = self.last_xact_idx {
            if post.xact_idx != Some(last_idx) {
                self.report_subtotal();
            }
        }

        // Accumulate amount.
        if let Some(amt) = &post.amount {
            if !amt.is_null() {
                match &self.subtotal {
                    None => {
                        self.subtotal = Some(amt.clone());
                    }
                    Some(existing) => {
                        if existing.commodity() == amt.commodity() {
                            self.subtotal = Some(existing.clone() + amt.clone());
                        } else {
                            self.subtotal = Some(amt.clone());
                        }
                    }
                }
            }
        }

        self.count += 1;
        self.last_xact_idx = post.xact_idx;
        self.last_post = Some(post);
    }

    fn flush(&mut self) {
        self.report_subtotal();
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.last_xact_idx = None;
        self.subtotal = None;
        self.count = 0;
        self.last_post = None;
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// SubtotalPosts
// ---------------------------------------------------------------------------

/// Accumulates subtotals by account for the balance report.
///
/// All incoming postings are grouped by their account id.
/// On flush, a single synthetic posting per account is emitted
/// with the accumulated total.
pub struct SubtotalPosts {
    handler: Box<dyn PostHandler>,
    /// Map from account id index -> (account_id, accumulated amount, date range).
    values: BTreeMap<usize, (AccountId, Amount, Option<NaiveDate>)>,
}

impl SubtotalPosts {
    pub fn new(handler: Box<dyn PostHandler>) -> Self {
        Self {
            handler,
            values: BTreeMap::new(),
        }
    }

    fn report_subtotal(&mut self) {
        if self.values.is_empty() {
            return;
        }

        let keys: Vec<usize> = self.values.keys().cloned().collect();
        for key in keys {
            let (acct_id, amount, date) = self.values.remove(&key).unwrap();
            let post = EnrichedPost::synthetic(
                Some(acct_id),
                amount,
                date,
                "- Subtotal",
            );
            self.handler.handle(post);
        }
    }
}

impl PostHandler for SubtotalPosts {
    fn handle(&mut self, post: EnrichedPost) {
        let acct_id = match post.account_id {
            Some(id) => id,
            None => return,
        };
        let key = acct_id.index();

        if let Some(amt) = &post.amount {
            if !amt.is_null() {
                let entry = self.values.entry(key);
                match entry {
                    std::collections::btree_map::Entry::Occupied(mut e) => {
                        let (_, ref mut existing_amt, _) = e.get_mut();
                        if existing_amt.commodity() == amt.commodity() {
                            *existing_amt = existing_amt.clone() + amt.clone();
                        }
                    }
                    std::collections::btree_map::Entry::Vacant(e) => {
                        e.insert((acct_id, amt.clone(), post.date));
                    }
                }
            }
        }
    }

    fn flush(&mut self) {
        self.report_subtotal();
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.values.clear();
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// IntervalPosts
// ---------------------------------------------------------------------------

/// Groups postings by date intervals and subtotals each period.
///
/// Used for periodic reports (e.g. monthly, weekly). Postings are
/// accumulated, sorted by date, then walked through intervals --
/// each period is subtotaled and emitted as a synthetic posting
/// per account.
pub struct IntervalPosts {
    handler: Box<dyn PostHandler>,
    /// Duration in days for each period.
    duration_days: i64,
    /// Optional start date for the first period.
    start: Option<NaiveDate>,
    /// Whether to generate empty-period postings.
    generate_empty: bool,
    /// All accumulated posts.
    all_posts: Vec<EnrichedPost>,
}

impl IntervalPosts {
    pub fn new(
        handler: Box<dyn PostHandler>,
        duration_days: i64,
        start: Option<NaiveDate>,
        generate_empty: bool,
    ) -> Self {
        Self {
            handler,
            duration_days,
            start,
            generate_empty,
            all_posts: Vec::new(),
        }
    }
}

impl PostHandler for IntervalPosts {
    fn handle(&mut self, post: EnrichedPost) {
        self.all_posts.push(post);
    }

    fn flush(&mut self) {
        if self.all_posts.is_empty() {
            self.handler.flush();
            return;
        }

        // Sort by date
        self.all_posts.sort_by_key(|p| p.date);

        let period_start_initial = match self.start {
            Some(d) => d,
            None => match self.all_posts[0].date {
                Some(d) => d,
                None => NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            },
        };

        let duration = chrono::Duration::days(self.duration_days);
        let mut period_start = period_start_initial;
        let mut period_end = period_start + duration;

        let mut idx = 0;
        let n = self.all_posts.len();

        while idx < n || self.generate_empty {
            // Collect postings in this period
            let mut period_values: BTreeMap<usize, (AccountId, Amount)> = BTreeMap::new();
            let mut saw_posts = false;

            while idx < n {
                let post_date = self.all_posts[idx].date.unwrap_or(
                    NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
                );
                if post_date >= period_end {
                    break;
                }

                if let Some(acct_id) = self.all_posts[idx].account_id {
                    if let Some(amt) = &self.all_posts[idx].amount {
                        if !amt.is_null() {
                            let key = acct_id.index();
                            let entry = period_values.entry(key);
                            match entry {
                                std::collections::btree_map::Entry::Occupied(mut e) => {
                                    let (_, ref mut existing) = e.get_mut();
                                    if existing.commodity() == amt.commodity() {
                                        *existing = existing.clone() + amt.clone();
                                    }
                                }
                                std::collections::btree_map::Entry::Vacant(e) => {
                                    e.insert((acct_id, amt.clone()));
                                }
                            }
                        }
                    }
                }

                saw_posts = true;
                idx += 1;
            }

            if saw_posts || self.generate_empty {
                if !period_values.is_empty() {
                    for (_key, (acct_id, amount)) in &period_values {
                        let post = EnrichedPost::synthetic(
                            Some(*acct_id),
                            amount.clone(),
                            Some(period_start),
                            &format!("- {}", period_start),
                        );
                        self.handler.handle(post);
                    }
                } else if self.generate_empty {
                    let post = EnrichedPost::synthetic(
                        None,
                        Amount::from_int(0),
                        Some(period_start),
                        &format!("- {}", period_start),
                    );
                    self.handler.handle(post);
                }
            }

            // Advance period
            period_start = period_end;
            period_end = period_start + duration;

            // If no more posts and not generating empty, stop
            if idx >= n && !self.generate_empty {
                break;
            }
            // Safety: prevent infinite loop when generate_empty but past all data
            if idx >= n && self.generate_empty && period_start > period_end {
                break;
            }
        }

        self.all_posts.clear();
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.all_posts.clear();
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// InvertPosts
// ---------------------------------------------------------------------------

/// Negates the amount of each posting before forwarding.
pub struct InvertPosts {
    handler: Box<dyn PostHandler>,
}

impl InvertPosts {
    pub fn new(handler: Box<dyn PostHandler>) -> Self {
        Self { handler }
    }
}

impl PostHandler for InvertPosts {
    fn handle(&mut self, mut post: EnrichedPost) {
        if let Some(ref amt) = post.amount {
            if !amt.is_null() {
                post.amount = Some(amt.negated());
            }
        }
        self.handler.handle(post);
    }

    fn flush(&mut self) {
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// RelatedPosts
// ---------------------------------------------------------------------------

/// Replaces each posting with the related (other-side) postings
/// from the same transaction.
pub struct RelatedPosts {
    handler: Box<dyn PostHandler>,
    also_matching: bool,
    /// Track seen (xact_idx, post_idx) pairs to avoid duplicates.
    seen: std::collections::HashSet<(usize, usize)>,
}

impl RelatedPosts {
    pub fn new(handler: Box<dyn PostHandler>, also_matching: bool) -> Self {
        Self {
            handler,
            also_matching,
            seen: std::collections::HashSet::new(),
        }
    }
}

impl PostHandler for RelatedPosts {
    fn handle(&mut self, post: EnrichedPost) {
        // If no xact reference, just pass through.
        let xact_idx = match post.xact_idx {
            Some(idx) => idx,
            None => {
                self.handler.handle(post);
                return;
            }
        };

        // Emit the original if also_matching.
        if self.also_matching {
            if let Some(pi) = post.post_idx {
                let key = (xact_idx, pi);
                if !self.seen.contains(&key) {
                    self.seen.insert(key);
                    self.handler.handle(post.clone());
                }
            }
        }

        // Emit related postings (indices stored in the enriched post).
        for &related_idx in &post.related_post_indices {
            let key = (xact_idx, related_idx);
            if !self.seen.contains(&key) {
                self.seen.insert(key);
                // Create a minimal enriched post for the related posting.
                let mut related = post.clone();
                related.post_idx = Some(related_idx);
                // Note: in a full implementation, we'd look up the actual
                // posting data from the journal. For the pipeline, we mark
                // it as related.
                self.handler.handle(related);
            }
        }
    }

    fn flush(&mut self) {
        self.seen.clear();
        self.handler.flush();
    }

    fn clear(&mut self) {
        self.seen.clear();
        self.handler.clear();
    }

    fn collected(&self) -> &[EnrichedPost] {
        self.handler.collected()
    }
}

// ---------------------------------------------------------------------------
// Helper: feed journal postings into a handler
// ---------------------------------------------------------------------------

/// Feed all postings from a journal into a handler, enriching them first.
pub fn walk_journal_posts(
    journal: &Journal,
    handler: &mut dyn PostHandler,
) {
    for (xi, xact) in journal.xacts.iter().enumerate() {
        for pi in 0..xact.posts.len() {
            let ep = EnrichedPost::from_journal(journal, xi, pi);
            handler.handle(ep);
        }
    }
    handler.flush();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::account::AccountId;
    use crate::amount::Amount;
    use crate::item::ItemState;
    use crate::journal::Journal;
    use crate::post::Post;
    use crate::xact::Transaction;

    /// Helper: create a simple enriched post.
    fn make_epost(
        acct_idx: usize,
        amount_str: &str,
        date: Option<NaiveDate>,
        payee: &str,
    ) -> EnrichedPost {
        EnrichedPost {
            account_id: Some(AccountId(acct_idx)),
            amount: Some(Amount::parse(amount_str).unwrap()),
            date,
            payee: payee.to_string(),
            state: ItemState::Uncleared,
            flags: 0,
            note: None,
            cost: None,
            code: None,
            xact_idx: None,
            post_idx: None,
            xdata: PostXData::default(),
            related_post_indices: Vec::new(),
        }
    }

    /// Helper: create a simple enriched post with xact reference.
    fn make_epost_with_xact(
        acct_idx: usize,
        amount_str: &str,
        date: Option<NaiveDate>,
        payee: &str,
        xact_idx: usize,
        post_idx: usize,
    ) -> EnrichedPost {
        let mut ep = make_epost(acct_idx, amount_str, date, payee);
        ep.xact_idx = Some(xact_idx);
        ep.post_idx = Some(post_idx);
        ep
    }

    fn d(y: i32, m: u32, d: u32) -> Option<NaiveDate> {
        Some(NaiveDate::from_ymd_opt(y, m, d).unwrap())
    }

    // ---- CollectPosts -------------------------------------------------------

    #[test]
    fn collect_posts_accumulates() {
        let mut collector = CollectPosts::new();
        collector.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Test 1"));
        collector.handle(make_epost(2, "$20.00", d(2024, 1, 2), "Test 2"));
        collector.flush();
        assert_eq!(collector.posts.len(), 2);
    }

    #[test]
    fn collect_posts_clear() {
        let mut collector = CollectPosts::new();
        collector.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Test"));
        assert_eq!(collector.posts.len(), 1);
        collector.clear();
        assert_eq!(collector.posts.len(), 0);
    }

    // ---- FilterPosts --------------------------------------------------------

    #[test]
    fn filter_posts_passes_matching() {
        let collector = Box::new(CollectPosts::new());
        let mut filter = FilterPosts::new(
            collector,
            Box::new(|post: &EnrichedPost| {
                post.amount
                    .as_ref()
                    .map(|a| a.is_positive())
                    .unwrap_or(false)
            }),
        );

        filter.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Pos"));
        filter.handle(make_epost(2, "$-5.00", d(2024, 1, 2), "Neg"));
        filter.handle(make_epost(3, "$20.00", d(2024, 1, 3), "Pos2"));
        filter.flush();

        assert_eq!(filter.collected().len(), 2);
    }

    #[test]
    fn filter_posts_blocks_non_matching() {
        let collector = Box::new(CollectPosts::new());
        let mut filter = FilterPosts::new(
            collector,
            Box::new(|_: &EnrichedPost| false),
        );

        filter.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Test"));
        filter.flush();

        assert_eq!(filter.collected().len(), 0);
    }

    // ---- DisplayFilter ------------------------------------------------------

    #[test]
    fn display_filter_passes_matching() {
        let collector = Box::new(CollectPosts::new());
        let mut display = DisplayFilter::new(
            collector,
            Box::new(|post: &EnrichedPost| {
                post.amount
                    .as_ref()
                    .map(|a| a.is_positive())
                    .unwrap_or(false)
            }),
        );

        display.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Pos"));
        display.handle(make_epost(2, "$-5.00", d(2024, 1, 2), "Neg"));
        display.flush();

        assert_eq!(display.collected().len(), 1);
    }

    // ---- SortPosts ----------------------------------------------------------

    #[test]
    fn sort_posts_by_date() {
        let collector = Box::new(CollectPosts::new());
        let mut sorter = SortPosts::new(
            collector,
            Box::new(|post: &EnrichedPost| SortKey::Date(post.date)),
            false,
        );

        sorter.handle(make_epost(1, "$10.00", d(2024, 3, 15), "March"));
        sorter.handle(make_epost(2, "$20.00", d(2024, 1, 10), "January"));
        sorter.handle(make_epost(3, "$30.00", d(2024, 2, 20), "February"));
        sorter.flush();

        let collected = sorter.collected();
        assert_eq!(collected.len(), 3);
        assert_eq!(collected[0].payee, "January");
        assert_eq!(collected[1].payee, "February");
        assert_eq!(collected[2].payee, "March");
    }

    #[test]
    fn sort_posts_reverse() {
        let collector = Box::new(CollectPosts::new());
        let mut sorter = SortPosts::new(
            collector,
            Box::new(|post: &EnrichedPost| SortKey::Date(post.date)),
            true,
        );

        sorter.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        sorter.handle(make_epost(2, "$20.00", d(2024, 3, 1), "C"));
        sorter.handle(make_epost(3, "$30.00", d(2024, 2, 1), "B"));
        sorter.flush();

        let collected = sorter.collected();
        assert_eq!(collected[0].payee, "C");
        assert_eq!(collected[1].payee, "B");
        assert_eq!(collected[2].payee, "A");
    }

    #[test]
    fn sort_posts_by_string_key() {
        let collector = Box::new(CollectPosts::new());
        let mut sorter = SortPosts::new(
            collector,
            Box::new(|post: &EnrichedPost| SortKey::String(post.payee.clone())),
            false,
        );

        sorter.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Charlie"));
        sorter.handle(make_epost(2, "$20.00", d(2024, 1, 2), "Alice"));
        sorter.handle(make_epost(3, "$30.00", d(2024, 1, 3), "Bob"));
        sorter.flush();

        let collected = sorter.collected();
        assert_eq!(collected[0].payee, "Alice");
        assert_eq!(collected[1].payee, "Bob");
        assert_eq!(collected[2].payee, "Charlie");
    }

    // ---- TruncatePosts ------------------------------------------------------

    #[test]
    fn truncate_posts_limits_output() {
        let collector = Box::new(CollectPosts::new());
        let mut truncate = TruncatePosts::new(collector, 2);

        truncate.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        truncate.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        truncate.handle(make_epost(3, "$30.00", d(2024, 1, 3), "C"));
        truncate.handle(make_epost(4, "$40.00", d(2024, 1, 4), "D"));
        truncate.flush();

        assert_eq!(truncate.collected().len(), 2);
        assert_eq!(truncate.collected()[0].payee, "A");
        assert_eq!(truncate.collected()[1].payee, "B");
    }

    #[test]
    fn truncate_posts_fewer_than_limit() {
        let collector = Box::new(CollectPosts::new());
        let mut truncate = TruncatePosts::new(collector, 10);

        truncate.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        truncate.flush();

        assert_eq!(truncate.collected().len(), 1);
    }

    #[test]
    fn truncate_posts_clear_resets_count() {
        let collector = Box::new(CollectPosts::new());
        let mut truncate = TruncatePosts::new(collector, 1);

        truncate.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        truncate.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        truncate.flush();
        assert_eq!(truncate.collected().len(), 1);

        truncate.clear();
        truncate.handle(make_epost(3, "$30.00", d(2024, 1, 3), "C"));
        truncate.flush();
        assert_eq!(truncate.collected().len(), 1);
        assert_eq!(truncate.collected()[0].payee, "C");
    }

    // ---- CalcPosts ----------------------------------------------------------

    #[test]
    fn calc_posts_running_total() {
        let collector = Box::new(CollectPosts::new());
        let mut calc = CalcPosts::new(collector, None, true);

        calc.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        calc.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        calc.handle(make_epost(3, "$30.00", d(2024, 1, 3), "C"));
        calc.flush();

        let collected = calc.collected();
        assert_eq!(collected.len(), 3);
        assert_eq!(collected[0].xdata.count, 1);
        assert_eq!(collected[1].xdata.count, 2);
        assert_eq!(collected[2].xdata.count, 3);

        // Check running totals
        let t1 = collected[0].xdata.total.as_ref().unwrap();
        let t2 = collected[1].xdata.total.as_ref().unwrap();
        let t3 = collected[2].xdata.total.as_ref().unwrap();
        assert_eq!(t1.to_string(), "$10.00");
        assert_eq!(t2.to_string(), "$30.00");
        assert_eq!(t3.to_string(), "$60.00");
    }

    #[test]
    fn calc_posts_no_running_total() {
        let collector = Box::new(CollectPosts::new());
        let mut calc = CalcPosts::new(collector, None, false);

        calc.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        calc.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        calc.flush();

        let collected = calc.collected();
        assert_eq!(collected.len(), 2);
        assert!(collected[0].xdata.total.is_none());
        assert!(collected[1].xdata.total.is_none());
    }

    #[test]
    fn calc_posts_visited_value() {
        let collector = Box::new(CollectPosts::new());
        let mut calc = CalcPosts::new(collector, None, true);

        calc.handle(make_epost(1, "$42.50", d(2024, 1, 1), "Test"));
        calc.flush();

        let collected = calc.collected();
        let visited = collected[0].xdata.visited_value.as_ref().unwrap();
        assert_eq!(visited.to_string(), "$42.50");
    }

    // ---- CollapsePosts ------------------------------------------------------

    #[test]
    fn collapse_single_post_passes_through() {
        let collector = Box::new(CollectPosts::new());
        let mut collapse = CollapsePosts::new(collector);

        let ep = make_epost_with_xact(1, "$10.00", d(2024, 1, 1), "Test", 0, 0);
        collapse.handle(ep);
        collapse.flush();

        assert_eq!(collapse.collected().len(), 1);
        assert_eq!(collapse.collected()[0].payee, "Test");
    }

    #[test]
    fn collapse_multiple_same_xact() {
        let collector = Box::new(CollectPosts::new());
        let mut collapse = CollapsePosts::new(collector);

        let ep1 = make_epost_with_xact(1, "$10.00", d(2024, 1, 1), "Test", 0, 0);
        let ep2 = make_epost_with_xact(2, "$20.00", d(2024, 1, 1), "Test", 0, 1);
        collapse.handle(ep1);
        collapse.handle(ep2);
        collapse.flush();

        let collected = collapse.collected();
        assert_eq!(collected.len(), 1);
        assert_eq!(collected[0].xdata.component_count, 2);
    }

    #[test]
    fn collapse_different_xacts() {
        let collector = Box::new(CollectPosts::new());
        let mut collapse = CollapsePosts::new(collector);

        let ep1 = make_epost_with_xact(1, "$10.00", d(2024, 1, 1), "Xact1", 0, 0);
        let ep2 = make_epost_with_xact(2, "$20.00", d(2024, 1, 1), "Xact1", 0, 1);
        let ep3 = make_epost_with_xact(3, "$30.00", d(2024, 1, 2), "Xact2", 1, 0);
        collapse.handle(ep1);
        collapse.handle(ep2);
        collapse.handle(ep3);
        collapse.flush();

        let collected = collapse.collected();
        assert_eq!(collected.len(), 2);
    }

    // ---- SubtotalPosts ------------------------------------------------------

    #[test]
    fn subtotal_posts_groups_by_account() {
        let collector = Box::new(CollectPosts::new());
        let mut subtotal = SubtotalPosts::new(collector);

        subtotal.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        subtotal.handle(make_epost(1, "$20.00", d(2024, 1, 2), "B"));
        subtotal.handle(make_epost(2, "$30.00", d(2024, 1, 3), "C"));
        subtotal.flush();

        let collected = subtotal.collected();
        assert_eq!(collected.len(), 2); // Two distinct accounts
    }

    #[test]
    fn subtotal_posts_accumulates_amounts() {
        let collector = Box::new(CollectPosts::new());
        let mut subtotal = SubtotalPosts::new(collector);

        subtotal.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        subtotal.handle(make_epost(1, "$20.00", d(2024, 1, 2), "B"));
        subtotal.flush();

        let collected = subtotal.collected();
        assert_eq!(collected.len(), 1);
        let amt = collected[0].amount.as_ref().unwrap();
        assert_eq!(amt.to_string(), "$30.00");
    }

    // ---- InvertPosts --------------------------------------------------------

    #[test]
    fn invert_posts_negates_amounts() {
        let collector = Box::new(CollectPosts::new());
        let mut invert = InvertPosts::new(collector);

        invert.handle(make_epost(1, "$10.00", d(2024, 1, 1), "Test"));
        invert.handle(make_epost(2, "$-20.00", d(2024, 1, 2), "Test2"));
        invert.flush();

        let collected = invert.collected();
        assert_eq!(collected.len(), 2);

        let a1 = collected[0].amount.as_ref().unwrap();
        assert!(a1.is_negative());
        assert_eq!(a1.to_string(), "$-10.00");

        let a2 = collected[1].amount.as_ref().unwrap();
        assert!(a2.is_positive());
        assert_eq!(a2.to_string(), "$20.00");
    }

    // ---- IntervalPosts ------------------------------------------------------

    #[test]
    fn interval_posts_groups_by_period() {
        let collector = Box::new(CollectPosts::new());
        let mut interval = IntervalPosts::new(
            collector,
            30, // ~monthly
            Some(NaiveDate::from_ymd_opt(2024, 1, 1).unwrap()),
            false,
        );

        interval.handle(make_epost(1, "$10.00", d(2024, 1, 5), "Jan"));
        interval.handle(make_epost(1, "$20.00", d(2024, 1, 15), "Jan2"));
        interval.handle(make_epost(1, "$30.00", d(2024, 2, 5), "Feb"));
        interval.flush();

        let collected = interval.collected();
        // Should have 2 periods: Jan (combined) and Feb
        assert_eq!(collected.len(), 2);
    }

    #[test]
    fn interval_posts_empty_period() {
        let collector = Box::new(CollectPosts::new());
        let mut interval = IntervalPosts::new(
            collector,
            30,
            Some(NaiveDate::from_ymd_opt(2024, 1, 1).unwrap()),
            false,
        );

        // No postings
        interval.flush();
        assert_eq!(interval.collected().len(), 0);
    }

    // ---- RelatedPosts -------------------------------------------------------

    #[test]
    fn related_posts_emits_others() {
        let collector = Box::new(CollectPosts::new());
        let mut related = RelatedPosts::new(collector, false);

        let mut ep = make_epost_with_xact(1, "$10.00", d(2024, 1, 1), "Test", 0, 0);
        ep.related_post_indices = vec![1, 2];
        related.handle(ep);
        related.flush();

        // Should emit the 2 related postings (not the original)
        assert_eq!(related.collected().len(), 2);
    }

    #[test]
    fn related_posts_also_matching() {
        let collector = Box::new(CollectPosts::new());
        let mut related = RelatedPosts::new(collector, true);

        let mut ep = make_epost_with_xact(1, "$10.00", d(2024, 1, 1), "Test", 0, 0);
        ep.related_post_indices = vec![1];
        related.handle(ep);
        related.flush();

        // Should emit original + 1 related = 2
        assert_eq!(related.collected().len(), 2);
    }

    // ---- walk_journal_posts -------------------------------------------------

    #[test]
    fn walk_journal_posts_enriches() {
        let mut journal = Journal::new();
        let acct1 = journal.find_account("Expenses:Food", true).unwrap();
        let acct2 = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact = Transaction::with_payee("Grocery");
        xact.item.date = Some(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap());
        xact.add_post(Post::with_account_and_amount(
            acct1,
            Amount::parse("$50.00").unwrap(),
        ));
        xact.add_post(Post::with_account(acct2));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let mut collector = CollectPosts::new();
        walk_journal_posts(&journal, &mut collector);

        assert_eq!(collector.posts.len(), 2);
        assert_eq!(collector.posts[0].payee, "Grocery");
        assert_eq!(collector.posts[0].date, Some(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap()));
        assert_eq!(collector.posts[0].account_id, Some(acct1));
    }

    // ---- Pipeline chaining --------------------------------------------------

    #[test]
    fn pipeline_filter_then_sort() {
        let collector = Box::new(CollectPosts::new());
        let sorter = Box::new(SortPosts::new(
            collector,
            Box::new(|post: &EnrichedPost| SortKey::Date(post.date)),
            false,
        ));
        let mut filter = FilterPosts::new(
            sorter,
            Box::new(|post: &EnrichedPost| {
                post.amount
                    .as_ref()
                    .map(|a| a.is_positive())
                    .unwrap_or(false)
            }),
        );

        filter.handle(make_epost(1, "$-5.00", d(2024, 3, 1), "Neg"));
        filter.handle(make_epost(2, "$20.00", d(2024, 1, 1), "Jan"));
        filter.handle(make_epost(3, "$10.00", d(2024, 2, 1), "Feb"));
        filter.flush();

        let collected = filter.collected();
        assert_eq!(collected.len(), 2);
        assert_eq!(collected[0].payee, "Jan");
        assert_eq!(collected[1].payee, "Feb");
    }

    #[test]
    fn pipeline_calc_then_truncate() {
        let collector = Box::new(CollectPosts::new());
        let truncate = Box::new(TruncatePosts::new(collector, 2));
        let mut calc = CalcPosts::new(truncate, None, true);

        calc.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        calc.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        calc.handle(make_epost(3, "$30.00", d(2024, 1, 3), "C"));
        calc.flush();

        let collected = calc.collected();
        assert_eq!(collected.len(), 2);
        // Running total should be computed before truncation
        let t2 = collected[1].xdata.total.as_ref().unwrap();
        assert_eq!(t2.to_string(), "$30.00");
    }

    #[test]
    fn pipeline_invert_then_calc() {
        let collector = Box::new(CollectPosts::new());
        let calc = Box::new(CalcPosts::new(collector, None, true));
        let mut invert = InvertPosts::new(calc);

        invert.handle(make_epost(1, "$10.00", d(2024, 1, 1), "A"));
        invert.handle(make_epost(2, "$20.00", d(2024, 1, 2), "B"));
        invert.flush();

        let collected = invert.collected();
        assert_eq!(collected.len(), 2);
        // Amounts should be negated
        assert!(collected[0].amount.as_ref().unwrap().is_negative());
        // Running total should reflect negated amounts
        let t2 = collected[1].xdata.total.as_ref().unwrap();
        assert_eq!(t2.to_string(), "$-30.00");
    }

    #[test]
    fn enriched_post_from_journal_roundtrip() {
        let mut journal = Journal::new();
        let acct = journal.find_account("Expenses:Food", true).unwrap();

        let mut xact = Transaction::with_payee("Store");
        xact.item.date = Some(NaiveDate::from_ymd_opt(2024, 6, 15).unwrap());
        xact.item.state = ItemState::Cleared;
        xact.code = Some("1001".to_string());
        xact.add_post(Post::with_account_and_amount(
            acct,
            Amount::parse("$99.99").unwrap(),
        ));
        xact.add_post(Post::with_account(
            journal.find_account("Assets:Cash", true).unwrap(),
        ));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let ep = EnrichedPost::from_journal(&journal, 0, 0);
        assert_eq!(ep.payee, "Store");
        assert_eq!(ep.state, ItemState::Cleared);
        assert_eq!(ep.code.as_deref(), Some("1001"));
        assert_eq!(ep.account_id, Some(acct));
        assert_eq!(ep.amount.as_ref().unwrap().to_string(), "$99.99");
        assert_eq!(ep.xact_idx, Some(0));
        assert_eq!(ep.post_idx, Some(0));
        assert_eq!(ep.related_post_indices, vec![1]);
    }
}
