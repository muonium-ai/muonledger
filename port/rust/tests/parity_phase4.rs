//! Phase 4 parity validation tests for the Rust port (T-000078).
//!
//! Integration tests covering balance assertions, lot annotations,
//! cost basis tracking, and commodity conversions.

use muonledger::amount::Amount;
use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::print::{print_journal, PrintOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::journal::Journal;
use muonledger::lot::LotAnnotation;
use muonledger::parser::TextualParser;

use chrono::NaiveDate;

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
// LOT ANNOTATION UNIT TESTS
// =========================================================================

mod lot_annotation_tests {
    use super::*;

    #[test]
    fn parse_price_only() {
        let (ann, _) = LotAnnotation::parse("{$150.00}").unwrap();
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert!(!ann.has_tag());
        let price = ann.price.unwrap();
        assert_eq!(price.to_double().unwrap(), 150.0);
    }

    #[test]
    fn parse_date_only() {
        let (ann, _) = LotAnnotation::parse("[2024/03/15]").unwrap();
        assert!(!ann.has_price());
        assert!(ann.has_date());
        assert_eq!(
            ann.date.unwrap(),
            NaiveDate::from_ymd_opt(2024, 3, 15).unwrap()
        );
    }

    #[test]
    fn parse_tag_only() {
        let (ann, _) = LotAnnotation::parse("(initial-buy)").unwrap();
        assert!(!ann.has_price());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("initial-buy"));
    }

    #[test]
    fn parse_price_and_date() {
        let (ann, _) = LotAnnotation::parse("{$150.00} [2024/03/15]").unwrap();
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(!ann.has_tag());
    }

    #[test]
    fn parse_price_and_tag() {
        let (ann, _) = LotAnnotation::parse("{$150.00} (lot1)").unwrap();
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("lot1"));
    }

    #[test]
    fn parse_date_and_tag() {
        let (ann, _) = LotAnnotation::parse("[2024/01/01] (mytag)").unwrap();
        assert!(!ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
    }

    #[test]
    fn parse_all_three() {
        let (ann, _) =
            LotAnnotation::parse("{$150.00} [2024/03/15] (initial purchase)").unwrap();
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("initial purchase"));
    }

    #[test]
    fn parse_fixated_price() {
        let (ann, _) = LotAnnotation::parse("{=$99.50}").unwrap();
        assert!(ann.has_price());
        let price = ann.price.unwrap();
        assert_eq!(price.to_double().unwrap(), 99.5);
    }

    #[test]
    fn parse_date_with_dashes() {
        let (ann, _) = LotAnnotation::parse("[2024-06-30]").unwrap();
        assert!(ann.has_date());
        assert_eq!(
            ann.date.unwrap(),
            NaiveDate::from_ymd_opt(2024, 6, 30).unwrap()
        );
    }

    #[test]
    fn parse_date_with_dots() {
        let (ann, _) = LotAnnotation::parse("[2024.12.25]").unwrap();
        assert!(ann.has_date());
        assert_eq!(
            ann.date.unwrap(),
            NaiveDate::from_ymd_opt(2024, 12, 25).unwrap()
        );
    }

    #[test]
    fn parse_empty_returns_empty_annotation() {
        let (ann, consumed) = LotAnnotation::parse("").unwrap();
        assert!(ann.is_empty());
        assert_eq!(consumed, 0);
    }

    #[test]
    fn parse_non_annotation_text() {
        let (ann, consumed) = LotAnnotation::parse("regular text").unwrap();
        assert!(ann.is_empty());
        assert_eq!(consumed, 0);
    }

    #[test]
    fn unclosed_brace_is_error() {
        let result = LotAnnotation::parse("{$30.00");
        assert!(result.is_err());
    }

    #[test]
    fn unclosed_bracket_is_error() {
        let result = LotAnnotation::parse("[2024-01-01");
        assert!(result.is_err());
    }

    #[test]
    fn unclosed_paren_is_error() {
        let result = LotAnnotation::parse("(tag without close");
        assert!(result.is_err());
    }

    #[test]
    fn display_price_only() {
        let ann = LotAnnotation::with_price(Amount::parse("$150.00").unwrap());
        let s = format!("{}", ann);
        assert!(s.contains("{"));
        assert!(s.contains("}"));
        assert!(s.contains("150"));
    }

    #[test]
    fn display_full_annotation() {
        let date = NaiveDate::from_ymd_opt(2024, 3, 15).unwrap();
        let ann = LotAnnotation::full(Amount::parse("$150.00").unwrap(), date, "lot1");
        let s = format!("{}", ann);
        assert!(s.contains("{"));
        assert!(s.contains("[2024/03/15]"));
        assert!(s.contains("(lot1)"));
    }

    #[test]
    fn display_empty_annotation() {
        let ann = LotAnnotation::new();
        let s = format!("{}", ann);
        assert!(s.is_empty());
    }

    #[test]
    fn equality_same_annotations() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 1).unwrap();
        let a = LotAnnotation::full(Amount::parse("$50.00").unwrap(), date, "lot1");
        let b = LotAnnotation::full(Amount::parse("$50.00").unwrap(), date, "lot1");
        assert_eq!(a, b);
    }

    #[test]
    fn inequality_different_price() {
        let a = LotAnnotation::with_price(Amount::parse("$50.00").unwrap());
        let b = LotAnnotation::with_price(Amount::parse("$60.00").unwrap());
        assert_ne!(a, b);
    }

    #[test]
    fn inequality_different_date() {
        let d1 = NaiveDate::from_ymd_opt(2024, 1, 1).unwrap();
        let d2 = NaiveDate::from_ymd_opt(2024, 1, 2).unwrap();
        let a = LotAnnotation::with_price_and_date(Amount::parse("$50.00").unwrap(), d1);
        let b = LotAnnotation::with_price_and_date(Amount::parse("$50.00").unwrap(), d2);
        assert_ne!(a, b);
    }

    #[test]
    fn inequality_different_tag() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 1).unwrap();
        let a = LotAnnotation::full(Amount::parse("$50.00").unwrap(), date, "lot1");
        let b = LotAnnotation::full(Amount::parse("$50.00").unwrap(), date, "lot2");
        assert_ne!(a, b);
    }

    #[test]
    fn with_price_constructor() {
        let ann = LotAnnotation::with_price(Amount::parse("$42.00").unwrap());
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert!(!ann.has_tag());
    }

    #[test]
    fn with_price_and_date_constructor() {
        let date = NaiveDate::from_ymd_opt(2024, 6, 15).unwrap();
        let ann = LotAnnotation::with_price_and_date(Amount::parse("$42.00").unwrap(), date);
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(!ann.has_tag());
        assert_eq!(ann.date.unwrap(), date);
    }

    #[test]
    fn full_constructor() {
        let date = NaiveDate::from_ymd_opt(2024, 6, 15).unwrap();
        let ann = LotAnnotation::full(Amount::parse("$42.00").unwrap(), date, "tag1");
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("tag1"));
    }

    #[test]
    fn default_is_empty() {
        let ann = LotAnnotation::default();
        assert!(ann.is_empty());
    }
}

// =========================================================================
// COST BASIS AND PRICE CONVERSION TESTS
// =========================================================================

mod cost_and_price_tests {
    use super::*;

    #[test]
    fn per_unit_cost_with_at() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("$-220.00"), "checking should be -$220.00");
    }

    #[test]
    fn total_cost_with_double_at() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @@ $220.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("$-220.00"), "checking should be -$220.00");
    }

    #[test]
    fn multiple_commodity_purchases() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/03/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("200 EUR"), "should show 200 EUR");
        assert!(output.contains("100 GBP"), "should show 100 GBP");
        // Checking: -220 - 130 = -350
        assert!(output.contains("$-350.00"), "checking should be -$350.00");
    }

    #[test]
    fn stock_purchase_with_per_unit_cost() {
        let journal = parse(
            "\
2024/06/01 Buy AAPL
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("10 AAPL"), "should show 10 AAPL");
        assert!(output.contains("$-1500.00"), "checking should be -$1500.00");
    }

    #[test]
    fn stock_purchase_with_total_cost() {
        let journal = parse(
            "\
2024/06/01 Buy AAPL
    Assets:Brokerage    10 AAPL @@ $1500.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("10 AAPL"), "should show 10 AAPL");
        assert!(output.contains("$-1500.00"), "checking should be -$1500.00");
    }

    #[test]
    fn register_shows_cost_conversion() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("200 EUR"), "register should show EUR amount");
    }

    #[test]
    fn register_shows_multiple_commodities() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/03/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("200 EUR"), "register should show EUR");
        assert!(output.contains("100 GBP"), "register should show GBP");
    }

    #[test]
    fn negative_commodity_sale() {
        let journal = parse(
            "\
2024/06/01 Buy AAPL
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking

2024/07/01 Sell AAPL
    Assets:Brokerage   -5 AAPL @ $160.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("5 AAPL"), "should show 5 AAPL remaining");
    }

    #[test]
    fn price_directive_parsed() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00

2024/06/01 Buy AAPL
    Assets:Brokerage    10 AAPL @ $150.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 1, "should have one price entry");
        assert_eq!(journal.prices[0].1, "AAPL");
        assert_eq!(journal.prices[0].2.to_double().unwrap(), 150.0);
    }

    #[test]
    fn multiple_price_directives() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00
P 2024/06/02 AAPL $155.00
P 2024/06/01 EUR $1.10

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 3, "should have three price entries");
    }

    #[test]
    fn price_directive_with_different_date_formats() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00
P 2024-07-01 GOOG $2800.00

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 2);
        assert_eq!(
            journal.prices[0].0,
            NaiveDate::from_ymd_opt(2024, 6, 1).unwrap()
        );
        assert_eq!(
            journal.prices[1].0,
            NaiveDate::from_ymd_opt(2024, 7, 1).unwrap()
        );
    }

    #[test]
    fn balanced_multi_commodity_total_line() {
        // With commodities, the balance total should reflect mixed commodities
        let journal = parse(
            "\
2024/01/01 Opening
    Assets:Bank:Checking     $1000.00
    Equity:Opening
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "total should be zero");
    }
}

// =========================================================================
// BALANCE ASSERTION RELATED TESTS
// =========================================================================

mod balance_assertion_tests {
    use super::*;

    // Note: The parser does not currently implement balance assertion
    // syntax (= AMOUNT after a posting). These tests verify what happens
    // with the = sign in various contexts.

    #[test]
    fn auxiliary_date_with_equals() {
        // Equals sign in transaction header means auxiliary date
        let journal = parse(
            "\
2024/01/15=2024/01/20 Payment
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(
            journal.xacts[0].item.date_aux,
            Some(NaiveDate::from_ymd_opt(2024, 1, 20).unwrap())
        );
    }

    #[test]
    fn auxiliary_date_with_dash_format() {
        let journal = parse(
            "\
2024-01-15=2024-01-20 Payment
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(
            journal.xacts[0].item.date_aux,
            Some(NaiveDate::from_ymd_opt(2024, 1, 20).unwrap())
        );
    }

    #[test]
    fn virtual_posting_parens_does_not_need_balance() {
        // Virtual posting with parentheses does not participate in balancing
        let journal = parse(
            "\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    (Budget:Food)      $-50.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.xacts[0].posts.len(), 3);
    }

    #[test]
    fn balanced_virtual_posting_brackets() {
        // Virtual posting with brackets must balance
        let result = try_parse(
            "\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    [Budget:Food]      $-50.00
",
        );
        // Bracketed virtual must balance -- this adds to the balance check
        // so the overall transaction will have a remainder.
        assert!(result.is_err(), "unbalanced bracketed virtual should error");
    }

    #[test]
    fn virtual_posting_in_register() {
        let journal = parse(
            "\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    (Budget:Food)      $-50.00
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("Budget:Food"), "register should show virtual posting");
    }

    #[test]
    fn multiple_virtual_postings() {
        let journal = parse(
            "\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    (Budget:Food)      $-50.00
    (Tracking:Groceries) $50.00
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.xacts[0].posts.len(), 4);
    }

    #[test]
    fn virtual_posting_balance_report() {
        let journal = parse(
            "\
2024/01/15 Test
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    (Budget:Food)      $-50.00
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Budget:Food"), "balance should show virtual accounts");
    }

    #[test]
    fn cost_with_per_unit_calculated_correctly() {
        // 100 AAPL @ $150 = $15000 cost
        let journal = parse(
            "\
2024/06/01 Buy
    Assets:Brokerage    100 AAPL @ $150.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$-15000.00"), "cost should be 100 * $150 = $15000");
    }

    #[test]
    fn cost_with_total_cost_calculated_correctly() {
        // 100 AAPL @@ $14500 = total cost $14500
        let journal = parse(
            "\
2024/06/01 Buy
    Assets:Brokerage    100 AAPL @@ $14500.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(
            output.contains("$-14500.00"),
            "total cost should be exactly $14500"
        );
    }

    #[test]
    fn explicit_both_amounts_balanced() {
        let journal = parse(
            "\
2024/01/01 Balanced
    Expenses:Food       $42.50
    Assets:Checking    $-42.50
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0");
    }

    #[test]
    fn unbalanced_explicit_amounts_rejected() {
        let result = try_parse(
            "\
2024/01/01 Bad
    Expenses:Food       $42.50
    Assets:Checking    $-40.00
",
        );
        assert!(result.is_err(), "unbalanced transaction should be rejected");
    }
}

// =========================================================================
// COMMODITY AND AMOUNT FORMATTING TESTS
// =========================================================================

mod commodity_formatting_tests {
    use super::*;

    #[test]
    fn prefix_commodity_symbol() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$50.00"), "prefix commodity symbol");
        assert!(output.contains("$-50.00"), "prefix commodity negative");
    }

    #[test]
    fn suffix_commodity_symbol() {
        let journal = parse(
            "\
2024/01/01 Test
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("200 EUR"), "suffix commodity symbol");
    }

    #[test]
    fn zero_amount_display() {
        let journal = parse(
            "\
2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "zero balance total");
    }

    #[test]
    fn large_amounts() {
        let journal = parse(
            "\
2024/01/01 Big Purchase
    Expenses:House       $250000.00
    Assets:Mortgage
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$250000.00"), "large amount display");
    }

    #[test]
    fn negative_prefix_commodity() {
        let journal = parse(
            "\
2024/01/01 Refund
    Assets:Checking      $100.00
    Expenses:Food       $-100.00
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$-100.00"), "negative prefix display");
    }

    #[test]
    fn mixed_commodities_in_balance() {
        let journal = parse(
            "\
2024/01/01 Multi
    Assets:Foreign       100 EUR @ $1.10
    Assets:Foreign        50 GBP @ $1.30
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("EUR"), "should show EUR");
        assert!(output.contains("GBP"), "should show GBP");
        assert!(output.contains("$"), "should show $");
    }

    #[test]
    fn default_commodity_directive() {
        let journal = parse(
            "\
D $1000.00

2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        // Should parse without error, and D directive is consumed
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn commodity_directive() {
        let journal = parse(
            "\
commodity $
commodity EUR

2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// PRINT COMMAND WITH COST/COMMODITY TESTS
// =========================================================================

mod print_cost_tests {
    use super::*;

    #[test]
    fn print_simple_transaction() {
        let journal = parse(
            "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("2024-01-15") || output.contains("2024/01/15"), "print shows date");
        assert!(output.contains("Grocery Store"), "print shows payee");
        assert!(output.contains("Expenses:Food"), "print shows account");
        assert!(output.contains("42.50"), "print shows amount");
    }

    #[test]
    fn print_cost_annotation() {
        let journal = parse(
            "\
2024/03/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("200 EUR"), "print shows commodity amount");
    }

    #[test]
    fn print_multiple_transactions() {
        let journal = parse(
            "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking

2024/01/02 Second
    Expenses:Transport  $20.00
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("First"), "print shows first payee");
        assert!(output.contains("Second"), "print shows second payee");
    }

    #[test]
    fn print_cleared_transaction() {
        let journal = parse(
            "\
2024/01/01 * Cleared Purchase
    Expenses:Food       $30.00
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("*"), "print shows cleared marker");
    }

    #[test]
    fn print_pending_transaction() {
        let journal = parse(
            "\
2024/01/01 ! Pending Purchase
    Expenses:Food       $30.00
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("!"), "print shows pending marker");
    }

    #[test]
    fn print_transaction_with_code() {
        let journal = parse(
            "\
2024/01/01 (1042) Hardware Store
    Expenses:Home       $120.00
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("1042"), "print shows code");
    }

    #[test]
    fn print_empty_journal() {
        let journal = Journal::new();
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.is_empty(), "empty journal should produce empty output");
    }
}
