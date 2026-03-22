package muonledger

import java.io.File
import java.time.LocalDate
import java.time.format.DateTimeFormatter

fun main(args: Array<String>) {
    if (args.contains("--version")) {
        println("muonledger 0.1.0 (kotlin)")
        return
    }

    // Parse arguments
    var filePath: String? = null
    var beginDate: LocalDate? = null
    var endDate: LocalDate? = null
    var command: String? = null
    val patterns = mutableListOf<String>()

    var i = 0
    while (i < args.size) {
        when (args[i]) {
            "-f", "--file" -> {
                i++
                if (i < args.size) filePath = args[i]
            }
            "--begin" -> {
                i++
                if (i < args.size) beginDate = parseDateArg(args[i])
            }
            "--end" -> {
                i++
                if (i < args.size) endDate = parseDateArg(args[i])
            }
            else -> {
                if (command == null && !args[i].startsWith("-")) {
                    command = args[i]
                } else if (command != null && !args[i].startsWith("-")) {
                    patterns.add(args[i])
                }
            }
        }
        i++
    }

    if (filePath == null) {
        System.err.println("Error: no journal file specified (-f FILE)")
        System.exit(1)
    }

    if (command == null) {
        System.err.println("Error: no command specified (balance, register, print)")
        System.exit(1)
    }

    // Reset commodity pool for clean state
    CommodityPool.reset()

    // Parse journal
    val parser = Parser()
    val file = File(filePath!!)
    if (!file.exists()) {
        System.err.println("Error: file not found: $filePath")
        System.exit(1)
    }

    try {
        parser.parse(file)
    } catch (e: ParseError) {
        System.err.println("Error: ${e.message}")
        System.exit(1)
    }

    val journal = parser.journal

    // Dispatch command
    when (command!!.lowercase()) {
        "balance", "bal" -> {
            val opts = BalanceCommand.Options(
                begin = beginDate,
                end = endDate,
                patterns = patterns
            )
            val output = BalanceCommand.run(journal, opts)
            print(output)
        }
        "register", "reg" -> {
            val opts = RegisterCommand.Options(
                begin = beginDate,
                end = endDate,
                accountPatterns = patterns
            )
            val output = RegisterCommand.run(journal, opts)
            print(output)
        }
        "print" -> {
            val output = PrintCommand.run(journal)
            print(output)
        }
        else -> {
            System.err.println("Error: unknown command: $command")
            System.exit(1)
        }
    }
}

private fun parseDateArg(text: String): LocalDate {
    // Try YYYY-MM-DD and YYYY/MM/DD formats
    for (pattern in listOf("yyyy-MM-dd", "yyyy/MM/dd")) {
        try {
            return LocalDate.parse(text, DateTimeFormatter.ofPattern(pattern))
        } catch (_: Exception) {
            // try next
        }
    }
    System.err.println("Error: cannot parse date: $text")
    System.exit(1)
    throw IllegalStateException("unreachable")
}
