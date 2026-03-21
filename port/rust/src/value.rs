//! Polymorphic value type for the expression engine.
//!
//! This module provides the `Value` enum, a Rust port of Ledger's `value_t`.
//! A Value wraps any of the supported types (boolean, integer, amount, balance,
//! string, date, datetime, sequence) and performs automatic type promotion
//! during arithmetic so that mixed-type operations "just work".
//!
//! The promotion hierarchy for numeric types is:
//!     Integer -> Amount -> Balance

use std::fmt;

use chrono::NaiveDate;
use chrono::NaiveDateTime;

use crate::amount::Amount;
use crate::balance::Balance;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error type for invalid value operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValueError(pub String);

impl fmt::Display for ValueError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "ValueError: {}", self.0)
    }
}

impl std::error::Error for ValueError {}

// ---------------------------------------------------------------------------
// Value enum
// ---------------------------------------------------------------------------

/// Polymorphic value type with automatic type promotion.
///
/// Uses Rust's enum for type-safe tagged union semantics. The promotion
/// hierarchy for arithmetic is: Integer -> Amount -> Balance.
#[derive(Debug, Clone)]
pub enum Value {
    /// No value (uninitialized).
    Void,
    /// Boolean value.
    Boolean(bool),
    /// Integer value (64-bit).
    Integer(i64),
    /// Exact-precision commoditized amount.
    Amount(Amount),
    /// Multi-commodity balance.
    Balance(Balance),
    /// String value.
    Str(String),
    /// Date value.
    Date(NaiveDate),
    /// Date-time value.
    DateTime(NaiveDateTime),
    /// Sequence of values.
    Sequence(Vec<Value>),
}

/// Numeric rank for type promotion.
fn numeric_rank(v: &Value) -> Option<u8> {
    match v {
        Value::Integer(_) => Some(0),
        Value::Amount(_) => Some(1),
        Value::Balance(_) => Some(2),
        _ => None,
    }
}

impl Value {
    // ---- type queries -------------------------------------------------------

    /// True if the value is Void (uninitialized).
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Void)
    }

    /// True if the value is numerically zero or empty.
    pub fn is_zero(&self) -> bool {
        match self {
            Value::Void => true,
            Value::Boolean(b) => !b,
            Value::Integer(n) => *n == 0,
            Value::Amount(a) => a.is_zero(),
            Value::Balance(b) => b.is_zero(),
            Value::Str(s) => s.is_empty(),
            Value::Sequence(seq) => seq.is_empty(),
            _ => false,
        }
    }

    /// True if the value is non-zero.
    pub fn is_nonzero(&self) -> bool {
        !self.is_zero()
    }

    /// True if the value is exactly zero (no display-precision rounding).
    pub fn is_realzero(&self) -> bool {
        match self {
            Value::Void => true,
            Value::Boolean(b) => !b,
            Value::Integer(n) => *n == 0,
            Value::Amount(a) => a.is_realzero(),
            Value::Balance(b) => b.is_empty() || b.iter().all(|a| a.is_realzero()),
            Value::Str(s) => s.is_empty(),
            Value::Sequence(seq) => seq.is_empty(),
            _ => false,
        }
    }

    /// Truthiness of the value.
    pub fn to_bool(&self) -> bool {
        match self {
            Value::Void => false,
            Value::Boolean(b) => *b,
            Value::Integer(n) => *n != 0,
            Value::Amount(a) => a.is_nonzero(),
            Value::Balance(b) => b.is_nonzero(),
            Value::Str(s) => !s.is_empty(),
            Value::Date(_) | Value::DateTime(_) => true,
            Value::Sequence(seq) => seq.iter().any(|v| v.to_bool()),
        }
    }

    // ---- type coercion (to_*) -----------------------------------------------

    /// Convert to bool.
    pub fn to_boolean(&self) -> bool {
        self.to_bool()
    }

    /// Convert to i64.
    pub fn to_int(&self) -> Result<i64, ValueError> {
        match self {
            Value::Integer(n) => Ok(*n),
            Value::Boolean(b) => Ok(if *b { 1 } else { 0 }),
            Value::Amount(a) => a
                .to_long()
                .map_err(|e| ValueError(format!("Cannot convert Amount to int: {}", e))),
            Value::Void => Ok(0),
            _ => Err(ValueError(format!(
                "Cannot convert {} to int",
                self.type_name()
            ))),
        }
    }

    /// Convert to Amount.
    pub fn to_amount(&self) -> Result<Amount, ValueError> {
        match self {
            Value::Amount(a) => Ok(a.clone()),
            Value::Integer(n) => Ok(Amount::from_int(*n)),
            Value::Boolean(b) => Ok(Amount::from_int(if *b { 1 } else { 0 })),
            Value::Void => Ok(Amount::from_int(0)),
            _ => Err(ValueError(format!(
                "Cannot convert {} to Amount",
                self.type_name()
            ))),
        }
    }

    /// Convert to Balance.
    pub fn to_balance(&self) -> Result<Balance, ValueError> {
        match self {
            Value::Balance(b) => Ok(b.clone()),
            Value::Amount(a) => Balance::from_amount(a)
                .map_err(|e| ValueError(format!("Cannot convert Amount to Balance: {}", e))),
            Value::Integer(n) => {
                let a = Amount::from_int(*n);
                Ok(Balance::from(a))
            }
            Value::Void => Ok(Balance::new()),
            _ => Err(ValueError(format!(
                "Cannot convert {} to Balance",
                self.type_name()
            ))),
        }
    }

    /// Convert to String.
    pub fn to_string_value(&self) -> String {
        match self {
            Value::Void => String::new(),
            Value::Boolean(b) => if *b { "true" } else { "false" }.to_string(),
            Value::Integer(n) => n.to_string(),
            Value::Amount(a) => a.to_string(),
            Value::Balance(b) => b.to_string(),
            Value::Str(s) => s.clone(),
            Value::Date(d) => d.to_string(),
            Value::DateTime(dt) => dt.to_string(),
            Value::Sequence(seq) => {
                let parts: Vec<String> = seq.iter().map(|v| v.to_string_value()).collect();
                format!("[{}]", parts.join(", "))
            }
        }
    }

    /// Convert to NaiveDate.
    pub fn to_date(&self) -> Result<NaiveDate, ValueError> {
        match self {
            Value::Date(d) => Ok(*d),
            Value::DateTime(dt) => Ok(dt.date()),
            _ => Err(ValueError(format!(
                "Cannot convert {} to date",
                self.type_name()
            ))),
        }
    }

    /// Convert to NaiveDateTime.
    pub fn to_datetime(&self) -> Result<NaiveDateTime, ValueError> {
        match self {
            Value::DateTime(dt) => Ok(*dt),
            Value::Date(d) => Ok(d.and_hms_opt(0, 0, 0).unwrap()),
            _ => Err(ValueError(format!(
                "Cannot convert {} to datetime",
                self.type_name()
            ))),
        }
    }

    /// Convert to a sequence of Values.
    pub fn to_sequence(&self) -> Vec<Value> {
        match self {
            Value::Sequence(seq) => seq.clone(),
            Value::Void => vec![],
            other => vec![other.clone()],
        }
    }

    /// Return the type name as a string.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Void => "Void",
            Value::Boolean(_) => "Boolean",
            Value::Integer(_) => "Integer",
            Value::Amount(_) => "Amount",
            Value::Balance(_) => "Balance",
            Value::Str(_) => "String",
            Value::Date(_) => "Date",
            Value::DateTime(_) => "DateTime",
            Value::Sequence(_) => "Sequence",
        }
    }

    // ---- internal promotion helpers -----------------------------------------

    /// Promote this value's inner data to the target type.
    fn promote_to(&self, target: u8) -> Result<Value, ValueError> {
        match target {
            0 => Ok(Value::Integer(self.to_int()?)),
            1 => Ok(Value::Amount(self.to_amount()?)),
            2 => Ok(Value::Balance(self.to_balance()?)),
            _ => Err(ValueError("Invalid promotion target".into())),
        }
    }

    /// Coerce two numeric values to a common type.
    fn coerce_pair(left: &Value, right: &Value) -> Result<(Value, Value, u8), ValueError> {
        let lr = numeric_rank(left).ok_or_else(|| {
            ValueError(format!(
                "Cannot perform arithmetic between {} and {}",
                left.type_name(),
                right.type_name()
            ))
        })?;
        let rr = numeric_rank(right).ok_or_else(|| {
            ValueError(format!(
                "Cannot perform arithmetic between {} and {}",
                left.type_name(),
                right.type_name()
            ))
        })?;

        let target = std::cmp::max(lr, rr);
        let lv = if lr == target {
            left.clone()
        } else {
            left.promote_to(target)?
        };
        let rv = if rr == target {
            right.clone()
        } else {
            right.promote_to(target)?
        };
        Ok((lv, rv, target))
    }

    // ---- arithmetic ---------------------------------------------------------

    /// Add two values with automatic type promotion.
    pub fn value_add(&self, other: &Value) -> Result<Value, ValueError> {
        // VOID acts as identity
        if self.is_null() {
            return Ok(other.clone());
        }
        if other.is_null() {
            return Ok(self.clone());
        }

        // STRING concatenation
        if let Value::Str(s) = self {
            return Ok(Value::Str(format!("{}{}", s, other.to_string_value())));
        }

        // SEQUENCE + SEQUENCE
        if let (Value::Sequence(left_seq), Value::Sequence(right_seq)) = (self, other) {
            if left_seq.len() == right_seq.len() {
                let result: Result<Vec<Value>, ValueError> = left_seq
                    .iter()
                    .zip(right_seq.iter())
                    .map(|(a, b)| a.value_add(b))
                    .collect();
                return Ok(Value::Sequence(result?));
            }
            let mut combined = left_seq.clone();
            combined.extend(right_seq.iter().cloned());
            return Ok(Value::Sequence(combined));
        }
        if let Value::Sequence(seq) = self {
            let mut result = seq.clone();
            result.push(other.clone());
            return Ok(Value::Sequence(result));
        }

        // Numeric promotion
        let (lv, rv, target) = Self::coerce_pair(self, other)?;
        match target {
            0 => {
                // Integer + Integer
                if let (Value::Integer(a), Value::Integer(b)) = (&lv, &rv) {
                    return Ok(Value::Integer(a + b));
                }
            }
            1 => {
                // Amount + Amount -- may promote to Balance if different commodities
                if let (Value::Amount(a), Value::Amount(b)) = (&lv, &rv) {
                    if a.has_commodity()
                        && b.has_commodity()
                        && a.commodity() != b.commodity()
                    {
                        let mut bal = Balance::from_amount(a).map_err(|e| {
                            ValueError(format!("Balance promotion failed: {}", e))
                        })?;
                        bal.add_amount(b)
                            .map_err(|e| ValueError(format!("Balance add failed: {}", e)))?;
                        return Ok(Value::Balance(bal));
                    }
                    return Ok(Value::Amount(a + b));
                }
            }
            2 => {
                // Balance + Balance
                if let (Value::Balance(a), Value::Balance(b)) = (&lv, &rv) {
                    return Ok(Value::Balance(a + b));
                }
            }
            _ => {}
        }

        Err(ValueError(format!(
            "Cannot add {} and {}",
            self.type_name(),
            other.type_name()
        )))
    }

    /// Subtract two values with automatic type promotion.
    pub fn value_sub(&self, other: &Value) -> Result<Value, ValueError> {
        if self.is_null() {
            return other.value_neg();
        }
        if other.is_null() {
            return Ok(self.clone());
        }

        // SEQUENCE - SEQUENCE
        if let (Value::Sequence(left_seq), Value::Sequence(right_seq)) = (self, other) {
            if left_seq.len() == right_seq.len() {
                let result: Result<Vec<Value>, ValueError> = left_seq
                    .iter()
                    .zip(right_seq.iter())
                    .map(|(a, b)| a.value_sub(b))
                    .collect();
                return Ok(Value::Sequence(result?));
            }
            return Err(ValueError(
                "Cannot subtract sequences of different lengths".into(),
            ));
        }

        let (lv, rv, target) = Self::coerce_pair(self, other)?;
        match target {
            0 => {
                if let (Value::Integer(a), Value::Integer(b)) = (&lv, &rv) {
                    return Ok(Value::Integer(a - b));
                }
            }
            1 => {
                if let (Value::Amount(a), Value::Amount(b)) = (&lv, &rv) {
                    if a.has_commodity()
                        && b.has_commodity()
                        && a.commodity() != b.commodity()
                    {
                        let mut bal = Balance::from_amount(a).map_err(|e| {
                            ValueError(format!("Balance promotion failed: {}", e))
                        })?;
                        bal.subtract_amount(b)
                            .map_err(|e| ValueError(format!("Balance sub failed: {}", e)))?;
                        return Ok(Value::Balance(bal));
                    }
                    return Ok(Value::Amount(a - b));
                }
            }
            2 => {
                if let (Value::Balance(a), Value::Balance(b)) = (&lv, &rv) {
                    return Ok(Value::Balance(a - b));
                }
            }
            _ => {}
        }

        Err(ValueError(format!(
            "Cannot subtract {} from {}",
            other.type_name(),
            self.type_name()
        )))
    }

    /// Multiply two values with automatic type promotion.
    pub fn value_mul(&self, other: &Value) -> Result<Value, ValueError> {
        // STRING * INTEGER -> repeat
        if let (Value::Str(s), Value::Integer(n)) = (self, other) {
            if *n < 0 {
                return Err(ValueError("Cannot repeat string negative times".into()));
            }
            return Ok(Value::Str(s.repeat(*n as usize)));
        }

        // Balance can only be multiplied by a scalar
        if let Value::Balance(_) = self {
            if let Value::Balance(_) = other {
                return Err(ValueError("Cannot multiply two balances".into()));
            }
        }
        if let Value::Balance(bal) = self {
            let scalar = other.to_amount()?;
            let result = bal
                .multiply(&scalar)
                .map_err(|e| ValueError(format!("Balance multiply failed: {}", e)))?;
            return Ok(Value::Balance(result));
        }
        if let Value::Balance(bal) = other {
            let scalar = self.to_amount()?;
            let result = bal
                .multiply(&scalar)
                .map_err(|e| ValueError(format!("Balance multiply failed: {}", e)))?;
            return Ok(Value::Balance(result));
        }

        let (lv, rv, target) = Self::coerce_pair(self, other)?;
        match target {
            0 => {
                if let (Value::Integer(a), Value::Integer(b)) = (&lv, &rv) {
                    return Ok(Value::Integer(a * b));
                }
            }
            1 => {
                if let (Value::Amount(a), Value::Amount(b)) = (&lv, &rv) {
                    return Ok(Value::Amount(a * b));
                }
            }
            _ => {}
        }

        Err(ValueError(format!(
            "Cannot multiply {} and {}",
            self.type_name(),
            other.type_name()
        )))
    }

    /// Divide two values with automatic type promotion.
    pub fn value_div(&self, other: &Value) -> Result<Value, ValueError> {
        // Balance can only be divided by a scalar
        if let Value::Balance(bal) = self {
            if let Value::Balance(_) = other {
                return Err(ValueError("Cannot divide two balances".into()));
            }
            let scalar = other.to_amount()?;
            let result = bal
                .divide(&scalar)
                .map_err(|e| ValueError(format!("Balance divide failed: {}", e)))?;
            return Ok(Value::Balance(result));
        }

        let (lv, rv, target) = Self::coerce_pair(self, other)?;
        match target {
            0 => {
                if let (Value::Integer(a), Value::Integer(b)) = (&lv, &rv) {
                    if *b == 0 {
                        return Err(ValueError("Divide by zero".into()));
                    }
                    // Integer division produces Amount to preserve precision
                    let la = Amount::from_int(*a);
                    let ra = Amount::from_int(*b);
                    return Ok(Value::Amount(&la / &ra));
                }
            }
            1 => {
                if let (Value::Amount(a), Value::Amount(b)) = (&lv, &rv) {
                    return Ok(Value::Amount(a / b));
                }
            }
            _ => {}
        }

        Err(ValueError(format!(
            "Cannot divide {} by {}",
            self.type_name(),
            other.type_name()
        )))
    }

    // ---- unary operations ---------------------------------------------------

    /// Negate the value.
    pub fn value_neg(&self) -> Result<Value, ValueError> {
        match self {
            Value::Void => Ok(Value::Void),
            Value::Integer(n) => Ok(Value::Integer(-n)),
            Value::Amount(a) => Ok(Value::Amount(a.negated())),
            Value::Balance(b) => Ok(Value::Balance(b.negated())),
            Value::Boolean(b) => Ok(Value::Boolean(!b)),
            _ => Err(ValueError(format!(
                "Cannot negate {}",
                self.type_name()
            ))),
        }
    }

    /// Absolute value.
    pub fn value_abs(&self) -> Result<Value, ValueError> {
        match self {
            Value::Integer(n) => Ok(Value::Integer(n.abs())),
            Value::Amount(a) => Ok(Value::Amount(a.abs())),
            Value::Balance(b) => Ok(Value::Balance(b.abs())),
            _ => Err(ValueError(format!(
                "Cannot take abs of {}",
                self.type_name()
            ))),
        }
    }

    // ---- comparison ---------------------------------------------------------

    /// Three-way comparison, returning -1, 0, or 1.
    pub fn value_cmp(&self, other: &Value) -> Result<i32, ValueError> {
        // Same type fast path
        match (self, other) {
            (Value::Void, Value::Void) => return Ok(0),
            (Value::Void, _) | (_, Value::Void) => {
                // One is void, the other isn't
                if self.is_null() && !other.is_null() {
                    return Err(ValueError("Cannot compare Void with non-Void".into()));
                }
                if !self.is_null() && other.is_null() {
                    return Err(ValueError("Cannot compare non-Void with Void".into()));
                }
            }
            (Value::Boolean(a), Value::Boolean(b)) => {
                return Ok((*a as i32) - (*b as i32));
            }
            (Value::Integer(a), Value::Integer(b)) => {
                return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
            }
            (Value::Amount(a), Value::Amount(b)) => {
                return a
                    .compare(b)
                    .map(|ord| match ord {
                        std::cmp::Ordering::Less => -1,
                        std::cmp::Ordering::Equal => 0,
                        std::cmp::Ordering::Greater => 1,
                    })
                    .map_err(|e| ValueError(format!("Amount comparison failed: {}", e)));
            }
            (Value::Str(a), Value::Str(b)) => {
                return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
            }
            (Value::Date(a), Value::Date(b)) => {
                return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
            }
            (Value::DateTime(a), Value::DateTime(b)) => {
                return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
            }
            _ => {}
        }

        // Cross-type numeric comparison
        let lr = numeric_rank(self);
        let rr = numeric_rank(other);
        if let (Some(_), Some(_)) = (lr, rr) {
            let (lv, rv, target) = Self::coerce_pair(self, other)?;
            match target {
                0 => {
                    if let (Value::Integer(a), Value::Integer(b)) = (&lv, &rv) {
                        return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
                    }
                }
                1 => {
                    if let (Value::Amount(a), Value::Amount(b)) = (&lv, &rv) {
                        return a
                            .compare(&b)
                            .map(|ord| match ord {
                                std::cmp::Ordering::Less => -1,
                                std::cmp::Ordering::Equal => 0,
                                std::cmp::Ordering::Greater => 1,
                            })
                            .map_err(|e| {
                                ValueError(format!("Amount comparison failed: {}", e))
                            });
                    }
                }
                2 => {
                    // Balance comparison: compare string forms
                    let ls = lv.to_string_value();
                    let rs = rv.to_string_value();
                    return Ok(if ls > rs { 1 } else if ls < rs { -1 } else { 0 });
                }
                _ => {}
            }
        }

        // STRING comparisons
        if matches!(self, Value::Str(_)) || matches!(other, Value::Str(_)) {
            let a = self.to_string_value();
            let b = other.to_string_value();
            return Ok(if a > b { 1 } else if a < b { -1 } else { 0 });
        }

        Err(ValueError(format!(
            "Cannot compare {} and {}",
            self.type_name(),
            other.type_name()
        )))
    }

    // ---- sequence operations ------------------------------------------------

    /// Append a value to the sequence.
    ///
    /// If this Value is Void, it becomes a Sequence.
    /// If it is not already a Sequence, it is wrapped into one first.
    pub fn push_back(&mut self, val: Value) {
        match self {
            Value::Void => {
                *self = Value::Sequence(vec![val]);
            }
            Value::Sequence(seq) => {
                seq.push(val);
            }
            _ => {
                let current = std::mem::replace(self, Value::Void);
                *self = Value::Sequence(vec![current, val]);
            }
        }
    }

    /// Remove the last element from the sequence.
    pub fn pop_back(&mut self) -> Result<(), ValueError> {
        match self {
            Value::Void => Err(ValueError("Cannot pop from a Void value".into())),
            Value::Sequence(seq) => {
                seq.pop();
                match seq.len() {
                    0 => {
                        *self = Value::Void;
                    }
                    1 => {
                        let solo = seq.remove(0);
                        *self = solo;
                    }
                    _ => {}
                }
                Ok(())
            }
            _ => {
                *self = Value::Void;
                Ok(())
            }
        }
    }

    /// Return the number of elements.
    pub fn len(&self) -> usize {
        match self {
            Value::Void => 0,
            Value::Sequence(seq) => seq.len(),
            _ => 1,
        }
    }

    /// Whether the value is empty.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Get element by index.
    pub fn get(&self, index: usize) -> Option<&Value> {
        match self {
            Value::Sequence(seq) => seq.get(index),
            _ if index == 0 => Some(self),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

impl fmt::Display for Value {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Value::Void => write!(f, ""),
            Value::Boolean(b) => write!(f, "{}", if *b { "true" } else { "false" }),
            Value::Integer(n) => write!(f, "{}", n),
            Value::Amount(a) => write!(f, "{}", a),
            Value::Balance(b) => write!(f, "{}", b),
            Value::Str(s) => write!(f, "{}", s),
            Value::Date(d) => write!(f, "{}", d),
            Value::DateTime(dt) => write!(f, "{}", dt),
            Value::Sequence(seq) => {
                write!(f, "(")?;
                for (i, v) in seq.iter().enumerate() {
                    if i > 0 {
                        write!(f, ", ")?;
                    }
                    write!(f, "{}", v)?;
                }
                write!(f, ")")
            }
        }
    }
}

// ---------------------------------------------------------------------------
// PartialEq
// ---------------------------------------------------------------------------

impl PartialEq for Value {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Value::Void, Value::Void) => true,
            (Value::Void, _) | (_, Value::Void) => false,
            (Value::Boolean(a), Value::Boolean(b)) => a == b,
            (Value::Integer(a), Value::Integer(b)) => a == b,
            (Value::Amount(a), Value::Amount(b)) => a == b,
            (Value::Balance(a), Value::Balance(b)) => a == b,
            (Value::Str(a), Value::Str(b)) => a == b,
            (Value::Date(a), Value::Date(b)) => a == b,
            (Value::DateTime(a), Value::DateTime(b)) => a == b,
            (Value::Sequence(a), Value::Sequence(b)) => a == b,
            // Cross-type numeric comparison
            _ => {
                let lr = numeric_rank(self);
                let rr = numeric_rank(other);
                if let (Some(_), Some(_)) = (lr, rr) {
                    if let Ok((lv, rv, _)) = Self::coerce_pair(self, other) {
                        return lv == rv;
                    }
                }
                // String comparison fallback
                if matches!(self, Value::Str(_)) || matches!(other, Value::Str(_)) {
                    return self.to_string_value() == other.to_string_value();
                }
                false
            }
        }
    }
}

impl Eq for Value {}

impl PartialOrd for Value {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        self.value_cmp(other).ok().map(|c| match c {
            n if n < 0 => std::cmp::Ordering::Less,
            0 => std::cmp::Ordering::Equal,
            _ => std::cmp::Ordering::Greater,
        })
    }
}

// ---------------------------------------------------------------------------
// From traits for easy construction
// ---------------------------------------------------------------------------

impl From<bool> for Value {
    fn from(b: bool) -> Self {
        Value::Boolean(b)
    }
}

impl From<i64> for Value {
    fn from(n: i64) -> Self {
        Value::Integer(n)
    }
}

impl From<i32> for Value {
    fn from(n: i32) -> Self {
        Value::Integer(n as i64)
    }
}

impl From<Amount> for Value {
    fn from(a: Amount) -> Self {
        Value::Amount(a)
    }
}

impl From<Balance> for Value {
    fn from(b: Balance) -> Self {
        Value::Balance(b)
    }
}

impl From<String> for Value {
    fn from(s: String) -> Self {
        Value::Str(s)
    }
}

impl From<&str> for Value {
    fn from(s: &str) -> Self {
        Value::Str(s.to_string())
    }
}

impl From<NaiveDate> for Value {
    fn from(d: NaiveDate) -> Self {
        Value::Date(d)
    }
}

impl From<NaiveDateTime> for Value {
    fn from(dt: NaiveDateTime) -> Self {
        Value::DateTime(dt)
    }
}

impl From<Vec<Value>> for Value {
    fn from(seq: Vec<Value>) -> Self {
        Value::Sequence(seq)
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

    // ---- construction -------------------------------------------------------

    #[test]
    fn void_value() {
        let v = Value::Void;
        assert!(v.is_null());
        assert!(v.is_zero());
        assert!(!v.to_bool());
    }

    #[test]
    fn boolean_value() {
        let t = Value::from(true);
        let f = Value::from(false);
        assert!(t.to_bool());
        assert!(!f.to_bool());
        assert!(!t.is_zero());
        assert!(f.is_zero());
    }

    #[test]
    fn integer_value() {
        let v = Value::from(42i64);
        assert!(!v.is_zero());
        assert!(v.to_bool());
        assert_eq!(v.to_int().unwrap(), 42);

        let z = Value::from(0i64);
        assert!(z.is_zero());
        assert!(!z.to_bool());
    }

    #[test]
    fn amount_value() {
        let v = Value::from(usd("10.00"));
        assert!(!v.is_zero());
        assert!(v.to_bool());
    }

    #[test]
    fn balance_value() {
        let bal = Balance::from_amount(&usd("10.00")).unwrap();
        let v = Value::from(bal);
        assert!(!v.is_zero());
    }

    #[test]
    fn string_value() {
        let v = Value::from("hello");
        assert!(!v.is_zero());
        assert!(v.to_bool());
        assert_eq!(v.to_string_value(), "hello");

        let empty = Value::from("");
        assert!(empty.is_zero());
        assert!(!empty.to_bool());
    }

    #[test]
    fn date_value() {
        let d = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let v = Value::from(d);
        assert!(v.to_bool());
        assert_eq!(v.to_date().unwrap(), d);
    }

    #[test]
    fn datetime_value() {
        let dt = NaiveDate::from_ymd_opt(2024, 1, 15)
            .unwrap()
            .and_hms_opt(10, 30, 0)
            .unwrap();
        let v = Value::from(dt);
        assert!(v.to_bool());
        assert_eq!(v.to_datetime().unwrap(), dt);
    }

    #[test]
    fn sequence_value() {
        let v = Value::from(vec![Value::from(1i64), Value::from(2i64)]);
        assert_eq!(v.len(), 2);
        assert!(!v.is_zero());
    }

    #[test]
    fn from_i32() {
        let v = Value::from(42i32);
        assert_eq!(v.to_int().unwrap(), 42);
    }

    // ---- type coercion ------------------------------------------------------

    #[test]
    fn to_boolean() {
        assert!(Value::from(1i64).to_boolean());
        assert!(!Value::from(0i64).to_boolean());
        assert!(Value::from(true).to_boolean());
    }

    #[test]
    fn to_int_from_boolean() {
        assert_eq!(Value::from(true).to_int().unwrap(), 1);
        assert_eq!(Value::from(false).to_int().unwrap(), 0);
    }

    #[test]
    fn to_int_from_void() {
        assert_eq!(Value::Void.to_int().unwrap(), 0);
    }

    #[test]
    fn to_amount_from_integer() {
        let a = Value::from(42i64).to_amount().unwrap();
        assert_eq!(a.to_long().unwrap(), 42);
    }

    #[test]
    fn to_balance_from_amount() {
        let bal = Value::from(usd("10.00")).to_balance().unwrap();
        assert_eq!(bal.len(), 1);
    }

    #[test]
    fn to_balance_from_void() {
        let bal = Value::Void.to_balance().unwrap();
        assert!(bal.is_empty());
    }

    #[test]
    fn to_string_value_various() {
        assert_eq!(Value::Void.to_string_value(), "");
        assert_eq!(Value::from(true).to_string_value(), "true");
        assert_eq!(Value::from(false).to_string_value(), "false");
        assert_eq!(Value::from(42i64).to_string_value(), "42");
    }

    #[test]
    fn to_date_from_datetime() {
        let dt = NaiveDate::from_ymd_opt(2024, 1, 15)
            .unwrap()
            .and_hms_opt(10, 30, 0)
            .unwrap();
        let v = Value::from(dt);
        assert_eq!(
            v.to_date().unwrap(),
            NaiveDate::from_ymd_opt(2024, 1, 15).unwrap()
        );
    }

    #[test]
    fn to_datetime_from_date() {
        let d = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let v = Value::from(d);
        let dt = v.to_datetime().unwrap();
        assert_eq!(dt.date(), d);
    }

    #[test]
    fn to_sequence_scalar() {
        let v = Value::from(42i64);
        let seq = v.to_sequence();
        assert_eq!(seq.len(), 1);
    }

    #[test]
    fn to_int_from_string_errors() {
        assert!(Value::from("hello").to_int().is_err());
    }

    // ---- arithmetic ---------------------------------------------------------

    #[test]
    fn add_integers() {
        let a = Value::from(10i64);
        let b = Value::from(20i64);
        let r = a.value_add(&b).unwrap();
        assert_eq!(r.to_int().unwrap(), 30);
    }

    #[test]
    fn add_void_identity() {
        let v = Value::from(42i64);
        let r = Value::Void.value_add(&v).unwrap();
        assert_eq!(r.to_int().unwrap(), 42);

        let r2 = v.value_add(&Value::Void).unwrap();
        assert_eq!(r2.to_int().unwrap(), 42);
    }

    #[test]
    fn add_integer_and_amount_promotes() {
        let a = Value::from(10i64);
        let b = Value::from(usd("5.00"));
        let r = a.value_add(&b).unwrap();
        // Should be Amount
        assert!(matches!(r, Value::Amount(_)));
    }

    #[test]
    fn add_amounts_same_commodity() {
        let a = Value::from(usd("10.00"));
        let b = Value::from(usd("5.00"));
        let r = a.value_add(&b).unwrap();
        if let Value::Amount(amt) = &r {
            assert_eq!(amt.to_string(), "$15.00");
        } else {
            panic!("Expected Amount");
        }
    }

    #[test]
    fn add_amounts_different_commodities_promotes_to_balance() {
        let a = Value::from(usd("10.00"));
        let b = Value::from(eur("20.00"));
        let r = a.value_add(&b).unwrap();
        assert!(matches!(r, Value::Balance(_)));
    }

    #[test]
    fn add_strings() {
        let a = Value::from("hello ");
        let b = Value::from("world");
        let r = a.value_add(&b).unwrap();
        assert_eq!(r.to_string_value(), "hello world");
    }

    #[test]
    fn add_sequences_same_length() {
        let a = Value::from(vec![Value::from(1i64), Value::from(2i64)]);
        let b = Value::from(vec![Value::from(10i64), Value::from(20i64)]);
        let r = a.value_add(&b).unwrap();
        if let Value::Sequence(seq) = &r {
            assert_eq!(seq[0].to_int().unwrap(), 11);
            assert_eq!(seq[1].to_int().unwrap(), 22);
        } else {
            panic!("Expected Sequence");
        }
    }

    #[test]
    fn add_sequences_different_length() {
        let a = Value::from(vec![Value::from(1i64)]);
        let b = Value::from(vec![Value::from(2i64), Value::from(3i64)]);
        let r = a.value_add(&b).unwrap();
        if let Value::Sequence(seq) = &r {
            assert_eq!(seq.len(), 3);
        } else {
            panic!("Expected Sequence");
        }
    }

    // ---- subtraction --------------------------------------------------------

    #[test]
    fn sub_integers() {
        let a = Value::from(10i64);
        let b = Value::from(3i64);
        let r = a.value_sub(&b).unwrap();
        assert_eq!(r.to_int().unwrap(), 7);
    }

    #[test]
    fn sub_void_negates() {
        let v = Value::from(5i64);
        let r = Value::Void.value_sub(&v).unwrap();
        assert_eq!(r.to_int().unwrap(), -5);
    }

    #[test]
    fn sub_amounts_different_commodities() {
        let a = Value::from(usd("10.00"));
        let b = Value::from(eur("5.00"));
        let r = a.value_sub(&b).unwrap();
        assert!(matches!(r, Value::Balance(_)));
    }

    // ---- multiplication -----------------------------------------------------

    #[test]
    fn mul_integers() {
        let a = Value::from(6i64);
        let b = Value::from(7i64);
        let r = a.value_mul(&b).unwrap();
        assert_eq!(r.to_int().unwrap(), 42);
    }

    #[test]
    fn mul_string_repeat() {
        let a = Value::from("ab");
        let b = Value::from(3i64);
        let r = a.value_mul(&b).unwrap();
        assert_eq!(r.to_string_value(), "ababab");
    }

    #[test]
    fn mul_balance_by_scalar() {
        let bal = Balance::from_amount(&usd("10.00")).unwrap();
        let a = Value::from(bal);
        let b = Value::from(2i64);
        let r = a.value_mul(&b).unwrap();
        if let Value::Balance(b) = &r {
            let amt = b.to_amount().unwrap();
            assert_eq!(amt.to_string(), "$20.00");
        } else {
            panic!("Expected Balance");
        }
    }

    #[test]
    fn mul_two_balances_errors() {
        let b1 = Value::from(Balance::from_amount(&usd("10.00")).unwrap());
        let b2 = Value::from(Balance::from_amount(&usd("5.00")).unwrap());
        assert!(b1.value_mul(&b2).is_err());
    }

    // ---- division -----------------------------------------------------------

    #[test]
    fn div_integers() {
        let a = Value::from(10i64);
        let b = Value::from(3i64);
        let r = a.value_div(&b).unwrap();
        // Integer division produces Amount
        assert!(matches!(r, Value::Amount(_)));
    }

    #[test]
    fn div_by_zero_errors() {
        let a = Value::from(10i64);
        let b = Value::from(0i64);
        assert!(a.value_div(&b).is_err());
    }

    #[test]
    fn div_two_balances_errors() {
        let b1 = Value::from(Balance::from_amount(&usd("10.00")).unwrap());
        let b2 = Value::from(Balance::from_amount(&usd("5.00")).unwrap());
        assert!(b1.value_div(&b2).is_err());
    }

    // ---- unary operations ---------------------------------------------------

    #[test]
    fn neg_integer() {
        let v = Value::from(42i64);
        let r = v.value_neg().unwrap();
        assert_eq!(r.to_int().unwrap(), -42);
    }

    #[test]
    fn neg_void() {
        let r = Value::Void.value_neg().unwrap();
        assert!(r.is_null());
    }

    #[test]
    fn neg_boolean() {
        let r = Value::from(true).value_neg().unwrap();
        assert_eq!(r, Value::from(false));
    }

    #[test]
    fn abs_integer() {
        let v = Value::from(-42i64);
        let r = v.value_abs().unwrap();
        assert_eq!(r.to_int().unwrap(), 42);
    }

    #[test]
    fn abs_string_errors() {
        assert!(Value::from("hello").value_abs().is_err());
    }

    // ---- comparison ---------------------------------------------------------

    #[test]
    fn cmp_integers() {
        let a = Value::from(10i64);
        let b = Value::from(20i64);
        assert_eq!(a.value_cmp(&b).unwrap(), -1);
        assert_eq!(b.value_cmp(&a).unwrap(), 1);
        assert_eq!(a.value_cmp(&a).unwrap(), 0);
    }

    #[test]
    fn cmp_strings() {
        let a = Value::from("abc");
        let b = Value::from("def");
        assert_eq!(a.value_cmp(&b).unwrap(), -1);
    }

    #[test]
    fn cmp_cross_type_numeric() {
        let a = Value::from(10i64);
        let b = Value::from(Amount::from_int(10));
        assert_eq!(a.value_cmp(&b).unwrap(), 0);
    }

    // ---- equality -----------------------------------------------------------

    #[test]
    fn eq_same_type() {
        assert_eq!(Value::from(42i64), Value::from(42i64));
        assert_ne!(Value::from(42i64), Value::from(43i64));
        assert_eq!(Value::from("hello"), Value::from("hello"));
    }

    #[test]
    fn eq_void() {
        assert_eq!(Value::Void, Value::Void);
        assert_ne!(Value::Void, Value::from(0i64));
    }

    #[test]
    fn eq_cross_type_numeric() {
        let a = Value::from(10i64);
        let b = Value::from(Amount::from_int(10));
        assert_eq!(a, b);
    }

    // ---- partial_ord --------------------------------------------------------

    #[test]
    fn partial_ord_integers() {
        let a = Value::from(10i64);
        let b = Value::from(20i64);
        assert!(a < b);
        assert!(b > a);
        assert!(a <= a);
        assert!(a >= a);
    }

    // ---- sequence operations ------------------------------------------------

    #[test]
    fn push_back_void() {
        let mut v = Value::Void;
        v.push_back(Value::from(1i64));
        assert!(matches!(v, Value::Sequence(_)));
        assert_eq!(v.len(), 1);
    }

    #[test]
    fn push_back_scalar() {
        let mut v = Value::from(1i64);
        v.push_back(Value::from(2i64));
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn push_back_sequence() {
        let mut v = Value::from(vec![Value::from(1i64)]);
        v.push_back(Value::from(2i64));
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn pop_back_to_void() {
        let mut v = Value::from(vec![Value::from(1i64)]);
        v.pop_back().unwrap();
        assert!(v.is_null());
    }

    #[test]
    fn pop_back_unwrap_single() {
        let mut v = Value::from(vec![Value::from(1i64), Value::from(2i64)]);
        v.pop_back().unwrap();
        // Should unwrap single element
        assert_eq!(v, Value::from(1i64));
    }

    #[test]
    fn pop_back_void_errors() {
        let mut v = Value::Void;
        assert!(v.pop_back().is_err());
    }

    #[test]
    fn pop_back_scalar() {
        let mut v = Value::from(42i64);
        v.pop_back().unwrap();
        assert!(v.is_null());
    }

    #[test]
    fn get_scalar() {
        let v = Value::from(42i64);
        assert_eq!(v.get(0), Some(&Value::from(42i64)));
        assert_eq!(v.get(1), None);
    }

    #[test]
    fn get_sequence() {
        let v = Value::from(vec![Value::from(1i64), Value::from(2i64)]);
        assert_eq!(v.get(0), Some(&Value::from(1i64)));
        assert_eq!(v.get(1), Some(&Value::from(2i64)));
        assert_eq!(v.get(2), None);
    }

    // ---- display ------------------------------------------------------------

    #[test]
    fn display_void() {
        assert_eq!(format!("{}", Value::Void), "");
    }

    #[test]
    fn display_boolean() {
        assert_eq!(format!("{}", Value::from(true)), "true");
        assert_eq!(format!("{}", Value::from(false)), "false");
    }

    #[test]
    fn display_integer() {
        assert_eq!(format!("{}", Value::from(42i64)), "42");
    }

    #[test]
    fn display_sequence() {
        let v = Value::from(vec![Value::from(1i64), Value::from(2i64)]);
        assert_eq!(format!("{}", v), "(1, 2)");
    }

    // ---- is_realzero --------------------------------------------------------

    #[test]
    fn is_realzero_void() {
        assert!(Value::Void.is_realzero());
    }

    #[test]
    fn is_realzero_integer() {
        assert!(Value::from(0i64).is_realzero());
        assert!(!Value::from(1i64).is_realzero());
    }

    #[test]
    fn is_realzero_empty_balance() {
        assert!(Value::from(Balance::new()).is_realzero());
    }

    // ---- type_name ----------------------------------------------------------

    #[test]
    fn type_names() {
        assert_eq!(Value::Void.type_name(), "Void");
        assert_eq!(Value::from(true).type_name(), "Boolean");
        assert_eq!(Value::from(1i64).type_name(), "Integer");
        assert_eq!(Value::from("hi").type_name(), "String");
    }
}
