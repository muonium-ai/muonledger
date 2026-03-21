//! muonledger — Rust port of the MuonLedger accounting engine.
//!
//! This crate provides the core data structures and logic for double-entry
//! bookkeeping with arbitrary-precision arithmetic.

pub mod account;
pub mod amount;
pub mod balance;
pub mod commodity;
pub mod item;
pub mod journal;
pub mod post;
pub mod value;
pub mod xact;

#[cfg(test)]
mod tests {
    #[test]
    fn skeleton_builds() {
        assert_eq!(1 + 1, 2);
    }
}
