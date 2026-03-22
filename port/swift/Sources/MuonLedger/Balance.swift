/// Multi-commodity balance for double-entry accounting.
///
/// Ported from ledger's `balance_t`. A balance holds amounts across
/// multiple commodities simultaneously, stored as a dictionary keyed
/// by commodity symbol. Arithmetic operators delegate to per-commodity
/// Amount operations, preserving all precision and rounding rules.

import Foundation

// MARK: - BalanceError

public enum BalanceError: Error, CustomStringConvertible {
    case uninitializedAmount
    case emptyCommodity
    case multipleCommodities

    public var description: String {
        switch self {
        case .uninitializedAmount:
            return "Cannot use an uninitialized amount in a balance"
        case .emptyCommodity:
            return "Cannot convert an empty balance to an amount"
        case .multipleCommodities:
            return "Cannot convert a balance with multiple commodities to an amount"
        }
    }
}

// MARK: - Balance

/// Multi-commodity balance as a dictionary of commodity symbol to Amount.
public struct Balance {
    /// Internal storage: commodity symbol (or "" for uncommoditized) -> Amount.
    private var _amounts: [String: Amount]

    // MARK: Construction

    /// Create an empty balance.
    public init() {
        _amounts = [:]
    }

    /// Create a balance from a single Amount.
    public init(_ amount: Amount) {
        _amounts = [:]
        if !amount.isNull && !amount.isRealZero {
            let key = amount.commoditySymbol ?? ""
            _amounts[key] = amount
        }
    }

    /// Create a balance by copying another balance.
    public init(_ other: Balance) {
        _amounts = other._amounts
    }

    // MARK: Internal helpers

    private static func commodityKey(_ amt: Amount) -> String {
        amt.commoditySymbol ?? ""
    }

    // MARK: Mutating add/subtract

    /// Add a single Amount into this balance (in-place).
    public mutating func add(_ amount: Amount) {
        guard !amount.isNull else { return }
        guard !amount.isRealZero else { return }

        let key = Balance.commodityKey(amount)
        if let existing = _amounts[key] {
            let result = existing + amount
            if result.isRealZero {
                _amounts.removeValue(forKey: key)
            } else {
                _amounts[key] = result
            }
        } else {
            _amounts[key] = amount
        }
    }

    /// Subtract a single Amount from this balance (in-place).
    public mutating func subtract(_ amount: Amount) {
        guard !amount.isNull else { return }
        guard !amount.isRealZero else { return }

        let key = Balance.commodityKey(amount)
        if let existing = _amounts[key] {
            let result = existing - amount
            if result.isRealZero {
                _amounts.removeValue(forKey: key)
            } else {
                _amounts[key] = result
            }
        } else {
            _amounts[key] = amount.negated()
        }
    }

    /// Add another Balance into this balance (in-place).
    public mutating func add(_ other: Balance) {
        for (_, amt) in other._amounts {
            add(amt)
        }
    }

    /// Subtract another Balance from this balance (in-place).
    public mutating func subtract(_ other: Balance) {
        for (_, amt) in other._amounts {
            subtract(amt)
        }
    }

    // MARK: Truth tests

    /// True if no amounts are stored.
    public var isEmpty: Bool {
        _amounts.isEmpty
    }

    /// True if all commodity amounts are zero (at display precision).
    public var isZero: Bool {
        if _amounts.isEmpty { return true }
        return _amounts.values.allSatisfy { $0.isZero }
    }

    /// True if any commodity amount is non-zero.
    public var isNonZero: Bool {
        if _amounts.isEmpty { return false }
        return _amounts.values.contains { $0.isNonZero }
    }

    // MARK: Commodity queries

    /// Number of distinct commodities.
    public var commodityCount: Int {
        _amounts.count
    }

    /// True if exactly one non-zero commodity entry exists.
    public var isSingleCommodity: Bool {
        _amounts.count == 1
    }

    /// Return the Amount if exactly one commodity, else nil.
    public var singleAmount: Amount? {
        guard _amounts.count == 1 else { return nil }
        return _amounts.values.first
    }

    /// Convert to a single Amount.
    ///
    /// Throws if the balance is empty or contains multiple commodities.
    public func toAmount() throws -> Amount {
        if isEmpty {
            throw BalanceError.emptyCommodity
        }
        if _amounts.count == 1 {
            return _amounts.values.first!
        }
        throw BalanceError.multipleCommodities
    }

    /// Read-only access to the internal amounts dictionary.
    public var amounts: [String: Amount] {
        _amounts
    }

    // MARK: Unary operations

    /// Return a negated copy.
    public func negated() -> Balance {
        var result = Balance()
        for (key, amt) in _amounts {
            result._amounts[key] = amt.negated()
        }
        return result
    }

    // MARK: Operators

    public static func + (lhs: Balance, rhs: Amount) -> Balance {
        var result = Balance(lhs)
        result.add(rhs)
        return result
    }

    public static func - (lhs: Balance, rhs: Amount) -> Balance {
        var result = Balance(lhs)
        result.subtract(rhs)
        return result
    }

    public static func + (lhs: Balance, rhs: Balance) -> Balance {
        var result = Balance(lhs)
        result.add(rhs)
        return result
    }

    public static func - (lhs: Balance, rhs: Balance) -> Balance {
        var result = Balance(lhs)
        result.subtract(rhs)
        return result
    }

    public static prefix func - (balance: Balance) -> Balance {
        balance.negated()
    }
}

// MARK: Equatable

extension Balance: Equatable {
    public static func == (lhs: Balance, rhs: Balance) -> Bool {
        lhs._amounts == rhs._amounts
    }
}

// MARK: CustomStringConvertible

extension Balance: CustomStringConvertible {
    public var description: String {
        if _amounts.isEmpty {
            return "0"
        }
        let parts = _amounts.keys.sorted().map { _amounts[$0]!.toString() }
        return parts.joined(separator: "\n")
    }
}
