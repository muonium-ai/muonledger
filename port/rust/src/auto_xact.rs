//! Automated transactions: `= PREDICATE` entries in journal files.
//!
//! Ported from ledger's `auto_xact_t`. An automated transaction has a
//! predicate expression and a list of template postings. When a regular
//! transaction post matches the predicate, the template postings are
//! instantiated and added to the transaction.
//!
//! Currently supports simple regex-style predicates: `/pattern/` matches
//! against the full account name of each posting.

use crate::journal::Journal;
use crate::post::{Post, POST_GENERATED};

// ---------------------------------------------------------------------------
// AutomatedTransaction
// ---------------------------------------------------------------------------

/// An automated transaction triggered by a predicate match.
///
/// In journal syntax:
/// ```text
/// = /^Expenses:Books/
///     (Liabilities:Taxes)  -0.10
/// ```
///
/// When any posting's account matches the predicate, the template postings
/// are instantiated relative to the matched posting's amount.
#[derive(Debug, Clone)]
pub struct AutomatedTransaction {
    /// The predicate expression string (e.g. `/^Expenses:Books/`).
    pub predicate_expr: String,
    /// Template postings to instantiate on match.
    pub posts: Vec<Post>,
}

impl AutomatedTransaction {
    /// Create a new automated transaction with the given predicate.
    pub fn new(predicate_expr: &str) -> Self {
        Self {
            predicate_expr: predicate_expr.to_string(),
            posts: Vec::new(),
        }
    }

    /// Add a template posting.
    pub fn add_post(&mut self, post: Post) {
        self.posts.push(post);
    }

    /// Test whether this automated transaction's predicate matches a posting.
    ///
    /// Currently supports:
    /// - `/pattern/` — substring match against the full account name
    /// - `account =~ /pattern/` — same as above (simplified)
    /// - Plain text — exact substring match against account name
    pub fn matches(&self, post: &Post, journal: &Journal) -> bool {
        let expr = self.predicate_expr.trim();

        // Extract pattern from /pattern/ syntax
        let pattern = if expr.starts_with('/') && expr.ends_with('/') && expr.len() > 2 {
            Some(&expr[1..expr.len() - 1])
        } else if let Some(idx) = expr.find("=~ /") {
            // account =~ /pattern/
            let after = &expr[idx + 4..];
            if after.ends_with('/') && after.len() > 1 {
                Some(&after[..after.len() - 1])
            } else {
                None
            }
        } else {
            None
        };

        if let Some(pat) = pattern {
            let pat_lower = pat.to_lowercase();
            if let Some(acct_id) = post.account_id {
                let fullname = journal.account_fullname(acct_id).to_lowercase();
                // Support ^ anchor for starts-with matching
                if pat_lower.starts_with('^') {
                    return fullname.starts_with(&pat_lower[1..]);
                }
                return fullname.contains(&pat_lower);
            }
            return false;
        }

        // Plain text: substring match
        if let Some(acct_id) = post.account_id {
            let fullname = journal.account_fullname(acct_id).to_lowercase();
            return fullname.contains(&expr.to_lowercase());
        }

        false
    }

    /// Generate postings to add to a transaction based on a matched posting.
    ///
    /// For each template posting:
    /// - If the template has no amount, it is left as None (auto-balance)
    /// - If the template amount has no commodity (bare number like `0.10`),
    ///   it is treated as a multiplier against the matched posting's amount
    /// - If the template amount has a commodity (like `$5.00`), it is used
    ///   as a fixed amount
    ///
    /// All generated postings are flagged with `POST_GENERATED`.
    pub fn apply_to(&self, matched_post: &Post) -> Vec<Post> {
        let mut result = Vec::new();

        for template in &self.posts {
            let mut generated = template.clone();
            generated.item.add_flags(POST_GENERATED);

            if let Some(ref tmpl_amt) = template.amount {
                if tmpl_amt.commodity().is_none() {
                    // Bare number: treat as multiplier
                    if let Some(ref matched_amt) = matched_post.amount {
                        let product = &(matched_amt.clone()) * &(tmpl_amt.clone());
                        generated.amount = Some(product);
                    }
                }
                // else: fixed amount with commodity, use as-is
            }
            // else: no amount, leave as None for auto-balancing

            result.push(generated);
        }

        result
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::post::{Post, POST_GENERATED};

    fn setup_journal() -> Journal {
        let mut journal = Journal::new();
        journal.find_account("Expenses:Books", true);
        journal.find_account("Expenses:Food", true);
        journal.find_account("Liabilities:Taxes", true);
        journal.find_account("Assets:Checking", true);
        journal
    }

    // ---- pattern matching tests -------------------------------------------

    #[test]
    fn matches_regex_pattern() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("/expenses:books/");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    #[test]
    fn matches_regex_pattern_case_insensitive() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("/EXPENSES:BOOKS/");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    #[test]
    fn matches_anchored_pattern() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("/^expenses:books/");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    #[test]
    fn no_match_different_account() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("/expenses:books/");

        let acct_id = journal.find_account("Expenses:Food", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(!auto.matches(&post, &journal));
    }

    #[test]
    fn no_match_no_account() {
        let journal = setup_journal();
        let auto = AutomatedTransaction::new("/expenses:books/");

        let post = Post::new(); // no account_id
        assert!(!auto.matches(&post, &journal));
    }

    #[test]
    fn matches_partial_pattern() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("/books/");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    #[test]
    fn matches_tilde_syntax() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("account =~ /books/");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    #[test]
    fn matches_plain_text() {
        let mut journal = setup_journal();
        let auto = AutomatedTransaction::new("Expenses:Books");

        let acct_id = journal.find_account("Expenses:Books", true).unwrap();
        let post = Post::with_account_and_amount(acct_id, Amount::parse("$10.00").unwrap());

        assert!(auto.matches(&post, &journal));
    }

    // ---- apply_to tests ---------------------------------------------------

    #[test]
    fn apply_multiplier_amount() {
        let mut journal = setup_journal();
        let tax_id = journal.find_account("Liabilities:Taxes", true).unwrap();

        let mut auto = AutomatedTransaction::new("/expenses:books/");
        // Template: multiply by -0.10
        let tmpl = Post::with_account_and_amount(tax_id, Amount::parse("-0.10").unwrap());
        auto.add_post(tmpl);

        let books_id = journal.find_account("Expenses:Books", true).unwrap();
        let matched = Post::with_account_and_amount(books_id, Amount::parse("$20.00").unwrap());

        let generated = auto.apply_to(&matched);
        assert_eq!(generated.len(), 1);

        let gen_post = &generated[0];
        assert!(gen_post.item.has_flags(POST_GENERATED));

        let gen_amt = gen_post.amount.as_ref().unwrap();
        // $20.00 * -0.10 = $-2.00
        let expected = Amount::parse("$-2.00").unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), expected.to_double().unwrap());
    }

    #[test]
    fn apply_fixed_amount() {
        let mut journal = setup_journal();
        let tax_id = journal.find_account("Liabilities:Taxes", true).unwrap();

        let mut auto = AutomatedTransaction::new("/expenses:books/");
        // Template: fixed amount $5.00
        let tmpl = Post::with_account_and_amount(tax_id, Amount::parse("$5.00").unwrap());
        auto.add_post(tmpl);

        let books_id = journal.find_account("Expenses:Books", true).unwrap();
        let matched = Post::with_account_and_amount(books_id, Amount::parse("$20.00").unwrap());

        let generated = auto.apply_to(&matched);
        assert_eq!(generated.len(), 1);

        let gen_amt = generated[0].amount.as_ref().unwrap();
        // Fixed amount: $5.00 regardless of matched amount
        let expected = Amount::parse("$5.00").unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), expected.to_double().unwrap());
    }

    #[test]
    fn apply_null_amount_template() {
        let mut journal = setup_journal();
        let tax_id = journal.find_account("Liabilities:Taxes", true).unwrap();

        let mut auto = AutomatedTransaction::new("/expenses:books/");
        // Template: no amount (auto-balance)
        let tmpl = Post::with_account(tax_id);
        auto.add_post(tmpl);

        let books_id = journal.find_account("Expenses:Books", true).unwrap();
        let matched = Post::with_account_and_amount(books_id, Amount::parse("$20.00").unwrap());

        let generated = auto.apply_to(&matched);
        assert_eq!(generated.len(), 1);
        assert!(generated[0].amount.is_none());
        assert!(generated[0].item.has_flags(POST_GENERATED));
    }

    #[test]
    fn apply_multiple_templates() {
        let mut journal = setup_journal();
        let tax_id = journal.find_account("Liabilities:Taxes", true).unwrap();
        let check_id = journal.find_account("Assets:Checking", true).unwrap();

        let mut auto = AutomatedTransaction::new("/expenses:books/");
        auto.add_post(Post::with_account_and_amount(
            tax_id,
            Amount::parse("-0.10").unwrap(),
        ));
        auto.add_post(Post::with_account(check_id));

        let books_id = journal.find_account("Expenses:Books", true).unwrap();
        let matched = Post::with_account_and_amount(books_id, Amount::parse("$20.00").unwrap());

        let generated = auto.apply_to(&matched);
        assert_eq!(generated.len(), 2);
        assert!(generated[0].item.has_flags(POST_GENERATED));
        assert!(generated[1].item.has_flags(POST_GENERATED));
    }

    #[test]
    fn generated_posts_have_flag() {
        let mut journal = setup_journal();
        let tax_id = journal.find_account("Liabilities:Taxes", true).unwrap();

        let mut auto = AutomatedTransaction::new("/expenses/");
        auto.add_post(Post::with_account_and_amount(
            tax_id,
            Amount::parse("$1.00").unwrap(),
        ));

        let books_id = journal.find_account("Expenses:Books", true).unwrap();
        let matched = Post::with_account_and_amount(books_id, Amount::parse("$10.00").unwrap());

        let generated = auto.apply_to(&matched);
        for g in &generated {
            assert!(g.item.has_flags(POST_GENERATED));
        }
    }

    #[test]
    fn new_auto_xact() {
        let auto = AutomatedTransaction::new("/test/");
        assert_eq!(auto.predicate_expr, "/test/");
        assert!(auto.posts.is_empty());
    }

    #[test]
    fn add_post_to_auto_xact() {
        let mut auto = AutomatedTransaction::new("/test/");
        auto.add_post(Post::new());
        auto.add_post(Post::new());
        assert_eq!(auto.posts.len(), 2);
    }
}
