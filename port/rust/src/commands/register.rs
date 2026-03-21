//! Register command: list postings chronologically with running totals.
//!
//! Ported from the Python reference implementation. Outputs postings in
//! chronological order, showing date, payee, account, amount, and a running
//! total that accumulates across all displayed postings.

use crate::amount::Amount;
use crate::balance::Balance;
use crate::journal::Journal;

// ---------------------------------------------------------------------------
// Column layout constants
// ---------------------------------------------------------------------------

// Default (80-column) layout
const DATE_WIDTH: usize = 10;
const PAYEE_WIDTH: usize = 22;
const ACCOUNT_WIDTH: usize = 22;
const AMOUNT_WIDTH: usize = 13;
const TOTAL_WIDTH: usize = 13;

// Wide (132-column) layout
const WIDE_DATE_WIDTH: usize = 10;
const WIDE_PAYEE_WIDTH: usize = 35;
const WIDE_ACCOUNT_WIDTH: usize = 39;
const WIDE_AMOUNT_WIDTH: usize = 24;
const WIDE_TOTAL_WIDTH: usize = 24;

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

/// Options for the register command.
#[derive(Debug, Clone)]
pub struct RegisterOptions {
    /// Use wide (132-column) layout.
    pub wide: bool,
    /// Limit output to first N postings.
    pub head: Option<usize>,
    /// Limit output to last N postings.
    pub tail: Option<usize>,
    /// Account name filter patterns (substring, case-insensitive).
    pub account_patterns: Vec<String>,
}

impl Default for RegisterOptions {
    fn default() -> Self {
        Self {
            wide: false,
            head: None,
            tail: None,
            account_patterns: Vec::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/// Format a date as YY-Mon-DD (e.g., 24-Jan-01).
fn format_date(date: &Option<chrono::NaiveDate>) -> String {
    match date {
        None => String::new(),
        Some(d) => {
            let months = [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            ];
            let y = d.year() % 100;
            let m = d.month0() as usize;
            let day = d.day();
            format!("{:02}-{}-{:02}", y, months[m], day)
        }
    }
}

/// Truncate text to width, appending ".." if truncated.
fn truncate(text: &str, width: usize) -> String {
    if text.len() <= width {
        return text.to_string();
    }
    if width <= 2 {
        return text[..width].to_string();
    }
    format!("{}..", &text[..width - 2])
}

/// Convert a Balance to display lines, one per commodity.
fn balance_to_lines(bal: &Balance) -> Vec<String> {
    if bal.is_empty() {
        return vec!["0".to_string()];
    }
    let amounts = bal.amounts();
    let mut result: Vec<String> = Vec::new();
    for (_key, amt) in &amounts {
        result.push(amt.to_string());
    }
    if result.is_empty() {
        result.push("0".to_string());
    }
    result
}

/// Format a posting amount as a string.
fn amount_str(amt: &Option<Amount>) -> String {
    match amt {
        None => "0".to_string(),
        Some(a) if a.is_null() => "0".to_string(),
        Some(a) => a.to_string(),
    }
}

/// Check if an account name matches any filter pattern (case-insensitive substring).
fn matches_account(account_fullname: &str, patterns: &[String]) -> bool {
    if patterns.is_empty() {
        return true;
    }
    let lower = account_fullname.to_lowercase();
    patterns.iter().any(|p| lower.contains(&p.to_lowercase()))
}

// ---------------------------------------------------------------------------
// Main command
// ---------------------------------------------------------------------------

use chrono::Datelike;

/// Generate a register report from a journal.
///
/// # Arguments
///
/// * `journal` - A populated journal with transactions and postings.
/// * `opts` - Options controlling output format and filtering.
///
/// # Returns
///
/// The formatted register report as a string.
pub fn register_command(journal: &Journal, opts: &RegisterOptions) -> String {
    let (date_w, payee_w, account_w, amount_w, total_w) = if opts.wide {
        (WIDE_DATE_WIDTH, WIDE_PAYEE_WIDTH, WIDE_ACCOUNT_WIDTH, WIDE_AMOUNT_WIDTH, WIDE_TOTAL_WIDTH)
    } else {
        (DATE_WIDTH, PAYEE_WIDTH, ACCOUNT_WIDTH, AMOUNT_WIDTH, TOTAL_WIDTH)
    };

    let mut rows: Vec<Vec<String>> = Vec::new();
    let mut running_total = Balance::new();

    for xact in &journal.xacts {
        let mut first_in_xact = true;
        for post in &xact.posts {
            let account_id = match post.account_id {
                Some(id) => id,
                None => continue,
            };
            let account_name = journal.accounts.fullname(account_id);

            if !matches_account(&account_name, &opts.account_patterns) {
                continue;
            }

            // Update running total
            if let Some(amt) = &post.amount {
                if !amt.is_null() {
                    running_total.add_amount(amt).ok();
                }
            }

            // Format date and payee (only first posting in xact)
            let (date_str, payee_str) = if first_in_xact {
                first_in_xact = false;
                (
                    format_date(&xact.item.date),
                    truncate(&xact.payee, payee_w - 1),
                )
            } else {
                (String::new(), String::new())
            };

            // Format posting amount
            let amt_str = amount_str(&post.amount);

            // Format running total (may be multi-line)
            let total_lines = balance_to_lines(&running_total);

            // Build output lines
            let mut lines: Vec<String> = Vec::new();

            let date_col = format!("{:<width$}", date_str, width = date_w);
            let payee_col = format!("{:<width$}", payee_str, width = payee_w);
            let account_display = truncate(&account_name, account_w - 1);
            let account_col = format!("{:<width$}", account_display, width = account_w);
            let amount_col = format!("{:>width$}", amt_str, width = amount_w);

            let first_total = total_lines.first().map_or("", |s| s.as_str());
            let total_col = format!("{:>width$}", first_total, width = total_w);

            let first_line = format!("{}{}{}{}{}", date_col, payee_col, account_col, amount_col, total_col);
            lines.push(first_line);

            // Additional total lines (multi-commodity)
            for extra_total in &total_lines[1..] {
                let blank_prefix = " ".repeat(date_w + payee_w + account_w + amount_w);
                lines.push(format!("{}{:>width$}", blank_prefix, extra_total, width = total_w));
            }

            rows.push(lines);
        }
    }

    // Apply --head / --tail
    if let Some(h) = opts.head {
        rows.truncate(h);
    }
    if let Some(t) = opts.tail {
        if t < rows.len() {
            rows = rows.split_off(rows.len() - t);
        }
    }

    // Flatten
    let mut output_lines: Vec<String> = Vec::new();
    for row in &rows {
        output_lines.extend(row.iter().cloned());
    }

    if output_lines.is_empty() {
        return String::new();
    }

    format!("{}\n", output_lines.join("\n"))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::TextualParser;

    fn parse_journal(text: &str) -> Journal {
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        parser.parse_string(text, &mut journal).unwrap();
        journal
    }

    #[test]
    fn register_empty_journal() {
        let journal = Journal::new();
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);
        assert_eq!(output, "");
    }

    #[test]
    fn register_single_transaction() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);

        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 2);
        // First posting shows date and payee
        assert!(lines[0].contains("24-Jan-15"));
        assert!(lines[0].contains("Grocery Store"));
        assert!(lines[0].contains("Expenses:Food"));
        assert!(lines[0].contains("$42.50"));
        // Second posting shows blank date/payee
        assert!(lines[1].starts_with("          "));
        assert!(lines[1].contains("Assets:Checking"));
        assert!(lines[1].contains("$-42.50"));
    }

    #[test]
    fn register_multiple_transactions() {
        let text = "\
2024/01/01 Opening Balance
    Assets:Bank:Checking     $1000.00
    Equity:Opening

2024/01/05 Grocery Store
    Expenses:Food               $42.50
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);

        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 4);
        assert!(lines[0].contains("24-Jan-01"));
        assert!(lines[0].contains("Opening Balance"));
        assert!(lines[2].contains("24-Jan-05"));
        assert!(lines[2].contains("Grocery Store"));
    }

    #[test]
    fn register_line_width_80() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);

        for line in output.lines() {
            assert_eq!(
                line.len(),
                80,
                "Line width should be 80, got {}: {:?}",
                line.len(),
                line
            );
        }
    }

    #[test]
    fn register_wide_mode() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions {
            wide: true,
            ..Default::default()
        };
        let output = register_command(&journal, &opts);

        for line in output.lines() {
            assert_eq!(
                line.len(),
                132,
                "Wide line width should be 132, got {}: {:?}",
                line.len(),
                line
            );
        }
    }

    #[test]
    fn register_running_total() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);

        // The running total accumulates across all postings
        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 4);
        // After first posting: $1000.00
        assert!(lines[0].contains("$1000.00"));
        // After last posting: total should be 0 (balanced journal)
        let last_line = lines.last().unwrap();
        assert!(last_line.ends_with("0") || last_line.trim_end().ends_with("0"));
    }

    #[test]
    fn register_account_filter() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions {
            account_patterns: vec!["Expenses".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);

        // Should only show Expenses postings
        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 1);
        assert!(lines[0].contains("Expenses:Food"));
    }

    #[test]
    fn register_head_limit() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions {
            head: Some(2),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);

        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 2);
    }

    #[test]
    fn register_tail_limit() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions {
            tail: Some(1),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);

        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 1);
    }

    #[test]
    fn register_case_insensitive_filter() {
        let text = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions {
            account_patterns: vec!["expenses".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"));
    }

    #[test]
    fn register_date_format() {
        let text = "\
2024/12/25 Christmas Shopping
    Expenses:Gifts       $100.00
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);
        assert!(output.contains("24-Dec-25"));
    }

    #[test]
    fn register_truncated_payee() {
        let text = "\
2024/01/15 This Is A Very Long Payee Name That Exceeds Width
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = RegisterOptions::default();
        let output = register_command(&journal, &opts);
        // Payee should be truncated with ..
        assert!(output.contains(".."));
    }
}
