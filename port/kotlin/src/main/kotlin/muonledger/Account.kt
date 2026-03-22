package muonledger

/**
 * A node in the hierarchical chart of accounts.
 *
 * Each Account represents one segment in a colon-separated account path
 * such as "Expenses:Food:Dining". A single invisible root account (depth 0)
 * sits at the top of the tree.
 */
class Account(
    /** Parent account, or null for the root. */
    var parent: Account? = null,
    /** Local name of this account segment (e.g. "Food"). */
    val name: String = "",
    /** Optional descriptive note. */
    var note: String? = null
) {
    /** Direct child accounts keyed by name. */
    private val _children: MutableMap<String, Account> = mutableMapOf()

    /** Depth in the account tree (root = 0). */
    val depth: Int = if (parent != null) parent!!.depth + 1 else 0

    /** Cached fullname. */
    private var _fullname: String? = null

    /** Read-only view of children. */
    val children: Map<String, Account> get() = _children

    val hasChildren: Boolean get() = _children.isNotEmpty()

    /**
     * Colon-separated full account path.
     * The root account (empty name) returns "".
     */
    val fullname: String
        get() {
            _fullname?.let { return it }
            val parts = mutableListOf<String>()
            var node: Account? = this
            while (node != null) {
                if (node.name.isNotEmpty()) {
                    parts.add(node.name)
                }
                node = node.parent
            }
            parts.reverse()
            val result = parts.joinToString(":")
            _fullname = result
            return result
        }

    /**
     * Look up or create an account by colon-separated path.
     *
     * For example, `root.findAccount("Expenses:Food:Dining")` creates
     * Expenses, Food, and Dining as needed.
     *
     * @param path colon-separated account path
     * @param autoCreate if false, returns null when any segment doesn't exist
     */
    fun findAccount(path: String, autoCreate: Boolean = true): Account? {
        // Fast path: direct child lookup (no colon)
        _children[path]?.let { return it }

        val sep = path.indexOf(':')
        val first: String
        val rest: String
        if (sep < 0) {
            first = path
            rest = ""
        } else {
            first = path.substring(0, sep)
            rest = path.substring(sep + 1)
        }

        require(first.isNotEmpty()) { "Account name contains an empty sub-account name" }

        var account = _children[first]
        if (account == null) {
            if (!autoCreate) return null
            account = Account(parent = this, name = first)
            _children[first] = account
        }

        return if (rest.isNotEmpty()) {
            account.findAccount(rest, autoCreate)
        } else {
            account
        }
    }

    /** Insert a child account. */
    fun addAccount(child: Account) {
        child.parent // ensure parent is set by the constructor or manually
        _children[child.name] = child
    }

    /** Remove a child account. Returns true if removed. */
    fun removeAccount(child: Account): Boolean {
        if (_children[child.name] === child) {
            _children.remove(child.name)
            return true
        }
        return false
    }

    /** Depth-first list of all descendant accounts (excluding self). */
    fun flatten(): List<Account> {
        val result = mutableListOf<Account>()
        flattenInto(result)
        return result
    }

    private fun flattenInto(result: MutableList<Account>) {
        for (child in _children.values) {
            result.add(child)
            child.flattenInto(result)
        }
    }

    /** Direct children sorted by name. */
    fun sortedChildren(): List<Account> = _children.values.sortedBy { it.name }

    override fun toString(): String = fullname

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Account) return false
        return fullname == other.fullname
    }

    override fun hashCode(): Int = fullname.hashCode()
}
