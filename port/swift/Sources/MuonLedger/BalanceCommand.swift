/// Balance command -- produces a balance report from a journal.
///
/// Ported from the Python/Rust reference implementations. Given a `Journal`,
/// accumulates posting amounts into their accounts and renders a formatted
/// balance report matching C++ ledger output.

import Foundation

// MARK: - BalanceCommand

/// Column width for amounts (right-aligned within this width).
private let amountWidth = 20

/// Separator line width matches amount column.
private let separator = String(repeating: "-", count: amountWidth)

/// Options for the balance command.
struct BalanceOptions {
    var flat: Bool = false
    var noTotal: Bool = false
    var showEmpty: Bool = false
    var depth: Int = 0
    var beginDate: Date? = nil
    var endDate: Date? = nil
    var patterns: [String] = []
}

/// Accumulate per-account (leaf) balances from all transactions.
private func accumulateBalances(
    journal: Journal,
    beginDate: Date?,
    endDate: Date?
) -> [String: Balance] {
    var balances: [String: Balance] = [:]
    for xact in journal.transactions {
        // Date filtering
        if let begin = beginDate, let d = xact.date {
            if d < begin { continue }
        }
        if let end = endDate, let d = xact.date {
            if d >= end { continue }
        }
        for post in xact.posts {
            guard let amt = post.amount, !amt.isNull else { continue }
            guard let acct = post.account else { continue }
            let name = acct.fullname
            if name.isEmpty { continue }
            if balances[name] == nil {
                balances[name] = Balance()
            }
            balances[name]!.add(amt)
        }
    }
    return balances
}

/// Roll up leaf balances into all ancestor accounts.
private func rollUpToParents(_ balances: [String: Balance]) -> [String: Balance] {
    var rolled: [String: Balance] = [:]
    for (name, bal) in balances {
        let parts = name.split(separator: ":").map(String.init)
        for i in 1...parts.count {
            let ancestor = parts[0..<i].joined(separator: ":")
            if rolled[ancestor] == nil {
                rolled[ancestor] = Balance()
            }
            rolled[ancestor]!.add(bal)
        }
    }
    return rolled
}

/// Apply depth limiting: keep only accounts with <= depth segments.
private func applyDepth(_ rolled: [String: Balance], depth: Int) -> [String: Balance] {
    var result: [String: Balance] = [:]
    for (name, bal) in rolled {
        let segments = name.split(separator: ":").count
        if segments <= depth {
            result[name] = bal
        }
    }
    return result
}

/// Simple substring match (case-insensitive).
private func matchesPattern(_ name: String, patterns: [String]) -> Bool {
    if patterns.isEmpty { return true }
    let lower = name.lowercased()
    return patterns.contains { lower.contains($0.lowercased()) }
}

/// Return immediate children of `name` from the set of all account names.
private func getChildren(_ name: String, allNames: Set<String>) -> [String] {
    let prefix = name + ":"
    var children: [String] = []
    for n in allNames {
        guard n.hasPrefix(prefix) else { continue }
        let rest = String(n.dropFirst(prefix.count))
        if !rest.contains(":") {
            children.append(n)
        }
    }
    return children.sorted()
}

/// Account entry for display: (display_name, full_name, balance).
typealias AccountEntry = (displayName: String, fullName: String, balance: Balance)

/// Collect accounts for tree (hierarchical) display.
private func collectTreeAccounts(
    rolled: [String: Balance],
    leafBalances: [String: Balance],
    showEmpty: Bool,
    depth: Int
) -> [AccountEntry] {
    let allNames = Set(rolled.keys)
    let topLevel = allNames.filter { !$0.contains(":") }.sorted()

    var result: [AccountEntry] = []

    func visibleChildren(_ name: String) -> [String] {
        let children = getChildren(name, allNames: allNames)
        if !showEmpty {
            return children.filter { rolled[$0]?.isNonZero ?? false }
        }
        return children
    }

    func hasDirectOrKnown(_ name: String) -> Bool {
        leafBalances[name] != nil
    }

    func walk(
        name: String,
        currentDepth: Int,
        collapsePrefix: String,
        indentDepth: Int
    ) {
        if depth > 0 && currentDepth >= depth { return }

        let bal = rolled[name] ?? Balance()
        let children = visibleChildren(name)

        // Build display name
        let leafSegment: String
        if let lastColon = name.lastIndex(of: ":") {
            leafSegment = String(name[name.index(after: lastColon)...])
        } else {
            leafSegment = name
        }
        let display = collapsePrefix.isEmpty ? leafSegment : "\(collapsePrefix):\(leafSegment)"

        // Collapse: single child, no direct postings
        if children.count == 1 && !hasDirectOrKnown(name) {
            walk(
                name: children[0],
                currentDepth: currentDepth,
                collapsePrefix: display,
                indentDepth: indentDepth
            )
            return
        }

        // Should we display this account?
        var shouldShow = false
        if bal.isNonZero {
            shouldShow = true
        } else if showEmpty && hasDirectOrKnown(name) {
            shouldShow = true
        }

        if !shouldShow && children.isEmpty { return }

        if shouldShow {
            let indent = String(repeating: "  ", count: indentDepth)
            let indentedDisplay = indent + display
            result.append((indentedDisplay, name, bal))
        }

        let childPrefix = shouldShow ? "" : display
        for child in children {
            walk(
                name: child,
                currentDepth: currentDepth + 1,
                collapsePrefix: childPrefix,
                indentDepth: indentDepth + (shouldShow ? 1 : 0)
            )
        }
    }

    for top in topLevel {
        walk(name: top, currentDepth: 0, collapsePrefix: "", indentDepth: 0)
    }

    return result
}

/// Collect accounts for flat display.
private func flatAccounts(
    leafBalances: [String: Balance],
    patterns: [String],
    showEmpty: Bool,
    depth: Int
) -> [AccountEntry] {
    var result: [AccountEntry] = []
    for name in leafBalances.keys.sorted() {
        let bal = leafBalances[name]!
        if !showEmpty && !bal.isNonZero { continue }
        if !patterns.isEmpty && !matchesPattern(name, patterns: patterns) { continue }
        if depth > 0 && name.split(separator: ":").count > depth { continue }
        result.append((name, name, bal))
    }
    return result
}

/// Format a Balance into right-aligned amount strings.
private func formatAmountLines(_ bal: Balance) -> [String] {
    if bal.isEmpty {
        return [rightAlign("0", width: amountWidth)]
    }

    var lines: [String] = []
    for key in bal.amounts.keys.sorted() {
        lines.append(rightAlign(bal.amounts[key]!.toString(), width: amountWidth))
    }

    if lines.isEmpty {
        lines.append(rightAlign("0", width: amountWidth))
    }

    return lines
}

/// Right-align a string within a given width.
private func rightAlign(_ s: String, width: Int) -> String {
    if s.count >= width { return s }
    return String(repeating: " ", count: width - s.count) + s
}

/// Filter tree entries by patterns, keeping ancestors of matching accounts.
private func filterTreeByPatterns(
    _ entries: [AccountEntry],
    patterns: [String]
) -> [AccountEntry] {
    var matchingFull = Set<String>()
    for (_, full, _) in entries {
        if matchesPattern(full, patterns: patterns) {
            matchingFull.insert(full)
        }
    }

    var ancestorNames = Set<String>()
    for full in matchingFull {
        let parts = full.split(separator: ":").map(String.init)
        for i in 1..<parts.count {
            ancestorNames.insert(parts[0..<i].joined(separator: ":"))
        }
    }

    return entries.filter { (_, full, _) in
        matchingFull.contains(full) || ancestorNames.contains(full)
    }
}

/// Produce a balance report from a journal.
func balanceCommand(journal: Journal, opts: BalanceOptions) -> String {
    let effectiveDepth = opts.depth

    // Step 1: Accumulate per-account (leaf) balances.
    var leafBalances = accumulateBalances(
        journal: journal, beginDate: opts.beginDate, endDate: opts.endDate
    )

    // Step 2: Roll up balances to parents.
    var rolled = rollUpToParents(leafBalances)

    // Step 3: Apply depth limiting.
    if effectiveDepth > 0 {
        rolled = applyDepth(rolled, depth: effectiveDepth)
        var depthLeaves: [String: Balance] = [:]
        for (name, bal) in leafBalances {
            let parts = name.split(separator: ":").map(String.init)
            let truncated: String
            if parts.count > effectiveDepth {
                truncated = parts[0..<effectiveDepth].joined(separator: ":")
            } else {
                truncated = name
            }
            if depthLeaves[truncated] == nil {
                depthLeaves[truncated] = Balance()
            }
            depthLeaves[truncated]!.add(bal)
        }
        leafBalances = depthLeaves
    }

    // Step 4: Determine which accounts to display.
    let accounts: [AccountEntry]
    if opts.flat {
        accounts = flatAccounts(
            leafBalances: leafBalances,
            patterns: opts.patterns,
            showEmpty: opts.showEmpty,
            depth: effectiveDepth
        )
    } else {
        let entries = collectTreeAccounts(
            rolled: rolled,
            leafBalances: leafBalances,
            showEmpty: opts.showEmpty,
            depth: effectiveDepth
        )
        if !opts.patterns.isEmpty {
            accounts = filterTreeByPatterns(entries, patterns: opts.patterns)
        } else {
            accounts = entries
        }
    }

    // Step 5: Render.
    var lines: [String] = []

    for (displayName, _, bal) in accounts {
        let amtLines = formatAmountLines(bal)
        lines.append("\(amtLines[0])  \(displayName)")
        for extra in amtLines.dropFirst() {
            lines.append(extra)
        }
    }

    // Compute grand total from leaf balances.
    var grandTotal = Balance()
    if opts.patterns.isEmpty {
        for bal in leafBalances.values {
            grandTotal.add(bal)
        }
    } else {
        // When patterns are active, sum only matching accounts.
        if opts.flat {
            for (_, _, bal) in accounts {
                grandTotal.add(bal)
            }
        } else {
            for (_, full, _) in accounts {
                if let leafBal = leafBalances[full] {
                    grandTotal.add(leafBal)
                }
            }
        }
    }

    // Total line.
    if !opts.noTotal && !accounts.isEmpty {
        lines.append(separator)
        if grandTotal.isEmpty || grandTotal.isZero {
            lines.append(rightAlign("0", width: amountWidth))
        } else {
            let totalLines = formatAmountLines(grandTotal)
            for tl in totalLines {
                lines.append(tl)
            }
        }
    }

    if lines.isEmpty { return "" }

    return lines.joined(separator: "\n") + "\n"
}
