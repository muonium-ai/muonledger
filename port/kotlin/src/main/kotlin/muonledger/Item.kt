package muonledger

import java.time.LocalDate

/**
 * Clearing state for a journal item.
 *
 * In ledger syntax: `*` for CLEARED, `!` for PENDING, or no mark for UNCLEARED.
 */
enum class TransactionState { UNCLEARED, CLEARED, PENDING }

/**
 * Base class for all journal items (transactions and postings).
 *
 * Mirrors ledger's `item_t` type. Every entry in a journal inherits
 * from Item, providing shared properties: dates, clearing state, notes,
 * and metadata tags.
 */
open class Item(
    /** Primary date of the item. */
    var date: LocalDate? = null,
    /** Clearing state. */
    var state: TransactionState = TransactionState.UNCLEARED,
    /** Free-form note text. */
    var note: String? = null
) {
    /** Auxiliary (effective) date. */
    var dateAux: LocalDate? = null

    /** Metadata tags as key-value pairs. */
    private var _tags: MutableMap<String, Any>? = null

    /** Item flags. */
    var flags: Int = 0

    fun hasDate(): Boolean = date != null

    fun hasTag(tag: String): Boolean = _tags?.containsKey(tag) == true

    fun getTag(tag: String): Any? = _tags?.get(tag)

    fun setTag(tag: String, value: Any = true) {
        if (_tags == null) _tags = mutableMapOf()
        _tags!![tag] = value
    }

    fun hasFlags(flag: Int): Boolean = (flags and flag) == flag

    fun addFlags(flag: Int) {
        flags = flags or flag
    }

    fun dropFlags(flag: Int) {
        flags = flags and flag.inv()
    }

    companion object {
        const val ITEM_NORMAL = 0x00
        const val ITEM_GENERATED = 0x01
        const val ITEM_TEMP = 0x02
        const val ITEM_NOTE_ON_NEXT_LINE = 0x04
        const val ITEM_INFERRED = 0x08
    }
}
