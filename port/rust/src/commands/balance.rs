//! Balance command -- produces a balance report from a journal.
//!
//! Ported from the Python reference implementation. Given a [`Journal`],
//! accumulates posting amounts into their accounts and renders a formatted
//! balance report.
//!
//! The output format mirrors ledger's default balance format:
//!
//! ```text
//!            $100.00  Assets:Bank:Checking
//!            $-50.00  Expenses:Food
//! --------------------
//!             $50.00
//! ```

use std::collections::{BTreeMap, HashSet};

use crate::balance::Balance;
use crate::journal::Journal;

/// Column width for amounts (right-aligned within this width).
const AMOUNT_WIDTH: usize = 20;

/// Separator line width matches amount column.
fn separator() -> String {
    "-".repeat(AMOUNT_WIDTH)
}

/// Options for the balance command.
#[derive(Debug, Clone)]
pub struct BalanceOptions {
    /// Show flat (non-hierarchical) output.
    pub flat: bool,
    /// Suppress the total line.
    pub no_total: bool,
    /// Show accounts with zero balances.
    pub show_empty: bool,
    /// Limit display depth (0 = unlimited).
    pub depth: usize,
    /// Account name filter patterns (substring match, case-insensitive).
    pub patterns: Vec<String>,
}

impl Default for BalanceOptions {
    fn default() -> Self {
        Self {
            flat: false,
            no_total: false,
            show_empty: false,
            depth: 0,
            patterns: Vec::new(),
        }
    }
}

/// Accumulate per-account (leaf) balances from all transactions.
fn accumulate_balances(journal: &Journal) -> BTreeMap<String, Balance> {
    let mut balances: BTreeMap<String, Balance> = BTreeMap::new();
    for xact in &journal.xacts {
        for post in &xact.posts {
            let amt = match &post.amount {
                Some(a) if !a.is_null() => a,
                _ => continue,
            };
            let account_id = match post.account_id {
                Some(id) => id,
                None => continue,
            };
            let name = journal.accounts.fullname(account_id);
            if name.is_empty() {
                continue;
            }
            let bal = balances.entry(name).or_insert_with(Balance::new);
            bal.add_amount(amt).ok();
        }
    }
    balances
}

/// Roll up leaf balances into all ancestor accounts.
fn roll_up_to_parents(balances: &BTreeMap<String, Balance>) -> BTreeMap<String, Balance> {
    let mut rolled: BTreeMap<String, Balance> = BTreeMap::new();
    for (name, bal) in balances {
        let parts: Vec<&str> = name.split(':').collect();
        for i in 1..=parts.len() {
            let ancestor = parts[..i].join(":");
            let entry = rolled.entry(ancestor).or_insert_with(Balance::new);
            entry.add_balance(bal);
        }
    }
    rolled
}

/// Apply depth limiting: keep only accounts with <= depth segments.
fn apply_depth(rolled: &BTreeMap<String, Balance>, depth: usize) -> BTreeMap<String, Balance> {
    let mut result: BTreeMap<String, Balance> = BTreeMap::new();
    for (name, bal) in rolled {
        let segments = name.split(':').count();
        if segments <= depth {
            result.insert(name.clone(), bal.clone());
        }
    }
    result
}

/// Simple substring match (case-insensitive).
fn matches_pattern(name: &str, patterns: &[String]) -> bool {
    if patterns.is_empty() {
        return true;
    }
    let lower = name.to_lowercase();
    patterns.iter().any(|p| lower.contains(&p.to_lowercase()))
}

/// Return immediate children of `name` from the set of all account names.
fn get_children(name: &str, all_names: &HashSet<String>) -> Vec<String> {
    let prefix = format!("{}:", name);
    let mut children = Vec::new();
    for n in all_names {
        if !n.starts_with(&prefix) {
            continue;
        }
        let rest = &n[prefix.len()..];
        if !rest.contains(':') {
            children.push(n.clone());
        }
    }
    children.sort();
    children
}

/// Account entry for display: (display_name, full_name, balance).
type AccountEntry = (String, String, Balance);

/// Collect accounts for tree (hierarchical) display.
fn collect_tree_accounts(
    rolled: &BTreeMap<String, Balance>,
    leaf_balances: &BTreeMap<String, Balance>,
    show_empty: bool,
    depth: usize,
) -> Vec<AccountEntry> {
    let all_names: HashSet<String> = rolled.keys().cloned().collect();
    let top_level: Vec<String> = {
        let mut tops: Vec<String> = all_names
            .iter()
            .filter(|n| !n.contains(':'))
            .cloned()
            .collect();
        tops.sort();
        tops
    };

    let mut result: Vec<AccountEntry> = Vec::new();

    fn visible_children(
        name: &str,
        all_names: &HashSet<String>,
        rolled: &BTreeMap<String, Balance>,
        show_empty: bool,
    ) -> Vec<String> {
        let children = get_children(name, all_names);
        if !show_empty {
            children
                .into_iter()
                .filter(|c| {
                    rolled
                        .get(c)
                        .map_or(false, |b| b.is_nonzero())
                })
                .collect()
        } else {
            children
        }
    }

    fn has_direct_or_known(name: &str, leaf_balances: &BTreeMap<String, Balance>) -> bool {
        leaf_balances.contains_key(name)
    }

    fn walk(
        name: &str,
        current_depth: usize,
        collapse_prefix: &str,
        indent_depth: usize,
        depth_limit: usize,
        all_names: &HashSet<String>,
        rolled: &BTreeMap<String, Balance>,
        leaf_balances: &BTreeMap<String, Balance>,
        show_empty: bool,
        result: &mut Vec<AccountEntry>,
    ) {
        if depth_limit > 0 && current_depth >= depth_limit {
            return;
        }

        let bal = rolled.get(name).cloned().unwrap_or_else(Balance::new);
        let children = visible_children(name, all_names, rolled, show_empty);

        // Build display name
        let leaf_segment = name.rsplit(':').next().unwrap_or(name);
        let display = if !collapse_prefix.is_empty() {
            format!("{}:{}", collapse_prefix, leaf_segment)
        } else {
            leaf_segment.to_string()
        };

        // Collapse: single child, no direct postings
        if children.len() == 1 && !has_direct_or_known(name, leaf_balances) {
            walk(
                &children[0],
                current_depth,
                &display,
                indent_depth,
                depth_limit,
                all_names,
                rolled,
                leaf_balances,
                show_empty,
                result,
            );
            return;
        }

        // Should we display this account?
        let mut should_show = false;
        if bal.is_nonzero() {
            should_show = true;
        } else if show_empty && has_direct_or_known(name, leaf_balances) {
            should_show = true;
        }

        if !should_show && children.is_empty() {
            return;
        }

        if should_show {
            let indented = format!("{}{}", "  ".repeat(indent_depth), display);
            result.push((indented, name.to_string(), bal));
        }

        for child in &children {
            walk(
                child,
                current_depth + 1,
                "",
                indent_depth + if should_show { 1 } else { 0 },
                depth_limit,
                all_names,
                rolled,
                leaf_balances,
                show_empty,
                result,
            );
        }
    }

    for top in &top_level {
        walk(
            top,
            0,
            "",
            0,
            depth,
            &all_names,
            rolled,
            leaf_balances,
            show_empty,
            &mut result,
        );
    }

    result
}

/// Collect accounts for flat display.
fn flat_accounts(
    leaf_balances: &BTreeMap<String, Balance>,
    patterns: &[String],
    show_empty: bool,
    depth: usize,
) -> Vec<AccountEntry> {
    let mut result: Vec<AccountEntry> = Vec::new();
    for (name, bal) in leaf_balances {
        if !show_empty && !bal.is_nonzero() {
            continue;
        }
        if !patterns.is_empty() && !matches_pattern(name, patterns) {
            continue;
        }
        if depth > 0 && name.split(':').count() > depth {
            continue;
        }
        result.push((name.clone(), name.clone(), bal.clone()));
    }
    result
}

/// Format a Balance into right-aligned amount strings.
fn format_amount_lines(bal: &Balance) -> Vec<String> {
    if bal.is_empty() {
        return vec![format!("{:>width$}", 0, width = AMOUNT_WIDTH)];
    }

    let mut lines: Vec<String> = Vec::new();
    for amt in bal.iter() {
        lines.push(format!("{:>width$}", amt.to_string(), width = AMOUNT_WIDTH));
    }

    if lines.is_empty() {
        lines.push(format!("{:>width$}", 0, width = AMOUNT_WIDTH));
    }

    lines
}

/// Produce a balance report from a journal.
///
/// # Arguments
///
/// * `journal` - The journal containing transactions to report on.
/// * `opts` - Options controlling the report format.
///
/// # Returns
///
/// The formatted balance report as a string.
pub fn balance_command(journal: &Journal, opts: &BalanceOptions) -> String {
    let effective_depth = opts.depth;

    // Step 1: Accumulate per-account (leaf) balances.
    let mut leaf_balances = accumulate_balances(journal);

    // Step 2: Roll up balances to parents.
    let mut rolled = roll_up_to_parents(&leaf_balances);

    // Step 3: Apply depth limiting.
    if effective_depth > 0 {
        rolled = apply_depth(&rolled, effective_depth);
        let mut depth_leaves: BTreeMap<String, Balance> = BTreeMap::new();
        for (name, bal) in &leaf_balances {
            let parts: Vec<&str> = name.split(':').collect();
            let truncated = if parts.len() > effective_depth {
                parts[..effective_depth].join(":")
            } else {
                name.clone()
            };
            let entry = depth_leaves.entry(truncated).or_insert_with(Balance::new);
            entry.add_balance(bal);
        }
        leaf_balances = depth_leaves;
    }

    // Step 4: Determine which accounts to display.
    let accounts = if opts.flat {
        flat_accounts(&leaf_balances, &opts.patterns, opts.show_empty, effective_depth)
    } else {
        let entries = collect_tree_accounts(&rolled, &leaf_balances, opts.show_empty, effective_depth);
        if !opts.patterns.is_empty() {
            filter_tree_by_patterns(&entries, &opts.patterns)
        } else {
            entries
        }
    };

    // Step 5: Render.
    let mut lines: Vec<String> = Vec::new();

    for (display_name, _full_name, bal) in &accounts {
        let amt_lines = format_amount_lines(bal);
        lines.push(format!("{}  {}", amt_lines[0], display_name));
        for extra in &amt_lines[1..] {
            lines.push(extra.clone());
        }
    }

    // Compute grand total from leaf balances.
    let mut grand_total = Balance::new();
    if opts.patterns.is_empty() {
        for bal in leaf_balances.values() {
            grand_total.add_balance(bal);
        }
    } else {
        // When patterns are active, sum only matching accounts.
        if opts.flat {
            for (_display, _full, bal) in &accounts {
                grand_total.add_balance(bal);
            }
        } else {
            for (_display, full, _bal) in &accounts {
                if let Some(leaf_bal) = leaf_balances.get(full) {
                    grand_total.add_balance(leaf_bal);
                }
            }
        }
    }

    // Total line.
    if !opts.no_total && !accounts.is_empty() {
        lines.push(separator());
        if grand_total.is_empty() || grand_total.is_zero() {
            lines.push(format!("{:>width$}", 0, width = AMOUNT_WIDTH));
        } else {
            let total_lines = format_amount_lines(&grand_total);
            for tl in &total_lines {
                lines.push(tl.clone());
            }
        }
    }

    if lines.is_empty() {
        return String::new();
    }

    format!("{}\n", lines.join("\n"))
}

/// Filter tree entries by patterns, keeping ancestors of matching accounts.
fn filter_tree_by_patterns(entries: &[AccountEntry], patterns: &[String]) -> Vec<AccountEntry> {
    let mut matching_full: HashSet<String> = HashSet::new();
    for (_display, full, _bal) in entries {
        if matches_pattern(full, patterns) {
            matching_full.insert(full.clone());
        }
    }

    let mut ancestor_names: HashSet<String> = HashSet::new();
    for full in &matching_full {
        let parts: Vec<&str> = full.split(':').collect();
        for i in 1..parts.len() {
            ancestor_names.insert(parts[..i].join(":"));
        }
    }

    entries
        .iter()
        .filter(|(_display, full, _bal)| {
            matching_full.contains(full) || ancestor_names.contains(full)
        })
        .cloned()
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::amount::Amount;
    use crate::journal::Journal;
    use crate::parser::TextualParser;
    use crate::post::Post;
    use crate::xact::Transaction;

    fn parse_journal(text: &str) -> Journal {
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        parser.parse_string(text, &mut journal).unwrap();
        journal
    }

    // ---- basic tests -------------------------------------------------------

    #[test]
    fn balance_empty_journal() {
        let journal = Journal::new();
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);
        assert_eq!(output, "");
    }

    #[test]
    fn balance_single_transaction() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        assert!(output.contains("$42.50"));
        assert!(output.contains("$-42.50"));
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Assets:Checking"));
        // Total should be zero
        assert!(output.contains("--------------------"));
        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        let last_line = lines.last().unwrap().trim();
        assert_eq!(last_line, "0");
    }

    #[test]
    fn balance_multiple_transactions() {
        let text = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        assert!(output.contains("$950.00"));
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Income:Salary"));
    }

    #[test]
    fn balance_flat_mode() {
        let text = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // Flat mode shows full account names
        assert!(output.contains("Assets:Bank:Checking"));
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Income:Salary"));
    }

    #[test]
    fn balance_no_total() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            no_total: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        assert!(!output.contains("----"));
    }

    #[test]
    fn balance_with_filter() {
        let text = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            patterns: vec!["Expenses".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        assert!(output.contains("Expenses"));
        assert!(!output.contains("Income"));
        assert!(!output.contains("Assets"));
    }

    #[test]
    fn balance_flat_with_filter() {
        let text = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            flat: true,
            patterns: vec!["Assets".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        assert!(output.contains("Assets:Bank:Checking"));
        assert!(!output.contains("Income"));
        assert!(!output.contains("Expenses"));
    }

    #[test]
    fn balance_hierarchical_collapsing() {
        // When an account has only one child and no direct postings,
        // it should be collapsed in tree mode.
        let text = "\
2024/01/15 Test
    Expenses:Food:Dining       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        // "Expenses:Food:Dining" should be collapsed since Expenses and
        // Expenses:Food have no direct postings and only one child each.
        // The display should show "Expenses:Food:Dining" as a collapsed entry.
        assert!(output.contains("Dining"));
    }

    #[test]
    fn balance_depth_limit() {
        let text = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            depth: 1,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // At depth 1, should show only top-level accounts
        assert!(output.contains("Assets"));
        assert!(output.contains("Expenses"));
        assert!(output.contains("Income"));
        // Should NOT show nested accounts
        assert!(!output.contains("Bank:Checking"));
        assert!(!output.contains("Food"));
    }

    #[test]
    fn balance_separator_and_total() {
        let text = "\
2024/01/15 Transfer
    Assets:Savings       $500.00
    Assets:Checking     $-500.00
";
        let journal = parse_journal(text);
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        // The total should be zero since it's a transfer within Assets
        assert!(output.contains("--------------------"));
        let lines: Vec<&str> = output.trim_end().split('\n').collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0");
    }

    #[test]
    fn balance_amount_right_aligned() {
        let text = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        // Check that amounts are right-aligned within AMOUNT_WIDTH
        for line in output.lines() {
            if line.starts_with('-') {
                continue; // separator
            }
            if line.contains("  ") && !line.trim().starts_with("0") {
                // Amount + account name line
                let amount_part = &line[..AMOUNT_WIDTH];
                // Amount should be right-aligned (starts with spaces)
                assert!(
                    amount_part.starts_with(' ') || amount_part.starts_with('$'),
                    "Amount not right-aligned: {:?}",
                    amount_part
                );
            }
        }
    }

    // ---- programmatic journal construction ---------------------------------

    #[test]
    fn balance_programmatic_journal() {
        let mut journal = Journal::new();

        let acct1 = journal.find_account("Expenses:Food", true).unwrap();
        let acct2 = journal.find_account("Assets:Checking", true).unwrap();

        let mut xact = Transaction::with_payee("Grocery Store");
        xact.add_post(Post::with_account_and_amount(
            acct1,
            Amount::parse("$42.50").unwrap(),
        ));
        xact.add_post(Post::with_account(acct2));
        journal.add_xact(xact).unwrap();

        let opts = BalanceOptions::default();
        let output = balance_command(&journal, &opts);

        assert!(output.contains("$42.50"));
        assert!(output.contains("$-42.50"));
    }

    #[test]
    fn balance_case_insensitive_filter() {
        let text = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse_journal(text);
        let opts = BalanceOptions {
            flat: true,
            patterns: vec!["expenses".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"));
    }
}
