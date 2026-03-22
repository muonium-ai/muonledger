/// Base type for all journal items (transactions and postings).
///
/// Ported from ledger's `item_t`. Every entry in a journal -- whether a
/// full transaction or an individual posting -- shares these common
/// properties: clearing state, dates, notes, and metadata tags.

import Foundation

// MARK: - TransactionState

/// Clearing state for a journal item.
///
/// In ledger syntax a transaction or posting may carry a clearing mark:
/// `*` for cleared, `!` for pending, or no mark for uncleared.
public enum TransactionState {
    case uncleared
    case cleared    // *
    case pending    // !
}

// MARK: - ItemFlags

/// Bit flags for journal items.
public struct ItemFlags: OptionSet {
    public let rawValue: UInt32

    public init(rawValue: UInt32) {
        self.rawValue = rawValue
    }

    public static let normal           = ItemFlags([])
    public static let generated        = ItemFlags(rawValue: 0x01)
    public static let temp             = ItemFlags(rawValue: 0x02)
    public static let noteOnNextLine   = ItemFlags(rawValue: 0x04)
    public static let inferred         = ItemFlags(rawValue: 0x08)
}

// MARK: - Item

/// Base class for all journal items: transactions and postings.
///
/// Uses class semantics so that back-references (Post -> Transaction)
/// work naturally.
public class Item {
    /// Bit flags (generated, temp, inferred, etc.).
    public var flags: ItemFlags

    /// Clearing state.
    public var state: TransactionState

    /// Primary date of the item.
    public var date: Date?

    /// Auxiliary (effective) date.
    public var dateAux: Date?

    /// Free-form note text from `;` comment lines.
    public var note: String?

    /// Metadata key-value pairs (tags).
    private var _metadata: [String: Any]?

    public init(flags: ItemFlags = .normal, note: String? = nil) {
        self.flags = flags
        self.state = .uncleared
        self.date = nil
        self.dateAux = nil
        self.note = note
        self._metadata = nil
    }

    // MARK: Flag helpers

    /// Return true if all bits in `flag` are set.
    public func hasFlags(_ flag: ItemFlags) -> Bool {
        flags.contains(flag)
    }

    /// Set the given flag bits.
    public func addFlags(_ flag: ItemFlags) {
        flags.insert(flag)
    }

    /// Clear the given flag bits.
    public func dropFlags(_ flag: ItemFlags) {
        flags.remove(flag)
    }

    // MARK: Metadata / tag system

    /// Return true if the metadata contains the given tag.
    public func hasTag(_ tag: String) -> Bool {
        _metadata?[tag] != nil
    }

    /// Return the value associated with a tag, or nil.
    public func getTag(_ tag: String) -> Any? {
        _metadata?[tag]
    }

    /// Set a metadata tag. Defaults to `true` for bare tags.
    public func setTag(_ tag: String, value: Any = true) {
        if _metadata == nil {
            _metadata = [:]
        }
        _metadata![tag] = value
    }
}
