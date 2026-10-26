"""Shared, typed contracts for the LLM-facing side of synthesis (AD-9, AD-11).

`models/` is core/shared: any branch may edit it in place when its work
requires it, but it is never forked or shadowed locally. These types are
deliberately separate from `models/verdict.py::Verdict`: `DraftVerdict` is
what the LLM itself produces and is schema-enforced against (OpenAI
Structured Outputs) -- it has no `evidence_basis`/`alternatives` fields,
since those are code-assembled from the `EvidenceBundle`, never chosen by the
model (AD-6, AD-7). Its `confidence` field is read but always discarded by
`pipeline/synthesis.py` in favor of `compute_confidence()`'s output.
"""

from pydantic import BaseModel, Field

from app.models.verdict import ProConItem, VerdictLabel


class LLMCallFailure(BaseModel):
    """Explicit typed failure sentinel for an `LLMClient.complete()` call.

    Returned instead of raising (AD-4, AD-9) -- mirrors `SourceFailure`'s
    role for `ProductSource.fetch()`.
    """

    reason: str
    detail: str | None = None


class DraftVerdict(BaseModel):
    """The strong model's own structured-output target.

    `confidence` here is the LLM's self-reported value -- read by
    `synthesize_verdict()` only to discard it (AD-6); it is never surfaced to
    a user or copied onto the final `Verdict`.
    """

    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    pros: list[ProConItem]
    cons: list[ProConItem]
    reasoning_summary: str


class ThemeClusters(BaseModel):
    """The cheap model's theme-clustering call output.

    Plain clustered theme strings, not citations -- the strong model's own
    synthesis call is what produces citation-bearing pros/cons; this is only
    a cost-control pre-processing step (see the architecture's Stack section
    and this story's Design Notes) that keeps the expensive call's prompt
    anchored to digested themes rather than an unstructured review dump.
    """

    pros_themes: list[str]
    cons_themes: list[str]
