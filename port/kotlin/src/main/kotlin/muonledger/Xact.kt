package muonledger

import java.time.LocalDate

/**
 * Raised when a transaction does not balance.
 */
class BalanceError(message: String) : Exception(message)

/**
 * A regular dated transaction -- the primary journal entry.
 *
 * Mirrors ledger's `xact_t` type. In journal syntax:
 *
 *     2024/01/15 * Grocery Store
 *         Expenses:Food       $42.50
 *         Assets:Checking
 *
 * The critical method is [finalize], which checks that all posting
 * groups balance and infers null amounts where exactly one posting
 * in a group lacks an amount.
 */
class Xact(
    /** Transaction date. */
    date: LocalDate? = null,
    /** Clearing state. */
    state: TransactionState = TransactionState.UNCLEARED,
    /** Payee / description. */
    var payee: String = "",
    /** Free-form note. */
    note: String? = null
) : Item(date = date, state = state, note = note) {

    /** The postings belonging to this transaction. */
    val posts: MutableList<Post> = mutableListOf()

    /** Optional transaction code (e.g. check number). */
    var code: String? = null

    /**
     * Add a posting to this transaction and set its back-reference.
     */
    fun addPost(post: Post) {
        post.xact = this
        posts.add(post)
    }

    /**
     * Remove a posting. Returns true if it was found and removed.
     */
    fun removePost(post: Post): Boolean {
        val removed = posts.remove(post)
        if (removed) post.xact = null
        return removed
    }

    // ---- Finalization -------------------------------------------------------

    /**
     * Finalize: infer null amounts and verify balance.
     *
     * Postings are partitioned into three groups:
     * 1. Real postings -- must balance to zero.
     * 2. Balanced-virtual postings `[Account]` -- must balance among themselves.
     * 3. Virtual postings `(Account)` -- not checked.
     *
     * Within each balancing group:
     * - If exactly one posting has a null amount, infer it from the sum of others.
     * - If multi-commodity and no null posting, treat as implicit exchange.
     * - If single-commodity and sum != 0, throw [BalanceError].
     *
     * Also handles lot annotation: if a posting has `lotPrice` but no `cost`,
     * derives `cost = |quantity| * lotPrice`.
     *
     * @throws BalanceError if the transaction does not balance.
     */
    fun finalize() {
        if (posts.isEmpty()) {
            throw BalanceError("Transaction has no postings")
        }

        // Derive cost from lot price where needed.
        // cost = lotPrice * |quantity|, keeping lotPrice's commodity.
        for (post in posts) {
            if (post.lotPrice != null && post.cost == null && post.amount != null) {
                val absQty = post.amount!!.abs().quantity!!
                post.cost = post.lotPrice!! * absQty
            }
        }

        // Partition postings into groups.
        val realPosts = mutableListOf<Post>()
        val balancedVirtualPosts = mutableListOf<Post>()

        for (post in posts) {
            if (post.isVirtual) {
                if (post.isBalanceVirtual) {
                    balancedVirtualPosts.add(post)
                }
                // Plain virtual postings are not balance-checked.
            } else {
                realPosts.add(post)
            }
        }

        // Balance each group independently.
        if (realPosts.isNotEmpty()) {
            finalizeGroup(realPosts, "real")
        }
        if (balancedVirtualPosts.isNotEmpty()) {
            finalizeGroup(balancedVirtualPosts, "balanced virtual")
        }
    }

    private fun finalizeGroup(groupPosts: List<Post>, groupLabel: String) {
        var balance: Value = Value.Empty
        var nullPost: Post? = null

        for (post in groupPosts) {
            // Use cost if available, otherwise the posting amount.
            val amt = post.cost ?: post.amount

            if (amt != null) {
                val amtValue = Value.AmountValue(amt)
                balance = balance.add(amtValue)
            } else if (nullPost != null) {
                throw BalanceError(
                    "Only one posting with null amount allowed per $groupLabel group"
                )
            } else {
                nullPost = post
            }
        }

        // Infer null-amount posting.
        if (nullPost != null) {
            if (balance.isNull || balance.isZero) {
                nullPost.amount = Amount.of(0)
            } else {
                val negBalance = -balance
                nullPost.amount = negBalance.toAmount()
            }
            nullPost.addFlags(Post.POST_CALCULATED or Item.ITEM_INFERRED)
            balance = Value.Empty
        }

        // Final balance verification.
        // Multi-commodity with all explicit amounts => implicit exchange.
        if (!balance.isNull && !balance.isZero) {
            val isMultiCommodity = balance is Value.BalanceValue && nullPost == null
            if (!isMultiCommodity) {
                throw BalanceError(
                    "Transaction does not balance ($groupLabel postings): remainder is $balance"
                )
            }
        }
    }
}
