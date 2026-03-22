package muonledger

/**
 * Style flags controlling how a commodity is displayed.
 * Mirrors ledger's COMMODITY_STYLE_* constants.
 */
object CommodityStyle {
    const val DEFAULTS: Int         = 0x000
    const val SUFFIXED: Int         = 0x001  // Symbol follows the amount (e.g., "100 EUR")
    const val SEPARATED: Int        = 0x002  // A space separates symbol from quantity
    const val DECIMAL_COMMA: Int    = 0x004  // Use comma as decimal point (European style)
    const val THOUSANDS: Int        = 0x008  // Insert grouping separators (e.g., "1,000")
    const val NOMARKET: Int         = 0x010  // Exclude from market-price valuations
    const val BUILTIN: Int          = 0x020  // Internally created
    const val KNOWN: Int            = 0x080  // Explicitly declared via a commodity directive
}

/**
 * A commodity (currency / stock / unit of value).
 */
data class Commodity(
    val symbol: String,
    var precision: Int = 0,
    var flags: Int = CommodityStyle.DEFAULTS,
    var note: String? = null
) {
    /** True when the symbol is printed before the quantity. */
    val isPrefix: Boolean
        get() = !hasFlags(CommodityStyle.SUFFIXED)

    /** True if the commodity uses thousands separators. */
    val useThousandsSeparator: Boolean
        get() = hasFlags(CommodityStyle.THOUSANDS)

    /** True if the commodity uses a comma as the decimal mark. */
    val useDecimalComma: Boolean
        get() = hasFlags(CommodityStyle.DECIMAL_COMMA)

    /** True if a space separates the symbol from the quantity. */
    val isSeparated: Boolean
        get() = hasFlags(CommodityStyle.SEPARATED)

    /** The symbol, quoted if it contains special characters. */
    val qualifiedSymbol: String
        get() {
            val needsQuoting = symbol.any { it.isDigit() || it.isWhitespace() || it in "+-*/=<>!@#%^&|?;,.[]{}()~" }
            return if (needsQuoting) "\"$symbol\"" else symbol
        }

    fun hasFlags(flag: Int): Boolean = (flags and flag) == flag

    fun addFlags(flag: Int) {
        flags = flags or flag
    }

    fun dropFlags(flag: Int) {
        flags = flags and flag.inv()
    }

    override fun toString(): String = qualifiedSymbol
}

/**
 * Singleton registry of all known commodities.
 * Mirrors ledger's commodity_pool_t.
 */
object CommodityPool {
    private val commodities = mutableMapOf<String, Commodity>()
    val nullCommodity: Commodity

    init {
        nullCommodity = create("", flags = CommodityStyle.BUILTIN or CommodityStyle.NOMARKET)
    }

    fun find(symbol: String): Commodity? = commodities[symbol]

    fun create(symbol: String, precision: Int = 0, flags: Int = CommodityStyle.DEFAULTS): Commodity {
        require(symbol !in commodities) { "Commodity '$symbol' already exists in pool" }
        val comm = Commodity(symbol = symbol, precision = precision, flags = flags)
        commodities[symbol] = comm
        return comm
    }

    fun findOrCreate(symbol: String): Commodity {
        return commodities[symbol] ?: create(symbol)
    }

    /**
     * Record display-style information learned from a parsed amount.
     * Precision is updated to the maximum of current and incoming.
     * Flags grow monotonically (never removed by learning).
     */
    fun learnStyle(
        symbol: String,
        prefix: Boolean = false,
        precision: Int = 0,
        thousands: Boolean = false,
        decimalComma: Boolean = false,
        separated: Boolean = false
    ): Commodity {
        val comm = findOrCreate(symbol)

        var learned = CommodityStyle.DEFAULTS
        if (!prefix) learned = learned or CommodityStyle.SUFFIXED
        if (separated) learned = learned or CommodityStyle.SEPARATED
        if (thousands) learned = learned or CommodityStyle.THOUSANDS
        if (decimalComma) learned = learned or CommodityStyle.DECIMAL_COMMA

        comm.addFlags(learned)
        if (precision > comm.precision) {
            comm.precision = precision
        }

        // If now declared prefix but SUFFIXED was set, remove it
        if (prefix && comm.hasFlags(CommodityStyle.SUFFIXED)) {
            comm.dropFlags(CommodityStyle.SUFFIXED)
        }

        return comm
    }

    /** Reset the pool (useful in tests). */
    fun reset() {
        commodities.clear()
        val nc = Commodity(symbol = "", precision = 0, flags = CommodityStyle.BUILTIN or CommodityStyle.NOMARKET)
        commodities[""] = nc
    }

    val size: Int get() = commodities.size
}
