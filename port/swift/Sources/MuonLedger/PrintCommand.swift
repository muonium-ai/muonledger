/// Print command: re-output parsed transactions in standard ledger format.
///
/// Outputs transactions in a clean, canonical format matching C++ ledger's
/// print command output.

import Foundation

// MARK: - PrintCommand

/// Options for the print command.
struct PrintOptions {
    var patterns: [String] = []
}

/// Format a date as YYYY/MM/DD for print output.
private func formatPrintDate(_ date: Date?) -> String {
    guard let date = date else { return "" }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    let year = calendar.component(.year, from: date)
    let month = calendar.component(.month, from: date)
    let day = calendar.component(.day, from: date)
    return String(format: "%04d/%02d/%02d", year, month, day)
}

/// Generate a print report from a journal.
func printCommand(journal: Journal, opts: PrintOptions) -> String {
    var output = ""

    for xact in journal.transactions {
        // Date line
        var dateLine = formatPrintDate(xact.date)

        // State marker
        switch xact.state {
        case .cleared:
            dateLine += " *"
        case .pending:
            dateLine += " !"
        case .uncleared:
            break
        }

        // Payee
        dateLine += " \(xact.payee)"

        output += dateLine + "\n"

        // Postings
        for post in xact.posts {
            guard let acct = post.account else { continue }
            let accountName = acct.fullname

            let amtStr: String
            if let amt = post.amount, !amt.isNull {
                amtStr = amt.toString()
            } else {
                amtStr = ""
            }

            if amtStr.isEmpty {
                output += "    \(accountName)\n"
            } else {
                // Right-align amount at roughly column 48
                let acctWidth = 40
                if accountName.count < acctWidth {
                    let padding = String(repeating: " ", count: acctWidth - accountName.count)
                    output += "    \(accountName)\(padding)  \(amtStr)\n"
                } else {
                    output += "    \(accountName)  \(amtStr)\n"
                }
            }
        }

        output += "\n"
    }

    return output
}
