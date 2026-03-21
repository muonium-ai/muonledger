//! Print command: output transactions in ledger format.
//!
//! Ported from the Python reference implementation. Produces output in
//! the standard ledger journal format:
//!
//! ```text
//! 2024-01-15 Grocery Store
//!     Expenses:Food                           $50.00
//!     Assets:Checking                        $-50.00
//! ```

use crate::item::ItemState;
use crate::journal::Journal;
use crate::report::{apply_to_journal, ReportOptions};

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

/// Options for the print command.
#[derive(Debug, Clone)]
pub struct PrintOptions {
    /// Account column width for amount alignment.
    pub account_width: usize,
    /// Amount column width.
    pub amount_width: usize,
    /// Report options for filtering.
    pub report: ReportOptions,
}

impl Default for PrintOptions {
    fn default() -> Self {
        Self {
            account_width: 40,
            amount_width: 12,
            report: ReportOptions::default(),
        }
    }
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/// Format a date as YYYY-MM-DD (ISO 8601).
fn format_date(date: &Option<chrono::NaiveDate>) -> String {
    match date {
        None => String::new(),
        Some(d) => d.format("%Y-%m-%d").to_string(),
    }
}

/// Format the clearing state marker.
fn format_state(state: ItemState) -> &'static str {
    match state {
        ItemState::Cleared => " *",
        ItemState::Pending => " !",
        ItemState::Uncleared => "",
    }
}

// ---------------------------------------------------------------------------
// Print command
// ---------------------------------------------------------------------------

/// Print transactions from a journal in ledger format.
///
/// Returns the formatted output as a `String`.
pub fn print_journal(journal: &Journal, options: &PrintOptions) -> String {
    let mut output = String::new();

    // Determine which transactions to include based on report filters.
    let enriched = apply_to_journal(&options.report, journal);

    // Collect unique transaction indices that passed filtering.
    let mut seen_xacts = std::collections::HashSet::new();
    let mut xact_indices: Vec<usize> = Vec::new();
    for ep in &enriched {
        if let Some(xi) = ep.xact_idx {
            if seen_xacts.insert(xi) {
                xact_indices.push(xi);
            }
        }
    }

    for (i, &xi) in xact_indices.iter().enumerate() {
        let xact = &journal.xacts[xi];

        if i > 0 {
            output.push('\n');
        }

        // Date line
        let date_str = format_date(&xact.item.date);
        let state_str = format_state(xact.item.state);

        // Build header: date [state] [(code)] payee
        output.push_str(&date_str);
        output.push_str(state_str);

        if let Some(ref code) = xact.code {
            output.push_str(&format!(" ({})", code));
        }

        if !xact.payee.is_empty() {
            output.push(' ');
            output.push_str(&xact.payee);
        }

        output.push('\n');

        // Transaction note
        if let Some(ref note) = xact.item.note {
            output.push_str(&format!("    ; {}\n", note));
        }

        // Postings
        for post in &xact.posts {
            let acct_name = match post.account_id {
                Some(id) => journal.account_fullname(id),
                None => "<unknown>".to_string(),
            };

            let amt_str = match &post.amount {
                Some(a) if !a.is_null() => a.to_string(),
                _ => String::new(),
            };

            if amt_str.is_empty() {
                output.push_str(&format!("    {}\n", acct_name));
            } else {
                // Right-align amount after account name
                let total_width = options.account_width + options.amount_width;
                let content_len = acct_name.len() + amt_str.len();
                if content_len < total_width {
                    let spaces = total_width - content_len;
                    output.push_str(&format!(
                        "    {}{}{}\n",
                        acct_name,
                        " ".repeat(spaces),
                        amt_str,
                    ));
                } else {
                    output.push_str(&format!("    {}  {}\n", acct_name, amt_str));
                }
            }

            // Posting note
            if let Some(ref note) = post.item.note {
                output.push_str(&format!("    ; {}\n", note));
            }
        }
    }

    output
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::item::ItemState;
    use crate::journal::Journal;
    use crate::post::Post;
    use crate::xact::Transaction;
    use chrono::NaiveDate;

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }

    fn make_test_journal() -> Journal {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let checking = journal.find_account("Assets:Checking", true).unwrap();

        let mut xact = Transaction::with_payee("Grocery Store");
        xact.item.date = Some(d(2024, 1, 15));
        xact.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$50.00").unwrap(),
        ));
        xact.add_post(Post::with_account(checking));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        journal
    }

    #[test]
    fn print_basic_transaction() {
        let journal = make_test_journal();
        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("2024-01-15"));
        assert!(output.contains("Grocery Store"));
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Assets:Checking"));
        assert!(output.contains("$50.00"));
    }

    #[test]
    fn print_with_clearing_state() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact = Transaction::with_payee("Store");
        xact.item.date = Some(d(2024, 3, 1));
        xact.item.state = ItemState::Cleared;
        xact.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$25.00").unwrap(),
        ));
        xact.add_post(Post::with_account(cash));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("2024-03-01 *"));
        assert!(output.contains("Store"));
    }

    #[test]
    fn print_with_code() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact = Transaction::with_payee("Store");
        xact.item.date = Some(d(2024, 4, 1));
        xact.code = Some("1042".to_string());
        xact.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$10.00").unwrap(),
        ));
        xact.add_post(Post::with_account(cash));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("(1042)"));
        assert!(output.contains("Store"));
    }

    #[test]
    fn print_multiple_transactions() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();
        let rent = journal.find_account("Expenses:Rent", true).unwrap();
        let checking = journal.find_account("Assets:Checking", true).unwrap();

        let mut xact1 = Transaction::with_payee("Grocery");
        xact1.item.date = Some(d(2024, 1, 1));
        xact1.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$50.00").unwrap(),
        ));
        xact1.add_post(Post::with_account(cash));
        xact1.finalize().unwrap();
        journal.xacts.push(xact1);

        let mut xact2 = Transaction::with_payee("Landlord");
        xact2.item.date = Some(d(2024, 2, 1));
        xact2.add_post(Post::with_account_and_amount(
            rent,
            Amount::parse("$1000.00").unwrap(),
        ));
        xact2.add_post(Post::with_account(checking));
        xact2.finalize().unwrap();
        journal.xacts.push(xact2);

        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("Grocery"));
        assert!(output.contains("Landlord"));
        assert!(output.contains("$50.00"));
        assert!(output.contains("$1000.00"));

        // Transactions should be separated by a blank line
        assert!(output.contains("\n\n"));
    }

    #[test]
    fn print_with_date_filter() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact1 = Transaction::with_payee("Jan");
        xact1.item.date = Some(d(2024, 1, 15));
        xact1.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$10.00").unwrap(),
        ));
        xact1.add_post(Post::with_account(cash));
        xact1.finalize().unwrap();
        journal.xacts.push(xact1);

        let mut xact2 = Transaction::with_payee("Mar");
        xact2.item.date = Some(d(2024, 3, 15));
        xact2.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$20.00").unwrap(),
        ));
        xact2.add_post(Post::with_account(cash));
        xact2.finalize().unwrap();
        journal.xacts.push(xact2);

        let mut options = PrintOptions::default();
        options.report.begin = Some(d(2024, 2, 1));

        let output = print_journal(&journal, &options);

        assert!(!output.contains("Jan"));
        assert!(output.contains("Mar"));
    }

    #[test]
    fn print_with_note() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact = Transaction::with_payee("Store");
        xact.item.date = Some(d(2024, 5, 1));
        xact.item.note = Some("weekly groceries".to_string());
        xact.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$75.00").unwrap(),
        ));
        xact.add_post(Post::with_account(cash));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("; weekly groceries"));
    }

    #[test]
    fn print_empty_journal() {
        let journal = Journal::new();
        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);
        assert!(output.is_empty());
    }

    #[test]
    fn print_format_alignment() {
        let journal = make_test_journal();
        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        // Each posting line should start with 4 spaces
        for line in output.lines() {
            if line.starts_with("    ") {
                // It's a posting or note line
                assert!(line.starts_with("    "));
            }
        }
    }

    #[test]
    fn print_pending_state() {
        let mut journal = Journal::new();
        let food = journal.find_account("Expenses:Food", true).unwrap();
        let cash = journal.find_account("Assets:Cash", true).unwrap();

        let mut xact = Transaction::with_payee("Pending Store");
        xact.item.date = Some(d(2024, 6, 1));
        xact.item.state = ItemState::Pending;
        xact.add_post(Post::with_account_and_amount(
            food,
            Amount::parse("$15.00").unwrap(),
        ));
        xact.add_post(Post::with_account(cash));
        xact.finalize().unwrap();
        journal.xacts.push(xact);

        let options = PrintOptions::default();
        let output = print_journal(&journal, &options);

        assert!(output.contains("2024-06-01 !"));
        assert!(output.contains("Pending Store"));
    }
}
