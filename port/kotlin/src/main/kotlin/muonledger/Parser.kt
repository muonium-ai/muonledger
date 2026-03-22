package muonledger

import java.io.File
import java.math.BigDecimal
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * Raised when the parser encounters invalid journal syntax.
 */
class ParseError(
    val msg: String,
    val lineNum: Int = 0,
    val source: String = ""
) : Exception(
    if (source.isNotEmpty() && source != "<string>")
        "$source:$lineNum: $msg"
    else if (lineNum > 0)
        "line $lineNum: $msg"
    else
        msg
)

/**
 * Textual journal parser for Ledger-format files.
 *
 * Ported from ledger's textual.cc via the Rust and Python reference
 * implementations. Reads plain-text journal files (or strings) and
 * populates a [Journal] with [Xact] and [Post] objects.
 */
class Parser {
    val journal = Journal()
    private val applyAccountStack = mutableListOf<String>()

    // Automated and periodic transactions stored as raw data
    data class AutoXact(val predicate: String, val posts: List<Post>)
    data class PeriodicXact(val period: String, val posts: List<Post>)

    val autoXacts = mutableListOf<AutoXact>()
    val periodicXacts = mutableListOf<PeriodicXact>()

    // Price directives: (date, commodity, price)
    val prices = mutableListOf<Triple<LocalDate, String, Amount>>()

    // ---- Public API ---------------------------------------------------------

    /**
     * Parse a journal file and populate the journal.
     * Returns the number of transactions parsed.
     */
    fun parse(file: File): Int {
        val text = file.readText(Charsets.UTF_8)
        return parseText(text, file.absolutePath)
    }

    /**
     * Parse journal data from a string.
     * Returns the number of transactions parsed.
     */
    fun parse(text: String, filePath: String = "<string>"): Int {
        return parseText(text, filePath)
    }

    // ---- Core parse loop ----------------------------------------------------

    private fun parseText(text: String, sourceName: String): Int {
        val lines = text.split("\n")
        var count = 0
        var i = 0

        while (i < lines.size) {
            val line = lines[i].trimEnd('\r')

            // Empty line - skip
            if (line.isEmpty() || line.isBlank()) {
                i++
                continue
            }

            val firstChar = line[0]

            // Comment lines
            if (firstChar in ";#%|*") {
                i++
                continue
            }

            // Multi-line comment block: comment ... end comment
            if (line.trimEnd() == "comment" || line.startsWith("comment ")) {
                i++
                while (i < lines.size) {
                    val cline = lines[i].trimEnd('\r')
                    if (cline.trim() == "end comment") {
                        i++
                        break
                    }
                    i++
                }
                continue
            }

            // apply account / end apply account
            if (line.startsWith("apply account ")) {
                val prefix = line.substring("apply account ".length).trim()
                if (prefix.isNotEmpty()) {
                    applyAccountStack.add(prefix)
                }
                i++
                continue
            }
            if (line.trimEnd() == "end apply account" || line.startsWith("end apply account")) {
                if (applyAccountStack.isNotEmpty()) {
                    applyAccountStack.removeLast()
                }
                i++
                continue
            }

            // end (standalone) - generic end
            if (line.startsWith("end ") || line.trim() == "end") {
                i++
                continue
            }

            // Directives starting with ! or @ (alternative prefixes, skip)
            if (firstChar == '!' || firstChar == '@') {
                i++
                continue
            }

            // alias directive
            if (line.startsWith("alias ")) {
                aliasDirective(line)
                i++
                continue
            }

            // account directive
            if (line.startsWith("account ")) {
                i = accountDirective(lines, i)
                continue
            }

            // commodity directive
            if (line.startsWith("commodity ")) {
                i = commodityDirective(lines, i)
                continue
            }

            // include directive
            if (line.startsWith("include ")) {
                includeDirective(line, sourceName)
                i++
                continue
            }

            // P price directive
            if (firstChar == 'P' && line.length > 1 && line[1] == ' ') {
                priceDirective(line, i + 1, sourceName)
                i++
                continue
            }

            // D default commodity directive (skip)
            if (firstChar == 'D' && line.length > 1 && line[1] == ' ') {
                i++
                continue
            }

            // Y / year directive (skip)
            if (firstChar == 'Y' && line.length > 1 && line[1] == ' ') {
                i++
                continue
            }
            if (line.startsWith("year ")) {
                i++
                continue
            }

            // Automated transactions (= PREDICATE)
            if (firstChar == '=') {
                val (autoXact, endI) = parseAutoXact(lines, i, sourceName)
                if (autoXact != null) {
                    autoXacts.add(autoXact)
                }
                i = endI
                continue
            }

            // Periodic transactions (~ PERIOD)
            if (firstChar == '~') {
                val (periodicXact, endI) = parsePeriodicXact(lines, i, sourceName)
                if (periodicXact != null) {
                    periodicXacts.add(periodicXact)
                }
                i = endI
                continue
            }

            // Transaction: starts with a digit (date)
            if (firstChar.isDigit()) {
                val (xact, endI) = parseXact(lines, i, sourceName)
                if (xact != null) {
                    journal.addTransaction(xact)
                    count++
                }
                i = endI
                continue
            }

            // Indented line outside transaction context or unknown - skip
            i++
        }

        return count
    }

    // ---- Directive handlers -------------------------------------------------

    private fun aliasDirective(line: String) {
        val rest = line.substring("alias ".length).trim()
        val eqPos = rest.indexOf('=')
        if (eqPos > 0) {
            val aliasName = rest.substring(0, eqPos).trim()
            val accountName = rest.substring(eqPos + 1).trim()
            if (aliasName.isNotEmpty() && accountName.isNotEmpty()) {
                journal.aliases[aliasName] = accountName
            }
        }
    }

    private fun accountDirective(lines: List<String>, start: Int): Int {
        val line = lines[start].trimEnd('\r')
        val accountName = line.substring("account ".length).trim()
        journal.root.findAccount(accountName)

        var i = start + 1
        while (i < lines.size) {
            val sline = lines[i].trimEnd('\r')
            if (sline.isEmpty() || (!sline.startsWith(' ') && !sline.startsWith('\t'))) {
                break
            }
            i++
        }
        return i
    }

    private fun commodityDirective(lines: List<String>, start: Int): Int {
        val line = lines[start].trimEnd('\r')
        val symbol = line.substring("commodity ".length).trim()
        CommodityPool.findOrCreate(symbol)

        var i = start + 1
        while (i < lines.size) {
            val sline = lines[i].trimEnd('\r')
            if (sline.isEmpty() || (!sline.startsWith(' ') && !sline.startsWith('\t'))) {
                break
            }
            i++
        }
        return i
    }

    private fun includeDirective(line: String, sourceName: String) {
        var includePath = line.substring("include ".length).trim()

        // Strip surrounding quotes
        if (includePath.length >= 2) {
            val first = includePath[0]
            val last = includePath[includePath.length - 1]
            if ((first == '"' || first == '\'') && last == first) {
                includePath = includePath.substring(1, includePath.length - 1)
            }
        }

        // Resolve relative to current file's directory
        val resolved = if (sourceName.isNotEmpty() && sourceName != "<string>") {
            val parent = File(sourceName).parentFile
            File(parent, includePath)
        } else {
            File(includePath)
        }

        if (!resolved.exists()) {
            throw ParseError("File to include was not found: ${resolved.absolutePath}")
        }

        parse(resolved)
    }

    private fun priceDirective(line: String, lineNum: Int, sourceName: String) {
        val rest = line.substring(1).trimStart()
        val dateResult = parseDateFromText(rest)
            ?: throw ParseError("Expected date in P directive", lineNum, sourceName)
        val (priceDate, dateEnd) = dateResult
        val afterDate = rest.substring(dateEnd).trimStart()
        val parts = afterDate.split(Regex("\\s+"), limit = 2)
        if (parts.size < 2) {
            throw ParseError("Expected commodity and price in P directive", lineNum, sourceName)
        }
        val commoditySymbol = parts[0]
        val priceText = parts[1].trim()
        val priceAmount = Amount.parse(priceText)
        prices.add(Triple(priceDate, commoditySymbol, priceAmount))
    }

    // ---- Automated / Periodic transaction parsing ---------------------------

    private fun parseAutoXact(
        lines: List<String>,
        start: Int,
        sourceName: String
    ): Pair<AutoXact?, Int> {
        val line = lines[start].trimEnd('\r')
        val predicate = line.substring(1).trim()
        if (predicate.isEmpty()) {
            var i = start + 1
            while (i < lines.size) {
                val pline = lines[i].trimEnd('\r')
                if (pline.isEmpty()) break
                val fc = pline[0]
                if (fc != ' ' && fc != '\t' && fc != ';') break
                i++
            }
            return Pair(null, i)
        }

        val posts = mutableListOf<Post>()
        var i = start + 1
        while (i < lines.size) {
            val pline = lines[i].trimEnd('\r')
            if (pline.isEmpty()) break
            val fc = pline[0]
            if (fc != ' ' && fc != '\t' && fc != ';') break

            val stripped = pline.trimStart()
            if (stripped.startsWith(';')) {
                i++
                continue
            }

            val post = parsePost(pline, i + 1, sourceName)
            if (post != null) posts.add(post)
            i++
        }

        return Pair(AutoXact(predicate, posts), i)
    }

    private fun parsePeriodicXact(
        lines: List<String>,
        start: Int,
        sourceName: String
    ): Pair<PeriodicXact?, Int> {
        val line = lines[start].trimEnd('\r')
        val period = line.substring(1).trim()
        if (period.isEmpty()) {
            var i = start + 1
            while (i < lines.size) {
                val pline = lines[i].trimEnd('\r')
                if (pline.isEmpty()) break
                val fc = pline[0]
                if (fc != ' ' && fc != '\t' && fc != ';') break
                i++
            }
            return Pair(null, i)
        }

        val posts = mutableListOf<Post>()
        var i = start + 1
        while (i < lines.size) {
            val pline = lines[i].trimEnd('\r')
            if (pline.isEmpty()) break
            val fc = pline[0]
            if (fc != ' ' && fc != '\t' && fc != ';') break

            val stripped = pline.trimStart()
            if (stripped.startsWith(';')) {
                i++
                continue
            }

            val post = parsePost(pline, i + 1, sourceName)
            if (post != null) posts.add(post)
            i++
        }

        return Pair(PeriodicXact(period, posts), i)
    }

    // ---- Transaction parsing ------------------------------------------------

    private fun parseXact(
        lines: List<String>,
        start: Int,
        sourceName: String
    ): Pair<Xact?, Int> {
        val line = lines[start].trimEnd('\r')
        val lineNum = start + 1

        var rest = line

        // 1. Parse date(s): DATE[=AUX_DATE]
        val dateResult = parseDateFromText(rest)
            ?: throw ParseError("Expected date", lineNum, sourceName)
        val (primaryDate, dateEnd) = dateResult
        rest = rest.substring(dateEnd)

        // Aux date after =
        @Suppress("UNUSED_VALUE")
        var auxDate: LocalDate? = null
        if (rest.startsWith("=")) {
            rest = rest.substring(1)
            val auxResult = parseDateFromText(rest)
                ?: throw ParseError("Expected auxiliary date after '='", lineNum, sourceName)
            auxDate = auxResult.first
            rest = rest.substring(auxResult.second)
        }

        rest = rest.trimStart()

        // 2. Parse optional state marker
        var state = TransactionState.UNCLEARED
        if (rest.startsWith("*")) {
            state = TransactionState.CLEARED
            rest = rest.substring(1).trimStart()
        } else if (rest.startsWith("!")) {
            state = TransactionState.PENDING
            rest = rest.substring(1).trimStart()
        }

        // 3. Parse optional code: (CODE)
        @Suppress("UNUSED_VALUE")
        var code: String? = null
        if (rest.startsWith("(")) {
            val close = rest.indexOf(')')
            if (close >= 0) {
                code = rest.substring(1, close)
                rest = rest.substring(close + 1).trimStart()
            }
        }

        // 4. Parse payee and optional inline note
        // Split at | for payee | note  (but also handle ; for inline comment)
        var xactNote: String? = null
        val payee: String

        // First check for semicolon (inline comment)
        val semiPos = rest.indexOf(';')
        if (semiPos >= 0) {
            val beforeSemi = rest.substring(0, semiPos).trimEnd()
            xactNote = rest.substring(semiPos + 1).trim()

            // Now check for | within the payee portion
            val pipePos = beforeSemi.indexOf('|')
            payee = if (pipePos >= 0) {
                val noteFromPipe = beforeSemi.substring(pipePos + 1).trim()
                if (xactNote.isNullOrEmpty()) xactNote = noteFromPipe
                else xactNote = "$noteFromPipe\n$xactNote"
                beforeSemi.substring(0, pipePos).trimEnd()
            } else {
                beforeSemi
            }
        } else {
            // Check for | in payee
            val pipePos = rest.indexOf('|')
            if (pipePos >= 0) {
                payee = rest.substring(0, pipePos).trimEnd()
                xactNote = rest.substring(pipePos + 1).trim()
            } else {
                payee = rest.trimEnd()
            }
        }

        // Build the transaction
        val xact = Xact(
            date = primaryDate,
            state = state,
            payee = payee,
            note = xactNote
        )

        // Parse posting lines
        var i = start + 1
        while (i < lines.size) {
            val pline = lines[i].trimEnd('\r')

            // Blank line or non-indented line ends the transaction
            if (pline.isEmpty()) break
            val fc = pline[0]
            if (fc != ' ' && fc != '\t') break

            val stripped = pline.trimStart()

            // Comment line attached to the transaction or previous posting
            if (stripped.startsWith(';')) {
                val commentText = stripped.substring(1).trim()
                // Attach to last posting if exists, else to transaction
                if (xact.posts.isNotEmpty()) {
                    val target = xact.posts.last()
                    if (target.note != null) {
                        target.note = "${target.note}\n$commentText"
                    } else {
                        target.note = commentText
                    }
                } else {
                    if (xact.note != null) {
                        xact.note = "${xact.note}\n$commentText"
                    } else {
                        xact.note = commentText
                    }
                }
                i++
                continue
            }

            // Parse as posting
            val post = parsePost(pline, i + 1, sourceName)
            if (post != null) {
                xact.addPost(post)
            }

            i++
        }

        return Pair(xact, i)
    }

    // ---- Posting parsing ----------------------------------------------------

    private fun parsePost(
        line: String,
        lineNum: Int,
        sourceName: String
    ): Post? {
        var rest = line.trimStart()
        if (rest.isEmpty()) return null

        // 1. Optional state marker on the posting itself
        if (rest.startsWith("*")) {
            rest = rest.substring(1).trimStart()
        } else if (rest.startsWith("!")) {
            rest = rest.substring(1).trimStart()
        }

        // 2. Detect virtual account brackets
        var isVirtual = false
        var isBalanceVirtual = false
        val accountName: String

        if (rest.startsWith("(")) {
            // Virtual posting (does not need to balance)
            isVirtual = true
            isBalanceVirtual = false
            val close = rest.indexOf(')')
            if (close < 0) {
                throw ParseError("Expected ')' for virtual account", lineNum, sourceName)
            }
            accountName = rest.substring(1, close).trim()
            rest = rest.substring(close + 1)
        } else if (rest.startsWith("[")) {
            // Balanced virtual posting (must balance)
            isVirtual = true
            isBalanceVirtual = true
            val close = rest.indexOf(']')
            if (close < 0) {
                throw ParseError("Expected ']' for balanced virtual account", lineNum, sourceName)
            }
            accountName = rest.substring(1, close).trim()
            rest = rest.substring(close + 1)
        } else {
            // Real account: name ends at two consecutive spaces, tab, or semicolon
            val (acct, remainder) = splitAccountAndRest(rest)
            accountName = acct
            rest = remainder
        }

        // Apply account prefix from apply account stack
        val prefixedName = if (applyAccountStack.isNotEmpty()) {
            val prefix = applyAccountStack.joinToString(":")
            "$prefix:$accountName"
        } else {
            accountName
        }

        // Resolve alias
        val resolvedName = journal.aliases[prefixedName] ?: prefixedName
        val account = journal.root.findAccount(resolvedName)!!

        // 3. Separate amount portion from inline comment
        rest = rest.trimStart()
        var postNote: String? = null

        val amountText: String
        if (rest.isNotEmpty()) {
            val semiPos = findCommentStart(rest)
            if (semiPos >= 0) {
                amountText = rest.substring(0, semiPos).trimEnd()
                postNote = rest.substring(semiPos + 1).trim()
            } else {
                amountText = rest.trimEnd()
            }
        } else {
            amountText = ""
        }

        // 4. Parse amount, lot annotations, cost, balance assertion
        var amount: Amount? = null
        var cost: Amount? = null
        var assignedAmount: Amount? = null
        var lotPrice: Amount? = null

        if (amountText.isNotEmpty()) {
            // Split off balance assertion (= AMOUNT) first
            val (amountCostText, assertionText) = splitBalanceAssertion(amountText)

            if (assertionText != null) {
                assignedAmount = Amount.parse(assertionText)
            }

            // Split off cost (@, @@)
            val (amtPart, costPart, costIsTotal) = splitAmountAndCost(amountCostText)

            // Extract lot annotation from the amount portion
            val (cleanAmtPart, lotPriceAmt) = parseLotAnnotation(amtPart)

            if (lotPriceAmt != null) {
                lotPrice = lotPriceAmt
            }

            if (cleanAmtPart.isNotEmpty()) {
                amount = Amount.parse(cleanAmtPart)
            }

            if (costPart != null) {
                val costAmount = Amount.parse(costPart)
                if (costIsTotal) {
                    cost = costAmount
                } else {
                    // Per-unit cost: total cost = |quantity| * cost_per_unit
                    if (amount != null && !amount.isNull) {
                        val absQty = amount.abs().quantity!!
                        cost = costAmount * absQty
                    } else {
                        cost = costAmount
                    }
                }
            }

            // If lot price but no explicit @ cost, derive cost
            if (cost == null && lotPrice != null && amount != null && !amount.isNull) {
                val absQty = amount.abs().quantity!!
                cost = lotPrice!! * absQty
            }
        }

        // Build the Post
        return Post(
            account = account,
            amount = amount,
            cost = cost,
            assignedAmount = assignedAmount,
            isVirtual = isVirtual,
            isBalanceVirtual = isBalanceVirtual,
            lotPrice = lotPrice,
            note = postNote
        )
    }

    // ---- Helper functions ---------------------------------------------------

    companion object {
        private val DATE_RE = Regex("""^(\d{4})[/-](\d{1,2})[/-](\d{1,2})""")

        /**
         * Parse a date from the beginning of text.
         * Returns (LocalDate, endIndex) or null.
         */
        fun parseDateFromText(text: String): Pair<LocalDate, Int>? {
            val match = DATE_RE.find(text.trimStart()) ?: return null
            val y = match.groupValues[1].toInt()
            val m = match.groupValues[2].toInt()
            val d = match.groupValues[3].toInt()
            val date = LocalDate.of(y, m, d)
            // Account for any leading whitespace trimmed
            val leadingSpaces = text.length - text.trimStart().length
            return Pair(date, leadingSpaces + match.range.last + 1)
        }

        /**
         * Split a posting line into account name and the remainder.
         * Account names end at two consecutive spaces, a tab, a semicolon, or end of line.
         */
        fun splitAccountAndRest(text: String): Pair<String, String> {
            var i = 0
            while (i < text.length) {
                val ch = text[i]
                // Tab separates account from amount
                if (ch == '\t') {
                    return Pair(text.substring(0, i).trimEnd(), text.substring(i + 1))
                }
                // Two consecutive spaces
                if (ch == ' ' && i + 1 < text.length && text[i + 1] == ' ') {
                    return Pair(text.substring(0, i).trimEnd(), text.substring(i + 2))
                }
                // Semicolon starts a comment
                if (ch == ';') {
                    return Pair(text.substring(0, i).trimEnd(), text.substring(i))
                }
                i++
            }
            // Entire line is the account name
            return Pair(text.trimEnd(), "")
        }

        /**
         * Find the position of an inline comment `;` in amount text.
         * Returns -1 if no comment found. Respects quoted strings.
         */
        fun findCommentStart(text: String): Int {
            var inQuote = false
            for (i in text.indices) {
                val ch = text[i]
                if (ch == '"') {
                    inQuote = !inQuote
                } else if (!inQuote && ch == ';') {
                    return i
                }
            }
            return -1
        }

        /**
         * Split an amount+cost string at `@` or `@@`.
         * Returns (amount_text, cost_text_or_null, is_total_cost).
         */
        fun splitAmountAndCost(text: String): Triple<String, String?, Boolean> {
            var inQuote = false
            var i = 0
            while (i < text.length) {
                val ch = text[i]
                if (ch == '"') {
                    inQuote = !inQuote
                } else if (!inQuote) {
                    // Skip over lot annotation brackets
                    if (ch == '{') {
                        val close = text.indexOf('}', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '[') {
                        val close = text.indexOf(']', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '(') {
                        val close = text.indexOf(')', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '@') {
                        if (i + 1 < text.length && text[i + 1] == '@') {
                            val amt = text.substring(0, i).trimEnd()
                            val cost = text.substring(i + 2).trimStart()
                            return Triple(amt, cost, true)
                        } else {
                            val amt = text.substring(0, i).trimEnd()
                            val cost = text.substring(i + 1).trimStart()
                            return Triple(amt, cost, false)
                        }
                    }
                }
                i++
            }
            return Triple(text, null, false)
        }

        /**
         * Split off a balance assertion `= AMOUNT` from the amount text.
         * Returns (amount_and_cost_text, assertion_amount_text_or_null).
         */
        fun splitBalanceAssertion(text: String): Pair<String, String?> {
            var inQuote = false
            var i = 0
            while (i < text.length) {
                val ch = text[i]
                if (ch == '"') {
                    inQuote = !inQuote
                } else if (!inQuote) {
                    // Skip over brackets
                    if (ch == '{') {
                        val close = text.indexOf('}', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '[') {
                        val close = text.indexOf(']', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '(') {
                        val close = text.indexOf(')', i + 1)
                        if (close >= 0) { i = close + 1; continue }
                    } else if (ch == '=') {
                        // Skip == (not a balance assertion)
                        if (i + 1 < text.length && text[i + 1] == '=') {
                            i += 2
                            continue
                        }
                        val lhs = text.substring(0, i).trimEnd()
                        val rhs = text.substring(i + 1).trimStart()
                        return Pair(lhs, if (rhs.isEmpty()) null else rhs)
                    }
                }
                i++
            }
            return Pair(text, null)
        }

        /**
         * Parse lot annotation `{price}` from an amount string.
         * Returns (amount_text_without_annotation, lot_price_or_null).
         */
        fun parseLotAnnotation(text: String): Pair<String, Amount?> {
            var inQuote = false
            var annStart: Int? = null
            for (i in text.indices) {
                val ch = text[i]
                if (ch == '"') {
                    inQuote = !inQuote
                } else if (!inQuote && ch == '{') {
                    annStart = i
                    break
                }
            }

            if (annStart == null) return Pair(text, null)

            val amountPart = text.substring(0, annStart).trimEnd()
            val restPart = text.substring(annStart)

            // Find the closing }
            val close = restPart.indexOf('}')
            if (close < 0) return Pair(text, null)

            var priceText = restPart.substring(1, close).trim()
            // Handle fixated price {=price}
            if (priceText.startsWith("=")) {
                priceText = priceText.substring(1).trim()
            }

            return if (priceText.isNotEmpty()) {
                val lotPrice = Amount.parse(priceText)
                Pair(amountPart, lotPrice)
            } else {
                Pair(text, null)
            }
        }
    }
}
