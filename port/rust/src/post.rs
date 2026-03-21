//! Postings: the line items within transactions that affect accounts.
//!
//! A posting is the fundamental unit of accounting change in Ledger. Each
//! transaction contains one or more postings, and each posting records a
//! debit or credit to a specific account.
//!
//! This module provides the `Post` struct, a Rust port of Ledger's `post_t`.

use crate::account::AccountId;
use crate::amount::Amount;
use crate::item::Item;

// ---------------------------------------------------------------------------
// Post flags (matching C++ #defines)
// ---------------------------------------------------------------------------

/// Virtual posting (parenthesized account).
pub const POST_VIRTUAL: u32 = 0x0010;
/// Virtual posting that must balance (bracketed account).
pub const POST_MUST_BALANCE: u32 = 0x0020;
/// Amount was calculated (e.g. from cost).
pub const POST_CALCULATED: u32 = 0x0040;
/// Posting was auto-generated.
pub const POST_GENERATED: u32 = 0x0080;
/// Cost was calculated.
pub const POST_COST_CALCULATED: u32 = 0x0080;
/// Cost is specified in full (not per-unit).
pub const POST_COST_IN_FULL: u32 = 0x0100;
/// Cost is fixated (@@).
pub const POST_COST_FIXATED: u32 = 0x0200;
/// Cost is virtual (not tracked).
pub const POST_COST_VIRTUAL: u32 = 0x0400;

// ---------------------------------------------------------------------------
// Post
// ---------------------------------------------------------------------------

/// A single line item within a transaction, recording a debit or credit
/// to an account.
#[derive(Debug, Clone)]
pub struct Post {
    /// Base item fields (flags, state, dates, notes, metadata, position).
    pub item: Item,
    /// The target account this posting debits or credits (arena index).
    pub account_id: Option<AccountId>,
    /// The posting amount; can be None until finalization infers it.
    pub amount: Option<Amount>,
    /// The cost amount (e.g. from `@ $10` or `@@ $100`).
    pub cost: Option<Amount>,
    /// Assigned amount from balance assertion.
    pub assigned_amount: Option<Amount>,
    /// Index of the parent transaction (set when added to a Transaction).
    pub xact_index: Option<usize>,
}

impl Post {
    /// Create a new Post with default values.
    pub fn new() -> Self {
        Self {
            item: Item::new(),
            account_id: None,
            amount: None,
            cost: None,
            assigned_amount: None,
            xact_index: None,
        }
    }

    /// Create a new Post with an account and amount.
    pub fn with_account_and_amount(account_id: AccountId, amount: Amount) -> Self {
        Self {
            item: Item::new(),
            account_id: Some(account_id),
            amount: Some(amount),
            cost: None,
            assigned_amount: None,
            xact_index: None,
        }
    }

    /// Create a new Post with account only (null amount, for auto-balancing).
    pub fn with_account(account_id: AccountId) -> Self {
        Self {
            item: Item::new(),
            account_id: Some(account_id),
            amount: None,
            cost: None,
            assigned_amount: None,
            xact_index: None,
        }
    }

    // ---- query helpers ------------------------------------------------------

    /// Return true if this posting participates in balance checking.
    ///
    /// Plain virtual postings `(Account)` do not need to balance.
    /// Real postings and balanced-virtual postings `[Account]` must.
    pub fn must_balance(&self) -> bool {
        if self.item.has_flags(POST_VIRTUAL) {
            return self.item.has_flags(POST_MUST_BALANCE);
        }
        true
    }

    /// Return true if this is a virtual posting (parenthesized account).
    pub fn is_virtual(&self) -> bool {
        self.item.has_flags(POST_VIRTUAL)
    }

    // ---- description --------------------------------------------------------

    /// Return a human-readable description for error messages.
    pub fn description(&self) -> String {
        if let Some(pos) = &self.item.position {
            format!("posting at line {}", pos.beg_line)
        } else {
            "generated posting".to_string()
        }
    }
}

impl Default for Post {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::item::ITEM_NORMAL;

    #[test]
    fn post_new_defaults() {
        let post = Post::new();
        assert!(post.account_id.is_none());
        assert!(post.amount.is_none());
        assert!(post.cost.is_none());
        assert!(post.assigned_amount.is_none());
        assert!(post.xact_index.is_none());
        assert_eq!(post.item.flags, ITEM_NORMAL);
    }

    #[test]
    fn post_with_account_and_amount() {
        let acct = AccountId(1);
        let amt = Amount::parse("$42.50").unwrap();
        let post = Post::with_account_and_amount(acct, amt);
        assert_eq!(post.account_id, Some(AccountId(1)));
        assert!(post.amount.is_some());
    }

    #[test]
    fn post_with_account_null_amount() {
        let acct = AccountId(2);
        let post = Post::with_account(acct);
        assert_eq!(post.account_id, Some(AccountId(2)));
        assert!(post.amount.is_none());
    }

    #[test]
    fn post_must_balance_real() {
        let post = Post::new();
        assert!(post.must_balance());
    }

    #[test]
    fn post_must_balance_virtual_no_balance() {
        let mut post = Post::new();
        post.item.add_flags(POST_VIRTUAL);
        assert!(!post.must_balance());
    }

    #[test]
    fn post_must_balance_virtual_with_balance() {
        let mut post = Post::new();
        post.item.add_flags(POST_VIRTUAL | POST_MUST_BALANCE);
        assert!(post.must_balance());
    }

    #[test]
    fn post_is_virtual() {
        let mut post = Post::new();
        assert!(!post.is_virtual());
        post.item.add_flags(POST_VIRTUAL);
        assert!(post.is_virtual());
    }

    #[test]
    fn post_description_generated() {
        let post = Post::new();
        assert_eq!(post.description(), "generated posting");
    }

    #[test]
    fn post_description_with_position() {
        let mut post = Post::new();
        post.item.position = Some(crate::item::Position {
            pathname: "test.dat".to_string(),
            beg_line: 10,
            ..Default::default()
        });
        assert_eq!(post.description(), "posting at line 10");
    }
}
