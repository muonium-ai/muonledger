//! Periodic transactions: `~ PERIOD` entries in journal files.
//!
//! Ported from ledger's `period_xact_t`. A periodic transaction defines
//! a recurring template used for budgeting. The period expression (e.g.
//! "monthly", "every 2 weeks") defines the recurrence, and the postings
//! define the budget amounts.
//!
//! In journal syntax:
//! ```text
//! ~ Monthly
//!     Expenses:Food         $500.00
//!     Assets:Checking
//! ```

use crate::post::Post;

// ---------------------------------------------------------------------------
// PeriodicTransaction
// ---------------------------------------------------------------------------

/// A periodic (budget) transaction triggered by a time period.
///
/// These are used by the `--budget` report option to generate expected
/// transactions at regular intervals. The `period_expr` captures the
/// recurrence specification.
#[derive(Debug, Clone)]
pub struct PeriodicTransaction {
    /// The period expression string (e.g. "Monthly", "Every 2 weeks").
    pub period_expr: String,
    /// Template postings for this periodic transaction.
    pub posts: Vec<Post>,
}

impl PeriodicTransaction {
    /// Create a new periodic transaction with the given period expression.
    pub fn new(period_expr: &str) -> Self {
        Self {
            period_expr: period_expr.to_string(),
            posts: Vec::new(),
        }
    }

    /// Add a template posting.
    pub fn add_post(&mut self, post: Post) {
        self.posts.push(post);
    }

    /// Return the period expression (trimmed).
    pub fn period(&self) -> &str {
        self.period_expr.trim()
    }

    /// Check if this is a monthly period.
    pub fn is_monthly(&self) -> bool {
        let p = self.period_expr.trim().to_lowercase();
        p == "monthly" || p == "every month"
    }

    /// Check if this is a weekly period.
    pub fn is_weekly(&self) -> bool {
        let p = self.period_expr.trim().to_lowercase();
        p == "weekly" || p == "every week"
    }

    /// Check if this is a yearly period.
    pub fn is_yearly(&self) -> bool {
        let p = self.period_expr.trim().to_lowercase();
        p == "yearly" || p == "every year" || p == "annually"
    }

    /// Check if this is a quarterly period.
    pub fn is_quarterly(&self) -> bool {
        let p = self.period_expr.trim().to_lowercase();
        p == "quarterly" || p == "every quarter" || p == "every 3 months"
    }

    /// Check if this is a daily period.
    pub fn is_daily(&self) -> bool {
        let p = self.period_expr.trim().to_lowercase();
        p == "daily" || p == "every day"
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;

    #[test]
    fn new_periodic_xact() {
        let px = PeriodicTransaction::new("Monthly");
        assert_eq!(px.period_expr, "Monthly");
        assert!(px.posts.is_empty());
    }

    #[test]
    fn add_post_to_periodic_xact() {
        let mut px = PeriodicTransaction::new("Weekly");
        px.add_post(Post::new());
        px.add_post(Post::new());
        assert_eq!(px.posts.len(), 2);
    }

    #[test]
    fn period_trimmed() {
        let px = PeriodicTransaction::new("  Monthly  ");
        assert_eq!(px.period(), "Monthly");
    }

    #[test]
    fn is_monthly() {
        assert!(PeriodicTransaction::new("Monthly").is_monthly());
        assert!(PeriodicTransaction::new("monthly").is_monthly());
        assert!(PeriodicTransaction::new("Every Month").is_monthly());
        assert!(!PeriodicTransaction::new("Weekly").is_monthly());
    }

    #[test]
    fn is_weekly() {
        assert!(PeriodicTransaction::new("Weekly").is_weekly());
        assert!(PeriodicTransaction::new("weekly").is_weekly());
        assert!(PeriodicTransaction::new("Every Week").is_weekly());
        assert!(!PeriodicTransaction::new("Monthly").is_weekly());
    }

    #[test]
    fn is_yearly() {
        assert!(PeriodicTransaction::new("Yearly").is_yearly());
        assert!(PeriodicTransaction::new("annually").is_yearly());
        assert!(PeriodicTransaction::new("Every Year").is_yearly());
        assert!(!PeriodicTransaction::new("Monthly").is_yearly());
    }

    #[test]
    fn is_quarterly() {
        assert!(PeriodicTransaction::new("Quarterly").is_quarterly());
        assert!(PeriodicTransaction::new("Every Quarter").is_quarterly());
        assert!(PeriodicTransaction::new("Every 3 months").is_quarterly());
        assert!(!PeriodicTransaction::new("Monthly").is_quarterly());
    }

    #[test]
    fn is_daily() {
        assert!(PeriodicTransaction::new("Daily").is_daily());
        assert!(PeriodicTransaction::new("Every Day").is_daily());
        assert!(!PeriodicTransaction::new("Monthly").is_daily());
    }

    #[test]
    fn periodic_xact_with_posts() {
        let mut px = PeriodicTransaction::new("Monthly");
        let post1 = Post::with_account_and_amount(
            crate::account::AccountId(1),
            Amount::parse("$500.00").unwrap(),
        );
        let post2 = Post::with_account(crate::account::AccountId(2));
        px.add_post(post1);
        px.add_post(post2);

        assert_eq!(px.posts.len(), 2);
        assert!(px.posts[0].amount.is_some());
        assert!(px.posts[1].amount.is_none());
    }

    #[test]
    fn periodic_xact_debug() {
        let px = PeriodicTransaction::new("Monthly");
        let debug_str = format!("{:?}", px);
        assert!(debug_str.contains("Monthly"));
    }

    #[test]
    fn periodic_xact_clone() {
        let mut px = PeriodicTransaction::new("Weekly");
        px.add_post(Post::new());
        let cloned = px.clone();
        assert_eq!(cloned.period_expr, "Weekly");
        assert_eq!(cloned.posts.len(), 1);
    }
}
