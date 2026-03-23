import Foundation

// MARK: - CLI Argument Parsing

/// Parse a date string in YYYY-MM-DD or YYYY/MM/DD format.
func parseDateArg(_ text: String) -> Date? {
    let parts: [String]
    if text.contains("-") {
        parts = text.split(separator: "-").map(String.init)
    } else if text.contains("/") {
        parts = text.split(separator: "/").map(String.init)
    } else {
        return nil
    }
    guard parts.count == 3,
          let year = Int(parts[0]),
          let month = Int(parts[1]),
          let day = Int(parts[2]) else {
        return nil
    }
    var components = DateComponents()
    components.year = year
    components.month = month
    components.day = day
    components.hour = 12 // noon to avoid timezone issues
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar.date(from: components)
}

let args = Array(CommandLine.arguments.dropFirst()) // drop program name

// Handle --version
if args.contains("--version") {
    print("muonledger 0.9.0 (swift)")
    exit(0)
}

// Parse -f / --file
var filePath: String? = nil
var command: String? = nil
var beginDate: Date? = nil
var endDate: Date? = nil
var patterns: [String] = []
var wide = false
var flat = false
var noTotal = false
var showEmpty = false
var depth = 0
var headLimit: Int? = nil
var tailLimit: Int? = nil

var i = 0
while i < args.count {
    let arg = args[i]
    switch arg {
    case "-f", "--file":
        i += 1
        if i < args.count { filePath = args[i] }
    case "--begin":
        i += 1
        if i < args.count {
            beginDate = parseDateArg(args[i])
            if beginDate == nil {
                fputs("Error: cannot parse date: \(args[i])\n", stderr)
                exit(1)
            }
        }
    case "--end":
        i += 1
        if i < args.count {
            endDate = parseDateArg(args[i])
            if endDate == nil {
                fputs("Error: cannot parse date: \(args[i])\n", stderr)
                exit(1)
            }
        }
    case "--wide", "-w":
        wide = true
    case "--flat":
        flat = true
    case "--no-total":
        noTotal = true
    case "--empty", "-E":
        showEmpty = true
    case "--depth":
        i += 1
        if i < args.count { depth = Int(args[i]) ?? 0 }
    case "--head":
        i += 1
        if i < args.count { headLimit = Int(args[i]) }
    case "--tail":
        i += 1
        if i < args.count { tailLimit = Int(args[i]) }
    default:
        if command == nil && !arg.hasPrefix("-") {
            // First non-option argument is the command
            command = arg
        } else if !arg.hasPrefix("-") {
            // Subsequent non-option arguments are patterns
            patterns.append(arg)
        }
    }
    i += 1
}

// Validate required arguments
guard let file = filePath else {
    fputs("Error: no journal file specified. Use -f <file>\n", stderr)
    exit(1)
}

guard let cmd = command else {
    fputs("Error: no command specified. Use: balance, register, or print\n", stderr)
    exit(1)
}

// Reset the global commodity pool for a clean parse
CommodityPool.resetCurrent()

// Parse the journal file
let parser = Parser()
do {
    try parser.parse(file: file)
} catch {
    fputs("Error parsing \(file): \(error)\n", stderr)
    exit(1)
}

let journal = parser.journal

// Dispatch to command
switch cmd {
case "balance", "bal":
    let opts = BalanceOptions(
        flat: flat,
        noTotal: noTotal,
        showEmpty: showEmpty,
        depth: depth,
        beginDate: beginDate,
        endDate: endDate,
        patterns: patterns
    )
    let output = balanceCommand(journal: journal, opts: opts)
    print(output, terminator: "")

case "register", "reg":
    let opts = RegisterOptions(
        wide: wide,
        head: headLimit,
        tail: tailLimit,
        beginDate: beginDate,
        endDate: endDate,
        accountPatterns: patterns
    )
    let output = registerCommand(journal: journal, opts: opts)
    print(output, terminator: "")

case "print":
    let opts = PrintOptions(patterns: patterns)
    let output = printCommand(journal: journal, opts: opts)
    print(output, terminator: "")

default:
    fputs("Error: unknown command '\(cmd)'. Use: balance, register, or print\n", stderr)
    exit(1)
}
