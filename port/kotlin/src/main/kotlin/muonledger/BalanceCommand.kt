package muonledger

/**
 * Balance command -- produces a balance report from a journal.
 *
 * Output format mirrors ledger's default balance format:
 *
 *            $100.00  Assets:Bank:Checking
 *            $-50.00  Expenses:Food
 * --------------------
 *             $50.00
 */
object BalanceCommand {

    private const val AMOUNT_WIDTH = 20
    private val SEPARATOR = "-".repeat(AMOUNT_WIDTH)

    data class Options(
        val flat: Boolean = false,
        val noTotal: Boolean = false,
        val showEmpty: Boolean = false,
        val depth: Int = 0,
        val begin: java.time.LocalDate? = null,
        val end: java.time.LocalDate? = null,
        val patterns: List<String> = emptyList()
    )

    fun run(journal: Journal, opts: Options): String {
        val effectiveDepth = opts.depth

        // Step 1: Accumulate per-account (leaf) balances.
        var leafBalances = accumulateBalances(journal, opts.begin, opts.end)

        // Step 2: Roll up balances to parents.
        var rolled = rollUpToParents(leafBalances)

        // Step 3: Apply depth limiting.
        if (effectiveDepth > 0) {
            rolled = applyDepth(rolled, effectiveDepth)
            val depthLeaves = mutableMapOf<String, Balance>()
            for ((name, bal) in leafBalances) {
                val parts = name.split(":")
                val truncated = if (parts.size > effectiveDepth) {
                    parts.take(effectiveDepth).joinToString(":")
                } else {
                    name
                }
                val entry = depthLeaves.getOrPut(truncated) { Balance() }
                entry.add(bal)
            }
            leafBalances = depthLeaves
        }

        // Step 4: Determine which accounts to display.
        val accounts = if (opts.flat) {
            flatAccounts(leafBalances, opts.patterns, opts.showEmpty, effectiveDepth)
        } else {
            val entries = collectTreeAccounts(rolled, leafBalances, opts.showEmpty, effectiveDepth)
            if (opts.patterns.isNotEmpty()) {
                filterTreeByPatterns(entries, opts.patterns)
            } else {
                entries
            }
        }

        // Step 5: Render.
        val lines = mutableListOf<String>()

        for ((displayName, _, bal) in accounts) {
            val amtLines = formatAmountLines(bal)
            lines.add("${amtLines[0]}  $displayName")
            for (extra in amtLines.drop(1)) {
                lines.add(extra)
            }
        }

        // Compute grand total from leaf balances.
        val grandTotal = Balance()
        if (opts.patterns.isEmpty()) {
            for (bal in leafBalances.values) {
                grandTotal.add(bal)
            }
        } else {
            if (opts.flat) {
                for ((_, _, bal) in accounts) {
                    grandTotal.add(bal)
                }
            } else {
                for ((_, full, _) in accounts) {
                    val leafBal = leafBalances[full]
                    if (leafBal != null) {
                        grandTotal.add(leafBal)
                    }
                }
            }
        }

        // Total line.
        if (!opts.noTotal && accounts.isNotEmpty()) {
            lines.add(SEPARATOR)
            if (grandTotal.isEmpty || grandTotal.isZero) {
                lines.add("0".padStart(AMOUNT_WIDTH))
            } else {
                val totalLines = formatAmountLines(grandTotal)
                lines.addAll(totalLines)
            }
        }

        if (lines.isEmpty()) {
            return ""
        }

        return lines.joinToString("\n") + "\n"
    }

    private fun accumulateBalances(
        journal: Journal,
        begin: java.time.LocalDate?,
        end: java.time.LocalDate?
    ): MutableMap<String, Balance> {
        val balances = mutableMapOf<String, Balance>()
        for (xact in journal.transactions) {
            if (begin != null && xact.date != null && xact.date!! < begin) continue
            if (end != null && xact.date != null && !xact.date!!.isBefore(end)) continue
            for (post in xact.posts) {
                val amt = post.amount ?: continue
                if (amt.isNull) continue
                val name = post.account.fullname
                if (name.isEmpty()) continue
                val bal = balances.getOrPut(name) { Balance() }
                bal.add(amt)
            }
        }
        return balances
    }

    private fun rollUpToParents(balances: Map<String, Balance>): MutableMap<String, Balance> {
        val rolled = mutableMapOf<String, Balance>()
        for ((name, bal) in balances) {
            val parts = name.split(":")
            for (i in 1..parts.size) {
                val ancestor = parts.take(i).joinToString(":")
                val entry = rolled.getOrPut(ancestor) { Balance() }
                entry.add(bal)
            }
        }
        return rolled
    }

    private fun applyDepth(rolled: Map<String, Balance>, depth: Int): MutableMap<String, Balance> {
        val result = mutableMapOf<String, Balance>()
        for ((name, bal) in rolled) {
            if (name.split(":").size <= depth) {
                result[name] = Balance(bal)
            }
        }
        return result
    }

    private fun Balance(other: Balance): Balance {
        val b = Balance()
        b.add(other)
        return b
    }

    private fun Balance.add(other: Balance) {
        for ((_, amt) in other.amounts()) {
            this.add(amt)
        }
    }

    private fun matchesPattern(name: String, patterns: List<String>): Boolean {
        if (patterns.isEmpty()) return true
        val lower = name.lowercase()
        return patterns.any { lower.contains(it.lowercase()) }
    }

    private fun getChildren(name: String, allNames: Set<String>): List<String> {
        val prefix = "$name:"
        return allNames.filter { n ->
            n.startsWith(prefix) && !n.substring(prefix.length).contains(':')
        }.sorted()
    }

    private data class AccountEntry(val displayName: String, val fullName: String, val balance: Balance)

    private fun collectTreeAccounts(
        rolled: Map<String, Balance>,
        leafBalances: Map<String, Balance>,
        showEmpty: Boolean,
        depth: Int
    ): List<AccountEntry> {
        val allNames = rolled.keys.toSet()
        val topLevel = allNames.filter { !it.contains(':') }.sorted()
        val result = mutableListOf<AccountEntry>()

        fun visibleChildren(name: String): List<String> {
            val children = getChildren(name, allNames)
            return if (!showEmpty) {
                children.filter { c ->
                    val b = rolled[c]
                    b != null && !b.isZero
                }
            } else {
                children
            }
        }

        fun hasDirectOrKnown(name: String): Boolean = name in leafBalances

        fun walk(name: String, currentDepth: Int, collapsePrefix: String, indentDepth: Int) {
            if (depth > 0 && currentDepth >= depth) return

            val bal = rolled[name] ?: Balance()
            val children = visibleChildren(name)

            // Build display name
            val leafSegment = name.substringAfterLast(':')
            val display = if (collapsePrefix.isNotEmpty()) {
                "$collapsePrefix:$leafSegment"
            } else {
                leafSegment
            }

            // Collapse: single child, no direct postings
            if (children.size == 1 && !hasDirectOrKnown(name)) {
                walk(children[0], currentDepth, display, indentDepth)
                return
            }

            // Should we display this account?
            var shouldShow = false
            if (!bal.isZero) {
                shouldShow = true
            } else if (showEmpty && hasDirectOrKnown(name)) {
                shouldShow = true
            }

            if (!shouldShow && children.isEmpty()) return

            if (shouldShow) {
                val indented = "  ".repeat(indentDepth) + display
                result.add(AccountEntry(indented, name, bal))
            }

            val childPrefix = if (shouldShow) "" else display
            for (child in children) {
                walk(
                    child,
                    currentDepth + 1,
                    childPrefix,
                    indentDepth + if (shouldShow) 1 else 0
                )
            }
        }

        for (top in topLevel) {
            walk(top, 0, "", 0)
        }

        return result
    }

    private fun flatAccounts(
        leafBalances: Map<String, Balance>,
        patterns: List<String>,
        showEmpty: Boolean,
        depth: Int
    ): List<AccountEntry> {
        val result = mutableListOf<AccountEntry>()
        for (name in leafBalances.keys.sorted()) {
            val bal = leafBalances[name]!!
            if (!showEmpty && bal.isZero) continue
            if (patterns.isNotEmpty() && !matchesPattern(name, patterns)) continue
            if (depth > 0 && name.split(":").size > depth) continue
            result.add(AccountEntry(name, name, bal))
        }
        return result
    }

    private fun filterTreeByPatterns(entries: List<AccountEntry>, patterns: List<String>): List<AccountEntry> {
        val matchingFull = mutableSetOf<String>()
        for (entry in entries) {
            if (matchesPattern(entry.fullName, patterns)) {
                matchingFull.add(entry.fullName)
            }
        }

        val ancestorNames = mutableSetOf<String>()
        for (full in matchingFull) {
            val parts = full.split(":")
            for (i in 1 until parts.size) {
                ancestorNames.add(parts.take(i).joinToString(":"))
            }
        }

        return entries.filter { it.fullName in matchingFull || it.fullName in ancestorNames }
    }

    private fun formatAmountLines(bal: Balance): List<String> {
        if (bal.isEmpty) {
            return listOf("0".padStart(AMOUNT_WIDTH))
        }

        val lines = mutableListOf<String>()
        for ((_, amt) in bal.amounts().toSortedMap()) {
            lines.add(amt.toString().padStart(AMOUNT_WIDTH))
        }

        if (lines.isEmpty()) {
            lines.add("0".padStart(AMOUNT_WIDTH))
        }

        return lines
    }
}
