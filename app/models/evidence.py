"""Shared, typed contract for the assembled Evidence Bundle (AD-5, AD-11).

`models/` is core/shared: any branch may edit it in place when its work
requires it, but it is never forked or shadowed locally. `EvidenceBundle` is
the one consistent record a future Verdict (Story 1.7) is grounded in --
every field is the direct, unmodified output of an existing Story 1.1-1.5
function (see `pipeline/orchestrator.py::assemble_evidence_bundle`). Facts
are kept as a distinct, separately-typed field from opinion-bearing data
(reviews, review signal, alternatives) so a later synthesis step can tell
exact/sourced data apart from probabilistic data (AD-5).
"""

from pydantic import BaseModel

from app.models.product import ProductFacts
from app.models.review import Review
from app.models.review_signal import ReviewSignalAssessment


class EvidenceBundle(BaseModel):
    """The single consistent record combining Stories 1.1/1.3/1.4/1.5's outputs.

    A degraded/empty result from any sub-stage (empty `reviews`, a low-signal
    `review_signal`, empty `alternatives`) is carried through here as-is --
    never re-interpreted or flattened into a different meaning (AD-4).
    """

    product_facts: ProductFacts
    reviews: list[Review]
    review_signal: ReviewSignalAssessment
    alternatives: list[ProductFacts]
