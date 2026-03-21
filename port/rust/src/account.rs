//! Hierarchical account tree (chart of accounts).
//!
//! Ported from ledger's `account.h` / `account.cc`. Each `Account`
//! represents one node in a colon-separated account hierarchy such as
//! `Expenses:Food:Dining`. A single invisible root account (depth 0) sits
//! at the top of the tree; the user-visible top-level accounts are its children.
//!
//! This implementation uses arena-based allocation: all accounts live in a
//! `Vec<Account>` and are referenced by `AccountId` (a `usize` index).
//! This avoids lifetimes and Rc/RefCell while providing O(1) access.

use std::collections::HashMap;
use std::fmt;

// ---------------------------------------------------------------------------
// AccountId
// ---------------------------------------------------------------------------

/// An opaque handle into an account arena (Vec<Account>).
///
/// This is a lightweight, copyable index. All actual account data lives in
/// the arena and is accessed through this id.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AccountId(pub usize);

impl AccountId {
    /// Return the raw index value.
    pub fn index(self) -> usize {
        self.0
    }
}

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

/// A node in the hierarchical chart of accounts.
///
/// Accounts are stored in an arena (`Vec<Account>`). Parent/child
/// relationships use `AccountId` indices rather than references.
#[derive(Debug, Clone)]
pub struct Account {
    /// Local name of this account segment (e.g. "Food").
    pub name: String,
    /// Parent account index, or None for the root.
    pub parent: Option<AccountId>,
    /// Child accounts keyed by name -> AccountId.
    children: HashMap<String, AccountId>,
    /// Depth in the account tree (root = 0).
    pub depth: usize,
    /// Post indices associated with this account.
    pub post_indices: Vec<usize>,
    /// Cached full account path (computed lazily).
    fullname_cache: Option<String>,
    /// Optional descriptive note.
    pub note: Option<String>,
}

impl Account {
    /// Create a new root account (empty name, no parent).
    pub fn new_root() -> Self {
        Self {
            name: String::new(),
            parent: None,
            children: HashMap::new(),
            depth: 0,
            post_indices: Vec::new(),
            fullname_cache: None,
            note: None,
        }
    }

    /// Create a new account with a name and parent.
    pub fn new(name: &str, parent: AccountId, parent_depth: usize) -> Self {
        Self {
            name: name.to_string(),
            parent: Some(parent),
            children: HashMap::new(),
            depth: parent_depth + 1,
            post_indices: Vec::new(),
            fullname_cache: None,
            note: None,
        }
    }

    /// Return true if this account has child accounts.
    pub fn has_children(&self) -> bool {
        !self.children.is_empty()
    }

    /// Return the number of direct children.
    pub fn children_count(&self) -> usize {
        self.children.len()
    }

    /// Get a child account id by name.
    pub fn child(&self, name: &str) -> Option<AccountId> {
        self.children.get(name).copied()
    }

    /// Return an iterator over (name, AccountId) pairs.
    pub fn children_iter(&self) -> impl Iterator<Item = (&str, AccountId)> {
        self.children.iter().map(|(k, v)| (k.as_str(), *v))
    }

    /// Return child AccountIds sorted by name.
    pub fn sorted_children(&self) -> Vec<AccountId> {
        let mut pairs: Vec<_> = self.children.iter().collect();
        pairs.sort_by_key(|(name, _)| (*name).clone());
        pairs.into_iter().map(|(_, id)| *id).collect()
    }

    /// Add a child account id.
    pub(crate) fn add_child(&mut self, name: &str, child_id: AccountId) {
        self.children.insert(name.to_string(), child_id);
    }

    /// Remove a child account by name.
    pub(crate) fn remove_child(&mut self, name: &str) -> bool {
        self.children.remove(name).is_some()
    }

    /// Invalidate the cached fullname.
    pub(crate) fn invalidate_fullname(&mut self) {
        self.fullname_cache = None;
    }
}

// ---------------------------------------------------------------------------
// AccountArena
// ---------------------------------------------------------------------------

/// Arena-based account storage.
///
/// All accounts live in a contiguous `Vec`. Parent/child relationships use
/// `AccountId` indices. This avoids the complexity of Rc<RefCell<>> or
/// lifetime-annotated references.
#[derive(Debug, Clone)]
pub struct AccountArena {
    accounts: Vec<Account>,
}

impl AccountArena {
    /// Create a new arena with a root account (index 0).
    pub fn new() -> Self {
        Self {
            accounts: vec![Account::new_root()],
        }
    }

    /// Return the root account id (always 0).
    pub fn root_id(&self) -> AccountId {
        AccountId(0)
    }

    /// Get a reference to an account by id.
    pub fn get(&self, id: AccountId) -> &Account {
        &self.accounts[id.0]
    }

    /// Get a mutable reference to an account by id.
    pub fn get_mut(&mut self, id: AccountId) -> &mut Account {
        &mut self.accounts[id.0]
    }

    /// Return the total number of accounts in the arena.
    pub fn len(&self) -> usize {
        self.accounts.len()
    }

    /// Return true if the arena is empty (it never truly is due to root).
    pub fn is_empty(&self) -> bool {
        self.accounts.is_empty()
    }

    /// Allocate a new account and return its id.
    fn alloc(&mut self, account: Account) -> AccountId {
        let id = AccountId(self.accounts.len());
        self.accounts.push(account);
        id
    }

    /// Compute the full colon-separated account path.
    ///
    /// The root account (whose name is empty) returns "".
    pub fn fullname(&self, id: AccountId) -> String {
        // Check cache first.
        if let Some(cached) = &self.accounts[id.0].fullname_cache {
            return cached.clone();
        }

        let mut parts: Vec<&str> = Vec::new();
        let mut current = Some(id);
        while let Some(cid) = current {
            let acct = &self.accounts[cid.0];
            if !acct.name.is_empty() {
                parts.push(&acct.name);
            }
            current = acct.parent;
        }
        parts.reverse();
        parts.join(":")
    }

    /// Compute and cache the fullname for the given account.
    pub fn cache_fullname(&mut self, id: AccountId) {
        let name = self.fullname(id);
        self.accounts[id.0].fullname_cache = Some(name);
    }

    /// Look up or create an account by colon-separated path.
    ///
    /// Splits on `:` and walks (or creates) intermediate accounts.
    /// For example, `find_account(root, "Expenses:Food:Dining")` creates
    /// `Expenses`, `Food`, and `Dining` as needed.
    pub fn find_account(&mut self, from: AccountId, path: &str, auto_create: bool) -> Option<AccountId> {
        if path.is_empty() {
            return Some(from);
        }

        // Fast path: direct child lookup (no colon).
        if let Some(child_id) = self.accounts[from.0].child(path) {
            return Some(child_id);
        }

        let sep = path.find(':');
        let (first, rest) = match sep {
            Some(pos) => (&path[..pos], &path[pos + 1..]),
            None => (path, ""),
        };

        if first.is_empty() {
            return None; // empty sub-account name
        }

        let child_id = if let Some(id) = self.accounts[from.0].child(first) {
            id
        } else {
            if !auto_create {
                return None;
            }
            let parent_depth = self.accounts[from.0].depth;
            let new_account = Account::new(first, from, parent_depth);
            let new_id = self.alloc(new_account);
            self.accounts[from.0].add_child(first, new_id);
            new_id
        };

        if rest.is_empty() {
            Some(child_id)
        } else {
            self.find_account(child_id, rest, auto_create)
        }
    }

    /// Depth-first list of all descendant account ids (excluding the given id).
    pub fn flatten(&self, id: AccountId) -> Vec<AccountId> {
        let mut result = Vec::new();
        self.flatten_into(id, &mut result);
        result
    }

    fn flatten_into(&self, id: AccountId, result: &mut Vec<AccountId>) {
        let acct = &self.accounts[id.0];
        for child_id in acct.children.values() {
            result.push(*child_id);
            self.flatten_into(*child_id, result);
        }
    }
}

impl Default for AccountArena {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for AccountArena {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "AccountArena({} accounts)", self.accounts.len())
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arena_has_root() {
        let arena = AccountArena::new();
        assert_eq!(arena.len(), 1);
        let root = arena.get(arena.root_id());
        assert_eq!(root.name, "");
        assert!(root.parent.is_none());
        assert_eq!(root.depth, 0);
        assert!(!root.has_children());
    }

    #[test]
    fn find_account_auto_create() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id = arena.find_account(root, "Expenses", true).unwrap();
        assert_eq!(arena.get(id).name, "Expenses");
        assert_eq!(arena.get(id).depth, 1);
        assert_eq!(arena.get(id).parent, Some(root));
        assert!(arena.get(root).has_children());
    }

    #[test]
    fn find_account_nested() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id = arena.find_account(root, "Expenses:Food:Dining", true).unwrap();
        assert_eq!(arena.get(id).name, "Dining");
        assert_eq!(arena.get(id).depth, 3);

        // Intermediate accounts should exist.
        let expenses_id = arena.find_account(root, "Expenses", false).unwrap();
        assert_eq!(arena.get(expenses_id).name, "Expenses");
        assert_eq!(arena.get(expenses_id).depth, 1);

        let food_id = arena.find_account(root, "Expenses:Food", false).unwrap();
        assert_eq!(arena.get(food_id).name, "Food");
        assert_eq!(arena.get(food_id).depth, 2);
    }

    #[test]
    fn find_account_no_auto_create_returns_none() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let result = arena.find_account(root, "Nonexistent", false);
        assert!(result.is_none());
    }

    #[test]
    fn find_account_reuses_existing() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id1 = arena.find_account(root, "Assets:Checking", true).unwrap();
        let id2 = arena.find_account(root, "Assets:Checking", true).unwrap();
        assert_eq!(id1, id2);
        // Should not have created duplicates.
        assert_eq!(arena.len(), 3); // root + Assets + Checking
    }

    #[test]
    fn fullname() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id = arena.find_account(root, "Expenses:Food:Dining", true).unwrap();
        assert_eq!(arena.fullname(id), "Expenses:Food:Dining");

        let food_id = arena.find_account(root, "Expenses:Food", false).unwrap();
        assert_eq!(arena.fullname(food_id), "Expenses:Food");

        assert_eq!(arena.fullname(root), "");
    }

    #[test]
    fn fullname_caching() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id = arena.find_account(root, "Assets:Bank", true).unwrap();
        arena.cache_fullname(id);
        // Second call should use cache.
        assert_eq!(arena.fullname(id), "Assets:Bank");
    }

    #[test]
    fn flatten_descendants() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        arena.find_account(root, "A:B:C", true).unwrap();
        arena.find_account(root, "A:D", true).unwrap();

        let descendants = arena.flatten(root);
        // root has child A; A has children B and D; B has child C.
        assert_eq!(descendants.len(), 4); // A, B, C, D
    }

    #[test]
    fn account_sorted_children() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        arena.find_account(root, "Zebra", true).unwrap();
        arena.find_account(root, "Apple", true).unwrap();
        arena.find_account(root, "Mango", true).unwrap();

        let sorted = arena.get(root).sorted_children();
        let names: Vec<&str> = sorted
            .iter()
            .map(|id| arena.get(*id).name.as_str())
            .collect();
        assert_eq!(names, vec!["Apple", "Mango", "Zebra"]);
    }

    #[test]
    fn account_remove_child() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        arena.find_account(root, "ToRemove", true).unwrap();
        assert!(arena.get(root).has_children());

        let removed = arena.get_mut(root).remove_child("ToRemove");
        assert!(removed);
        assert!(!arena.get(root).has_children());
    }

    #[test]
    fn account_post_indices() {
        let mut arena = AccountArena::new();
        let root = arena.root_id();

        let id = arena.find_account(root, "Assets", true).unwrap();
        arena.get_mut(id).post_indices.push(0);
        arena.get_mut(id).post_indices.push(1);
        assert_eq!(arena.get(id).post_indices.len(), 2);
    }

    #[test]
    fn display() {
        let arena = AccountArena::new();
        assert_eq!(format!("{}", arena), "AccountArena(1 accounts)");
    }
}
