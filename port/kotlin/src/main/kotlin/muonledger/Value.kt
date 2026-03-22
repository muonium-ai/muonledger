package muonledger

/**
 * Polymorphic value type for the expression engine.
 *
 * Mirrors ledger's `value_t` type. A Value wraps an Amount, Balance,
 * or nothing (Empty), with automatic type promotion during arithmetic.
 *
 * The promotion hierarchy:
 *   Empty -> AmountValue -> BalanceValue
 *
 * Adding two AmountValues of the same commodity stays AmountValue;
 * different commodities promotes to BalanceValue.
 */
sealed class Value {

    /** No value. */
    data object Empty : Value()

    /** A single-commodity amount. */
    data class AmountValue(val amount: Amount) : Value()

    /** A multi-commodity balance. */
    data class BalanceValue(val balance: Balance) : Value()

    // ---- Query --------------------------------------------------------------

    val isZero: Boolean
        get() = when (this) {
            is Empty -> true
            is AmountValue -> amount.isZero
            is BalanceValue -> balance.isZero
        }

    val isNull: Boolean
        get() = this is Empty

    // ---- Arithmetic ---------------------------------------------------------

    /**
     * Add another value to this one.
     *
     * Auto-promotes: Amount + Amount of different commodity -> Balance.
     */
    fun add(other: Value): Value = when (this) {
        is Empty -> other
        is AmountValue -> when (other) {
            is Empty -> this
            is AmountValue -> addAmounts(this.amount, other.amount)
            is BalanceValue -> {
                val result = Balance(other.balance)
                result.add(this.amount)
                BalanceValue(result)
            }
        }
        is BalanceValue -> when (other) {
            is Empty -> this
            is AmountValue -> {
                val result = Balance(this.balance)
                result.add(other.amount)
                BalanceValue(result)
            }
            is BalanceValue -> BalanceValue(this.balance + other.balance)
        }
    }

    /**
     * Subtract another value from this one.
     */
    fun subtract(other: Value): Value = when (this) {
        is Empty -> other.negate()
        is AmountValue -> when (other) {
            is Empty -> this
            is AmountValue -> subtractAmounts(this.amount, other.amount)
            is BalanceValue -> {
                val result = Balance(this.amount)
                for (amt in other.balance.amounts().values) {
                    result.subtract(amt)
                }
                BalanceValue(result)
            }
        }
        is BalanceValue -> when (other) {
            is Empty -> this
            is AmountValue -> {
                val result = Balance(this.balance)
                result.subtract(other.amount)
                BalanceValue(result)
            }
            is BalanceValue -> BalanceValue(this.balance - other.balance)
        }
    }

    /**
     * Negate this value.
     */
    fun negate(): Value = when (this) {
        is Empty -> Empty
        is AmountValue -> AmountValue(-amount)
        is BalanceValue -> BalanceValue(-balance)
    }

    /**
     * Convert to an Amount.
     *
     * @throws IllegalStateException if this is a multi-commodity balance.
     */
    fun toAmount(): Amount = when (this) {
        is Empty -> Amount.of(0)
        is AmountValue -> amount.copy()
        is BalanceValue -> balance.toAmount()
    }

    // ---- Operators ----------------------------------------------------------

    operator fun plus(other: Value): Value = add(other)
    operator fun minus(other: Value): Value = subtract(other)
    operator fun unaryMinus(): Value = negate()

    // ---- String -------------------------------------------------------------

    override fun toString(): String = when (this) {
        is Empty -> ""
        is AmountValue -> amount.toString()
        is BalanceValue -> balance.toString()
    }

    companion object {
        /**
         * Add two amounts, promoting to Balance if commodities differ.
         */
        private fun addAmounts(a: Amount, b: Amount): Value {
            if (a.hasCommodity() && b.hasCommodity() && a.commodity != b.commodity) {
                val bal = Balance(a)
                bal.add(b)
                return BalanceValue(bal)
            }
            return AmountValue(a + b)
        }

        /**
         * Subtract two amounts, promoting to Balance if commodities differ.
         */
        private fun subtractAmounts(a: Amount, b: Amount): Value {
            if (a.hasCommodity() && b.hasCommodity() && a.commodity != b.commodity) {
                val bal = Balance(a)
                bal.subtract(b)
                return BalanceValue(bal)
            }
            return AmountValue(a - b)
        }
    }
}
