"""
Commodity annotation types for lot tracking in double-entry accounting.

This module provides ``Annotation``, ``KeepDetails``, and
``AnnotatedCommodity``, a Python port of Ledger's ``annotation_t``,
``keep_details_t``, and ``annotated_commodity_t``.

Annotations record the circumstances under which a commodity lot was
acquired: per-unit purchase price, acquisition date, a free-form tag,
and an optional valuation expression.  In journal syntax these appear
after the amount quantity::

    10 AAPL {$150.00} [2024-01-15] (lot1) ((market(amount, date, t)))
            ^price      ^date       ^tag    ^value_expr

``KeepDetails`` controls which annotation fields survive when
annotations are stripped for display or comparison (e.g., the
``--lots``, ``--lot-prices``, ``--lot-dates``, ``--lot-tags`` options).

``AnnotatedCommodity`` pairs a base ``Commodity`` with an ``Annotation``
so that lots purchased at different prices or times can be tracked
independently.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from muonledger.commodity import Commodity

if TYPE_CHECKING:
    from muonledger.amount import Amount

__all__ = [
    "Annotation",
    "KeepDetails",
    "AnnotatedCommodity",
]


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

@dataclass
class Annotation:
    """Lot annotation metadata attached to a commodity.

    Each field may be ``None`` (absent).  Two annotations are equal when
    all four fields match.

    Attributes
    ----------
    price : Amount | None
        Per-unit lot price (e.g., ``{$10}``).
    date : datetime.date | None
        Acquisition date (e.g., ``[2024/01/01]``).
    tag : str | None
        Free-form tag for lot identification (e.g., ``(note)``).
    value_expr : str | None
        Custom valuation expression (e.g., ``((market(...)))``).
    """

    price: Amount | None = None
    date: datetime.date | None = None
    tag: str | None = None
    value_expr: str | None = None

    # -- flags (mirrors C++ ANNOTATION_* flags) ----------------------------

    PRICE_CALCULATED: int = 0x01
    PRICE_FIXATED: int = 0x02
    PRICE_NOT_PER_UNIT: int = 0x04
    DATE_CALCULATED: int = 0x08
    TAG_CALCULATED: int = 0x10
    VALUE_EXPR_CALCULATED: int = 0x20

    flags: int = field(default=0, repr=False)

    def has_flags(self, flag: int) -> bool:
        """Return True if all bits in *flag* are set."""
        return (self.flags & flag) == flag

    def add_flags(self, flag: int) -> None:
        """Set the given flag bits."""
        self.flags |= flag

    def drop_flags(self, flag: int) -> None:
        """Clear the given flag bits."""
        self.flags &= ~flag

    # -- emptiness ---------------------------------------------------------

    def is_empty(self) -> bool:
        """True if no annotation fields are set."""
        return (
            self.price is None
            and self.date is None
            and self.tag is None
            and self.value_expr is None
        )

    def __bool__(self) -> bool:
        """True if any annotation field is set."""
        return not self.is_empty()

    # -- equality / hashing ------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Annotation):
            return NotImplemented
        # Semantic flags that affect equality (mirrors ANNOTATION_SEMANTIC_FLAGS).
        SEMANTIC_FLAGS = self.PRICE_FIXATED
        return (
            self.price == other.price
            and self.date == other.date
            and self.tag == other.tag
            and self.value_expr == other.value_expr
            and (self.flags & SEMANTIC_FLAGS) == (other.flags & SEMANTIC_FLAGS)
        )

    def __hash__(self) -> int:
        SEMANTIC_FLAGS = self.PRICE_FIXATED
        return hash((
            self.price,
            self.date,
            self.tag,
            self.value_expr,
            self.flags & SEMANTIC_FLAGS,
        ))

    # -- ordering (mirrors C++ operator<) ----------------------------------

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Annotation):
            return NotImplemented

        # Absent sorts before present for each field.
        for self_val, other_val in [
            (self.price, other.price),
            (self.date, other.date),
            (self.tag, other.tag),
            (self.value_expr, other.value_expr),
        ]:
            if self_val is None and other_val is not None:
                return True
            if self_val is not None and other_val is None:
                return False

        # When both present, compare field values.
        if self.price is not None and other.price is not None:
            if self.price < other.price:
                return True
            if self.price > other.price:
                return False

        if self.date is not None and other.date is not None:
            if self.date < other.date:
                return True
            if self.date > other.date:
                return False

        if self.tag is not None and other.tag is not None:
            if self.tag < other.tag:
                return True
            if self.tag > other.tag:
                return False

        if self.value_expr is not None and other.value_expr is not None:
            if self.value_expr < other.value_expr:
                return True

        SEMANTIC_FLAGS = self.PRICE_FIXATED
        if (self.flags & SEMANTIC_FLAGS) < (other.flags & SEMANTIC_FLAGS):
            return True

        return False

    # -- string representation ---------------------------------------------

    def __str__(self) -> str:
        """Format as an annotation string (e.g., ``{$10} [2024-01-15] (lot1)``)."""
        parts: list[str] = []

        if self.price is not None:
            fixated = "=" if self.has_flags(self.PRICE_FIXATED) else ""
            parts.append(f"{{{fixated}{self.price}}}")

        if self.date is not None:
            parts.append(f"[{self.date.strftime('%Y/%m/%d')}]")

        if self.tag is not None:
            parts.append(f"({self.tag})")

        if self.value_expr is not None:
            parts.append(f"(({self.value_expr}))")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# KeepDetails
# ---------------------------------------------------------------------------

@dataclass
class KeepDetails:
    """Controls which annotation details survive stripping.

    When commodities need to be simplified for display or comparison,
    a ``KeepDetails`` specifies which annotation fields to retain.

    Attributes
    ----------
    keep_price : bool
        Retain the lot price annotation.
    keep_date : bool
        Retain the lot date annotation.
    keep_tag : bool
        Retain the lot tag annotation.
    keep_all : bool
        Shortcut: if True, retain all annotation fields.
    only_actuals : bool
        If True, discard computed (``*_CALCULATED``) annotations even if
        the corresponding ``keep_*`` flag is set.
    """

    keep_price: bool = False
    keep_date: bool = False
    keep_tag: bool = False
    keep_all: bool = False
    only_actuals: bool = False

    def keep_any(self) -> bool:
        """True if at least one annotation field would be retained."""
        return self.keep_all or self.keep_price or self.keep_date or self.keep_tag

    def should_keep(self, annotation: Annotation) -> Annotation:
        """Return a new annotation with only the fields that survive filtering.

        Fields are retained when their ``keep_*`` flag (or ``keep_all``)
        is set, *and* (if ``only_actuals`` is True) they were not computed.
        """
        if annotation.is_empty():
            return Annotation()

        if self.keep_all:
            if not self.only_actuals:
                return Annotation(
                    price=annotation.price,
                    date=annotation.date,
                    tag=annotation.tag,
                    value_expr=annotation.value_expr,
                    flags=annotation.flags,
                )
            # keep_all with only_actuals: keep non-calculated fields
            kp = self.keep_price or True
            kd = self.keep_date or True
            kt = self.keep_tag or True
        else:
            kp = self.keep_price
            kd = self.keep_date
            kt = self.keep_tag

        new_price = None
        new_date = None
        new_tag = None
        new_value_expr = None
        new_flags = 0

        if kp and annotation.price is not None:
            if not (self.only_actuals and annotation.has_flags(Annotation.PRICE_CALCULATED)):
                new_price = annotation.price
                new_flags |= annotation.flags & (
                    Annotation.PRICE_CALCULATED
                    | Annotation.PRICE_FIXATED
                    | Annotation.PRICE_NOT_PER_UNIT
                )

        if kd and annotation.date is not None:
            if not (self.only_actuals and annotation.has_flags(Annotation.DATE_CALCULATED)):
                new_date = annotation.date
                new_flags |= annotation.flags & Annotation.DATE_CALCULATED

        if kt and annotation.tag is not None:
            if not (self.only_actuals and annotation.has_flags(Annotation.TAG_CALCULATED)):
                new_tag = annotation.tag
                new_flags |= annotation.flags & Annotation.TAG_CALCULATED

        # Value expressions are not controlled by keep_* flags; they are
        # kept unless they were calculated.
        if annotation.value_expr is not None:
            if not annotation.has_flags(Annotation.VALUE_EXPR_CALCULATED):
                new_value_expr = annotation.value_expr

        return Annotation(
            price=new_price,
            date=new_date,
            tag=new_tag,
            value_expr=new_value_expr,
            flags=new_flags,
        )


# ---------------------------------------------------------------------------
# AnnotatedCommodity
# ---------------------------------------------------------------------------

class AnnotatedCommodity:
    """A commodity with attached lot annotation information.

    Wraps a base ``Commodity`` and adds lot-specific metadata via its
    ``annotation`` member.

    Parameters
    ----------
    commodity : Commodity
        The underlying unannotated base commodity.
    annotation : Annotation
        The lot annotation (price, date, tag, value_expr).
    """

    __slots__ = ("commodity", "annotation")

    def __init__(self, commodity: Commodity, annotation: Annotation) -> None:
        self.commodity = commodity
        self.annotation = annotation

    # -- identity / equality -----------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AnnotatedCommodity):
            return (
                self.commodity == other.commodity
                and self.annotation == other.annotation
            )
        if isinstance(other, Commodity):
            return self.commodity == other and self.annotation.is_empty()
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.commodity, self.annotation))

    # -- delegation --------------------------------------------------------

    @property
    def symbol(self) -> str:
        return self.commodity.symbol

    @property
    def qualified_symbol(self) -> str:
        return self.commodity.qualified_symbol

    # -- stripping ---------------------------------------------------------

    def strip_annotations(self, keep: KeepDetails) -> Commodity | AnnotatedCommodity:
        """Selectively remove annotation fields based on *keep*.

        If at least one annotation field survives, returns a new
        ``AnnotatedCommodity`` with the filtered annotation.  If no
        fields survive, returns the unannotated base commodity.
        """
        filtered = keep.should_keep(self.annotation)
        if filtered:
            return AnnotatedCommodity(self.commodity, filtered)
        return self.commodity

    # -- display -----------------------------------------------------------

    def __repr__(self) -> str:
        return f"AnnotatedCommodity({self.commodity!r}, {self.annotation!r})"

    def __str__(self) -> str:
        ann_str = str(self.annotation)
        if ann_str:
            return f"{self.commodity.qualified_symbol} {ann_str}"
        return self.commodity.qualified_symbol
