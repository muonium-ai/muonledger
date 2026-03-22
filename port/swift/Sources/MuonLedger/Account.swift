/// Hierarchical account tree (chart of accounts).
///
/// Ported from ledger's `account.h` / `account.cc`. Each `Account`
/// represents one node in a colon-separated account hierarchy such as
/// `Expenses:Food:Dining`. A single invisible root account (depth 0) sits
/// at the top of the tree; the user-visible top-level accounts are its children.

import Foundation

// MARK: - Account

/// A node in the hierarchical chart of accounts.
///
/// Uses class semantics (reference type) so that parent/child relationships
/// work naturally with weak references avoiding retain cycles.
public final class Account {
    /// Local name of this account segment (e.g. "Food").
    public let name: String

    /// Parent account, or nil for the root.
    public weak var parent: Account?

    /// Child accounts keyed by name.
    private var _children: [String: Account] = [:]

    /// Depth in the account tree (root = 0).
    public let depth: Int

    /// Posts associated with this account.
    public var posts: [Any] = []

    /// Cached full account path (computed lazily).
    private var _fullname: String?

    /// Optional descriptive note.
    public var note: String?

    // MARK: Initialization

    /// Create a new account node.
    ///
    /// - Parameters:
    ///   - parent: Parent account, or nil for the root.
    ///   - name: Local name of this account segment.
    ///   - note: Optional descriptive note.
    public init(parent: Account? = nil, name: String = "", note: String? = nil) {
        self.name = name
        self.parent = parent
        self.depth = parent != nil ? parent!.depth + 1 : 0
        self.note = note
    }

    // MARK: Properties

    /// Colon-separated full account path.
    ///
    /// The root account (whose name is empty) returns "".
    public var fullname: String {
        if let cached = _fullname {
            return cached
        }

        var parts: [String] = []
        var node: Account? = self
        while let current = node {
            if !current.name.isEmpty {
                parts.append(current.name)
            }
            node = current.parent
        }
        parts.reverse()
        let result = parts.joined(separator: ":")
        _fullname = result
        return result
    }

    /// Read-only access to child accounts keyed by name.
    public var children: [String: Account] {
        _children
    }

    /// Whether this account has any child accounts.
    public var hasChildren: Bool {
        !_children.isEmpty
    }

    /// Number of direct children.
    public var childCount: Int {
        _children.count
    }

    // MARK: Tree manipulation

    /// Insert `child` as a direct child of this account.
    public func addAccount(_ child: Account) {
        // Note: since Account is a class, we update the child's reference.
        // depth and parent are let properties, so we need to create through init.
        // Instead, we store the child directly and trust it was created properly.
        child.invalidateFullname()
        _children[child.name] = child
    }

    /// Remove `child` from this account's children.
    ///
    /// Returns `true` if the child was present and removed.
    @discardableResult
    public func removeAccount(_ child: Account) -> Bool {
        if let existing = _children[child.name], existing === child {
            _children.removeValue(forKey: child.name)
            return true
        }
        return false
    }

    /// Look up or create an account by colon-separated path.
    ///
    /// Splits on ":" and walks (or creates) intermediate accounts.
    /// For example, `root.findAccount("Expenses:Food:Dining")` creates
    /// `Expenses`, `Food`, and `Dining` as needed.
    ///
    /// If `autoCreate` is false, returns nil when any segment does not exist.
    public func findAccount(_ path: String, autoCreate: Bool = true) -> Account? {
        // Fast path: direct child lookup (no colon)
        if let existing = _children[path] {
            return existing
        }

        let first: String
        let rest: String
        if let sepIndex = path.firstIndex(of: ":") {
            first = String(path[path.startIndex..<sepIndex])
            rest = String(path[path.index(after: sepIndex)...])
        } else {
            first = path
            rest = ""
        }

        guard !first.isEmpty else {
            return nil // empty sub-account name
        }

        var account = _children[first]
        if account == nil {
            if !autoCreate {
                return nil
            }
            let newAccount = Account(parent: self, name: first)
            _children[first] = newAccount
            account = newAccount
        }

        if rest.isEmpty {
            return account
        }
        return account!.findAccount(rest, autoCreate: autoCreate)
    }

    // MARK: Posts

    /// Append a posting reference to this account.
    public func addPost(_ post: Any) {
        posts.append(post)
    }

    // MARK: Traversal helpers

    /// Depth-first list of all descendant accounts (excluding self).
    public func flatten() -> [Account] {
        var result: [Account] = []
        flattenInto(&result)
        return result
    }

    private func flattenInto(_ result: inout [Account]) {
        for child in _children.values {
            result.append(child)
            child.flattenInto(&result)
        }
    }

    /// Return direct children sorted by name.
    public func sortedChildren() -> [Account] {
        _children.values.sorted { $0.name < $1.name }
    }

    // MARK: Internal helpers

    /// Clear cached fullname for this node and all descendants.
    private func invalidateFullname() {
        _fullname = nil
        for child in _children.values {
            child.invalidateFullname()
        }
    }
}

// MARK: CustomStringConvertible

extension Account: CustomStringConvertible {
    public var description: String {
        fullname
    }
}
