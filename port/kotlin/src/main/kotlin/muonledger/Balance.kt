package muonledger

/**
 * Multi-commodity balance for double-entry accounting.
 *
 * Mirrors ledger's `balance_t` type. A balance holds amounts across
 * multiple commodities simultaneously. Internally stored as a map
 * keyed by commodity symbol.
 */
class Balance {

    private val amounts: MutableMap<String, Amount> = mutableMapOf()

    // ---- Construction -------------------------------------------------------

    constructor()

    constructor(amount: Amount) {
        if (!amount.isNull && !amount.isZero) {
            amounts[commodityKey(amount)] = amount.copy()
        }
    }

    constructor(other: Balance) {
        for ((k, v) in other.amounts) {
            amounts[k] = v.copy()
        }
    }

    // ---- Internal helpers ---------------------------------------------------

    private fun commodityKey(amt: Amount): String {
        return amt.commodity?.symbol ?: ""
    }

    // ---- Public add / subtract ----------------------------------------------

    /**
     * Add an amount to this balance (mutating).
     */
    fun add(amount: Amount) {
        val key = commodityKey(amount)
        val existing = amounts[key]
        if (existing != null) {
            val sum = existing + amount
            if (sum.isZero) {
                amounts.remove(key)
            } else {
                amounts[key] = sum
            }
        } else {
            if (!amount.isZero) {
                amounts[key] = amount.copy()
            }
        }
    }

    /**
     * Subtract an amount from this balance (mutating).
     */
    fun subtract(amount: Amount) {
        val key = commodityKey(amount)
        val existing = amounts[key]
        if (existing != null) {
            val diff = existing - amount
            if (diff.isZero) {
                amounts.remove(key)
            } else {
                amounts[key] = diff
            }
        } else {
            if (!amount.isZero) {
                amounts[key] = -amount
            }
        }
    }

    // ---- Query --------------------------------------------------------------

    /** True if no amounts are stored or all are zero. */
    val isZero: Boolean
        get() = amounts.isEmpty() || amounts.values.all { it.isZero }

    /** True if no amounts are stored. */
    val isEmpty: Boolean
        get() = amounts.isEmpty()

    /** True if exactly one commodity is present. */
    val isSingleCommodity: Boolean
        get() = amounts.size == 1

    /** Return the single Amount if exactly one commodity, else null. */
    val singleAmount: Amount?
        get() = if (amounts.size == 1) amounts.values.first() else null

    /** Number of distinct commodities. */
    val commodityCount: Int
        get() = amounts.size

    /** Read-only view of the internal amounts map. */
    fun amounts(): Map<String, Amount> = amounts.toMap()

    // ---- Operators ----------------------------------------------------------

    operator fun plus(other: Balance): Balance {
        val result = Balance(this)
        for (amt in other.amounts.values) {
            result.add(amt)
        }
        return result
    }

    operator fun minus(other: Balance): Balance {
        val result = Balance(this)
        for (amt in other.amounts.values) {
            result.subtract(amt)
        }
        return result
    }

    operator fun plus(amount: Amount): Balance {
        val result = Balance(this)
        result.add(amount)
        return result
    }

    operator fun minus(amount: Amount): Balance {
        val result = Balance(this)
        result.subtract(amount)
        return result
    }

    operator fun unaryMinus(): Balance {
        val result = Balance()
        for ((k, v) in amounts) {
            result.amounts[k] = -v
        }
        return result
    }

    /**
     * Convert to a single Amount.
     *
     * @throws IllegalStateException if the balance is empty or has multiple commodities.
     */
    fun toAmount(): Amount {
        if (amounts.isEmpty()) {
            throw IllegalStateException("Cannot convert an empty balance to an amount")
        }
        if (amounts.size == 1) {
            return amounts.values.first().copy()
        }
        throw IllegalStateException(
            "Cannot convert a balance with multiple commodities to an amount"
        )
    }

    // ---- Equality / String --------------------------------------------------

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Balance) return false
        return amounts == other.amounts
    }

    override fun hashCode(): Int = amounts.hashCode()

    override fun toString(): String {
        if (amounts.isEmpty()) return "0"
        return amounts.keys.sorted().joinToString("\n") { amounts[it].toString() }
    }
}
