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
from muonledger.amount import Amount
from muonledger.commodity import Commodity, CommodityPool
from muonledger.price_history import PriceHistory
from muonledger.timelog import TimelogProcessor
from muonledger.value import Value
from muonledger.xact import BalanceAssertionError, Transaction

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
        "_account_balances",
        "timelog",
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
        self._account_balances: dict[str, Value] = {}  # running balances per account for assertions
        self.timelog: TimelogProcessor = TimelogProcessor()

    # ------------------------------------------------------------------
    # Transaction management
    # ------------------------------------------------------------------

    def add_xact(self, xact: Transaction) -> bool:
        """Add *xact* to the journal after finalizing it.

        Calls :meth:`Transaction.finalize` to infer missing amounts and
        verify double-entry balance.  Then checks balance assertions.
        Returns ``True`` if the transaction was successfully added,
        ``False`` if finalization indicated the transaction should be
        skipped (e.g. all-null amounts).

        Raises
        ------
        BalanceError
            Propagated from :meth:`Transaction.finalize` if the
            transaction does not balance.
        BalanceAssertionError
            If a balance assertion on any posting fails.
        """
        # Handle balance assignments before finalize: if a posting has
        # no amount but has an assigned_amount, compute the amount needed
        # to reach the asserted balance.
        for post in xact.posts:
            if post.assigned_amount is not None and (
                post.amount is None or post.amount.is_null()
            ):
                acct_key = self._account_key(post.account)
                current = self._account_balances.get(acct_key, Value())
                # The posting amount should bring the balance to assigned_amount
                target = Value(post.assigned_amount)
                if current.is_null():
                    post.amount = Amount(post.assigned_amount)
                else:
                    diff = target - current
                    post.amount = diff.to_amount()

        if not xact.finalize():
            return False

        # Check balance assertions and update running account balances.
        for post in xact.posts:
            if post.amount is None or post.amount.is_null():
                continue
            acct_key = self._account_key(post.account)
            current = self._account_balances.get(acct_key, Value())
            post_amt = post.amount
            if current.is_null():
                current = Value(post_amt)
            else:
                current = current + Value(post_amt)
            self._account_balances[acct_key] = current

            if post.assigned_amount is not None:
                expected = Value(post.assigned_amount)
                if not self._values_match(current, expected):
                    raise BalanceAssertionError(
                        f"Balance assertion failed: expected {post.assigned_amount}, "
                        f"got {current.to_amount()}",
                        post=post,
                    )

        self.xacts.append(xact)
        return True

    @staticmethod
    def _account_key(account: object) -> str:
        """Get a string key for an account for balance tracking."""
        if account is None:
            return "<unknown>"
        if isinstance(account, str):
            return account
        return account.fullname

    @staticmethod
    def _values_match(actual: Value, expected: Value) -> bool:
        """Check if two Values match for balance assertion purposes."""
        diff = actual - expected
        return diff.is_null() or diff.is_zero()

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
