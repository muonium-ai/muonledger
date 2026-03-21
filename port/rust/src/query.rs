//! Query language parser for user-friendly command-line queries.
//!
//! This module provides `QueryParser` and `parse_query()`, a Rust port of
//! Ledger's `query_t` from `query.h` / `query.cc`.  It translates
//! user-facing shorthand like:
//!
//! ```text
//!   food and @grocery
//! ```
//!
//! into expression AST nodes equivalent to:
//!
//! ```text
//!   (account =~ /food/) and (payee =~ /grocery/)
//! ```
//!
//! The query language supports:
//!   - Bare terms match account names: `food` becomes `account =~ /food/`
//!   - `@term` matches payees: `@grocery` becomes `payee =~ /grocery/`
//!   - `#term` matches codes: `#1234` becomes `code =~ /1234/`
//!   - `=term` matches notes: `=vacation` becomes `note =~ /vacation/`
//!   - `%term` matches tags: `%project` becomes `has_tag(/project/)`
//!   - `/regex/` matches account names with a regex pattern
//!   - Boolean connectives: `and`/`&`, `or`/`|`, `not`/`!`
//!   - Parenthesized grouping: `(food or drinks) and @store`
//!   - Implicit AND between consecutive terms: `Expenses Food` is
//!     `(account =~ /Expenses/) and (account =~ /Food/)`
//!
//! Operator precedence (lowest to highest): `or`, `and`/implicit, `not`, atoms.

use std::fmt;

use crate::expr_ast::{ExprNode, NodeValue, OpKind};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error raised when the query parser encounters invalid input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueryParseError(pub String);

impl fmt::Display for QueryParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "QueryParseError: {}", self.0)
    }
}

impl std::error::Error for QueryParseError {}

// ---------------------------------------------------------------------------
// Query token types
// ---------------------------------------------------------------------------

/// Token kinds specific to the query lexer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum QTokenKind {
    Lparen,
    Rparen,
    TokNot,
    TokAnd,
    TokOr,
    TokCode,
    TokPayee,
    TokNote,
    TokAccount,
    TokMeta,
    Term,
    EndReached,
}

/// A single token produced by the query lexer.
#[derive(Debug, Clone)]
struct QToken {
    kind: QTokenKind,
    value: Option<String>,
}

impl QToken {
    fn new(kind: QTokenKind) -> Self {
        QToken { kind, value: None }
    }

    fn with_value(kind: QTokenKind, value: String) -> Self {
        QToken {
            kind,
            value: Some(value),
        }
    }

    fn is_end(&self) -> bool {
        self.kind == QTokenKind::EndReached
    }
}

// ---------------------------------------------------------------------------
// Keywords
// ---------------------------------------------------------------------------

fn keyword_lookup(word: &str) -> Option<QTokenKind> {
    match word.to_lowercase().as_str() {
        "and" => Some(QTokenKind::TokAnd),
        "or" => Some(QTokenKind::TokOr),
        "not" => Some(QTokenKind::TokNot),
        "code" => Some(QTokenKind::TokCode),
        "desc" | "payee" => Some(QTokenKind::TokPayee),
        "note" => Some(QTokenKind::TokNote),
        "account" => Some(QTokenKind::TokAccount),
        "tag" | "meta" | "data" => Some(QTokenKind::TokMeta),
        _ => None,
    }
}

/// Characters that act as operator boundaries when scanning bare-word identifiers.
fn is_boundary_char(ch: char) -> bool {
    matches!(ch, '(' | ')' | '&' | '|' | '!' | '@' | '#' | '%' | '=')
}

// ---------------------------------------------------------------------------
// Query Lexer
// ---------------------------------------------------------------------------

/// Tokenizes a query string into `QToken` values.
struct QueryLexer {
    source: Vec<char>,
    pos: usize,
    cache: Option<QToken>,
}

impl QueryLexer {
    fn new(source: &str) -> Self {
        QueryLexer {
            source: source.chars().collect(),
            pos: 0,
            cache: None,
        }
    }

    fn push_token(&mut self, tok: QToken) {
        assert!(
            self.cache.is_none(),
            "Cannot push more than one token"
        );
        self.cache = Some(tok);
    }

    fn peek_token(&mut self) -> QToken {
        if self.cache.is_none() {
            let tok = self.next_token();
            self.cache = Some(tok);
        }
        self.cache.clone().unwrap()
    }

    fn next_token(&mut self) -> QToken {
        if let Some(tok) = self.cache.take() {
            return tok;
        }

        self.skip_whitespace();

        if self.pos >= self.source.len() {
            return QToken::new(QTokenKind::EndReached);
        }

        let ch = self.source[self.pos];

        // Quoted / delimited patterns
        if ch == '\'' || ch == '"' || ch == '/' {
            return self.scan_quoted_pattern();
        }

        // Single-character operators
        match ch {
            '(' => {
                self.pos += 1;
                return QToken::new(QTokenKind::Lparen);
            }
            ')' => {
                self.pos += 1;
                return QToken::new(QTokenKind::Rparen);
            }
            '&' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokAnd);
            }
            '|' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokOr);
            }
            '!' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokNot);
            }
            '@' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokPayee);
            }
            '#' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokCode);
            }
            '%' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokMeta);
            }
            '=' => {
                self.pos += 1;
                return QToken::new(QTokenKind::TokNote);
            }
            _ => {}
        }

        // Bare-word identifier
        self.scan_identifier()
    }

    fn skip_whitespace(&mut self) {
        while self.pos < self.source.len() && self.source[self.pos].is_whitespace() {
            self.pos += 1;
        }
    }

    fn scan_quoted_pattern(&mut self) -> QToken {
        let closing = self.source[self.pos];
        let is_regex = closing == '/';
        self.pos += 1; // skip opening delimiter
        let mut buf = String::new();

        while self.pos < self.source.len() {
            let ch = self.source[self.pos];
            self.pos += 1;
            if ch == '\\' && self.pos < self.source.len() {
                let next_ch = self.source[self.pos];
                self.pos += 1;
                if is_regex && next_ch != closing {
                    buf.push('\\');
                }
                buf.push(next_ch);
            } else if ch == closing {
                if buf.is_empty() {
                    // Return empty pattern as a term with empty string
                    // The Python version raises an error here, but we'll be lenient
                    return QToken::with_value(QTokenKind::Term, String::new());
                }
                return QToken::with_value(QTokenKind::Term, buf);
            } else {
                buf.push(ch);
            }
        }

        // Unterminated pattern -- return what we have as a term
        QToken::with_value(QTokenKind::Term, buf)
    }

    fn scan_identifier(&mut self) -> QToken {
        let start = self.pos;
        while self.pos < self.source.len() {
            let ch = self.source[self.pos];
            if ch.is_whitespace() || is_boundary_char(ch) {
                break;
            }
            self.pos += 1;
        }

        let ident: String = self.source[start..self.pos].iter().collect();
        let ident = ident.trim().to_string();

        if ident.is_empty() {
            return QToken::new(QTokenKind::EndReached);
        }

        // Match against keywords
        if let Some(kind) = keyword_lookup(&ident) {
            return QToken::new(kind);
        }

        QToken::with_value(QTokenKind::Term, ident)
    }
}

// ---------------------------------------------------------------------------
// Query Parser
// ---------------------------------------------------------------------------

/// Recursive-descent parser that builds ExprNode trees from query strings.
///
/// The parser implements the standard precedence hierarchy:
///   - `parse_or_expr`: `or` / `|` (lowest precedence)
///   - `parse_and_expr`: `and` / `&`, plus implicit AND between adjacent terms
///   - `parse_unary_expr`: `not` / `!`
///   - `parse_query_term`: atoms (patterns, field prefixes, parenthesized groups)
pub struct QueryParser {
    lexer: QueryLexer,
    parse_depth: usize,
}

/// Maximum nesting depth for query expressions.
const MAX_PARSE_DEPTH: usize = 256;

impl QueryParser {
    /// Create a new parser for the given query string.
    pub fn new(query_string: &str) -> Self {
        QueryParser {
            lexer: QueryLexer::new(query_string),
            parse_depth: 0,
        }
    }

    /// Parse the query and return the root ExprNode, or None if empty.
    pub fn parse(&mut self) -> Result<Option<ExprNode>, QueryParseError> {
        self.parse_or_expr(QTokenKind::TokAccount)
    }

    fn parse_query_term(
        &mut self,
        tok_context: QTokenKind,
    ) -> Result<Option<ExprNode>, QueryParseError> {
        let tok = self.lexer.next_token();

        if tok.is_end() {
            self.lexer.push_token(tok);
            return Ok(None);
        }

        // Field context switches
        if matches!(
            tok.kind,
            QTokenKind::TokCode
                | QTokenKind::TokPayee
                | QTokenKind::TokNote
                | QTokenKind::TokAccount
                | QTokenKind::TokMeta
        ) {
            let node = self.parse_query_term(tok.kind)?;
            if node.is_none() {
                return Err(QueryParseError(
                    "Field prefix not followed by a search term".to_string(),
                ));
            }
            return Ok(node);
        }

        // TERM: build the appropriate match node
        if tok.kind == QTokenKind::Term {
            let pattern = tok.value.unwrap_or_default();
            if tok_context == QTokenKind::TokMeta {
                return Ok(Some(Self::make_meta_node(&pattern)));
            }
            return Ok(Some(Self::make_match_node(tok_context, &pattern)));
        }

        // Parenthesized sub-expression
        if tok.kind == QTokenKind::Lparen {
            self.parse_depth += 1;
            if self.parse_depth > MAX_PARSE_DEPTH {
                return Err(QueryParseError(
                    "Query expression nested too deeply".to_string(),
                ));
            }
            let node = self.parse_or_expr(tok_context)?;
            self.parse_depth -= 1;
            let closing = self.lexer.next_token();
            if closing.kind != QTokenKind::Rparen {
                return Err(QueryParseError("Missing ')'".to_string()));
            }
            return Ok(node);
        }

        // Anything else: push back and return None
        self.lexer.push_token(tok);
        Ok(None)
    }

    fn parse_unary_expr(
        &mut self,
        tok_context: QTokenKind,
    ) -> Result<Option<ExprNode>, QueryParseError> {
        let tok = self.lexer.next_token();
        if tok.kind == QTokenKind::TokNot {
            let term = self.parse_query_term(tok_context)?;
            match term {
                Some(t) => {
                    let node = ExprNode::unary(OpKind::ONot, t);
                    Ok(Some(node))
                }
                None => Err(QueryParseError(
                    "'not' operator not followed by argument".to_string(),
                )),
            }
        } else {
            self.lexer.push_token(tok);
            self.parse_query_term(tok_context)
        }
    }

    fn parse_and_expr(
        &mut self,
        tok_context: QTokenKind,
    ) -> Result<Option<ExprNode>, QueryParseError> {
        let mut node = match self.parse_unary_expr(tok_context)? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.lexer.next_token();
            if tok.kind == QTokenKind::TokAnd {
                // Explicit AND
                let right = self.parse_unary_expr(tok_context)?;
                match right {
                    Some(r) => {
                        node = ExprNode::binary(OpKind::OAnd, node, r);
                    }
                    None => {
                        return Err(QueryParseError(
                            "'and' operator not followed by argument".to_string(),
                        ));
                    }
                }
            } else {
                self.lexer.push_token(tok);
                // Implicit AND: if the next token can start a unary_expr,
                // treat it as an implicit AND.
                let peek = self.lexer.peek_token();
                if matches!(
                    peek.kind,
                    QTokenKind::Term
                        | QTokenKind::TokNot
                        | QTokenKind::Lparen
                        | QTokenKind::TokCode
                        | QTokenKind::TokPayee
                        | QTokenKind::TokNote
                        | QTokenKind::TokAccount
                        | QTokenKind::TokMeta
                ) {
                    let right = self.parse_unary_expr(tok_context)?;
                    if let Some(r) = right {
                        node = ExprNode::binary(OpKind::OAnd, node, r);
                        continue;
                    }
                }
                break;
            }
        }
        Ok(Some(node))
    }

    fn parse_or_expr(
        &mut self,
        tok_context: QTokenKind,
    ) -> Result<Option<ExprNode>, QueryParseError> {
        let mut node = match self.parse_and_expr(tok_context)? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.lexer.next_token();
            if tok.kind == QTokenKind::TokOr {
                let right = self.parse_and_expr(tok_context)?;
                match right {
                    Some(r) => {
                        node = ExprNode::binary(OpKind::OOr, node, r);
                    }
                    None => {
                        return Err(QueryParseError(
                            "'or' operator not followed by argument".to_string(),
                        ));
                    }
                }
            } else {
                self.lexer.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Node construction helpers
    // ------------------------------------------------------------------

    /// Build an O_MATCH node: `field =~ /pattern/`.
    ///
    /// Maps tok_context to the appropriate field identifier:
    ///   - TokAccount -> "account"
    ///   - TokPayee   -> "payee"
    ///   - TokCode    -> "code"
    ///   - TokNote    -> "note"
    fn make_match_node(tok_context: QTokenKind, pattern: &str) -> ExprNode {
        let field_name = match tok_context {
            QTokenKind::TokAccount => "account",
            QTokenKind::TokPayee => "payee",
            QTokenKind::TokCode => "code",
            QTokenKind::TokNote => "note",
            _ => "account",
        };

        let ident = ExprNode::ident_node(field_name);
        let mask = ExprNode::value_node(NodeValue::Str(pattern.to_string()));
        ExprNode::binary(OpKind::OMatch, ident, mask)
    }

    /// Build a function-call node: `has_tag(/pattern/)`.
    ///
    /// The resulting AST is:
    ///   O_CALL
    ///     left: IDENT("has_tag")
    ///     right: VALUE(pattern)
    fn make_meta_node(tag_pattern: &str) -> ExprNode {
        let ident = ExprNode::ident_node("has_tag");
        let arg = ExprNode::value_node(NodeValue::Str(tag_pattern.to_string()));
        ExprNode::binary(OpKind::OCall, ident, arg)
    }
}

// ---------------------------------------------------------------------------
// Convenience function
// ---------------------------------------------------------------------------

/// Parse a user-facing query string into an ExprNode tree.
///
/// Returns the root of the expression tree, or None if the query is empty.
pub fn parse_query(query_string: &str) -> Result<Option<ExprNode>, QueryParseError> {
    let query_string = query_string.trim();
    if query_string.is_empty() {
        return Ok(None);
    }
    QueryParser::new(query_string).parse()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // Helper to extract field name from match node's left child (IDENT)
    fn match_field(node: &ExprNode) -> &str {
        assert_eq!(node.kind, OpKind::OMatch);
        if let Some(ref left) = node.left {
            if let NodeValue::Str(ref s) = left.value {
                return s;
            }
        }
        panic!("Expected IDENT left child with Str value");
    }

    // Helper to extract pattern from match node's right child (VALUE)
    fn match_pattern(node: &ExprNode) -> &str {
        assert_eq!(node.kind, OpKind::OMatch);
        if let Some(ref right) = node.right {
            if let NodeValue::Str(ref s) = right.value {
                return s;
            }
        }
        panic!("Expected VALUE right child with Str value");
    }

    #[test]
    fn test_empty_query() {
        let result = parse_query("").unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_whitespace_query() {
        let result = parse_query("   ").unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_bare_term_matches_account() {
        let node = parse_query("Expenses").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "account");
        assert_eq!(match_pattern(&node), "Expenses");
    }

    #[test]
    fn test_payee_shorthand() {
        let node = parse_query("@Grocery").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "payee");
        assert_eq!(match_pattern(&node), "Grocery");
    }

    #[test]
    fn test_code_shorthand() {
        let node = parse_query("#1234").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "code");
        assert_eq!(match_pattern(&node), "1234");
    }

    #[test]
    fn test_note_shorthand() {
        let node = parse_query("=vacation").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "note");
        assert_eq!(match_pattern(&node), "vacation");
    }

    #[test]
    fn test_meta_shorthand() {
        let node = parse_query("%project").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OCall);
        // Left should be IDENT("has_tag")
        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::Ident);
        assert_eq!(left.value, NodeValue::Str("has_tag".to_string()));
        // Right should be VALUE("project")
        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::Value);
        assert_eq!(right.value, NodeValue::Str("project".to_string()));
    }

    #[test]
    fn test_explicit_and() {
        let node = parse_query("Expenses and Food").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);

        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::OMatch);
        assert_eq!(match_field(left), "account");
        assert_eq!(match_pattern(left), "Expenses");

        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::OMatch);
        assert_eq!(match_field(right), "account");
        assert_eq!(match_pattern(right), "Food");
    }

    #[test]
    fn test_ampersand_and() {
        let node = parse_query("Expenses & Food").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);
    }

    #[test]
    fn test_explicit_or() {
        let node = parse_query("Expenses or Income").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OOr);

        let left = node.left.as_ref().unwrap();
        assert_eq!(match_field(left), "account");
        assert_eq!(match_pattern(left), "Expenses");

        let right = node.right.as_ref().unwrap();
        assert_eq!(match_field(right), "account");
        assert_eq!(match_pattern(right), "Income");
    }

    #[test]
    fn test_pipe_or() {
        let node = parse_query("Expenses | Income").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OOr);
    }

    #[test]
    fn test_not_operator() {
        let node = parse_query("not Expenses").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::ONot);
        let child = node.left.as_ref().unwrap();
        assert_eq!(child.kind, OpKind::OMatch);
        assert_eq!(match_field(child), "account");
        assert_eq!(match_pattern(child), "Expenses");
    }

    #[test]
    fn test_exclaim_not() {
        let node = parse_query("!Expenses").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::ONot);
    }

    #[test]
    fn test_implicit_and() {
        // Two consecutive terms: implicit AND
        let node = parse_query("Expenses Food").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);

        let left = node.left.as_ref().unwrap();
        assert_eq!(match_pattern(left), "Expenses");

        let right = node.right.as_ref().unwrap();
        assert_eq!(match_pattern(right), "Food");
    }

    #[test]
    fn test_parenthesized_grouping() {
        let node = parse_query("(Expenses or Income) and @store")
            .unwrap()
            .unwrap();
        assert_eq!(node.kind, OpKind::OAnd);

        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::OOr);

        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::OMatch);
        assert_eq!(match_field(right), "payee");
        assert_eq!(match_pattern(right), "store");
    }

    #[test]
    fn test_mixed_field_prefixes() {
        let node = parse_query("@Grocery and #1234").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);

        let left = node.left.as_ref().unwrap();
        assert_eq!(match_field(left), "payee");

        let right = node.right.as_ref().unwrap();
        assert_eq!(match_field(right), "code");
    }

    #[test]
    fn test_quoted_pattern_single() {
        let node = parse_query("'Expenses:Food'").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_pattern(&node), "Expenses:Food");
    }

    #[test]
    fn test_quoted_pattern_double() {
        let node = parse_query("\"Expenses:Food\"").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_pattern(&node), "Expenses:Food");
    }

    #[test]
    fn test_regex_pattern() {
        let node = parse_query("/Exp.*/").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_pattern(&node), "Exp.*");
    }

    #[test]
    fn test_keyword_payee() {
        let node = parse_query("payee Grocery").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "payee");
        assert_eq!(match_pattern(&node), "Grocery");
    }

    #[test]
    fn test_keyword_desc() {
        let node = parse_query("desc Grocery").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "payee");
    }

    #[test]
    fn test_keyword_code() {
        let node = parse_query("code 5678").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "code");
        assert_eq!(match_pattern(&node), "5678");
    }

    #[test]
    fn test_keyword_note() {
        let node = parse_query("note trip").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "note");
    }

    #[test]
    fn test_keyword_tag() {
        let node = parse_query("tag project").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OCall);
    }

    #[test]
    fn test_keyword_meta() {
        let node = parse_query("meta status").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OCall);
    }

    #[test]
    fn test_keyword_account() {
        let node = parse_query("account Expenses").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "account");
        assert_eq!(match_pattern(&node), "Expenses");
    }

    #[test]
    fn test_precedence_and_binds_tighter_than_or() {
        // "a or b and c" should parse as "a or (b and c)"
        let node = parse_query("A or B and C").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OOr);
        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::OAnd);
    }

    #[test]
    fn test_precedence_not_binds_tightest() {
        // "not A and B" should parse as "(not A) and B"
        let node = parse_query("not A and B").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);
        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::ONot);
    }

    #[test]
    fn test_complex_query() {
        let node = parse_query("(Expenses or Income) and @Grocery and not #1234")
            .unwrap()
            .unwrap();
        // Top level should be AND chain
        assert_eq!(node.kind, OpKind::OAnd);
    }

    #[test]
    fn test_field_prefix_not_followed_by_term() {
        let result = parse_query("@");
        assert!(result.is_err());
    }

    #[test]
    fn test_not_not_followed_by_term() {
        let result = parse_query("not");
        assert!(result.is_err());
    }

    #[test]
    fn test_and_not_followed_by_term() {
        let result = parse_query("Expenses and");
        assert!(result.is_err());
    }

    #[test]
    fn test_or_not_followed_by_term() {
        let result = parse_query("Expenses or");
        assert!(result.is_err());
    }

    #[test]
    fn test_missing_closing_paren() {
        let result = parse_query("(Expenses");
        assert!(result.is_err());
    }

    #[test]
    fn test_multiple_implicit_and() {
        // Three consecutive terms
        let node = parse_query("Expenses Food Grocery").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OAnd);
        // Should be ((Expenses AND Food) AND Grocery)
        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::OAnd);
    }

    #[test]
    fn test_payee_with_quoted_term() {
        let node = parse_query("@'Whole Foods'").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
        assert_eq!(match_field(&node), "payee");
        assert_eq!(match_pattern(&node), "Whole Foods");
    }

    #[test]
    fn test_node_structure_bare_term() {
        let node = parse_query("food").unwrap().unwrap();
        assert_eq!(node.kind, OpKind::OMatch);

        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::Ident);
        assert_eq!(left.value, NodeValue::Str("account".to_string()));

        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::Value);
        assert_eq!(right.value, NodeValue::Str("food".to_string()));
    }

    #[test]
    fn test_escaped_char_in_regex() {
        let node = parse_query("/Exp\\.*/").unwrap().unwrap();
        assert_eq!(match_pattern(&node), "Exp\\.*");
    }
}
