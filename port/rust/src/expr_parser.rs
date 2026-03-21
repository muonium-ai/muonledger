//! Pratt / precedence-climbing parser for the Ledger expression language.
//!
//! This module provides the `ExprParser` type, a Rust port of Ledger's
//! `parser_t` from `parser.h` / `parser.cc`.  It takes a sequence of tokens
//! produced by `ExprTokenizer` and builds an `ExprNode` AST.
//!
//! The parser uses recursive descent with operator-precedence climbing.
//! Each `parse_*` method handles one precedence level and delegates to the
//! next-tighter level for its operands.  The precedence levels, from lowest
//! to highest, are:
//!
//!   1. value_expr   -- semicolons (`;`) / O_SEQ
//!   2. assign_expr  -- assignment (`=`) / O_DEFINE
//!   3. lambda_expr  -- arrow (`->`) / O_LAMBDA
//!   4. comma_expr   -- comma (`,`) / O_CONS
//!   5. query_expr   -- ternary (`? :`) and postfix `if`/`else` / O_QUERY
//!   6. or_expr      -- logical OR (`or`, `|`, `||`) / O_OR
//!   7. and_expr     -- logical AND (`and`, `&`, `&&`) / O_AND
//!   8. logic_expr   -- comparisons (`==`, `!=`, `<`, `<=`, etc.)
//!   9. add_expr     -- addition/subtraction (`+`, `-`) / O_ADD, O_SUB
//!  10. mul_expr     -- multiplication/division (`*`, `/`) / O_MUL, O_DIV
//!  11. unary_expr   -- unary prefix (`!`, `-`, `not`) / O_NOT, O_NEG
//!  12. dot_expr     -- member access (`.`) / O_LOOKUP
//!  13. call_expr    -- function call (`func(...)`) / O_CALL
//!  14. value_term   -- literals, identifiers, parenthesized sub-expressions

use std::fmt;

use crate::expr_ast::{ExprNode, NodeValue, OpKind};
use crate::expr_token::{ExprTokenizer, Token, TokenKind, TokenValue, TokenizeError};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Error raised when the parser encounters invalid syntax.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseError(pub String);

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "ParseError: {}", self.0)
    }
}

impl std::error::Error for ParseError {}

impl From<TokenizeError> for ParseError {
    fn from(e: TokenizeError) -> Self {
        ParseError(e.0)
    }
}

// ---------------------------------------------------------------------------
// ExprParser
// ---------------------------------------------------------------------------

/// Recursive-descent, precedence-climbing parser for Ledger expressions.
///
/// The parser consumes tokens from an `ExprTokenizer` and builds an
/// `ExprNode` AST.  It supports one level of token look-ahead via an
/// internal push-back mechanism.
pub struct ExprParser {
    tokenizer: ExprTokenizer,
    lookahead: Option<Token>,
}

impl ExprParser {
    /// Create a new parser for the given expression string.
    pub fn new(source: &str) -> Self {
        ExprParser {
            tokenizer: ExprTokenizer::new(source),
            lookahead: None,
        }
    }

    fn next_token(&mut self) -> Result<Token, ParseError> {
        if let Some(tok) = self.lookahead.take() {
            Ok(tok)
        } else {
            Ok(self.tokenizer.next_token()?)
        }
    }

    fn push_token(&mut self, tok: Token) {
        debug_assert!(
            self.lookahead.is_none(),
            "Cannot push more than one token"
        );
        self.lookahead = Some(tok);
    }

    fn peek_token(&mut self) -> Result<TokenKind, ParseError> {
        let tok = self.next_token()?;
        let kind = tok.kind;
        self.push_token(tok);
        Ok(kind)
    }

    fn expect(&mut self, kind: TokenKind) -> Result<Token, ParseError> {
        let tok = self.next_token()?;
        if tok.kind != kind {
            return Err(ParseError(format!(
                "Expected {} but got {} at position {}",
                kind, tok.kind, tok.position
            )));
        }
        Ok(tok)
    }

    // ------------------------------------------------------------------
    // Public entry point
    // ------------------------------------------------------------------

    /// Parse the entire expression and return the root AST node.
    ///
    /// Returns `Err(ParseError)` if the expression is empty or malformed.
    pub fn parse(&mut self) -> Result<ExprNode, ParseError> {
        let node = self.parse_value_expr()?;
        match node {
            None => Err(ParseError("Empty expression".to_string())),
            Some(n) => {
                let tok = self.next_token()?;
                if tok.kind != TokenKind::TokEof {
                    return Err(ParseError(format!(
                        "Unexpected token {} at position {}",
                        tok.kind, tok.position
                    )));
                }
                Ok(n)
            }
        }
    }

    // ------------------------------------------------------------------
    // Level 1: semicolon sequences
    // ------------------------------------------------------------------

    fn parse_value_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_assign_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        let mut chain: Option<*mut ExprNode> = None;

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::Semi {
                let right = self.parse_assign_expr()?;
                if chain.is_none() {
                    let mut seq = ExprNode::new(OpKind::OSeq);
                    seq.left = Some(Box::new(node));
                    seq.right = right.map(Box::new);
                    node = seq;
                    // Point chain to node itself (which is the seq)
                    chain = Some(&mut node as *mut ExprNode);
                } else {
                    // Build a new seq node and attach to chain's right
                    let mut seq = ExprNode::new(OpKind::OSeq);
                    seq.right = right.map(Box::new);
                    // We need to attach the previous chain's right content as seq.left
                    // and replace chain's right with seq.
                    unsafe {
                        let chain_ptr = chain.unwrap();
                        let old_right = (*chain_ptr).right.take();
                        seq.left = old_right;
                        (*chain_ptr).right = Some(Box::new(seq));
                        // Update chain to point to the new seq
                        chain = Some(
                            (*chain_ptr).right.as_mut().unwrap().as_mut() as *mut ExprNode
                        );
                    }
                }
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 2: assignment
    // ------------------------------------------------------------------

    fn parse_assign_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let node = match self.parse_lambda_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        let tok = self.next_token()?;
        if tok.kind == TokenKind::Assign {
            let rhs = self.parse_lambda_expr()?;
            let scope_node = ExprNode {
                kind: OpKind::Scope,
                left: rhs.map(Box::new),
                right: None,
                value: NodeValue::None,
            };
            Ok(Some(ExprNode {
                kind: OpKind::ODefine,
                left: Some(Box::new(node)),
                right: Some(Box::new(scope_node)),
                value: NodeValue::None,
            }))
        } else {
            self.push_token(tok);
            Ok(Some(node))
        }
    }

    // ------------------------------------------------------------------
    // Level 3: lambda
    // ------------------------------------------------------------------

    fn parse_lambda_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let node = match self.parse_comma_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        let tok = self.next_token()?;
        if tok.kind == TokenKind::Arrow {
            let body = self.parse_querycolon_expr()?;
            let scope_node = ExprNode {
                kind: OpKind::Scope,
                left: body.map(Box::new),
                right: None,
                value: NodeValue::None,
            };
            Ok(Some(ExprNode {
                kind: OpKind::OLambda,
                left: Some(Box::new(node)),
                right: Some(Box::new(scope_node)),
                value: NodeValue::None,
            }))
        } else {
            self.push_token(tok);
            Ok(Some(node))
        }
    }

    // ------------------------------------------------------------------
    // Level 4: comma lists
    // ------------------------------------------------------------------

    fn parse_comma_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_querycolon_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        let mut tail: Option<*mut ExprNode> = None;

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::Comma {
                // Peek to see if we have a closing paren (trailing comma).
                let peek_kind = self.peek_token()?;
                if peek_kind == TokenKind::Rparen {
                    break;
                }

                let next_item = self.parse_querycolon_expr()?;

                if tail.is_none() {
                    let mut cons = ExprNode::new(OpKind::OCons);
                    cons.left = Some(Box::new(node));
                    let mut chain = ExprNode::new(OpKind::OCons);
                    chain.left = next_item.map(Box::new);
                    cons.right = Some(Box::new(chain));
                    node = cons;
                    // tail points to the last cons (the right child)
                    tail = Some(
                        node.right.as_mut().unwrap().as_mut() as *mut ExprNode
                    );
                } else {
                    let mut chain = ExprNode::new(OpKind::OCons);
                    chain.left = next_item.map(Box::new);
                    unsafe {
                        let tail_ptr = tail.unwrap();
                        (*tail_ptr).right = Some(Box::new(chain));
                        tail = Some(
                            (*tail_ptr).right.as_mut().unwrap().as_mut() as *mut ExprNode
                        );
                    }
                }
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 5: ternary / postfix if
    // ------------------------------------------------------------------

    fn parse_querycolon_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let node = match self.parse_or_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        let tok = self.next_token()?;
        if tok.kind == TokenKind::Query {
            // Traditional ternary: cond ? then : else
            let then_expr = self.parse_or_expr()?.ok_or_else(|| {
                ParseError("'?' operator not followed by argument".to_string())
            })?;
            self.expect(TokenKind::Colon)?;
            let else_expr = self.parse_or_expr()?.ok_or_else(|| {
                ParseError("':' operator not followed by argument".to_string())
            })?;
            let colon = ExprNode::binary(OpKind::OColon, then_expr, else_expr);
            Ok(Some(ExprNode {
                kind: OpKind::OQuery,
                left: Some(Box::new(node)),
                right: Some(Box::new(colon)),
                value: NodeValue::None,
            }))
        } else if tok.kind == TokenKind::KwIf {
            // Postfix: value_expr if cond [else alt]
            let cond = self.parse_or_expr()?.ok_or_else(|| {
                ParseError("'if' keyword not followed by argument".to_string())
            })?;
            let tok2 = self.next_token()?;
            let alt = if tok2.kind == TokenKind::KwElse {
                self.parse_or_expr()?.ok_or_else(|| {
                    ParseError("'else' keyword not followed by argument".to_string())
                })?
            } else {
                self.push_token(tok2);
                ExprNode::value_node(NodeValue::None)
            };
            let colon = ExprNode::binary(OpKind::OColon, node, alt);
            Ok(Some(ExprNode {
                kind: OpKind::OQuery,
                left: Some(Box::new(cond)),
                right: Some(Box::new(colon)),
                value: NodeValue::None,
            }))
        } else {
            self.push_token(tok);
            Ok(Some(node))
        }
    }

    // ------------------------------------------------------------------
    // Level 6: logical OR
    // ------------------------------------------------------------------

    fn parse_or_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_and_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::KwOr {
                let right = self.parse_and_expr()?.ok_or_else(|| {
                    ParseError(format!(
                        "'{}' operator not followed by argument",
                        tok.symbol
                    ))
                })?;
                node = ExprNode::binary(OpKind::OOr, node, right);
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 7: logical AND
    // ------------------------------------------------------------------

    fn parse_and_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_logic_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::KwAnd {
                let right = self.parse_logic_expr()?.ok_or_else(|| {
                    ParseError(format!(
                        "'{}' operator not followed by argument",
                        tok.symbol
                    ))
                })?;
                node = ExprNode::binary(OpKind::OAnd, node, right);
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 8: comparison / match
    // ------------------------------------------------------------------

    fn parse_logic_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_add_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            let (op_kind, negate) = match tok.kind {
                TokenKind::Equal => (Some(OpKind::OEq), false),
                TokenKind::Nequal => (Some(OpKind::OEq), true),
                TokenKind::Match => (Some(OpKind::OMatch), false),
                TokenKind::Nmatch => (Some(OpKind::OMatch), true),
                TokenKind::Less => (Some(OpKind::OLt), false),
                TokenKind::LessEq => (Some(OpKind::OLte), false),
                TokenKind::Greater => (Some(OpKind::OGt), false),
                TokenKind::GreaterEq => (Some(OpKind::OGte), false),
                _ => {
                    self.push_token(tok);
                    break;
                }
            };

            if let Some(kind) = op_kind {
                let right = self.parse_add_expr()?.ok_or_else(|| {
                    ParseError(format!(
                        "'{}' operator not followed by argument",
                        tok.symbol
                    ))
                })?;
                node = ExprNode::binary(kind, node, right);
                if negate {
                    node = ExprNode::unary(OpKind::ONot, node);
                }
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 9: addition / subtraction
    // ------------------------------------------------------------------

    fn parse_add_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_mul_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            let op_kind = match tok.kind {
                TokenKind::Plus => OpKind::OAdd,
                TokenKind::Minus => OpKind::OSub,
                _ => {
                    self.push_token(tok);
                    break;
                }
            };

            let right = self.parse_mul_expr()?.ok_or_else(|| {
                ParseError(format!(
                    "'{}' operator not followed by argument",
                    tok.symbol
                ))
            })?;
            node = ExprNode::binary(op_kind, node, right);
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 10: multiplication / division
    // ------------------------------------------------------------------

    fn parse_mul_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_unary_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            let op_kind = match tok.kind {
                TokenKind::Star => OpKind::OMul,
                TokenKind::Slash | TokenKind::KwDiv => OpKind::ODiv,
                _ => {
                    self.push_token(tok);
                    break;
                }
            };

            let right = self.parse_unary_expr()?.ok_or_else(|| {
                ParseError(format!(
                    "'{}' operator not followed by argument",
                    tok.symbol
                ))
            })?;
            node = ExprNode::binary(op_kind, node, right);
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 11: unary prefix
    // ------------------------------------------------------------------

    fn parse_unary_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let tok = self.next_token()?;

        if tok.kind == TokenKind::Exclam {
            let operand = self.parse_unary_expr()?.ok_or_else(|| {
                ParseError("'!' operator not followed by argument".to_string())
            })?;
            // Constant folding for literal booleans.
            if operand.kind == OpKind::Value {
                if let NodeValue::Boolean(b) = operand.value {
                    return Ok(Some(ExprNode::value_node(NodeValue::Boolean(!b))));
                }
            }
            return Ok(Some(ExprNode::unary(OpKind::ONot, operand)));
        }

        if tok.kind == TokenKind::Minus {
            let operand = self.parse_unary_expr()?.ok_or_else(|| {
                ParseError("'-' operator not followed by argument".to_string())
            })?;
            // Constant folding for numeric literals.
            if operand.kind == OpKind::Value {
                match operand.value {
                    NodeValue::Integer(n) => {
                        return Ok(Some(ExprNode::value_node(NodeValue::Integer(-n))));
                    }
                    NodeValue::Float(n) => {
                        return Ok(Some(ExprNode::value_node(NodeValue::Float(-n))));
                    }
                    _ => {}
                }
            }
            return Ok(Some(ExprNode::unary(OpKind::ONeg, operand)));
        }

        self.push_token(tok);
        self.parse_dot_expr()
    }

    // ------------------------------------------------------------------
    // Level 12: dot / member access
    // ------------------------------------------------------------------

    fn parse_dot_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_call_expr()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::Dot {
                let right = self.parse_call_expr()?.ok_or_else(|| {
                    ParseError("'.' operator not followed by argument".to_string())
                })?;
                node = ExprNode::binary(OpKind::OLookup, node, right);
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 13: function call
    // ------------------------------------------------------------------

    fn parse_call_expr(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let mut node = match self.parse_value_term()? {
            Some(n) => n,
            None => return Ok(None),
        };

        loop {
            let tok = self.next_token()?;
            if tok.kind == TokenKind::Lparen {
                // Push LPAREN back so parse_value_term sees it as a
                // parenthesized expression (the argument list).
                self.push_token(tok);
                let args = self.parse_value_term()?;
                node = ExprNode {
                    kind: OpKind::OCall,
                    left: Some(Box::new(node)),
                    right: args.map(Box::new),
                    value: NodeValue::None,
                };
            } else {
                self.push_token(tok);
                break;
            }
        }
        Ok(Some(node))
    }

    // ------------------------------------------------------------------
    // Level 14: primary values
    // ------------------------------------------------------------------

    fn parse_value_term(&mut self) -> Result<Option<ExprNode>, ParseError> {
        let tok = self.next_token()?;

        match tok.kind {
            TokenKind::Value => {
                let nv = token_value_to_node_value(&tok.value);
                Ok(Some(ExprNode::value_node(nv)))
            }
            TokenKind::Ident => {
                if let TokenValue::Str(name) = tok.value {
                    Ok(Some(ExprNode::ident_node(&name)))
                } else {
                    Ok(Some(ExprNode::ident_node("")))
                }
            }
            TokenKind::Lparen => {
                let inner = self.parse_value_expr()?;
                self.expect(TokenKind::Rparen)?;
                Ok(inner)
            }
            _ => {
                self.push_token(tok);
                Ok(None)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Convert a `TokenValue` to a `NodeValue`.
fn token_value_to_node_value(tv: &TokenValue) -> NodeValue {
    match tv {
        TokenValue::None => NodeValue::None,
        TokenValue::Integer(n) => NodeValue::Integer(*n),
        TokenValue::Float(n) => NodeValue::Float(*n),
        TokenValue::Str(s) => NodeValue::Str(s.clone()),
        TokenValue::Boolean(b) => NodeValue::Boolean(*b),
    }
}

/// Convenience function: parse an expression string into an AST.
pub fn compile(expr_string: &str) -> Result<ExprNode, ParseError> {
    ExprParser::new(expr_string).parse()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_integer_literal() {
        let node = compile("42").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Integer(42));
    }

    #[test]
    fn test_parse_float_literal() {
        let node = compile("3.14").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Float(3.14));
    }

    #[test]
    fn test_parse_boolean_true() {
        let node = compile("true").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Boolean(true));
    }

    #[test]
    fn test_parse_boolean_false() {
        let node = compile("false").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Boolean(false));
    }

    #[test]
    fn test_parse_string_literal() {
        let node = compile(r#""hello""#).unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Str("hello".to_string()));
    }

    #[test]
    fn test_parse_identifier() {
        let node = compile("amount").unwrap();
        assert_eq!(node.kind, OpKind::Ident);
        assert_eq!(node.value, NodeValue::Str("amount".to_string()));
    }

    #[test]
    fn test_parse_addition() {
        let node = compile("1 + 2").unwrap();
        assert_eq!(node.kind, OpKind::OAdd);
        assert_eq!(node.left.as_ref().unwrap().value, NodeValue::Integer(1));
        assert_eq!(node.right.as_ref().unwrap().value, NodeValue::Integer(2));
    }

    #[test]
    fn test_parse_subtraction() {
        let node = compile("5 - 3").unwrap();
        assert_eq!(node.kind, OpKind::OSub);
    }

    #[test]
    fn test_parse_multiplication() {
        let node = compile("2 * 3").unwrap();
        assert_eq!(node.kind, OpKind::OMul);
    }

    #[test]
    fn test_parse_division() {
        let node = compile("10 / 2").unwrap();
        assert_eq!(node.kind, OpKind::ODiv);
    }

    #[test]
    fn test_precedence_mul_over_add() {
        // 1 + 2 * 3 should parse as 1 + (2 * 3)
        let node = compile("1 + 2 * 3").unwrap();
        assert_eq!(node.kind, OpKind::OAdd);
        assert_eq!(node.left.as_ref().unwrap().value, NodeValue::Integer(1));
        let right = node.right.as_ref().unwrap();
        assert_eq!(right.kind, OpKind::OMul);
        assert_eq!(right.left.as_ref().unwrap().value, NodeValue::Integer(2));
        assert_eq!(right.right.as_ref().unwrap().value, NodeValue::Integer(3));
    }

    #[test]
    fn test_parenthesized_expression() {
        // (1 + 2) * 3 should parse as (1 + 2) * 3
        let node = compile("(1 + 2) * 3").unwrap();
        assert_eq!(node.kind, OpKind::OMul);
        let left = node.left.as_ref().unwrap();
        assert_eq!(left.kind, OpKind::OAdd);
    }

    #[test]
    fn test_unary_negation_literal() {
        // -42 should constant-fold to Value(-42)
        let node = compile("-42").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Integer(-42));
    }

    #[test]
    fn test_unary_negation_ident() {
        // -x should produce O_NEG node
        let node = compile("-x").unwrap();
        assert_eq!(node.kind, OpKind::ONeg);
        assert_eq!(
            node.left.as_ref().unwrap().value,
            NodeValue::Str("x".to_string())
        );
    }

    #[test]
    fn test_logical_not_literal() {
        // !true should constant-fold to false
        let node = compile("!true").unwrap();
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Boolean(false));
    }

    #[test]
    fn test_logical_not_ident() {
        let node = compile("!x").unwrap();
        assert_eq!(node.kind, OpKind::ONot);
    }

    #[test]
    fn test_comparison_equal() {
        let node = compile("a == b").unwrap();
        assert_eq!(node.kind, OpKind::OEq);
    }

    #[test]
    fn test_comparison_not_equal() {
        // != desugars to !(==)
        let node = compile("a != b").unwrap();
        assert_eq!(node.kind, OpKind::ONot);
        assert_eq!(node.left.as_ref().unwrap().kind, OpKind::OEq);
    }

    #[test]
    fn test_comparison_less() {
        let node = compile("a < b").unwrap();
        assert_eq!(node.kind, OpKind::OLt);
    }

    #[test]
    fn test_comparison_less_equal() {
        let node = compile("a <= b").unwrap();
        assert_eq!(node.kind, OpKind::OLte);
    }

    #[test]
    fn test_comparison_greater() {
        let node = compile("a > b").unwrap();
        assert_eq!(node.kind, OpKind::OGt);
    }

    #[test]
    fn test_comparison_greater_equal() {
        let node = compile("a >= b").unwrap();
        assert_eq!(node.kind, OpKind::OGte);
    }

    #[test]
    fn test_logical_and() {
        let node = compile("a and b").unwrap();
        assert_eq!(node.kind, OpKind::OAnd);
    }

    #[test]
    fn test_logical_or() {
        let node = compile("a or b").unwrap();
        assert_eq!(node.kind, OpKind::OOr);
    }

    #[test]
    fn test_and_or_precedence() {
        // a or b and c should parse as a or (b and c)
        let node = compile("a or b and c").unwrap();
        assert_eq!(node.kind, OpKind::OOr);
        assert_eq!(node.right.as_ref().unwrap().kind, OpKind::OAnd);
    }

    #[test]
    fn test_ternary_operator() {
        let node = compile("x ? 1 : 2").unwrap();
        assert_eq!(node.kind, OpKind::OQuery);
        let colon = node.right.as_ref().unwrap();
        assert_eq!(colon.kind, OpKind::OColon);
        assert_eq!(colon.left.as_ref().unwrap().value, NodeValue::Integer(1));
        assert_eq!(colon.right.as_ref().unwrap().value, NodeValue::Integer(2));
    }

    #[test]
    fn test_postfix_if() {
        let node = compile("1 if x").unwrap();
        assert_eq!(node.kind, OpKind::OQuery);
        // condition is x
        assert_eq!(
            node.left.as_ref().unwrap().value,
            NodeValue::Str("x".to_string())
        );
        // then branch is 1
        let colon = node.right.as_ref().unwrap();
        assert_eq!(colon.kind, OpKind::OColon);
        assert_eq!(colon.left.as_ref().unwrap().value, NodeValue::Integer(1));
    }

    #[test]
    fn test_postfix_if_else() {
        let node = compile("1 if x else 2").unwrap();
        assert_eq!(node.kind, OpKind::OQuery);
        let colon = node.right.as_ref().unwrap();
        assert_eq!(colon.left.as_ref().unwrap().value, NodeValue::Integer(1));
        assert_eq!(colon.right.as_ref().unwrap().value, NodeValue::Integer(2));
    }

    #[test]
    fn test_assignment() {
        let node = compile("x = 42").unwrap();
        assert_eq!(node.kind, OpKind::ODefine);
        assert_eq!(
            node.left.as_ref().unwrap().value,
            NodeValue::Str("x".to_string())
        );
        let scope = node.right.as_ref().unwrap();
        assert_eq!(scope.kind, OpKind::Scope);
        assert_eq!(scope.left.as_ref().unwrap().value, NodeValue::Integer(42));
    }

    #[test]
    fn test_lambda() {
        let node = compile("x -> x + 1").unwrap();
        assert_eq!(node.kind, OpKind::OLambda);
        let scope = node.right.as_ref().unwrap();
        assert_eq!(scope.kind, OpKind::Scope);
        assert_eq!(scope.left.as_ref().unwrap().kind, OpKind::OAdd);
    }

    #[test]
    fn test_function_call() {
        let node = compile("f(1)").unwrap();
        assert_eq!(node.kind, OpKind::OCall);
        assert_eq!(
            node.left.as_ref().unwrap().value,
            NodeValue::Str("f".to_string())
        );
        assert_eq!(
            node.right.as_ref().unwrap().value,
            NodeValue::Integer(1)
        );
    }

    #[test]
    fn test_function_call_no_args() {
        // f() -- empty parens yield None right child
        let node = compile("f()").unwrap();
        assert_eq!(node.kind, OpKind::OCall);
        assert!(node.right.is_none());
    }

    #[test]
    fn test_dot_access() {
        let node = compile("a.b").unwrap();
        assert_eq!(node.kind, OpKind::OLookup);
        assert_eq!(
            node.left.as_ref().unwrap().value,
            NodeValue::Str("a".to_string())
        );
        assert_eq!(
            node.right.as_ref().unwrap().value,
            NodeValue::Str("b".to_string())
        );
    }

    #[test]
    fn test_comma_list() {
        let node = compile("f(1, 2, 3)").unwrap();
        assert_eq!(node.kind, OpKind::OCall);
        let args = node.right.as_ref().unwrap();
        assert_eq!(args.kind, OpKind::OCons);
    }

    #[test]
    fn test_semicolon_sequence() {
        let node = compile("1; 2; 3").unwrap();
        assert_eq!(node.kind, OpKind::OSeq);
    }

    #[test]
    fn test_match_operator() {
        let node = compile("account =~ /Expenses/").unwrap();
        assert_eq!(node.kind, OpKind::OMatch);
    }

    #[test]
    fn test_nmatch_operator() {
        // !~ desugars to !(=~)
        let node = compile("account !~ /Expenses/").unwrap();
        assert_eq!(node.kind, OpKind::ONot);
        assert_eq!(node.left.as_ref().unwrap().kind, OpKind::OMatch);
    }

    #[test]
    fn test_complex_expression() {
        // amount > 100 and account =~ /Expenses/
        let node = compile("amount > 100 and account =~ /Expenses/").unwrap();
        assert_eq!(node.kind, OpKind::OAnd);
        assert_eq!(node.left.as_ref().unwrap().kind, OpKind::OGt);
        assert_eq!(node.right.as_ref().unwrap().kind, OpKind::OMatch);
    }

    #[test]
    fn test_empty_expression_error() {
        let result = compile("");
        assert!(result.is_err());
    }

    #[test]
    fn test_unexpected_token_error() {
        let result = compile("1 2");
        assert!(result.is_err());
    }

    #[test]
    fn test_div_keyword() {
        let node = compile("10 div 3").unwrap();
        assert_eq!(node.kind, OpKind::ODiv);
    }

    #[test]
    fn test_nested_parens() {
        let node = compile("((1 + 2))").unwrap();
        assert_eq!(node.kind, OpKind::OAdd);
    }

    #[test]
    fn test_chained_dot() {
        let node = compile("a.b.c").unwrap();
        assert_eq!(node.kind, OpKind::OLookup);
        // Left should be a.b (another OLookup)
        assert_eq!(node.left.as_ref().unwrap().kind, OpKind::OLookup);
    }

    #[test]
    fn test_method_call() {
        let node = compile("a.f(1)").unwrap();
        // a.f(1) parses as a.(f(1)) -> O_LOOKUP with a on left, O_CALL on right
        // because call_expr is tighter than dot_expr in the precedence hierarchy.
        assert_eq!(node.kind, OpKind::OLookup);
        assert_eq!(node.right.as_ref().unwrap().kind, OpKind::OCall);
    }
}
