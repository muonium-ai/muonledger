//! Multi-commodity balance for double-entry accounting.
//!
//! This module provides the `Balance` type, a Rust port of Ledger's
//! `balance_t`. A balance holds amounts across multiple commodities
//! simultaneously -- something that `Amount` cannot do (it panics if you
//! add two amounts with different commodities).
//!
//! Internally the amounts are stored in a `BTreeMap` keyed by commodity
//! symbol (String), giving deterministic iteration order. Arithmetic
//! operators delegate to the per-commodity Amount operations, so all
//! precision and rounding rules of Amount are preserved.

use std::collections::BTreeMap;
use std::fmt;
use std::ops::{Add, Neg, Sub};

use crate::amount::Amount;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error type for invalid balance operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BalanceError(pub String);

impl fmt::Display for BalanceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "BalanceError: {}", self.0)
    }
}

impl std::error::Error for BalanceError {}

// ---------------------------------------------------------------------------
// Balance
// ---------------------------------------------------------------------------

/// Multi-commodity balance.
///
/// Stores one `Amount` per commodity symbol. Adding amounts of the same
/// commodity accumulates them; adding amounts of different commodities
/// creates separate entries. Zero-valued entries are automatically removed
/// after each operation.
#[derive(Debug, Clone)]
pub struct Balance {
    amounts: BTreeMap<String, Amount>,
}

impl Balance {
    // ---- construction ------------------------------------------------------

    /// Create an empty balance.
    pub fn new() -> Self {
        Self {
            amounts: BTreeMap::new(),
        }
    }

    /// Create a balance from a single amount.
    ///
    /// Returns an error if the amount is null (uninitialized).
    /// If the amount is zero, returns an empty balance.
    pub fn from_amount(amt: &Amount) -> Result<Self, BalanceError> {
        if amt.is_null() {
            return Err(BalanceError(
                "Cannot initialize a balance from an uninitialized amount".into(),
            ));
        }
        let mut bal = Self::new();
        if !amt.is_realzero() {
            let key = Self::commodity_key(amt);
            bal.amounts.insert(key, amt.clone());
        }
        Ok(bal)
    }

    /// Create a balance by copying another balance.
    pub fn from_balance(other: &Balance) -> Self {
        Self {
            amounts: other.amounts.clone(),
        }
    }

    /// Create a balance from a map of commodity -> Amount.
    pub fn from_map(map: BTreeMap<String, Amount>) -> Self {
        let mut bal = Self::new();
        for (k, v) in map {
            if !v.is_realzero() {
                bal.amounts.insert(k, v);
            }
        }
        bal
    }

    // ---- internal helpers --------------------------------------------------

    /// Return the dict key for an Amount's commodity.
    fn commodity_key(amt: &Amount) -> String {
        amt.commodity().unwrap_or("").to_string()
    }

    /// Add a single Amount into this balance (in-place).
    fn add_amount_inplace(&mut self, amt: &Amount) -> Result<(), BalanceError> {
        if amt.is_null() {
            return Err(BalanceError(
                "Cannot add an uninitialized amount to a balance".into(),
            ));
        }
        if amt.is_realzero() {
            return Ok(());
        }

        let key = Self::commodity_key(amt);
        if let Some(existing) = self.amounts.get(&key) {
            let sum = existing + amt;
            if sum.is_realzero() {
                self.amounts.remove(&key);
            } else {
                self.amounts.insert(key, sum);
            }
        } else {
            self.amounts.insert(key, amt.clone());
        }
        Ok(())
    }

    /// Subtract a single Amount from this balance (in-place).
    fn subtract_amount_inplace(&mut self, amt: &Amount) -> Result<(), BalanceError> {
        if amt.is_null() {
            return Err(BalanceError(
                "Cannot subtract an uninitialized amount from a balance".into(),
            ));
        }
        if amt.is_realzero() {
            return Ok(());
        }

        let key = Self::commodity_key(amt);
        if let Some(existing) = self.amounts.get(&key) {
            let diff = existing - amt;
            if diff.is_realzero() {
                self.amounts.remove(&key);
            } else {
                self.amounts.insert(key, diff);
            }
        } else {
            self.amounts.insert(key, amt.negated());
        }
        Ok(())
    }

    // ---- public add / subtract ---------------------------------------------

    /// Add an Amount to this balance in-place.
    pub fn add_amount(&mut self, amt: &Amount) -> Result<(), BalanceError> {
        self.add_amount_inplace(amt)
    }

    /// Add another Balance to this balance in-place.
    pub fn add_balance(&mut self, other: &Balance) {
        for amt in other.amounts.values() {
            // Amounts from a valid balance should never be null.
            self.add_amount_inplace(amt)
                .expect("Balance contained a null amount");
        }
    }

    /// Subtract an Amount from this balance in-place.
    pub fn subtract_amount(&mut self, amt: &Amount) -> Result<(), BalanceError> {
        self.subtract_amount_inplace(amt)
    }

    /// Subtract another Balance from this balance in-place.
    pub fn subtract_balance(&mut self, other: &Balance) {
        for amt in other.amounts.values() {
            self.subtract_amount_inplace(amt)
                .expect("Balance contained a null amount");
        }
    }

    // ---- scalar multiply / divide ------------------------------------------

    /// Multiply all component amounts by a scalar Amount.
    ///
    /// The scalar must not have a commodity.
    pub fn multiply(&self, scalar: &Amount) -> Result<Balance, BalanceError> {
        if scalar.has_commodity() {
            return Err(BalanceError(
                "Cannot multiply a balance by a commoditized amount".into(),
            ));
        }
        let mut result = Balance::new();
        for (key, amt) in &self.amounts {
            let product = amt * scalar;
            if !product.is_realzero() {
                result.amounts.insert(key.clone(), product);
            }
        }
        Ok(result)
    }

    /// Divide all component amounts by a scalar Amount.
    ///
    /// The scalar must not have a commodity and must not be zero.
    pub fn divide(&self, scalar: &Amount) -> Result<Balance, BalanceError> {
        if scalar.has_commodity() {
            return Err(BalanceError(
                "Cannot divide a balance by a commoditized amount".into(),
            ));
        }
        if scalar.is_realzero() {
            return Err(BalanceError("Divide by zero".into()));
        }
        let mut result = Balance::new();
        for (key, amt) in &self.amounts {
            let quotient = amt / scalar;
            if !quotient.is_realzero() {
                result.amounts.insert(key.clone(), quotient);
            }
        }
        Ok(result)
    }

    // ---- unary operations --------------------------------------------------

    /// Return a negated copy.
    pub fn negated(&self) -> Self {
        let mut result = Balance::new();
        for (key, amt) in &self.amounts {
            result.amounts.insert(key.clone(), amt.negated());
        }
        result
    }

    /// Negate all component amounts in-place.
    pub fn negate(&mut self) {
        for amt in self.amounts.values_mut() {
            amt.in_place_negate();
        }
    }

    /// Return the absolute value of the balance.
    pub fn abs(&self) -> Self {
        let mut result = Balance::new();
        for amt in self.amounts.values() {
            let abs_amt = amt.abs();
            result
                .add_amount_inplace(&abs_amt)
                .expect("abs produced null amount");
        }
        result
    }

    // ---- truth tests -------------------------------------------------------

    /// True if all commodity amounts are zero (at display precision).
    pub fn is_zero(&self) -> bool {
        if self.amounts.is_empty() {
            return true;
        }
        self.amounts.values().all(|a| a.is_zero())
    }

    /// True if no amounts are stored.
    pub fn is_empty(&self) -> bool {
        self.amounts.is_empty()
    }

    /// True if any commodity amount is non-zero.
    pub fn is_nonzero(&self) -> bool {
        if self.amounts.is_empty() {
            return false;
        }
        self.amounts.values().any(|a| a.is_nonzero())
    }

    // ---- commodity queries -------------------------------------------------

    /// Return the Amount if exactly one commodity, else None.
    pub fn single_amount(&self) -> Option<&Amount> {
        if self.amounts.len() == 1 {
            self.amounts.values().next()
        } else {
            None
        }
    }

    /// Convert to a single Amount.
    ///
    /// Returns an error if the balance is empty or contains multiple commodities.
    pub fn to_amount(&self) -> Result<Amount, BalanceError> {
        if self.is_empty() {
            return Err(BalanceError(
                "Cannot convert an empty balance to an amount".into(),
            ));
        }
        if self.amounts.len() == 1 {
            Ok(self.amounts.values().next().unwrap().clone())
        } else {
            Err(BalanceError(
                "Cannot convert a balance with multiple commodities to an amount".into(),
            ))
        }
    }

    /// Return the number of distinct commodities.
    pub fn commodity_count(&self) -> usize {
        self.amounts.len()
    }

    /// Return a clone of the internal commodity-to-Amount mapping.
    pub fn amounts(&self) -> BTreeMap<String, Amount> {
        self.amounts.clone()
    }

    /// Get the Amount for a given commodity symbol.
    pub fn get(&self, commodity: &str) -> Option<&Amount> {
        self.amounts.get(commodity)
    }

    /// Check if a commodity is present.
    pub fn contains(&self, commodity: &str) -> bool {
        self.amounts.contains_key(commodity)
    }

    /// Number of commodities in the balance.
    pub fn len(&self) -> usize {
        self.amounts.len()
    }

    // ---- rounding ----------------------------------------------------------

    /// Return a copy with all amounts rounded to their display precision.
    pub fn rounded(&self) -> Self {
        let mut result = Balance::new();
        for (key, amt) in &self.amounts {
            result.amounts.insert(key.clone(), amt.rounded());
        }
        result
    }

    /// Return a copy with all amounts rounded to `precision` places.
    pub fn roundto(&self, precision: u32) -> Self {
        let mut result = Balance::new();
        for (key, amt) in &self.amounts {
            result.amounts.insert(key.clone(), amt.roundto(precision));
        }
        result
    }

    // ---- iteration ---------------------------------------------------------

    /// Iterate over the Amounts in sorted commodity order.
    pub fn iter(&self) -> impl Iterator<Item = &Amount> {
        self.amounts.values()
    }

    /// Iterate over (commodity, Amount) pairs in sorted order.
    pub fn iter_with_commodity(&self) -> impl Iterator<Item = (&String, &Amount)> {
        self.amounts.iter()
    }
}

// ---------------------------------------------------------------------------
// Default
// ---------------------------------------------------------------------------

impl Default for Balance {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// From traits
// ---------------------------------------------------------------------------

impl From<Amount> for Balance {
    fn from(amt: Amount) -> Self {
        Balance::from_amount(&amt).unwrap_or_else(|_| Balance::new())
    }
}

impl From<&Amount> for Balance {
    fn from(amt: &Amount) -> Self {
        Balance::from_amount(amt).unwrap_or_else(|_| Balance::new())
    }
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

impl fmt::Display for Balance {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.amounts.is_empty() {
            return write!(f, "0");
        }
        let parts: Vec<String> = self.amounts.values().map(|a| a.to_string()).collect();
        write!(f, "{}", parts.join("\n"))
    }
}

// ---------------------------------------------------------------------------
// PartialEq
// ---------------------------------------------------------------------------

impl PartialEq for Balance {
    fn eq(&self, other: &Self) -> bool {
        self.amounts == other.amounts
    }
}

impl Eq for Balance {}

impl PartialEq<Amount> for Balance {
    fn eq(&self, other: &Amount) -> bool {
        if other.is_realzero() {
            return self.is_empty();
        }
        if self.amounts.len() == 1 {
            let key = Self::commodity_key(other);
            if let Some(existing) = self.amounts.get(&key) {
                return existing == other;
            }
        }
        false
    }
}

// ---------------------------------------------------------------------------
// Neg
// ---------------------------------------------------------------------------

impl Neg for Balance {
    type Output = Balance;
    fn neg(self) -> Balance {
        self.negated()
    }
}

impl Neg for &Balance {
    type Output = Balance;
    fn neg(self) -> Balance {
        self.negated()
    }
}

// ---------------------------------------------------------------------------
// Add
// ---------------------------------------------------------------------------

impl Add for &Balance {
    type Output = Balance;
    fn add(self, rhs: &Balance) -> Balance {
        let mut result = self.clone();
        result.add_balance(rhs);
        result
    }
}

impl Add for Balance {
    type Output = Balance;
    fn add(self, rhs: Balance) -> Balance {
        (&self).add(&rhs)
    }
}

impl Add<&Amount> for &Balance {
    type Output = Balance;
    fn add(self, rhs: &Amount) -> Balance {
        let mut result = self.clone();
        result
            .add_amount(rhs)
            .expect("Cannot add uninitialized amount to balance");
        result
    }
}

impl Add<Amount> for Balance {
    type Output = Balance;
    fn add(self, rhs: Amount) -> Balance {
        (&self).add(&rhs)
    }
}

// ---------------------------------------------------------------------------
// Sub
// ---------------------------------------------------------------------------

impl Sub for &Balance {
    type Output = Balance;
    fn sub(self, rhs: &Balance) -> Balance {
        let mut result = self.clone();
        result.subtract_balance(rhs);
        result
    }
}

impl Sub for Balance {
    type Output = Balance;
    fn sub(self, rhs: Balance) -> Balance {
        (&self).sub(&rhs)
    }
}

impl Sub<&Amount> for &Balance {
    type Output = Balance;
    fn sub(self, rhs: &Amount) -> Balance {
        let mut result = self.clone();
        result
            .subtract_amount(rhs)
            .expect("Cannot subtract uninitialized amount from balance");
        result
    }
}

impl Sub<Amount> for Balance {
    type Output = Balance;
    fn sub(self, rhs: Amount) -> Balance {
        (&self).sub(&rhs)
    }
}

// ---------------------------------------------------------------------------
// IntoIterator
// ---------------------------------------------------------------------------

impl<'a> IntoIterator for &'a Balance {
    type Item = &'a Amount;
    type IntoIter = std::collections::btree_map::Values<'a, String, Amount>;

    fn into_iter(self) -> Self::IntoIter {
        self.amounts.values()
    }
}

impl IntoIterator for Balance {
    type Item = (String, Amount);
    type IntoIter = std::collections::btree_map::IntoIter<String, Amount>;

    fn into_iter(self) -> Self::IntoIter {
        self.amounts.into_iter()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn usd(val: &str) -> Amount {
        Amount::parse(&format!("${}", val)).unwrap()
    }

    fn eur(val: &str) -> Amount {
        Amount::parse(&format!("{} EUR", val)).unwrap()
    }

    fn bare(val: &str) -> Amount {
        Amount::parse(val).unwrap()
    }

    // ---- construction -------------------------------------------------------

    #[test]
    fn new_balance_is_empty() {
        let b = Balance::new();
        assert!(b.is_empty());
        assert!(b.is_zero());
        assert!(!b.is_nonzero());
        assert_eq!(b.len(), 0);
    }

    #[test]
    fn from_amount_single() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        assert_eq!(b.len(), 1);
        assert!(b.contains("$"));
        assert!(!b.is_empty());
        assert!(b.is_nonzero());
    }

    #[test]
    fn from_amount_zero_is_empty() {
        let b = Balance::from_amount(&usd("0.00")).unwrap();
        assert!(b.is_empty());
    }

    #[test]
    fn from_amount_null_errors() {
        let null = Amount::null();
        assert!(Balance::from_amount(&null).is_err());
    }

    #[test]
    fn from_balance_clones() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let b2 = Balance::from_balance(&b1);
        assert_eq!(b1, b2);
    }

    #[test]
    fn from_trait() {
        let b: Balance = usd("5.00").into();
        assert_eq!(b.len(), 1);
    }

    // ---- add / subtract ----------------------------------------------------

    #[test]
    fn add_same_commodity() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&usd("5.00")).unwrap();
        assert_eq!(b.len(), 1);
        let amt = b.to_amount().unwrap();
        assert_eq!(amt.to_string(), "$15.00");
    }

    #[test]
    fn add_different_commodities() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&eur("20.00")).unwrap();
        assert_eq!(b.len(), 2);
        assert!(b.contains("$"));
        assert!(b.contains("EUR"));
    }

    #[test]
    fn add_cancels_to_zero() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&usd("-10.00")).unwrap();
        assert!(b.is_empty());
        assert!(b.is_zero());
    }

    #[test]
    fn subtract_amount() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.subtract_amount(&usd("3.00")).unwrap();
        let amt = b.to_amount().unwrap();
        assert_eq!(amt.to_string(), "$7.00");
    }

    #[test]
    fn subtract_new_commodity() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.subtract_amount(&eur("5.00")).unwrap();
        assert_eq!(b.len(), 2);
        // EUR should be negative
        let eur_amt = b.get("EUR").unwrap();
        assert!(eur_amt.is_negative());
    }

    #[test]
    fn add_balance() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let mut b2 = Balance::from_amount(&eur("20.00")).unwrap();
        b2.add_balance(&b1);
        assert_eq!(b2.len(), 2);
    }

    #[test]
    fn subtract_balance() {
        let mut b1 = Balance::new();
        b1.add_amount(&usd("10.00")).unwrap();
        b1.add_amount(&eur("20.00")).unwrap();

        let mut b2 = Balance::new();
        b2.add_amount(&usd("10.00")).unwrap();
        b2.add_amount(&eur("20.00")).unwrap();

        b1.subtract_balance(&b2);
        assert!(b1.is_empty());
    }

    // ---- operators ---------------------------------------------------------

    #[test]
    fn add_operator() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let b2 = Balance::from_amount(&usd("5.00")).unwrap();
        let b3 = &b1 + &b2;
        assert_eq!(b3.to_amount().unwrap().to_string(), "$15.00");
    }

    #[test]
    fn sub_operator() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let b2 = Balance::from_amount(&usd("3.00")).unwrap();
        let b3 = &b1 - &b2;
        assert_eq!(b3.to_amount().unwrap().to_string(), "$7.00");
    }

    #[test]
    fn add_amount_operator() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let result = &b + &eur("5.00");
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn neg_operator() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let neg = -&b;
        let amt = neg.to_amount().unwrap();
        assert!(amt.is_negative());
    }

    // ---- multiply / divide -------------------------------------------------

    #[test]
    fn multiply_by_scalar() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let scalar = bare("2");
        let result = b.multiply(&scalar).unwrap();
        assert_eq!(result.to_amount().unwrap().to_string(), "$20.00");
    }

    #[test]
    fn multiply_by_commoditized_errors() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        assert!(b.multiply(&usd("2.00")).is_err());
    }

    #[test]
    fn divide_by_scalar() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let scalar = bare("2");
        let result = b.divide(&scalar).unwrap();
        let amt = result.to_amount().unwrap();
        // Should be $5.00 (rational arithmetic)
        assert!(amt.to_string().contains("5"));
    }

    #[test]
    fn divide_by_zero_errors() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let scalar = bare("0");
        assert!(b.divide(&scalar).is_err());
    }

    // ---- truth tests -------------------------------------------------------

    #[test]
    fn is_zero_empty() {
        assert!(Balance::new().is_zero());
    }

    #[test]
    fn is_nonzero_with_value() {
        let b = Balance::from_amount(&usd("1.00")).unwrap();
        assert!(b.is_nonzero());
        assert!(!b.is_zero());
    }

    // ---- commodity queries -------------------------------------------------

    #[test]
    fn single_amount_one_commodity() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        assert!(b.single_amount().is_some());
    }

    #[test]
    fn single_amount_multiple_commodities() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&eur("20.00")).unwrap();
        assert!(b.single_amount().is_none());
    }

    #[test]
    fn to_amount_empty_errors() {
        assert!(Balance::new().to_amount().is_err());
    }

    #[test]
    fn to_amount_multiple_errors() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&eur("20.00")).unwrap();
        assert!(b.to_amount().is_err());
    }

    // ---- negate ------------------------------------------------------------

    #[test]
    fn negate_in_place() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.negate();
        let amt = b.to_amount().unwrap();
        assert!(amt.is_negative());
    }

    #[test]
    fn negated_copy() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let neg = b.negated();
        // Original unchanged
        assert!(b.to_amount().unwrap().is_positive());
        assert!(neg.to_amount().unwrap().is_negative());
    }

    // ---- abs ---------------------------------------------------------------

    #[test]
    fn abs_negative() {
        let b = Balance::from_amount(&usd("-10.00")).unwrap();
        let a = b.abs();
        assert!(a.to_amount().unwrap().is_positive());
    }

    // ---- display -----------------------------------------------------------

    #[test]
    fn display_empty() {
        assert_eq!(Balance::new().to_string(), "0");
    }

    #[test]
    fn display_single() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        assert_eq!(b.to_string(), "$10.00");
    }

    #[test]
    fn display_multiple() {
        let mut b = Balance::from_amount(&usd("10.00")).unwrap();
        b.add_amount(&eur("20.00")).unwrap();
        let s = b.to_string();
        assert!(s.contains("$10.00"));
        assert!(s.contains("20.00 EUR"));
    }

    // ---- equality ----------------------------------------------------------

    #[test]
    fn balance_eq() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let b2 = Balance::from_amount(&usd("10.00")).unwrap();
        assert_eq!(b1, b2);
    }

    #[test]
    fn balance_ne() {
        let b1 = Balance::from_amount(&usd("10.00")).unwrap();
        let b2 = Balance::from_amount(&usd("20.00")).unwrap();
        assert_ne!(b1, b2);
    }

    #[test]
    fn balance_eq_amount() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        assert!(b == usd("10.00"));
    }

    #[test]
    fn balance_eq_zero_amount() {
        let b = Balance::new();
        let zero = Amount::from_int(0);
        assert!(b == zero);
    }

    // ---- iteration ---------------------------------------------------------

    #[test]
    fn iterate_amounts() {
        let mut b = Balance::new();
        b.add_amount(&usd("10.00")).unwrap();
        b.add_amount(&eur("20.00")).unwrap();

        let amounts: Vec<&Amount> = b.iter().collect();
        assert_eq!(amounts.len(), 2);
    }

    #[test]
    fn into_iter_ref() {
        let b = Balance::from_amount(&usd("10.00")).unwrap();
        let mut count = 0;
        for _amt in &b {
            count += 1;
        }
        assert_eq!(count, 1);
    }

    // ---- rounding ----------------------------------------------------------

    #[test]
    fn roundto() {
        let b = Balance::from_amount(&usd("10.005")).unwrap();
        let r = b.roundto(2);
        assert_eq!(r.len(), 1);
    }

    // ---- add null amount errors --------------------------------------------

    #[test]
    fn add_null_amount_errors() {
        let mut b = Balance::new();
        assert!(b.add_amount(&Amount::null()).is_err());
    }

    #[test]
    fn subtract_null_amount_errors() {
        let mut b = Balance::new();
        assert!(b.subtract_amount(&Amount::null()).is_err());
    }

    // ---- add zero is no-op -------------------------------------------------

    #[test]
    fn add_zero_no_op() {
        let mut b = Balance::new();
        b.add_amount(&usd("0.00")).unwrap();
        assert!(b.is_empty());
    }
}
