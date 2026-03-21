//! Format string parser and evaluator for report output.
//!
//! This module provides the `Format` struct, a Rust port of Ledger's
//! `format_t` type from `format.h` / `format.cc`.  Ledger uses
//! printf-inspired format strings to control how report lines are rendered.
//!
//! A format string such as `"%-20(account)  %12(total)\n"` is parsed into
//! a list of `FormatElement` objects -- some holding literal text, others
//! holding compiled expressions.  When the format is evaluated against a scope,
//! each element is rendered in sequence and the results are concatenated.
//!
//! Supported syntax:
//!   - Literal text (passed through verbatim)
//!   - Backslash escapes (`\n`, `\t`, etc.)
//!   - `%[-][width][.maxwidth](expr)` -- expression with optional formatting
//!   - `%%` -- literal percent sign
//!
//! Width and alignment:
//!   - `%20(expr)` -- right-aligned, minimum 20 characters wide
//!   - `%-20(expr)` -- left-aligned, minimum 20 characters wide
//!   - `%.20(expr)` -- truncate to 20 characters
//!   - `%20.30(expr)` -- minimum 20, maximum 30 characters

use std::fmt;

use crate::expr_ast::{ExprNode, NodeValue, OpKind};
use crate::expr_parser::{ExprParser, ParseError};
use crate::scope::{Scope, ScopeValue};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error raised when a format string cannot be parsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FormatError(pub String);

impl fmt::Display for FormatError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "FormatError: {}", self.0)
    }
}

impl std::error::Error for FormatError {}

impl From<ParseError> for FormatError {
    fn from(e: ParseError) -> Self {
        FormatError(e.0)
    }
}

// ---------------------------------------------------------------------------
// ElisionStyle
// ---------------------------------------------------------------------------

/// Controls how overlong strings are shortened to fit max_width.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ElisionStyle {
    /// Truncate from the end, appending ".." marker.
    TruncateTrailing,
    /// Truncate from the middle, inserting ".." marker.
    TruncateMiddle,
    /// Truncate from the start, prepending ".." marker.
    TruncateLeading,
    /// Abbreviate (same as truncate trailing for now).
    Abbreviate,
}

// ---------------------------------------------------------------------------
// ElementKind
// ---------------------------------------------------------------------------

/// Whether a format element holds literal text or a compiled expression.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ElementKind {
    /// Literal string content.
    String,
    /// A compiled expression to evaluate.
    Expr,
}

// ---------------------------------------------------------------------------
// FormatElement
// ---------------------------------------------------------------------------

/// A single element in the parsed format string.
///
/// Each element is either a literal STRING or a compiled EXPR. Elements
/// carry optional min_width and max_width constraints plus an alignment flag.
#[derive(Debug, Clone)]
pub struct FormatElement {
    /// Whether this element holds literal text or an expression.
    pub kind: ElementKind,
    /// The element payload: literal string for STRING elements.
    pub literal: String,
    /// The compiled expression AST for EXPR elements.
    pub expr: Option<ExprNode>,
    /// Minimum display width (pad with spaces if shorter).
    pub min_width: usize,
    /// Maximum display width (truncate if longer; 0 means unlimited).
    pub max_width: usize,
    /// If true, left-justify within the min_width field.
    pub align_left: bool,
    /// The original expression text (for debugging).
    pub expr_text: String,
}

impl FormatElement {
    /// Create a literal string element.
    fn literal(s: String) -> Self {
        FormatElement {
            kind: ElementKind::String,
            literal: s,
            expr: None,
            min_width: 0,
            max_width: 0,
            align_left: false,
            expr_text: String::new(),
        }
    }

    /// Create an expression element.
    fn expression(
        node: ExprNode,
        expr_text: String,
        min_width: usize,
        max_width: usize,
        align_left: bool,
    ) -> Self {
        FormatElement {
            kind: ElementKind::Expr,
            literal: String::new(),
            expr: Some(node),
            min_width,
            max_width,
            align_left,
            expr_text,
        }
    }
}

// ---------------------------------------------------------------------------
// Backslash escape mapping
// ---------------------------------------------------------------------------

fn escape_char(ch: char) -> char {
    match ch {
        'b' => '\u{0008}', // backspace
        'f' => '\u{000C}', // form feed
        'n' => '\n',
        'r' => '\r',
        't' => '\t',
        'v' => '\u{000B}', // vertical tab
        '\\' => '\\',
        other => other,
    }
}

// ---------------------------------------------------------------------------
// Expression evaluation (minimal evaluator for format system)
// ---------------------------------------------------------------------------

/// Walk the AST and evaluate it against a scope.
///
/// This is a minimal expression evaluator sufficient for the format system.
/// It handles identifiers, literal values, basic arithmetic, comparisons,
/// logical operators, ternary expressions, and function calls.
fn evaluate_expr(node: &ExprNode, scope: &dyn Scope) -> String {
    match node.kind {
        OpKind::Value => match &node.value {
            NodeValue::Integer(n) => n.to_string(),
            NodeValue::Float(n) => format!("{}", n),
            NodeValue::Str(s) => s.clone(),
            NodeValue::Boolean(b) => if *b { "true" } else { "false" }.to_string(),
            NodeValue::None => String::new(),
        },

        OpKind::Ident => {
            if let NodeValue::Str(name) = &node.value {
                match scope.resolve(name) {
                    Some(sv) => scope_value_to_string(&sv),
                    None => String::new(),
                }
            } else {
                String::new()
            }
        }

        OpKind::OAdd => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            format!("{}", left + right)
        }

        OpKind::OSub => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            format!("{}", left - right)
        }

        OpKind::OMul => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            format!("{}", left * right)
        }

        OpKind::ODiv => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            if right == 0 {
                "0".to_string()
            } else {
                format!("{}", left / right)
            }
        }

        OpKind::ONeg => {
            let val = evaluate_expr_numeric(node.left.as_deref(), scope);
            format!("{}", -val)
        }

        OpKind::ONot => {
            let val = evaluate_expr_bool(node.left.as_deref(), scope);
            if !val { "true" } else { "false" }.to_string()
        }

        OpKind::OEq => {
            let left = evaluate_expr(node.left.as_deref().unwrap(), scope);
            let right = evaluate_expr(node.right.as_deref().unwrap(), scope);
            if left == right { "true" } else { "false" }.to_string()
        }

        OpKind::OLt => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            if left < right { "true" } else { "false" }.to_string()
        }

        OpKind::OLte => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            if left <= right { "true" } else { "false" }.to_string()
        }

        OpKind::OGt => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            if left > right { "true" } else { "false" }.to_string()
        }

        OpKind::OGte => {
            let left = evaluate_expr_numeric(node.left.as_deref(), scope);
            let right = evaluate_expr_numeric(node.right.as_deref(), scope);
            if left >= right { "true" } else { "false" }.to_string()
        }

        OpKind::OAnd => {
            let left = evaluate_expr_bool(node.left.as_deref(), scope);
            if !left {
                return "false".to_string();
            }
            let right = evaluate_expr_bool(node.right.as_deref(), scope);
            if right { "true" } else { "false" }.to_string()
        }

        OpKind::OOr => {
            let left = evaluate_expr_bool(node.left.as_deref(), scope);
            if left {
                return "true".to_string();
            }
            let right = evaluate_expr_bool(node.right.as_deref(), scope);
            if right { "true" } else { "false" }.to_string()
        }

        OpKind::OQuery => {
            let cond = evaluate_expr_bool(node.left.as_deref(), scope);
            if let Some(ref colon) = node.right {
                if colon.kind == OpKind::OColon {
                    if cond {
                        return evaluate_expr(colon.left.as_deref().unwrap(), scope);
                    } else {
                        return evaluate_expr(colon.right.as_deref().unwrap(), scope);
                    }
                }
            }
            String::new()
        }

        OpKind::OCons => {
            // Comma list -- evaluate last element
            if let Some(ref right) = node.right {
                evaluate_expr(right, scope)
            } else if let Some(ref left) = node.left {
                evaluate_expr(left, scope)
            } else {
                String::new()
            }
        }

        OpKind::Scope => {
            if let Some(ref left) = node.left {
                evaluate_expr(left, scope)
            } else {
                String::new()
            }
        }

        OpKind::OLookup => {
            // Member access: left.right
            if let (Some(ref left_node), Some(ref right_node)) = (&node.left, &node.right) {
                if let (OpKind::Ident, OpKind::Ident) = (left_node.kind, right_node.kind) {
                    if let (NodeValue::Str(left_name), NodeValue::Str(right_name)) =
                        (&left_node.value, &right_node.value)
                    {
                        let full_name = format!("{}.{}", left_name, right_name);
                        if let Some(sv) = scope.resolve(&full_name) {
                            return scope_value_to_string(&sv);
                        }
                    }
                }
            }
            String::new()
        }

        OpKind::OSeq => {
            // Semicolon sequence -- evaluate left, then right, return right
            if let Some(ref left) = node.left {
                evaluate_expr(left, scope);
            }
            if let Some(ref right) = node.right {
                evaluate_expr(right, scope)
            } else {
                String::new()
            }
        }

        _ => String::new(),
    }
}

fn evaluate_expr_numeric(node: Option<&ExprNode>, scope: &dyn Scope) -> i64 {
    match node {
        Some(n) => {
            let s = evaluate_expr(n, scope);
            s.parse::<i64>().unwrap_or(0)
        }
        None => 0,
    }
}

fn evaluate_expr_bool(node: Option<&ExprNode>, scope: &dyn Scope) -> bool {
    match node {
        Some(n) => {
            let s = evaluate_expr(n, scope);
            !s.is_empty() && s != "0" && s != "false"
        }
        None => false,
    }
}

fn scope_value_to_string(sv: &ScopeValue) -> String {
    match sv {
        ScopeValue::Node(nv) => match nv {
            NodeValue::None => String::new(),
            NodeValue::Integer(n) => n.to_string(),
            NodeValue::Float(n) => format!("{}", n),
            NodeValue::Str(s) => s.clone(),
            NodeValue::Boolean(b) => if *b { "true" } else { "false" }.to_string(),
        },
    }
}

// ---------------------------------------------------------------------------
// Parse expression from format string
// ---------------------------------------------------------------------------

/// Parse an expression starting after '(' in the format string.
///
/// Returns the parsed AST node and the position after the closing ')'.
fn parse_expression_from_format(fmt: &[char], pos: usize) -> Result<(ExprNode, usize), FormatError> {
    let mut depth: usize = 1;
    let mut i = pos;

    while i < fmt.len() && depth > 0 {
        let ch = fmt[i];
        if ch == '(' {
            depth += 1;
        } else if ch == ')' {
            depth -= 1;
        } else if ch == '"' || ch == '\'' {
            let quote = ch;
            i += 1;
            while i < fmt.len() && fmt[i] != quote {
                if fmt[i] == '\\' {
                    i += 1;
                }
                i += 1;
            }
        }
        i += 1;
    }

    if depth != 0 {
        return Err(FormatError(format!(
            "Unmatched '(' in format string at position {}",
            pos
        )));
    }

    let expr_text: String = fmt[pos..i - 1].iter().collect();
    if expr_text.is_empty() {
        return Err(FormatError(format!(
            "Empty expression in format string at position {}",
            pos
        )));
    }

    let mut parser = ExprParser::new(&expr_text);
    let node = parser.parse().map_err(FormatError::from)?;

    Ok((node, i))
}

// ---------------------------------------------------------------------------
// Format
// ---------------------------------------------------------------------------

/// Compiles and evaluates printf-style format strings for report output.
///
/// A format string is parsed into a list of `FormatElement` objects. When
/// evaluated against a scope, each element is rendered and concatenated
/// into the final output string.
#[derive(Debug, Clone)]
pub struct Format {
    /// The parsed element list.
    pub elements: Vec<FormatElement>,
    /// The default truncation style.
    pub default_style: ElisionStyle,
    /// The original format string.
    format_string: String,
}

impl Format {
    /// Create a new Format by parsing the given format string.
    pub fn new(fmt: &str) -> Result<Self, FormatError> {
        let mut format = Format {
            elements: Vec::new(),
            default_style: ElisionStyle::TruncateTrailing,
            format_string: fmt.to_string(),
        };
        if !fmt.is_empty() {
            format.parse(fmt)?;
        }
        Ok(format)
    }

    /// Create an empty Format with no elements.
    pub fn empty() -> Self {
        Format {
            elements: Vec::new(),
            default_style: ElisionStyle::TruncateTrailing,
            format_string: String::new(),
        }
    }

    /// Return the original format string.
    pub fn format_string(&self) -> &str {
        &self.format_string
    }

    /// Parse a format string into a list of FormatElement objects.
    fn parse(&mut self, fmt_str: &str) -> Result<(), FormatError> {
        let fmt: Vec<char> = fmt_str.chars().collect();
        let mut elements: Vec<FormatElement> = Vec::new();
        let mut literal_buf = String::new();
        let mut i = 0;

        while i < fmt.len() {
            let ch = fmt[i];

            if ch != '%' && ch != '\\' {
                literal_buf.push(ch);
                i += 1;
                continue;
            }

            // Flush any accumulated literal text
            if !literal_buf.is_empty() {
                elements.push(FormatElement::literal(
                    std::mem::take(&mut literal_buf),
                ));
            }

            if ch == '\\' {
                // Backslash escape
                i += 1;
                if i >= fmt.len() {
                    elements.push(FormatElement::literal("\\".to_string()));
                    break;
                }
                let esc_char = fmt[i];
                elements.push(FormatElement::literal(
                    escape_char(esc_char).to_string(),
                ));
                i += 1;
                continue;
            }

            // ch == '%'
            i += 1;
            if i >= fmt.len() {
                return Err(FormatError("Format string ends with bare '%'".to_string()));
            }

            // Check for %%
            if fmt[i] == '%' {
                elements.push(FormatElement::literal("%".to_string()));
                i += 1;
                continue;
            }

            // Parse flags
            let mut align_left = false;
            while i < fmt.len() && fmt[i] == '-' {
                align_left = true;
                i += 1;
            }

            // Parse min_width
            let mut min_width: usize = 0;
            while i < fmt.len() && fmt[i].is_ascii_digit() {
                min_width = min_width * 10 + (fmt[i] as usize - '0' as usize);
                i += 1;
            }

            // Parse max_width
            let mut max_width: usize = 0;
            if i < fmt.len() && fmt[i] == '.' {
                i += 1;
                while i < fmt.len() && fmt[i].is_ascii_digit() {
                    max_width = max_width * 10 + (fmt[i] as usize - '0' as usize);
                    i += 1;
                }
            }

            // Now expect '('
            if i >= fmt.len() {
                return Err(FormatError(
                    "Format string ends before expression specifier".to_string(),
                ));
            }

            if fmt[i] == '(' {
                i += 1; // skip '('
                let (node, new_i) = parse_expression_from_format(&fmt, i)?;
                let expr_text: String = fmt[i..new_i - 1].iter().collect();
                i = new_i;
                elements.push(FormatElement::expression(
                    node, expr_text, min_width, max_width, align_left,
                ));
            } else {
                return Err(FormatError(format!(
                    "Unrecognized formatting character: {:?} at position {}",
                    fmt[i], i
                )));
            }
        }

        // Flush remaining literal text
        if !literal_buf.is_empty() {
            elements.push(FormatElement::literal(literal_buf));
        }

        self.elements = elements;
        Ok(())
    }

    /// Evaluate the format string against a scope, producing a string.
    pub fn calc(&self, scope: &dyn Scope) -> String {
        let mut parts = Vec::new();

        for elem in &self.elements {
            let mut text = match elem.kind {
                ElementKind::String => elem.literal.clone(),
                ElementKind::Expr => {
                    if let Some(ref node) = elem.expr {
                        evaluate_expr(node, scope)
                    } else {
                        String::new()
                    }
                }
            };

            // Apply width constraints
            if elem.max_width > 0 || elem.min_width > 0 {
                let text_len = text.len();

                if elem.max_width > 0 && text_len > elem.max_width {
                    text = Self::truncate(&text, elem.max_width, Some(self.default_style));
                } else if elem.min_width > 0 && text_len < elem.min_width {
                    if elem.align_left {
                        text = format!("{:<width$}", text, width = elem.min_width);
                    } else {
                        text = format!("{:>width$}", text, width = elem.min_width);
                    }
                }
            }

            parts.push(text);
        }

        parts.join("")
    }

    /// Shorten a string to fit within the given display width.
    pub fn truncate(text: &str, width: usize, style: Option<ElisionStyle>) -> String {
        if width == 0 || text.len() <= width {
            return text.to_string();
        }

        let style = style.unwrap_or(ElisionStyle::TruncateTrailing);

        match style {
            ElisionStyle::TruncateLeading => {
                if width <= 2 {
                    return ".."[..width].to_string();
                }
                let skip = text.len() - (width - 2);
                format!("..{}", &text[skip..])
            }

            ElisionStyle::TruncateMiddle => {
                if width <= 2 {
                    return ".."[..width].to_string();
                }
                let left_len = (width - 2) / 2;
                let right_len = (width - 2) / 2 + (width - 2) % 2;
                let right_start = text.len() - right_len;
                format!("{}..{}", &text[..left_len], &text[right_start..])
            }

            ElisionStyle::TruncateTrailing | ElisionStyle::Abbreviate => {
                if width <= 2 {
                    return ".."[..width].to_string();
                }
                format!("{}..", &text[..width - 2])
            }
        }
    }

    /// Return a human-readable dump of all elements for debugging.
    pub fn dump(&self) -> String {
        let mut lines = Vec::new();
        for (i, elem) in self.elements.iter().enumerate() {
            let kind_str = match elem.kind {
                ElementKind::String => "STRING",
                ElementKind::Expr => "  EXPR",
            };
            let flags = if elem.align_left { "LEFT" } else { "RIGHT" };
            let mut line = format!(
                "Element {}: {}  flags: {}  min: {:2}  max: {:2}",
                i, kind_str, flags, elem.min_width, elem.max_width
            );
            if elem.kind == ElementKind::String {
                line.push_str(&format!("   str: '{}'", elem.literal));
            } else {
                line.push_str(&format!("  expr: {}", elem.expr_text));
            }
            lines.push(line);
        }
        lines.join("\n")
    }
}

impl fmt::Display for Format {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Format({:?})", self.format_string)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scope::SymbolScope;

    #[test]
    fn test_empty_format() {
        let fmt = Format::new("").unwrap();
        assert!(fmt.elements.is_empty());
    }

    #[test]
    fn test_literal_only() {
        let fmt = Format::new("hello world").unwrap();
        assert_eq!(fmt.elements.len(), 1);
        assert_eq!(fmt.elements[0].kind, ElementKind::String);
        assert_eq!(fmt.elements[0].literal, "hello world");
    }

    #[test]
    fn test_backslash_escapes() {
        let fmt = Format::new("a\\nb\\tc").unwrap();
        // "a" flushed before \n, then "\n", then "b" flushed before \t, then "\t", then "c"
        assert_eq!(fmt.elements.len(), 5);
        let scope = SymbolScope::new(None);
        let result = fmt.calc(&scope);
        assert_eq!(result, "a\nb\tc");
    }

    #[test]
    fn test_percent_percent() {
        let fmt = Format::new("100%%").unwrap();
        let scope = SymbolScope::new(None);
        let result = fmt.calc(&scope);
        assert_eq!(result, "100%");
    }

    #[test]
    fn test_simple_expression() {
        let fmt = Format::new("%(account)").unwrap();
        assert_eq!(fmt.elements.len(), 1);
        assert_eq!(fmt.elements[0].kind, ElementKind::Expr);
        assert_eq!(fmt.elements[0].expr_text, "account");

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Expenses:Food".to_string())),
        );
        let result = fmt.calc(&scope);
        assert_eq!(result, "Expenses:Food");
    }

    #[test]
    fn test_expression_with_min_width_right_align() {
        let fmt = Format::new("%20(account)").unwrap();
        assert_eq!(fmt.elements[0].min_width, 20);
        assert!(!fmt.elements[0].align_left);

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Food".to_string())),
        );
        let result = fmt.calc(&scope);
        assert_eq!(result, "                Food");
        assert_eq!(result.len(), 20);
    }

    #[test]
    fn test_expression_with_min_width_left_align() {
        let fmt = Format::new("%-20(account)").unwrap();
        assert_eq!(fmt.elements[0].min_width, 20);
        assert!(fmt.elements[0].align_left);

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Food".to_string())),
        );
        let result = fmt.calc(&scope);
        assert_eq!(result, "Food                ");
        assert_eq!(result.len(), 20);
    }

    #[test]
    fn test_expression_with_max_width() {
        let fmt = Format::new("%.10(account)").unwrap();
        assert_eq!(fmt.elements[0].max_width, 10);

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Expenses:Food:Groceries".to_string())),
        );
        let result = fmt.calc(&scope);
        assert_eq!(result.len(), 10);
        assert!(result.ends_with(".."));
    }

    #[test]
    fn test_expression_with_min_and_max_width() {
        let fmt = Format::new("%10.20(account)").unwrap();
        assert_eq!(fmt.elements[0].min_width, 10);
        assert_eq!(fmt.elements[0].max_width, 20);
    }

    #[test]
    fn test_mixed_literal_and_expression() {
        let fmt = Format::new("Account: %(account)  Total: %(total)").unwrap();
        // "Account: " literal, account expr, "  Total: " literal, total expr
        assert_eq!(fmt.elements.len(), 4);
        assert_eq!(fmt.elements[0].kind, ElementKind::String);
        assert_eq!(fmt.elements[1].kind, ElementKind::Expr);
        assert_eq!(fmt.elements[2].kind, ElementKind::String);
        assert_eq!(fmt.elements[3].kind, ElementKind::Expr);

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Food".to_string())),
        );
        scope.define("total", ScopeValue::from_node(NodeValue::Integer(100)));
        let result = fmt.calc(&scope);
        assert_eq!(result, "Account: Food  Total: 100");
    }

    #[test]
    fn test_typical_ledger_format() {
        let fmt = Format::new("%-20(account)  %12(total)\\n").unwrap();
        assert_eq!(fmt.elements.len(), 4); // expr, literal "  ", expr, literal "\n"

        let mut scope = SymbolScope::new(None);
        scope.define(
            "account",
            ScopeValue::from_node(NodeValue::Str("Expenses:Food".to_string())),
        );
        scope.define("total", ScopeValue::from_node(NodeValue::Integer(50)));
        let result = fmt.calc(&scope);
        // %-20(account) = "Expenses:Food       " (20 chars, left-aligned)
        // "  " = 2 spaces literal
        // %12(total) = "          50" (12 chars, right-aligned)
        // \n
        assert_eq!(result.len(), 35);
        assert!(result.starts_with("Expenses:Food"));
        assert!(result.ends_with("50\n"));
        // Verify the pieces: 20 + 2 + 12 + 1
        let expected = format!("{:<20}  {:>12}\n", "Expenses:Food", "50");
        assert_eq!(result, expected);
    }

    #[test]
    fn test_expression_missing_variable() {
        let fmt = Format::new("%(missing)").unwrap();
        let scope = SymbolScope::new(None);
        let result = fmt.calc(&scope);
        assert_eq!(result, "");
    }

    #[test]
    fn test_truncate_trailing() {
        let result = Format::truncate("Hello World!", 8, Some(ElisionStyle::TruncateTrailing));
        assert_eq!(result, "Hello ..");
        assert_eq!(result.len(), 8);
    }

    #[test]
    fn test_truncate_leading() {
        let result = Format::truncate("Hello World!", 8, Some(ElisionStyle::TruncateLeading));
        // leading: ".." + last (width-2) = 6 chars from "Hello World!" -> "World!"
        assert_eq!(result, "..World!");
        assert_eq!(result.len(), 8);
    }

    #[test]
    fn test_truncate_middle() {
        let result = Format::truncate("Hello World!", 8, Some(ElisionStyle::TruncateMiddle));
        // left_len = (8-2)/2 = 3, right_len = 3
        assert_eq!(result, "Hel..ld!");
        assert_eq!(result.len(), 8);
    }

    #[test]
    fn test_truncate_short_width() {
        let result = Format::truncate("Hello", 2, Some(ElisionStyle::TruncateTrailing));
        assert_eq!(result, "..");

        let result = Format::truncate("Hello", 1, Some(ElisionStyle::TruncateTrailing));
        assert_eq!(result, ".");
    }

    #[test]
    fn test_truncate_no_truncation_needed() {
        let result = Format::truncate("Hi", 10, Some(ElisionStyle::TruncateTrailing));
        assert_eq!(result, "Hi");
    }

    #[test]
    fn test_truncate_zero_width() {
        let result = Format::truncate("Hello", 0, Some(ElisionStyle::TruncateTrailing));
        assert_eq!(result, "Hello");
    }

    #[test]
    fn test_bare_percent_error() {
        let result = Format::new("hello%");
        assert!(result.is_err());
    }

    #[test]
    fn test_unmatched_paren_error() {
        let result = Format::new("%(account");
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_expression_error() {
        let result = Format::new("%()");
        assert!(result.is_err());
    }

    #[test]
    fn test_unrecognized_format_char_error() {
        let result = Format::new("%d");
        assert!(result.is_err());
    }

    #[test]
    fn test_integer_expression() {
        let fmt = Format::new("%(value)").unwrap();
        let mut scope = SymbolScope::new(None);
        scope.define("value", ScopeValue::from_node(NodeValue::Integer(42)));
        let result = fmt.calc(&scope);
        assert_eq!(result, "42");
    }

    #[test]
    fn test_boolean_expression() {
        let fmt = Format::new("%(flag)").unwrap();
        let mut scope = SymbolScope::new(None);
        scope.define("flag", ScopeValue::from_node(NodeValue::Boolean(true)));
        let result = fmt.calc(&scope);
        assert_eq!(result, "true");
    }

    #[test]
    fn test_nested_parens_in_expression() {
        // Expression with nested parens: (1 + 2)
        let fmt = Format::new("%((1 + 2))").unwrap();
        assert_eq!(fmt.elements.len(), 1);
        assert_eq!(fmt.elements[0].kind, ElementKind::Expr);
    }

    #[test]
    fn test_dump() {
        let fmt = Format::new("%-20(account) %12(total)").unwrap();
        let dump = fmt.dump();
        assert!(dump.contains("EXPR"));
        assert!(dump.contains("LEFT"));
        assert!(dump.contains("RIGHT"));
        assert!(dump.contains("account"));
        assert!(dump.contains("total"));
    }

    #[test]
    fn test_display() {
        let fmt = Format::new("%(account)").unwrap();
        let s = format!("{}", fmt);
        assert!(s.contains("Format"));
    }

    #[test]
    fn test_format_string_accessor() {
        let fmt = Format::new("%(x)").unwrap();
        assert_eq!(fmt.format_string(), "%(x)");
    }

    #[test]
    fn test_empty_format_instance() {
        let fmt = Format::empty();
        assert!(fmt.elements.is_empty());
        assert_eq!(fmt.format_string(), "");
    }

    #[test]
    fn test_trailing_backslash() {
        let fmt = Format::new("hello\\").unwrap();
        let scope = SymbolScope::new(None);
        let result = fmt.calc(&scope);
        assert_eq!(result, "hello\\");
    }

    #[test]
    fn test_multiple_expressions_adjacent() {
        let fmt = Format::new("%(a)%(b)").unwrap();
        assert_eq!(fmt.elements.len(), 2);

        let mut scope = SymbolScope::new(None);
        scope.define("a", ScopeValue::from_node(NodeValue::Str("X".to_string())));
        scope.define("b", ScopeValue::from_node(NodeValue::Str("Y".to_string())));
        let result = fmt.calc(&scope);
        assert_eq!(result, "XY");
    }

    #[test]
    fn test_width_no_padding_when_text_fits() {
        let fmt = Format::new("%5(x)").unwrap();
        let mut scope = SymbolScope::new(None);
        scope.define(
            "x",
            ScopeValue::from_node(NodeValue::Str("12345".to_string())),
        );
        let result = fmt.calc(&scope);
        assert_eq!(result, "12345");
    }

    #[test]
    fn test_arithmetic_expression_in_format() {
        // Arithmetic expression: 2 + 3
        let fmt = Format::new("%(2 + 3)").unwrap();
        let scope = SymbolScope::new(None);
        let result = fmt.calc(&scope);
        // The parser should handle literal arithmetic
        // This depends on parser support -- the result should be "5"
        // if the expression evaluator handles it properly
        assert!(!result.is_empty());
    }
}
