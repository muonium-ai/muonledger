"""Hierarchical account tree (chart of accounts).

Ported from ledger's ``account.h`` / ``account.cc``.  Each :class:`Account`
represents one node in a colon-separated account hierarchy such as
``Expenses:Food:Dining``.  A single invisible root account (depth 0) sits
at the top of the tree; the user-visible top-level accounts are its children.
"""

from __future__ import annotations

from typing import Any, Iterator

__all__ = ["Account"]


class Account:
    """A node in the hierarchical chart of accounts.

    Parameters
    ----------
    parent:
        Parent account, or ``None`` for the root.
    name:
        Local name of this account segment (e.g. ``"Food"``).
    note:
        Optional descriptive note.
    """

    __slots__ = (
        "name",
        "parent",
        "_children",
        "depth",
        "posts",
        "_fullname",
        "note",
        "_xdata",
    )

    def __init__(
        self,
        parent: Account | None = None,
        name: str = "",
        note: str | None = None,
    ) -> None:
        self.name: str = name
        self.parent: Account | None = parent
        self._children: dict[str, Account] = {}
        self.depth: int = (parent.depth + 1) if parent is not None else 0
        self.posts: list[Any] = []
        self._fullname: str | None = None
        self.note: str | None = note
        self._xdata: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fullname(self) -> str:
        """Colon-separated full account path.

        The root account (whose *name* is empty) returns ``""``.
        """
        if self._fullname is not None:
            return self._fullname

        parts: list[str] = []
        node: Account | None = self
        while node is not None:
            if node.name:
                parts.append(node.name)
            node = node.parent
        parts.reverse()
        result = ":".join(parts)
        self._fullname = result
        return result

    @property
    def children(self) -> dict[str, Account]:
        """Read-only access to child accounts keyed by name."""
        return self._children

    @property
    def has_children(self) -> bool:
        return len(self._children) > 0

    # ------------------------------------------------------------------
    # Tree manipulation
    # ------------------------------------------------------------------

    def add_account(self, child: Account) -> None:
        """Insert *child* as a direct child of this account."""
        child.parent = self
        child.depth = self.depth + 1
        # Invalidate cached fullnames down the subtree.
        child._invalidate_fullname()
        self._children[child.name] = child

    def remove_account(self, child: Account) -> bool:
        """Remove *child* from this account's children.

        Returns ``True`` if the child was present and removed.
        """
        if child.name in self._children and self._children[child.name] is child:
            del self._children[child.name]
            return True
        return False

    def find_account(
        self, path: str, auto_create: bool = True
    ) -> Account | None:
        """Look up or create an account by colon-separated *path*.

        Splits on ``":"`` and walks (or creates) intermediate accounts.
        For example, ``root.find_account("Expenses:Food:Dining")`` creates
        ``Expenses``, ``Food``, and ``Dining`` as needed.

        If *auto_create* is ``False``, returns ``None`` when any segment
        along the path does not exist.
        """
        # Fast path: direct child lookup (no colon).
        if path in self._children:
            return self._children[path]

        sep = path.find(":")
        if sep == -1:
            first, rest = path, ""
        else:
            first, rest = path[:sep], path[sep + 1:]

        if not first:
            raise ValueError("Account name contains an empty sub-account name")

        account = self._children.get(first)
        if account is None:
            if not auto_create:
                return None
            account = Account(parent=self, name=first)
            self._children[first] = account

        if rest:
            return account.find_account(rest, auto_create=auto_create)
        return account

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def add_post(self, post: Any) -> None:
        """Append a posting reference to this account."""
        self.posts.append(post)

    # ------------------------------------------------------------------
    # Extended data (xdata)
    # ------------------------------------------------------------------

    def has_xdata(self) -> bool:
        """Return whether extended reporting data has been allocated."""
        return self._xdata is not None

    def xdata(self) -> dict[str, Any]:
        """Return the extended data dict, creating it lazily."""
        if self._xdata is None:
            self._xdata = {}
        return self._xdata

    def set_xdata(self, key: str, value: Any) -> None:
        """Set a single key in the extended data dict."""
        self.xdata()[key] = value

    def clear_xdata(self) -> None:
        """Recursively clear extended data from this account and descendants."""
        self._xdata = None
        for child in self._children.values():
            child.clear_xdata()

    # ------------------------------------------------------------------
    # Traversal helpers
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[Account]:
        """Iterate over direct child accounts."""
        return iter(self._children.values())

    def __len__(self) -> int:
        """Number of direct children."""
        return len(self._children)

    def __contains__(self, name: object) -> bool:
        """Check whether a child with the given *name* exists."""
        return name in self._children

    def __getitem__(self, name: str) -> Account:
        """Return the child account with the given *name*."""
        return self._children[name]

    def flatten(self) -> list[Account]:
        """Depth-first list of all descendant accounts (excluding self)."""
        result: list[Account] = []
        self._flatten_into(result)
        return result

    def _flatten_into(self, result: list[Account]) -> None:
        for child in self._children.values():
            result.append(child)
            child._flatten_into(result)

    def sorted_children(self) -> list[Account]:
        """Return direct children sorted by name."""
        return sorted(self._children.values(), key=lambda a: a.name)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self.fullname

    def __repr__(self) -> str:
        return f"Account({self.fullname!r})"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invalidate_fullname(self) -> None:
        """Clear cached fullname for this node and all descendants."""
        self._fullname = None
        for child in self._children.values():
            child._invalidate_fullname()
