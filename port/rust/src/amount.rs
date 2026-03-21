//! Exact-precision commoditized amounts for double-entry accounting.
//!
//! This module provides the `Amount` type, a Rust port of Ledger's `amount_t`.
//! It uses `num_rational::BigRational` for exact rational arithmetic (mirroring
//! GMP's `mpq_t` semantics) so that addition, subtraction, multiplication, and
//! division never introduce rounding error.

use lazy_static::lazy_static;
use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::{One, Signed, ToPrimitive, Zero};
use regex::Regex;
use std::cmp::Ordering;
use std::fmt;
use std::ops::{Add, Div, Mul, Neg, Sub};
use std::str::FromStr;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error type for invalid amount operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AmountError(pub String);

impl fmt::Display for AmountError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "AmountError: {}", self.0)
    }
}

impl std::error::Error for AmountError {}

// ---------------------------------------------------------------------------
// Display style
// ---------------------------------------------------------------------------

/// Display style hints parsed from the input string.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AmountStyle {
    pub prefix: bool,
    pub separated: bool,
    pub thousands: bool,
    pub decimal_comma: bool,
}

impl Default for AmountStyle {
    fn default() -> Self {
        Self {
            prefix: false,
            separated: false,
            thousands: false,
            decimal_comma: false,
        }
    }
}

// ---------------------------------------------------------------------------
// Parsing helpers
// ---------------------------------------------------------------------------

lazy_static! {
    /// Prefix commodity: non-digit, non-sign, non-whitespace characters, or quoted string.
    static ref PREFIX_SYMBOL_RE: Regex =
        Regex::new(r#"^([^\d\s\-+.,'"]+|"[^"]+")"#).unwrap();

    /// Suffix commodity: same pattern at end of string.
    static ref SUFFIX_SYMBOL_RE: Regex =
        Regex::new(r#"([^\d\s\-+.,'"]+|"[^"]+")$"#).unwrap();
}

/// Count decimal places after the decimal point in a numeric string.
fn count_decimal_places(s: &str) -> u32 {
    if let Some(pos) = s.find('.') {
        (s.len() - pos - 1) as u32
    } else {
        0
    }
}

/// Parse a numeric string (already cleaned of commodity) into a BigRational.
fn parse_numeric(clean: &str) -> Result<BigRational, AmountError> {
    if clean.is_empty() {
        return Err(AmountError("No quantity specified for amount".into()));
    }

    if clean.contains('.') {
        let parts: Vec<&str> = clean.splitn(2, '.').collect();
        let integer_part = parts[0];
        let decimal_part = parts[1];
        let dp = decimal_part.len() as u32;

        // Construct as (integer_part * 10^dp + decimal_part) / 10^dp
        let combined = format!("{}{}", integer_part, decimal_part);
        let numerator = BigInt::from_str(&combined)
            .map_err(|e| AmountError(format!("Cannot parse numeric value: {:?}: {}", clean, e)))?;
        let denominator = BigInt::from(10).pow(dp);
        Ok(BigRational::new(numerator, denominator))
    } else {
        let n = BigInt::from_str(clean)
            .map_err(|e| AmountError(format!("Cannot parse numeric value: {:?}: {}", clean, e)))?;
        Ok(BigRational::from_integer(n))
    }
}

/// Result of parsing an amount string.
struct ParsedAmount {
    quantity: BigRational,
    precision: u32,
    commodity: Option<String>,
    style: AmountStyle,
}

/// Parse an amount string into its components.
fn parse_amount_string(text: &str) -> Result<ParsedAmount, AmountError> {
    let text = text.trim();
    if text.is_empty() {
        return Err(AmountError("No quantity specified for amount".into()));
    }

    let mut style = AmountStyle::default();
    let mut commodity_symbol: Option<String> = None;
    let mut negative = false;

    let mut rest = text;

    // Handle leading sign
    if rest.starts_with('-') {
        negative = true;
        rest = rest[1..].trim_start();
    } else if rest.starts_with('+') {
        rest = rest[1..].trim_start();
    }

    if rest.is_empty() {
        return Err(AmountError("No quantity specified for amount".into()));
    }

    let first_char = rest.chars().next().unwrap();

    if !first_char.is_ascii_digit() && first_char != '.' {
        // Prefix commodity
        if let Some(m) = PREFIX_SYMBOL_RE.find(rest) {
            let raw_sym = m.as_str();
            commodity_symbol = Some(raw_sym.trim_matches('"').to_string());
            rest = &rest[m.end()..];
            if rest.starts_with(' ') {
                style.separated = true;
                rest = rest.trim_start();
            }
            style.prefix = true;
        }
    } else {
        // Number comes first; commodity may be suffix
        let mut num_end = 0;
        for (i, ch) in rest.char_indices() {
            if "0123456789.,-'".contains(ch) {
                num_end = i + ch.len_utf8();
            } else {
                break;
            }
        }
        // If we never broke out of the loop, num_end covers the whole string
        if num_end == 0 && rest.chars().all(|c| "0123456789.,-'".contains(c)) {
            num_end = rest.len();
        }

        let num_part = &rest[..num_end];
        let suffix_part = &rest[num_end..];

        if !suffix_part.is_empty() {
            let mut sp = suffix_part;
            if sp.starts_with(' ') {
                style.separated = true;
                sp = sp.trim_start();
            }
            if !sp.is_empty() {
                commodity_symbol = Some(sp.trim_matches('"').to_string());
            }
        }
        rest = num_part;
    }

    let numeric_str = rest.trim();
    if numeric_str.is_empty() {
        return Err(AmountError("No quantity specified for amount".into()));
    }

    // Detect decimal mark convention
    let has_comma = numeric_str.contains(',');
    let has_period = numeric_str.contains('.');
    let has_apostrophe = numeric_str.contains('\'');

    let decimal_places: u32;
    let mut clean: String;

    if has_comma && has_period {
        let last_comma = numeric_str.rfind(',').unwrap();
        let last_period = numeric_str.rfind('.').unwrap();
        if last_period > last_comma {
            // Period is decimal mark, comma is thousands
            style.thousands = true;
            clean = numeric_str.replace(',', "");
            decimal_places = count_decimal_places(&clean);
        } else {
            // Comma is decimal mark, period is thousands
            style.thousands = true;
            style.decimal_comma = true;
            clean = numeric_str.replace('.', "").replace(',', ".");
            decimal_places = count_decimal_places(&clean);
        }
    } else if has_comma {
        let last_comma = numeric_str.rfind(',').unwrap();
        let after_comma = &numeric_str[last_comma + 1..];
        let comma_count = numeric_str.matches(',').count();
        let first_comma = numeric_str.find(',').unwrap();
        let int_part = &numeric_str[..first_comma];

        if comma_count > 1 {
            // Multiple commas = thousands separators
            style.thousands = true;
            clean = numeric_str.replace(',', "");
            decimal_places = 0;
        } else if after_comma.len() != 3 {
            // Not exactly 3 digits after = decimal comma
            style.decimal_comma = true;
            clean = numeric_str.replace(',', ".");
            decimal_places = after_comma.len() as u32;
        } else if int_part.trim_start_matches('-') == "0" {
            // 0,xxx = decimal comma (European style)
            style.decimal_comma = true;
            clean = numeric_str.replace(',', ".");
            decimal_places = after_comma.len() as u32;
        } else {
            // Ambiguous: 3 digits after single comma. Treat as thousands.
            style.thousands = true;
            clean = numeric_str.replace(',', "");
            decimal_places = 0;
        }
    } else if has_period {
        clean = numeric_str.to_string();
        decimal_places = count_decimal_places(&clean);
    } else if has_apostrophe {
        style.thousands = true;
        clean = numeric_str.replace('\'', "");
        decimal_places = 0;
    } else {
        clean = numeric_str.to_string();
        decimal_places = 0;
    }

    if has_apostrophe {
        clean = clean.replace('\'', "");
    }

    let mut quantity = parse_numeric(&clean)?;
    if negative {
        quantity = -quantity;
    }

    Ok(ParsedAmount {
        quantity,
        precision: decimal_places,
        commodity: commodity_symbol,
        style,
    })
}

// ---------------------------------------------------------------------------
// Amount
// ---------------------------------------------------------------------------

/// Extra decimal places added on division to avoid precision loss.
const EXTEND_BY_DIGITS: u32 = 6;

/// Exact-precision commoditized amount.
///
/// Uses `BigRational` for internal storage, matching the infinite-precision
/// rational arithmetic of Ledger's GMP-backed `amount_t`.
#[derive(Debug, Clone)]
pub struct Amount {
    quantity: Option<BigRational>,
    precision: u32,
    commodity: Option<String>,
    style: AmountStyle,
    keep_precision: bool,
}

impl Amount {
    // ---- construction -----------------------------------------------------

    /// Create a null/uninitialized amount.
    pub fn null() -> Self {
        Self {
            quantity: None,
            precision: 0,
            commodity: None,
            style: AmountStyle::default(),
            keep_precision: false,
        }
    }

    /// Create an amount from an integer value.
    pub fn from_int(value: i64) -> Self {
        Self {
            quantity: Some(BigRational::from_integer(BigInt::from(value))),
            precision: 0,
            commodity: None,
            style: AmountStyle::default(),
            keep_precision: false,
        }
    }

    /// Create an amount from a BigRational value.
    pub fn from_rational(value: BigRational) -> Self {
        Self {
            quantity: Some(value),
            precision: 0,
            commodity: None,
            style: AmountStyle::default(),
            keep_precision: false,
        }
    }

    /// Create an amount from a float value.
    pub fn from_f64(value: f64) -> Self {
        // Use string conversion for reasonable precision
        let s = format!("{}", value);
        let rational = parse_numeric(&s).unwrap_or_else(|_| BigRational::zero());
        Self {
            quantity: Some(rational),
            precision: EXTEND_BY_DIGITS,
            commodity: None,
            style: AmountStyle::default(),
            keep_precision: false,
        }
    }

    /// Parse an amount from a string (e.g., "$10.00", "10 EUR", "-5.25").
    pub fn parse(text: &str) -> Result<Self, AmountError> {
        let parsed = parse_amount_string(text)?;
        Ok(Self {
            quantity: Some(parsed.quantity),
            precision: parsed.precision,
            commodity: parsed.commodity,
            style: parsed.style,
            keep_precision: false,
        })
    }

    /// Parse an amount that keeps full parsed precision for display.
    pub fn exact(text: &str) -> Result<Self, AmountError> {
        let mut amt = Self::parse(text)?;
        amt.keep_precision = true;
        Ok(amt)
    }

    /// Create an amount with a specific commodity.
    pub fn with_commodity(mut self, commodity: &str) -> Self {
        if commodity.is_empty() {
            self.commodity = None;
        } else {
            self.commodity = Some(commodity.to_string());
        }
        self
    }

    // ---- null / truth tests -----------------------------------------------

    /// True if no value has been set (uninitialized).
    pub fn is_null(&self) -> bool {
        self.quantity.is_none()
    }

    fn require_quantity(&self) -> Result<&BigRational, AmountError> {
        self.quantity
            .as_ref()
            .ok_or_else(|| AmountError("Cannot use an uninitialized amount".into()))
    }

    /// True if the exact rational value is zero.
    pub fn is_realzero(&self) -> bool {
        match &self.quantity {
            Some(q) => q.is_zero(),
            None => false,
        }
    }

    /// True if the amount displays as zero at its display precision.
    pub fn is_zero(&self) -> bool {
        match &self.quantity {
            Some(q) => {
                if q.is_zero() {
                    return true;
                }
                let dp = self.display_precision();
                let rounded = self.round_rational(q, dp);
                rounded.is_zero()
            }
            None => false,
        }
    }

    pub fn is_nonzero(&self) -> bool {
        !self.is_zero()
    }

    pub fn is_negative(&self) -> bool {
        self.sign() < 0
    }

    pub fn is_positive(&self) -> bool {
        self.sign() > 0
    }

    /// Return -1, 0, or 1.
    pub fn sign(&self) -> i32 {
        match &self.quantity {
            Some(q) => {
                if q.is_positive() {
                    1
                } else if q.is_negative() {
                    -1
                } else {
                    0
                }
            }
            None => 0,
        }
    }

    // ---- properties -------------------------------------------------------

    /// The raw BigRational value.
    pub fn quantity(&self) -> Result<&BigRational, AmountError> {
        self.require_quantity()
    }

    /// The commodity symbol string.
    pub fn commodity(&self) -> Option<&str> {
        self.commodity.as_deref()
    }

    /// Set the commodity.
    pub fn set_commodity(&mut self, commodity: Option<&str>) {
        self.commodity = commodity.map(|s| s.to_string());
    }

    /// Whether this amount has a commodity.
    pub fn has_commodity(&self) -> bool {
        matches!(&self.commodity, Some(c) if !c.is_empty())
    }

    /// The internal precision.
    pub fn precision(&self) -> u32 {
        self.precision
    }

    /// Whether keep_precision is set.
    pub fn keep_precision(&self) -> bool {
        self.keep_precision
    }

    /// Return the precision used for display output.
    pub fn display_precision(&self) -> u32 {
        if self.keep_precision {
            return self.precision;
        }
        // For commodity-less amounts, if the value is a whole number,
        // display as integer (no decimal places).
        if !self.has_commodity() {
            if let Some(q) = &self.quantity {
                if q.is_integer() {
                    return 0;
                }
            }
        }
        self.precision
    }

    // ---- unary operations -------------------------------------------------

    /// Return a negated copy.
    pub fn negated(&self) -> Self {
        let mut result = self.clone();
        if let Some(q) = &result.quantity {
            result.quantity = Some(-q);
        }
        result
    }

    /// Return the absolute value.
    pub fn abs(&self) -> Self {
        if self.sign() < 0 {
            self.negated()
        } else {
            self.clone()
        }
    }

    /// Negate in place.
    pub fn in_place_negate(&mut self) {
        if let Some(q) = &self.quantity {
            self.quantity = Some(-q);
        }
    }

    /// Return a copy with commodity stripped.
    pub fn number(&self) -> Self {
        let mut result = self.clone();
        result.commodity = None;
        result
    }

    /// Remove the commodity from this amount (in-place).
    pub fn clear_commodity(&mut self) {
        self.commodity = None;
    }

    // ---- rounding ---------------------------------------------------------

    /// Round a BigRational to `places` decimal digits (half away from zero).
    fn round_rational(&self, q: &BigRational, places: u32) -> BigRational {
        let factor = BigRational::from_integer(BigInt::from(10).pow(places));
        let scaled = q * &factor;
        let half = BigRational::new(BigInt::one(), BigInt::from(2));

        let rounded_val = if scaled.is_negative() {
            let pos = -&scaled;
            let r = (&pos + &half).to_integer();
            -r
        } else {
            (&scaled + &half).to_integer()
        };

        BigRational::new(rounded_val, BigInt::from(10).pow(places))
    }

    /// Return a rounded copy (clears keep_precision).
    pub fn rounded(&self) -> Self {
        let mut result = self.clone();
        result.keep_precision = false;
        result
    }

    /// Round to exactly `places` decimal digits.
    pub fn roundto(&self, places: u32) -> Self {
        let mut result = self.clone();
        result.in_place_roundto(places);
        result
    }

    /// Round in place to exactly `places` decimal digits.
    pub fn in_place_roundto(&mut self, places: u32) {
        if let Some(q) = &self.quantity {
            let rounded = self.round_rational(q, places);
            self.quantity = Some(rounded);
            self.precision = places;
        }
    }

    /// Clear the keep_precision flag.
    pub fn in_place_round(&mut self) {
        self.keep_precision = false;
    }

    /// Return a copy with keep_precision set.
    pub fn unrounded(&self) -> Self {
        let mut result = self.clone();
        result.keep_precision = true;
        result
    }

    /// Set keep_precision flag.
    pub fn in_place_unround(&mut self) {
        self.keep_precision = true;
    }

    /// Return a truncated copy (toward zero).
    pub fn truncated(&self) -> Self {
        let mut result = self.clone();
        result.in_place_truncate();
        result
    }

    /// Truncate toward zero to display precision.
    pub fn in_place_truncate(&mut self) {
        if let Some(q) = &self.quantity {
            let dp = self.display_precision();
            let factor = BigRational::from_integer(BigInt::from(10).pow(dp));
            let scaled = q * &factor;
            let truncated_val = scaled.to_integer();
            self.quantity =
                Some(BigRational::new(truncated_val, BigInt::from(10).pow(dp)));
        }
    }

    /// Return a floored copy.
    pub fn floored(&self) -> Self {
        let mut result = self.clone();
        result.in_place_floor();
        result
    }

    /// Floor in place.
    pub fn in_place_floor(&mut self) {
        if let Some(q) = &self.quantity {
            self.quantity = Some(BigRational::from_integer(q.floor().to_integer()));
        }
    }

    /// Return a ceilinged copy.
    pub fn ceilinged(&self) -> Self {
        let mut result = self.clone();
        result.in_place_ceiling();
        result
    }

    /// Ceiling in place.
    pub fn in_place_ceiling(&mut self) {
        if let Some(q) = &self.quantity {
            self.quantity = Some(BigRational::from_integer(q.ceil().to_integer()));
        }
    }

    /// Return a reduced copy (no-op for now).
    pub fn reduce(&self) -> Self {
        self.clone()
    }

    // ---- comparison -------------------------------------------------------

    /// Three-way comparison.
    pub fn compare(&self, other: &Amount) -> Result<Ordering, AmountError> {
        let lq = self.require_quantity()?;
        let rq = other.require_quantity()?;

        if self.has_commodity() && other.has_commodity() && self.commodity != other.commodity {
            return Err(AmountError(format!(
                "Cannot compare amounts with different commodities: '{:?}' and '{:?}'",
                self.commodity, other.commodity
            )));
        }

        Ok(lq.cmp(rq))
    }

    // ---- arithmetic helpers -----------------------------------------------

    #[allow(dead_code)]
    fn coerce_int(value: i64) -> Amount {
        Amount::from_int(value)
    }

    // ---- conversion -------------------------------------------------------

    /// Convert to f64.
    pub fn to_double(&self) -> Result<f64, AmountError> {
        let q = self.require_quantity()?;
        Ok(q.to_f64().unwrap_or(f64::NAN))
    }

    /// Convert to i64 (rounded).
    pub fn to_long(&self) -> Result<i64, AmountError> {
        let f = self.to_double()?;
        Ok(f.round() as i64)
    }

    // ---- string formatting ------------------------------------------------

    /// Format the numeric part to `prec` decimal places.
    fn format_quantity(&self, prec: u32) -> String {
        let q = match &self.quantity {
            Some(q) => q,
            None => return "<null>".to_string(),
        };

        if prec == 0 {
            // Integer display
            let half = BigRational::new(BigInt::one(), BigInt::from(2));
            let rounded = if q.is_negative() {
                let pos = -q;
                let r = (&pos + &half).to_integer();
                -(r)
            } else {
                (q + &half).to_integer()
            };
            let int_str = rounded.to_string();

            // Apply thousands separators if needed
            if self.use_thousands() {
                self.apply_thousands_to_integer(&int_str)
            } else {
                int_str
            }
        } else {
            let factor = BigRational::from_integer(BigInt::from(10).pow(prec));
            let scaled = q * &factor;
            let half = BigRational::new(BigInt::one(), BigInt::from(2));

            let int_val = if scaled.is_negative() {
                let pos = -&scaled;
                let r = (&pos + &half).to_integer();
                -r
            } else {
                (&scaled + &half).to_integer()
            };

            let negative = int_val.is_negative();
            let abs_val = if negative { -&int_val } else { int_val.clone() };

            let abs_str = abs_val.to_string();
            let prec_usize = prec as usize;

            // Pad with leading zeros if necessary
            let padded = if abs_str.len() <= prec_usize {
                format!("{:0>width$}", abs_str, width = prec_usize + 1)
            } else {
                abs_str
            };

            let split_pos = padded.len() - prec_usize;
            let integer_part = &padded[..split_pos];
            let decimal_part = &padded[split_pos..];

            let use_decimal_comma = self.use_decimal_comma();
            let decimal_sep = if use_decimal_comma { "," } else { "." };

            let integer_display = if self.use_thousands() {
                // Strip the sign handling from integer_part since we handle it separately
                self.apply_thousands_to_integer(integer_part)
            } else {
                integer_part.to_string()
            };

            let result = format!("{}{}{}", integer_display, decimal_sep, decimal_part);
            if negative {
                format!("-{}", result)
            } else {
                result
            }
        }
    }

    fn use_thousands(&self) -> bool {
        self.style.thousands
    }

    fn use_decimal_comma(&self) -> bool {
        self.style.decimal_comma
    }

    fn apply_thousands_to_integer(&self, int_str: &str) -> String {
        let use_decimal_comma = self.use_decimal_comma();
        let thousands_sep = if use_decimal_comma { "." } else { "," };

        // Handle negative sign
        let (sign, digits) = if int_str.starts_with('-') {
            ("-", &int_str[1..])
        } else {
            ("", int_str)
        };

        if digits.len() <= 3 {
            return int_str.to_string();
        }

        let mut groups: Vec<&str> = Vec::new();
        let mut end = digits.len();
        while end > 3 {
            groups.push(&digits[end - 3..end]);
            end -= 3;
        }
        groups.push(&digits[..end]);
        groups.reverse();

        format!("{}{}", sign, groups.join(thousands_sep))
    }

    /// Return the display value without commodity.
    pub fn quantity_string(&self) -> String {
        if self.quantity.is_none() {
            return "<null>".to_string();
        }
        let dp = self.display_precision();
        self.format_quantity(dp)
    }

    /// Return the display value with commodity.
    pub fn to_string(&self) -> String {
        if self.quantity.is_none() {
            return "<null>".to_string();
        }
        let dp = self.display_precision();
        let num_str = self.format_quantity(dp);
        self.apply_commodity_to_string(&num_str)
    }

    /// Return the full-precision value with commodity.
    pub fn to_fullstring(&self) -> String {
        if self.quantity.is_none() {
            return "<null>".to_string();
        }
        let num_str = self.format_quantity(self.precision);
        self.apply_commodity_to_string(&num_str)
    }

    fn apply_commodity_to_string(&self, num_str: &str) -> String {
        if !self.has_commodity() {
            return num_str.to_string();
        }
        let sym = self.commodity.as_ref().unwrap();
        let sep = if self.style.separated { " " } else { "" };
        if self.style.prefix {
            format!("{}{}{}", sym, sep, num_str)
        } else {
            format!("{}{}{}", num_str, sep, sym)
        }
    }
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

impl fmt::Display for Amount {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_string())
    }
}

// ---------------------------------------------------------------------------
// FromStr
// ---------------------------------------------------------------------------

impl FromStr for Amount {
    type Err = AmountError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Amount::parse(s)
    }
}

// ---------------------------------------------------------------------------
// Neg
// ---------------------------------------------------------------------------

impl Neg for Amount {
    type Output = Amount;
    fn neg(self) -> Amount {
        self.negated()
    }
}

impl Neg for &Amount {
    type Output = Amount;
    fn neg(self) -> Amount {
        self.negated()
    }
}

// ---------------------------------------------------------------------------
// PartialEq, Eq, PartialOrd, Ord
// ---------------------------------------------------------------------------

impl PartialEq for Amount {
    fn eq(&self, other: &Self) -> bool {
        if self.is_null() && other.is_null() {
            return true;
        }
        if self.is_null() || other.is_null() {
            return false;
        }
        if self.has_commodity() && other.has_commodity() && self.commodity != other.commodity {
            return false;
        }
        self.quantity == other.quantity
    }
}

impl Eq for Amount {}

impl PartialOrd for Amount {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        self.compare(other).ok()
    }
}

// ---------------------------------------------------------------------------
// Arithmetic operators
// ---------------------------------------------------------------------------

impl Add for &Amount {
    type Output = Amount;

    fn add(self, rhs: &Amount) -> Amount {
        let lq = self.require_quantity().expect("Cannot add uninitialized amount");
        let rq = rhs
            .require_quantity()
            .expect("Cannot add uninitialized amount");

        if self.has_commodity() && rhs.has_commodity() && self.commodity != rhs.commodity {
            panic!(
                "Adding amounts with different commodities: '{:?}' != '{:?}'",
                self.commodity, rhs.commodity
            );
        }

        let mut result = self.clone();
        result.quantity = Some(lq + rq);
        result.precision = std::cmp::max(self.precision, rhs.precision);

        if !self.has_commodity() && rhs.has_commodity() {
            result.commodity = rhs.commodity.clone();
            result.style = rhs.style.clone();
        }
        result
    }
}

impl Add for Amount {
    type Output = Amount;
    fn add(self, rhs: Amount) -> Amount {
        (&self).add(&rhs)
    }
}

impl Sub for &Amount {
    type Output = Amount;

    fn sub(self, rhs: &Amount) -> Amount {
        let lq = self
            .require_quantity()
            .expect("Cannot subtract uninitialized amount");
        let rq = rhs
            .require_quantity()
            .expect("Cannot subtract uninitialized amount");

        if self.has_commodity() && rhs.has_commodity() && self.commodity != rhs.commodity {
            panic!(
                "Subtracting amounts with different commodities: '{:?}' != '{:?}'",
                self.commodity, rhs.commodity
            );
        }

        let mut result = self.clone();
        result.quantity = Some(lq - rq);
        result.precision = std::cmp::max(self.precision, rhs.precision);

        if !self.has_commodity() && rhs.has_commodity() {
            result.commodity = rhs.commodity.clone();
            result.style = rhs.style.clone();
        }
        result
    }
}

impl Sub for Amount {
    type Output = Amount;
    fn sub(self, rhs: Amount) -> Amount {
        (&self).sub(&rhs)
    }
}

impl Mul for &Amount {
    type Output = Amount;

    fn mul(self, rhs: &Amount) -> Amount {
        let lq = self
            .require_quantity()
            .expect("Cannot multiply uninitialized amount");
        let rq = rhs
            .require_quantity()
            .expect("Cannot multiply uninitialized amount");

        let mut result = self.clone();
        result.quantity = Some(lq * rq);
        result.precision = self.precision + rhs.precision;

        if !self.has_commodity() && rhs.has_commodity() {
            result.commodity = rhs.commodity.clone();
            result.style = rhs.style.clone();
        }
        result
    }
}

impl Mul for Amount {
    type Output = Amount;
    fn mul(self, rhs: Amount) -> Amount {
        (&self).mul(&rhs)
    }
}

impl Div for &Amount {
    type Output = Amount;

    fn div(self, rhs: &Amount) -> Amount {
        let lq = self
            .require_quantity()
            .expect("Cannot divide uninitialized amount");
        let rq = rhs
            .require_quantity()
            .expect("Cannot divide uninitialized amount");

        if rq.is_zero() {
            panic!("Divide by zero");
        }

        let mut result = self.clone();
        result.quantity = Some(lq / rq);
        result.precision = self.precision + rhs.precision + EXTEND_BY_DIGITS;

        if !self.has_commodity() && rhs.has_commodity() {
            result.commodity = rhs.commodity.clone();
            result.style = rhs.style.clone();
        }
        result
    }
}

impl Div for Amount {
    type Output = Amount;
    fn div(self, rhs: Amount) -> Amount {
        (&self).div(&rhs)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---- parsing ----------------------------------------------------------

    #[test]
    fn parse_simple_integer() {
        let a = Amount::parse("42").unwrap();
        assert_eq!(a.quantity_string(), "42");
        assert!(!a.has_commodity());
        assert_eq!(a.precision(), 0);
    }

    #[test]
    fn parse_simple_decimal() {
        let a = Amount::parse("10.50").unwrap();
        assert_eq!(a.precision(), 2);
        assert_eq!(a.quantity_string(), "10.50");
    }

    #[test]
    fn parse_negative() {
        let a = Amount::parse("-5.25").unwrap();
        assert!(a.is_negative());
        assert_eq!(a.quantity_string(), "-5.25");
    }

    #[test]
    fn parse_prefix_commodity() {
        let a = Amount::parse("$10.00").unwrap();
        assert_eq!(a.commodity(), Some("$"));
        assert_eq!(a.to_string(), "$10.00");
        assert!(a.style.prefix);
        assert!(!a.style.separated);
    }

    #[test]
    fn parse_prefix_commodity_separated() {
        let a = Amount::parse("$ 10.00").unwrap();
        assert_eq!(a.commodity(), Some("$"));
        assert_eq!(a.to_string(), "$ 10.00");
        assert!(a.style.prefix);
        assert!(a.style.separated);
    }

    #[test]
    fn parse_suffix_commodity() {
        let a = Amount::parse("10 AAPL").unwrap();
        assert_eq!(a.commodity(), Some("AAPL"));
        assert_eq!(a.to_string(), "10 AAPL");
        assert!(!a.style.prefix);
        assert!(a.style.separated);
    }

    #[test]
    fn parse_suffix_commodity_with_decimal() {
        let a = Amount::parse("-5.25 EUR").unwrap();
        assert_eq!(a.commodity(), Some("EUR"));
        assert_eq!(a.to_string(), "-5.25 EUR");
        assert!(a.is_negative());
    }

    #[test]
    fn parse_thousands_comma() {
        let a = Amount::parse("$1,000.00").unwrap();
        assert_eq!(a.commodity(), Some("$"));
        assert_eq!(a.precision(), 2);
        assert!(a.style.thousands);
        assert_eq!(a.to_string(), "$1,000.00");
    }

    #[test]
    fn parse_thousands_multiple_commas() {
        let a = Amount::parse("1,000,000").unwrap();
        assert!(a.style.thousands);
        assert_eq!(a.precision(), 0);
        // Commodity-less whole number displays as integer
        assert_eq!(a.quantity_string(), "1,000,000");
    }

    #[test]
    fn parse_decimal_comma_european() {
        let a = Amount::parse("10,50 EUR").unwrap();
        assert_eq!(a.commodity(), Some("EUR"));
        assert!(a.style.decimal_comma);
        assert_eq!(a.precision(), 2);
    }

    #[test]
    fn parse_european_with_period_thousands() {
        let a = Amount::parse("1.000,50 EUR").unwrap();
        assert_eq!(a.commodity(), Some("EUR"));
        assert!(a.style.decimal_comma);
        assert!(a.style.thousands);
        assert_eq!(a.precision(), 2);
    }

    #[test]
    fn parse_quoted_commodity() {
        let a = Amount::parse("10 \"MUTUAL FUND\"").unwrap();
        assert_eq!(a.commodity(), Some("MUTUAL FUND"));
    }

    #[test]
    fn parse_empty_fails() {
        assert!(Amount::parse("").is_err());
    }

    // ---- null / truth tests -----------------------------------------------

    #[test]
    fn null_amount() {
        let a = Amount::null();
        assert!(a.is_null());
        assert_eq!(a.to_string(), "<null>");
    }

    #[test]
    fn zero_detection() {
        let a = Amount::parse("0").unwrap();
        assert!(a.is_realzero());
        assert!(a.is_zero());
    }

    #[test]
    fn nonzero_detection() {
        let a = Amount::parse("1").unwrap();
        assert!(!a.is_zero());
        assert!(a.is_nonzero());
    }

    // ---- sign tests -------------------------------------------------------

    #[test]
    fn sign_positive() {
        let a = Amount::parse("42").unwrap();
        assert_eq!(a.sign(), 1);
        assert!(a.is_positive());
    }

    #[test]
    fn sign_negative() {
        let a = Amount::parse("-10").unwrap();
        assert_eq!(a.sign(), -1);
        assert!(a.is_negative());
    }

    #[test]
    fn sign_zero() {
        let a = Amount::parse("0").unwrap();
        assert_eq!(a.sign(), 0);
    }

    // ---- unary operations -------------------------------------------------

    #[test]
    fn negation() {
        let a = Amount::parse("$10.00").unwrap();
        let b = a.negated();
        assert_eq!(b.to_string(), "$-10.00");
    }

    #[test]
    fn abs_negative() {
        let a = Amount::parse("-$10.00").unwrap();
        let b = a.abs();
        assert_eq!(b.to_string(), "$10.00");
    }

    #[test]
    fn abs_positive() {
        let a = Amount::parse("$10.00").unwrap();
        let b = a.abs();
        assert_eq!(b.to_string(), "$10.00");
    }

    // ---- arithmetic -------------------------------------------------------

    #[test]
    fn add_same_commodity() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::parse("$20.00").unwrap();
        let c = &a + &b;
        assert_eq!(c.to_string(), "$30.00");
    }

    #[test]
    fn add_integers() {
        let a = Amount::parse("10").unwrap();
        let b = Amount::parse("20").unwrap();
        let c = &a + &b;
        assert_eq!(c.to_string(), "30");
    }

    #[test]
    fn sub_same_commodity() {
        let a = Amount::parse("$30.00").unwrap();
        let b = Amount::parse("$10.00").unwrap();
        let c = &a - &b;
        assert_eq!(c.to_string(), "$20.00");
    }

    #[test]
    fn mul_amount_by_integer() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::from_int(3);
        let c = &a * &b;
        assert_eq!(c.to_string(), "$30.00");
    }

    #[test]
    fn div_amount_by_integer() {
        let a = Amount::parse("$30.00").unwrap();
        let b = Amount::from_int(3);
        let c = &a / &b;
        // Division adds EXTEND_BY_DIGITS precision
        assert_eq!(c.commodity(), Some("$"));
        // Value should be 10
        let val = c.to_double().unwrap();
        assert!((val - 10.0).abs() < 1e-10);
    }

    #[test]
    #[should_panic(expected = "Divide by zero")]
    fn div_by_zero() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::from_int(0);
        let _ = &a / &b;
    }

    #[test]
    #[should_panic(expected = "different commodities")]
    fn add_different_commodities_panics() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::parse("10.00 EUR").unwrap();
        let _ = &a + &b;
    }

    #[test]
    fn mul_precision_tracking() {
        let a = Amount::parse("$10.00").unwrap(); // precision 2
        let b = Amount::parse("3.5").unwrap(); // precision 1
        let c = &a * &b;
        assert_eq!(c.precision(), 3); // 2 + 1
    }

    #[test]
    fn add_precision_max() {
        let a = Amount::parse("$10.00").unwrap(); // precision 2
        let b = Amount::parse("$5.0").unwrap(); // precision 1
        let c = &a + &b;
        assert_eq!(c.precision(), 2); // max(2, 1)
    }

    // ---- comparison -------------------------------------------------------

    #[test]
    fn compare_equal() {
        let a = Amount::parse("$10.00").unwrap();
        let b = Amount::parse("$10.00").unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn compare_less_than() {
        let a = Amount::parse("$5.00").unwrap();
        let b = Amount::parse("$10.00").unwrap();
        assert!(a < b);
    }

    #[test]
    fn compare_greater_than() {
        let a = Amount::parse("$15.00").unwrap();
        let b = Amount::parse("$10.00").unwrap();
        assert!(a > b);
    }

    #[test]
    fn compare_null_amounts() {
        let a = Amount::null();
        let b = Amount::null();
        assert_eq!(a, b);
    }

    #[test]
    fn compare_null_vs_non_null() {
        let a = Amount::null();
        let b = Amount::parse("10").unwrap();
        assert_ne!(a, b);
    }

    // ---- rounding ---------------------------------------------------------

    #[test]
    fn roundto_places() {
        let a = Amount::parse("10.456").unwrap();
        let b = a.roundto(2);
        assert_eq!(b.quantity_string(), "10.46");
    }

    #[test]
    fn round_half_away_from_zero() {
        let a = Amount::parse("10.555").unwrap();
        let b = a.roundto(2);
        assert_eq!(b.quantity_string(), "10.56");

        let c = Amount::parse("-10.555").unwrap();
        let d = c.roundto(2);
        assert_eq!(d.quantity_string(), "-10.56");
    }

    #[test]
    fn truncated() {
        let a = Amount::parse("10.789").unwrap();
        let b = a.truncated();
        assert_eq!(b.quantity_string(), "10.789");
    }

    #[test]
    fn floored() {
        let a = Amount::parse("10.7").unwrap();
        let b = a.floored();
        // floor(10.7) = 10, commodity-less whole number displays as integer
        assert_eq!(b.quantity_string(), "10");
    }

    #[test]
    fn ceilinged() {
        let a = Amount::parse("10.1").unwrap();
        let b = a.ceilinged();
        // ceil(10.1) = 11
        assert_eq!(b.quantity_string(), "11");
    }

    // ---- display ----------------------------------------------------------

    #[test]
    fn display_whole_number_no_commodity_as_integer() {
        // Commodity-less whole numbers should display without decimals
        let a = Amount::parse("100").unwrap();
        assert_eq!(a.to_string(), "100");
    }

    #[test]
    fn display_whole_number_with_commodity_keeps_precision() {
        let a = Amount::parse("$100.00").unwrap();
        assert_eq!(a.to_string(), "$100.00");
    }

    #[test]
    fn keep_precision() {
        let a = Amount::exact("10.5000").unwrap();
        assert!(a.keep_precision());
        assert_eq!(a.display_precision(), 4);
        assert_eq!(a.quantity_string(), "10.5000");
    }

    #[test]
    fn fullstring_shows_internal_precision() {
        let a = Amount::parse("$10.50").unwrap();
        assert_eq!(a.to_fullstring(), "$10.50");
    }

    // ---- from_int ---------------------------------------------------------

    #[test]
    fn from_int() {
        let a = Amount::from_int(42);
        assert_eq!(a.to_string(), "42");
        assert!(!a.has_commodity());
    }

    #[test]
    fn from_int_with_commodity() {
        let a = Amount::from_int(100).with_commodity("$");
        assert_eq!(a.commodity(), Some("$"));
    }

    // ---- number (strip commodity) -----------------------------------------

    #[test]
    fn number_strips_commodity() {
        let a = Amount::parse("$10.00").unwrap();
        let b = a.number();
        assert!(!b.has_commodity());
        // Commodity-less whole numbers display as integers (matching Python/C++ behavior)
        assert_eq!(b.quantity_string(), "10");
        assert_eq!(b.precision(), 2); // Internal precision preserved

        // Non-whole number retains decimals
        let c = Amount::parse("$10.50").unwrap();
        let d = c.number();
        assert_eq!(d.quantity_string(), "10.50");
    }

    // ---- neg operator -----------------------------------------------------

    #[test]
    fn neg_operator() {
        let a = Amount::parse("$10.00").unwrap();
        let b = -a;
        assert_eq!(b.to_string(), "$-10.00");
    }

    // ---- European formatting roundtrip ------------------------------------

    #[test]
    fn european_format_display() {
        let a = Amount::parse("1.000,50 EUR").unwrap();
        assert_eq!(a.to_string(), "1.000,50 EUR");
    }

    // ---- apostrophe thousands ---------------------------------------------

    #[test]
    fn apostrophe_thousands() {
        let a = Amount::parse("1'000'000").unwrap();
        assert!(a.style.thousands);
        assert_eq!(a.precision(), 0);
    }

    // ---- commodity propagation in arithmetic ------------------------------

    #[test]
    fn add_propagates_commodity() {
        let a = Amount::parse("10").unwrap();
        let b = Amount::parse("$5.00").unwrap();
        let c = &a + &b;
        assert_eq!(c.commodity(), Some("$"));
    }

    #[test]
    fn mul_propagates_commodity() {
        let a = Amount::from_int(3);
        let b = Amount::parse("$10.00").unwrap();
        let c = &a * &b;
        assert_eq!(c.commodity(), Some("$"));
    }

    // ---- in_place operations ----------------------------------------------

    #[test]
    fn in_place_negate() {
        let mut a = Amount::parse("$10.00").unwrap();
        a.in_place_negate();
        assert!(a.is_negative());
    }

    #[test]
    fn clear_commodity() {
        let mut a = Amount::parse("$10.00").unwrap();
        a.clear_commodity();
        assert!(!a.has_commodity());
    }

    // ---- to_double / to_long ----------------------------------------------

    #[test]
    fn to_double() {
        let a = Amount::parse("10.50").unwrap();
        let f = a.to_double().unwrap();
        assert!((f - 10.5).abs() < 1e-10);
    }

    #[test]
    fn to_long() {
        let a = Amount::parse("10.6").unwrap();
        let l = a.to_long().unwrap();
        assert_eq!(l, 11);
    }

    // ---- FromStr trait -----------------------------------------------------

    #[test]
    fn from_str_trait() {
        let a: Amount = "$10.00".parse().unwrap();
        assert_eq!(a.commodity(), Some("$"));
        assert_eq!(a.precision(), 2);
    }

    // ---- edge cases -------------------------------------------------------

    #[test]
    fn parse_zero_with_commodity() {
        let a = Amount::parse("$0.00").unwrap();
        assert!(a.is_zero());
        assert!(a.is_realzero());
        assert_eq!(a.to_string(), "$0.00");
    }

    #[test]
    fn parse_positive_sign() {
        let a = Amount::parse("+42").unwrap();
        assert_eq!(a.quantity_string(), "42");
        assert!(a.is_positive());
    }

    #[test]
    fn large_number() {
        let a = Amount::parse("999999999999999999").unwrap();
        assert_eq!(a.quantity_string(), "999999999999999999");
    }

    #[test]
    fn exact_rational_division() {
        // 1/3 should be exact in rational form
        let a = Amount::from_int(1);
        let b = Amount::from_int(3);
        let c = &a / &b;
        // Multiply back should be exact
        let d = &c * &b;
        assert_eq!(d.quantity().unwrap(), &BigRational::from_integer(BigInt::from(1)));
    }
}
