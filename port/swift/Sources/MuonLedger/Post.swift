/// Posting: a line item within a transaction that debits or credits an account.
///
/// Ported from ledger's `post_t`. Each transaction contains one or more
/// postings, and each posting records a change to a specific account.

import Foundation

// MARK: - PostFlags

/// Bit flags specific to postings.
public struct PostFlags: OptionSet {
    public let rawValue: UInt32

    public init(rawValue: UInt32) {
        self.rawValue = rawValue
    }

    public static let virtual         = PostFlags(rawValue: 0x0010)
    public static let mustBalance     = PostFlags(rawValue: 0x0020)
    public static let calculated      = PostFlags(rawValue: 0x0040)
    public static let costCalculated  = PostFlags(rawValue: 0x0080)
    public static let costInFull      = PostFlags(rawValue: 0x0100)
    public static let costFixated     = PostFlags(rawValue: 0x0200)
    public static let costVirtual     = PostFlags(rawValue: 0x0400)
}

// MARK: - Post

/// A single posting within a transaction.
public final class Post: Item {
    /// The target account this posting debits or credits.
    public var account: Account?

    /// The posting amount; nil until finalization infers it.
    public var amount: Amount?

    /// Cost amount from `@ price` or `@@ total`.
    public var cost: Amount?

    /// Balance assertion amount from `= $X`.
    public var assignedAmount: Amount?

    /// Lot annotation price from `{$150.00}`.
    public var lotPrice: Amount?

    /// Whether this is a virtual posting `(Account)`.
    public var isVirtual: Bool {
        postFlags.contains(.virtual) && !postFlags.contains(.mustBalance)
    }

    /// Whether this is a balance-virtual posting `[Account]`.
    public var isBalanceVirtual: Bool {
        postFlags.contains(.virtual) && postFlags.contains(.mustBalance)
    }

    /// Post-specific flags (separate from Item flags).
    public var postFlags: PostFlags

    /// Back-reference to the owning transaction.
    public weak var xact: Xact?

    /// Create a new posting.
    public init(
        account: Account? = nil,
        amount: Amount? = nil,
        flags: ItemFlags = .normal,
        note: String? = nil
    ) {
        self.account = account
        self.amount = amount
        self.cost = nil
        self.assignedAmount = nil
        self.lotPrice = nil
        self.postFlags = PostFlags([])
        self.xact = nil
        super.init(flags: flags, note: note)
    }

    /// Whether this posting participates in balance checking.
    ///
    /// Plain virtual postings `(Account)` do not need to balance.
    /// Real postings and balanced-virtual postings `[Account]` must.
    public var mustBalance: Bool {
        if postFlags.contains(.virtual) {
            return postFlags.contains(.mustBalance)
        }
        return true
    }

    /// Make this a virtual posting (parenthesized account).
    public func makeVirtual() {
        postFlags.insert(.virtual)
    }

    /// Make this a balance-virtual posting (bracketed account).
    public func makeBalanceVirtual() {
        postFlags.insert(.virtual)
        postFlags.insert(.mustBalance)
    }
}
