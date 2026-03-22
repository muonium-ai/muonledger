/// Exact-precision commoditized amounts for double-entry accounting.
///
/// This module provides the `Amount` struct, a Swift port of Ledger's
/// `amount_t` type. It uses Foundation's `Decimal` for exact decimal
/// arithmetic so that addition, subtraction, and multiplication never
/// introduce rounding error within the decimal domain.

import Foundation

// MARK: - AmountError

public enum AmountError: Error, CustomStringConvertible {
    case uninitializedAmount
    case noQuantity(String)
    case cannotParse(String, String)
    case divideByZero
    case commodityMismatch(String, String, String)

    public var description: String {
        switch self {
        case .uninitializedAmount:
            return "Cannot use an uninitialized amount"
        case .noQuantity(let text):
            return "No quantity specified for amount: '\(text)'"
        case .cannotParse(let value, let text):
            return "Cannot parse numeric value: '\(value)'\n  While parsing: '\(text)'"
        case .divideByZero:
            return "Divide by zero"
        case .commodityMismatch(let op, let lhs, let rhs):
            return "\(op) amounts with different commodities: '\(lhs)' and '\(rhs)'"
        }
    }
}

// MARK: - ParsedStyle

/// Display style hints extracted during parsing.
struct ParsedStyle {
    var isPrefix: Bool = false
    var isSeparated: Bool = false
    var useThousands: Bool = false
    var useDecimalComma: Bool = false
}

// MARK: - Parsing helpers

/// Count the number of decimal digits after the decimal point.
private func countDecimalPlaces(_ s: String) -> Int {
    guard let dotIndex = s.firstIndex(of: ".") else { return 0 }
    return s.distance(from: s.index(after: dotIndex), to: s.endIndex)
}

/// Parse an amount string into (quantity, precision, commodity, style).
private func parseAmountString(
    _ text: String,
    pool: CommodityPool? = nil
) throws -> (Decimal, Int, Commodity?, ParsedStyle) {
    let originalText = text
    var rest = text.trimmingCharacters(in: .whitespaces)

    guard !rest.isEmpty else {
        throw AmountError.noQuantity(originalText)
    }

    var style = ParsedStyle()
    var commoditySymbol: String? = nil
    var negative = false

    // Handle leading sign
    if rest.hasPrefix("-") {
        negative = true
        rest = String(rest.dropFirst()).trimmingCharacters(in: .whitespaces)
    } else if rest.hasPrefix("+") {
        rest = String(rest.dropFirst()).trimmingCharacters(in: .whitespaces)
    }

    guard !rest.isEmpty else {
        throw AmountError.noQuantity(originalText)
    }

    let firstChar = rest.first!

    if !firstChar.isNumber && firstChar != "." {
        // Prefix commodity: scan non-digit, non-sign chars
        var symEnd = rest.startIndex
        if rest.hasPrefix("\"") {
            // Quoted symbol
            if let closeQuote = rest.dropFirst().firstIndex(of: "\"") {
                symEnd = rest.index(after: closeQuote)
                let rawSym = String(rest[rest.startIndex..<symEnd])
                commoditySymbol = String(rawSym.dropFirst().dropLast()) // strip quotes
            }
        } else {
            // Unquoted symbol: scan until digit, whitespace, sign, dot, comma
            symEnd = rest.startIndex
            for ch in rest {
                if ch.isNumber || ch.isWhitespace || ch == "-" || ch == "+" ||
                   ch == "." || ch == "," || ch == "'" || ch == "\"" {
                    break
                }
                symEnd = rest.index(after: symEnd)
            }
            commoditySymbol = String(rest[rest.startIndex..<symEnd])
        }
        rest = String(rest[symEnd...])
        if rest.hasPrefix(" ") {
            style.isSeparated = true
            rest = rest.trimmingCharacters(in: .whitespaces)
        }
        style.isPrefix = true
    } else {
        // Number comes first; commodity may be suffix
        var numEnd = rest.startIndex
        for ch in rest {
            if "0123456789.,-'".contains(ch) {
                numEnd = rest.index(after: numEnd)
            } else {
                break
            }
        }
        let suffixPart = String(rest[numEnd...])
        rest = String(rest[rest.startIndex..<numEnd])

        if !suffixPart.isEmpty {
            var suffix = suffixPart
            if suffix.hasPrefix(" ") {
                style.isSeparated = true
                suffix = suffix.trimmingCharacters(in: .whitespaces)
            }
            if !suffix.isEmpty {
                // Strip quotes if present
                if suffix.hasPrefix("\"") && suffix.hasSuffix("\"") && suffix.count >= 2 {
                    commoditySymbol = String(suffix.dropFirst().dropLast())
                } else {
                    commoditySymbol = suffix
                }
            }
        }
    }

    // Now parse the numeric part
    let numericStr = rest.trimmingCharacters(in: .whitespaces)

    guard !numericStr.isEmpty else {
        throw AmountError.noQuantity(originalText)
    }

    let hasComma = numericStr.contains(",")
    let hasPeriod = numericStr.contains(".")
    let hasApostrophe = numericStr.contains("'")

    var clean = numericStr
    var decimalPlaces = 0

    if hasComma && hasPeriod {
        let lastComma = numericStr.lastIndex(of: ",")!
        let lastPeriod = numericStr.lastIndex(of: ".")!
        if lastPeriod > lastComma {
            // Period is decimal mark, comma is thousands
            style.useThousands = true
            clean = numericStr.replacingOccurrences(of: ",", with: "")
            decimalPlaces = countDecimalPlaces(clean)
        } else {
            // Comma is decimal mark, period is thousands
            style.useThousands = true
            style.useDecimalComma = true
            clean = numericStr.replacingOccurrences(of: ".", with: "")
                .replacingOccurrences(of: ",", with: ".")
            decimalPlaces = countDecimalPlaces(clean)
        }
    } else if hasComma {
        let lastComma = numericStr.lastIndex(of: ",")!
        let afterComma = String(numericStr[numericStr.index(after: lastComma)...])
        let commaCount = numericStr.filter { $0 == "," }.count

        if commaCount > 1 {
            // Multiple commas = thousands separators
            style.useThousands = true
            clean = numericStr.replacingOccurrences(of: ",", with: "")
            decimalPlaces = 0
        } else if afterComma.count != 3 {
            // Not exactly 3 digits after = decimal comma
            style.useDecimalComma = true
            clean = numericStr.replacingOccurrences(of: ",", with: ".")
            decimalPlaces = afterComma.count
        } else {
            let firstComma = numericStr.firstIndex(of: ",")!
            let intPart = String(numericStr[numericStr.startIndex..<firstComma])
            let stripped = intPart.trimmingCharacters(in: CharacterSet(charactersIn: "-"))
            if stripped == "0" {
                // 0,xxx = decimal comma
                style.useDecimalComma = true
                clean = numericStr.replacingOccurrences(of: ",", with: ".")
                decimalPlaces = afterComma.count
            } else {
                // Ambiguous: 3 digits after single comma. Treat as thousands.
                style.useThousands = true
                clean = numericStr.replacingOccurrences(of: ",", with: "")
                decimalPlaces = 0
            }
        }
    } else if hasPeriod {
        clean = numericStr
        decimalPlaces = countDecimalPlaces(clean)
    } else if hasApostrophe {
        style.useThousands = true
        clean = numericStr.replacingOccurrences(of: "'", with: "")
        decimalPlaces = 0
    } else {
        clean = numericStr
        decimalPlaces = 0
    }

    if hasApostrophe {
        clean = clean.replacingOccurrences(of: "'", with: "")
    }

    guard let quantity = Decimal(string: clean) else {
        throw AmountError.cannotParse(clean, originalText)
    }

    let finalQuantity = negative ? -quantity : quantity

    // Resolve commodity through the pool
    var commodityObj: Commodity? = nil
    if let sym = commoditySymbol {
        let resolvedPool = pool ?? CommodityPool.getCurrent()
        commodityObj = resolvedPool.learnStyle(
            sym,
            prefix: style.isPrefix,
            precision: decimalPlaces,
            thousands: style.useThousands,
            decimalComma: style.useDecimalComma,
            separated: style.isSeparated
        )
    }

    return (finalQuantity, decimalPlaces, commodityObj, style)
}

// MARK: - Amount

/// Exact-precision commoditized amount.
///
/// Uses Foundation's `Decimal` for internal storage, providing exact decimal
/// arithmetic matching Ledger's `amount_t`.
public struct Amount {
    /// Extra decimal places added on division to avoid precision loss.
    public static let extendByDigits = 6

    private var _quantity: Decimal?
    private var _precision: Int
    private var _commodity: Commodity?
    private var _style: ParsedStyle
    private var _keepPrecision: Bool

    // MARK: Construction

    /// Create a null/uninitialized amount.
    public init() {
        _quantity = nil
        _precision = 0
        _commodity = nil
        _style = ParsedStyle()
        _keepPrecision = false
    }

    /// Create an amount from a Decimal value with optional commodity.
    public init(_ value: Decimal, precision: Int = 0, commodity: Commodity? = nil) {
        _quantity = value
        _precision = precision
        _commodity = commodity
        _style = ParsedStyle()
        _keepPrecision = false
    }

    /// Create an amount from an integer with optional commodity.
    public init(_ value: Int, commodity: Commodity? = nil) {
        _quantity = Decimal(value)
        _precision = 0
        _commodity = commodity
        _style = ParsedStyle()
        _keepPrecision = false
    }

    /// Create an amount from a Double with optional commodity.
    public init(_ value: Double, commodity: Commodity? = nil) {
        _quantity = Decimal(value)
        _precision = Amount.extendByDigits
        _commodity = commodity
        _style = ParsedStyle()
        _keepPrecision = false
    }

    /// Parse an amount from a string (e.g. "$50.00", "100 EUR").
    public init(parsing text: String, pool: CommodityPool? = nil) throws {
        let (q, prec, comm, style) = try parseAmountString(text, pool: pool)
        _quantity = q
        _precision = prec
        _commodity = comm
        _style = style
        _keepPrecision = false
    }

    /// Create an amount that keeps full parsed precision for display.
    public static func exact(_ text: String, pool: CommodityPool? = nil) throws -> Amount {
        var amt = try Amount(parsing: text, pool: pool)
        amt._keepPrecision = true
        return amt
    }

    // MARK: Null / truth tests

    /// True if no value has been set (uninitialised).
    public var isNull: Bool {
        _quantity == nil
    }

    private func requireQuantity() throws -> Decimal {
        guard let q = _quantity else {
            throw AmountError.uninitializedAmount
        }
        return q
    }

    /// True if the exact value is zero.
    public var isRealZero: Bool {
        guard let q = _quantity else { return false }
        return q == Decimal.zero
    }

    /// True if the amount displays as zero at its display precision.
    public var isZero: Bool {
        guard let q = _quantity else { return false }
        if q == Decimal.zero { return true }
        let dp = displayPrecision
        let rounded = roundDecimal(q, places: dp)
        return rounded == Decimal.zero
    }

    /// True if the amount is non-zero.
    public var isNonZero: Bool {
        !isZero
    }

    /// True if negative.
    public var isNegative: Bool {
        sign < 0
    }

    /// True if positive.
    public var isPositive: Bool {
        sign > 0
    }

    /// Return -1, 0, or 1.
    public var sign: Int {
        guard let q = _quantity else { return 0 }
        if q > Decimal.zero { return 1 }
        if q < Decimal.zero { return -1 }
        return 0
    }

    // MARK: Properties

    /// The raw Decimal value.
    public var quantity: Decimal {
        _quantity ?? Decimal.zero
    }

    /// The commodity symbol string, or nil.
    public var commoditySymbol: String? {
        _commodity?.symbol
    }

    /// The underlying Commodity object.
    public var commodity: Commodity? {
        get { _commodity }
        set { _commodity = newValue }
    }

    /// Whether this amount has a non-empty commodity.
    public var hasCommodity: Bool {
        _commodity != nil && !_commodity!.symbol.isEmpty
    }

    /// The internal precision.
    public var precision: Int {
        _precision
    }

    /// Whether keep_precision is set.
    public var keepPrecision: Bool {
        _keepPrecision
    }

    /// The precision used for display output.
    public var displayPrecision: Int {
        if _keepPrecision {
            return _precision
        }
        if let comm = _commodity, !comm.symbol.isEmpty, comm.precision > 0 {
            return comm.precision
        }
        // For commodity-less amounts, if the value is a whole number,
        // display as integer.
        if _commodity == nil || _commodity!.symbol.isEmpty {
            if let q = _quantity, q == roundDecimal(q, places: 0) {
                return 0
            }
        }
        return _precision
    }

    // MARK: Unary operations

    /// Return a negated copy.
    public func negated() -> Amount {
        var result = self
        if let q = result._quantity {
            result._quantity = -q
        }
        return result
    }

    /// Return the absolute value.
    public func abs() -> Amount {
        if sign < 0 {
            return negated()
        }
        return self
    }

    /// Negate in place.
    public mutating func negate() {
        if let q = _quantity {
            _quantity = -q
        }
    }

    // MARK: Prefix operators

    public static prefix func - (amount: Amount) -> Amount {
        amount.negated()
    }

    public static prefix func + (amount: Amount) -> Amount {
        amount
    }

    // MARK: Rounding

    /// Return a copy with keep_precision cleared.
    public func rounded() -> Amount {
        var result = self
        result._keepPrecision = false
        return result
    }

    /// Return a copy rounded to the given number of decimal places.
    public func roundedTo(_ places: Int) -> Amount {
        var result = self
        if let q = result._quantity {
            result._quantity = roundDecimal(q, places: places)
            result._precision = max(places, 0)
        }
        return result
    }

    /// Return a copy with keep_precision set (shows full internal precision).
    public func unrounded() -> Amount {
        var result = self
        result._keepPrecision = true
        return result
    }

    /// Return a copy with the commodity stripped.
    public func number() -> Amount {
        var result = self
        result._commodity = nil
        return result
    }

    /// Remove the commodity from this amount (in-place).
    public mutating func clearCommodity() {
        _commodity = nil
    }

    // MARK: Comparison

    /// Three-way comparison.
    public func compare(_ other: Amount) throws -> Int {
        let lq = try requireQuantity()
        let rq = try other.requireQuantity()

        if hasCommodity && other.hasCommodity && _commodity != other._commodity {
            throw AmountError.commodityMismatch(
                "Comparing",
                commoditySymbol ?? "",
                other.commoditySymbol ?? ""
            )
        }

        if lq < rq { return -1 }
        if lq > rq { return 1 }
        return 0
    }

    // MARK: Arithmetic

    public static func + (lhs: Amount, rhs: Amount) -> Amount {
        var result = lhs
        let lq = lhs._quantity ?? Decimal.zero
        let rq = rhs._quantity ?? Decimal.zero
        result._quantity = lq + rq
        result._precision = max(lhs._precision, rhs._precision)
        if !lhs.hasCommodity && rhs.hasCommodity {
            result._commodity = rhs._commodity
            result._style = rhs._style
        }
        return result
    }

    public static func - (lhs: Amount, rhs: Amount) -> Amount {
        var result = lhs
        let lq = lhs._quantity ?? Decimal.zero
        let rq = rhs._quantity ?? Decimal.zero
        result._quantity = lq - rq
        result._precision = max(lhs._precision, rhs._precision)
        if !lhs.hasCommodity && rhs.hasCommodity {
            result._commodity = rhs._commodity
            result._style = rhs._style
        }
        return result
    }

    /// Multiply by a scalar amount.
    public static func * (lhs: Amount, rhs: Amount) -> Amount {
        var result = lhs
        let lq = lhs._quantity ?? Decimal.zero
        let rq = rhs._quantity ?? Decimal.zero
        result._quantity = lq * rq
        result._precision = lhs._precision + rhs._precision
        if !lhs.hasCommodity && rhs.hasCommodity {
            result._commodity = rhs._commodity
            result._style = rhs._style
        }
        return result
    }

    /// Multiply by an integer scalar.
    public static func * (lhs: Amount, rhs: Int) -> Amount {
        var result = lhs
        let lq = lhs._quantity ?? Decimal.zero
        result._quantity = lq * Decimal(rhs)
        return result
    }

    /// Multiply by a Decimal scalar.
    public static func * (lhs: Amount, rhs: Decimal) -> Amount {
        var result = lhs
        let lq = lhs._quantity ?? Decimal.zero
        result._quantity = lq * rhs
        return result
    }

    // MARK: Conversion

    /// Return the value as a Double.
    public var doubleValue: Double {
        guard let q = _quantity else { return 0.0 }
        return NSDecimalNumber(decimal: q).doubleValue
    }

    /// Return the value as an Int (rounded).
    public var intValue: Int {
        guard let q = _quantity else { return 0 }
        return NSDecimalNumber(decimal: roundDecimal(q, places: 0)).intValue
    }

    // MARK: Formatting

    private var useThousands: Bool {
        if let comm = _commodity, comm.hasFlags(.thousands) {
            return true
        }
        return _style.useThousands
    }

    private var useDecimalComma: Bool {
        if let comm = _commodity, comm.hasFlags(.decimalComma) {
            return true
        }
        return _style.useDecimalComma
    }

    /// Format the numeric part to the given number of decimal places.
    private func formatQuantity(_ prec: Int) -> String {
        guard let q = _quantity else { return "<null>" }

        let rounded = roundDecimal(q, places: max(prec, 0))
        let isNeg = rounded < Decimal.zero
        let absVal = isNeg ? -rounded : rounded

        if prec <= 0 {
            let intVal = NSDecimalNumber(decimal: absVal).intValue
            let str = "\(intVal)"
            return isNeg ? "-\(str)" : str
        }

        // Scale to integer by multiplying by 10^prec
        var factor = Decimal(1)
        for _ in 0..<prec {
            factor = factor * Decimal(10)
        }
        let scaled = absVal * factor
        let intVal = NSDecimalNumber(decimal: roundDecimal(scaled, places: 0))
        var intStr = intVal.stringValue

        // Pad with leading zeros if needed
        while intStr.count < prec + 1 {
            intStr = "0" + intStr
        }

        let integerPart = String(intStr.prefix(intStr.count - prec))
        let decimalPart = String(intStr.suffix(prec))

        let useThousands = self.useThousands
        let useDecimalComma = self.useDecimalComma
        let thousandsSep: Character = useDecimalComma ? "." : ","
        let decimalSep: Character = useDecimalComma ? "," : "."

        // Apply thousands separators if needed
        var formattedInt = integerPart
        if useThousands && formattedInt.count > 3 {
            var groups: [String] = []
            var remaining = formattedInt
            while remaining.count > 3 {
                let idx = remaining.index(remaining.endIndex, offsetBy: -3)
                groups.insert(String(remaining[idx...]), at: 0)
                remaining = String(remaining[..<idx])
            }
            groups.insert(remaining, at: 0)
            formattedInt = groups.joined(separator: String(thousandsSep))
        }

        let result = "\(formattedInt)\(decimalSep)\(decimalPart)"
        return isNeg ? "-\(result)" : result
    }

    /// Return the display value without commodity.
    public var quantityString: String {
        guard _quantity != nil else { return "<null>" }
        return formatQuantity(displayPrecision)
    }

    /// Return the display value with commodity.
    public func toString() -> String {
        guard _quantity != nil else { return "<null>" }
        let numStr = formatQuantity(displayPrecision)
        return applyCommodity(numStr)
    }

    /// Return the full-precision value with commodity.
    public func toFullString() -> String {
        guard _quantity != nil else { return "<null>" }
        let numStr = formatQuantity(_precision)
        return applyCommodity(numStr)
    }

    private func applyCommodity(_ numStr: String) -> String {
        guard hasCommodity, let comm = _commodity else {
            return numStr
        }

        let sym = comm.qualifiedSymbol
        let isSeparated = comm.hasFlags(.separated) || _style.isSeparated
        let isPrefix = comm.isPrefix

        let sep = isSeparated ? " " : ""
        if isPrefix {
            return "\(sym)\(sep)\(numStr)"
        } else {
            return "\(numStr)\(sep)\(sym)"
        }
    }
}

// MARK: Equatable

extension Amount: Equatable {
    public static func == (lhs: Amount, rhs: Amount) -> Bool {
        if lhs.isNull && rhs.isNull { return true }
        if lhs.isNull || rhs.isNull { return false }
        if lhs.hasCommodity && rhs.hasCommodity && lhs._commodity != rhs._commodity {
            return false
        }
        return lhs._quantity == rhs._quantity
    }
}

// MARK: Comparable

extension Amount: Comparable {
    public static func < (lhs: Amount, rhs: Amount) -> Bool {
        let lq = lhs._quantity ?? Decimal.zero
        let rq = rhs._quantity ?? Decimal.zero
        return lq < rq
    }
}

// MARK: CustomStringConvertible

extension Amount: CustomStringConvertible {
    public var description: String {
        toString()
    }
}

// MARK: - Decimal helpers

/// Round a Decimal to the given number of places (half away from zero).
private func roundDecimal(_ value: Decimal, places: Int) -> Decimal {
    var result = Decimal()
    var val = value
    NSDecimalRound(&result, &val, places, .bankers)
    return result
}
