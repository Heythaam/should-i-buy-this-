"""Shared, typed contract for product-fact retrieval (AD-3, AD-4).

`models/` is core/shared (AD-11): any branch may edit it in place when its
work requires it, but it is never forked or shadowed locally. This story only
adds what the Tier 2 scraper needs -- `SourceTier`, `ProductFacts`, and the
`SourceFailure` sentinel.
"""

from enum import Enum

from pydantic import BaseModel, Field


class SourceTier(str, Enum):
    """Which `ProductSource` implementation (AD-3) supplied a result."""

    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ProductFacts(BaseModel):
    """Facts extracted from a product page for one Canonical Product.

    Every field here is a *fact* (AD-5) -- exact, sourced directly from the
    page -- never inferred or rewritten downstream.
    """

    canonical_product_id: str
    title: str
    price: float | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    source_tier: SourceTier
    review_count: int | None = Field(default=None, ge=0)


class SourceFailure(BaseModel):
    """Explicit typed failure sentinel for a `ProductSource.fetch()` call.

    Returned instead of raising (AD-4, AD-9) -- never `None`-as-success and
    never a partially-filled `ProductFacts`.
    """

    source_tier: SourceTier
    reason: str
    detail: str | None = None


class InsufficientDataResult(BaseModel):
    """The FR-3-level "insufficient data" outcome (AD-4).

    Returned by `pipeline/orchestrator.py::resolve_product_facts` whenever a
    URL can't be canonicalized or a `ProductSource.fetch()` call degrades to
    a `SourceFailure` -- the one explicit, user-facing result a future
    API/UI renders instead of a fabricated or partial `Verdict`.

    Kept distinct from `SourceFailure`: `SourceFailure` is a scraper-tier's
    internal, per-tier signal (AD-3); this is the pipeline-level outcome,
    so collapsing the two would couple the eventual frontend contract to the
    scraper's internal vocabulary.
    """

    reason: str
    detail: str | None = None
    source_tier: SourceTier | None = None
