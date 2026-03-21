"""Periodic transactions (``~ PERIOD``).

Ported from ledger's ``period_xact_t``.  A periodic transaction uses the
``~`` prefix followed by a period expression (e.g. ``Monthly``, ``Weekly``,
``Every 2 weeks``).  These define recurring budget entries that are used
with ``--budget`` reporting to compare actual vs. budgeted amounts.

Example journal syntax::

    ~ Monthly
        Expenses:Food                        $500
        Expenses:Rent                      $1,500
        Assets:Checking

    2024/01/15 Grocery Store
        Expenses:Food                        $50
        Assets:Checking                     $-50

With ``--budget``, the balance report shows budget vs actual amounts.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, List, Optional

from muonledger.amount import Amount
from muonledger.item import ITEM_GENERATED
from muonledger.post import POST_GENERATED, Post
from muonledger.times import DateInterval, parse_period
from muonledger.xact import Transaction

if TYPE_CHECKING:
    from muonledger.journal import Journal

__all__ = ["PeriodicTransaction", "BudgetPosts"]


class PeriodicTransaction:
    """A periodic transaction (``~ PERIOD``).

    Parameters
    ----------
    period_expr : str
        The period expression string, e.g. ``"Monthly"``, ``"Every 2 weeks"``.
    posts : list[Post]
        Template postings that define the budget for each period.
    """

    __slots__ = ("period_expr", "posts", "interval")

    def __init__(
        self, period_expr: str, posts: Optional[List[Post]] = None
    ) -> None:
        self.period_expr: str = period_expr
        self.posts: List[Post] = posts if posts is not None else []
        self.interval: Optional[DateInterval] = None

    def parse_period(self) -> DateInterval:
        """Parse the period expression into a :class:`DateInterval`.

        The result is cached in :attr:`interval`.  Returns the interval.

        Raises :class:`ValueError` if the period expression is not recognized.
        """
        if self.interval is None:
            self.interval = parse_period(self.period_expr)
        return self.interval

    def generate_xacts(
        self, begin_date: date, end_date: date
    ) -> List[Transaction]:
        """Generate transactions for each period between *begin_date* and *end_date*.

        Each generated transaction contains copies of the template postings
        with the ``POST_GENERATED`` flag set.

        Parameters
        ----------
        begin_date : date
            Start of the date range (inclusive).
        end_date : date
            End of the date range (exclusive).

        Returns
        -------
        list[Transaction]
            Generated transactions, one per period within the range.
        """
        if begin_date >= end_date:
            return []

        interval = self.parse_period()
        dur = interval.duration

        generated_xacts: List[Transaction] = []
        current = begin_date

        while current < end_date:
            xact = Transaction(payee=f"Budget: {self.period_expr}")
            xact._date = current

            for template_post in self.posts:
                post = Post(
                    account=template_post.account,
                    amount=Amount(template_post.amount) if template_post.amount is not None else None,
                    flags=template_post.flags,
                    note=template_post.note,
                )
                post.cost = template_post.cost
                post.add_flags(POST_GENERATED)
                xact.add_post(post)

            generated_xacts.append(xact)
            current = current + dur

        return generated_xacts

    def __repr__(self) -> str:
        return (
            f"PeriodicTransaction(period={self.period_expr!r}, "
            f"posts={len(self.posts)})"
        )


# ---------------------------------------------------------------------------
# Budget filter
# ---------------------------------------------------------------------------


class BudgetPosts:
    """Generates budget postings from periodic transactions.

    This filter works by:
    1. Pre-generating all budget postings for the date range
    2. Tracking actual postings that match budget accounts
    3. Providing budget totals per account for comparison

    Parameters
    ----------
    handler : object
        Downstream handler (a :class:`~muonledger.filters.PostHandler`).
    periodic_xacts : list[PeriodicTransaction]
        The periodic transactions that define the budget.
    begin : date
        Start of the reporting period.
    end : date
        End of the reporting period.
    """

    def __init__(
        self,
        handler: object,
        periodic_xacts: List[PeriodicTransaction],
        begin: date,
        end: date,
    ) -> None:
        self.handler = handler
        self.periodic_xacts = periodic_xacts
        self.begin = begin
        self.end = end
        self._budget_totals: dict[str, Amount] = {}
        self._actual_totals: dict[str, Amount] = {}
        self._budget_xacts: List[Transaction] = []
        self._generate_budget()

    def _generate_budget(self) -> None:
        """Pre-generate all budget transactions."""
        for pxact in self.periodic_xacts:
            xacts = pxact.generate_xacts(self.begin, self.end)
            self._budget_xacts.extend(xacts)
            for xact in xacts:
                for post in xact.posts:
                    if post.account is not None and post.amount is not None:
                        key = post.account.fullname
                        if key in self._budget_totals:
                            self._budget_totals[key] = (
                                self._budget_totals[key] + post.amount
                            )
                        else:
                            self._budget_totals[key] = Amount(post.amount)

    def __call__(self, post: Post) -> None:
        """Process a regular posting, tracking actuals against budget."""
        if post.account is not None and post.amount is not None:
            key = post.account.fullname
            if key in self._actual_totals:
                self._actual_totals[key] = self._actual_totals[key] + post.amount
            else:
                self._actual_totals[key] = Amount(post.amount)

        # Forward to downstream handler
        if self.handler is not None:
            self.handler(post)

    def get_budget_total(self, account_name: str) -> Optional[Amount]:
        """Return the total budgeted amount for *account_name*."""
        return self._budget_totals.get(account_name)

    def get_actual_total(self, account_name: str) -> Optional[Amount]:
        """Return the total actual amount for *account_name*."""
        return self._actual_totals.get(account_name)

    @property
    def budget_accounts(self) -> set[str]:
        """Return the set of account names that have budget entries."""
        return set(self._budget_totals.keys())

    @property
    def budget_xacts(self) -> List[Transaction]:
        """Return all generated budget transactions."""
        return self._budget_xacts

    def flush(self) -> None:
        """Flush the downstream handler."""
        if self.handler is not None and hasattr(self.handler, "flush"):
            self.handler.flush()

    def clear(self) -> None:
        """Clear state for reuse."""
        self._budget_totals.clear()
        self._actual_totals.clear()
        self._budget_xacts.clear()
        if self.handler is not None and hasattr(self.handler, "clear"):
            self.handler.clear()
