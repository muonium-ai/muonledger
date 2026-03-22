package muonledger

/**
 * Print command: re-output transactions in ledger format.
 */
object PrintCommand {

    fun run(journal: Journal): String {
        val sb = StringBuilder()

        for (xact in journal.transactions) {
            // Date
            val date = xact.date
            if (date != null) {
                sb.append("%04d/%02d/%02d".format(date.year, date.monthValue, date.dayOfMonth))
            }

            // Payee
            sb.append(" ${xact.payee}\n")

            // Postings
            for (post in xact.posts) {
                val acctName = post.account.fullname
                val amtStr = post.amount?.let {
                    if (!it.isNull) it.toString() else null
                }

                if (amtStr != null) {
                    // Right-align amount at column 48 (4 indent + 40 account + space)
                    val line = "    ${acctName.padEnd(40)}  $amtStr"
                    sb.append(line).append('\n')
                } else {
                    sb.append("    $acctName\n")
                }
            }

            sb.append('\n')
        }

        return sb.toString()
    }
}
