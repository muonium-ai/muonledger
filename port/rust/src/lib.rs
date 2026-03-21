//! muonledger — Rust port of the MuonLedger accounting engine.
//!
//! This crate provides the core data structures and logic for double-entry
//! bookkeeping with arbitrary-precision arithmetic.

pub mod account;
pub mod amount;
pub mod auto_xact;
pub mod balance;
pub mod commands;
pub mod commodity;
pub mod expr_ast;
pub mod expr_parser;
pub mod expr_token;
pub mod filters;
pub mod format;
pub mod item;
pub mod journal;
pub mod lot;
pub mod parser;
pub mod periodic_xact;
pub mod post;
pub mod query;
pub mod report;
pub mod scope;
pub mod value;
pub mod xact;

#[cfg(test)]
mod tests {
    #[test]
    fn skeleton_builds() {
        assert_eq!(1 + 1, 2);
    }
}
