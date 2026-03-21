//! muonledger CLI -- balance, register, and print reports.

use std::path::Path;
use std::process;

use clap::{Parser, Subcommand};

use muonledger::commands::balance::{balance_command, BalanceOptions};
use muonledger::commands::register::{register_command, RegisterOptions};
use muonledger::journal::Journal;
use muonledger::parser::TextualParser;

// ---------------------------------------------------------------------------
// CLI definition
// ---------------------------------------------------------------------------

#[derive(Parser)]
#[command(name = "muonledger", version = "0.1.0", about = "Plain-text accounting")]
struct Cli {
    /// Path to the journal file.
    #[arg(short = 'f', long = "file")]
    file: String,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Show account balances.
    #[command(alias = "bal")]
    Balance {
        /// Flat (non-hierarchical) output.
        #[arg(long)]
        flat: bool,

        /// Suppress the total line.
        #[arg(long = "no-total")]
        no_total: bool,

        /// Show accounts with zero balances.
        #[arg(short = 'E', long = "empty")]
        empty: bool,

        /// Limit display depth (0 = unlimited).
        #[arg(long, default_value_t = 0)]
        depth: usize,

        /// Account filter patterns.
        #[arg(trailing_var_arg = true)]
        patterns: Vec<String>,
    },

    /// Show postings chronologically with running totals.
    #[command(alias = "reg")]
    Register {
        /// Wide (132-column) layout.
        #[arg(short = 'w', long)]
        wide: bool,

        /// Limit to first N postings.
        #[arg(long)]
        head: Option<usize>,

        /// Limit to last N postings.
        #[arg(long)]
        tail: Option<usize>,

        /// Account filter patterns.
        #[arg(trailing_var_arg = true)]
        patterns: Vec<String>,
    },

    /// Print transactions (pass-through format).
    Print {
        /// Account filter patterns.
        #[arg(trailing_var_arg = true)]
        patterns: Vec<String>,
    },
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    let cli = Cli::parse();

    // Parse journal file.
    let path = Path::new(&cli.file);
    let mut journal = Journal::new();
    let parser = TextualParser::new();

    if let Err(e) = parser.parse_file(path, &mut journal) {
        eprintln!("Error parsing {}: {} (line {})", cli.file, e.message, e.line_num);
        process::exit(1);
    }

    match cli.command {
        Command::Balance {
            flat,
            no_total,
            empty,
            depth,
            patterns,
        } => {
            let opts = BalanceOptions {
                flat,
                no_total,
                show_empty: empty,
                depth,
                patterns,
            };
            let output = balance_command(&journal, &opts);
            print!("{}", output);
        }
        Command::Register {
            wide,
            head,
            tail,
            patterns,
        } => {
            let opts = RegisterOptions {
                wide,
                head,
                tail,
                account_patterns: patterns,
            };
            let output = register_command(&journal, &opts);
            print!("{}", output);
        }
        Command::Print { patterns: _ } => {
            // Simple print: output transactions in ledger format.
            for xact in &journal.xacts {
                if let Some(date) = &xact.item.date {
                    print!("{}", date.format("%Y/%m/%d"));
                }
                println!(" {}", xact.payee);
                for post in &xact.posts {
                    let acct_name = match post.account_id {
                        Some(id) => journal.accounts.fullname(id),
                        None => "<unknown>".to_string(),
                    };
                    let amt_str = match &post.amount {
                        Some(a) if !a.is_null() => a.to_string(),
                        _ => String::new(),
                    };
                    if amt_str.is_empty() {
                        println!("    {}", acct_name);
                    } else {
                        println!("    {:40}  {}", acct_name, amt_str);
                    }
                }
                println!();
            }
        }
    }
}
