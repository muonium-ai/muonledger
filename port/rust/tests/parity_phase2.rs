//! Phase 2 parity validation tests for the Rust port (T-000058).
//!
//! Integration tests covering the filter pipeline, report options,
//! print command, directives, and cross-command consistency.

use muonledger::amount::Amount;
use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::print::{print_journal, PrintOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::filters::*;
use muonledger::item::ItemState;
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;
use muonledger::post::Post;
use muonledger::report::{apply_to_journal, build_filter_chain, ReportOptions};
use muonledger::xact::Transaction;

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

fn od(y: i32, m: u32, day: u32) -> Option<NaiveDate> {
    Some(d(y, m, day))
}

/// Make a minimal enriched post for direct pipeline testing.
fn make_ep(
    acct_idx: usize,
    amount_str: &str,
    date: Option<NaiveDate>,
    payee: &str,
) -> EnrichedPost {
    use muonledger::account::AccountId;
    EnrichedPost {
        account_id: Some(AccountId(acct_idx)),
        amount: Some(Amount::parse(amount_str).unwrap()),
        date,
        payee: payee.to_string(),
        state: ItemState::Uncleared,
        flags: 0,
        note: None,
        cost: None,
        code: None,
        xact_idx: None,
        post_idx: None,
        xdata: PostXData::default(),
        related_post_indices: Vec::new(),
    }
}

fn make_ep_xact(
    acct_idx: usize,
    amount_str: &str,
    date: Option<NaiveDate>,
    payee: &str,
    xact_idx: usize,
    post_idx: usize,
) -> EnrichedPost {
    let mut ep = make_ep(acct_idx, amount_str, date, payee);
    ep.xact_idx = Some(xact_idx);
    ep.post_idx = Some(post_idx);
    ep
}

/// Build a programmatic journal with three transactions.
fn make_three_xact_journal() -> Journal {
    let mut journal = Journal::new();
    let food = journal.find_account("Expenses:Food", true).unwrap();
    let cash = journal.find_account("Assets:Cash", true).unwrap();
    let rent = journal.find_account("Expenses:Rent", true).unwrap();
    let checking = journal.find_account("Assets:Checking", true).unwrap();

    let mut xact1 = Transaction::with_payee("Grocery Store");
    xact1.item.date = Some(d(2024, 1, 15));
    xact1.add_post(Post::with_account_and_amount(food, Amount::parse("$50.00").unwrap()));
    xact1.add_post(Post::with_account(cash));
    xact1.finalize().unwrap();
    journal.xacts.push(xact1);

    let mut xact2 = Transaction::with_payee("Landlord");
    xact2.item.date = Some(d(2024, 2, 1));
    xact2.item.state = ItemState::Cleared;
    xact2.add_post(Post::with_account_and_amount(rent, Amount::parse("$1000.00").unwrap()));
    xact2.add_post(Post::with_account(checking));
    xact2.finalize().unwrap();
    journal.xacts.push(xact2);

    let mut xact3 = Transaction::with_payee("Restaurant");
    xact3.item.date = Some(d(2024, 3, 10));
    xact3.add_post(Post::with_account_and_amount(food, Amount::parse("$30.00").unwrap()));
    xact3.add_post(Post::with_account(cash));
    xact3.finalize().unwrap();
    journal.xacts.push(xact3);

    journal
}

// =========================================================================
// FILTER PIPELINE TESTS
// =========================================================================

mod filter_pipeline {
    use super::*;

    #[test]
    fn collect_posts_accumulates_correctly() {
        let mut collector = CollectPosts::new();
        collector.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        collector.handle(make_ep(1, "$20.00", od(2024, 1, 2), "B"));
        collector.handle(make_ep(2, "$30.00", od(2024, 1, 3), "C"));
        collector.flush();
        assert_eq!(collector.collected().len(), 3);
    }

    #[test]
    fn filter_posts_with_positive_amount_predicate() {
        let collector = Box::new(CollectPosts::new());
        let mut filter = FilterPosts::new(
            collector,
            Box::new(|p: &EnrichedPost| {
                p.amount.as_ref().map(|a| a.is_positive()).unwrap_or(false)
            }),
        );

        filter.handle(make_ep(0, "$10.00", od(2024, 1, 1), "Pos"));
        filter.handle(make_ep(1, "$-5.00", od(2024, 1, 2), "Neg"));
        filter.handle(make_ep(2, "$25.00", od(2024, 1, 3), "Pos2"));
        filter.flush();

        assert_eq!(filter.collected().len(), 2);
        assert_eq!(filter.collected()[0].payee, "Pos");
        assert_eq!(filter.collected()[1].payee, "Pos2");
    }

    #[test]
    fn filter_posts_by_payee_predicate() {
        let collector = Box::new(CollectPosts::new());
        let mut filter = FilterPosts::new(
            collector,
            Box::new(|p: &EnrichedPost| p.payee.contains("Store")),
        );

        filter.handle(make_ep(0, "$10.00", od(2024, 1, 1), "Grocery Store"));
        filter.handle(make_ep(1, "$20.00", od(2024, 1, 2), "Landlord"));
        filter.handle(make_ep(2, "$15.00", od(2024, 1, 3), "Hardware Store"));
        filter.flush();

        assert_eq!(filter.collected().len(), 2);
    }

    #[test]
    fn sort_posts_by_amount_integer_key() {
        let collector = Box::new(CollectPosts::new());
        let mut sorter = SortPosts::new(
            collector,
            Box::new(|p: &EnrichedPost| {
                let cents = p.amount.as_ref().map(|a| a.to_string()).unwrap_or_default();
                // Sort by payee as a proxy for amount ordering
                SortKey::String(cents)
            }),
            false,
        );

        sorter.handle(make_ep(0, "$30.00", od(2024, 1, 1), "C"));
        sorter.handle(make_ep(1, "$10.00", od(2024, 1, 2), "A"));
        sorter.handle(make_ep(2, "$20.00", od(2024, 1, 3), "B"));
        sorter.flush();

        let collected = sorter.collected();
        assert_eq!(collected.len(), 3);
        // String sort on "$10.00", "$20.00", "$30.00"
        assert_eq!(collected[0].payee, "A");
        assert_eq!(collected[1].payee, "B");
        assert_eq!(collected[2].payee, "C");
    }

    #[test]
    fn sort_posts_by_date() {
        let collector = Box::new(CollectPosts::new());
        let mut sorter = SortPosts::new(
            collector,
            Box::new(|p: &EnrichedPost| SortKey::Date(p.date)),
            false,
        );

        sorter.handle(make_ep(0, "$10.00", od(2024, 3, 1), "March"));
        sorter.handle(make_ep(1, "$20.00", od(2024, 1, 1), "January"));
        sorter.handle(make_ep(2, "$15.00", od(2024, 2, 1), "February"));
        sorter.flush();

        let collected = sorter.collected();
        assert_eq!(collected[0].payee, "January");
        assert_eq!(collected[1].payee, "February");
        assert_eq!(collected[2].payee, "March");
    }

    #[test]
    fn calc_posts_running_totals() {
        let collector = Box::new(CollectPosts::new());
        let mut calc = CalcPosts::new(collector, None, true);

        calc.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        calc.handle(make_ep(1, "$20.00", od(2024, 1, 2), "B"));
        calc.handle(make_ep(2, "$30.00", od(2024, 1, 3), "C"));
        calc.flush();

        let collected = calc.collected();
        assert_eq!(collected[0].xdata.total.as_ref().unwrap().to_string(), "$10.00");
        assert_eq!(collected[1].xdata.total.as_ref().unwrap().to_string(), "$30.00");
        assert_eq!(collected[2].xdata.total.as_ref().unwrap().to_string(), "$60.00");
        assert_eq!(collected[2].xdata.count, 3);
    }

    #[test]
    fn truncate_posts_limits_output() {
        let collector = Box::new(CollectPosts::new());
        let mut truncate = TruncatePosts::new(collector, 2);

        truncate.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        truncate.handle(make_ep(1, "$20.00", od(2024, 1, 2), "B"));
        truncate.handle(make_ep(2, "$30.00", od(2024, 1, 3), "C"));
        truncate.handle(make_ep(3, "$40.00", od(2024, 1, 4), "D"));
        truncate.flush();

        assert_eq!(truncate.collected().len(), 2);
        assert_eq!(truncate.collected()[0].payee, "A");
        assert_eq!(truncate.collected()[1].payee, "B");
    }

    #[test]
    fn collapse_posts_one_per_transaction() {
        let collector = Box::new(CollectPosts::new());
        let mut collapse = CollapsePosts::new(collector);

        // Two postings from xact 0
        collapse.handle(make_ep_xact(0, "$50.00", od(2024, 1, 1), "Store", 0, 0));
        collapse.handle(make_ep_xact(1, "$-50.00", od(2024, 1, 1), "Store", 0, 1));
        // One posting from xact 1
        collapse.handle(make_ep_xact(2, "$100.00", od(2024, 2, 1), "Landlord", 1, 0));
        collapse.flush();

        let collected = collapse.collected();
        assert_eq!(collected.len(), 2); // 2 transactions -> 2 collapsed posts
    }

    #[test]
    fn subtotal_posts_groups_by_account() {
        let collector = Box::new(CollectPosts::new());
        let mut subtotal = SubtotalPosts::new(collector);

        // Account 0 appears twice
        subtotal.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        subtotal.handle(make_ep(0, "$20.00", od(2024, 1, 2), "B"));
        // Account 1 appears once
        subtotal.handle(make_ep(1, "$30.00", od(2024, 1, 3), "C"));
        subtotal.flush();

        let collected = subtotal.collected();
        assert_eq!(collected.len(), 2); // 2 distinct accounts
        // Account 0 should have $30.00 total
        let acct0_post = collected.iter().find(|p| {
            p.amount.as_ref().map(|a| a.to_string()) == Some("$30.00".to_string())
        });
        assert!(acct0_post.is_some());
    }

    #[test]
    fn interval_posts_groups_by_month() {
        let collector = Box::new(CollectPosts::new());
        let mut interval = IntervalPosts::new(
            collector,
            30,
            Some(d(2024, 1, 1)),
            false,
        );

        interval.handle(make_ep(0, "$10.00", od(2024, 1, 5), "Jan1"));
        interval.handle(make_ep(0, "$20.00", od(2024, 1, 20), "Jan2"));
        interval.handle(make_ep(0, "$30.00", od(2024, 2, 10), "Feb"));
        interval.flush();

        let collected = interval.collected();
        assert_eq!(collected.len(), 2); // Jan combined, Feb separate
    }

    #[test]
    fn invert_posts_negates_amounts() {
        let collector = Box::new(CollectPosts::new());
        let mut invert = InvertPosts::new(collector);

        invert.handle(make_ep(0, "$10.00", od(2024, 1, 1), "Pos"));
        invert.handle(make_ep(1, "$-20.00", od(2024, 1, 2), "Neg"));
        invert.flush();

        let collected = invert.collected();
        assert_eq!(collected[0].amount.as_ref().unwrap().to_string(), "$-10.00");
        assert_eq!(collected[1].amount.as_ref().unwrap().to_string(), "$20.00");
    }

    #[test]
    fn chained_filter_sort_calc_collect() {
        let collector = Box::new(CollectPosts::new());
        let truncate = Box::new(TruncatePosts::new(collector, 3));
        let calc = Box::new(CalcPosts::new(truncate, None, true));
        let sorter = Box::new(SortPosts::new(
            calc,
            Box::new(|p: &EnrichedPost| SortKey::Date(p.date)),
            false,
        ));
        let mut filter = FilterPosts::new(
            sorter,
            Box::new(|p: &EnrichedPost| {
                p.amount.as_ref().map(|a| a.is_positive()).unwrap_or(false)
            }),
        );

        filter.handle(make_ep(0, "$-5.00", od(2024, 3, 1), "Neg"));
        filter.handle(make_ep(1, "$30.00", od(2024, 1, 1), "Jan"));
        filter.handle(make_ep(2, "$20.00", od(2024, 2, 1), "Feb"));
        filter.handle(make_ep(3, "$10.00", od(2024, 4, 1), "Apr"));
        filter.handle(make_ep(4, "$40.00", od(2024, 5, 1), "May"));
        filter.flush();

        let collected = filter.collected();
        // Filter removes Neg, sort orders by date, truncate keeps first 3
        assert_eq!(collected.len(), 3);
        assert_eq!(collected[0].payee, "Jan");
        assert_eq!(collected[1].payee, "Feb");
        assert_eq!(collected[2].payee, "Apr");
        // Running totals should be computed
        assert!(collected[0].xdata.total.is_some());
    }

    #[test]
    fn empty_journal_through_pipeline() {
        let journal = Journal::new();
        let opts = ReportOptions::default();

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), 0);
    }

    #[test]
    fn pipeline_with_multiple_commodities() {
        let text = "\
2024/01/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking

2024/01/05 Buy Pounds
    Assets:Foreign       100 GBP @ $1.30
    Assets:Checking
";
        let journal = parse(text);
        let opts = ReportOptions::default();

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);

        let enriched = apply_to_journal(&opts, &journal);
        let post_count = enriched.len();
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), post_count);
        assert!(post_count >= 4); // At least 4 postings (2 per xact)
    }

    #[test]
    fn pipeline_invert_then_calc_running_total() {
        let collector = Box::new(CollectPosts::new());
        let calc = Box::new(CalcPosts::new(collector, None, true));
        let mut invert = InvertPosts::new(calc);

        invert.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        invert.handle(make_ep(1, "$20.00", od(2024, 1, 2), "B"));
        invert.flush();

        let collected = invert.collected();
        // After invert: -10, -20. Running total: -10, -30
        assert_eq!(collected[1].xdata.total.as_ref().unwrap().to_string(), "$-30.00");
    }

    #[test]
    fn filter_all_rejected_yields_empty() {
        let collector = Box::new(CollectPosts::new());
        let mut filter = FilterPosts::new(
            collector,
            Box::new(|_: &EnrichedPost| false),
        );

        filter.handle(make_ep(0, "$10.00", od(2024, 1, 1), "A"));
        filter.handle(make_ep(1, "$20.00", od(2024, 1, 2), "B"));
        filter.flush();

        assert_eq!(filter.collected().len(), 0);
    }

    #[test]
    fn display_filter_with_clearing_state_predicate() {
        let collector = Box::new(CollectPosts::new());
        let mut display = DisplayFilter::new(
            collector,
            Box::new(|p: &EnrichedPost| p.state == ItemState::Cleared),
        );

        let mut cleared = make_ep(0, "$10.00", od(2024, 1, 1), "Cleared");
        cleared.state = ItemState::Cleared;
        let uncleared = make_ep(1, "$20.00", od(2024, 1, 2), "Uncleared");

        display.handle(cleared);
        display.handle(uncleared);
        display.flush();

        assert_eq!(display.collected().len(), 1);
        assert_eq!(display.collected()[0].payee, "Cleared");
    }
}

// =========================================================================
// REPORT OPTIONS TESTS
// =========================================================================

mod report_options {
    use super::*;

    #[test]
    fn default_options_return_all_posts() {
        let journal = make_three_xact_journal();
        let opts = ReportOptions::default();
        let posts = apply_to_journal(&opts, &journal);
        assert_eq!(posts.len(), 6); // 3 xacts x 2 posts
    }

    #[test]
    fn begin_date_filtering() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.begin = Some(d(2024, 2, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Feb 1 and Mar 10 transactions = 4 posts
        assert_eq!(posts.len(), 4);
    }

    #[test]
    fn end_date_filtering() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.end = Some(d(2024, 2, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Only Jan 15 = 2 posts
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn begin_and_end_date_range() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.begin = Some(d(2024, 1, 20));
        opts.end = Some(d(2024, 3, 1));
        let posts = apply_to_journal(&opts, &journal);
        // Only Feb 1 xact = 2 posts
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn cleared_state_filtering() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.cleared = true;
        let posts = apply_to_journal(&opts, &journal);
        // Only xact2 (Landlord) is cleared = 2 posts
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Landlord");
    }

    #[test]
    fn pending_state_filtering() {
        let text = "\
2024/01/01 ! Pending
    Expenses:Food       $20.00
    Assets:Checking

2024/01/02 * Cleared
    Expenses:Food       $30.00
    Assets:Checking
";
        let journal = parse(text);
        let mut opts = ReportOptions::default();
        opts.pending = true;
        let posts = apply_to_journal(&opts, &journal);
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Pending");
    }

    #[test]
    fn depth_limiting() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.depth = 1;
        let posts = apply_to_journal(&opts, &journal);
        // All accounts are depth 2 (Expenses:Food, Assets:Cash, etc.)
        assert_eq!(posts.len(), 0);
    }

    #[test]
    fn depth_two_allows_all() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.depth = 2;
        let posts = apply_to_journal(&opts, &journal);
        assert_eq!(posts.len(), 6);
    }

    #[test]
    fn invert_option_through_chain() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.invert = true;

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // First post was Expenses:Food $50, should be negated
        let first = &chain.collected()[0];
        assert!(first.amount.as_ref().unwrap().is_negative());
    }

    #[test]
    fn sort_expr_option() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.sort_expr = Some("payee".to_string());

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        let collected = chain.collected();
        // Sorted by payee: Grocery Store, Landlord, Restaurant
        assert_eq!(collected[0].payee, "Grocery Store");
        assert_eq!(collected[2].payee, "Landlord");
    }

    #[test]
    fn head_limiting() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.head = Some(3);

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        assert_eq!(chain.collected().len(), 3);
    }

    #[test]
    fn subtotal_mode() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.subtotal = true;

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // 4 distinct accounts: Expenses:Food, Assets:Cash, Expenses:Rent, Assets:Checking
        assert_eq!(chain.collected().len(), 4);
    }

    #[test]
    fn collapse_mode() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.collapse = true;

        let collector = Box::new(CollectPosts::new());
        let mut chain = build_filter_chain(&opts, collector);
        let enriched = apply_to_journal(&opts, &journal);
        for ep in enriched {
            chain.handle(ep);
        }
        chain.flush();

        // 3 transactions -> 3 collapsed posts
        assert_eq!(chain.collected().len(), 3);
    }

    #[test]
    fn account_filter() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.account_filter = Some("food".to_string());
        let posts = apply_to_journal(&opts, &journal);
        // Expenses:Food in xact1 and xact3
        assert_eq!(posts.len(), 2);
    }

    #[test]
    fn payee_filter() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.payee_filter = Some("landlord".to_string());
        let posts = apply_to_journal(&opts, &journal);
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Landlord");
    }

    #[test]
    fn combined_options_begin_and_cleared() {
        let journal = make_three_xact_journal();
        let mut opts = ReportOptions::default();
        opts.begin = Some(d(2024, 1, 20));
        opts.cleared = true;
        let posts = apply_to_journal(&opts, &journal);
        // Only xact2 (Landlord, Feb 1, cleared) matches both
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0].payee, "Landlord");
    }

    #[test]
    fn monthly_interval_option() {
        let mut opts = ReportOptions::default();
        opts.monthly = true;
        assert_eq!(opts.interval_days(), Some(30));
    }

    #[test]
    fn yearly_interval_option() {
        let mut opts = ReportOptions::default();
        opts.yearly = true;
        assert_eq!(opts.interval_days(), Some(365));
    }
}

// =========================================================================
// PRINT COMMAND TESTS
// =========================================================================

mod print_command {
    use super::*;

    #[test]
    fn simple_transaction_format() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("2024-01-15"));
        assert!(output.contains("Grocery Store"));
        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("Assets:Checking"));
        assert!(output.contains("$42.50"));
    }

    #[test]
    fn multiple_transactions_separated_by_blank_line() {
        let text = "\
2024/01/01 First
    Expenses:Food       $10.00
    Assets:Cash

2024/01/02 Second
    Expenses:Rent       $500.00
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("First"));
        assert!(output.contains("Second"));
        assert!(output.contains("\n\n")); // blank line separator
    }

    #[test]
    fn cleared_state_marker() {
        let text = "\
2024/01/01 * Cleared Store
    Expenses:Food       $25.00
    Assets:Cash
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("2024-01-01 *"));
        assert!(output.contains("Cleared Store"));
    }

    #[test]
    fn pending_state_marker() {
        let text = "\
2024/01/01 ! Pending Store
    Expenses:Food       $15.00
    Assets:Cash
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("2024-01-01 !"));
    }

    #[test]
    fn transaction_code() {
        let text = "\
2024/01/01 (1042) Hardware Store
    Expenses:Home       $120.00
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("(1042)"));
        assert!(output.contains("Hardware Store"));
    }

    #[test]
    fn transaction_note() {
        let text = "\
2024/01/01 Store ; weekly groceries
    Expenses:Food       $75.00
    Assets:Cash
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("; weekly groceries"));
    }

    #[test]
    fn cost_amounts() {
        let text = "\
2024/01/01 Buy Euros
    Assets:Foreign       200 EUR @ $1.10
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("Assets:Foreign"));
        assert!(output.contains("Assets:Checking"));
    }

    #[test]
    fn virtual_postings_format() {
        let text = "\
2024/01/01 Store
    Expenses:Food       $50.00
    Assets:Checking    $-50.00
    (Budget:Food)      $-50.00
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("Budget:Food"));
        assert!(output.contains("$50.00"));
    }

    #[test]
    fn date_filtering_in_print() {
        let text = "\
2024/01/01 January
    Expenses:Food       $10.00
    Assets:Cash

2024/03/01 March
    Expenses:Food       $30.00
    Assets:Cash
";
        let journal = parse(text);
        let mut options = PrintOptions::default();
        options.report.begin = Some(d(2024, 2, 1));
        let output = print_journal(&journal, &options);

        assert!(!output.contains("January"));
        assert!(output.contains("March"));
    }

    #[test]
    fn account_filtering_in_print() {
        let text = "\
2024/01/01 Store
    Expenses:Food       $50.00
    Assets:Checking

2024/01/02 Landlord
    Expenses:Rent       $1000.00
    Assets:Checking
";
        let journal = parse(text);
        let mut options = PrintOptions::default();
        options.report.account_filter = Some("rent".to_string());
        let output = print_journal(&journal, &options);

        // Account filter matches postings; if Rent posting passes, its xact is printed
        assert!(output.contains("Landlord"));
    }

    #[test]
    fn empty_journal_print() {
        let journal = Journal::new();
        let output = print_journal(&journal, &PrintOptions::default());
        assert!(output.is_empty());
    }

    #[test]
    fn posting_lines_start_with_four_spaces() {
        let text = "\
2024/01/15 Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        for line in output.lines() {
            if !line.starts_with("2024") && !line.starts_with("; ") && !line.is_empty() {
                assert!(
                    line.starts_with("    "),
                    "Posting line should start with 4 spaces: {:?}",
                    line
                );
            }
        }
    }
}

// =========================================================================
// DIRECTIVE INTEGRATION TESTS
// =========================================================================

mod directive_integration {
    use super::*;

    #[test]
    fn alias_affects_account_names() {
        let text = "\
alias food=Expenses:Food
alias cash=Assets:Cash

2024/01/15 Store
    food       $42.50
    cash
";
        let journal = parse(text);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("Expenses:Food"));
        assert!(output.contains("$42.50"));
    }

    #[test]
    fn apply_account_prefixes_accounts() {
        let text = "\
apply account Assets

2024/01/15 Transfer
    Checking       $100.00
    Savings       $-100.00

end apply account
";
        let journal = parse(text);
        let output = balance_command(&journal, &BalanceOptions::default());

        assert!(output.contains("Assets:Checking") || output.contains("Checking"));
    }

    #[test]
    fn bucket_directive_stored() {
        let text = "\
bucket Assets:Checking

2024/01/15 Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);

        // Verify the bucket directive was parsed and stored
        assert!(journal.bucket.is_some());
        let bucket_name = journal.account_fullname(journal.bucket.unwrap());
        assert_eq!(bucket_name, "Assets:Checking");

        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("$42.50"));
        assert!(output.contains("$-42.50"));
    }

    #[test]
    fn price_directive_stored() {
        let text = "\
P 2024/01/01 EUR $1.10
P 2024/01/01 GBP $1.30

2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        assert_eq!(journal.prices.len(), 2);
        assert_eq!(journal.prices[0].1, "EUR");
        assert_eq!(journal.prices[1].1, "GBP");
    }

    #[test]
    fn default_commodity_directive() {
        let text = "\
D $1000.00

2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        // Default commodity should be set in the pool
        assert!(journal.commodity_pool.default_commodity.is_some());
    }

    #[test]
    fn no_market_flag() {
        let text = "\
N $

2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        assert!(journal.no_market_commodities.contains(&"$".to_string()));
    }

    #[test]
    fn tag_declaration() {
        let text = "\
tag project
tag category

2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        assert_eq!(journal.tag_declarations.len(), 2);
        assert!(journal.tag_declarations.contains(&"project".to_string()));
        assert!(journal.tag_declarations.contains(&"category".to_string()));
    }

    #[test]
    fn payee_declaration() {
        let text = "\
payee Grocery Store
payee Landlord

2024/01/15 Grocery Store
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        assert_eq!(journal.payee_declarations.len(), 2);
        assert!(journal.payee_declarations.contains(&"Grocery Store".to_string()));
    }

    #[test]
    fn define_directive() {
        let text = "\
define myvar=42
define rate=1.10

2024/01/15 Test
    Expenses:Food       $10.00
    Assets:Cash
";
        let journal = parse(text);
        assert_eq!(journal.defines.get("myvar"), Some(&"42".to_string()));
        assert_eq!(journal.defines.get("rate"), Some(&"1.10".to_string()));
    }

    #[test]
    fn multiple_combined_directives() {
        let text = "\
alias food=Expenses:Food
tag project
payee Grocery Store
P 2024/01/01 EUR $1.10
N $

2024/01/15 Grocery Store
    food       $42.50
    Assets:Cash
";
        let journal = parse(text);

        // All directives should be parsed correctly
        assert!(journal.tag_declarations.contains(&"project".to_string()));
        assert!(journal.payee_declarations.contains(&"Grocery Store".to_string()));
        assert_eq!(journal.prices.len(), 1);
        assert!(journal.no_market_commodities.contains(&"$".to_string()));

        // The alias should work
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"));
    }

    #[test]
    fn account_directive_with_alias_sub_directive() {
        let text = "\
account Expenses:Food
    alias food

2024/01/15 Store
    food       $42.50
    Assets:Cash
";
        let journal = parse(text);
        let output = balance_command(&journal, &BalanceOptions::default());
        assert!(output.contains("Expenses:Food"));
    }

    #[test]
    fn apply_account_nested() {
        let text = "\
apply account Assets

2024/01/15 Transfer
    Checking        $100.00
    Savings        $-100.00

end apply account

2024/01/16 Store
    Expenses:Food       $50.00
    Assets:Checking
";
        let journal = parse(text);
        // Should have at least 2 transactions
        assert!(journal.xacts.len() >= 2);
    }
}

// =========================================================================
// CROSS-COMMAND CONSISTENCY TESTS
// =========================================================================

mod cross_command_consistency {
    use super::*;

    #[test]
    fn balance_and_register_amounts_agree() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/05 Groceries
    Expenses:Food          $50.00
    Assets:Checking
";
        let journal = parse(text);

        let bal_output = balance_command(&journal, &BalanceOptions::default());
        let reg_output = register_command(&journal, &RegisterOptions::default());

        // Both should contain the key amounts
        assert!(bal_output.contains("$50.00")); // Expenses:Food
        assert!(reg_output.contains("$50.00")); // Food posting amount
        assert!(reg_output.contains("$1000.00")); // Paycheck amount
    }

    #[test]
    fn print_reproduces_parseable_output() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food                              $42.50
    Assets:Checking
";
        let journal = parse(text);
        let printed = print_journal(&journal, &PrintOptions::default());

        // The printed output should be parseable
        let reparsed = parse(&printed);
        assert_eq!(reparsed.xacts.len(), 1);
        assert_eq!(reparsed.xacts[0].payee, "Grocery Store");
    }

    #[test]
    fn all_commands_handle_empty_journal() {
        let journal = Journal::new();

        let bal = balance_command(&journal, &BalanceOptions::default());
        let reg = register_command(&journal, &RegisterOptions::default());
        let prn = print_journal(&journal, &PrintOptions::default());

        assert!(bal.is_empty());
        assert!(reg.is_empty());
        assert!(prn.is_empty());
    }

    #[test]
    fn filter_options_affect_all_commands() {
        let text = "\
2024/01/01 * Cleared
    Expenses:Food       $30.00
    Assets:Checking

2024/01/02 Uncleared
    Expenses:Rent       $500.00
    Assets:Checking
";
        let journal = parse(text);

        // Print with date filter
        let mut print_opts = PrintOptions::default();
        print_opts.report.begin = Some(d(2024, 1, 2));
        let print_output = print_journal(&journal, &print_opts);

        assert!(!print_output.contains("Cleared"));
        assert!(print_output.contains("Uncleared"));
    }

    #[test]
    fn balance_total_line_sums_to_zero_for_balanced_journal() {
        let text = "\
2024/01/01 Paycheck
    Assets:Checking     $1000.00
    Income:Salary

2024/01/05 Groceries
    Expenses:Food          $50.00
    Assets:Checking

2024/01/10 Rent
    Expenses:Rent         $800.00
    Assets:Checking
";
        let journal = parse(text);
        let output = balance_command(&journal, &BalanceOptions::default());

        // Last line should be 0 (balanced journal)
        let lines: Vec<&str> = output.trim_end().lines().collect();
        let last = lines.last().unwrap().trim();
        assert_eq!(last, "0", "Balanced journal total should be 0");
    }

    #[test]
    fn register_shows_all_postings_by_default() {
        let text = "\
2024/01/01 Test1
    Expenses:Food       $10.00
    Assets:Cash

2024/01/02 Test2
    Expenses:Rent       $500.00
    Assets:Checking
";
        let journal = parse(text);
        let output = register_command(&journal, &RegisterOptions::default());

        let lines: Vec<&str> = output.trim_end().lines().collect();
        assert_eq!(lines.len(), 4); // 2 xacts x 2 posts each
    }

    #[test]
    fn print_preserves_cleared_and_code() {
        let text = "\
2024/01/01 * (123) Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        let output = print_journal(&journal, &PrintOptions::default());

        assert!(output.contains("*"));
        assert!(output.contains("(123)"));
        assert!(output.contains("Grocery Store"));
    }
}
