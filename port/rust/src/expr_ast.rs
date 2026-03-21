//! AST node types for the Ledger expression engine.
//!
//! This module provides the `OpKind` enum and `ExprNode` struct, a Rust port
//! of Ledger's `op_t` type from `op.h`.  Every parsed expression is
//! represented as a tree of `ExprNode` objects, each carrying a `kind` tag
//! that identifies it as a constant, terminal, or operator, plus a polymorphic
//! `value` field for node-specific data.

use std::fmt;

// ---------------------------------------------------------------------------
// OpKind
// ---------------------------------------------------------------------------

/// Discriminator for the kind of AST node an `ExprNode` represents.
///
/// Mirrors `op_t::kind_t` from the C++ Ledger source.  The enum is
/// partitioned into logical groups: constant terminals, callable terminals,
/// unary operators, and binary operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum OpKind {
    // --- Constant Terminals ---
    /// Internal sentinel: declared-but-unassigned variable.
    Plug,
    /// Literal constant (integer, amount, string, date, etc.).
    Value,
    /// Named identifier, resolved at compile or eval time.
    Ident,

    // --- Callable / Scope Terminals ---
    /// Native callable.
    Function,
    /// Lexical scope capture wrapping a sub-expression.
    Scope,

    // --- Unary Operators ---
    /// Logical negation (`not expr` or `! expr`).
    ONot,
    /// Arithmetic negation (`- expr`).
    ONeg,

    // --- Comparison Operators ---
    /// Equality test (`==`).
    OEq,
    /// Less than (`<`).
    OLt,
    /// Less than or equal (`<=`).
    OLte,
    /// Greater than (`>`).
    OGt,
    /// Greater than or equal (`>=`).
    OGte,

    // --- Logical Connectives ---
    /// Short-circuit logical AND.
    OAnd,
    /// Short-circuit logical OR.
    OOr,

    // --- Arithmetic Operators ---
    /// Addition (`+`).
    OAdd,
    /// Subtraction (`-`).
    OSub,
    /// Multiplication (`*`).
    OMul,
    /// Division (`/`).
    ODiv,

    // --- Ternary Conditional ---
    /// Ternary condition (`expr ? a : b`).
    OQuery,
    /// Ternary branches holder.
    OColon,

    // --- Structural Operators ---
    /// Comma-separated list constructor.
    OCons,
    /// Semicolon-separated sequence.
    OSeq,

    // --- Definition / Invocation ---
    /// Variable or function definition (`name = expr`).
    ODefine,
    /// Member access / dot operator (`obj.member`).
    OLookup,
    /// Lambda expression (`params -> body`).
    OLambda,
    /// Function call (`func(args)`).
    OCall,
    /// Regex match operator (`expr =~ /pattern/`).
    OMatch,

    /// Default-constructed, not yet assigned a real kind.
    Unknown,
}

impl OpKind {
    /// True if this kind represents a unary operator.
    pub fn is_unary(self) -> bool {
        matches!(self, OpKind::ONot | OpKind::ONeg)
    }

    /// True if this kind represents a binary operator.
    pub fn is_binary(self) -> bool {
        matches!(
            self,
            OpKind::OEq
                | OpKind::OLt
                | OpKind::OLte
                | OpKind::OGt
                | OpKind::OGte
                | OpKind::OAnd
                | OpKind::OOr
                | OpKind::OAdd
                | OpKind::OSub
                | OpKind::OMul
                | OpKind::ODiv
                | OpKind::OQuery
                | OpKind::OColon
                | OpKind::OCons
                | OpKind::OSeq
                | OpKind::ODefine
                | OpKind::OLookup
                | OpKind::OLambda
                | OpKind::OCall
                | OpKind::OMatch
        )
    }

    /// True if this kind represents a terminal (constant or callable).
    pub fn is_terminal(self) -> bool {
        matches!(
            self,
            OpKind::Plug | OpKind::Value | OpKind::Ident | OpKind::Function | OpKind::Scope
        )
    }
}

impl fmt::Display for OpKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

// ---------------------------------------------------------------------------
// NodeValue - polymorphic payload for AST nodes
// ---------------------------------------------------------------------------

/// The polymorphic payload carried by an AST node.
#[derive(Debug, Clone, PartialEq)]
pub enum NodeValue {
    /// No value.
    None,
    /// Integer constant.
    Integer(i64),
    /// Floating-point constant.
    Float(f64),
    /// String value (identifier name, string literal).
    Str(String),
    /// Boolean constant.
    Boolean(bool),
}

impl NodeValue {
    /// True if this is the None variant.
    pub fn is_none(&self) -> bool {
        matches!(self, NodeValue::None)
    }
}

impl fmt::Display for NodeValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            NodeValue::None => write!(f, "None"),
            NodeValue::Integer(n) => write!(f, "{}", n),
            NodeValue::Float(n) => write!(f, "{}", n),
            NodeValue::Str(s) => write!(f, "{}", s),
            NodeValue::Boolean(b) => write!(f, "{}", b),
        }
    }
}

// ---------------------------------------------------------------------------
// ExprNode
// ---------------------------------------------------------------------------

/// A single node in the expression abstract syntax tree.
///
/// Uses `Box` for child pointers to allow recursive tree structure.
#[derive(Debug, Clone, PartialEq)]
pub struct ExprNode {
    /// Discriminator tag identifying this node's role in the AST.
    pub kind: OpKind,
    /// Left child (operand) or sole operand for unary operators.
    pub left: Option<Box<ExprNode>>,
    /// Right child for binary operators.
    pub right: Option<Box<ExprNode>>,
    /// Polymorphic payload -- the active content depends on `kind`:
    /// - VALUE nodes: the literal value (integer, float, string, bool)
    /// - IDENT nodes: the identifier name (Str)
    /// - Operators: None (children carry the data)
    pub value: NodeValue,
}

impl ExprNode {
    /// Create a new node with the given kind and no children.
    pub fn new(kind: OpKind) -> Self {
        ExprNode {
            kind,
            left: None,
            right: None,
            value: NodeValue::None,
        }
    }

    /// Create a VALUE node with the given payload.
    pub fn value_node(value: NodeValue) -> Self {
        ExprNode {
            kind: OpKind::Value,
            left: None,
            right: None,
            value,
        }
    }

    /// Create an IDENT node with the given name.
    pub fn ident_node(name: &str) -> Self {
        ExprNode {
            kind: OpKind::Ident,
            left: None,
            right: None,
            value: NodeValue::Str(name.to_string()),
        }
    }

    /// Create a unary operator node.
    pub fn unary(kind: OpKind, operand: ExprNode) -> Self {
        ExprNode {
            kind,
            left: Some(Box::new(operand)),
            right: None,
            value: NodeValue::None,
        }
    }

    /// Create a binary operator node.
    pub fn binary(kind: OpKind, left: ExprNode, right: ExprNode) -> Self {
        ExprNode {
            kind,
            left: Some(Box::new(left)),
            right: Some(Box::new(right)),
            value: NodeValue::None,
        }
    }

    // ------------------------------------------------------------------
    // Classification helpers
    // ------------------------------------------------------------------

    /// True if this node is a literal VALUE constant.
    pub fn is_value(&self) -> bool {
        self.kind == OpKind::Value
    }

    /// True if this node is an identifier reference.
    pub fn is_ident(&self) -> bool {
        self.kind == OpKind::Ident
    }

    /// True if this node is a unary operator.
    pub fn is_unary_op(&self) -> bool {
        self.kind.is_unary()
    }

    /// True if this node is a binary operator.
    pub fn is_binary_op(&self) -> bool {
        self.kind.is_binary()
    }

    /// True if this node is a terminal (constant or callable).
    pub fn is_terminal(&self) -> bool {
        self.kind.is_terminal()
    }

    // ------------------------------------------------------------------
    // Traversal
    // ------------------------------------------------------------------

    /// Pre-order depth-first traversal calling `visitor` on each node.
    pub fn walk<F: FnMut(&ExprNode)>(&self, visitor: &mut F) {
        visitor(self);
        if let Some(ref left) = self.left {
            left.walk(visitor);
        }
        if let Some(ref right) = self.right {
            right.walk(visitor);
        }
    }

    /// Post-order depth-first traversal calling `visitor` on each node.
    pub fn walk_post<F: FnMut(&ExprNode)>(&self, visitor: &mut F) {
        if let Some(ref left) = self.left {
            left.walk_post(visitor);
        }
        if let Some(ref right) = self.right {
            right.walk_post(visitor);
        }
        visitor(self);
    }

    /// Collect all nodes via pre-order traversal into a Vec.
    pub fn iter_nodes(&self) -> Vec<&ExprNode> {
        let mut nodes = Vec::new();
        let mut stack = vec![self];
        while let Some(node) = stack.pop() {
            nodes.push(node);
            // Push right first so left is processed first (pre-order).
            if let Some(ref right) = node.right {
                stack.push(right);
            }
            if let Some(ref left) = node.left {
                stack.push(left);
            }
        }
        nodes
    }

    // ------------------------------------------------------------------
    // Display
    // ------------------------------------------------------------------

    /// Return a multi-line hierarchical dump for debugging.
    pub fn dump(&self, depth: usize) -> String {
        let indent = "  ".repeat(depth);
        let mut parts = vec![format!("{}{:?}", indent, self.kind)];
        if !self.value.is_none() {
            parts[0] = format!("{} ({:?})", parts[0], self.value);
        }
        if let Some(ref left) = self.left {
            parts.push(left.dump(depth + 1));
        }
        if let Some(ref right) = self.right {
            parts.push(right.dump(depth + 1));
        }
        parts.join("\n")
    }
}

impl fmt::Display for ExprNode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.kind {
            OpKind::Value | OpKind::Ident => {
                write!(f, "ExprNode({:?}, {:?})", self.kind, self.value)
            }
            _ => {
                let mut parts = Vec::new();
                if self.left.is_some() {
                    parts.push("left=...");
                }
                if self.right.is_some() {
                    parts.push("right=...");
                }
                if parts.is_empty() {
                    write!(f, "ExprNode({:?})", self.kind)
                } else {
                    write!(f, "ExprNode({:?}, {})", self.kind, parts.join(", "))
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_value_node_creation() {
        let node = ExprNode::value_node(NodeValue::Integer(42));
        assert_eq!(node.kind, OpKind::Value);
        assert_eq!(node.value, NodeValue::Integer(42));
        assert!(node.left.is_none());
        assert!(node.right.is_none());
    }

    #[test]
    fn test_ident_node_creation() {
        let node = ExprNode::ident_node("amount");
        assert_eq!(node.kind, OpKind::Ident);
        assert_eq!(node.value, NodeValue::Str("amount".to_string()));
    }

    #[test]
    fn test_unary_node() {
        let operand = ExprNode::value_node(NodeValue::Integer(5));
        let node = ExprNode::unary(OpKind::ONeg, operand);
        assert_eq!(node.kind, OpKind::ONeg);
        assert!(node.left.is_some());
        assert!(node.right.is_none());
        assert!(node.is_unary_op());
    }

    #[test]
    fn test_binary_node() {
        let left = ExprNode::value_node(NodeValue::Integer(1));
        let right = ExprNode::value_node(NodeValue::Integer(2));
        let node = ExprNode::binary(OpKind::OAdd, left, right);
        assert_eq!(node.kind, OpKind::OAdd);
        assert!(node.left.is_some());
        assert!(node.right.is_some());
        assert!(node.is_binary_op());
    }

    #[test]
    fn test_classification_helpers() {
        let val = ExprNode::value_node(NodeValue::Integer(1));
        assert!(val.is_value());
        assert!(!val.is_ident());
        assert!(val.is_terminal());
        assert!(!val.is_unary_op());
        assert!(!val.is_binary_op());

        let ident = ExprNode::ident_node("x");
        assert!(!ident.is_value());
        assert!(ident.is_ident());
        assert!(ident.is_terminal());
    }

    #[test]
    fn test_opkind_classification() {
        assert!(OpKind::ONot.is_unary());
        assert!(OpKind::ONeg.is_unary());
        assert!(!OpKind::OAdd.is_unary());

        assert!(OpKind::OAdd.is_binary());
        assert!(OpKind::OEq.is_binary());
        assert!(!OpKind::ONot.is_binary());

        assert!(OpKind::Value.is_terminal());
        assert!(OpKind::Ident.is_terminal());
        assert!(OpKind::Function.is_terminal());
        assert!(!OpKind::OAdd.is_terminal());
    }

    #[test]
    fn test_walk_preorder() {
        // Build tree: 1 + 2
        let left = ExprNode::value_node(NodeValue::Integer(1));
        let right = ExprNode::value_node(NodeValue::Integer(2));
        let root = ExprNode::binary(OpKind::OAdd, left, right);

        let mut visited = Vec::new();
        root.walk(&mut |node| visited.push(node.kind));
        assert_eq!(visited, vec![OpKind::OAdd, OpKind::Value, OpKind::Value]);
    }

    #[test]
    fn test_walk_postorder() {
        let left = ExprNode::value_node(NodeValue::Integer(1));
        let right = ExprNode::value_node(NodeValue::Integer(2));
        let root = ExprNode::binary(OpKind::OAdd, left, right);

        let mut visited = Vec::new();
        root.walk_post(&mut |node| visited.push(node.kind));
        assert_eq!(visited, vec![OpKind::Value, OpKind::Value, OpKind::OAdd]);
    }

    #[test]
    fn test_dump() {
        let left = ExprNode::value_node(NodeValue::Integer(1));
        let right = ExprNode::value_node(NodeValue::Integer(2));
        let root = ExprNode::binary(OpKind::OAdd, left, right);
        let dump = root.dump(0);
        assert!(dump.contains("OAdd"));
        assert!(dump.contains("Value"));
    }

    #[test]
    fn test_display() {
        let node = ExprNode::value_node(NodeValue::Integer(42));
        let s = format!("{}", node);
        assert!(s.contains("Value"));
        assert!(s.contains("Integer(42)"));
    }

    #[test]
    fn test_node_value_is_none() {
        assert!(NodeValue::None.is_none());
        assert!(!NodeValue::Integer(0).is_none());
        assert!(!NodeValue::Boolean(false).is_none());
    }
}
