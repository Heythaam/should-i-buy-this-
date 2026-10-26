"""Shared, typed contract for the final Verdict (AD-7, AD-11).

`models/` is core/shared: any branch may edit it in place when its work
requires it, but it is never forked or shadowed locally. `Verdict` is the
single frontend contract this story's spec names: used for OpenAI structured-
output enforcement (via `DraftVerdict` in `models/llm.py`, the LLM-facing
subset of this shape), as the eventual FastAPI response model (Story 1.8/1.9),
and as what the UI template renders. `schema_version` is bumped on any future
breaking change so a consumer can treat an unexpected version as incompatible
rather than guessing.

`evidence_basis` and `alternatives` are never produced by the LLM -- they are
assembled directly from the `EvidenceBundle` by `pipeline/synthesis.py`. Every
`ProConItem.citation` is guaranteed, by the time a `Verdict` is constructed,
to have been resolved against a real `EvidenceBundle` item (AD-4, AD-7) --
`synthesize_verdict()` drops any pro/con whose citation doesn't resolve
before this model is ever instantiated.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.models.product import ProductFacts, SourceTier


class VerdictLabel(str, Enum):
    """The three possible verdict outcomes (PRD FR-9)."""

    BUY = "BUY"
    SKIP = "SKIP"
    WAIT = "WAIT"


class Citation(BaseModel):
    """A pointer at one specific item inside the `EvidenceBundle` that
    produced a `Verdict`.

    `source_index` indexes into `EvidenceBundle.reviews` (for `"review"`) or
    `EvidenceBundle.alternatives` (for `"alternative"`); it is `None` for
    `"product_fact"`, since a bundle carries exactly one `ProductFacts`
    record to point at. There is deliberately no price-history source type
    (AD-3/FR-9's structural guardrail) -- any price-trend claim is uncitable
    by construction and is dropped by the same citation-resolution check
    every other claim goes through.
    """

    source_type: Literal["review", "alternative", "product_fact"]
    source_index: int | None = None
    quote: str


class ProConItem(BaseModel):
    """One pro or con claim, always paired with its grounding citation."""

    text: str
    citation: Citation


class EvidenceBasis(BaseModel):
    """Small structured object so the UI can always render the Confidence
    Score next to the evidence it's based on (PRD FR-12), never a bare
    number."""

    review_count: int = Field(ge=0)
    is_low_signal: bool
    alternatives_count: int = Field(ge=0)
    source_tier: SourceTier


class Verdict(BaseModel):
    """The one structured, schema-validated verdict (AD-7).

    `confidence` is always `compute_confidence(bundle)`'s output -- any
    confidence value the LLM produced is discarded before this model is
    constructed (AD-6). `evidence_basis` and `alternatives` come directly
    from the `EvidenceBundle`, never from the LLM.
    """

    schema_version: int
    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_basis: EvidenceBasis
    pros: list[ProConItem]
    cons: list[ProConItem]
    alternatives: list[ProductFacts]
    reasoning_summary: str
