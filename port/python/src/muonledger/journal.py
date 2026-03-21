"""Central container for all financial data in a Ledger session.

Ported from ledger's ``journal.h`` / ``journal.cc``.  The :class:`Journal`
owns the account tree (rooted at *master*), all parsed transactions (regular,
automated, and periodic), and the shared :class:`CommodityPool`.

There is exactly one journal per session.  Parsing populates it and the
reporting engine reads from it.
"""

from __future__ import annotations

from typing import Iterator

from muonledger.account import Account
from muonledger.commodity import Commodity, CommodityPool
from muonledger.price_history import PriceHistory
from muonledger.xact import Transaction

__all__ = ["Journal"]


class Journal:
    """The central container for all financial data.

    On construction an invisible root :class:`Account` (with an empty name)
    is created as *master*, mirroring ledger's ``journal_t`` constructor.

    Parameters
    ----------
    commodity_pool:
        An existing :class:`CommodityPool` to use.  If ``None`` a fresh
        pool is created.
    """

    __slots__ = (
        "master",
        "xacts",
        "auto_xacts",
        "period_xacts",
        "commodity_pool",
        "sources",
        "was_loaded",
        "prices",
        "bucket",
        "account_aliases",
        "default_year",
        "tag_declarations",
        "payee_declarations",
        "apply_account_stack",
        "apply_tag_stack",
        "no_market_commodities",
        "defines",
        "price_history",
    )

    def __init__(
        self,
        commodity_pool: CommodityPool | None = None,
    ) -> None:
        self.master: Account = Account()  # root account with empty name
        self.xacts: list[Transaction] = []
        self.auto_xacts: list = []  # stub for automated transactions
        self.period_xacts: list = []  # stub for periodic transactions
        self.commodity_pool: CommodityPool = (
            commodity_pool if commodity_pool is not None else CommodityPool()
        )
        self.sources: list[str] = []
        self.was_loaded: bool = False
        self.prices: list[tuple] = []  # (date, commodity, price_amount)
        self.bucket: Account | None = None  # default account (A directive)
        self.account_aliases: dict[str, Account] = {}
        self.default_year: int | None = None
        self.tag_declarations: list[str] = []
        self.payee_declarations: list[str] = []
        self.apply_account_stack: list[str] = []
        self.apply_tag_stack: list[str] = []
        self.no_market_commodities: list[str] = []
        self.defines: dict[str, str] = {}
        self.price_history: PriceHistory = PriceHistory()

    # ------------------------------------------------------------------
    # Transaction management
    # ------------------------------------------------------------------

    def add_xact(self, xact: Transaction) -> bool:
        """Add *xact* to the journal after finalizing it.

        Calls :meth:`Transaction.finalize` to infer missing amounts and
        verify double-entry balance.  Returns ``True`` if the transaction
        was successfully added, ``False`` if finalization indicated the
        transaction should be skipped (e.g. all-null amounts).

        Raises
        ------
        BalanceError
            Propagated from :meth:`Transaction.finalize` if the
            transaction does not balance.
        """
        if not xact.finalize():
            return False
        self.xacts.append(xact)
        return True

    def remove_xact(self, xact: Transaction) -> None:
        """Remove *xact* from the journal.

        Raises ``ValueError`` if the transaction is not present.
        """
        self.xacts.remove(xact)

    # ------------------------------------------------------------------
    # Account helpers
    # ------------------------------------------------------------------

    def find_account(
        self, path: str, auto_create: bool = True
    ) -> Account | None:
        """Look up or create an account by colon-separated *path*.

        Delegates to :meth:`Account.find_account` on :attr:`master`.
        """
        return self.master.find_account(path, auto_create=auto_create)

    # ------------------------------------------------------------------
    # Commodity helpers
    # ------------------------------------------------------------------

    def register_commodity(self, symbol: str) -> Commodity:
        """Find or create a :class:`Commodity` in the shared pool.

        Delegates to :meth:`CommodityPool.find_or_create`.
        """
        return self.commodity_pool.find_or_create(symbol)

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Number of regular transactions in the journal."""
        return len(self.xacts)

    def __iter__(self) -> Iterator[Transaction]:
        """Iterate over regular transactions in parse order."""
        return iter(self.xacts)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset the journal to its initial (empty) state.

        Creates a fresh root account and empties all transaction lists,
        sources, and the commodity pool.
        """
        self.master = Account()
        self.xacts.clear()
        self.auto_xacts.clear()
        self.period_xacts.clear()
        self.commodity_pool = CommodityPool()
        self.sources.clear()
        self.was_loaded = False
        self.prices.clear()
        self.bucket = None
        self.account_aliases.clear()
        self.default_year = None
        self.tag_declarations.clear()
        self.payee_declarations.clear()
        self.apply_account_stack.clear()
        self.apply_tag_stack.clear()
        self.no_market_commodities.clear()
        self.defines.clear()
        self.price_history = PriceHistory()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Journal(xacts={len(self.xacts)}, "
            f"accounts={len(self.master.flatten())})"
        )
