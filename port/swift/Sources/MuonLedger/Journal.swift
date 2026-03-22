/// Central container for all financial data in a ledger session.
///
/// Ported from ledger's `journal_t`. The Journal owns the account tree
/// (rooted at a master account), all parsed transactions, and account aliases.
///
/// There is exactly one journal per session. Parsing populates it and
/// the reporting engine reads from it.

import Foundation

// MARK: - Journal

/// The central container for all financial data.
public final class Journal {
    /// Root account (invisible, empty name).
    public var master: Account

    /// All regular transactions in parse order.
    public var transactions: [Xact]

    /// Account name aliases.
    public var aliases: [String: String]

    /// Create a new empty journal.
    public init() {
        self.master = Account()
        self.transactions = []
        self.aliases = [:]
    }

    // MARK: Transaction management

    /// Add a transaction to the journal after finalizing it.
    ///
    /// Calls `finalize()` to infer missing amounts and verify balance.
    /// Returns `true` if the transaction was successfully added, `false`
    /// if finalization indicated it should be skipped.
    ///
    /// - Throws: `TransactionError` if the transaction does not balance.
    @discardableResult
    public func addTransaction(_ xact: Xact) throws -> Bool {
        guard try xact.finalize() else { return false }
        transactions.append(xact)
        return true
    }

    // MARK: Account helpers

    /// Look up or create an account by colon-separated path.
    ///
    /// Resolves aliases before lookup. For example, if an alias maps
    /// "Food" to "Expenses:Food", then `findOrCreateAccount("Food")`
    /// returns the `Expenses:Food` account.
    public func findOrCreateAccount(_ name: String) -> Account {
        let resolvedName = aliases[name] ?? name
        return master.findAccount(resolvedName, autoCreate: true)!
    }

    // MARK: Container protocol

    /// Number of transactions in the journal.
    public var count: Int {
        transactions.count
    }

    // MARK: Reset

    /// Reset the journal to its initial (empty) state.
    public func clear() {
        master = Account()
        transactions.removeAll()
        aliases.removeAll()
    }
}
