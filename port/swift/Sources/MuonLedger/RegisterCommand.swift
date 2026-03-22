/// Register command: list postings chronologically with running totals.
///
/// Ported from the Python/Rust reference implementations. Outputs postings in
/// chronological order, showing date, payee, account, amount, and a running
/// total that accumulates across all displayed postings.

import Foundation

// MARK: - RegisterCommand

// Default (80-column) layout
private let regDateWidth = 10
private let regPayeeWidth = 22
private let regAccountWidth = 22
private let regAmountWidth = 13
private let regTotalWidth = 13

// Wide (132-column) layout
private let wideRegDateWidth = 10
private let wideRegPayeeWidth = 35
private let wideRegAccountWidth = 39
private let wideRegAmountWidth = 24
private let wideRegTotalWidth = 24

/// Options for the register command.
struct RegisterOptions {
    var wide: Bool = false
    var head: Int? = nil
    var tail: Int? = nil
    var beginDate: Date? = nil
    var endDate: Date? = nil
    var accountPatterns: [String] = []
}

/// Format a date as YY-Mon-DD (e.g., 24-Jan-01).
private func formatRegDate(_ date: Date?) -> String {
    guard let date = date else { return "" }
    let months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    let year = calendar.component(.year, from: date) % 100
    let month = calendar.component(.month, from: date)
    let day = calendar.component(.day, from: date)
    return String(format: "%02d-%@-%02d", year, months[month - 1], day)
}

/// Truncate text to width, appending ".." if truncated.
private func truncate(_ text: String, width: Int) -> String {
    if text.count <= width { return text }
    if width <= 2 { return String(text.prefix(width)) }
    return String(text.prefix(width - 2)) + ".."
}

/// Convert a Balance to display lines, one per commodity.
private func balanceToLines(_ bal: Balance) -> [String] {
    if bal.isEmpty { return ["0"] }
    var result: [String] = []
    for key in bal.amounts.keys.sorted() {
        result.append(bal.amounts[key]!.toString())
    }
    if result.isEmpty { result.append("0") }
    return result
}

/// Format a posting amount as a string.
private func amountStr(_ amt: Amount?) -> String {
    guard let amt = amt, !amt.isNull else { return "0" }
    return amt.toString()
}

/// Check if account matches any filter pattern (case-insensitive substring).
private func matchesAccount(_ accountFullname: String, patterns: [String]) -> Bool {
    if patterns.isEmpty { return true }
    let lower = accountFullname.lowercased()
    return patterns.contains { lower.contains($0.lowercased()) }
}

/// Left-pad a string to a given width.
private func leftAlign(_ s: String, width: Int) -> String {
    if s.count >= width { return s }
    return s + String(repeating: " ", count: width - s.count)
}

/// Right-pad a string to a given width.
private func regRightAlign(_ s: String, width: Int) -> String {
    if s.count >= width { return s }
    return String(repeating: " ", count: width - s.count) + s
}

/// Generate a register report from a journal.
func registerCommand(journal: Journal, opts: RegisterOptions) -> String {
    let dateW: Int
    let payeeW: Int
    let accountW: Int
    let amountW: Int
    let totalW: Int

    if opts.wide {
        dateW = wideRegDateWidth
        payeeW = wideRegPayeeWidth
        accountW = wideRegAccountWidth
        amountW = wideRegAmountWidth
        totalW = wideRegTotalWidth
    } else {
        dateW = regDateWidth
        payeeW = regPayeeWidth
        accountW = regAccountWidth
        amountW = regAmountWidth
        totalW = regTotalWidth
    }

    var rows: [[String]] = []
    var runningTotal = Balance()

    for xact in journal.transactions {
        // Date filtering
        if let begin = opts.beginDate, let d = xact.date {
            if d < begin { continue }
        }
        if let end = opts.endDate, let d = xact.date {
            if d >= end { continue }
        }

        var firstInXact = true
        for post in xact.posts {
            guard let acct = post.account else { continue }
            let accountName = acct.fullname

            if !matchesAccount(accountName, patterns: opts.accountPatterns) {
                continue
            }

            // Update running total
            if let amt = post.amount, !amt.isNull {
                runningTotal.add(amt)
            }

            // Format date and payee (only first posting shown in xact)
            let dateStr: String
            let payeeStr: String
            if firstInXact {
                firstInXact = false
                dateStr = formatRegDate(xact.date)
                payeeStr = truncate(xact.payee, width: payeeW - 1)
            } else {
                dateStr = ""
                payeeStr = ""
            }

            // Format posting amount
            let amtStr = amountStr(post.amount)

            // Format running total (may be multi-line for multi-commodity)
            let totalLines = balanceToLines(runningTotal)

            // Build output lines
            var lines: [String] = []

            let dateCol = leftAlign(dateStr, width: dateW)
            let payeeCol = leftAlign(payeeStr, width: payeeW)
            let accountDisplay = truncate(accountName, width: accountW - 1)
            let accountCol = leftAlign(accountDisplay, width: accountW)
            let amountCol = regRightAlign(amtStr, width: amountW)

            let firstTotal = totalLines.first ?? ""
            let totalCol = regRightAlign(firstTotal, width: totalW)

            let firstLine = "\(dateCol)\(payeeCol)\(accountCol)\(amountCol)\(totalCol)"
            lines.append(firstLine)

            // Additional total lines (multi-commodity)
            for extraTotal in totalLines.dropFirst() {
                let blankPrefix = String(repeating: " ", count: dateW + payeeW + accountW + amountW)
                lines.append("\(blankPrefix)\(regRightAlign(extraTotal, width: totalW))")
            }

            rows.append(lines)
        }
    }

    // Apply --head / --tail
    if let h = opts.head {
        rows = Array(rows.prefix(h))
    }
    if let t = opts.tail {
        if t < rows.count {
            rows = Array(rows.suffix(t))
        }
    }

    // Flatten
    var outputLines: [String] = []
    for row in rows {
        outputLines.append(contentsOf: row)
    }

    if outputLines.isEmpty { return "" }

    return outputLines.joined(separator: "\n") + "\n"
}
