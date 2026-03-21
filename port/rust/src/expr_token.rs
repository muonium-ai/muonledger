//! Expression tokenizer for the Ledger expression language.
//!
//! This module provides the `ExprTokenizer` type, a Rust port of Ledger's
//! `token_t` from `token.h` / `token.cc`.  It breaks an expression string
//! like `amount > 100 and account =~ /Expenses/` into a sequence of typed
//! `Token` values that the expression parser can consume.
//!
//! The tokenizer handles:
//!   - Single- and multi-character operators (+, -, ==, !=, ->, &&, etc.)
//!   - Reserved words (and, or, not, div, if, else, true, false)
//!   - Bracketed date literals ([2024/01/01])
//!   - Quoted strings ('hello', "world")
//!   - Regular expression masks (/pattern/)
//!   - Numeric literals (42, 3.14)
//!   - Identifiers (amount, payee, account)
//!   - Grouping delimiters and punctuation

use std::fmt;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error raised when the tokenizer encounters invalid input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenizeError(pub String);

impl fmt::Display for TokenizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "TokenizeError: {}", self.0)
    }
}

impl std::error::Error for TokenizeError {}

// ---------------------------------------------------------------------------
// TokenKind
// ---------------------------------------------------------------------------

/// Enumeration of all token kinds in the expression grammar.
///
/// Mirrors `expr_t::token_t::kind_t` from the C++ Ledger source.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TokenKind {
    // Errors and special markers
    Error,
    Value,
    Ident,
    Mask,

    // Grouping delimiters
    Lparen,
    Rparen,
    Lbrace,
    Rbrace,

    // Comparison operators
    Equal,      // ==
    Nequal,     // !=
    Less,       // <
    LessEq,     // <=
    Greater,    // >
    GreaterEq,  // >=

    // Assignment and matching
    Assign,     // =
    Match,      // =~
    Nmatch,     // !~

    // Arithmetic operators
    Minus,      // -
    Plus,       // +
    Star,       // *
    Slash,      // /
    Arrow,      // ->
    KwDiv,      // div (integer division)

    // Logical operators
    Exclam,     // ! or 'not'
    KwAnd,      // & or && or 'and'
    KwOr,       // | or || or 'or'
    KwMod,      // %

    // Control-flow keywords
    KwIf,       // if
    KwElse,     // else

    // Ternary operators
    Query,      // ?
    Colon,      // :

    // Punctuation
    Dot,        // .
    Comma,      // ,
    Semi,       // ;

    // End markers
    TokEof,
    Unknown,
}

impl fmt::Display for TokenKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            TokenKind::Error => "ERROR",
            TokenKind::Value => "VALUE",
            TokenKind::Ident => "IDENT",
            TokenKind::Mask => "MASK",
            TokenKind::Lparen => "(",
            TokenKind::Rparen => ")",
            TokenKind::Lbrace => "{",
            TokenKind::Rbrace => "}",
            TokenKind::Equal => "==",
            TokenKind::Nequal => "!=",
            TokenKind::Less => "<",
            TokenKind::LessEq => "<=",
            TokenKind::Greater => ">",
            TokenKind::GreaterEq => ">=",
            TokenKind::Assign => "=",
            TokenKind::Match => "=~",
            TokenKind::Nmatch => "!~",
            TokenKind::Minus => "-",
            TokenKind::Plus => "+",
            TokenKind::Star => "*",
            TokenKind::Slash => "/",
            TokenKind::Arrow => "->",
            TokenKind::KwDiv => "div",
            TokenKind::Exclam => "!",
            TokenKind::KwAnd => "and",
            TokenKind::KwOr => "or",
            TokenKind::KwMod => "%",
            TokenKind::KwIf => "if",
            TokenKind::KwElse => "else",
            TokenKind::Query => "?",
            TokenKind::Colon => ":",
            TokenKind::Dot => ".",
            TokenKind::Comma => ",",
            TokenKind::Semi => ";",
            TokenKind::TokEof => "EOF",
            TokenKind::Unknown => "UNKNOWN",
        };
        write!(f, "{}", s)
    }
}

// ---------------------------------------------------------------------------
// TokenValue - polymorphic token payload
// ---------------------------------------------------------------------------

/// The parsed value carried by a token.
#[derive(Debug, Clone, PartialEq)]
pub enum TokenValue {
    /// No value.
    None,
    /// Integer literal.
    Integer(i64),
    /// Floating-point literal.
    Float(f64),
    /// String value (identifier name, string literal, regex pattern, date).
    Str(String),
    /// Boolean literal.
    Boolean(bool),
}

impl fmt::Display for TokenValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TokenValue::None => write!(f, "None"),
            TokenValue::Integer(n) => write!(f, "{}", n),
            TokenValue::Float(n) => write!(f, "{}", n),
            TokenValue::Str(s) => write!(f, "{}", s),
            TokenValue::Boolean(b) => write!(f, "{}", b),
        }
    }
}

// ---------------------------------------------------------------------------
// Token
// ---------------------------------------------------------------------------

/// A single lexical token produced by the expression tokenizer.
#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    /// The type of this token.
    pub kind: TokenKind,
    /// The parsed value (string for IDENT, numeric for VALUE, etc.).
    pub value: TokenValue,
    /// The character offset in the source string where this token starts.
    pub position: usize,
    /// The number of characters consumed from the input.
    pub length: usize,
    /// Short textual representation for diagnostics.
    pub symbol: String,
}

impl Token {
    /// Create a new token.
    pub fn new(kind: TokenKind, position: usize) -> Self {
        Token {
            kind,
            value: TokenValue::None,
            position,
            length: 0,
            symbol: String::new(),
        }
    }
}

impl fmt::Display for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.kind {
            TokenKind::Value | TokenKind::Ident | TokenKind::Mask => {
                write!(f, "Token({}, {:?})", self.kind, self.value)
            }
            _ => write!(f, "Token({})", self.kind),
        }
    }
}

// ---------------------------------------------------------------------------
// Reserved words
// ---------------------------------------------------------------------------

/// Look up a reserved word, returning (TokenKind, Option<TokenValue>).
fn reserved_word(word: &str) -> Option<(TokenKind, TokenValue)> {
    match word {
        "and" => Some((TokenKind::KwAnd, TokenValue::None)),
        "or" => Some((TokenKind::KwOr, TokenValue::None)),
        "not" => Some((TokenKind::Exclam, TokenValue::None)),
        "div" => Some((TokenKind::KwDiv, TokenValue::None)),
        "if" => Some((TokenKind::KwIf, TokenValue::None)),
        "else" => Some((TokenKind::KwElse, TokenValue::None)),
        "true" => Some((TokenKind::Value, TokenValue::Boolean(true))),
        "false" => Some((TokenKind::Value, TokenValue::Boolean(false))),
        "null" => Some((TokenKind::Value, TokenValue::None)),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// ExprTokenizer
// ---------------------------------------------------------------------------

/// Lexical tokenizer for Ledger expressions.
///
/// Takes a string expression and produces `Token` values.  The tokenizer
/// supports a context flag `op_context` that controls whether `/` is
/// interpreted as division (operator context) or as a regex delimiter
/// (terminal context).
pub struct ExprTokenizer {
    source: Vec<char>,
    pos: usize,
    op_context: bool,
}

impl ExprTokenizer {
    /// Create a new tokenizer for the given source string.
    pub fn new(source: &str) -> Self {
        ExprTokenizer {
            source: source.chars().collect(),
            pos: 0,
            op_context: false,
        }
    }

    fn peek(&self) -> Option<char> {
        self.source.get(self.pos).copied()
    }

    fn advance(&mut self) -> char {
        let ch = self.source[self.pos];
        self.pos += 1;
        ch
    }

    fn skip_whitespace(&mut self) {
        while self.pos < self.source.len() && self.source[self.pos].is_whitespace() {
            self.pos += 1;
        }
    }

    fn read_while<F: Fn(char) -> bool>(&mut self, pred: F) -> String {
        let start = self.pos;
        while self.pos < self.source.len() && pred(self.source[self.pos]) {
            self.pos += 1;
        }
        self.source[start..self.pos].iter().collect()
    }

    fn make_token(
        &self,
        kind: TokenKind,
        start: usize,
        value: TokenValue,
        symbol: &str,
    ) -> Token {
        Token {
            kind,
            value,
            position: start,
            length: self.pos - start,
            symbol: symbol.to_string(),
        }
    }

    fn read_string(
        &mut self,
        delim: char,
        start: usize,
    ) -> Result<Token, TokenizeError> {
        let mut buf = String::new();
        while self.pos < self.source.len() {
            let ch = self.advance();
            if ch == delim {
                return Ok(self.make_token(
                    TokenKind::Value,
                    start,
                    TokenValue::Str(buf),
                    &delim.to_string(),
                ));
            }
            if ch == '\\' && self.pos < self.source.len() {
                let next_ch = self.advance();
                buf.push(next_ch);
            } else {
                buf.push(ch);
            }
        }
        Err(TokenizeError(format!(
            "Unterminated string literal starting at position {}",
            start
        )))
    }

    fn read_date_literal(&mut self, start: usize) -> Result<Token, TokenizeError> {
        let mut buf = String::new();
        while self.pos < self.source.len() {
            let ch = self.advance();
            if ch == ']' {
                return Ok(self.make_token(
                    TokenKind::Value,
                    start,
                    TokenValue::Str(buf),
                    "[",
                ));
            }
            buf.push(ch);
        }
        Err(TokenizeError(format!(
            "Unterminated date literal starting at position {}",
            start
        )))
    }

    fn read_regex(&mut self, start: usize) -> Result<Token, TokenizeError> {
        let mut pat = String::new();
        while self.pos < self.source.len() {
            let ch = self.advance();
            if ch == '\\' {
                if self.pos < self.source.len() && self.source[self.pos] == '/' {
                    pat.push(self.advance());
                } else {
                    pat.push('\\');
                }
            } else if ch == '/' {
                return Ok(self.make_token(
                    TokenKind::Value,
                    start,
                    TokenValue::Str(pat),
                    "/",
                ));
            } else {
                pat.push(ch);
            }
        }
        Err(TokenizeError(format!(
            "Unterminated regex literal starting at position {}",
            start
        )))
    }

    fn read_identifier(&mut self, start: usize) -> Token {
        let word = self.read_while(|ch| ch.is_alphanumeric() || ch == '_');

        if let Some((kind, val)) = reserved_word(&word) {
            return self.make_token(kind, start, val, &word);
        }

        self.make_token(TokenKind::Ident, start, TokenValue::Str(word.clone()), &word)
    }

    fn read_number(&mut self, start: usize) -> Result<Token, TokenizeError> {
        let int_part = self.read_while(|ch| ch.is_ascii_digit());
        if self.peek() == Some('.') {
            // Check if next char after dot is a digit (decimal number).
            if self.pos + 1 < self.source.len() && self.source[self.pos + 1].is_ascii_digit() {
                self.advance(); // consume '.'
                let frac_part = self.read_while(|ch| ch.is_ascii_digit());
                let text = format!("{}.{}", int_part, frac_part);
                let val: f64 = text.parse().map_err(|_| {
                    TokenizeError(format!("Invalid numeric literal at position {}", start))
                })?;
                return Ok(self.make_token(TokenKind::Value, start, TokenValue::Float(val), ""));
            }
        }
        let val: i64 = int_part.parse().map_err(|_| {
            TokenizeError(format!("Invalid numeric literal at position {}", start))
        })?;
        Ok(self.make_token(TokenKind::Value, start, TokenValue::Integer(val), ""))
    }

    /// Read and return the next token from the source.
    ///
    /// After yielding a VALUE, IDENT, RPAREN, or RBRACE token the tokenizer
    /// enters operator context (`/` = division).  After other tokens it enters
    /// terminal context (`/` = regex).
    pub fn next_token(&mut self) -> Result<Token, TokenizeError> {
        self.skip_whitespace();

        if self.pos >= self.source.len() {
            return Ok(Token::new(TokenKind::TokEof, self.pos));
        }

        let start = self.pos;
        let ch = self.advance();

        let tok = match ch {
            '(' => self.make_token(TokenKind::Lparen, start, TokenValue::None, "("),
            ')' => self.make_token(TokenKind::Rparen, start, TokenValue::None, ")"),
            '{' => self.make_token(TokenKind::Lbrace, start, TokenValue::None, "{"),
            '}' => self.make_token(TokenKind::Rbrace, start, TokenValue::None, "}"),

            '&' => {
                if self.peek() == Some('&') {
                    self.advance();
                }
                self.make_token(TokenKind::KwAnd, start, TokenValue::None, "&")
            }
            '|' => {
                if self.peek() == Some('|') {
                    self.advance();
                }
                self.make_token(TokenKind::KwOr, start, TokenValue::None, "|")
            }

            '!' => {
                if self.peek() == Some('=') {
                    self.advance();
                    self.make_token(TokenKind::Nequal, start, TokenValue::None, "!=")
                } else if self.peek() == Some('~') {
                    self.advance();
                    self.make_token(TokenKind::Nmatch, start, TokenValue::None, "!~")
                } else {
                    self.make_token(TokenKind::Exclam, start, TokenValue::None, "!")
                }
            }

            '=' => {
                if self.peek() == Some('~') {
                    self.advance();
                    self.make_token(TokenKind::Match, start, TokenValue::None, "=~")
                } else if self.peek() == Some('=') {
                    self.advance();
                    self.make_token(TokenKind::Equal, start, TokenValue::None, "==")
                } else {
                    self.make_token(TokenKind::Assign, start, TokenValue::None, "=")
                }
            }

            '<' => {
                if self.peek() == Some('=') {
                    self.advance();
                    self.make_token(TokenKind::LessEq, start, TokenValue::None, "<=")
                } else {
                    self.make_token(TokenKind::Less, start, TokenValue::None, "<")
                }
            }

            '>' => {
                if self.peek() == Some('=') {
                    self.advance();
                    self.make_token(TokenKind::GreaterEq, start, TokenValue::None, ">=")
                } else {
                    self.make_token(TokenKind::Greater, start, TokenValue::None, ">")
                }
            }

            '-' => {
                if self.peek() == Some('>') {
                    self.advance();
                    self.make_token(TokenKind::Arrow, start, TokenValue::None, "->")
                } else {
                    self.make_token(TokenKind::Minus, start, TokenValue::None, "-")
                }
            }

            '+' => self.make_token(TokenKind::Plus, start, TokenValue::None, "+"),
            '*' => self.make_token(TokenKind::Star, start, TokenValue::None, "*"),
            '%' => self.make_token(TokenKind::KwMod, start, TokenValue::None, "%"),
            '?' => self.make_token(TokenKind::Query, start, TokenValue::None, "?"),
            ':' => self.make_token(TokenKind::Colon, start, TokenValue::None, ":"),
            '.' => self.make_token(TokenKind::Dot, start, TokenValue::None, "."),
            ',' => self.make_token(TokenKind::Comma, start, TokenValue::None, ","),
            ';' => self.make_token(TokenKind::Semi, start, TokenValue::None, ";"),

            '/' => {
                if self.op_context {
                    self.make_token(TokenKind::Slash, start, TokenValue::None, "/")
                } else {
                    self.read_regex(start)?
                }
            }

            '[' => self.read_date_literal(start)?,

            '\'' | '"' => self.read_string(ch, start)?,

            c if c.is_ascii_digit() => {
                self.pos = start; // reset so read_number can match from start
                self.read_number(start)?
            }

            c if c.is_alphabetic() || c == '_' => {
                self.pos = start; // reset so read_identifier can match from start
                self.read_identifier(start)
            }

            _ => {
                return Err(TokenizeError(format!(
                    "Unexpected character {:?} at position {}",
                    ch, start
                )));
            }
        };

        // Update operator context: after a value, identifier, or closing
        // delimiter we expect an operator next (so / means division).
        self.op_context = matches!(
            tok.kind,
            TokenKind::Value | TokenKind::Ident | TokenKind::Rparen | TokenKind::Rbrace
        );

        Ok(tok)
    }

    /// Tokenize the entire source and return a list of tokens.
    ///
    /// The returned list does *not* include the final `TokEof` token.
    pub fn tokenize(&mut self) -> Result<Vec<Token>, TokenizeError> {
        let mut tokens = Vec::new();
        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::TokEof {
                break;
            }
            tokens.push(tok);
        }
        Ok(tokens)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_integer() {
        let mut tz = ExprTokenizer::new("42");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::Integer(42));
    }

    #[test]
    fn test_float_literal() {
        let mut tz = ExprTokenizer::new("3.14");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::Float(3.14));
    }

    #[test]
    fn test_identifier() {
        let mut tz = ExprTokenizer::new("amount");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Ident);
        assert_eq!(tokens[0].value, TokenValue::Str("amount".to_string()));
    }

    #[test]
    fn test_reserved_words() {
        let mut tz = ExprTokenizer::new("true false and or not if else div");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 8);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::Boolean(true));
        assert_eq!(tokens[1].kind, TokenKind::Value);
        assert_eq!(tokens[1].value, TokenValue::Boolean(false));
        assert_eq!(tokens[2].kind, TokenKind::KwAnd);
        assert_eq!(tokens[3].kind, TokenKind::KwOr);
        assert_eq!(tokens[4].kind, TokenKind::Exclam);
        assert_eq!(tokens[5].kind, TokenKind::KwIf);
        assert_eq!(tokens[6].kind, TokenKind::KwElse);
        assert_eq!(tokens[7].kind, TokenKind::KwDiv);
    }

    #[test]
    fn test_comparison_operators() {
        let mut tz = ExprTokenizer::new("== != < <= > >=");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 6);
        assert_eq!(tokens[0].kind, TokenKind::Equal);
        assert_eq!(tokens[1].kind, TokenKind::Nequal);
        assert_eq!(tokens[2].kind, TokenKind::Less);
        assert_eq!(tokens[3].kind, TokenKind::LessEq);
        assert_eq!(tokens[4].kind, TokenKind::Greater);
        assert_eq!(tokens[5].kind, TokenKind::GreaterEq);
    }

    #[test]
    fn test_logical_operators() {
        let mut tz = ExprTokenizer::new("& && | || !");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 5);
        assert_eq!(tokens[0].kind, TokenKind::KwAnd);
        assert_eq!(tokens[1].kind, TokenKind::KwAnd);
        assert_eq!(tokens[2].kind, TokenKind::KwOr);
        assert_eq!(tokens[3].kind, TokenKind::KwOr);
        assert_eq!(tokens[4].kind, TokenKind::Exclam);
    }

    #[test]
    fn test_arithmetic_and_punctuation() {
        let mut tz = ExprTokenizer::new("+ - * % ? : . , ;");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 9);
        assert_eq!(tokens[0].kind, TokenKind::Plus);
        assert_eq!(tokens[1].kind, TokenKind::Minus);
        assert_eq!(tokens[2].kind, TokenKind::Star);
        assert_eq!(tokens[3].kind, TokenKind::KwMod);
        assert_eq!(tokens[4].kind, TokenKind::Query);
        assert_eq!(tokens[5].kind, TokenKind::Colon);
        assert_eq!(tokens[6].kind, TokenKind::Dot);
        assert_eq!(tokens[7].kind, TokenKind::Comma);
        assert_eq!(tokens[8].kind, TokenKind::Semi);
    }

    #[test]
    fn test_arrow_and_match_operators() {
        let mut tz = ExprTokenizer::new("-> =~ !~ =");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 4);
        assert_eq!(tokens[0].kind, TokenKind::Arrow);
        assert_eq!(tokens[1].kind, TokenKind::Match);
        assert_eq!(tokens[2].kind, TokenKind::Nmatch);
        assert_eq!(tokens[3].kind, TokenKind::Assign);
    }

    #[test]
    fn test_grouping() {
        let mut tz = ExprTokenizer::new("( ) { }");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 4);
        assert_eq!(tokens[0].kind, TokenKind::Lparen);
        assert_eq!(tokens[1].kind, TokenKind::Rparen);
        assert_eq!(tokens[2].kind, TokenKind::Lbrace);
        assert_eq!(tokens[3].kind, TokenKind::Rbrace);
    }

    #[test]
    fn test_string_literal_double_quotes() {
        let mut tz = ExprTokenizer::new(r#""hello world""#);
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::Str("hello world".to_string()));
    }

    #[test]
    fn test_string_literal_single_quotes() {
        let mut tz = ExprTokenizer::new("'hello'");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::Str("hello".to_string()));
    }

    #[test]
    fn test_date_literal() {
        let mut tz = ExprTokenizer::new("[2024/01/15]");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(
            tokens[0].value,
            TokenValue::Str("2024/01/15".to_string())
        );
    }

    #[test]
    fn test_regex_literal() {
        let mut tz = ExprTokenizer::new("/Expenses/");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(
            tokens[0].value,
            TokenValue::Str("Expenses".to_string())
        );
    }

    #[test]
    fn test_slash_as_division_in_op_context() {
        // After an identifier, / should be division
        let mut tz = ExprTokenizer::new("a / b");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 3);
        assert_eq!(tokens[0].kind, TokenKind::Ident);
        assert_eq!(tokens[1].kind, TokenKind::Slash);
        assert_eq!(tokens[2].kind, TokenKind::Ident);
    }

    #[test]
    fn test_complex_expression() {
        let mut tz = ExprTokenizer::new("amount > 100 and account =~ /Expenses/");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 7);
        assert_eq!(tokens[0].kind, TokenKind::Ident);
        assert_eq!(tokens[1].kind, TokenKind::Greater);
        assert_eq!(tokens[2].kind, TokenKind::Value);
        assert_eq!(tokens[2].value, TokenValue::Integer(100));
        assert_eq!(tokens[3].kind, TokenKind::KwAnd);
        assert_eq!(tokens[4].kind, TokenKind::Ident);
        assert_eq!(tokens[5].kind, TokenKind::Match);
        assert_eq!(tokens[6].kind, TokenKind::Value);
    }

    #[test]
    fn test_empty_expression() {
        let mut tz = ExprTokenizer::new("");
        let tokens = tz.tokenize().unwrap();
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_whitespace_only() {
        let mut tz = ExprTokenizer::new("   \t\n  ");
        let tokens = tz.tokenize().unwrap();
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_unterminated_string_error() {
        let mut tz = ExprTokenizer::new("\"hello");
        let result = tz.tokenize();
        assert!(result.is_err());
    }

    #[test]
    fn test_unexpected_character_error() {
        let mut tz = ExprTokenizer::new("~");
        let result = tz.tokenize();
        assert!(result.is_err());
    }

    #[test]
    fn test_null_keyword() {
        let mut tz = ExprTokenizer::new("null");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].kind, TokenKind::Value);
        assert_eq!(tokens[0].value, TokenValue::None);
    }

    #[test]
    fn test_escape_in_string() {
        let mut tz = ExprTokenizer::new(r#""he\"llo""#);
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].value, TokenValue::Str("he\"llo".to_string()));
    }

    #[test]
    fn test_positions_tracked() {
        let mut tz = ExprTokenizer::new("a + b");
        let tokens = tz.tokenize().unwrap();
        assert_eq!(tokens[0].position, 0);
        assert_eq!(tokens[1].position, 2);
        assert_eq!(tokens[2].position, 4);
    }
}
