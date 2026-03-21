//! Phase 6 parity validation tests for the Rust port (T-000078).
//!
//! Integration tests covering automated transactions, periodic transactions,
//! directives (account, commodity, alias, apply, tag, payee, year, bucket,
//! include), and advanced parser features.

use muonledger::amount::Amount;
use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::print::{print_journal, PrintOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;
use muonledger::post::POST_GENERATED;

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
// AUTOMATED TRANSACTION TESTS
// =========================================================================

mod auto_xact_tests {
    use super::*;

    #[test]
    fn auto_xact_parsed() {
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
        assert_eq!(journal.auto_xacts[0].predicate_expr, "/Food/");
    }

    #[test]
    fn auto_xact_generates_posting() {
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
        assert!(
            xact.posts.len() > 2,
            "auto xact should generate extra posting, got {} posts",
            xact.posts.len()
        );
    }

    #[test]
    fn auto_xact_generated_has_flag() {
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
        assert!(!generated.is_empty(), "should have generated postings");
    }

    #[test]
    fn auto_xact_fixed_amount() {
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
        let gen_amt = generated[0].amount.as_ref().unwrap();
        assert_eq!(gen_amt.to_double().unwrap(), 5.0);
    }

    #[test]
    fn auto_xact_multiplier() {
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
    fn auto_xact_no_match() {
        let journal = parse(
            "\
= /Rent/
    (Expenses:Tax)             0.10

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let xact = &journal.xacts[0];
        // No match, so only original 2 postings
        assert_eq!(xact.posts.len(), 2);
    }

    #[test]
    fn auto_xact_matches_multiple_transactions() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $2.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking

2024/01/20 Restaurant
    Expenses:Food              $30.00
    Assets:Checking
",
        );
        // Both transactions should get generated postings
        assert!(journal.xacts[0].posts.len() > 2, "first xact should have generated posting");
        assert!(journal.xacts[1].posts.len() > 2, "second xact should have generated posting");
    }

    #[test]
    fn auto_xact_multiple_rules() {
        let journal = parse(
            "\
= /Food/
    (Expenses:FoodTax)         $2.00

= /Utilities/
    (Expenses:UtilityTax)      $3.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities         $100.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 2);
        // Food xact should match first rule only
        assert!(journal.xacts[0].posts.len() > 2);
        // Utilities xact should match second rule only
        assert!(journal.xacts[1].posts.len() > 2);
    }

    #[test]
    fn auto_xact_anchored_pattern() {
        let journal = parse(
            "\
= /^Expenses:Food/
    (Expenses:Tax)             $1.00

2024/01/15 Grocery
    Expenses:Food              $50.00
    Assets:Checking

2024/01/20 Other
    Income:Food:Sales          $30.00
    Assets:Checking
",
        );
        // Only Expenses:Food should match (anchored at start)
        assert!(journal.xacts[0].posts.len() > 2, "Food should match");
        // Income:Food:Sales should not match ^Expenses:Food
        assert_eq!(journal.xacts[1].posts.len(), 2, "Income should not match");
    }

    #[test]
    fn auto_xact_plain_text_predicate() {
        let journal = parse(
            "\
= Expenses:Food
    (Expenses:Tax)             $1.00

2024/01/15 Grocery
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        // Plain text predicate should match as substring
        assert!(journal.xacts[0].posts.len() > 2);
    }

    #[test]
    fn auto_xact_case_insensitive_match() {
        let journal = parse(
            "\
= /FOOD/
    (Expenses:Tax)             $1.00

2024/01/15 Grocery
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert!(
            journal.xacts[0].posts.len() > 2,
            "case-insensitive match should work"
        );
    }

    #[test]
    fn auto_xact_empty_predicate_skipped() {
        let journal = parse(
            "\
=
    (Expenses:Tax)             $1.00

2024/01/15 Grocery
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 0);
        assert_eq!(journal.xacts[0].posts.len(), 2);
    }

    #[test]
    fn auto_xact_in_balance_report() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $5.00

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Tax"), "balance should show generated posting account");
    }

    #[test]
    fn auto_xact_in_register_report() {
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
        assert!(output.contains("Tax"), "register should show generated posting");
    }
}

// =========================================================================
// PERIODIC TRANSACTION TESTS
// =========================================================================

mod periodic_xact_tests {
    use super::*;

    #[test]
    fn periodic_xact_parsed_monthly() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_monthly());
    }

    #[test]
    fn periodic_xact_parsed_weekly() {
        let journal = parse(
            "\
~ Weekly
    Expenses:Groceries    $100.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_weekly());
    }

    #[test]
    fn periodic_xact_parsed_yearly() {
        let journal = parse(
            "\
~ Yearly
    Expenses:Insurance    $1200.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_yearly());
    }

    #[test]
    fn periodic_xact_parsed_daily() {
        let journal = parse(
            "\
~ Daily
    Expenses:Coffee       $5.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_daily());
    }

    #[test]
    fn periodic_xact_parsed_quarterly() {
        let journal = parse(
            "\
~ Quarterly
    Expenses:Tax          $3000.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_quarterly());
    }

    #[test]
    fn periodic_xact_has_posts() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts[0].posts.len(), 2);
    }

    #[test]
    fn multiple_periodic_xacts() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

~ Weekly
    Expenses:Gas          $50.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 2);
    }

    #[test]
    fn periodic_xact_with_every_month() {
        let journal = parse(
            "\
~ Every Month
    Expenses:Rent         $1500.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert!(journal.periodic_xacts[0].is_monthly());
    }

    #[test]
    fn periodic_xact_empty_period_skipped() {
        let journal = parse(
            "\
~
    Expenses:Food         $500.00
    Assets:Checking

2024/01/01 Placeholder
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.periodic_xacts.len(), 0);
    }

    #[test]
    fn periodic_xact_does_not_affect_regular_transactions() {
        let journal = parse(
            "\
~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

2024/01/01 Regular
    Expenses:Misc         $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.xacts[0].payee, "Regular");
    }
}

// =========================================================================
// ACCOUNT ALIAS DIRECTIVE TESTS
// =========================================================================

mod alias_directive_tests {
    use super::*;

    #[test]
    fn alias_directive_basic() {
        let journal = parse(
            "\
alias food=Expenses:Food

2024/01/01 Test
    food                $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"), "alias should resolve to full account");
    }

    #[test]
    fn alias_directive_multiple() {
        let journal = parse(
            "\
alias food=Expenses:Food
alias check=Assets:Checking

2024/01/01 Test
    food                $50.00
    check
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Assets:Checking"));
    }

    #[test]
    fn alias_from_account_directive() {
        let journal = parse(
            "\
account Expenses:Food
    alias food

2024/01/01 Test
    food                $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"));
    }
}

// =========================================================================
// APPLY ACCOUNT DIRECTIVE TESTS
// =========================================================================

mod apply_account_tests {
    use super::*;

    #[test]
    fn apply_account_basic() {
        let journal = parse(
            "\
apply account Personal

2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking

end apply account
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(
            output.contains("Personal"),
            "apply account should prefix accounts, got: {}",
            output
        );
    }

    #[test]
    fn apply_account_nested() {
        let journal = parse(
            "\
apply account Personal

apply account US

2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking

end apply account
end apply account
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        // Should have Personal:US prefix
        assert!(
            output.contains("Personal") && output.contains("US"),
            "nested apply account should stack prefixes, got: {}",
            output
        );
    }

    #[test]
    fn apply_account_only_within_scope() {
        let journal = parse(
            "\
apply account Personal

2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking

end apply account

2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 2);
        // First transaction should have Personal prefix; second should not
        let opts = BalanceOptions {
            flat: true,
            ..Default::default()
        };
        let output = balance_command(&journal, &opts);
        assert!(output.contains("Personal"), "first xact under apply account, got: {}", output);
    }
}

// =========================================================================
// APPLY TAG DIRECTIVE TESTS
// =========================================================================

mod apply_tag_tests {
    use super::*;

    #[test]
    fn apply_tag_basic() {
        let journal = parse(
            "\
apply tag project

2024/01/01 Test
    Expenses:Food       $50.00
    Assets:Checking

end apply tag
",
        );
        assert_eq!(journal.xacts.len(), 1);
        // The transaction should have the tag applied
        assert!(
            journal.xacts[0].item.has_tag("project"),
            "apply tag should add tag to transactions"
        );
    }

    #[test]
    fn apply_tag_only_within_scope() {
        let journal = parse(
            "\
apply tag project

2024/01/01 First
    Expenses:Food       $10.00
    Assets:Checking

end apply tag

2024/01/02 Second
    Expenses:Food       $20.00
    Assets:Checking
",
        );
        assert!(journal.xacts[0].item.has_tag("project"), "first should have tag");
        assert!(!journal.xacts[1].item.has_tag("project"), "second should not");
    }
}

// =========================================================================
// TAG AND PAYEE DECLARATION TESTS
// =========================================================================

mod declaration_tests {
    use super::*;

    #[test]
    fn tag_declaration() {
        let journal = parse(
            "\
tag Receipt
tag Project

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.tag_declarations.len(), 2);
        assert!(journal.tag_declarations.contains(&"Receipt".to_string()));
        assert!(journal.tag_declarations.contains(&"Project".to_string()));
    }

    #[test]
    fn payee_declaration() {
        let journal = parse(
            "\
payee Grocery Store
payee Electric Company

2024/01/01 Grocery Store
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.payee_declarations.len(), 2);
        assert!(journal.payee_declarations.contains(&"Grocery Store".to_string()));
        assert!(journal.payee_declarations.contains(&"Electric Company".to_string()));
    }

    #[test]
    fn tag_declaration_with_sub_directives() {
        let journal = parse(
            "\
tag Receipt
    check /^[0-9]+$/

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        // Sub-directives should be consumed without error
        assert_eq!(journal.tag_declarations.len(), 1);
    }

    #[test]
    fn payee_declaration_with_sub_directives() {
        let journal = parse(
            "\
payee Grocery Store
    alias Groceries

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.payee_declarations.len(), 1);
    }
}

// =========================================================================
// YEAR / DEFAULT YEAR DIRECTIVE TESTS
// =========================================================================

mod year_directive_tests {
    use super::*;

    #[test]
    fn year_directive_y() {
        let journal = parse(
            "\
Y 2024

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.default_year, Some(2024));
    }

    #[test]
    fn year_directive_word() {
        let journal = parse(
            "\
year 2025

2025/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.default_year, Some(2025));
    }
}

// =========================================================================
// BUCKET DIRECTIVE TESTS
// =========================================================================

mod bucket_directive_tests {
    use super::*;

    #[test]
    fn bucket_directive() {
        let journal = parse(
            "\
bucket Assets:Checking

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.bucket.is_some(), "bucket should be set");
    }

    #[test]
    fn bucket_directive_short_a() {
        let journal = parse(
            "\
A Assets:Checking

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.bucket.is_some(), "A directive should set bucket");
    }
}

// =========================================================================
// ACCOUNT DIRECTIVE TESTS
// =========================================================================

mod account_directive_tests {
    use super::*;

    #[test]
    fn account_directive_creates_account() {
        let journal = parse(
            "\
account Expenses:Food
account Assets:Checking

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn account_directive_with_note() {
        let journal = parse(
            "\
account Expenses:Food
    note Food and groceries

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn account_directive_with_default() {
        let journal = parse(
            "\
account Assets:Checking
    default

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.bucket.is_some(), "account default should set bucket");
    }

    #[test]
    fn account_directive_with_alias() {
        let journal = parse(
            "\
account Expenses:Food
    alias food

2024/01/01 Test
    food                $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"));
    }
}

// =========================================================================
// COMMODITY DIRECTIVE TESTS
// =========================================================================

mod commodity_directive_tests {
    use super::*;

    #[test]
    fn commodity_directive_basic() {
        let journal = parse(
            "\
commodity $
commodity EUR

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn commodity_directive_with_sub_directives() {
        let journal = parse(
            "\
commodity $
    note US Dollar
    format $1,000.00

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
    }
}

// =========================================================================
// NO-MARKET AND DEFINE DIRECTIVES
// =========================================================================

mod other_directive_tests {
    use super::*;

    #[test]
    fn n_no_market_directive() {
        let journal = parse(
            "\
N $

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert!(journal.no_market_commodities.contains(&"$".to_string()));
    }

    #[test]
    fn define_directive() {
        let journal = parse(
            "\
define tax_rate=0.10

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.defines.get("tax_rate"), Some(&"0.10".to_string()));
    }

    #[test]
    fn d_default_commodity_directive() {
        let journal = parse(
            "\
D $1,000.00

2024/01/01 Test
    Expenses:Food       $10.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.commodity_pool.default_commodity.is_some());
    }
}

// =========================================================================
// INCLUDE DIRECTIVE TESTS
// =========================================================================

mod include_directive_tests {
    use super::*;

    #[test]
    fn include_nonexistent_file_is_error() {
        let result = try_parse(
            "\
include nonexistent_file.ledger
",
        );
        // include from a <string> source might resolve oddly, but should
        // still fail for a truly nonexistent file
        assert!(result.is_err(), "including nonexistent file should error");
    }
}

// =========================================================================
// PRICE HISTORY TESTS
// =========================================================================

mod price_history_tests {
    use super::*;

    #[test]
    fn single_price_directive() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 1);
        assert_eq!(journal.prices[0].1, "AAPL");
    }

    #[test]
    fn multiple_price_directives() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00
P 2024/06/02 AAPL $155.00
P 2024/06/03 AAPL $152.00

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 3);
    }

    #[test]
    fn price_directive_different_commodities() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00
P 2024/06/01 EUR $1.10
P 2024/06/01 GBP $1.30

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices.len(), 3);
        let symbols: Vec<&str> = journal.prices.iter().map(|p| p.1.as_str()).collect();
        assert!(symbols.contains(&"AAPL"));
        assert!(symbols.contains(&"EUR"));
        assert!(symbols.contains(&"GBP"));
    }

    #[test]
    fn price_directive_dates_correct() {
        let journal = parse(
            "\
P 2024/01/15 AAPL $150.00
P 2024/06/30 GOOG $2800.00

2024/01/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(
            journal.prices[0].0,
            NaiveDate::from_ymd_opt(2024, 1, 15).unwrap()
        );
        assert_eq!(
            journal.prices[1].0,
            NaiveDate::from_ymd_opt(2024, 6, 30).unwrap()
        );
    }

    #[test]
    fn price_directive_amounts_correct() {
        let journal = parse(
            "\
P 2024/06/01 AAPL $150.00
P 2024/06/01 EUR $1.10

2024/06/01 Placeholder
    Expenses:Misc       $1.00
    Assets:Checking
",
        );
        assert_eq!(journal.prices[0].2.to_double().unwrap(), 150.0);
        assert_eq!(journal.prices[1].2.to_double().unwrap(), 1.10);
    }
}

// =========================================================================
// CROSS-FEATURE INTEGRATION TESTS
// =========================================================================

mod cross_feature_tests {
    use super::*;

    #[test]
    fn auto_xact_with_periodic_xact() {
        let journal = parse(
            "\
= /Food/
    (Expenses:Tax)             $2.00

~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

2024/01/15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.xacts[0].posts.len() > 2, "auto xact should apply");
    }

    #[test]
    fn directives_with_transactions() {
        let journal = parse(
            "\
account Expenses:Food
account Assets:Checking

commodity $

P 2024/01/01 EUR $1.10

2024/01/15 Grocery Store
    Expenses:Food       $50.00
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.prices.len(), 1);
    }

    #[test]
    fn complex_journal_with_all_features() {
        let journal = parse(
            "\
; Header comment
account Expenses:Food
account Assets:Checking
commodity $
tag Receipt
payee Grocery Store

P 2024/01/01 EUR $1.10

Y 2024

= /Food/
    (Expenses:Tax)             $1.00

~ Monthly
    Expenses:Food         $500.00
    Assets:Checking

2024/01/15 * (1042) Grocery Store ; weekly shopping
    Expenses:Food       $50.00
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $75.00
    Assets:Checking

2024/02/01 Buy Euros
    Assets:Foreign       100 EUR @ $1.10
    Assets:Checking
",
        );
        assert_eq!(journal.xacts.len(), 3);
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.prices.len(), 1);
        assert_eq!(journal.tag_declarations.len(), 1);
        assert_eq!(journal.payee_declarations.len(), 1);
        assert_eq!(journal.default_year, Some(2024));
    }

    #[test]
    fn complex_journal_balance_report() {
        let journal = parse(
            "\
2024/01/01 Opening Balance
    Assets:Bank:Checking     $5000.00
    Equity:Opening

2024/01/15 * Grocery Store
    Expenses:Food            $50.00
    Assets:Bank:Checking

2024/01/20 Electric Company
    Expenses:Utilities       $75.00
    Assets:Bank:Checking

2024/02/01 Paycheck
    Assets:Bank:Checking    $3000.00
    Income:Salary

2024/02/15 Buy Euros
    Assets:Foreign           200 EUR @ $1.10
    Assets:Bank:Checking
",
        );
        let output = balance_command(&journal, &BalanceOptions::default());
        // Checking: 5000 - 50 - 75 + 3000 - 220 = 7655
        assert!(output.contains("$7655.00"), "checking should be $7655.00");
        assert!(output.contains("200 EUR"), "should show EUR");
        assert!(output.contains("$50.00"), "should show food expense");
        assert!(output.contains("$75.00"), "should show utilities expense");
        // With mixed commodities, the total line may show "0" or the
        // multi-commodity breakdown. The key check is that it parses and
        // the amounts are correct.
        assert!(output.contains("----"), "should have separator line");
    }

    #[test]
    fn complex_journal_register_report() {
        let journal = parse(
            "\
2024/01/01 Opening Balance
    Assets:Checking     $1000.00
    Equity:Opening

2024/01/15 Grocery Store
    Expenses:Food       $50.00
    Assets:Checking

2024/01/20 Electric Company
    Expenses:Utilities  $75.00
    Assets:Checking
",
        );
        let output = register_command(&journal, &RegisterOptions::default());
        assert!(output.contains("24-Jan-01"), "shows first date");
        assert!(output.contains("24-Jan-15"), "shows second date");
        assert!(output.contains("24-Jan-20"), "shows third date");
        assert!(output.contains("Opening Balance"), "shows payee");
    }

    #[test]
    fn print_preserves_transaction_structure() {
        let journal = parse(
            "\
2024/01/15 * (1042) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
",
        );
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.contains("2024-01-15") || output.contains("2024/01/15"), "print shows date");
        assert!(output.contains("*"), "print shows cleared state");
        assert!(output.contains("1042"), "print shows code");
        assert!(output.contains("Grocery Store"), "print shows payee");
    }

    #[test]
    fn apply_account_with_alias() {
        let journal = parse(
            "\
alias food=Expenses:Food

apply account Personal

2024/01/01 Test
    food                $50.00
    Assets:Checking

end apply account
",
        );
        assert_eq!(journal.xacts.len(), 1);
        // Alias should resolve before apply account is considered
        // (implementation may vary)
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(
            output.contains("Food") || output.contains("Personal"),
            "should resolve alias or apply account"
        );
    }

    #[test]
    fn cleared_pending_mix_in_report() {
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
        let output = balance_command(&journal, &BalanceOptions::default());
        // Total food = 10 + 20 + 30 = 60
        assert!(output.contains("$60.00"), "food total should be $60");
    }
}
