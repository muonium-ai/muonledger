package muonledger

/**
 * Central container for all financial data in a Ledger session.
 *
 * Mirrors ledger's `journal_t` type. The journal owns the account tree
 * (rooted at [root]), all parsed transactions, and account aliases.
 */
class Journal {

    /** The root account node (invisible, depth 0). */
    val root: Account = Account()

    /** All regular transactions, in parse order. */
    val transactions: MutableList<Xact> = mutableListOf()

    /** Account aliases: short name -> full path. */
    val aliases: MutableMap<String, String> = mutableMapOf()

    /**
     * Add a transaction to the journal after finalizing it.
     *
     * Calls [Xact.finalize] to infer missing amounts and verify
     * double-entry balance, then appends the transaction.
     *
     * @throws BalanceError if the transaction does not balance.
     */
    fun addTransaction(xact: Xact) {
        xact.finalize()
        transactions.add(xact)
    }

    /**
     * Look up or create an account by colon-separated path.
     *
     * If an alias exists for the given name, it is resolved first.
     */
    fun findOrCreateAccount(name: String): Account {
        val resolved = aliases[name] ?: name
        return root.findAccount(resolved)!!
    }

    /** Number of transactions in the journal. */
    val size: Int get() = transactions.size

    override fun toString(): String {
        return "Journal(transactions=${transactions.size}, accounts=${root.flatten().size})"
    }
}
