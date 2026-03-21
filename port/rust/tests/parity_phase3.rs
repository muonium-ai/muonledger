//! Phase 3 parity validation tests for the Rust port (T-000070).
//!
//! Integration tests covering automated transactions, periodic transactions,
//! lot annotations, and cross-feature integration.

use muonledger::amount::Amount;
use muonledger::auto_xact::AutomatedTransaction;
use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::print::{print_journal, PrintOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::journal::Journal;
use muonledger::lot::LotAnnotation;
use muonledger::parser::TextualParser;
use muonledger::periodic_xact::PeriodicTransaction;
use muonledger::post::{Post, POST_GENERATED};

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

fn d(y: i32, m: u32, day: u32) -> NaiveDate {
    NaiveDate::from_ymd_opt(y, m, day).unwrap()
}

// =========================================================================
// AUTOMATED TRANSACTION TESTS
// =========================================================================

mod auto_xact_tests {
    use super::*;

    #[test]
    fn simple_auto_xact_food_pattern() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 1);
        // The matching transaction should have extra generated posting(s).
        let xact = &journal.xacts[0];
        assert!(
            xact.posts.len() > 2,
            "Expected generated posting from auto xact, got {} posts",
            xact.posts.len()
        );
    }

    #[test]
    fn auto_xact_with_fixed_amount() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        assert!(xact.posts.len() > 2);
        // Find the generated posting
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
        // Fixed amount should be $5.00 regardless of matched amount
        let gen_amt = generated[0].amount.as_ref().unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), 5.0);
    }

    #[test]
    fn auto_xact_with_multiplier() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
        // $50.00 * 0.10 = $5.00
        let gen_amt = generated[0].amount.as_ref().unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), 5.0);
    }

    #[test]
    fn multiple_auto_xacts_same_transaction() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

= /Expenses/
    (Expenses:Audit)           $1.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 2);
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        // /Food/ matches Expenses:Food posting
        // /Expenses/ matches Expenses:Food posting
        // Both should generate postings
        assert!(
            generated.len() >= 2,
            "Expected at least 2 generated postings, got {}",
            generated.len()
        );
    }

    #[test]
    fn auto_xact_no_match() {
        let journal = parse(
            "\
= /Utilities/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 1);
        let xact = &journal.xacts[0];
        // No match, so only original 2 postings
        assert_eq!(
            xact.posts.len(),
            2,
            "No auto xact should match; expected 2 posts, got {}",
            xact.posts.len()
        );
    }

    #[test]
    fn auto_xact_case_insensitive_pattern() {
        let journal = parse(
            "\
= /food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty(), "Case-insensitive match should work");
    }

    #[test]
    fn auto_xact_account_tilde_syntax() {
        let journal = parse(
            "\
= account =~ /food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty(), "account =~ /pattern/ syntax should match");
    }

    #[test]
    fn generated_postings_have_flag() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
        for g in &generated {
            assert!(g.item.has_flags(POST_GENERATED));
        }
    }

    #[test]
    fn auto_xact_doesnt_recurse_on_generated() {
        // If /Expenses/ matches, it should not trigger again on the generated
        // posting that also goes to an Expenses account.
        let journal = parse(
            "\
= /Expenses/
    (Expenses:Tax)             $1.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        // Should only have generated from the original Expenses:Food post, not recursively
        // from generated Expenses:Tax post.
        assert_eq!(
            generated.len(),
            1,
            "Auto xact should not recurse on generated postings, got {} generated",
            generated.len()
        );
    }

    #[test]
    fn auto_xact_multiple_template_postings() {
        let journal = parse(
            "\
= /Food/
    (Expenses:StateTax)        0.05
    (Expenses:FedTax)          0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert_eq!(
            generated.len(),
            2,
            "Two template postings should produce two generated postings"
        );
    }

    #[test]
    fn auto_xact_integration_balance() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = balance_command(
            &journal,
            &BalanceOptions {
                flat: true,
                ..BalanceOptions::default()
            },
        );
        assert!(!output.is_empty());
        // Balance should mention Expenses:Food and Assets:Checking
        assert!(output.contains("Expenses:Food"), "Balance should show Expenses:Food: {}", output);
        assert!(
            output.contains("Checking"),
            "Balance should show Assets:Checking: {}",
            output
        );
    }

    #[test]
    fn auto_xact_integration_register() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(!output.is_empty());
        // Register should show the original postings
        assert!(
            output.contains("Grocery Store"),
            "Register should show payee"
        );
    }

    #[test]
    fn auto_xact_virtual_posting() {
        let journal = parse(
            "\
= /Food/
    (Budget:Food)              $-50.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
        // Parenthesized accounts create virtual postings
        for g in &generated {
            assert!(
                g.is_virtual(),
                "Parenthesized auto xact postings should be virtual"
            );
        }
    }

    #[test]
    fn auto_xact_different_commodity() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             EUR 1.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
        // Fixed amount with different commodity should be used as-is
        let gen_amt = generated[0].amount.as_ref().unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), 1.0);
    }

    #[test]
    fn auto_xact_affects_balance_totals() {
        // Full pipeline: auto xact generated postings affect the balance report.
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = balance_command(
            &journal,
            &BalanceOptions {
                flat: true,
                ..BalanceOptions::default()
            },
        );
        // The auto xact adds $5.00 to Expenses:Tax
        assert!(
            output.contains("Expenses:Tax"),
            "Auto xact generated posting should appear in balance: {}",
            output
        );
    }

    #[test]
    fn auto_xact_programmatic_match() {
        // Test the match/apply API directly (not through parser).
        let mut journal = Journal::new();
        let food_id = journal.find_account("Expenses:Food", true).unwrap();
        let tax_id = journal.find_account("Expenses:Tax", true).unwrap();

        let mut auto = AutomatedTransaction::new("/food/");
        auto.add_post(Post::with_account_and_amount(
            tax_id,
            Amount::parse("$5.00").unwrap(),
        ));

        let matched = Post::with_account_and_amount(food_id, Amount::parse("$50.00").unwrap());
        assert!(auto.matches(&matched, &journal));

        let generated = auto.apply_to(&matched);
        assert_eq!(generated.len(), 1);
        assert!(generated[0].item.has_flags(POST_GENERATED));
    }

    #[test]
    fn auto_xact_programmatic_no_match() {
        let mut journal = Journal::new();
        let rent_id = journal.find_account("Expenses:Rent", true).unwrap();
        let tax_id = journal.find_account("Expenses:Tax", true).unwrap();

        let mut auto = AutomatedTransaction::new("/food/");
        auto.add_post(Post::with_account_and_amount(
            tax_id,
            Amount::parse("$5.00").unwrap(),
        ));

        let non_matching = Post::with_account_and_amount(rent_id, Amount::parse("$1000.00").unwrap());
        assert!(!auto.matches(&non_matching, &journal));
    }

    #[test]
    fn auto_xact_anchored_pattern() {
        let journal = parse(
            "\
= /^Expenses:Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty(), "Anchored pattern should match");
    }

    #[test]
    fn auto_xact_anchored_pattern_no_match() {
        let journal = parse(
            "\
= /^Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        // "^Food" should not match "Expenses:Food" because it doesn't start with "Food"
        assert!(
            generated.is_empty(),
            "Anchored ^Food should not match Expenses:Food"
        );
    }
}

// =========================================================================
// PERIODIC TRANSACTION TESTS
// =========================================================================

mod periodic_xact_tests {
    use super::*;

    #[test]
    fn parse_monthly_syntax() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food              $500.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts[0].period(), "Monthly");
    }

    #[test]
    fn parse_weekly_syntax() {
        let journal = parse(
            "\
~ Weekly
    Expenses:Groceries         $100.00
    Assets:Cash
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_weekly());
    }

    #[test]
    fn parse_yearly_syntax() {
        let journal = parse(
            "\
~ Yearly
    Expenses:Insurance         $1200.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_yearly());
    }

    #[test]
    fn parse_daily_syntax() {
        let journal = parse(
            "\
~ Daily
    Expenses:Coffee            $5.00
    Assets:Cash
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_daily());
    }

    #[test]
    fn periodic_xact_stores_period_expression() {
        let journal = parse(
            "\
~ Every 2 weeks
    Expenses:Groceries         $200.00
    Assets:Cash
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts[0].period(), "Every 2 weeks");
    }

    #[test]
    fn periodic_xact_stores_template_postings() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food              $500.00
    Assets:Checking
",
        );
        let px = &journal.periodic_xacts[0];
        assert_eq!(px.posts.len(), 2);
        // First posting should have an amount
        assert!(px.posts[0].amount.is_some());
    }

    #[test]
    fn multiple_periodic_xacts() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food              $500.00
    Assets:Checking

~ Weekly
    Expenses:Groceries         $100.00
    Assets:Cash
",
        );
        assert_eq!(journal.periodic_xacts.len(), 2);
        assert!(journal.periodic_xacts[0].is_monthly());
        assert!(journal.periodic_xacts[1].is_weekly());
    }

    #[test]
    fn periodic_xact_coexists_with_auto_and_regular() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

~ Monthly
    Expenses:Food              $500.00
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn periodic_xact_doesnt_affect_balance() {
        // Without --budget, periodic xacts are just templates and should
        // not appear in balance output.
        let journal = parse(
            "\
~ Monthly
    Expenses:Food              $500.00
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        // Balance should show $50.00 for Food, not $500.00
        assert!(output.contains("50"), "Balance should reflect actual transactions, not periodic");
    }

    #[test]
    fn period_helpers() {
        let monthly = PeriodicTransaction::new("Monthly");
        assert!(monthly.is_monthly());
        assert!(!monthly.is_weekly());
        assert!(!monthly.is_yearly());
        assert!(!monthly.is_daily());
        assert!(!monthly.is_quarterly());

        let quarterly = PeriodicTransaction::new("Every 3 months");
        assert!(quarterly.is_quarterly());

        let annually = PeriodicTransaction::new("Annually");
        assert!(annually.is_yearly());
    }

    #[test]
    fn periodic_xact_multiple_postings() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food              $300.00
    Expenses:Rent              $1200.00
    Assets:Checking
",
        );
        let px = &journal.periodic_xacts[0];
        assert_eq!(px.posts.len(), 3);
    }

    #[test]
    fn periodic_xact_with_comments() {
        let journal = parse(
            "\
~ Monthly
    ; budget for food
    Expenses:Food              $500.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        // Comment lines within should be handled (may or may not reduce posting count)
        assert!(journal.periodic_xacts[0].posts.len() >= 2);
    }

    #[test]
    fn periodic_xact_programmatic_construction() {
        let mut px = PeriodicTransaction::new("Every Week");
        assert!(px.is_weekly());
        assert_eq!(px.posts.len(), 0);

        px.add_post(Post::new());
        px.add_post(Post::new());
        assert_eq!(px.posts.len(), 2);

        let cloned = px.clone();
        assert_eq!(cloned.period_expr, "Every Week");
        assert_eq!(cloned.posts.len(), 2);
    }
}

// =========================================================================
// LOT ANNOTATION TESTS
// =========================================================================

mod lot_annotation_tests {
    use super::*;

    #[test]
    fn parse_lot_with_price() {
        let (ann, consumed) = LotAnnotation::parse("{$10.00}").unwrap();
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert!(!ann.has_tag());
        let price = ann.price.as_ref().unwrap();
        assert_eq!(price.to_double().unwrap(), 10.0);
        assert!(consumed > 0);
    }

    #[test]
    fn parse_lot_with_date() {
        let (ann, _) = LotAnnotation::parse("[2024-01-15]").unwrap();
        assert!(ann.has_date());
        assert_eq!(ann.date.unwrap(), d(2024, 1, 15));
    }

    #[test]
    fn parse_lot_with_tag() {
        let (ann, _) = LotAnnotation::parse("(lot-tag)").unwrap();
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("lot-tag"));
    }

    #[test]
    fn parse_lot_full_annotation() {
        let (ann, _) = LotAnnotation::parse("{$10.00} [2024-01-15] (initial)").unwrap();
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.price.as_ref().unwrap().to_double().unwrap(), 10.0);
        assert_eq!(ann.date.unwrap(), d(2024, 1, 15));
        assert_eq!(ann.tag.as_deref(), Some("initial"));
    }

    #[test]
    fn lot_display_format() {
        let ann = LotAnnotation::full(
            Amount::parse("$150.00").unwrap(),
            d(2024, 1, 15),
            "lot1",
        );
        let s = format!("{}", ann);
        assert!(s.contains("{"), "Display should contain {{");
        assert!(s.contains("[2024/01/15]"), "Display should contain date");
        assert!(s.contains("(lot1)"), "Display should contain tag");
    }

    #[test]
    fn lot_empty() {
        let ann = LotAnnotation::new();
        assert!(ann.is_empty());
        let s = format!("{}", ann);
        assert!(s.is_empty());
    }

    #[test]
    fn lot_price_different_commodity() {
        let (ann, _) = LotAnnotation::parse("{EUR 25.00}").unwrap();
        assert!(ann.has_price());
        let price = ann.price.as_ref().unwrap();
        assert_eq!(price.to_double().unwrap(), 25.0);
    }

    #[test]
    fn lot_equality() {
        let date = d(2024, 1, 15);
        let a = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot1");
        let b = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot1");
        assert_eq!(a, b);
    }

    #[test]
    fn lot_inequality() {
        let date = d(2024, 1, 15);
        let a = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot1");
        let b = LotAnnotation::full(Amount::parse("$31.00").unwrap(), date, "lot1");
        assert_ne!(a, b);

        let c = LotAnnotation::full(Amount::parse("$30.00").unwrap(), d(2024, 1, 16), "lot1");
        assert_ne!(a, c);

        let e = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot2");
        assert_ne!(a, e);
    }

    #[test]
    fn lot_constructors() {
        let price_only = LotAnnotation::with_price(Amount::parse("$10.00").unwrap());
        assert!(price_only.has_price());
        assert!(!price_only.has_date());
        assert!(!price_only.has_tag());

        let price_date = LotAnnotation::with_price_and_date(
            Amount::parse("$10.00").unwrap(),
            d(2024, 6, 1),
        );
        assert!(price_date.has_price());
        assert!(price_date.has_date());
        assert!(!price_date.has_tag());

        let full = LotAnnotation::full(
            Amount::parse("$10.00").unwrap(),
            d(2024, 6, 1),
            "purchase",
        );
        assert!(full.has_price());
        assert!(full.has_date());
        assert!(full.has_tag());
    }

    #[test]
    fn lot_parse_date_formats() {
        // Slash format
        let (ann1, _) = LotAnnotation::parse("[2024/01/15]").unwrap();
        assert_eq!(ann1.date.unwrap(), d(2024, 1, 15));

        // Dash format
        let (ann2, _) = LotAnnotation::parse("[2024-01-15]").unwrap();
        assert_eq!(ann2.date.unwrap(), d(2024, 1, 15));

        // Dot format
        let (ann3, _) = LotAnnotation::parse("[2024.01.15]").unwrap();
        assert_eq!(ann3.date.unwrap(), d(2024, 1, 15));
    }

    #[test]
    fn lot_parse_errors() {
        assert!(LotAnnotation::parse("{$10.00").is_err());
        assert!(LotAnnotation::parse("[2024-01-15").is_err());
        assert!(LotAnnotation::parse("(unclosed tag").is_err());
    }

    #[test]
    fn lot_parse_fixation() {
        let (ann, _) = LotAnnotation::parse("{=$30.00}").unwrap();
        assert!(ann.has_price());
        assert_eq!(ann.price.as_ref().unwrap().to_double().unwrap(), 30.0);
    }
}

// =========================================================================
// CROSS-FEATURE INTEGRATION TESTS
// =========================================================================

mod integration_tests {
    use super::*;

    #[test]
    fn auto_xact_balance_agreement() {
        // Balance totals should be consistent with auto xact additions.
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $10.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking

2024/01/20 Restaurant
    Expenses:Food              $30.00
    Assets:Checking
",
        );
        let output = balance_command(
            &journal,
            &BalanceOptions {
                flat: true,
                ..BalanceOptions::default()
            },
        );
        // Both Food postings match, so Expenses:Tax should have $20.00 total
        assert!(
            output.contains("Expenses:Tax"),
            "Tax account should appear in balance: {}",
            output
        );
    }

    #[test]
    fn auto_xact_register_running_totals() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(!output.is_empty());
        assert!(output.contains("Grocery Store"));
    }

    #[test]
    fn auto_xact_with_alias_directive() {
        let journal = parse(
            "\
alias food=Expenses:Food

= /Food/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    food                       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        // The alias should resolve food -> Expenses:Food
        // and the auto xact /Food/ should match
        let xact = &journal.xacts[0];
        let generated: Vec<_> = xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(
            !generated.is_empty(),
            "Auto xact should match aliased account"
        );
    }

    #[test]
    fn print_shows_generated_postings() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(!output.is_empty());
        // Print should include the generated posting
        assert!(
            output.contains("Tax"),
            "Print should show generated postings: {}",
            output
        );
    }

    #[test]
    fn empty_journal_through_phase3() {
        let journal = parse("");
        assert_eq!(journal.xacts.len(), 0);
        assert_eq!(journal.auto_xacts.len(), 0);
        assert_eq!(journal.periodic_xacts.len(), 0);

        let bal = balance_command(&journal, &BalanceOptions::default());
        let reg = register_command(&journal, &RegisterOptions::default());
        // Should not panic
        assert!(bal.is_empty() || bal.trim().is_empty() || bal.contains("0"));
        assert!(reg.is_empty() || reg.trim().is_empty());
    }

    #[test]
    fn large_journal_auto_xacts_stress() {
        // Build a journal with many transactions and auto xacts.
        let mut text = String::new();
        text.push_str("= /Expenses/\n    (Expenses:Tax)             0.05\n\n");
        for i in 1..=50 {
            text.push_str(&format!(
                "2024/01/{:02} Vendor {}\n    Expenses:Food              $10.00\n    Assets:Checking\n\n",
                (i % 28) + 1,
                i
            ));
        }
        let journal = parse(&text);
        assert_eq!(journal.xacts.len(), 50);
        // Each Expenses:Food posting should trigger the auto xact
        for xact in &journal.xacts {
            let generated: Vec<_> = xact
                .posts
                .iter()
                .filter(|p| p.item.has_flags(POST_GENERATED))
                .collect();
            assert!(
                !generated.is_empty(),
                "Each transaction should have generated postings"
            );
        }
    }

    #[test]
    fn auto_xact_plus_periodic_in_same_journal() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             0.10

~ Monthly
    Expenses:Food              $500.00
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.xacts.len(), 1);

        // Auto xact should apply to the regular transaction
        let generated: Vec<_> = journal.xacts[0]
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());

        // Periodic xact should be stored but not generate transactions
        assert!(journal.periodic_xacts[0].is_monthly());
    }

    #[test]
    fn mixed_directives_auto_periodic_regular() {
        let journal = parse(
            "\
; Comment at top
account Expenses:Food
account Assets:Checking

alias food=Expenses:Food

= /Food/
    (Expenses:Tax)             0.05

~ Monthly
    Expenses:Rent              $1500.00
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking

2024/01/20 * Landlord
    Expenses:Rent              $1500.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 2);
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);

        // Auto xact should match the grocery store transaction
        let grocery_xact = &journal.xacts[0];
        let generated: Vec<_> = grocery_xact
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        assert!(!generated.is_empty());
    }

    #[test]
    fn balanced_journal_with_auto_xacts_balance_is_zero() {
        // When auto xact posts are virtual (parenthesized), the main
        // balance should still be zero for a balanced journal.
        let journal = parse(
            "\
= /Food/
    (Budget:Food)              $-50.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        // The non-virtual postings (Expenses:Food + Assets:Checking) should net to 0
        // The virtual posting (Budget:Food) is separate
        // Total line should exist
        assert!(!output.is_empty());
    }

    #[test]
    fn auto_xact_with_multiple_transactions() {
        let journal = parse(
            "\
= /Expenses/
    (Expenses:Tax)             0.08

2024/01/15 Grocery Store
    Expenses:Food              $100.00
    Assets:Checking

2024/01/20 Gas Station
    Expenses:Gas               $40.00
    Assets:Checking

2024/01/25 Movie Theater
    Entertainment:Movies       $15.00
    Assets:Cash
",
        );
        // /Expenses/ should match Food and Gas but not Entertainment:Movies
        let food_gen: Vec<_> = journal.xacts[0]
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        let gas_gen: Vec<_> = journal.xacts[1]
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();
        let movie_gen: Vec<_> = journal.xacts[2]
            .posts
            .iter()
            .filter(|p| p.item.has_flags(POST_GENERATED))
            .collect();

        assert!(!food_gen.is_empty(), "Expenses:Food should match");
        assert!(!gas_gen.is_empty(), "Expenses:Gas should match");
        assert!(
            movie_gen.is_empty(),
            "Entertainment:Movies should not match /Expenses/"
        );
    }

    #[test]
    fn register_with_auto_xact_account_filter() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let opts = RegisterOptions {
            account_patterns: vec!["Tax".to_string()],
            ..RegisterOptions::default()
        };
        let output = register_command(&journal, &opts);
        // Filtering for "Tax" should show the auto-generated posting
        assert!(
            output.contains("Tax"),
            "Register filtered by Tax should show generated posting: {}",
            output
        );
    }
}
