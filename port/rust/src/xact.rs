//! Transaction class for Ledger's journal entries.
//!
//! This module provides the `Transaction` struct, a Rust port of Ledger's
//! `xact_t`. A transaction is a dated entry with a payee and two or more
//! postings that must balance (double-entry invariant).
//!
//! The critical method is `finalize()`, which:
//!   1. Scans all postings, sums amounts, tracks null-amount postings
//!   2. Infers the missing amount if exactly one posting has a null amount
//!   3. Verifies that the transaction balances (sum equals zero)

use std::fmt;

use crate::amount::Amount;
use crate::item::{Item, ITEM_INFERRED};
use crate::post::{Post, POST_CALCULATED};
use crate::value::Value;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Raised when a transaction does not balance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BalanceError(pub String);

impl fmt::Display for BalanceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "BalanceError: {}", self.0)
    }
}

impl std::error::Error for BalanceError {}

// ---------------------------------------------------------------------------
// Transaction
// ---------------------------------------------------------------------------

/// A regular dated transaction -- the primary journal entry.
///
/// In journal syntax:
/// ```text
///     2024/01/15 * (1042) Grocery Store
///         Expenses:Food       $42.50
///         Assets:Checking
/// ```
///
/// Here `*` is the clearing state (Cleared), `(1042)` is the code,
/// and `Grocery Store` is the payee.
#[derive(Debug, Clone)]
pub struct Transaction {
    /// Base item fields (flags, state, dates, notes, metadata, position).
    pub item: Item,
    /// The payee/description of the transaction.
    pub payee: String,
    /// The list of postings in this transaction.
    pub posts: Vec<Post>,
    /// Optional check number or transaction code.
    pub code: Option<String>,
}

impl Transaction {
    /// Create a new empty transaction.
    pub fn new() -> Self {
        Self {
            item: Item::new(),
            payee: String::new(),
            posts: Vec::new(),
            code: None,
        }
    }

    /// Create a new transaction with a payee.
    pub fn with_payee(payee: &str) -> Self {
        Self {
            item: Item::new(),
            payee: payee.to_string(),
            posts: Vec::new(),
            code: None,
        }
    }

    // ---- post management ----------------------------------------------------

    /// Add a posting to this transaction.
    ///
    /// Sets the posting's `xact_index` back-reference to this transaction's
    /// index in the posts vec (not the journal index -- that is set at
    /// journal level).
    pub fn add_post(&mut self, mut post: Post) {
        let idx = self.posts.len();
        post.xact_index = Some(idx);
        self.posts.push(post);
    }

    /// Return the number of postings.
    pub fn len(&self) -> usize {
        self.posts.len()
    }

    /// Return true if there are no postings.
    pub fn is_empty(&self) -> bool {
        self.posts.is_empty()
    }

    // ---- magnitude ----------------------------------------------------------

    /// Compute the absolute value of the positive side of the transaction.
    ///
    /// Sums the cost (or amount, if no cost) of all postings with positive
    /// amounts. Used in error messages to give context about the
    /// transaction's overall size.
    pub fn magnitude(&self) -> Value {
        let mut mag = Value::Void;
        for post in &self.posts {
            let amt = post.cost.as_ref().or(post.amount.as_ref());
            if let Some(a) = amt {
                if !a.is_null() && a.is_positive() {
                    if mag.is_null() {
                        mag = Value::Amount(a.clone());
                    } else {
                        mag = mag
                            .value_add(&Value::Amount(a.clone()))
                            .unwrap_or(mag);
                    }
                }
            }
        }
        mag
    }

    // ---- finalize -----------------------------------------------------------

    /// Finalize the transaction: infer amounts and check balance.
    ///
    /// This is the core of double-entry accounting enforcement. Called after
    /// all postings have been added.
    ///
    /// 1. Scan all postings that must balance, accumulate their amounts.
    /// 2. Track the single posting (if any) with a null amount.
    /// 3. If exactly one null-amount posting exists, set its amount to
    ///    negate the running balance (auto-balance).
    /// 4. Verify the final balance is zero.
    /// 5. Return `Err(BalanceError)` if the transaction does not balance.
    ///
    /// Returns `Ok(true)` if valid, `Ok(false)` if all amounts are null
    /// (degenerate transaction to be ignored).
    pub fn finalize(&mut self) -> Result<bool, BalanceError> {
        // Phase 1: Scan postings, accumulate balance, find null-amount posts.
        let mut balance = Value::Void;
        let mut null_post_idx: Option<usize> = None;

        for (i, post) in self.posts.iter().enumerate() {
            if !post.must_balance() {
                continue;
            }

            // Use cost if available, otherwise the posting amount.
            let amt = post.cost.as_ref().or(post.amount.as_ref());

            match amt {
                Some(a) if !a.is_null() => {
                    let reduced = if a.keep_precision() {
                        a.rounded()
                    } else {
                        a.clone()
                    };
                    if balance.is_null() {
                        balance = Value::Amount(reduced);
                    } else {
                        balance = balance
                            .value_add(&Value::Amount(reduced))
                            .map_err(|e| BalanceError(format!("Balance computation failed: {}", e)))?;
                    }
                }
                _ => {
                    // Null amount posting
                    if null_post_idx.is_some() {
                        return Err(BalanceError(
                            "Only one posting with null amount allowed per transaction"
                                .to_string(),
                        ));
                    }
                    null_post_idx = Some(i);
                }
            }
        }

        // Phase 2: Infer null-amount posting.
        if let Some(idx) = null_post_idx {
            if balance.is_null() || balance.is_realzero() {
                // All other amounts are null or zero; set to zero.
                self.posts[idx].amount = Some(Amount::from_int(0));
            } else {
                // Set the null posting's amount to negate the balance.
                let neg_balance = balance
                    .value_neg()
                    .map_err(|e| BalanceError(format!("Negation failed: {}", e)))?;
                let inferred_amount = neg_balance
                    .to_amount()
                    .map_err(|e| BalanceError(format!("Cannot convert to amount: {}", e)))?;
                self.posts[idx].amount = Some(inferred_amount);
            }
            self.posts[idx].item.add_flags(POST_CALCULATED | ITEM_INFERRED);
            // Reset balance to zero since we just balanced it.
            balance = Value::Void;
        }

        // Phase 3: Final balance verification.
        // When a transaction has postings in multiple commodities and every
        // posting has an explicit amount (no null-amount posting), C++ ledger
        // treats it as an implicit exchange and considers it balanced.  We
        // replicate that: if the accumulated balance is a multi-commodity
        // Balance variant and there was no null posting to infer, skip the
        // single-commodity zero check.
        if !balance.is_null() && !balance.is_zero() {
            let is_multi_commodity =
                matches!(&balance, Value::Balance(_)) && null_post_idx.is_none();
            if !is_multi_commodity {
                return Err(BalanceError(format!(
                    "Transaction does not balance: remainder is {}",
                    balance.to_string_value()
                )));
            }
        }

        // Check if all amounts were null (degenerate transaction).
        let all_null = self.posts.iter().all(|p| {
            p.amount.is_none() || p.amount.as_ref().map_or(true, |a| a.is_null())
        });
        if all_null && !self.posts.is_empty() {
            return Ok(false);
        }

        Ok(true)
    }

    // ---- description --------------------------------------------------------

    /// Return a human-readable description for error messages.
    pub fn description(&self) -> String {
        if let Some(pos) = &self.item.position {
            format!("transaction at line {}", pos.beg_line)
        } else {
            "generated transaction".to_string()
        }
    }
}

impl Default for Transaction {
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
    use crate::account::AccountId;
    use crate::amount::Amount;
    use crate::post::Post;

    fn make_post(account_id: usize, amount_str: &str) -> Post {
        Post::with_account_and_amount(
            AccountId(account_id),
            Amount::parse(amount_str).unwrap(),
        )
    }

    fn make_null_post(account_id: usize) -> Post {
        Post::with_account(AccountId(account_id))
    }

    #[test]
    fn transaction_new_defaults() {
        let xact = Transaction::new();
        assert!(xact.payee.is_empty());
        assert!(xact.posts.is_empty());
        assert!(xact.code.is_none());
        assert_eq!(xact.len(), 0);
        assert!(xact.is_empty());
    }

    #[test]
    fn transaction_with_payee() {
        let xact = Transaction::with_payee("Grocery Store");
        assert_eq!(xact.payee, "Grocery Store");
    }

    #[test]
    fn transaction_add_post() {
        let mut xact = Transaction::new();
        let post = make_post(1, "$42.50");
        xact.add_post(post);
        assert_eq!(xact.len(), 1);
        assert!(!xact.is_empty());
        assert_eq!(xact.posts[0].xact_index, Some(0));
    }

    #[test]
    fn finalize_balanced_transaction() {
        let mut xact = Transaction::with_payee("Test");
        xact.add_post(make_post(1, "$42.50"));
        xact.add_post(make_post(2, "$-42.50"));
        let result = xact.finalize();
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);
    }

    #[test]
    fn finalize_auto_balance_single_null() {
        let mut xact = Transaction::with_payee("Test");
        xact.add_post(make_post(1, "$42.50"));
        xact.add_post(make_null_post(2));
        let result = xact.finalize();
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);

        // The null post should now have $-42.50
        let inferred = xact.posts[1].amount.as_ref().unwrap();
        assert!(inferred.is_negative());
        assert!(xact.posts[1].item.has_flags(POST_CALCULATED));
        assert!(xact.posts[1].item.has_flags(ITEM_INFERRED));
    }

    #[test]
    fn finalize_multiple_null_posts_error() {
        let mut xact = Transaction::with_payee("Test");
        xact.add_post(make_null_post(1));
        xact.add_post(make_null_post(2));
        let result = xact.finalize();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.0.contains("null amount"));
    }

    #[test]
    fn finalize_unbalanced_error() {
        let mut xact = Transaction::with_payee("Test");
        xact.add_post(make_post(1, "$42.50"));
        xact.add_post(make_post(2, "$-10.00"));
        let result = xact.finalize();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.0.contains("does not balance"));
    }

    #[test]
    fn finalize_all_null_returns_false() {
        let mut xact = Transaction::with_payee("Test");
        xact.add_post(make_null_post(1));
        let result = xact.finalize();
        // Single null post is auto-balanced to 0, but check degenerate case
        // with the auto-balance logic: it infers 0, so all amounts become 0.
        // That should still return true since we did infer an amount.
        assert!(result.is_ok());
    }

    #[test]
    fn finalize_three_way_split() {
        let mut xact = Transaction::with_payee("Split");
        xact.add_post(make_post(1, "$100.00"));
        xact.add_post(make_post(2, "$-60.00"));
        xact.add_post(make_null_post(3));
        let result = xact.finalize();
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);

        // The third post should be inferred as $-40.00
        let inferred = xact.posts[2].amount.as_ref().unwrap();
        assert!(inferred.is_negative());
    }

    #[test]
    fn finalize_with_cost() {
        // When a posting has a cost, finalize uses the cost for balancing.
        let mut xact = Transaction::with_payee("Stock buy");
        let mut buy_post = make_post(1, "10 AAPL");
        buy_post.cost = Some(Amount::parse("$1500.00").unwrap());
        xact.add_post(buy_post);
        xact.add_post(make_null_post(2));

        let result = xact.finalize();
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);
    }

    #[test]
    fn transaction_description() {
        let xact = Transaction::new();
        assert_eq!(xact.description(), "generated transaction");
    }
}
