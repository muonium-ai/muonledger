package muonledger

import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode

/**
 * Exact-precision commoditized amount for double-entry accounting.
 *
 * Uses java.math.BigDecimal for exact decimal arithmetic, mirroring
 * ledger's amount_t type.
 */
class Amount private constructor(
    /** The exact decimal quantity, or null for an uninitialized amount. */
    var quantity: BigDecimal?,
    /** The associated commodity, or null. */
    var commodity: Commodity?,
    /** Number of decimal places for display. */
    var precision: Int,
    /** Display style hints. */
    private var style: AmountStyle
) : Comparable<Amount> {

    data class AmountStyle(
        var isPrefix: Boolean = false,
        var isSeparated: Boolean = false,
        var useThousands: Boolean = false,
        var useDecimalComma: Boolean = false
    )

    // ---- Construction -------------------------------------------------------

    companion object {
        /** Create an uninitialized (null) amount. */
        fun nil(): Amount = Amount(null, null, 0, AmountStyle())

        /** Create an amount from a BigDecimal with optional commodity. */
        fun of(value: BigDecimal, commodity: Commodity? = null): Amount {
            return Amount(value, commodity, value.scale().coerceAtLeast(0), AmountStyle())
        }

        /** Create an amount from an integer with optional commodity. */
        fun of(value: Int, commodity: Commodity? = null): Amount {
            return Amount(BigDecimal(value), commodity, 0, AmountStyle())
        }

        /** Create an amount from a long with optional commodity. */
        fun of(value: Long, commodity: Commodity? = null): Amount {
            return Amount(BigDecimal(value), commodity, 0, AmountStyle())
        }

        /** Create from a string with optional commodity symbol. */
        fun of(value: String, commodity: Commodity? = null): Amount {
            val bd = BigDecimal(value)
            return Amount(bd, commodity, bd.scale().coerceAtLeast(0), AmountStyle())
        }

        /**
         * Parse an amount string like "$50.00", "100 EUR", "$-15.00", "$12,500.00".
         */
        fun parse(text: String): Amount {
            val trimmed = text.trim()
            if (trimmed.isEmpty()) {
                throw IllegalArgumentException("Cannot parse empty amount string")
            }

            var rest = trimmed
            var negative = false

            // Handle leading sign
            if (rest.startsWith("-")) {
                negative = true
                rest = rest.substring(1).trimStart()
            } else if (rest.startsWith("+")) {
                rest = rest.substring(1).trimStart()
            }

            val style = AmountStyle()
            var commoditySymbol: String? = null

            // Check for prefix commodity (starts with non-digit, non-dot)
            val firstChar = rest.firstOrNull() ?: throw IllegalArgumentException("Cannot parse amount: $text")

            if (!firstChar.isDigit() && firstChar != '.') {
                // Prefix commodity
                val symbolEnd = findSymbolEnd(rest)
                val rawSymbol = rest.substring(0, symbolEnd).trim('"')
                rest = rest.substring(symbolEnd)
                if (rest.startsWith(" ")) {
                    style.isSeparated = true
                    rest = rest.trimStart()
                }
                style.isPrefix = true
                commoditySymbol = rawSymbol
            } else {
                // Number first; check for suffix commodity
                val numEnd = findNumEnd(rest)
                val numPart = rest.substring(0, numEnd)
                var suffixPart = rest.substring(numEnd)
                if (suffixPart.startsWith(" ")) {
                    style.isSeparated = true
                    suffixPart = suffixPart.trimStart()
                }
                if (suffixPart.isNotEmpty()) {
                    commoditySymbol = suffixPart.trim('"')
                }
                rest = numPart
            }

            // Parse the numeric part
            val numericStr = rest.trim()
            if (numericStr.isEmpty()) {
                throw IllegalArgumentException("No quantity in amount: $text")
            }

            val hasComma = ',' in numericStr
            val hasPeriod = '.' in numericStr
            var decimalPlaces = 0
            var clean: String

            if (hasComma && hasPeriod) {
                val lastComma = numericStr.lastIndexOf(',')
                val lastPeriod = numericStr.lastIndexOf('.')
                if (lastPeriod > lastComma) {
                    // Period is decimal mark, comma is thousands
                    style.useThousands = true
                    clean = numericStr.replace(",", "")
                    decimalPlaces = countDecimalPlaces(clean)
                } else {
                    // Comma is decimal mark, period is thousands
                    style.useThousands = true
                    style.useDecimalComma = true
                    clean = numericStr.replace(".", "").replace(",", ".")
                    decimalPlaces = countDecimalPlaces(clean)
                }
            } else if (hasComma) {
                val lastComma = numericStr.lastIndexOf(',')
                val afterComma = numericStr.substring(lastComma + 1)
                val commaCount = numericStr.count { it == ',' }

                if (commaCount > 1) {
                    style.useThousands = true
                    clean = numericStr.replace(",", "")
                    decimalPlaces = 0
                } else if (afterComma.length != 3) {
                    style.useDecimalComma = true
                    clean = numericStr.replace(",", ".")
                    decimalPlaces = afterComma.length
                } else {
                    // Ambiguous: treat as thousands
                    style.useThousands = true
                    clean = numericStr.replace(",", "")
                    decimalPlaces = 0
                }
            } else if (hasPeriod) {
                clean = numericStr
                decimalPlaces = countDecimalPlaces(clean)
            } else {
                clean = numericStr
                decimalPlaces = 0
            }

            var bd = BigDecimal(clean)
            if (negative) bd = bd.negate()

            // Resolve commodity
            var commodityObj: Commodity? = null
            if (commoditySymbol != null) {
                commodityObj = CommodityPool.learnStyle(
                    symbol = commoditySymbol,
                    prefix = style.isPrefix,
                    precision = decimalPlaces,
                    thousands = style.useThousands,
                    decimalComma = style.useDecimalComma,
                    separated = style.isSeparated
                )
            }

            return Amount(bd, commodityObj, decimalPlaces, style)
        }

        private fun findSymbolEnd(s: String): Int {
            // Quoted symbol
            if (s.startsWith("\"")) {
                val end = s.indexOf('"', 1)
                return if (end < 0) s.length else end + 1
            }
            // Unquoted: run of non-digit, non-whitespace, non-sign, non-dot, non-comma chars
            var i = 0
            while (i < s.length) {
                val c = s[i]
                if (c.isDigit() || c.isWhitespace() || c in "-+.,") break
                i++
            }
            return i
        }

        private fun findNumEnd(s: String): Int {
            var i = 0
            while (i < s.length) {
                val c = s[i]
                if (c.isDigit() || c in ".,-'") {
                    i++
                } else {
                    break
                }
            }
            return i
        }

        private fun countDecimalPlaces(s: String): Int {
            val dot = s.indexOf('.')
            return if (dot < 0) 0 else s.length - dot - 1
        }
    }

    // ---- Null / truth tests -------------------------------------------------

    /** True if no value has been set (uninitialized). */
    val isNull: Boolean get() = quantity == null

    /** True if the quantity is exactly zero. */
    val isZero: Boolean
        get() {
            val q = quantity ?: throw IllegalStateException("Cannot test uninitialized amount")
            return q.signum() == 0
        }

    /** True if quantity is negative. */
    val isNegative: Boolean
        get() {
            val q = quantity ?: throw IllegalStateException("Cannot test uninitialized amount")
            return q.signum() < 0
        }

    /** True if quantity is positive. */
    val isPositive: Boolean
        get() {
            val q = quantity ?: throw IllegalStateException("Cannot test uninitialized amount")
            return q.signum() > 0
        }

    fun hasCommodity(): Boolean = commodity != null && commodity!!.symbol.isNotEmpty()

    // ---- Display precision --------------------------------------------------

    /** The effective precision for display output. */
    fun displayPrecision(): Int {
        val comm = commodity
        if (comm != null && comm.symbol.isNotEmpty() && comm.precision > 0) {
            return comm.precision
        }
        return precision
    }

    // ---- Unary operations ---------------------------------------------------

    /** Return a negated copy. */
    operator fun unaryMinus(): Amount {
        val q = requireQuantity()
        return Amount(q.negate(), commodity, precision, style.copy())
    }

    /** Return the absolute value. */
    fun abs(): Amount {
        val q = requireQuantity()
        return Amount(q.abs(), commodity, precision, style.copy())
    }

    // ---- Arithmetic ---------------------------------------------------------

    operator fun plus(other: Amount): Amount {
        val lq = requireQuantity()
        val rq = other.requireQuantity()

        if (hasCommodity() && other.hasCommodity() && commodity != other.commodity) {
            throw IllegalArgumentException(
                "Adding amounts with different commodities: '${commodity?.symbol}' != '${other.commodity?.symbol}'"
            )
        }

        val resultCommodity = if (!hasCommodity() && other.hasCommodity()) other.commodity else commodity
        val resultStyle = if (!hasCommodity() && other.hasCommodity()) other.style.copy() else style.copy()
        return Amount(lq.add(rq), resultCommodity, maxOf(precision, other.precision), resultStyle)
    }

    operator fun minus(other: Amount): Amount {
        val lq = requireQuantity()
        val rq = other.requireQuantity()

        if (hasCommodity() && other.hasCommodity() && commodity != other.commodity) {
            throw IllegalArgumentException(
                "Subtracting amounts with different commodities: '${commodity?.symbol}' != '${other.commodity?.symbol}'"
            )
        }

        val resultCommodity = if (!hasCommodity() && other.hasCommodity()) other.commodity else commodity
        val resultStyle = if (!hasCommodity() && other.hasCommodity()) other.style.copy() else style.copy()
        return Amount(lq.subtract(rq), resultCommodity, maxOf(precision, other.precision), resultStyle)
    }

    /** Multiply by a scalar BigDecimal. */
    operator fun times(scalar: BigDecimal): Amount {
        val q = requireQuantity()
        return Amount(q.multiply(scalar), commodity, precision + scalar.scale().coerceAtLeast(0), style.copy())
    }

    /** Multiply by another Amount. */
    operator fun times(other: Amount): Amount {
        val lq = requireQuantity()
        val rq = other.requireQuantity()
        val resultCommodity = if (!hasCommodity() && other.hasCommodity()) other.commodity else commodity
        val resultStyle = if (!hasCommodity() && other.hasCommodity()) other.style.copy() else style.copy()
        return Amount(lq.multiply(rq), resultCommodity, precision + other.precision, resultStyle)
    }

    // ---- Comparison ---------------------------------------------------------

    override fun compareTo(other: Amount): Int {
        val lq = requireQuantity()
        val rq = other.requireQuantity()
        return lq.compareTo(rq)
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Amount) return false
        if (isNull && other.isNull) return true
        if (isNull || other.isNull) return false
        if (hasCommodity() && other.hasCommodity() && commodity != other.commodity) return false
        return quantity!!.compareTo(other.quantity!!) == 0
    }

    override fun hashCode(): Int {
        val commKey = commodity?.symbol
        // Normalize via stripTrailingZeros for consistent hashing
        return 31 * (quantity?.stripTrailingZeros()?.hashCode() ?: 0) + (commKey?.hashCode() ?: 0)
    }

    // ---- Formatting ---------------------------------------------------------

    /**
     * Format this amount for display. Examples:
     * - `$50.00` (prefix commodity)
     * - `100 EUR` (suffix commodity, separated)
     * - `$-15.00` (negative, prefix)
     * - `$12,500.00` (thousands separator)
     */
    override fun toString(): String {
        val q = quantity ?: return "<null>"
        val dp = displayPrecision()
        val numStr = formatQuantity(q, dp)
        return applyCommodity(numStr)
    }

    /** Format quantity without commodity. */
    fun quantityString(): String {
        val q = quantity ?: return "<null>"
        val dp = displayPrecision()
        return formatQuantity(q, dp)
    }

    private fun formatQuantity(q: BigDecimal, prec: Int): String {
        val rounded = q.setScale(prec, RoundingMode.HALF_UP)
        val isNeg = rounded.signum() < 0
        val abs = rounded.abs()

        val plain = abs.toPlainString()
        val parts = plain.split(".")
        var integerPart = parts[0]
        val decimalPart = if (parts.size > 1) parts[1] else ""

        // Determine separator characters
        val comm = commodity
        val useThousands = comm?.useThousandsSeparator == true || style.useThousands
        val useDecimalComma = comm?.useDecimalComma == true || style.useDecimalComma
        val thousandsSep = if (useDecimalComma) "." else ","
        val decimalSep = if (useDecimalComma) "," else "."

        // Apply thousands separators
        if (useThousands && integerPart.length > 3) {
            val groups = mutableListOf<String>()
            while (integerPart.length > 3) {
                groups.add(0, integerPart.takeLast(3))
                integerPart = integerPart.dropLast(3)
            }
            groups.add(0, integerPart)
            integerPart = groups.joinToString(thousandsSep)
        }

        val result = if (prec > 0) {
            // Pad or trim decimal part to exact precision
            val paddedDecimal = decimalPart.padEnd(prec, '0').take(prec)
            "$integerPart$decimalSep$paddedDecimal"
        } else {
            integerPart
        }

        return if (isNeg) "-$result" else result
    }

    private fun applyCommodity(numStr: String): String {
        val comm = commodity ?: return numStr
        if (comm.symbol.isEmpty()) return numStr

        val sym = comm.qualifiedSymbol
        val commObj = commodity
        val separated = commObj?.isSeparated == true || style.isSeparated
        val prefix = commObj?.isPrefix ?: style.isPrefix
        val sep = if (separated) " " else ""

        return if (prefix) {
            // For prefix: sign goes after symbol: $-15.00
            if (numStr.startsWith("-")) {
                "$sym${sep}-${numStr.substring(1)}"
            } else {
                "$sym$sep$numStr"
            }
        } else {
            "$numStr$sep$sym"
        }
    }

    // ---- Copy ---------------------------------------------------------------

    fun copy(): Amount = Amount(quantity, commodity, precision, style.copy())

    // ---- Internal -----------------------------------------------------------

    private fun requireQuantity(): BigDecimal {
        return quantity ?: throw IllegalStateException("Cannot use an uninitialized amount")
    }
}
