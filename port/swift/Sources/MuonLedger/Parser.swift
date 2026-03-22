/// Textual journal parser for Ledger-format files.
///
/// Ported from ledger's `textual.cc` via the Rust reference implementation.
/// The `Parser` reads plain-text journal files (or strings) and populates
/// a `Journal` with `Xact` and `Post` objects.

import Foundation

// MARK: - ParseError

public enum ParseError: Error, CustomStringConvertible {
    case invalidSyntax(String, Int, String)
    case fileNotFound(String)

    public var description: String {
        switch self {
        case .invalidSyntax(let message, let line, let source):
            if source.isEmpty {
                return "line \(line): \(message)"
            }
            return "\(source):\(line): \(message)"
        case .fileNotFound(let path):
            return "File not found: \(path)"
        }
    }
}

// MARK: - Parser

/// Parse Ledger-format textual journal files.
public class Parser {
    /// The journal being populated by parsing.
    public let journal: Journal

    /// Stack for `apply account` directives.
    private var applyAccountStack: [String] = []

    /// Account name aliases from `alias X=Y`.
    private var aliases: [String: String] = [:]

    public init() {
        self.journal = Journal()
    }

    /// Convenience initializer with an existing journal.
    public init(journal: Journal) {
        self.journal = journal
    }

    // MARK: - Public API

    /// Parse a journal file at the given path.
    public func parse(file path: String) throws {
        let content: String
        do {
            content = try String(contentsOfFile: path, encoding: .utf8)
        } catch {
            throw ParseError.fileNotFound(path)
        }
        try parse(text: content, filePath: path)
    }

    /// Parse journal text and populate the journal.
    @discardableResult
    public func parse(text: String, filePath: String = "<string>") throws -> Int {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
            .map { String($0) }
        var count = 0
        var i = 0

        while i < lines.count {
            let line = lines[i].hasSuffix("\r")
                ? String(lines[i].dropLast())
                : lines[i]

            // Empty / blank line
            if line.isEmpty || line.allSatisfy({ $0.isWhitespace }) {
                i += 1
                continue
            }

            let firstChar = line.first!

            // Comment lines at top level
            if ";#%|*".contains(firstChar) {
                i += 1
                continue
            }

            // Multi-line comment block
            if line.trimmingCharacters(in: .whitespaces) == "comment" ||
               line.hasPrefix("comment ") {
                i += 1
                while i < lines.count {
                    let cline = lines[i].trimmingCharacters(in: .init(charactersIn: "\r"))
                    if cline.trimmingCharacters(in: .whitespaces) == "end comment" {
                        i += 1
                        break
                    }
                    i += 1
                }
                continue
            }

            // apply account / end apply account
            if line.hasPrefix("apply account ") {
                let prefix = String(line.dropFirst("apply account ".count))
                    .trimmingCharacters(in: .whitespaces)
                if !prefix.isEmpty {
                    applyAccountStack.append(prefix)
                }
                i += 1
                continue
            }
            if line.trimmingCharacters(in: .whitespaces) == "end apply account" {
                if !applyAccountStack.isEmpty {
                    applyAccountStack.removeLast()
                }
                i += 1
                continue
            }

            // alias directive
            if line.hasPrefix("alias ") {
                parseAliasDirective(line)
                i += 1
                continue
            }

            // include directive
            if line.hasPrefix("include ") {
                try parseIncludeDirective(line, filePath: filePath)
                i += 1
                continue
            }

            // P price directive
            if firstChar == "P" && line.count > 1 &&
               line[line.index(after: line.startIndex)] == " " {
                // Store price but don't process further
                i += 1
                continue
            }

            // D default commodity directive
            if firstChar == "D" && line.count > 1 &&
               line[line.index(after: line.startIndex)] == " " {
                i += 1
                continue
            }

            // account directive (skip sub-directives)
            if line.hasPrefix("account ") {
                i += 1
                while i < lines.count {
                    let sline = lines[i].trimmingCharacters(in: .init(charactersIn: "\r"))
                    if sline.isEmpty ||
                       (!sline.hasPrefix(" ") && !sline.hasPrefix("\t")) {
                        break
                    }
                    i += 1
                }
                continue
            }

            // commodity directive (skip sub-directives)
            if line.hasPrefix("commodity ") {
                i += 1
                while i < lines.count {
                    let sline = lines[i].trimmingCharacters(in: .init(charactersIn: "\r"))
                    if sline.isEmpty ||
                       (!sline.hasPrefix(" ") && !sline.hasPrefix("\t")) {
                        break
                    }
                    i += 1
                }
                continue
            }

            // Automated transaction (= PREDICATE)
            if firstChar == "=" {
                i = try parseAutoXact(lines: lines, start: i, filePath: filePath)
                continue
            }

            // Periodic transaction (~ PERIOD)
            if firstChar == "~" {
                i = try parsePeriodicXact(lines: lines, start: i, filePath: filePath)
                continue
            }

            // Transaction: starts with a digit (date)
            if firstChar.isNumber {
                let (xact, endI) = try parseXact(lines: lines, start: i, filePath: filePath)
                if let xact = xact {
                    if try journal.addTransaction(xact) {
                        count += 1
                    }
                }
                i = endI
                continue
            }

            // Indented line outside transaction context — skip
            if firstChar == " " || firstChar == "\t" {
                i += 1
                continue
            }

            // Unknown line — skip
            i += 1
        }

        return count
    }

    // MARK: - Directive Handlers

    private func parseAliasDirective(_ line: String) {
        let rest = String(line.dropFirst("alias ".count))
            .trimmingCharacters(in: .whitespaces)
        guard let eqIdx = rest.firstIndex(of: "=") else { return }
        let aliasName = String(rest[rest.startIndex..<eqIdx])
            .trimmingCharacters(in: .whitespaces)
        let accountName = String(rest[rest.index(after: eqIdx)...])
            .trimmingCharacters(in: .whitespaces)
        if !aliasName.isEmpty && !accountName.isEmpty {
            aliases[aliasName] = accountName
            journal.aliases[aliasName] = accountName
        }
    }

    private func parseIncludeDirective(_ line: String, filePath: String) throws {
        var includePath = String(line.dropFirst("include ".count))
            .trimmingCharacters(in: .whitespaces)

        // Strip surrounding quotes
        if includePath.count >= 2 {
            let first = includePath.first!
            let last = includePath.last!
            if (first == "\"" || first == "'") && last == first {
                includePath = String(includePath.dropFirst().dropLast())
            }
        }

        // Resolve relative to current file's directory
        let resolved: String
        if filePath != "<string>" && !filePath.isEmpty {
            let parentDir = (filePath as NSString).deletingLastPathComponent
            resolved = (parentDir as NSString).appendingPathComponent(includePath)
        } else {
            resolved = includePath
        }

        try parse(file: resolved)
    }

    // MARK: - Automated Transaction

    private func parseAutoXact(
        lines: [String],
        start: Int,
        filePath: String
    ) throws -> Int {
        // Skip the '=' and extract predicate
        let line = cleanLine(lines[start])
        _ = String(line.dropFirst()).trimmingCharacters(in: .whitespaces)

        var i = start + 1
        while i < lines.count {
            let pline = cleanLine(lines[i])
            if pline.isEmpty { break }
            let fc = pline.first!
            if fc != " " && fc != "\t" && fc != ";" { break }
            i += 1
        }
        return i
    }

    // MARK: - Periodic Transaction

    private func parsePeriodicXact(
        lines: [String],
        start: Int,
        filePath: String
    ) throws -> Int {
        let line = cleanLine(lines[start])
        _ = String(line.dropFirst()).trimmingCharacters(in: .whitespaces)

        var i = start + 1
        while i < lines.count {
            let pline = cleanLine(lines[i])
            if pline.isEmpty { break }
            let fc = pline.first!
            if fc != " " && fc != "\t" && fc != ";" { break }
            i += 1
        }
        return i
    }

    // MARK: - Transaction Parsing

    private func parseXact(
        lines: [String],
        start: Int,
        filePath: String
    ) throws -> (Xact?, Int) {
        let line = cleanLine(lines[start])
        let lineNum = start + 1

        var rest = line[line.startIndex...]

        // 1. Parse date
        guard let (date, dateEnd) = parseDate(rest) else {
            throw ParseError.invalidSyntax(
                "Expected date", lineNum, filePath
            )
        }
        rest = rest[dateEnd...]

        // Skip auxiliary date (=DATE)
        if rest.hasPrefix("=") {
            rest = rest[rest.index(after: rest.startIndex)...]
            if let (_, auxEnd) = parseDate(rest) {
                rest = rest[auxEnd...]
            }
        }

        // Trim leading whitespace
        rest = rest.drop(while: { $0.isWhitespace })

        // 2. Parse optional state marker
        var state: TransactionState = .uncleared
        if rest.hasPrefix("*") {
            state = .cleared
            rest = rest[rest.index(after: rest.startIndex)...]
                .drop(while: { $0.isWhitespace })
        } else if rest.hasPrefix("!") {
            state = .pending
            rest = rest[rest.index(after: rest.startIndex)...]
                .drop(while: { $0.isWhitespace })
        }

        // 3. Parse optional code: (CODE)
        var code: String? = nil
        if rest.hasPrefix("(") {
            if let closeIdx = rest.firstIndex(of: ")") {
                code = String(rest[rest.index(after: rest.startIndex)..<closeIdx])
                rest = rest[rest.index(after: closeIdx)...]
                    .drop(while: { $0.isWhitespace })
            }
        }

        // 4. Parse payee and optional note (separated by ; or |)
        let restStr = String(rest)
        var payee: String
        var xactNote: String? = nil

        // Check for | separator first (payee | note)
        if let pipeIdx = restStr.firstIndex(of: "|") {
            // Only use pipe as separator if not after a semicolon
            let beforePipe = String(restStr[restStr.startIndex..<pipeIdx])
            if !beforePipe.contains(";") {
                payee = beforePipe.trimmingCharacters(in: .whitespaces)
                xactNote = String(restStr[restStr.index(after: pipeIdx)...])
                    .trimmingCharacters(in: .whitespaces)
            } else {
                // Semicolon comes first
                let semiIdx = restStr.firstIndex(of: ";")!
                payee = String(restStr[restStr.startIndex..<semiIdx])
                    .trimmingCharacters(in: .whitespaces)
                xactNote = String(restStr[restStr.index(after: semiIdx)...])
                    .trimmingCharacters(in: .whitespaces)
            }
        } else if let semiIdx = restStr.firstIndex(of: ";") {
            payee = String(restStr[restStr.startIndex..<semiIdx])
                .trimmingCharacters(in: .whitespaces)
            xactNote = String(restStr[restStr.index(after: semiIdx)...])
                .trimmingCharacters(in: .whitespaces)
        } else {
            payee = restStr.trimmingCharacters(in: .whitespaces)
        }

        // Build the transaction
        let xact = Xact(payee: payee)
        xact.date = date
        xact.state = state
        xact.code = code
        xact.note = xactNote

        // Parse posting lines
        var i = start + 1
        while i < lines.count {
            let pline = cleanLine(lines[i])

            // Blank line or non-indented line ends the transaction
            if pline.isEmpty { break }
            let fc = pline.first!
            if fc != " " && fc != "\t" { break }

            let stripped = pline.trimmingCharacters(in: .whitespaces)

            // Comment line attached to transaction or previous posting
            if stripped.hasPrefix(";") {
                let commentText = String(stripped.dropFirst())
                    .trimmingCharacters(in: .whitespaces)

                if !xact.posts.isEmpty {
                    let target = xact.posts.last!
                    if let existing = target.note {
                        target.note = "\(existing)\n\(commentText)"
                    } else {
                        target.note = commentText
                    }
                } else {
                    if let existing = xact.note {
                        xact.note = "\(existing)\n\(commentText)"
                    } else {
                        xact.note = commentText
                    }
                }
                i += 1
                continue
            }

            // Parse as posting
            if let post = try parsePost(stripped, lineNum: i + 1, filePath: filePath) {
                xact.addPost(post)
            }

            i += 1
        }

        return (xact, i)
    }

    // MARK: - Posting Parsing

    private func parsePost(
        _ text: String,
        lineNum: Int,
        filePath: String
    ) throws -> Post? {
        var rest = text
        if rest.isEmpty { return nil }

        // 1. Optional state marker on the posting itself
        if rest.hasPrefix("*") {
            rest = String(rest.dropFirst()).trimmingCharacters(
                in: .init(charactersIn: " \t"))
        } else if rest.hasPrefix("!") {
            rest = String(rest.dropFirst()).trimmingCharacters(
                in: .init(charactersIn: " \t"))
        }

        // 2. Detect virtual account brackets
        var isVirtual = false
        var mustBalance = true
        var accountName: String

        if rest.hasPrefix("(") {
            // Virtual posting (does not need to balance)
            isVirtual = true
            mustBalance = false
            guard let closeIdx = rest.firstIndex(of: ")") else {
                throw ParseError.invalidSyntax(
                    "Expected ')' for virtual account", lineNum, filePath
                )
            }
            accountName = String(rest[rest.index(after: rest.startIndex)..<closeIdx])
                .trimmingCharacters(in: .whitespaces)
            rest = String(rest[rest.index(after: closeIdx)...])
        } else if rest.hasPrefix("[") {
            // Balanced virtual posting (must balance)
            isVirtual = true
            mustBalance = true
            guard let closeIdx = rest.firstIndex(of: "]") else {
                throw ParseError.invalidSyntax(
                    "Expected ']' for balanced virtual account", lineNum, filePath
                )
            }
            accountName = String(rest[rest.index(after: rest.startIndex)..<closeIdx])
                .trimmingCharacters(in: .whitespaces)
            rest = String(rest[rest.index(after: closeIdx)...])
        } else {
            // Real account: name ends at 2+ spaces, tab, or semicolon
            let (acct, remainder) = splitAccountAndRest(rest)
            accountName = acct
            rest = remainder
        }

        // Resolve aliases
        if let resolved = aliases[accountName] {
            accountName = resolved
        }

        // Apply account prefix
        if !applyAccountStack.isEmpty {
            let prefix = applyAccountStack.joined(separator: ":")
            accountName = "\(prefix):\(accountName)"
        }

        // Look up or create the account
        let account = journal.findOrCreateAccount(accountName)

        // 3. Separate amount portion from inline comment
        rest = rest.trimmingCharacters(in: .init(charactersIn: " \t"))
        var postNote: String? = nil
        var amountText: String

        if !rest.isEmpty {
            if let semiPos = findCommentStart(rest) {
                amountText = String(rest[rest.startIndex..<semiPos])
                    .trimmingCharacters(in: .whitespaces)
                let commentText = String(rest[rest.index(after: semiPos)...])
                    .trimmingCharacters(in: .whitespaces)
                if !commentText.isEmpty {
                    postNote = commentText
                }
            } else {
                amountText = rest.trimmingCharacters(in: .whitespaces)
            }
        } else {
            amountText = ""
        }

        // 4. Parse amount, cost, lot annotations, balance assertion
        var amount: Amount? = nil
        var cost: Amount? = nil
        var assignedAmount: Amount? = nil
        var lotPrice: Amount? = nil

        if !amountText.isEmpty {
            // Split off balance assertion (= AMOUNT)
            let (amountCostText, assertionText) = splitBalanceAssertion(amountText)

            if let assertText = assertionText {
                if !assertText.isEmpty {
                    assignedAmount = try Amount(parsing: assertText)
                }
            }

            // Split off cost (@, @@)
            let (amtPart, costPart, costIsTotal) = splitAmountAndCost(amountCostText)

            // Extract lot annotations from the amount portion
            let (amtClean, lotPriceAmt) = parseLotAnnotation(amtPart)

            if !amtClean.isEmpty {
                amount = try Amount(parsing: amtClean)
            }

            if let costText = costPart, !costText.isEmpty {
                let costAmount = try Amount(parsing: costText)
                if costIsTotal {
                    cost = costAmount
                } else {
                    // Per-unit cost: total = |amount| * cost_per_unit
                    if let amt = amount, !amt.isNull {
                        let absAmt = amt.abs().number()
                        cost = absAmt * costAmount
                    } else {
                        cost = costAmount
                    }
                }
            }

            lotPrice = lotPriceAmt

            // If lot annotation has a price but no explicit @ cost, derive cost
            if cost == nil, let lp = lotPrice, let amt = amount, !amt.isNull {
                let absAmt = amt.abs().number()
                cost = absAmt * lp
            }
        }

        // Build the Post
        let post = Post(account: account, amount: amount)
        post.cost = cost
        post.assignedAmount = assignedAmount
        post.lotPrice = lotPrice
        post.note = postNote

        if isVirtual {
            if mustBalance {
                post.makeBalanceVirtual()
            } else {
                post.makeVirtual()
            }
        }

        return post
    }

    // MARK: - Helpers

    /// Remove trailing \r from a line.
    private func cleanLine(_ line: String) -> String {
        line.hasSuffix("\r") ? String(line.dropLast()) : line
    }

    /// Parse a date from the beginning of a substring.
    /// Supports YYYY-MM-DD and YYYY/MM/DD.
    /// Returns the Date and the index past the date.
    private func parseDate(_ text: Substring) -> (Date, Substring.Index)? {
        // Quick check: need at least 8 chars (YYYY-M-D)
        guard text.count >= 8 else { return nil }

        var idx = text.startIndex
        // Scan year (4 digits)
        var yearStr = ""
        for _ in 0..<4 {
            guard idx < text.endIndex, text[idx].isNumber else { return nil }
            yearStr.append(text[idx])
            idx = text.index(after: idx)
        }
        // Separator
        guard idx < text.endIndex else { return nil }
        let sep = text[idx]
        guard sep == "-" || sep == "/" else { return nil }
        idx = text.index(after: idx)

        // Scan month (1-2 digits)
        var monthStr = ""
        while idx < text.endIndex && text[idx].isNumber && monthStr.count < 2 {
            monthStr.append(text[idx])
            idx = text.index(after: idx)
        }
        guard !monthStr.isEmpty else { return nil }

        // Separator
        guard idx < text.endIndex, text[idx] == sep else { return nil }
        idx = text.index(after: idx)

        // Scan day (1-2 digits)
        var dayStr = ""
        while idx < text.endIndex && text[idx].isNumber && dayStr.count < 2 {
            dayStr.append(text[idx])
            idx = text.index(after: idx)
        }
        guard !dayStr.isEmpty else { return nil }

        guard let year = Int(yearStr),
              let month = Int(monthStr),
              let day = Int(dayStr) else { return nil }

        var components = DateComponents()
        components.year = year
        components.month = month
        components.day = day
        components.hour = 12 // noon to avoid timezone issues

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!

        guard let date = calendar.date(from: components) else { return nil }

        return (date, idx)
    }

    /// Split a posting line into account name and remainder.
    /// Account names end at two consecutive spaces, a tab, a semicolon, or end of line.
    private func splitAccountAndRest(_ text: String) -> (String, String) {
        var i = text.startIndex
        while i < text.endIndex {
            let ch = text[i]
            // Tab separates account from amount
            if ch == "\t" {
                let acct = String(text[text.startIndex..<i])
                    .trimmingCharacters(in: .whitespaces)
                let remainder = String(text[text.index(after: i)...])
                return (acct, remainder)
            }
            // Two consecutive spaces
            let next = text.index(after: i)
            if ch == " " && next < text.endIndex && text[next] == " " {
                let acct = String(text[text.startIndex..<i])
                    .trimmingCharacters(in: .whitespaces)
                let remainder = String(text[text.index(after: next)...])
                return (acct, remainder)
            }
            // Semicolon starts a comment
            if ch == ";" {
                let acct = String(text[text.startIndex..<i])
                    .trimmingCharacters(in: .whitespaces)
                return (acct, String(text[i...]))
            }
            i = text.index(after: i)
        }
        // Entire text is the account name
        return (text.trimmingCharacters(in: .whitespaces), "")
    }

    /// Find the start of an inline comment (;) outside of quotes.
    private func findCommentStart(_ text: String) -> String.Index? {
        var inQuote = false
        for i in text.indices {
            let ch = text[i]
            if ch == "\"" {
                inQuote = !inQuote
            } else if !inQuote && ch == ";" {
                return i
            }
        }
        return nil
    }

    /// Split off a balance assertion `= AMOUNT` from the amount text.
    private func splitBalanceAssertion(_ text: String) -> (String, String?) {
        var inQuote = false
        var i = text.startIndex
        while i < text.endIndex {
            let ch = text[i]
            if ch == "\"" {
                inQuote = !inQuote
            } else if !inQuote {
                // Skip lot annotation brackets
                if ch == "{" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: "}") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "[" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: "]") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "(" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: ")") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "=" {
                    // Skip == (not a balance assertion)
                    let next = text.index(after: i)
                    if next < text.endIndex && text[next] == "=" {
                        i = text.index(after: next)
                        continue
                    }
                    let lhs = String(text[text.startIndex..<i])
                        .trimmingCharacters(in: .whitespaces)
                    let rhs = String(text[text.index(after: i)...])
                        .trimmingCharacters(in: .whitespaces)
                    return (lhs, rhs.isEmpty ? nil : rhs)
                }
            }
            i = text.index(after: i)
        }
        return (text, nil)
    }

    /// Split an amount+cost string at `@` or `@@`.
    /// Returns (amount_text, cost_text_or_nil, is_total_cost).
    private func splitAmountAndCost(_ text: String) -> (String, String?, Bool) {
        var inQuote = false
        var i = text.startIndex
        while i < text.endIndex {
            let ch = text[i]
            if ch == "\"" {
                inQuote = !inQuote
            } else if !inQuote {
                // Skip lot annotation brackets
                if ch == "{" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: "}") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "[" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: "]") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "(" {
                    if let closeIdx = text[text.index(after: i)...].firstIndex(of: ")") {
                        i = text.index(after: closeIdx)
                        continue
                    }
                } else if ch == "@" {
                    let next = text.index(after: i)
                    if next < text.endIndex && text[next] == "@" {
                        let amt = String(text[text.startIndex..<i])
                            .trimmingCharacters(in: .whitespaces)
                        let costIdx = text.index(after: next)
                        let costStr = costIdx < text.endIndex
                            ? String(text[costIdx...])
                                .trimmingCharacters(in: .whitespaces)
                            : ""
                        return (amt, costStr.isEmpty ? nil : costStr, true)
                    } else {
                        let amt = String(text[text.startIndex..<i])
                            .trimmingCharacters(in: .whitespaces)
                        let costStr = next < text.endIndex
                            ? String(text[next...])
                                .trimmingCharacters(in: .whitespaces)
                            : ""
                        return (amt, costStr.isEmpty ? nil : costStr, false)
                    }
                }
            }
            i = text.index(after: i)
        }
        return (text, nil, false)
    }

    /// Parse lot annotations {$price} from an amount string.
    /// Returns (amount_text_without_annotations, lot_price_or_nil).
    private func parseLotAnnotation(_ text: String) -> (String, Amount?) {
        var inQuote = false
        for (offset, ch) in text.enumerated() {
            let idx = text.index(text.startIndex, offsetBy: offset)
            if ch == "\"" {
                inQuote = !inQuote
            } else if !inQuote && ch == "{" {
                let amountPart = String(text[text.startIndex..<idx])
                    .trimmingCharacters(in: .whitespaces)
                let afterBrace = text[text.index(after: idx)...]
                if let closeBrace = afterBrace.firstIndex(of: "}") {
                    let priceStr = String(afterBrace[afterBrace.startIndex..<closeBrace])
                        .trimmingCharacters(in: .whitespaces)
                    if let lotPrice = try? Amount(parsing: priceStr) {
                        return (amountPart, lotPrice)
                    }
                }
                return (amountPart, nil)
            }
        }
        return (text, nil)
    }
}
