package muonledger

/**
 * Register command: list postings chronologically with running totals.
 *
 * Output format matches ledger's default register report:
 * 24-Jan-15 Grocery Store          Expenses:Food                $50.00       $50.00
 *                                  Assets:Checking             $-50.00            0
 */
object RegisterCommand {

    // Default (80-column) layout
    private const val DATE_WIDTH = 10
    private const val PAYEE_WIDTH = 22
    private const val ACCOUNT_WIDTH = 22
    private const val AMOUNT_WIDTH = 13
    private const val TOTAL_WIDTH = 13

    data class Options(
        val wide: Boolean = false,
        val head: Int? = null,
        val tail: Int? = null,
        val begin: java.time.LocalDate? = null,
        val end: java.time.LocalDate? = null,
        val accountPatterns: List<String> = emptyList()
    )

    fun run(journal: Journal, opts: Options): String {
        val dateW = DATE_WIDTH
        val payeeW = PAYEE_WIDTH
        val accountW = ACCOUNT_WIDTH
        val amountW = AMOUNT_WIDTH
        val totalW = TOTAL_WIDTH

        val rows = mutableListOf<List<String>>()
        val runningTotal = Balance()

        for (xact in journal.transactions) {
            // Date filtering
            if (opts.begin != null && xact.date != null && xact.date!! < opts.begin) continue
            if (opts.end != null && xact.date != null && !xact.date!!.isBefore(opts.end)) continue

            var firstInXact = true
            for (post in xact.posts) {
                val accountName = post.account.fullname

                if (!matchesAccount(accountName, opts.accountPatterns)) continue

                // Update running total
                val amt = post.amount
                if (amt != null && !amt.isNull) {
                    runningTotal.add(amt)
                }

                // Format date and payee
                val dateStr: String
                val payeeStr: String
                if (firstInXact) {
                    dateStr = formatDate(xact.date)
                    payeeStr = truncate(xact.payee, payeeW - 1)
                    firstInXact = false
                } else {
                    dateStr = ""
                    payeeStr = ""
                }

                // Format posting amount
                val amtStr = amountStr(amt)

                // Format running total
                val totalLines = balanceToLines(runningTotal)

                // Build output lines
                val lines = mutableListOf<String>()

                val dateCol = dateStr.padEnd(dateW)
                val payeeCol = payeeStr.padEnd(payeeW)
                val accountCol = truncate(accountName, accountW - 1).padEnd(accountW)
                val amountCol = amtStr.padStart(amountW)

                val firstTotal = totalLines.firstOrNull() ?: ""
                val totalCol = firstTotal.padStart(totalW)

                lines.add("$dateCol$payeeCol$accountCol$amountCol$totalCol")

                // Additional total lines (multi-commodity)
                for (extraTotal in totalLines.drop(1)) {
                    val blankPrefix = " ".repeat(dateW + payeeW + accountW + amountW)
                    lines.add("$blankPrefix${extraTotal.padStart(totalW)}")
                }

                rows.add(lines)
            }
        }

        // Apply --head / --tail
        var displayRows = rows.toList()
        if (opts.head != null) {
            displayRows = displayRows.take(opts.head)
        }
        if (opts.tail != null) {
            displayRows = displayRows.takeLast(opts.tail)
        }

        val outputLines = displayRows.flatMap { it }

        if (outputLines.isEmpty()) return ""

        return outputLines.joinToString("\n") + "\n"
    }

    private val MONTHS = arrayOf(
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    )

    private fun formatDate(date: java.time.LocalDate?): String {
        if (date == null) return ""
        val y = date.year % 100
        val m = date.monthValue - 1
        val d = date.dayOfMonth
        return "%02d-%s-%02d".format(y, MONTHS[m], d)
    }

    private fun truncate(text: String, width: Int): String {
        if (text.length <= width) return text
        if (width <= 2) return text.take(width)
        return text.take(width - 2) + ".."
    }

    private fun balanceToLines(bal: Balance): List<String> {
        if (bal.isEmpty) return listOf("0")
        val amounts = bal.amounts()
        val result = amounts.keys.sorted().map { amounts[it].toString() }
        return result.ifEmpty { listOf("0") }
    }

    private fun amountStr(amt: Amount?): String {
        if (amt == null || amt.isNull) return "0"
        return amt.toString()
    }

    private fun matchesAccount(accountFullname: String, patterns: List<String>): Boolean {
        if (patterns.isEmpty()) return true
        val lower = accountFullname.lowercase()
        return patterns.any { lower.contains(it.lowercase()) }
    }
}
