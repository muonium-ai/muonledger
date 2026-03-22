/// Commodity and CommodityPool for double-entry accounting.
///
/// This module provides the `Commodity` and `CommodityPool` types, a Swift port
/// of Ledger's `commodity_t` and `commodity_pool_t`. Commodities represent
/// currencies, stocks, mutual funds, and any other unit of value. The pool is a
/// registry that manages creation, lookup, and style learning.
///
/// A key design principle (inherited from Ledger) is that display formatting is
/// *learned* from usage: the first time a commodity like "$" is seen with two
/// decimal places and a thousands separator, those style flags are recorded and
/// applied to all future output of that commodity.

import Foundation

// MARK: - CommodityStyle

/// Bit-flags controlling how a commodity is displayed.
///
/// Mirrors the `COMMODITY_STYLE_*` constants from Ledger's `commodity.h`.
public struct CommodityStyle: OptionSet, Sendable {
    public let rawValue: UInt32

    public init(rawValue: UInt32) {
        self.rawValue = rawValue
    }

    public static let defaults             = CommodityStyle([])
    public static let suffixed             = CommodityStyle(rawValue: 0x001)
    public static let separated            = CommodityStyle(rawValue: 0x002)
    public static let decimalComma         = CommodityStyle(rawValue: 0x004)
    public static let thousands            = CommodityStyle(rawValue: 0x008)
    public static let nomarket             = CommodityStyle(rawValue: 0x010)
    public static let builtin              = CommodityStyle(rawValue: 0x020)
    public static let known                = CommodityStyle(rawValue: 0x080)
    public static let thousandsApostrophe  = CommodityStyle(rawValue: 0x4000)
}

// MARK: - Commodity

/// Characters that require a symbol to be quoted (spaces, digits, operators).
private let needsQuotingPattern = try! NSRegularExpression(
    pattern: #"[\s\d+\-*/=<>!@#%^&|?;,.\[\]{}()~]"#
)

/// A commodity (currency / stock / unit of value).
public final class Commodity {
    /// The canonical commodity name (e.g., `"$"`, `"EUR"`, `"AAPL"`).
    public let symbol: String

    /// Number of decimal places for display.
    public var precision: Int

    /// Display style flags.
    public var flags: CommodityStyle

    /// Optional user-supplied note.
    public var note: String?

    public init(
        symbol: String = "",
        precision: Int = 0,
        flags: CommodityStyle = .defaults,
        note: String? = nil
    ) {
        self.symbol = symbol
        self.precision = precision
        self.flags = flags
        self.note = note
    }

    // MARK: Flags

    /// Return `true` if all bits in `flag` are set.
    public func hasFlags(_ flag: CommodityStyle) -> Bool {
        flags.contains(flag)
    }

    /// Set the given flag bits.
    public func addFlags(_ flag: CommodityStyle) {
        flags.insert(flag)
    }

    /// Clear the given flag bits.
    public func dropFlags(_ flag: CommodityStyle) {
        flags.remove(flag)
    }

    // MARK: Derived properties

    /// `true` when the symbol is printed before the quantity.
    public var isPrefix: Bool {
        !hasFlags(.suffixed)
    }

    /// The symbol, quoted if it contains special characters.
    public var qualifiedSymbol: String {
        let range = NSRange(symbol.startIndex..., in: symbol)
        if needsQuotingPattern.firstMatch(in: symbol, range: range) != nil {
            return "\"\(symbol)\""
        }
        return symbol
    }

    /// A commodity is valid unless it is the null commodity (empty symbol).
    public var isValid: Bool {
        !symbol.isEmpty
    }
}

extension Commodity: Equatable {
    public static func == (lhs: Commodity, rhs: Commodity) -> Bool {
        lhs.symbol == rhs.symbol
    }
}

extension Commodity: Hashable {
    public func hash(into hasher: inout Hasher) {
        hasher.combine(symbol)
    }
}

extension Commodity: CustomStringConvertible {
    public var description: String {
        qualifiedSymbol
    }
}

// MARK: - CommodityPool

/// Registry of all known commodities.
///
/// Mirrors Ledger's `commodity_pool_t`. Call `findOrCreate(_:)` to obtain
/// a `Commodity` for a given symbol string.
public final class CommodityPool {
    /// Process-wide default pool.
    public static var current: CommodityPool?

    private var commodities: [String: Commodity] = [:]

    /// Optional default commodity.
    public var defaultCommodity: Commodity?

    /// The null commodity (empty symbol, builtin, nomarket).
    public let nullCommodity: Commodity

    public init() {
        let null = Commodity(
            symbol: "",
            precision: 0,
            flags: [.builtin, .nomarket]
        )
        self.nullCommodity = null
        commodities[""] = null
    }

    // MARK: Lookup / creation

    /// Look up an existing commodity by symbol. Returns `nil` if not found.
    public func find(_ symbol: String) -> Commodity? {
        commodities[symbol]
    }

    /// Create a new commodity and register it in the pool.
    ///
    /// Throws if the symbol already exists.
    @discardableResult
    public func create(
        _ symbol: String,
        precision: Int = 0,
        flags: CommodityStyle = .defaults,
        note: String? = nil
    ) throws -> Commodity {
        if commodities[symbol] != nil {
            throw CommodityError.alreadyExists(symbol)
        }
        let comm = Commodity(symbol: symbol, precision: precision, flags: flags, note: note)
        commodities[symbol] = comm
        return comm
    }

    /// Look up a commodity by symbol, creating it if it does not exist.
    @discardableResult
    public func findOrCreate(_ symbol: String) -> Commodity {
        if let existing = find(symbol) {
            return existing
        }
        // Safe to force-try since we just checked it doesn't exist.
        return try! create(symbol)
    }

    // MARK: Style learning

    /// Record display-style information learned from a parsed amount.
    ///
    /// When an amount like `$1,000.00` is first seen, the parser calls this
    /// method to teach the pool that `$` is a prefix symbol with 2-decimal
    /// precision and comma thousands separators.
    @discardableResult
    public func learnStyle(
        _ symbol: String,
        prefix: Bool = false,
        precision: Int = 0,
        thousands: Bool = false,
        decimalComma: Bool = false,
        separated: Bool = false
    ) -> Commodity {
        let comm = findOrCreate(symbol)

        // Build the learned flag set.
        var learned = CommodityStyle.defaults
        if !prefix {
            learned.insert(.suffixed)
        }
        if separated {
            learned.insert(.separated)
        }
        if thousands {
            learned.insert(.thousands)
        }
        if decimalComma {
            learned.insert(.decimalComma)
        }

        // Merge: flags grow monotonically; precision takes the max.
        comm.addFlags(learned)
        if precision > comm.precision {
            comm.precision = precision
        }

        // If the caller says prefix and SUFFIXED was previously set, drop SUFFIXED.
        if prefix && comm.hasFlags(.suffixed) {
            comm.dropFlags(.suffixed)
        }

        return comm
    }

    // MARK: Iteration / membership

    /// Number of commodities in the pool (including null).
    public var count: Int {
        commodities.count
    }

    /// Check whether a symbol is registered.
    public func contains(_ symbol: String) -> Bool {
        commodities[symbol] != nil
    }

    // MARK: Default pool convenience

    /// Return the current (global) pool, creating one if needed.
    public static func getCurrent() -> CommodityPool {
        if let pool = current {
            return pool
        }
        let pool = CommodityPool()
        current = pool
        return pool
    }

    /// Reset the global pool (useful in tests).
    public static func resetCurrent() {
        current = nil
    }
}

// MARK: - CommodityError

public enum CommodityError: Error, CustomStringConvertible {
    case alreadyExists(String)

    public var description: String {
        switch self {
        case .alreadyExists(let symbol):
            return "Commodity '\(symbol)' already exists in pool"
        }
    }
}
