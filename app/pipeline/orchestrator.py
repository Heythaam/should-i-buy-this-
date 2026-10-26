"""The pipeline orchestrator (core/shared, AD-1, AD-11).

`resolve_product_facts()` is the only place that decides whether a request
became `ProductFacts` or the FR-3-level `InsufficientDataResult` (AD-4): it
calls `canonicalize()` then `source.fetch()`, and never lets a
`canonicalize()` exception or a `SourceFailure` propagate past itself
unconverted. Taken on its own, `resolve_product_facts()` has no code path
that calls LLM synthesis, so "a failure never reaches synthesis" holds
structurally for it; `produce_verdict()` below is what actually wires this
function's result into `synthesize_verdict()`, short-circuiting first.

`assemble_evidence_bundle()` (Story 1.6) composes `resolve_product_facts()`
with Story 1.3-1.5's review/alternatives functions into one `EvidenceBundle`
-- the one consistent record a future Verdict (Story 1.7) is grounded in. It
reuses those functions exactly as they are; its only logic is the
short-circuit-on-insufficient-data sequencing (see this story's spec Design
Notes).

`produce_verdict()` (Story 1.7) composes `assemble_evidence_bundle()` with
`pipeline/synthesis.py::synthesize_verdict()` into the complete end-to-end
v1 pipeline: canonicalize -> extract facts -> sample reviews -> find
alternatives -> assemble Evidence Bundle -> LLM synthesis -> compute
confidence -> `Verdict`. It short-circuits on an `InsufficientDataResult`
from either stage -- a failed/insufficient Evidence Bundle never reaches
`synthesize_verdict()` (AD-4).

Intentionally minimal (three functions) rather than building out
job/queue/SSE machinery now -- that belongs to Story 1.9 (AD-10); AD-11 lets
that story extend this same file in place.
"""

import logging

from app.models.evidence import EvidenceBundle
from app.models.product import InsufficientDataResult, ProductFacts, SourceFailure
from app.models.verdict import Verdict
from app.pipeline.alternatives import select_alternatives
from app.pipeline.canonicalize import InvalidProductURLError, canonicalize
from app.pipeline.llm_client import LLMClient
from app.pipeline.review_sampling import sample_reviews
from app.pipeline.review_signal import assess_review_signal
from app.pipeline.sources.base import ProductSource
from app.pipeline.synthesis import synthesize_verdict

logger = logging.getLogger(__name__)


async def resolve_product_facts(
    url: str, source: ProductSource
) -> ProductFacts | InsufficientDataResult:
    """Resolve `url` to `ProductFacts`, or an honest `InsufficientDataResult`.

    Never raises (AD-4): a `canonicalize()` failure (non-Amazon/malformed
    URL) and a `source.fetch()` degradation (blocked/CAPTCHA/unsupported
    layout) both map to `InsufficientDataResult` instead of propagating.
    `source` is injected rather than constructed here, so a future Tier 1/3
    source can be passed in without changing this function.
    """
    try:
        canonicalize(url)
    except InvalidProductURLError as exc:
        logger.warning("resolve_product_facts: invalid_url for %s: %s", url, exc)
        return InsufficientDataResult(reason="invalid_url", detail=str(exc))

    result = await source.fetch(url)

    if isinstance(result, SourceFailure):
        logger.warning(
            "resolve_product_facts: %s for %s (source_tier=%s)",
            result.reason,
            url,
            result.source_tier,
        )
        return InsufficientDataResult(
            reason=result.reason,
            detail=result.detail,
            source_tier=result.source_tier,
        )

    return result


async def assemble_evidence_bundle(
    url: str, source: ProductSource
) -> EvidenceBundle | InsufficientDataResult:
    """Assemble the one `EvidenceBundle` a future Verdict is grounded in.

    Composes, in order, `resolve_product_facts()`, `source.fetch_reviews()`,
    `sample_reviews()`, `assess_review_signal()`,
    `source.find_candidate_alternatives()`, and `select_alternatives()`.

    A failed or insufficient extraction short-circuits immediately (AD-4):
    `resolve_product_facts()`'s `InsufficientDataResult` is returned
    unchanged, before any review or alternatives call is made -- Story 1.2's
    honest-failure gate is never bypassed. Every sub-stage's degraded/empty
    result (no reviews, low review signal, no alternatives) is carried
    through into the bundle as-is -- this function adds no interpretation of
    its own.
    """
    facts_or_insufficient = await resolve_product_facts(url, source)
    if isinstance(facts_or_insufficient, InsufficientDataResult):
        return facts_or_insufficient

    facts = facts_or_insufficient

    reviews = await source.fetch_reviews(url)
    if not reviews:
        logger.warning("assemble_evidence_bundle: no_reviews_found for %s", url)
    sampled_reviews = sample_reviews(reviews)

    # Signal is computed from the page's aggregate `review_count` (Story
    # 1.4's own design), not `len(reviews)`/`len(sampled_reviews)` -- the
    # bounded sample is deliberately capped and would under-count on
    # popular products.
    review_signal = assess_review_signal(facts.review_count)
    if review_signal.is_low_signal:
        logger.warning(
            "assemble_evidence_bundle: low_review_signal for %s: %s",
            url,
            review_signal.reason,
        )

    # `facts.category` may be `None` or `""` here; `find_candidate_alternatives()`
    # already guards both cases (Story 1.5) and returns `[]` rather than
    # raising, so no extra guard is needed at this call site.
    candidates = await source.find_candidate_alternatives(facts.category)
    alternatives = select_alternatives(facts, candidates)
    if not alternatives:
        logger.warning("assemble_evidence_bundle: no_alternatives_found for %s", url)

    return EvidenceBundle(
        product_facts=facts,
        reviews=sampled_reviews,
        review_signal=review_signal,
        alternatives=alternatives,
    )


async def produce_verdict(
    url: str, source: ProductSource, llm: LLMClient
) -> Verdict | InsufficientDataResult:
    """Run the complete end-to-end v1 pipeline for `url`.

    Composes `assemble_evidence_bundle()` then `synthesize_verdict()`,
    short-circuiting on an `InsufficientDataResult` from either -- a failed
    or insufficient Evidence Bundle is returned unchanged, before
    `synthesize_verdict()` (and therefore any LLM call) is ever invoked
    (AD-4).
    """
    bundle_or_insufficient = await assemble_evidence_bundle(url, source)
    if isinstance(bundle_or_insufficient, InsufficientDataResult):
        return bundle_or_insufficient

    return await synthesize_verdict(bundle_or_insufficient, llm)
