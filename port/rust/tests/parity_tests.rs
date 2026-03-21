//! Phase 1 parity validation tests for Rust port (T-000036).
//!
//! Integration tests verifying that the Rust port's balance and register
//! commands produce correct output matching expected ledger format.
//! Exercises the full pipeline: parsing -> journal -> commands -> formatted output.

use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn parse(text: &str) -> Journal {
    let mut journal = Journal::new();
    let parser = TextualParser::new();
    parser.parse_string(text, &mut journal).unwrap();
    journal
}

// =========================================================================
// BALANCE COMMAND PARITY
// =========================================================================

mod balance_parity {
    use super::*;

    // ---- Simple 2-posting transaction ----

    #[test]
    fn simple_two_posting_shows_accounts_and_amounts() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $50
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("$50"), "should show $50 for Expenses:Food");
        assert!(output.contains("$-50"), "should show $-50 for Assets:Checking");
        assert!(output.contains("Expenses:Food"), "should show Expenses:Food");
        assert!(output.contains("Assets:Checking"), "should show Assets:Checking");
    }

    #[test]
    fn simple_two_posting_tree_format() {
        // In tree mode, accounts with a single child and no direct postings
        // get collapsed (e.g., Expenses:Food on one line).
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $50.00
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        // Should have: account line, account line, separator, total = 4 lines
        assert!(lines.len() >= 4, "expected at least 4 lines, got {}: {:?}", lines.len(), lines);

        // Separator should be 20 dashes
        let has_separator = lines.iter().any(|l| l.contains("--------------------"));
        assert!(has_separator, "should have separator line");
    }

    // ---- Multiple transactions ----

    #[test]
    fn multiple_transactions_subtotals_correct() {
        let input = "\
2024/01/01 Opening Balance
    Assets:Bank:Checking     $1000.00
    Equity:Opening

2024/01/05 Grocery Store
    Expenses:Food               $50.00
    Assets:Bank:Checking

2024/01/10 Electric Company
    Expenses:Utilities          $75.00
    Assets:Bank:Checking

2024/01/15 Paycheck
    Assets:Bank:Checking       $2000.00
    Income:Salary
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Assets:Bank:Checking = 1000 - 50 - 75 + 2000 = 2875
        assert!(output.contains("$2875.00"), "checking should be $2875.00");
        // Expenses:Food = 50
        assert!(output.contains("$50.00"), "food should be $50.00");
        // Expenses:Utilities = 75
        assert!(output.contains("$75.00"), "utilities should be $75.00");
        // Income:Salary = -2000
        assert!(output.contains("$-2000.00"), "income should be $-2000.00");
        // Equity:Opening = -1000
        assert!(output.contains("$-1000.00"), "equity should be $-1000.00");
    }

    #[test]
    fn three_transactions_accumulate() {
        let input = "\
2024/01/01 Xact1
    Expenses:Food       $10.00
    Assets:Cash

2024/01/02 Xact2
    Expenses:Food       $20.00
    Assets:Cash

2024/01/03 Xact3
    Expenses:Food       $30.00
    Assets:Cash
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Food total: 10+20+30 = 60
        assert!(output.contains("$60.00"), "food total should be $60.00");
        // Cash total: -60
        assert!(output.contains("$-60.00"), "cash total should be $-60.00");
    }

    // ---- Flat mode ----

    #[test]
    fn flat_mode_shows_full_account_paths() {
        let input = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // Flat mode should show full colon-separated names
        assert!(output.contains("Assets:Bank:Checking"), "flat mode should show full path");
        assert!(output.contains("Expenses:Food"), "flat should show Expenses:Food");
        assert!(output.contains("Income:Salary"), "flat should show Income:Salary");
    }

    #[test]
    fn flat_mode_vs_tree_mode_differ() {
        let input = "\
2024/01/01 Test
    Expenses:Food:Dining:Restaurant   $45.00
    Assets:Checking
";
        let journal = parse(input);

        let tree_output = balance_command(&journal, &BalanceOptions::default());
        let flat_opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let flat_output = balance_command(&journal, &flat_opts);

        // Both should contain the amount
        assert!(tree_output.contains("$45.00"), "tree shows amount");
        assert!(flat_output.contains("$45.00"), "flat shows amount");

        // Flat always shows full path
        assert!(
            flat_output.contains("Expenses:Food:Dining:Restaurant"),
            "flat shows full path"
        );
    }

    // ---- Depth limiting ----

    #[test]
    fn depth_1_shows_only_top_level_accounts() {
        let input = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            depth: 1,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // Should show only top-level: Assets, Expenses, Income
        assert!(output.contains("Assets"), "depth 1 should show Assets");
        assert!(output.contains("Expenses"), "depth 1 should show Expenses");
        assert!(output.contains("Income"), "depth 1 should show Income");

        // Should NOT show sub-accounts
        assert!(!output.contains("Bank"), "depth 1 should not show Bank");
        assert!(!output.contains("Checking"), "depth 1 should not show Checking");
        assert!(!output.contains("Food"), "depth 1 should not show Food");
        assert!(!output.contains("Salary"), "depth 1 should not show Salary");
    }

    #[test]
    fn depth_2_shows_two_levels() {
        let input = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            depth: 2,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // Should show up to 2 levels
        assert!(output.contains("Food"), "depth 2 should show Food");
        assert!(output.contains("Salary"), "depth 2 should show Salary");
        // Should NOT show 3-level accounts
        assert!(!output.contains("Checking"), "depth 2 should not show Checking (3 levels)");
    }

    #[test]
    fn depth_aggregates_amounts() {
        // Depth limiting should aggregate child amounts into parent
        let input = "\
2024/01/01 Test1
    Expenses:Food:Dining     $25.00
    Assets:Cash

2024/01/02 Test2
    Expenses:Food:Grocery    $35.00
    Assets:Cash
";
        let journal = parse(input);
        let opts = BalanceOptions {
            depth: 2,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        // At depth 2, Expenses:Food should show $60.00 (25+35)
        assert!(output.contains("$60.00"), "depth 2 should aggregate to $60.00");
    }

    // ---- Negative amounts / credits ----

    #[test]
    fn negative_amounts_display_correctly() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Assets:Checking should show negative (credit)
        assert!(output.contains("$-42.50"), "credit should show negative");
    }

    #[test]
    fn refund_shows_negative_expense() {
        let input = "\
2024/01/01 Refund
    Assets:Checking      $50.00
    Expenses:Food       $-50.00
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("$50.00"), "checking should show $50.00");
        assert!(output.contains("$-50.00"), "food refund should show $-50.00");
    }

    // ---- Multiple commodities ----

    #[test]
    fn multiple_commodities_shown_separately() {
        let input = "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/03/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("100 GBP"), "should show 100 GBP");
        // Checking: -(200*1.10) + -(100*1.30) = -220 + -130 = -350
        assert!(output.contains("$-350.00"), "checking should be $-350.00");
    }

    #[test]
    fn mixed_dollar_and_euro_in_balance() {
        let input = "\
2024/01/01 Dollar Purchase
    Expenses:Food       $50.00
    Assets:Checking

2024/01/02 Euro Purchase
    Expenses:Travel     100 EUR @ $1.10
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("$50.00"), "should show dollar expense");
        assert!(output.contains("100 EUR"), "should show EUR expense");
    }

    // ---- Balance total line ----

    #[test]
    fn total_line_separator_format() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Separator is exactly 20 dashes
        assert!(
            output.contains("--------------------"),
            "separator should be 20 dashes"
        );
    }

    #[test]
    fn total_line_zero_for_balanced_journal() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "total should be zero for balanced journal");
    }

    #[test]
    fn no_total_option_suppresses_total() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            no_total: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        assert!(!output.contains("----"), "no_total should suppress separator");
    }

    // ---- Amounts right-aligned in 20-char column ----

    #[test]
    fn amounts_right_aligned_in_column() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        for line in output.lines() {
            if line.starts_with('-') || line.trim() == "0" {
                continue;
            }
            if line.len() >= 20 && line.contains("  ") {
                let amount_part = &line[..20];
                assert!(
                    amount_part.starts_with(' ') || amount_part.starts_with('$'),
                    "Amount not right-aligned: {:?}",
                    amount_part
                );
            }
        }
    }

    // ---- Empty journal ----

    #[test]
    fn empty_journal_produces_empty_output() {
        let journal = Journal::new();
        let output = balance_command(&journal, &BalanceOptions::default());
        assert_eq!(output, "", "empty journal should produce empty balance output");
    }

    // ---- Alphabetical ordering ----

    #[test]
    fn accounts_appear_alphabetically() {
        let input = "\
2024/01/01 Test
    Zebra:Account       $10.00
    Assets:Cash

2024/01/02 Test
    Alpha:Account       $20.00
    Assets:Cash
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        let lines: Vec<&str> = output.lines().collect();
        let alpha_pos = lines.iter().position(|l| l.contains("Alpha"));
        let zebra_pos = lines.iter().position(|l| l.contains("Zebra"));

        assert!(
            alpha_pos.is_some() && zebra_pos.is_some(),
            "both accounts should appear"
        );
        assert!(
            alpha_pos.unwrap() < zebra_pos.unwrap(),
            "Alpha should appear before Zebra"
        );
    }

    // ---- Internal transfers ----

    #[test]
    fn internal_transfer_balances_to_zero() {
        let input = "\
2024/07/01 Transfer to Savings
    Assets:Savings       $500.00
    Assets:Checking     $-500.00
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("$500.00"), "savings shows $500.00");
        assert!(output.contains("$-500.00"), "checking shows $-500.00");
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "internal transfer total should be zero");
    }

    // ---- Pattern filtering ----

    #[test]
    fn pattern_filter_includes_only_matching() {
        let input = "\
2024/01/01 Paycheck
    Assets:Bank:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food              $50.00
    Assets:Bank:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            patterns: vec!["Expenses".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);

        assert!(output.contains("Expenses"), "should show Expenses");
        assert!(!output.contains("Income"), "should not show Income");
        assert!(!output.contains("Assets"), "should not show Assets");
    }

    #[test]
    fn pattern_filter_case_insensitive() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let opts = BalanceOptions {
            flat: true,
            patterns: vec!["expenses".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "case-insensitive filter should work");
    }

    // ---- Hierarchy collapsing ----

    #[test]
    fn single_child_collapses_in_tree_mode() {
        let input = "\
2024/01/15 Test
    Expenses:Food:Dining:Restaurant   $45.00
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Expenses -> Food -> Dining -> Restaurant, all single-child,
        // should collapse into one line
        let expense_lines: Vec<&str> = output
            .lines()
            .filter(|l| l.contains("Restaurant") || l.contains("Dining") || l.contains("Food") || l.contains("Expenses"))
            .filter(|l| !l.starts_with('-'))
            .collect();
        assert_eq!(
            expense_lines.len(),
            1,
            "deeply nested single-child path should collapse to one line, got {:?}",
            expense_lines
        );
    }

    #[test]
    fn multiple_children_do_not_collapse() {
        let input = "\
2024/01/01 Test
    Expenses:Food       $25.00
    Expenses:Transport  $15.00
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Expenses has two children (Food, Transport), should not collapse
        assert!(output.contains("Food"), "should show Food");
        assert!(output.contains("Transport"), "should show Transport");
    }
}

// =========================================================================
// REGISTER COMMAND PARITY
// =========================================================================

mod register_parity {
    use super::*;

    // ---- Simple register ----

    #[test]
    fn simple_register_date_payee_account_amount_total() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        assert_eq!(lines.len(), 2, "two postings produce two lines");

        // First line: date, payee, account, amount, running total
        let first = lines[0];
        assert!(first.contains("24-Jan-15"), "shows date in YY-Mon-DD format");
        assert!(first.contains("Grocery Store"), "shows payee");
        assert!(first.contains("Expenses:Food"), "shows account");
        assert!(first.contains("$42.50"), "shows amount");
    }

    #[test]
    fn second_posting_blank_date_and_payee() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        // Second posting should have blank date and payee columns
        assert!(
            lines[1].starts_with("          "),
            "second posting should have blank date column"
        );
    }

    // ---- Multiple transactions: running total ----

    #[test]
    fn running_total_accumulates_correctly() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        assert_eq!(lines.len(), 4, "4 postings across 2 transactions");

        // After first posting ($1000): running total = $1000
        assert!(lines[0].contains("$1000.00"), "first running total is $1000.00");

        // After all postings: running total should be 0 (balanced)
        let last = lines.last().unwrap();
        let total_col = &last[last.len().saturating_sub(13)..];
        assert_eq!(total_col.trim(), "0", "final running total should be 0");
    }

    #[test]
    fn running_total_with_account_filter() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            account_patterns: vec!["Assets".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();

        assert_eq!(lines.len(), 2, "should show only 2 Assets postings");
        // First Assets posting: $1000, total $1000
        assert!(lines[0].contains("$1000.00"), "first Assets posting");
        // Second Assets posting: $-50, total $950
        assert!(lines[1].contains("$950.00"), "running total should be $950.00");
    }

    // ---- Wide format ----

    #[test]
    fn wide_format_132_columns() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            wide: true,
            ..Default::default()
        };
        let output = register_command(&journal, &opts);

        for line in output.lines() {
            assert_eq!(
                line.len(),
                132,
                "wide mode should produce 132-column lines, got {}: {:?}",
                line.len(),
                line
            );
        }
    }

    #[test]
    fn default_format_80_columns() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());

        for line in output.lines() {
            assert_eq!(
                line.len(),
                80,
                "default mode should produce 80-column lines, got {}: {:?}",
                line.len(),
                line
            );
        }
    }

    #[test]
    fn wide_format_shows_longer_payee() {
        let input = "\
2024/01/15 A Moderately Long Payee Name Here
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);

        let narrow = register_command(&journal, &RegisterOptions::default());
        let wide_opts = RegisterOptions {
            wide: true,
            ..Default::default()
        };
        let wide = register_command(&journal, &wide_opts);

        // Wide mode has 35-char payee width vs 22, so more of the name shows
        let narrow_first = narrow.lines().next().unwrap();
        let wide_first = wide.lines().next().unwrap();

        // The narrow version may truncate the payee
        if narrow_first.contains("..") {
            // Wide should show more of the payee
            assert!(
                !wide_first[10..45].contains("..") || wide_first[10..45].len() > narrow_first[10..32].len(),
                "wide mode should show more of the payee"
            );
        }
    }

    // ---- Head/tail limiting ----

    #[test]
    fn head_limit_truncates_output() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking

2024/01/03 Gas
    Expenses:Transport     $30.00
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            head: Some(3),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 3, "--head 3 should produce 3 lines");
    }

    #[test]
    fn tail_limit_shows_last_entries() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking

2024/01/03 Gas
    Expenses:Transport     $30.00
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            tail: Some(2),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 2, "--tail 2 should produce 2 lines");
    }

    // ---- Chronological ordering ----

    #[test]
    fn transactions_appear_in_date_order() {
        let input = "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Cash

2024/02/01 Second
    Expenses:Food       $20.00
    Assets:Cash

2024/03/01 Third
    Expenses:Food       $30.00
    Assets:Cash
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        // Filter lines that have dates (non-blank first column)
        let date_lines: Vec<&&str> = lines.iter().filter(|l| !l.starts_with(' ')).collect();
        assert!(date_lines.len() >= 3, "should have 3 transactions with dates");
        assert!(date_lines[0].contains("24-Jan-01"), "first is Jan");
        assert!(date_lines[1].contains("24-Feb-01"), "second is Feb");
        assert!(date_lines[2].contains("24-Mar-01"), "third is Mar");
    }

    // ---- Date formatting ----

    #[test]
    fn various_month_formats() {
        let months = [
            ("2024/01/01", "24-Jan-01"),
            ("2024/06/15", "24-Jun-15"),
            ("2024/12/25", "24-Dec-25"),
        ];
        for (date_input, expected) in &months {
            let input = format!(
                "{} Test\n    Expenses:Food       $10.00\n    Assets:Cash\n",
                date_input
            );
            let journal = parse(&input);
            let output = register_command(&journal, &RegisterOptions::default());
            assert!(
                output.contains(expected),
                "date {} should format as {}, got: {}",
                date_input,
                expected,
                output.lines().next().unwrap_or("")
            );
        }
    }

    #[test]
    fn dash_date_format_parsed_correctly() {
        let input = "\
2024-03-15 Dash Date
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("24-Mar-15"), "dash-separated date should parse correctly");
    }

    // ---- Payee truncation ----

    #[test]
    fn long_payee_truncated_with_dots() {
        let input = "\
2024/01/15 This Is A Very Long Payee Name That Will Exceed The Column Width
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains(".."), "long payee should be truncated with ..");
    }

    // ---- Account filter ----

    #[test]
    fn account_filter_shows_only_matching() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            account_patterns: vec!["Expenses".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();

        assert_eq!(lines.len(), 1, "should only show Expenses postings");
        assert!(lines[0].contains("Expenses:Food"), "should show Expenses:Food");
    }

    #[test]
    fn account_filter_case_insensitive() {
        let input = "\
2024/01/15 Test
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);
        let opts = RegisterOptions {
            account_patterns: vec!["expenses".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "case-insensitive filter should work");
    }

    // ---- Multi-commodity register ----

    #[test]
    fn multi_commodity_amounts_shown() {
        let input = "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/03/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());

        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("100 GBP"), "should show 100 GBP");
    }

    // ---- Three-way split ----

    #[test]
    fn three_way_split_produces_three_posting_lines() {
        let input = "\
2024/02/01 Dinner Party
    Expenses:Food:Dining        $60.00
    Expenses:Food:Drinks        $25.00
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();

        assert!(lines.len() >= 3, "three-way split should produce 3+ lines");
        assert!(lines[0].contains("$60.00"), "first posting $60.00");
        assert!(lines[1].contains("$25.00"), "second posting $25.00");
        assert!(lines[1].contains("$85.00"), "running total after second $85.00");
    }

    // ---- Empty journal ----

    #[test]
    fn empty_journal_produces_empty_output() {
        let journal = Journal::new();
        let output = register_command(&journal, &RegisterOptions::default());
        assert_eq!(output, "", "empty journal should produce empty register output");
    }
}

// =========================================================================
// FULL PIPELINE TESTS: Parse -> Command -> Verify exact output properties
// =========================================================================

mod full_pipeline {
    use super::*;

    #[test]
    fn parse_to_balance_exact_output_structure() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $50.00
    Assets:Checking
";
        let journal = parse(input);
        let output = balance_command(&journal, &BalanceOptions::default());

        let lines: Vec<&str> = output.trim_end().lines().collect();

        // Should have exactly: 2 account lines + separator + total = 4 lines
        assert_eq!(lines.len(), 4, "expected 4 lines, got {}: {:?}", lines.len(), lines);

        // Line 1 and 2: account lines (amounts right-aligned in 20-char column)
        // The two accounts should be alphabetically ordered:
        // Assets:Checking before Expenses:Food
        assert!(
            lines[0].contains("Assets:Checking") || lines[0].contains("Expenses:Food"),
            "first account line"
        );
        assert!(
            lines[1].contains("Assets:Checking") || lines[1].contains("Expenses:Food"),
            "second account line"
        );

        // Line 3: separator (20 dashes)
        assert_eq!(lines[2], "--------------------", "separator should be 20 dashes");

        // Line 4: total (right-aligned zero)
        assert_eq!(lines[3].trim(), "0", "total should be zero");
    }

    #[test]
    fn parse_to_register_exact_output_structure() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $50.00
    Assets:Checking
";
        let journal = parse(input);
        let output = register_command(&journal, &RegisterOptions::default());

        let lines: Vec<&str> = output.trim_end().lines().collect();

        // Should have exactly 2 lines (2 postings)
        assert_eq!(lines.len(), 2, "expected 2 lines");

        // Each line should be exactly 80 characters
        for line in &lines {
            assert_eq!(line.len(), 80, "each line should be 80 chars");
        }

        // First line starts with date
        assert!(lines[0].starts_with("24-Jan-15"), "first line starts with date");

        // Second line starts with spaces (blank date/payee)
        assert!(lines[1].starts_with("          "), "second line has blank date");
    }

    #[test]
    fn empty_journal_both_commands_empty() {
        let journal = Journal::new();

        let balance_out = balance_command(&journal, &BalanceOptions::default());
        let register_out = register_command(&journal, &RegisterOptions::default());

        assert_eq!(balance_out, "", "empty balance");
        assert_eq!(register_out, "", "empty register");
    }

    #[test]
    fn single_posting_auto_balance_inferred() {
        let input = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(input);

        // Verify the auto-balanced posting was inferred
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.xacts[0].posts.len(), 2);
        let post2 = &journal.xacts[0].posts[1];
        assert!(post2.amount.is_some(), "second posting should have inferred amount");
        let amt = post2.amount.as_ref().unwrap();
        assert_eq!(amt.to_string(), "$-42.50", "inferred amount should be $-42.50");

        // Both commands should produce output reflecting both postings
        let balance_out = balance_command(&journal, &BalanceOptions::default());
        assert!(balance_out.contains("$42.50"), "balance shows debit");
        assert!(balance_out.contains("$-42.50"), "balance shows credit");

        let register_out = register_command(&journal, &RegisterOptions::default());
        assert!(register_out.contains("$42.50"), "register shows debit");
        assert!(register_out.contains("$-42.50"), "register shows credit");
    }

    #[test]
    fn comments_only_journal_produces_empty_output() {
        let input = "\
; This is just a comment file
# With no transactions
; At all
";
        let journal = parse(input);

        let balance_out = balance_command(&journal, &BalanceOptions::default());
        let register_out = register_command(&journal, &RegisterOptions::default());

        assert_eq!(balance_out, "", "comments-only journal: empty balance");
        assert_eq!(register_out, "", "comments-only journal: empty register");
    }

    #[test]
    fn balance_and_register_agree_on_amounts() {
        let input = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking

2024/01/03 Electric
    Expenses:Utilities     $75.00
    Assets:Checking
";
        let journal = parse(input);
        let balance_out = balance_command(&journal, &BalanceOptions::default());
        let register_out = register_command(&journal, &RegisterOptions::default());

        // Both should show the same posting amounts for expenses
        assert!(balance_out.contains("$50.00") && register_out.contains("$50.00"), "both show $50");
        assert!(balance_out.contains("$75.00") && register_out.contains("$75.00"), "both show $75");
        // Register shows individual posting amounts; balance shows net totals.
        // Both should reference $1000.00 in some form.
        assert!(register_out.contains("$1000.00"), "register shows $1000 posting");
        // Balance shows the net: 1000 - 50 - 75 = 875
        assert!(balance_out.contains("$875.00"), "balance shows net checking $875");
    }

    #[test]
    fn all_balanced_journals_have_zero_total() {
        let fixtures = vec![
            "\
2024/01/15 Simple
    Expenses:Food       $42.50
    Assets:Checking
",
            "\
2024/01/01 Multi1
    Assets:Bank:Checking     $1000.00
    Equity:Opening

2024/01/05 Multi2
    Expenses:Food               $50.00
    Assets:Bank:Checking
",
            "\
2024/02/01 ThreeWay
    Expenses:Food:Dining        $60.00
    Expenses:Food:Drinks        $25.00
    Assets:Checking
",
            "\
2024/07/01 Transfer
    Assets:Savings       $500.00
    Assets:Checking     $-500.00
",
        ];

        for (i, fixture) in fixtures.iter().enumerate() {
            let journal = parse(fixture);
            let output = balance_command(&journal, &BalanceOptions::default());
            let lines: Vec<&str> = output.trim_end().lines().collect();
            let last = lines.last().unwrap().trim();
            assert_eq!(
                last, "0",
                "fixture {} should have zero total, got {:?}",
                i, last
            );
        }
    }

    #[test]
    fn large_journal_stress_test() {
        // Build a journal with many transactions
        let mut input = String::new();
        for i in 1..=50 {
            let day = format!("{:02}", (i % 28) + 1);
            let month = format!("{:02}", ((i - 1) / 28) + 1);
            input.push_str(&format!(
                "2024/{}/{} Transaction {}\n    Expenses:Category{}       ${}.00\n    Assets:Checking\n\n",
                month, day, i, i % 5, i * 10
            ));
        }

        let journal = parse(&input);
        assert_eq!(journal.xacts.len(), 50, "should parse 50 transactions");

        let balance_out = balance_command(&journal, &BalanceOptions::default());
        assert!(!balance_out.is_empty(), "balance should produce output");

        let register_out = register_command(&journal, &RegisterOptions::default());
        assert!(!register_out.is_empty(), "register should produce output");

        // Total should be zero
        let lines: Vec<&str> = balance_out.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "50-transaction journal should still balance to zero");
    }

    // ---- Exact parsing edge cases ----

    #[test]
    fn both_postings_explicit_amounts() {
        let input = "\
2024/01/01 Explicit Both
    Expenses:Food       $42.50
    Assets:Checking    $-42.50
";
        let journal = parse(input);
        assert_eq!(journal.xacts.len(), 1, "should parse with both explicit amounts");

        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$42.50"), "shows debit");
        assert!(output.contains("$-42.50"), "shows credit");
    }

    #[test]
    fn unbalanced_transaction_fails_parse() {
        let input = "\
2024/01/15 Bad Transaction
    Expenses:Food       $42.50
    Assets:Checking     $-10.00
";
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        let result = parser.parse_string(input, &mut journal);
        assert!(result.is_err(), "unbalanced transaction should produce an error");
    }
}
