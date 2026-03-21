//! Phase 5 parity validation tests for the Rust port (T-000078).
//!
//! Integration tests covering error handling, edge cases, malformed input,
//! and parser error messages.

use muonledger::amount::Amount;
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
// EMPTY AND MINIMAL INPUT HANDLING
// =========================================================================

mod empty_input_tests {
    use super::*;

    #[test]
    fn empty_string_parses_ok() {
        let journal = parse("");
        assert!(journal.xacts.is_empty());
    }

    #[test]
    fn whitespace_only_parses_ok() {
        let journal = parse("   \n  \n\n   ");
        assert!(journal.xacts.is_empty());
    }

    #[test]
    fn comment_only_parses_ok() {
        let journal = parse("; just a comment\n# another comment\n");
        assert!(journal.xacts.is_empty());
    }

    #[test]
    fn multiple_blank_lines_only() {
        let journal = parse("\n\n\n\n\n");
        assert!(journal.xacts.is_empty());
    }

    #[test]
    fn empty_journal_balance_is_empty() {
        let journal = Journal::new();
        let output = balance_command(&journal, &BalanceOptions::default());
        assert_eq!(output, "");
    }

    #[test]
    fn empty_journal_register_is_empty() {
        let journal = Journal::new();
        let output = register_command(&journal, &RegisterOptions::default());
        assert_eq!(output, "");
    }

    #[test]
    fn single_transaction_minimal() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $1
    Assets:Cash
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn comment_block_only() {
        let journal = parse(
            "\
comment
This is a block comment
end comment
",
        );
        assert!(journal.xacts.is_empty());
    }

    #[test]
    fn mixed_comment_styles() {
        let journal = parse(
            "\
; semicolon comment
# hash comment
% percent comment
| pipe comment
* star comment
",
        );
        assert!(journal.xacts.is_empty());
    }
}

// =========================================================================
// UNBALANCED TRANSACTION DETECTION
// =========================================================================

mod unbalanced_tests {
    use super::*;

    #[test]
    fn unbalanced_explicit_amounts_error() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        assert!(result.is_err(), "unbalanced amounts should error");
    }

    #[test]
    fn unbalanced_error_message_contains_info() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        let err = result.unwrap_err();
        let msg = format!("{}", err);
        assert!(
            msg.contains("balance") || msg.contains("Balance"),
            "error should mention balance: {:?}",
            msg
        );
    }

    #[test]
    fn unbalanced_three_postings_error() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $20.00
    Expenses:Drink      $15.00
    Assets:Checking    $-30.00
",
        );
        assert!(result.is_err(), "unbalanced three postings should error");
    }

    #[test]
    fn balanced_three_postings_ok() {
        let journal = parse(
            "\
2024/01/01 Good
    Expenses:Food       $20.00
    Expenses:Drink      $15.00
    Assets:Checking    $-35.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.xacts[0].posts.len(), 3);
    }

    #[test]
    fn multiple_null_amounts_rejected() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food
    Assets:Checking
",
        );
        assert!(
            result.is_err(),
            "multiple null-amount postings should be rejected"
        );
    }

    #[test]
    fn single_null_amount_inferred() {
        let journal = parse(
            "\
2024/01/01 Good
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let post2 = &journal.xacts[0].posts[1];
        assert!(post2.amount.is_some());
        let amt = post2.amount.as_ref().unwrap();
        assert_eq!(amt.to_string(), "$-50.00");
    }

    #[test]
    fn single_posting_with_amount_is_unbalanced() {
        // A transaction with only one posting (with amount) needs
        // something to balance against.
        let result = try_parse(
            "\
2024/01/01 One Posting
    Expenses:Food       $50.00
",
        );
        // Single posting with an explicit amount cannot balance
        assert!(
            result.is_err(),
            "single posting with amount should be unbalanced"
        );
    }

    #[test]
    fn zero_amount_postings_balanced() {
        let journal = parse(
            "\
2024/01/01 Zero
    Expenses:Food       $0.00
    Assets:Checking     $0.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn large_number_balancing() {
        let journal = parse(
            "\
2024/01/01 Large
    Assets:Savings       $999999.99
    Assets:Checking     $-999999.99
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0");
    }

    #[test]
    fn negative_to_negative_balancing() {
        let journal = parse(
            "\
2024/01/01 Refund
    Assets:Checking      $50.00
    Expenses:Food       $-50.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// PARSER ERROR LINE NUMBERS
// =========================================================================

mod error_line_numbers {
    use super::*;

    #[test]
    fn error_at_first_transaction() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        let err = result.unwrap_err();
        // Error should reference line number
        assert!(err.line_num > 0, "error should have line number");
    }

    #[test]
    fn error_at_later_transaction() {
        let result = try_parse(
            "\
2024/01/01 Good
    Expenses:Food       $42.50
    Assets:Checking

2024/01/02 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        let err = result.unwrap_err();
        // Error should be at line 5 or later
        assert!(
            err.line_num >= 5,
            "error should be at line 5+, got {}",
            err.line_num
        );
    }

    #[test]
    fn error_message_includes_source() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        let err = result.unwrap_err();
        let display = format!("{}", err);
        // ParseError Display format includes source and line number
        assert!(
            display.contains("string") || display.contains("line"),
            "display should include source info"
        );
    }

    #[test]
    fn error_struct_fields_populated() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-10.00
",
        );
        let err = result.unwrap_err();
        assert!(!err.message.is_empty(), "error message should not be empty");
        assert!(err.line_num > 0, "line_num should be > 0");
    }
}

// =========================================================================
// MALFORMED DATE HANDLING
// =========================================================================

mod malformed_dates {
    use super::*;

    #[test]
    fn valid_slash_date() {
        let journal = parse(
            "\
2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn valid_dash_date() {
        let journal = parse(
            "\
2024-01-15 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn single_digit_month_and_day() {
        let journal = parse(
            "\
2024/1/5 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn various_years() {
        for year in &["2020", "2024", "2025", "1999", "2030"] {
            let text = format!(
                "{}/01/01 Test\n    Expenses:Food       $10.00\n    Assets:Checking\n",
                year
            );
            let journal = parse(&text);
            assert_eq!(journal.xacts.len(), 1, "failed for year {}", year);
        }
    }

    #[test]
    fn december_31_date() {
        let journal = parse(
            "\
2024/12/31 Year End
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn february_29_leap_year() {
        let journal = parse(
            "\
2024/02/29 Leap Day
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn january_1_date() {
        let journal = parse(
            "\
2024/01/01 New Year
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// SPECIAL CHARACTER HANDLING
// =========================================================================

mod special_characters {
    use super::*;

    #[test]
    fn payee_with_apostrophe() {
        let journal = parse(
            "\
2024/01/01 McDonald's
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].payee.contains("McDonald's"));
    }

    #[test]
    fn payee_with_hash() {
        let journal = parse(
            "\
2024/01/01 Store #1234
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].payee.contains("#1234"));
    }

    #[test]
    fn payee_with_ampersand() {
        let journal = parse(
            "\
2024/01/01 Ben & Jerry's
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].payee.contains("&"));
    }

    #[test]
    fn payee_with_numbers() {
        let journal = parse(
            "\
2024/01/01 7-Eleven
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].payee.contains("7-Eleven"));
    }

    #[test]
    fn account_with_spaces_in_component() {
        // Accounts can have multi-word components like "Expenses:Dining Out"
        // These are terminated by two spaces or tab before the amount
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Dining Out  $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn long_payee_name() {
        let journal = parse(
            "\
2024/01/01 This Is A Very Long Payee Name That Goes On And On
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.xacts[0].payee.len() > 30);
    }

    #[test]
    fn account_deep_hierarchy() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food:Dining:Restaurant:Italian  $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Italian"), "deep hierarchy account");
    }

    #[test]
    fn transaction_with_inline_note() {
        let journal = parse(
            "\
2024/01/01 Test ; this is a note
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.xacts[0].item.note.is_some());
    }

    #[test]
    fn posting_with_inline_note() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00 ; food expense
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let post = &journal.xacts[0].posts[0];
        assert!(post.item.note.is_some());
    }
}

// =========================================================================
// WHITESPACE AND FORMATTING EDGE CASES
// =========================================================================

mod whitespace_tests {
    use super::*;

    #[test]
    fn tabs_for_indentation() {
        let journal = parse("2024/01/01 Test\n\tExpenses:Food       $10.00\n\tAssets:Checking\n");
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn mixed_tabs_and_spaces() {
        let journal = parse(
            "2024/01/01 Test\n\t  Expenses:Food       $10.00\n  \tAssets:Checking\n",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn many_blank_lines_between_transactions() {
        let journal = parse(
            "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking



2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 2);
    }

    #[test]
    fn trailing_whitespace_on_lines() {
        let journal =
            parse("2024/01/01 Test   \n    Expenses:Food       $10.00   \n    Assets:Checking   \n");
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn no_trailing_newline() {
        let journal = parse("2024/01/01 Test\n    Expenses:Food       $10.00\n    Assets:Checking");
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn windows_line_endings() {
        let journal =
            parse("2024/01/01 Test\r\n    Expenses:Food       $10.00\r\n    Assets:Checking\r\n");
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// AMOUNT PARSING EDGE CASES
// =========================================================================

mod amount_edge_cases {
    use super::*;

    #[test]
    fn integer_amount_no_decimals() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $50
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn amount_with_one_decimal_place() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $50.5
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn very_small_amount() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $0.01
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$0.01"));
    }

    #[test]
    fn negative_amount_with_minus_prefix() {
        let journal = parse(
            "\
2024/01/01 Refund
    Assets:Checking      $50.00
    Expenses:Food       $-50.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn commodity_amount_integer() {
        let journal = parse(
            "\
2024/01/01 Buy
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn commodity_amount_decimal() {
        let journal = parse(
            "\
2024/01/01 Buy
    Assets:Brokerage    10.5 AAPL @ $150.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn amount_parse_unit_dollar() {
        let amt = Amount::parse("$42.50").unwrap();
        assert_eq!(amt.to_double().unwrap(), 42.5);
        assert_eq!(amt.commodity(), Some("$"));
    }

    #[test]
    fn amount_parse_unit_suffix() {
        let amt = Amount::parse("100 EUR").unwrap();
        assert_eq!(amt.to_double().unwrap(), 100.0);
        assert_eq!(amt.commodity(), Some("EUR"));
    }

    #[test]
    fn amount_parse_negative() {
        let amt = Amount::parse("$-42.50").unwrap();
        assert_eq!(amt.to_double().unwrap(), -42.5);
    }

    #[test]
    fn amount_parse_zero() {
        let amt = Amount::parse("$0.00").unwrap();
        assert_eq!(amt.to_double().unwrap(), 0.0);
    }

    #[test]
    fn amount_from_int() {
        let amt = Amount::from_int(0);
        assert!(amt.is_null() || amt.to_double().unwrap() == 0.0);
    }

    #[test]
    fn amount_is_positive() {
        let amt = Amount::parse("$50.00").unwrap();
        assert!(amt.is_positive());
    }

    #[test]
    fn amount_is_negative() {
        let amt = Amount::parse("$-50.00").unwrap();
        assert!(amt.is_negative());
    }

    #[test]
    fn amount_abs() {
        let amt = Amount::parse("$-50.00").unwrap();
        let abs = amt.abs();
        assert!(abs.is_positive() || abs.to_double().unwrap() == 50.0);
    }

    #[test]
    fn amount_negation() {
        let amt = Amount::parse("$50.00").unwrap();
        let neg = -amt;
        assert_eq!(neg.to_double().unwrap(), -50.0);
    }

    #[test]
    fn amount_addition() {
        let a = Amount::parse("$30.00").unwrap();
        let b = Amount::parse("$20.00").unwrap();
        let sum = a + b;
        assert_eq!(sum.to_double().unwrap(), 50.0);
    }

    #[test]
    fn amount_subtraction() {
        let a = Amount::parse("$50.00").unwrap();
        let b = Amount::parse("$20.00").unwrap();
        let diff = a - b;
        assert_eq!(diff.to_double().unwrap(), 30.0);
    }

    #[test]
    fn amount_multiplication() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::parse("5").unwrap();
        let product = &a * &b;
        assert_eq!(product.to_double().unwrap(), 50.0);
    }

    #[test]
    fn amount_display() {
        let amt = Amount::parse("$42.50").unwrap();
        let s = format!("{}", amt);
        assert!(s.contains("42.50"), "display should contain 42.50, got {}", s);
    }
}

// =========================================================================
// METADATA AND TAGS
// =========================================================================

mod metadata_tests {
    use super::*;

    #[test]
    fn transaction_inline_note() {
        let journal = parse(
            "\
2024/01/01 Test ; inline note
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].item.note.is_some());
    }

    #[test]
    fn transaction_note_on_next_line() {
        let journal = parse(
            "\
2024/01/01 Test
    ; note on next line
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        // Note on next line before postings should be attached to xact
        // (implementation may vary; this verifies parsing doesn't fail)
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn posting_inline_note() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00 ; food note
    Assets:Checking
",
        );
        let post = &journal.xacts[0].posts[0];
        assert!(post.item.note.is_some());
    }

    #[test]
    fn posting_note_on_next_line() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    ; note for previous posting
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn metadata_key_value() {
        let journal = parse(
            "\
2024/01/01 Test
    ; Payee: Store
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn tag_line_colon_syntax() {
        let journal = parse(
            "\
2024/01/01 Test
    ; :tag1:tag2:
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// TRANSACTION STATE FLAGS
// =========================================================================

mod state_tests {
    use super::*;
    use muonledger::item::ItemState;

    #[test]
    fn cleared_star() {
        let journal = parse(
            "\
2024/01/01 * Cleared
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Cleared);
    }

    #[test]
    fn pending_exclamation() {
        let journal = parse(
            "\
2024/01/01 ! Pending
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Pending);
    }

    #[test]
    fn uncleared_default() {
        let journal = parse(
            "\
2024/01/01 Uncleared
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Uncleared);
    }

    #[test]
    fn cleared_with_code() {
        let journal = parse(
            "\
2024/01/01 * (1042) Cleared with Code
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Cleared);
        assert_eq!(journal.xacts[0].code.as_deref(), Some("1042"));
    }

    #[test]
    fn pending_with_code() {
        let journal = parse(
            "\
2024/01/01 ! (5555) Pending with Code
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Pending);
        assert_eq!(journal.xacts[0].code.as_deref(), Some("5555"));
    }

    #[test]
    fn multiple_states_in_journal() {
        let journal = parse(
            "\
2024/01/01 * Cleared
    Expenses:Food       $10.00
    Assets:Checking

2024/01/02 ! Pending
    Expenses:Food       $20.00
    Assets:Checking

2024/01/03 Uncleared
    Expenses:Food       $30.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts[0].item.state, ItemState::Cleared);
        assert_eq!(journal.xacts[1].item.state, ItemState::Pending);
        assert_eq!(journal.xacts[2].item.state, ItemState::Uncleared);
    }
}

// =========================================================================
// COMMENT BLOCK HANDLING
// =========================================================================

mod comment_block_tests {
    use super::*;

    #[test]
    fn comment_block_ignored() {
        let journal = parse(
            "\
comment
This is a block comment
end comment

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn comment_block_between_transactions() {
        let journal = parse(
            "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking

comment
Middle comment block
end comment

2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 2);
    }

    #[test]
    fn multiline_comment_block() {
        let journal = parse(
            "\
comment
Line 1
Line 2
Line 3
Line 4
end comment

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn hash_comment_between_transactions() {
        let journal = parse(
            "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking

# Comment between transactions

2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 2);
    }

    #[test]
    fn semicolon_comment_at_file_start() {
        let journal = parse(
            "\
; File header comment
; Author: test

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// REGISTER REPORT EDGE CASES
// =========================================================================

mod register_edge_cases {
    use super::*;

    #[test]
    fn register_single_transaction() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 2, "two postings = two lines");
    }

    #[test]
    fn register_head_zero() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            head: Some(0),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        assert_eq!(output, "", "head 0 should produce no output");
    }

    #[test]
    fn register_head_1() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            head: Some(1),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 1, "head 1 should produce 1 line");
    }

    #[test]
    fn register_tail_1() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            tail: Some(1),
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 1, "tail 1 should produce 1 line");
    }

    #[test]
    fn register_account_filter_no_match() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            account_patterns: vec!["Nonexistent".to_string()],
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        assert_eq!(output, "", "no matching accounts should produce empty output");
    }

    #[test]
    fn register_wide_mode() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            wide: true,
            ..Default::default()
        };
        let output = register_command(&journal, &opts);
        for line in output.lines() {
            assert_eq!(line.len(), 132, "wide mode should be 132 chars");
        }
    }
}

// =========================================================================
// BALANCE REPORT EDGE CASES
// =========================================================================

mod balance_edge_cases {
    use super::*;

    #[test]
    fn balance_no_total_flag() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = BalanceOptions {
            no_total: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(!output.contains("----"), "no_total suppresses separator");
    }

    #[test]
    fn balance_flat_mode() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "flat mode shows full path");
    }

    #[test]
    fn balance_depth_limit() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food:Dining    $10.00
    Assets:Bank:Checking
",
        );
        let opts = BalanceOptions {
            depth: 1,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses"), "depth 1 shows top-level");
        assert!(!output.contains("Dining"), "depth 1 hides sub-accounts");
    }

    #[test]
    fn balance_pattern_filter() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Expenses:Transport  $20.00
    Assets:Checking    $-30.00
",
        );
        let opts = BalanceOptions {
            patterns: vec!["Food".to_string()],
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Food"), "filter shows matched");
        assert!(!output.contains("Transport"), "filter hides unmatched");
    }

    #[test]
    fn balance_case_insensitive_filter() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        let opts = BalanceOptions {
            patterns: vec!["food".to_string()],
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Expenses:Food"), "case-insensitive filter");
    }
}
