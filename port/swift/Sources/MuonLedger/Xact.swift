/// Transaction class for ledger journal entries.
///
/// Ported from ledger's `xact_t`. A transaction is a dated entry with a
/// payee and two or more postings that must balance (double-entry invariant).
///
/// The critical method is `finalize()`, which:
/// 1. Scans all postings, sums amounts, tracks nil-amount postings
/// 2. Infers the missing amount if exactly one posting has nil amount
/// 3. Verifies that the transaction balances (sum equals zero)

import Foundation

// MARK: - TransactionError

public enum TransactionError: Error, CustomStringConvertible {
    case doesNotBalance(String)
    case multipleNullPostings(String)

    public var description: String {
        switch self {
        case .doesNotBalance(let msg):
            return msg
        case .multipleNullPostings(let msg):
            return msg
        }
    }
}

// MARK: - Xact (Transaction)

/// A regular dated transaction -- the primary journal entry.
///
/// In journal syntax:
/// ```
/// 2024/01/15 * Grocery Store
///     Expenses:Food       $42.50
///     Assets:Checking
/// ```
public final class Xact: Item {
    /// The payee/description of the transaction.
    public var payee: String

    /// List of postings in this transaction.
    public var posts: [Post]

    /// Optional transaction code (e.g. check number).
    public var code: String?

    public init(
        payee: String = "",
        flags: ItemFlags = .normal,
        note: String? = nil
    ) {
        self.payee = payee
        self.posts = []
        self.code = nil
        super.init(flags: flags, note: note)
    }

    // MARK: Post management

    /// Add a posting to this transaction and set its back-reference.
    public func addPost(_ post: Post) {
        post.xact = self
        posts.append(post)
    }

    /// Remove a posting from this transaction.
    @discardableResult
    public func removePost(_ post: Post) -> Bool {
        guard let idx = posts.firstIndex(where: { $0 === post }) else {
            return false
        }
        posts.remove(at: idx)
        post.xact = nil
        return true
    }

    // MARK: Finalize

    /// Balance-check and infer nil amounts within a single posting group.
    private func finalizeGroup(
        _ posts: [Post],
        groupLabel: String
    ) throws {
        var balance = Value.empty
        var nullPost: Post? = nil

        for post in posts {
            // Use cost if available, otherwise the posting amount.
            let amt = post.cost ?? post.amount

            if let a = amt, !a.isNull {
                let reduced = a.keepPrecision ? a.rounded() : a
                balance = balance.add(Value(reduced))
            } else if nullPost != nil {
                throw TransactionError.multipleNullPostings(
                    "Only one posting with null amount allowed per \(groupLabel) group"
                )
            } else {
                nullPost = post
            }
        }

        // Infer nil-amount posting.
        if let np = nullPost {
            if balance.isNull || balance.isRealZero {
                np.amount = Amount(0)
            } else {
                let negBalance = -balance
                np.amount = try negBalance.toAmount()
            }
            np.postFlags.insert(.calculated)
            np.addFlags(.inferred)
            balance = .empty
        }

        // Final balance verification.
        // When a transaction has postings in multiple commodities and every
        // posting has an explicit amount (no null-amount posting), ledger
        // treats it as an implicit exchange and considers it balanced.
        if !balance.isNull && !balance.isZero {
            let isMultiCommodity = balance.isBalance && nullPost == nil
            if !isMultiCommodity {
                throw TransactionError.doesNotBalance(
                    "Transaction does not balance (\(groupLabel) postings): remainder is \(balance)"
                )
            }
        }
    }

    /// Finalize the transaction: infer amounts and check balance.
    ///
    /// This is the core of double-entry accounting enforcement. Called
    /// after all postings have been added. The algorithm handles three
    /// separate balancing groups:
    ///
    /// 1. **Real postings** -- regular account postings must balance to zero.
    /// 2. **Balanced virtual postings** `[Account]` -- must balance to zero
    ///    among themselves, independently from real postings.
    /// 3. **Virtual postings** `(Account)` -- not checked for balance at all.
    ///
    /// - Returns: `true` if the transaction is valid, `false` if all amounts
    ///   are nil (indicating the transaction should be ignored).
    /// - Throws: `TransactionError` if postings do not balance or if a group
    ///   has multiple nil-amount postings.
    @discardableResult
    public func finalize() throws -> Bool {
        // Reject transactions with no postings
        guard !posts.isEmpty else { return false }

        // Handle lot annotations: derive cost from lot price
        for post in posts {
            if let lotPrice = post.lotPrice, post.cost == nil, let amt = post.amount {
                // cost = |quantity| * lot_price
                let absQty = amt.abs().number()
                post.cost = absQty * lotPrice
            }
        }

        // Partition postings into three groups
        var realPosts: [Post] = []
        var balancedVirtualPosts: [Post] = []
        // Plain virtual postings are not balance-checked

        for post in posts {
            if post.postFlags.contains(.virtual) {
                if post.postFlags.contains(.mustBalance) {
                    balancedVirtualPosts.append(post)
                }
                // else: plain virtual -- skip balance checking
            } else {
                realPosts.append(post)
            }
        }

        // Balance each group independently
        if !realPosts.isEmpty {
            try finalizeGroup(realPosts, groupLabel: "real")
        }
        if !balancedVirtualPosts.isEmpty {
            try finalizeGroup(balancedVirtualPosts, groupLabel: "balanced virtual")
        }

        // Check if all amounts were nil (degenerate transaction)
        let allNull = posts.allSatisfy { post in
            post.amount == nil || post.amount!.isNull
        }
        if allNull && !posts.isEmpty {
            return false
        }

        return true
    }
}
