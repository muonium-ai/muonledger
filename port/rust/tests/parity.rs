//! Phase 1 parity validation tests for Rust port.
//!
//! These integration tests validate that the Rust port produces correct output
//! for balance and register reports, matching the expected behavior of C++
//! ledger for Phase 1 features.

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

fn try_parse(text: &str) -> Result<Journal, muonledger::parser::ParseError> {
    let mut journal = Journal::new();
    let parser = TextualParser::new();
    parser.parse_string(text, &mut journal)?;
    Ok(journal)
}

// =========================================================================
// FIXTURE: journal text constants
// =========================================================================

/// Simple two-posting transaction.
const SIMPLE_TWO_POSTING: &str = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";

/// Multiple transactions with different accounts.
const MULTI_TRANSACTION: &str = "\
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

/// Multi-account transaction (three-way split).
const THREE_WAY_SPLIT: &str = "\
2024/02/01 Dinner Party
    Expenses:Food:Dining        $60.00
    Expenses:Food:Drinks        $25.00
    Assets:Checking
";

/// Transactions with different commodities (using cost annotation for balance).
const MULTI_COMMODITY: &str = "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/03/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
";

/// Cleared and pending transactions.
const CLEARED_PENDING: &str = "\
2024/04/01 * Cleared Grocery
    Expenses:Food       $30.00
    Assets:Checking

2024/04/02 ! Pending Utility
    Expenses:Utilities  $50.00
    Assets:Checking

2024/04/03 Uncleared Misc
    Expenses:Misc       $10.00
    Assets:Checking
";

/// Transaction with code and note.
const CODE_AND_NOTE: &str = "\
2024/05/01 (1042) Hardware Store ; bought supplies
    Expenses:Home       $120.00
    Assets:Checking
";

/// Journal with comments and blank lines.
const COMMENTS_AND_BLANKS: &str = "\
; This is a comment at the top of the file.
# Another style comment.

2024/06/01 First Transaction
    Expenses:Food       $20.00
    Assets:Checking

; Mid-file comment.

2024/06/15 Second Transaction
    Expenses:Transport  $15.00
    Assets:Checking
";

/// Transfer between asset accounts (zero total).
const INTERNAL_TRANSFER: &str = "\
2024/07/01 Transfer to Savings
    Assets:Savings       $500.00
    Assets:Checking     $-500.00
";

/// Deep account hierarchy.
const DEEP_HIERARCHY: &str = "\
2024/08/01 Dining Out
    Expenses:Food:Dining:Restaurant   $45.00
    Assets:Bank:Checking

2024/08/02 Coffee
    Expenses:Food:Dining:Cafe         $5.00
    Assets:Bank:Checking

2024/08/03 Groceries
    Expenses:Food:Grocery             $60.00
    Assets:Bank:Checking
";

// =========================================================================
// BALANCE REPORT PARITY
// =========================================================================

mod balance_parity {
    use super::*;

    #[test]
    fn simple_two_posting_accounts_shown() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"), "should show Expenses:Food");
        assert!(output.contains("Assets:Checking"), "should show Assets:Checking");
    }

    #[test]
    fn simple_two_posting_amounts_correct() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$42.50"), "Expenses should be $42.50");
        assert!(output.contains("$-42.50"), "Assets should be $-42.50");
    }

    #[test]
    fn simple_two_posting_total_is_zero() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        // Should have separator and total
        assert!(output.contains("--------------------"), "should have separator");
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "total should be zero");
    }

    #[test]
    fn multi_transaction_balance_accumulates() {
        let journal = parse(MULTI_TRANSACTION);
        let output = balance_command(&journal, &BalanceOptions::default());
        // Assets:Bank:Checking = 1000 - 50 - 75 + 2000 = 2875
        assert!(output.contains("$2875.00"), "checking balance should be $2875.00");
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
    fn three_way_split_balance() {
        let journal = parse(THREE_WAY_SPLIT);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$60.00"), "dining should be $60.00");
        assert!(output.contains("$25.00"), "drinks should be $25.00");
        assert!(output.contains("$-85.00"), "checking should be $-85.00");
    }

    #[test]
    fn multi_commodity_balance() {
        let journal = parse(MULTI_COMMODITY);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("100 GBP"), "should show 100 GBP");
        // Checking was auto-balanced: -$220 + -$130 = -$350
        assert!(output.contains("$-350.00"), "checking total should be -$350.00");
    }

    #[test]
    fn internal_transfer_total_zero() {
        let journal = parse(INTERNAL_TRANSFER);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$500.00"), "savings should show $500.00");
        assert!(output.contains("$-500.00"), "checking should show $-500.00");
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "total should be zero for internal transfer");
    }

    #[test]
    fn balance_sorted_alphabetically() {
        let journal = parse(MULTI_TRANSACTION);
        let output = balance_command(&journal, &BalanceOptions::default());
        // In tree mode, top-level accounts should appear alphabetically
        let lines: Vec<&str> = output.lines().collect();
        let account_lines: Vec<&str> = lines
            .iter()
            .filter(|l| !l.starts_with('-') && l.contains("  "))
            .copied()
            .collect();
        // Find positions of top-level accounts
        let assets_pos = account_lines.iter().position(|l| l.contains("Assets"));
        let equity_pos = account_lines.iter().position(|l| l.contains("Equity"));
        let expenses_pos = account_lines.iter().position(|l| l.contains("Expenses"));
        let income_pos = account_lines.iter().position(|l| l.contains("Income"));

        assert!(assets_pos < equity_pos, "Assets before Equity");
        assert!(equity_pos < expenses_pos, "Equity before Expenses");
        assert!(expenses_pos < income_pos, "Expenses before Income");
    }

    // ---- Account hierarchy display ----

    #[test]
    fn hierarchy_collapsing_single_child() {
        // When an account has only one child and no direct postings,
        // tree mode collapses them (e.g. "Equity:Opening" instead of
        // separate Equity and Opening lines).
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = balance_command(&journal, &BalanceOptions::default());
        // Expenses:Food has no siblings and Expenses has no direct postings,
        // so they should be collapsed into one line.
        let expense_lines: Vec<&str> = output
            .lines()
            .filter(|l| l.contains("Expense") || l.contains("Food"))
            .collect();
        assert_eq!(expense_lines.len(), 1, "Expenses:Food should collapse to one line");
    }

    #[test]
    fn hierarchy_no_collapse_with_siblings() {
        let journal = parse(DEEP_HIERARCHY);
        let output = balance_command(&journal, &BalanceOptions::default());
        // Expenses:Food has children Dining and Grocery,
        // so Food should not collapse with its children
        assert!(
            output.contains("Dining") && output.contains("Grocery"),
            "should show both Dining and Grocery children"
        );
    }

    // ---- Depth limiting ----

    #[test]
    fn depth_1_shows_only_top_level() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = BalanceOptions {
            depth: 1,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Assets"), "should show Assets");
        assert!(output.contains("Expenses"), "should show Expenses");
        assert!(output.contains("Income"), "should show Income");
        assert!(!output.contains("Bank"), "should not show Bank sub-account");
        assert!(!output.contains("Food"), "should not show Food sub-account");
        assert!(!output.contains("Salary"), "should not show Salary sub-account");
    }

    #[test]
    fn depth_2_shows_two_levels() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = BalanceOptions {
            depth: 2,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        // Should show up to 2 levels
        assert!(output.contains("Food"), "should show Expenses:Food at depth 2");
        assert!(output.contains("Utilities"), "should show Expenses:Utilities at depth 2");
        // Should NOT show 3-level accounts
        assert!(
            !output.contains("Checking"),
            "should not show Bank:Checking at depth 2 (3 levels)"
        );
    }

    // ---- Filtering by account pattern ----

    #[test]
    fn filter_shows_only_matching() {
        let journal = parse(MULTI_TRANSACTION);
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
    fn filter_flat_mode() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = BalanceOptions {
            flat: true,
            patterns: vec!["Food".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "should show Expenses:Food");
        assert!(!output.contains("Utilities"), "should not show Utilities");
    }

    #[test]
    fn filter_case_insensitive() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let opts = BalanceOptions {
            flat: true,
            patterns: vec!["expenses".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "case-insensitive filter");
    }

    // ---- Total line ----

    #[test]
    fn no_total_suppresses_separator() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let opts = BalanceOptions {
            no_total: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(!output.contains("----"), "no_total should suppress separator");
    }

    // ---- Amount formatting ----

    #[test]
    fn amounts_are_right_aligned() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = balance_command(&journal, &BalanceOptions::default());
        for line in output.lines() {
            if line.starts_with('-') || line.trim() == "0" {
                continue;
            }
            // Lines with account names should have 20-char amount column
            if line.contains("  ") {
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
        assert_eq!(output, "", "empty journal should produce empty output");
    }
}

// =========================================================================
// REGISTER REPORT PARITY
// =========================================================================

mod register_parity {
    use super::*;

    #[test]
    fn simple_two_posting_register() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 2, "two postings should produce two lines");
    }

    #[test]
    fn date_formatting_yy_mon_dd() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("24-Jan-15"), "date should be formatted as YY-Mon-DD");
    }

    #[test]
    fn first_posting_shows_date_and_payee() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        let first_line = output.lines().next().unwrap();
        assert!(first_line.contains("24-Jan-15"), "first posting shows date");
        assert!(first_line.contains("Grocery Store"), "first posting shows payee");
        assert!(first_line.contains("Expenses:Food"), "first posting shows account");
        assert!(first_line.contains("$42.50"), "first posting shows amount");
    }

    #[test]
    fn second_posting_blank_date_and_payee() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let second = lines[1];
        // Date column (10 chars) + payee column (22 chars) should be blank
        assert!(
            second.starts_with("          "),
            "second posting should have blank date"
        );
    }

    #[test]
    fn chronological_ordering() {
        let journal = parse(MULTI_TRANSACTION);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        // Find lines with dates
        let date_lines: Vec<&str> = lines.iter().filter(|l| !l.starts_with(' ')).copied().collect();
        assert!(date_lines.len() >= 4, "should have 4 transactions");
        // Verify chronological order
        assert!(date_lines[0].contains("24-Jan-01"), "first is Jan 01");
        assert!(date_lines[1].contains("24-Jan-05"), "second is Jan 05");
        assert!(date_lines[2].contains("24-Jan-10"), "third is Jan 10");
        assert!(date_lines[3].contains("24-Jan-15"), "fourth is Jan 15");
    }

    #[test]
    fn running_total_accumulates() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        // After first posting ($42.50): running total = $42.50
        assert!(lines[0].contains("$42.50"), "first running total");
        // After second posting ($-42.50): running total = 0
        let last_13: &str = &lines[1][lines[1].len() - 13..];
        assert!(
            last_13.trim() == "0",
            "running total should be 0 after balanced xact, got {:?}",
            last_13
        );
    }

    #[test]
    fn running_total_across_transactions() {
        // The running total accumulates across all displayed postings
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/02 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse(text);
        let opts = RegisterOptions {
            account_patterns: vec!["Assets".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 2, "two Assets postings");
        // First: $1000.00, running total $1000.00
        assert!(lines[0].contains("$1000.00"), "first Assets posting");
        // Second: $-50.00, running total $950.00
        assert!(lines[1].contains("$950.00"), "running total after second");
    }

    #[test]
    fn line_width_80_columns() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        for line in output.lines() {
            assert_eq!(line.len(), 80, "line width should be 80, got {}: {:?}", line.len(), line);
        }
    }

    #[test]
    fn wide_mode_132_columns() {
        let journal = parse(SIMPLE_TWO_POSTING);
        let opts = RegisterOptions {
            wide: true,
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        for line in output.lines() {
            assert_eq!(
                line.len(),
                132,
                "wide line width should be 132, got {}: {:?}",
                line.len(),
                line
            );
        }
    }

    #[test]
    fn account_filter() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = RegisterOptions {
            account_patterns: vec!["Expenses".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        // Should only show Expenses postings
        for line in output.lines() {
            if line.trim().is_empty() {
                continue;
            }
            // Account column starts at position 32 (10 date + 22 payee)
            let account_area = &line[32..54];
            assert!(
                account_area.contains("Expenses") || account_area.trim().is_empty(),
                "should only show Expenses, got: {:?}",
                account_area
            );
        }
    }

    #[test]
    fn head_limit() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = RegisterOptions {
            head: Some(3),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 3, "--head 3 should produce 3 lines");
    }

    #[test]
    fn tail_limit() {
        let journal = parse(MULTI_TRANSACTION);
        let opts = RegisterOptions {
            tail: Some(2),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 2, "--tail 2 should produce 2 lines");
    }

    #[test]
    fn payee_truncation() {
        let text = "\
2024/01/15 This Is A Very Long Payee Name That Should Be Truncated
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains(".."), "long payee should be truncated with ..");
    }

    #[test]
    fn multi_commodity_register() {
        let journal = parse(MULTI_COMMODITY);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("200 EUR"), "should show EUR amount");
        assert!(output.contains("100 GBP"), "should show GBP amount");
    }

    #[test]
    fn three_way_split_register() {
        let journal = parse(THREE_WAY_SPLIT);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        // 3 postings = at least 3 lines (could be more for multi-line totals)
        assert!(lines.len() >= 3, "three-way split should produce 3+ lines");
        // First posting: $60.00
        assert!(lines[0].contains("$60.00"), "first posting amount");
        // Second posting: $25.00, running total $85.00
        assert!(lines[1].contains("$25.00"), "second posting amount");
        assert!(lines[1].contains("$85.00"), "running total after second");
    }

    #[test]
    fn empty_journal_register() {
        let journal = Journal::new();
        let output = register_command(&journal, &RegisterOptions::default());
        assert_eq!(output, "", "empty journal should produce empty register");
    }

    #[test]
    fn december_date_format() {
        let text = "\
2024/12/25 Christmas Shopping
    Expenses:Gifts       $100.00
    Assets:Checking
";
        let journal = parse(text);
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("24-Dec-25"), "December date format");
    }
}

// =========================================================================
// PARSER ROBUSTNESS
// =========================================================================

mod parser_parity {
    use super::*;

    #[test]
    fn comments_and_blank_lines_ignored() {
        let journal = parse(COMMENTS_AND_BLANKS);
        // Should parse 2 transactions successfully
        assert_eq!(journal.xacts.len(), 2, "should parse 2 transactions despite comments");
    }

    #[test]
    fn multiple_transactions_parsed() {
        let journal = parse(MULTI_TRANSACTION);
        assert_eq!(journal.xacts.len(), 4, "should parse 4 transactions");
    }

    #[test]
    fn auto_balanced_transaction() {
        // One posting has no amount -> should be auto-inferred
        let journal = parse(SIMPLE_TWO_POSTING);
        assert_eq!(journal.xacts.len(), 1, "should parse 1 transaction");
        assert_eq!(journal.xacts[0].posts.len(), 2, "should have 2 postings");
        // The second posting should have its amount inferred
        let post2 = &journal.xacts[0].posts[1];
        assert!(post2.amount.is_some(), "inferred posting should have amount");
        let amt = post2.amount.as_ref().unwrap();
        assert_eq!(amt.to_string(), "$-42.50", "inferred amount should be $-42.50");
    }

    #[test]
    fn unbalanced_transaction_errors() {
        let text = "\
2024/01/15 Bad Transaction
    Expenses:Food       $42.50
    Assets:Checking     $-10.00
";
        let result = try_parse(text);
        assert!(result.is_err(), "unbalanced transaction should produce an error");
    }

    #[test]
    fn cleared_transaction_parsed() {
        let journal = parse(CLEARED_PENDING);
        assert_eq!(journal.xacts.len(), 3, "should parse 3 transactions");
        // We can verify the transactions parsed correctly by checking amounts
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$30.00"), "cleared grocery");
        assert!(output.contains("$50.00"), "pending utility");
        assert!(output.contains("$10.00"), "uncleared misc");
    }

    #[test]
    fn code_and_note_parsed() {
        let journal = parse(CODE_AND_NOTE);
        assert_eq!(journal.xacts.len(), 1, "should parse 1 transaction");
        assert_eq!(
            journal.xacts[0].code.as_deref(),
            Some("1042"),
            "transaction code should be parsed"
        );
    }

    #[test]
    fn three_way_split_parsed() {
        let journal = parse(THREE_WAY_SPLIT);
        assert_eq!(journal.xacts.len(), 1, "should parse 1 transaction");
        assert_eq!(journal.xacts[0].posts.len(), 3, "should have 3 postings");
    }

    #[test]
    fn multi_commodity_parsed() {
        let journal = parse(MULTI_COMMODITY);
        assert_eq!(journal.xacts.len(), 2, "should parse 2 transactions");
    }

    #[test]
    fn comment_block_ignored() {
        let text = "\
2024/01/01 Before Comment
    Expenses:Food       $10.00
    Assets:Checking

comment
This is a block comment
that spans multiple lines
end comment

2024/01/02 After Comment
    Expenses:Food       $20.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 2, "comment block should be ignored");
    }

    #[test]
    fn hash_comment_lines_ignored() {
        let text = "\
# This is a hash comment
2024/01/01 Transaction
    Expenses:Food       $10.00
    Assets:Checking
# Another hash comment
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1, "hash comments should be ignored");
    }

    #[test]
    fn multiple_blank_lines_between_transactions() {
        let text = "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking



2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 2, "multiple blank lines should be fine");
    }

    #[test]
    fn explicit_amounts_both_postings() {
        // Both postings have explicit amounts that balance
        let text = "\
2024/01/01 Explicit
    Expenses:Food       $42.50
    Assets:Checking    $-42.50
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1, "should parse with both explicit amounts");
    }

    #[test]
    fn negative_amounts() {
        let text = "\
2024/01/01 Refund
    Assets:Checking      $50.00
    Expenses:Food       $-50.00
";
        let journal = parse(text);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$50.00"), "checking should have $50.00");
        assert!(output.contains("$-50.00"), "food should have $-50.00");
    }

    #[test]
    fn payee_with_special_characters() {
        let text = "\
2024/01/01 McDonald's #1234
    Expenses:Food       $10.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1, "should handle special chars in payee");
        assert!(
            journal.xacts[0].payee.contains("McDonald"),
            "payee should contain McDonald"
        );
    }

    #[test]
    fn date_with_dashes() {
        let text = "\
2024-01-15 Dash Date Format
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1, "should parse dash-separated dates");
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("24-Jan-15"), "date should be correct");
    }
}

// =========================================================================
// CROSS-REPORT CONSISTENCY
// =========================================================================

mod cross_report {
    use super::*;

    #[test]
    fn balance_and_register_agree_on_amounts() {
        let journal = parse(MULTI_TRANSACTION);
        let balance_out = balance_command(&journal, &BalanceOptions::default());
        let register_out = register_command(&journal, &RegisterOptions::default());

        // Both reports should reference the same amounts
        assert!(balance_out.contains("$50.00"), "balance shows $50.00 for food");
        assert!(register_out.contains("$50.00"), "register shows $50.00 for food");
        assert!(balance_out.contains("$75.00"), "balance shows $75.00 for utilities");
        assert!(register_out.contains("$75.00"), "register shows $75.00 for utilities");
    }

    #[test]
    fn balance_total_zero_for_complete_journal() {
        // A fully balanced journal should always have zero total in balance report
        for fixture in &[
            SIMPLE_TWO_POSTING,
            MULTI_TRANSACTION,
            THREE_WAY_SPLIT,
            INTERNAL_TRANSFER,
            CLEARED_PENDING,
            CODE_AND_NOTE,
            COMMENTS_AND_BLANKS,
            DEEP_HIERARCHY,
        ] {
            let journal = parse(fixture);
            let output = balance_command(&journal, &BalanceOptions::default());
            let lines: Vec<&str> = output.trim_end().lines().collect();
            let last = lines.last().unwrap().trim();
            assert_eq!(
                last, "0",
                "total should be zero for balanced journal: {:?}...",
                &fixture[..fixture.len().min(40)]
            );
        }
    }

    #[test]
    fn register_last_running_total_zero_for_unfiltered() {
        // An unfiltered register report over a balanced journal should end with 0
        let journal = parse(SIMPLE_TWO_POSTING);
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last_total_col = &lines.last().unwrap()[67..]; // last 13 chars
        assert_eq!(
            last_total_col.trim(),
            "0",
            "last running total should be 0 for balanced journal"
        );
    }
}
