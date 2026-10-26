"""Tests for `synthesize_verdict()` (AD-4, AD-5, AD-6, AD-7, AD-9).

Covers this story's I/O & Edge-Case Matrix using a stub `LLMClient` -- no
live OpenAI calls (this story's own testing rule, mirroring `ProductSource`'s
convention).
"""

import asyncio

from app.models.evidence import EvidenceBundle
from app.models.llm import DraftVerdict, LLMCallFailure, ThemeClusters
from app.models.product import InsufficientDataResult, ProductFacts, SourceTier
from app.models.review import Review
from app.models.review_signal import ReviewSignalAssessment
from app.models.verdict import Citation, ProConItem, Verdict, VerdictLabel
from app.pipeline.confidence import compute_confidence
from app.pipeline.synthesis import synthesize_verdict

_REVIEW_0_BODY = "The battery life is disappointing and dies within a day."
_REVIEW_1_BODY = "Sound quality is excellent for the price."


def _facts(category: str | None = "Smart Speakers") -> ProductFacts:
    return ProductFacts(
        canonical_product_id="amazon:B08N5WRWNW",
        title="Echo Dot",
        price=39.99,
        specs={"Color": "Charcoal"},
        source_tier=SourceTier.TIER_2,
        category=category,
        review_count=25,
    )


def _alt(index: int) -> ProductFacts:
    return ProductFacts(
        canonical_product_id=f"amazon:ALT{index:07d}",
        title=f"Alternative Speaker {index}",
        price=35.0,
        source_tier=SourceTier.TIER_2,
    )


def _bundle(reviews=None, alternatives=None, is_low_signal=False) -> EvidenceBundle:
    return EvidenceBundle(
        product_facts=_facts(),
        reviews=reviews
        if reviews is not None
        else [
            Review(rating=2, body=_REVIEW_0_BODY),
            Review(rating=5, body=_REVIEW_1_BODY),
        ],
        review_signal=ReviewSignalAssessment(
            is_low_signal=is_low_signal,
            reason="Review count is low." if is_low_signal else None,
        ),
        alternatives=alternatives if alternatives is not None else [_alt(0)],
    )


def _themes() -> ThemeClusters:
    return ThemeClusters(pros_themes=["good sound"], cons_themes=["short battery life"])


def _resolvable_draft(label: VerdictLabel = VerdictLabel.SKIP) -> DraftVerdict:
    """A draft whose pro and con both carry resolvable citations."""
    return DraftVerdict(
        label=label,
        confidence=0.99,  # deliberately wrong/self-reported -- must be discarded
        pros=[
            ProConItem(
                text="Great sound quality",
                citation=Citation(source_type="review", source_index=1, quote="Sound quality is excellent"),
            )
        ],
        cons=[
            ProConItem(
                text="Battery life is short",
                citation=Citation(
                    source_type="review", source_index=0, quote="battery life is disappointing"
                ),
            )
        ],
        reasoning_summary="Mixed signal: good sound, poor battery life.",
    )


def _unresolvable_draft(label: VerdictLabel = VerdictLabel.WAIT) -> DraftVerdict:
    """A draft whose pro and con both carry citations that don't resolve."""
    return DraftVerdict(
        label=label,
        confidence=0.5,
        pros=[
            ProConItem(
                text="Fabricated claim",
                citation=Citation(source_type="review", source_index=99, quote="not a real quote"),
            )
        ],
        cons=[
            ProConItem(
                text="Another fabricated claim",
                citation=Citation(source_type="alternative", source_index=99, quote="not real either"),
            )
        ],
        reasoning_summary="Inconclusive.",
    )


def _mixed_draft() -> DraftVerdict:
    """A draft with one resolvable pro and one unresolvable con."""
    return DraftVerdict(
        label=VerdictLabel.BUY,
        confidence=0.9,
        pros=[
            ProConItem(
                text="Great sound quality",
                citation=Citation(source_type="review", source_index=1, quote="Sound quality is excellent"),
            )
        ],
        cons=[
            ProConItem(
                text="Fabricated con",
                citation=Citation(source_type="review", source_index=42, quote="does not exist"),
            )
        ],
        reasoning_summary="Mostly positive.",
    )


# -- Complete bundle, LLM succeeds first try -----------------------------


def test_llm_succeeds_first_try_yields_final_verdict_with_overwritten_confidence(stub_llm_client):
    bundle = _bundle()
    draft = _resolvable_draft(label=VerdictLabel.SKIP)
    llm = stub_llm_client([_themes(), draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert result.label == VerdictLabel.SKIP
    assert result.confidence == compute_confidence(bundle)
    assert result.confidence != draft.confidence  # the LLM's own value is discarded
    assert len(result.pros) == 1
    assert len(result.cons) == 1
    # Exactly two LLM calls: theme clustering, then synthesis -- no retry.
    assert len(llm.calls) == 2


def test_evidence_basis_and_alternatives_come_from_bundle_not_llm(stub_llm_client):
    bundle = _bundle()
    draft = _resolvable_draft()
    llm = stub_llm_client([_themes(), draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert result.evidence_basis.review_count == len(bundle.reviews)
    assert result.evidence_basis.is_low_signal == bundle.review_signal.is_low_signal
    assert result.evidence_basis.alternatives_count == len(bundle.alternatives)
    assert result.evidence_basis.source_tier == bundle.product_facts.source_tier
    assert result.alternatives == bundle.alternatives


def test_schema_version_is_set(stub_llm_client):
    bundle = _bundle()
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert result.schema_version == 1


# -- Zero resolvable claims on first try, retry succeeds ------------------


def test_zero_resolvable_on_first_try_retries_and_succeeds(stub_llm_client):
    bundle = _bundle()
    first_draft = _unresolvable_draft()
    retried_draft = _resolvable_draft(label=VerdictLabel.BUY)
    llm = stub_llm_client([_themes(), first_draft, retried_draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert result.label == VerdictLabel.BUY
    assert len(result.pros) == 1
    assert len(result.cons) == 1
    # theme call + first synthesis call + one retry synthesis call.
    assert len(llm.calls) == 3
    # The retry prompt carries the validation error appended.
    assert "Validation failed" in llm.calls[2]["user_prompt"]


# -- Both attempts leave zero resolvable claims ----------------------------


def test_both_attempts_unresolvable_yields_insufficient_data(stub_llm_client):
    bundle = _bundle()
    llm = stub_llm_client([_themes(), _unresolvable_draft(), _unresolvable_draft()])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, InsufficientDataResult)
    assert not isinstance(result, Verdict)
    assert len(llm.calls) == 3


# -- Underlying LLM call fails outright ------------------------------------


def test_theme_call_failure_yields_insufficient_data_without_synthesis_call(stub_llm_client):
    bundle = _bundle()
    failure = LLMCallFailure(reason="timeout", detail="theme call timed out")
    llm = stub_llm_client([failure])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "timeout"
    assert result.detail == "theme call timed out"
    assert len(llm.calls) == 1  # synthesis call never attempted


def test_synthesis_call_failure_yields_insufficient_data(stub_llm_client):
    bundle = _bundle()
    failure = LLMCallFailure(reason="llm_call_failed", detail="network error")
    llm = stub_llm_client([_themes(), failure])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "llm_call_failed"
    assert result.detail == "network error"


def test_retry_call_failure_yields_insufficient_data(stub_llm_client):
    bundle = _bundle()
    failure = LLMCallFailure(reason="llm_call_failed", detail="network error on retry")
    llm = stub_llm_client([_themes(), _unresolvable_draft(), failure])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, InsufficientDataResult)
    assert result.detail == "network error on retry"


# -- Some but not all citations unresolved ---------------------------------


def test_mixed_resolvable_and_unresolvable_drops_only_the_unresolvable_ones(stub_llm_client):
    bundle = _bundle()
    draft = _mixed_draft()
    llm = stub_llm_client([_themes(), draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert len(result.pros) == 1
    assert result.pros[0].text == "Great sound quality"
    assert len(result.cons) == 0  # the fabricated con was dropped
    # No retry needed: at least one resolvable claim (the pro) remained.
    assert len(llm.calls) == 2


# -- "Wait" label, no price-history data -----------------------------------


def test_wait_label_citations_never_reference_price_history(stub_llm_client):
    """`Citation.source_type` has no price-history option at all, so a
    WAIT verdict's citations can only point at reviews, alternatives, or
    product facts -- never price trends (FR-9's structural guardrail)."""
    bundle = _bundle()
    draft = _resolvable_draft(label=VerdictLabel.WAIT)
    llm = stub_llm_client([_themes(), draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert result.label == VerdictLabel.WAIT
    all_items = result.pros + result.cons
    assert all(item.citation.source_type in ("review", "alternative", "product_fact") for item in all_items)


def test_fabricated_price_trend_claim_as_product_fact_is_dropped(stub_llm_client):
    """A citation tagged `product_fact` whose quote doesn't literally match
    any real fact field (e.g. a fabricated price-trend claim) is dropped --
    the same citation check every other claim goes through."""
    bundle = _bundle()
    draft = DraftVerdict(
        label=VerdictLabel.WAIT,
        confidence=0.5,
        pros=[],
        cons=[
            ProConItem(
                text="Price has been trending down recently",
                citation=Citation(
                    source_type="product_fact",
                    source_index=None,
                    quote="price has been trending down",
                ),
            )
        ],
        reasoning_summary="Inconclusive.",
    )
    retried = _resolvable_draft(label=VerdictLabel.WAIT)
    llm = stub_llm_client([_themes(), draft, retried])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    # The fabricated price-trend "product_fact" claim never resolves (it
    # matches no real title/price/spec text), so the first attempt resolves
    # to nothing and a retry happens; the retry's genuinely-grounded claims
    # are what the final Verdict carries.
    assert isinstance(result, Verdict)
    assert all(item.citation.quote != "price has been trending down" for item in result.cons)


def test_product_fact_citation_resolves_when_quote_matches_real_fact(stub_llm_client):
    bundle = _bundle()
    draft = DraftVerdict(
        label=VerdictLabel.BUY,
        confidence=0.8,
        pros=[
            ProConItem(
                text="Comes in a nice color",
                citation=Citation(source_type="product_fact", source_index=None, quote="Charcoal"),
            )
        ],
        cons=[],
        reasoning_summary="Solid product fact grounding.",
    )
    llm = stub_llm_client([_themes(), draft])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert len(result.pros) == 1


# -- Missing source_index on an indexed citation type ----------------------


def test_review_citation_with_no_source_index_is_dropped_not_raised(stub_llm_client):
    """A `review`-typed citation with `source_index=None` has nothing to
    index into -- it must resolve to `None` (and get dropped) rather than
    raise, even though its quote would otherwise be long enough to match."""
    bundle = _bundle()
    draft = DraftVerdict(
        label=VerdictLabel.WAIT,
        confidence=0.5,
        pros=[],
        cons=[
            ProConItem(
                text="Battery life is short",
                citation=Citation(
                    source_type="review", source_index=None, quote="battery life is disappointing"
                ),
            )
        ],
        reasoning_summary="Inconclusive.",
    )
    retried = _resolvable_draft(label=VerdictLabel.WAIT)
    llm = stub_llm_client([_themes(), draft, retried])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert all(item.citation.source_index is not None for item in result.pros + result.cons)


def test_alternative_citation_with_no_source_index_is_dropped_not_raised(stub_llm_client):
    """An `alternative`-typed citation with `source_index=None` has nothing
    to index into -- it must resolve to `None` (and get dropped) rather than
    raise, even though its quote would otherwise be long enough to match."""
    bundle = _bundle()
    draft = DraftVerdict(
        label=VerdictLabel.WAIT,
        confidence=0.5,
        pros=[
            ProConItem(
                text="An alternative exists",
                citation=Citation(
                    source_type="alternative", source_index=None, quote="Alternative Speaker 0"
                ),
            )
        ],
        cons=[],
        reasoning_summary="Inconclusive.",
    )
    retried = _resolvable_draft(label=VerdictLabel.WAIT)
    llm = stub_llm_client([_themes(), draft, retried])

    result = asyncio.run(synthesize_verdict(bundle, llm))

    assert isinstance(result, Verdict)
    assert all(item.citation.source_index is not None for item in result.pros + result.cons)


# -- Model routing ----------------------------------------------------------


def test_theme_call_uses_cheap_model_and_synthesis_call_uses_strong_model(
    stub_llm_client, monkeypatch
):
    # Override to distinct, non-default values so this test would fail if
    # the code bypassed `Settings` and hardcoded today's defaults instead of
    # actually reading the configured model names.
    monkeypatch.setenv("LLM_CHEAP_MODEL", "test-cheap-model-override")
    monkeypatch.setenv("LLM_STRONG_MODEL", "test-strong-model-override")
    bundle = _bundle()
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    asyncio.run(synthesize_verdict(bundle, llm))

    assert llm.calls[0]["model"] == "test-cheap-model-override"
    assert llm.calls[0]["response_model"] is ThemeClusters
    assert llm.calls[1]["model"] == "test-strong-model-override"
    assert llm.calls[1]["response_model"] is DraftVerdict
