//! Scope hierarchy for expression variable and function resolution.
//!
//! This module provides the scope chain used by the expression evaluator to
//! resolve identifiers.  It is a Rust port of Ledger's `scope_t` hierarchy
//! from `scope.h`.
//!
//! The chain-of-responsibility pattern allows each scope in the hierarchy to
//! either handle a lookup itself or delegate to its parent:
//!
//! ```text
//! SymbolScope  -->  SymbolScope  -->  (root, no parent)
//! (inner)          (outer)
//! ```
//!
//! Scope types:
//! - **Scope**: Trait with `lookup(name)` protocol.
//! - **ChildScope**: Delegates `lookup` and `define` to a parent.
//! - **SymbolScope**: Maintains a local map of names to values or callables,
//!   checking locally first then delegating to the parent.
//! - **CallScope**: Provides positional function-call arguments.
//! - **BindScope**: Joins two scopes -- grandchild searched first, then parent.

use std::collections::HashMap;

use crate::expr_ast::NodeValue;

// ---------------------------------------------------------------------------
// ScopeValue - what can be stored in a scope
// ---------------------------------------------------------------------------

/// A value that can be stored in or retrieved from a scope.
///
/// This is deliberately kept simple for now. As the expression evaluator
/// grows, this may evolve to use `Value` from `value.rs`.
#[derive(Debug, Clone, PartialEq)]
pub enum ScopeValue {
    /// A node value (integer, float, string, boolean, none).
    Node(NodeValue),
}

impl ScopeValue {
    /// Create from a NodeValue.
    pub fn from_node(nv: NodeValue) -> Self {
        ScopeValue::Node(nv)
    }

    /// True if this is None/Void.
    pub fn is_null(&self) -> bool {
        matches!(self, ScopeValue::Node(NodeValue::None))
    }
}

// ---------------------------------------------------------------------------
// Scope trait
// ---------------------------------------------------------------------------

/// Abstract base trait for all scopes in the expression evaluation chain.
///
/// Every scope must implement `lookup(name)` to resolve symbol names.
pub trait Scope {
    /// Resolve `name` to a ScopeValue, or return `None`.
    fn lookup(&self, name: &str) -> Option<ScopeValue>;

    /// Define a symbol in this scope.  Default is a no-op.
    fn define(&mut self, _name: &str, _value: ScopeValue) {}

    /// Resolve `name` by walking the scope chain.
    ///
    /// The default implementation simply calls `lookup`.
    fn resolve(&self, name: &str) -> Option<ScopeValue> {
        self.lookup(name)
    }

    /// Return a human-readable description of this scope (for debugging).
    fn description(&self) -> &str {
        "<scope>"
    }
}

// ---------------------------------------------------------------------------
// ChildScope
// ---------------------------------------------------------------------------

/// A scope that delegates both `define` and `lookup` to a parent.
///
/// If a lookup is not handled by a derived type, it automatically propagates
/// to the parent.
pub struct ChildScope<'a> {
    parent: Option<&'a dyn Scope>,
}

impl<'a> ChildScope<'a> {
    /// Create a new child scope with the given parent.
    pub fn new(parent: Option<&'a dyn Scope>) -> Self {
        ChildScope { parent }
    }

    /// Get a reference to the parent scope.
    pub fn parent(&self) -> Option<&'a dyn Scope> {
        self.parent
    }
}

impl<'a> Scope for ChildScope<'a> {
    fn lookup(&self, name: &str) -> Option<ScopeValue> {
        self.parent.and_then(|p| p.lookup(name))
    }

    fn resolve(&self, name: &str) -> Option<ScopeValue> {
        let result = self.lookup(name);
        if result.is_some() {
            return result;
        }
        self.parent.and_then(|p| p.resolve(name))
    }

    fn description(&self) -> &str {
        match self.parent {
            Some(p) => p.description(),
            None => "<child_scope>",
        }
    }
}

// ---------------------------------------------------------------------------
// SymbolScope
// ---------------------------------------------------------------------------

/// A scope with a local symbol table for user-defined variables and functions.
///
/// When `define` is called, the symbol is stored locally.  When `lookup`
/// is called, the local table is checked first; if the symbol is not found,
/// the lookup delegates to the parent.
pub struct SymbolScope<'a> {
    parent: Option<&'a dyn Scope>,
    symbols: HashMap<String, ScopeValue>,
}

impl<'a> SymbolScope<'a> {
    /// Create a new symbol scope with the given parent.
    pub fn new(parent: Option<&'a dyn Scope>) -> Self {
        SymbolScope {
            parent,
            symbols: HashMap::new(),
        }
    }

    /// Get a reference to the parent scope.
    pub fn parent(&self) -> Option<&'a dyn Scope> {
        self.parent
    }

    /// Return the number of locally defined symbols.
    pub fn len(&self) -> usize {
        self.symbols.len()
    }

    /// True if there are no locally defined symbols.
    pub fn is_empty(&self) -> bool {
        self.symbols.is_empty()
    }
}

impl<'a> Scope for SymbolScope<'a> {
    fn define(&mut self, name: &str, value: ScopeValue) {
        self.symbols.insert(name.to_string(), value);
    }

    fn lookup(&self, name: &str) -> Option<ScopeValue> {
        if let Some(val) = self.symbols.get(name) {
            return Some(val.clone());
        }
        self.parent.and_then(|p| p.lookup(name))
    }

    fn resolve(&self, name: &str) -> Option<ScopeValue> {
        let result = self.lookup(name);
        if result.is_some() {
            return result;
        }
        self.parent.and_then(|p| p.resolve(name))
    }

    fn description(&self) -> &str {
        match self.parent {
            Some(p) => p.description(),
            None => "<symbol_scope>",
        }
    }
}

// ---------------------------------------------------------------------------
// CallScope
// ---------------------------------------------------------------------------

/// Scope for function/method calls, providing positional arguments.
///
/// When the expression engine encounters a function call, it creates a
/// `CallScope` that holds the function arguments as a list of ScopeValues.
pub struct CallScope<'a> {
    parent: Option<&'a dyn Scope>,
    /// Positional arguments.
    pub args: Vec<ScopeValue>,
}

impl<'a> CallScope<'a> {
    /// Create a new call scope with the given parent.
    pub fn new(parent: Option<&'a dyn Scope>) -> Self {
        CallScope {
            parent,
            args: Vec::new(),
        }
    }

    /// Create a new call scope with the given parent and arguments.
    pub fn with_args(parent: Option<&'a dyn Scope>, args: Vec<ScopeValue>) -> Self {
        CallScope { parent, args }
    }

    /// Append an argument value.
    pub fn push_back(&mut self, val: ScopeValue) {
        self.args.push(val);
    }

    /// Prepend an argument value.
    pub fn push_front(&mut self, val: ScopeValue) {
        self.args.insert(0, val);
    }

    /// Remove the last argument.
    pub fn pop_back(&mut self) {
        self.args.pop();
    }

    /// Get argument at index.
    pub fn get(&self, index: usize) -> Option<&ScopeValue> {
        self.args.get(index)
    }

    /// Return the number of arguments.
    pub fn len(&self) -> usize {
        self.args.len()
    }

    /// True if there are no arguments.
    pub fn is_empty(&self) -> bool {
        self.args.is_empty()
    }

    /// Return True if argument `index` exists and is not null.
    pub fn has(&self, index: usize) -> bool {
        self.args.get(index).map_or(false, |v| !v.is_null())
    }
}

impl<'a> Scope for CallScope<'a> {
    fn lookup(&self, name: &str) -> Option<ScopeValue> {
        self.parent.and_then(|p| p.lookup(name))
    }

    fn resolve(&self, name: &str) -> Option<ScopeValue> {
        let result = self.lookup(name);
        if result.is_some() {
            return result;
        }
        self.parent.and_then(|p| p.resolve(name))
    }

    fn description(&self) -> &str {
        match self.parent {
            Some(p) => p.description(),
            None => "<call_scope>",
        }
    }
}

// ---------------------------------------------------------------------------
// BindScope
// ---------------------------------------------------------------------------

/// Joins two scopes: lookups check the grandchild first, then the parent.
///
/// `BindScope` is used when evaluating an expression that needs access to
/// two independent scope chains.  Lookups try the grandchild scope first;
/// if not found, they fall through to the parent.
pub struct BindScope<'a> {
    parent: Option<&'a dyn Scope>,
    grandchild: &'a dyn Scope,
}

impl<'a> BindScope<'a> {
    /// Create a new bind scope joining parent and grandchild.
    pub fn new(parent: &'a dyn Scope, grandchild: &'a dyn Scope) -> Self {
        BindScope {
            parent: Some(parent),
            grandchild,
        }
    }
}

impl<'a> Scope for BindScope<'a> {
    fn lookup(&self, name: &str) -> Option<ScopeValue> {
        let result = self.grandchild.lookup(name);
        if result.is_some() {
            return result;
        }
        self.parent.and_then(|p| p.lookup(name))
    }

    fn resolve(&self, name: &str) -> Option<ScopeValue> {
        let result = self.lookup(name);
        if result.is_some() {
            return result;
        }
        self.parent.and_then(|p| p.resolve(name))
    }

    fn description(&self) -> &str {
        self.grandchild.description()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // A simple root scope for testing that always returns None.
    struct EmptyScope;

    impl Scope for EmptyScope {
        fn lookup(&self, _name: &str) -> Option<ScopeValue> {
            None
        }

        fn description(&self) -> &str {
            "<empty>"
        }
    }

    #[test]
    fn test_symbol_scope_define_and_lookup() {
        let mut scope = SymbolScope::new(None);
        scope.define("x", ScopeValue::from_node(NodeValue::Integer(42)));
        let result = scope.lookup("x");
        assert!(result.is_some());
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(42))
        );
    }

    #[test]
    fn test_symbol_scope_lookup_missing() {
        let scope = SymbolScope::new(None);
        let result = scope.lookup("x");
        assert!(result.is_none());
    }

    #[test]
    fn test_symbol_scope_parent_delegation() {
        let mut parent = SymbolScope::new(None);
        parent.define("y", ScopeValue::from_node(NodeValue::Integer(10)));

        let child = SymbolScope::new(Some(&parent));
        // Child should find y via parent delegation.
        let result = child.lookup("y");
        assert!(result.is_some());
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(10))
        );
    }

    #[test]
    fn test_symbol_scope_local_shadows_parent() {
        let mut parent = SymbolScope::new(None);
        parent.define("x", ScopeValue::from_node(NodeValue::Integer(1)));

        let mut child = SymbolScope::new(Some(&parent));
        child.define("x", ScopeValue::from_node(NodeValue::Integer(2)));

        let result = child.lookup("x");
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(2))
        );
    }

    #[test]
    fn test_child_scope_delegates_to_parent() {
        let mut parent = SymbolScope::new(None);
        parent.define("z", ScopeValue::from_node(NodeValue::Boolean(true)));

        let child = ChildScope::new(Some(&parent));
        let result = child.lookup("z");
        assert!(result.is_some());
    }

    #[test]
    fn test_child_scope_no_parent() {
        let child = ChildScope::new(None);
        let result = child.lookup("anything");
        assert!(result.is_none());
    }

    #[test]
    fn test_call_scope_arguments() {
        let empty = EmptyScope;
        let mut cs = CallScope::new(Some(&empty));
        assert!(cs.is_empty());
        assert_eq!(cs.len(), 0);

        cs.push_back(ScopeValue::from_node(NodeValue::Integer(1)));
        cs.push_back(ScopeValue::from_node(NodeValue::Integer(2)));
        assert_eq!(cs.len(), 2);
        assert!(!cs.is_empty());

        assert_eq!(
            cs.get(0).unwrap(),
            &ScopeValue::from_node(NodeValue::Integer(1))
        );
        assert_eq!(
            cs.get(1).unwrap(),
            &ScopeValue::from_node(NodeValue::Integer(2))
        );
        assert!(cs.get(2).is_none());

        assert!(cs.has(0));
        assert!(cs.has(1));
        assert!(!cs.has(2));
    }

    #[test]
    fn test_call_scope_push_front() {
        let empty = EmptyScope;
        let mut cs = CallScope::new(Some(&empty));
        cs.push_back(ScopeValue::from_node(NodeValue::Integer(2)));
        cs.push_front(ScopeValue::from_node(NodeValue::Integer(1)));
        assert_eq!(
            cs.get(0).unwrap(),
            &ScopeValue::from_node(NodeValue::Integer(1))
        );
        assert_eq!(
            cs.get(1).unwrap(),
            &ScopeValue::from_node(NodeValue::Integer(2))
        );
    }

    #[test]
    fn test_call_scope_pop_back() {
        let empty = EmptyScope;
        let mut cs = CallScope::new(Some(&empty));
        cs.push_back(ScopeValue::from_node(NodeValue::Integer(1)));
        cs.push_back(ScopeValue::from_node(NodeValue::Integer(2)));
        cs.pop_back();
        assert_eq!(cs.len(), 1);
    }

    #[test]
    fn test_call_scope_has_null() {
        let empty = EmptyScope;
        let mut cs = CallScope::new(Some(&empty));
        cs.push_back(ScopeValue::from_node(NodeValue::None));
        // has() returns false for null values
        assert!(!cs.has(0));
    }

    #[test]
    fn test_call_scope_delegates_lookup() {
        let mut parent = SymbolScope::new(None);
        parent.define("x", ScopeValue::from_node(NodeValue::Integer(99)));

        let cs = CallScope::new(Some(&parent));
        let result = cs.lookup("x");
        assert!(result.is_some());
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(99))
        );
    }

    #[test]
    fn test_bind_scope_grandchild_first() {
        let mut parent = SymbolScope::new(None);
        parent.define("x", ScopeValue::from_node(NodeValue::Integer(1)));

        let mut grandchild = SymbolScope::new(None);
        grandchild.define("x", ScopeValue::from_node(NodeValue::Integer(2)));

        let bind = BindScope::new(&parent, &grandchild);
        let result = bind.lookup("x");
        // Grandchild should win.
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(2))
        );
    }

    #[test]
    fn test_bind_scope_falls_through_to_parent() {
        let mut parent = SymbolScope::new(None);
        parent.define("y", ScopeValue::from_node(NodeValue::Integer(10)));

        let grandchild = SymbolScope::new(None);
        // grandchild has no "y"

        let bind = BindScope::new(&parent, &grandchild);
        let result = bind.lookup("y");
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(10))
        );
    }

    #[test]
    fn test_bind_scope_not_found() {
        let parent = SymbolScope::new(None);
        let grandchild = SymbolScope::new(None);

        let bind = BindScope::new(&parent, &grandchild);
        let result = bind.lookup("missing");
        assert!(result.is_none());
    }

    #[test]
    fn test_description() {
        let empty = EmptyScope;
        assert_eq!(empty.description(), "<empty>");

        let child = ChildScope::new(Some(&empty));
        assert_eq!(child.description(), "<empty>");

        let child_no_parent = ChildScope::new(None);
        assert_eq!(child_no_parent.description(), "<child_scope>");

        let sym = SymbolScope::new(None);
        assert_eq!(sym.description(), "<symbol_scope>");

        let cs = CallScope::new(Some(&empty));
        assert_eq!(cs.description(), "<empty>");

        let cs_no_parent = CallScope::new(None);
        assert_eq!(cs_no_parent.description(), "<call_scope>");
    }

    #[test]
    fn test_resolve_walks_chain() {
        let mut root = SymbolScope::new(None);
        root.define("a", ScopeValue::from_node(NodeValue::Integer(1)));

        let mut mid = SymbolScope::new(Some(&root));
        mid.define("b", ScopeValue::from_node(NodeValue::Integer(2)));

        let leaf = SymbolScope::new(Some(&mid));

        // resolve should find "a" from root
        let result = leaf.resolve("a");
        assert!(result.is_some());
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(1))
        );

        // resolve should find "b" from mid
        let result = leaf.resolve("b");
        assert!(result.is_some());
        assert_eq!(
            result.unwrap(),
            ScopeValue::from_node(NodeValue::Integer(2))
        );

        // resolve should return None for unknown
        let result = leaf.resolve("c");
        assert!(result.is_none());
    }

    #[test]
    fn test_symbol_scope_len_and_is_empty() {
        let mut scope = SymbolScope::new(None);
        assert!(scope.is_empty());
        assert_eq!(scope.len(), 0);

        scope.define("x", ScopeValue::from_node(NodeValue::Integer(1)));
        assert!(!scope.is_empty());
        assert_eq!(scope.len(), 1);
    }

    #[test]
    fn test_scope_value_is_null() {
        assert!(ScopeValue::from_node(NodeValue::None).is_null());
        assert!(!ScopeValue::from_node(NodeValue::Integer(0)).is_null());
        assert!(!ScopeValue::from_node(NodeValue::Boolean(false)).is_null());
    }
}
