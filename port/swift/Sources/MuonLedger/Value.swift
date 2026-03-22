/// Polymorphic value type for the expression engine.
///
/// Ported from ledger's `value_t`. A Value wraps either nothing (empty),
/// a single Amount, or a multi-commodity Balance, and performs automatic
/// type promotion during arithmetic.
///
/// The promotion hierarchy for numeric operations is:
///     empty -> Amount -> Balance

import Foundation

// MARK: - ValueError

public enum ValueError: Error, CustomStringConvertible {
    case cannotConvert(String, String)

    public var description: String {
        switch self {
        case .cannotConvert(let from, let to):
            return "Cannot convert \(from) to \(to)"
        }
    }
}

// MARK: - Value

/// Polymorphic value: empty, single-commodity Amount, or multi-commodity Balance.
public enum Value {
    case empty
    case amount(Amount)
    case balance(Balance)

    // MARK: Construction helpers

    /// Create a Value from an Amount.
    public init(_ amount: Amount) {
        self = .amount(amount)
    }

    /// Create a Value from a Balance.
    public init(_ balance: Balance) {
        self = .balance(balance)
    }

    // MARK: Truth tests

    /// True if this value is empty (void).
    public var isNull: Bool {
        if case .empty = self { return true }
        return false
    }

    /// True if the value is zero or empty.
    public var isZero: Bool {
        switch self {
        case .empty:
            return true
        case .amount(let a):
            return a.isZero
        case .balance(let b):
            return b.isZero
        }
    }

    /// True if the value is exactly zero (no display-precision rounding).
    public var isRealZero: Bool {
        switch self {
        case .empty:
            return true
        case .amount(let a):
            return a.isRealZero
        case .balance(let b):
            return b.isEmpty || b.isZero
        }
    }

    /// True if non-zero.
    public var isNonZero: Bool {
        !isZero
    }

    /// Whether this value holds a Balance (multi-commodity).
    public var isBalance: Bool {
        if case .balance = self { return true }
        return false
    }

    // MARK: Conversion

    /// Convert to an Amount. Throws if multi-commodity balance.
    public func toAmount() throws -> Amount {
        switch self {
        case .empty:
            return Amount(0)
        case .amount(let a):
            return a
        case .balance(let b):
            return try b.toAmount()
        }
    }

    // MARK: Arithmetic

    /// Add another Value to this one, with auto-promotion.
    public func add(_ other: Value) -> Value {
        switch (self, other) {
        case (.empty, _):
            return other
        case (_, .empty):
            return self

        case (.amount(let a), .amount(let b)):
            // Same commodity or one uncommoditized: stay as Amount
            if !a.hasCommodity || !b.hasCommodity ||
               a.commoditySymbol == b.commoditySymbol {
                return .amount(a + b)
            }
            // Different commodities: promote to Balance
            var bal = Balance(a)
            bal.add(b)
            return .balance(bal)

        case (.amount(let a), .balance(let b)):
            var result = Balance(b)
            result.add(a)
            return .balance(result)

        case (.balance(let a), .amount(let b)):
            var result = Balance(a)
            result.add(b)
            return .balance(result)

        case (.balance(let a), .balance(let b)):
            return .balance(a + b)
        }
    }

    /// Subtract another Value from this one, with auto-promotion.
    public func subtract(_ other: Value) -> Value {
        switch (self, other) {
        case (.empty, _):
            return other.negated()
        case (_, .empty):
            return self

        case (.amount(let a), .amount(let b)):
            if !a.hasCommodity || !b.hasCommodity ||
               a.commoditySymbol == b.commoditySymbol {
                return .amount(a - b)
            }
            var bal = Balance(a)
            bal.subtract(b)
            return .balance(bal)

        case (.amount(let a), .balance(let b)):
            var result = Balance(a)
            result.subtract(b)
            return .balance(result)

        case (.balance(let a), .amount(let b)):
            var result = Balance(a)
            result.subtract(b)
            return .balance(result)

        case (.balance(let a), .balance(let b)):
            return .balance(a - b)
        }
    }

    /// Negate this value.
    public func negated() -> Value {
        switch self {
        case .empty:
            return .empty
        case .amount(let a):
            return .amount(a.negated())
        case .balance(let b):
            return .balance(b.negated())
        }
    }

    // MARK: Operators

    public static func + (lhs: Value, rhs: Value) -> Value {
        lhs.add(rhs)
    }

    public static func - (lhs: Value, rhs: Value) -> Value {
        lhs.subtract(rhs)
    }

    public static prefix func - (value: Value) -> Value {
        value.negated()
    }
}

// MARK: CustomStringConvertible

extension Value: CustomStringConvertible {
    public var description: String {
        switch self {
        case .empty:
            return ""
        case .amount(let a):
            return a.toString()
        case .balance(let b):
            return b.description
        }
    }
}
