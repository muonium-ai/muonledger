//! Lot annotations for tracking cost basis and purchase details.
//!
//! Ported from ledger's `annotate.h` / `annotate.cc`. Lot annotations
//! attach additional metadata to commodity amounts:
//!
//! - **Price**: the per-unit purchase price `{$30.00}`
//! - **Date**: the purchase date `[2024-01-15]`
//! - **Tag**: a descriptive note `(lot-tag)`
//!
//! Example in journal syntax:
//! ```text
//! 2024/01/15 Buy stock
//!     Assets:Brokerage    10 AAPL {$150.00} [2024-01-15] (initial purchase)
//!     Assets:Checking     $-1500.00
//! ```

use std::fmt;

use chrono::NaiveDate;

use crate::amount::Amount;

// ---------------------------------------------------------------------------
// LotAnnotation
// ---------------------------------------------------------------------------

/// Annotation metadata attached to a commodity lot.
///
/// Tracks the price, date, and/or tag associated with a particular
/// acquisition of a commodity. Used for cost basis tracking, capital
/// gains calculations, and lot identification.
#[derive(Debug, Clone)]
pub struct LotAnnotation {
    /// The per-unit price at acquisition (e.g. `{$150.00}`).
    pub price: Option<Amount>,
    /// The date of acquisition (e.g. `[2024-01-15]`).
    pub date: Option<NaiveDate>,
    /// A descriptive tag (e.g. `(initial purchase)`).
    pub tag: Option<String>,
}

impl LotAnnotation {
    /// Create an empty annotation.
    pub fn new() -> Self {
        Self {
            price: None,
            date: None,
            tag: None,
        }
    }

    /// Create an annotation with a price.
    pub fn with_price(price: Amount) -> Self {
        Self {
            price: Some(price),
            date: None,
            tag: None,
        }
    }

    /// Create an annotation with a price and date.
    pub fn with_price_and_date(price: Amount, date: NaiveDate) -> Self {
        Self {
            price: Some(price),
            date: Some(date),
            tag: None,
        }
    }

    /// Create a fully specified annotation.
    pub fn full(price: Amount, date: NaiveDate, tag: &str) -> Self {
        Self {
            price: Some(price),
            date: Some(date),
            tag: Some(tag.to_string()),
        }
    }

    /// Return true if this annotation has no data.
    pub fn is_empty(&self) -> bool {
        self.price.is_none() && self.date.is_none() && self.tag.is_none()
    }

    /// Return true if this annotation has a price.
    pub fn has_price(&self) -> bool {
        self.price.is_some()
    }

    /// Return true if this annotation has a date.
    pub fn has_date(&self) -> bool {
        self.date.is_some()
    }

    /// Return true if this annotation has a tag.
    pub fn has_tag(&self) -> bool {
        self.tag.is_some()
    }

    /// Parse a lot annotation from text like `{$30.00} [2024-01-15] (note)`.
    ///
    /// Handles:
    /// - `{AMOUNT}` — per-unit price
    /// - `[DATE]` — acquisition date
    /// - `(TAG)` — descriptive tag
    ///
    /// Returns the parsed annotation and the number of bytes consumed.
    pub fn parse(text: &str) -> Result<(Self, usize), String> {
        let mut annotation = LotAnnotation::new();
        let mut pos = 0;
        let bytes = text.as_bytes();

        while pos < bytes.len() {
            // Skip whitespace
            while pos < bytes.len() && (bytes[pos] == b' ' || bytes[pos] == b'\t') {
                pos += 1;
            }
            if pos >= bytes.len() {
                break;
            }

            match bytes[pos] {
                b'{' => {
                    // Price annotation: {AMOUNT}
                    pos += 1;
                    // Skip optional {= for lot fixation
                    if pos < bytes.len() && bytes[pos] == b'=' {
                        pos += 1;
                    }
                    if let Some(close) = text[pos..].find('}') {
                        let price_text = text[pos..pos + close].trim();
                        let price = Amount::parse(price_text)
                            .map_err(|e| format!("Invalid lot price: {}", e))?;
                        annotation.price = Some(price);
                        pos += close + 1;
                    } else {
                        return Err("Expected '}' for lot price".to_string());
                    }
                }
                b'[' => {
                    // Date annotation: [DATE]
                    pos += 1;
                    if let Some(close) = text[pos..].find(']') {
                        let date_text = text[pos..pos + close].trim();
                        let date = parse_lot_date(date_text)
                            .map_err(|e| format!("Invalid lot date: {}", e))?;
                        annotation.date = Some(date);
                        pos += close + 1;
                    } else {
                        return Err("Expected ']' for lot date".to_string());
                    }
                }
                b'(' => {
                    // Tag annotation: (TAG)
                    pos += 1;
                    if let Some(close) = text[pos..].find(')') {
                        let tag_text = text[pos..pos + close].trim();
                        annotation.tag = Some(tag_text.to_string());
                        pos += close + 1;
                    } else {
                        return Err("Expected ')' for lot tag".to_string());
                    }
                }
                _ => break,
            }
        }

        Ok((annotation, pos))
    }
}

impl Default for LotAnnotation {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for LotAnnotation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut parts = Vec::new();
        if let Some(ref price) = self.price {
            parts.push(format!("{{{}}}", price));
        }
        if let Some(ref date) = self.date {
            parts.push(format!("[{}]", date.format("%Y/%m/%d")));
        }
        if let Some(ref tag) = self.tag {
            parts.push(format!("({})", tag));
        }
        write!(f, "{}", parts.join(" "))
    }
}

impl PartialEq for LotAnnotation {
    fn eq(&self, other: &Self) -> bool {
        // Compare price by double value (sufficient for lot matching)
        let price_eq = match (&self.price, &other.price) {
            (Some(a), Some(b)) => a.to_double() == b.to_double()
                && a.commodity() == b.commodity(),
            (None, None) => true,
            _ => false,
        };
        price_eq && self.date == other.date && self.tag == other.tag
    }
}

// ---------------------------------------------------------------------------
// Date parsing helper
// ---------------------------------------------------------------------------

fn parse_lot_date(text: &str) -> Result<NaiveDate, String> {
    // Try common date formats
    for fmt in &["%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"] {
        if let Ok(d) = NaiveDate::parse_from_str(text, fmt) {
            return Ok(d);
        }
    }
    Err(format!("Cannot parse lot date: {:?}", text))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    #[test]
    fn new_empty() {
        let ann = LotAnnotation::new();
        assert!(ann.is_empty());
        assert!(!ann.has_price());
        assert!(!ann.has_date());
        assert!(!ann.has_tag());
    }

    #[test]
    fn with_price() {
        let ann = LotAnnotation::with_price(Amount::parse("$30.00").unwrap());
        assert!(!ann.is_empty());
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert!(!ann.has_tag());
    }

    #[test]
    fn with_price_and_date() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let ann = LotAnnotation::with_price_and_date(
            Amount::parse("$30.00").unwrap(),
            date,
        );
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert_eq!(ann.date.unwrap(), date);
    }

    #[test]
    fn full_annotation() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let ann = LotAnnotation::full(
            Amount::parse("$150.00").unwrap(),
            date,
            "initial purchase",
        );
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("initial purchase"));
    }

    #[test]
    fn default_is_empty() {
        let ann = LotAnnotation::default();
        assert!(ann.is_empty());
    }

    #[test]
    fn display_price_only() {
        let ann = LotAnnotation::with_price(Amount::parse("$30.00").unwrap());
        let s = format!("{}", ann);
        assert!(s.contains("{"));
        assert!(s.contains("}"));
        assert!(s.contains("30"));
    }

    #[test]
    fn display_full() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let ann = LotAnnotation::full(
            Amount::parse("$150.00").unwrap(),
            date,
            "lot1",
        );
        let s = format!("{}", ann);
        assert!(s.contains("{"));
        assert!(s.contains("[2024/01/15]"));
        assert!(s.contains("(lot1)"));
    }

    #[test]
    fn display_empty() {
        let ann = LotAnnotation::new();
        let s = format!("{}", ann);
        assert!(s.is_empty());
    }

    #[test]
    fn parse_price_annotation() {
        let (ann, consumed) = LotAnnotation::parse("{$30.00}").unwrap();
        assert!(ann.has_price());
        assert!(!ann.has_date());
        assert_eq!(consumed, 8);
    }

    #[test]
    fn parse_date_annotation() {
        let (ann, consumed) = LotAnnotation::parse("[2024/01/15]").unwrap();
        assert!(!ann.has_price());
        assert!(ann.has_date());
        assert_eq!(ann.date.unwrap(), NaiveDate::from_ymd_opt(2024, 1, 15).unwrap());
        assert_eq!(consumed, 12);
    }

    #[test]
    fn parse_tag_annotation() {
        let (ann, _) = LotAnnotation::parse("(lot1)").unwrap();
        assert!(!ann.has_price());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("lot1"));
    }

    #[test]
    fn parse_full_annotation() {
        let (ann, _) = LotAnnotation::parse("{$150.00} [2024-01-15] (initial)").unwrap();
        assert!(ann.has_price());
        assert!(ann.has_date());
        assert!(ann.has_tag());
        assert_eq!(ann.tag.as_deref(), Some("initial"));
        assert_eq!(ann.date.unwrap(), NaiveDate::from_ymd_opt(2024, 1, 15).unwrap());
    }

    #[test]
    fn parse_price_with_fixation() {
        let (ann, _) = LotAnnotation::parse("{=$30.00}").unwrap();
        assert!(ann.has_price());
    }

    #[test]
    fn parse_empty_string() {
        let (ann, consumed) = LotAnnotation::parse("").unwrap();
        assert!(ann.is_empty());
        assert_eq!(consumed, 0);
    }

    #[test]
    fn parse_non_annotation() {
        let (ann, consumed) = LotAnnotation::parse("something else").unwrap();
        assert!(ann.is_empty());
        assert_eq!(consumed, 0);
    }

    #[test]
    fn parse_unclosed_brace() {
        let result = LotAnnotation::parse("{$30.00");
        assert!(result.is_err());
    }

    #[test]
    fn parse_unclosed_bracket() {
        let result = LotAnnotation::parse("[2024-01-15");
        assert!(result.is_err());
    }

    #[test]
    fn parse_unclosed_paren() {
        let result = LotAnnotation::parse("(tag without closing");
        assert!(result.is_err());
    }

    #[test]
    fn parse_lot_date_formats() {
        assert!(parse_lot_date("2024/01/15").is_ok());
        assert!(parse_lot_date("2024-01-15").is_ok());
        assert!(parse_lot_date("2024.01.15").is_ok());
        assert!(parse_lot_date("invalid").is_err());
    }

    #[test]
    fn equality() {
        let date = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let a = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot1");
        let b = LotAnnotation::full(Amount::parse("$30.00").unwrap(), date, "lot1");
        assert_eq!(a, b);
    }

    #[test]
    fn inequality_price() {
        let a = LotAnnotation::with_price(Amount::parse("$30.00").unwrap());
        let b = LotAnnotation::with_price(Amount::parse("$31.00").unwrap());
        assert_ne!(a, b);
    }

    #[test]
    fn inequality_date() {
        let d1 = NaiveDate::from_ymd_opt(2024, 1, 15).unwrap();
        let d2 = NaiveDate::from_ymd_opt(2024, 1, 16).unwrap();
        let a = LotAnnotation::with_price_and_date(Amount::parse("$30.00").unwrap(), d1);
        let b = LotAnnotation::with_price_and_date(Amount::parse("$30.00").unwrap(), d2);
        assert_ne!(a, b);
    }
}
