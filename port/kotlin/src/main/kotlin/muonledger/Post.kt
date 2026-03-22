package muonledger

/**
 * A single line item within a transaction, recording a debit or credit
 * to an account.
 *
 * Mirrors ledger's `post_t` type. A posting references an account and
 * carries an amount (which may be null until finalization infers it).
 */
class Post(
    /** The target account this posting debits or credits. */
    var account: Account,
    /** The posting amount; null for inferred postings. */
    var amount: Amount? = null,
    /** Cost from `@ price` or `@@ total`. */
    var cost: Amount? = null,
    /** Balance assertion amount from `= $X`. */
    var assignedAmount: Amount? = null,
    /** True if this is a virtual posting `(Account)`. */
    var isVirtual: Boolean = false,
    /** True if this is a balance-virtual posting `[Account]`. */
    var isBalanceVirtual: Boolean = false,
    /** Lot price from `{$150.00}`. */
    var lotPrice: Amount? = null,
    /** Free-form note text. */
    note: String? = null
) : Item(note = note) {

    /** Back-reference to the parent transaction. */
    var xact: Xact? = null
        internal set

    /**
     * True if this posting participates in balance checking.
     *
     * Plain virtual postings `(Account)` do not need to balance.
     * Real postings and balanced-virtual postings `[Account]` must.
     */
    fun mustBalance(): Boolean {
        if (isVirtual) return isBalanceVirtual
        return true
    }

    companion object {
        const val POST_VIRTUAL = 0x0010
        const val POST_MUST_BALANCE = 0x0020
        const val POST_CALCULATED = 0x0040
        const val POST_COST_CALCULATED = 0x0080
        const val POST_COST_IN_FULL = 0x0100
        const val POST_COST_FIXATED = 0x0200
    }
}
