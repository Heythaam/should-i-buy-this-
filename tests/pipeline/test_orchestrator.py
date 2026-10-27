"""Tests for `resolve_product_facts()` and `assemble_evidence_bundle()`
(AD-1, AD-4, AD-5).

Covers the story's I/O & Edge-Case Matrix using a stub `ProductSource` --
no real scraper/network needed, and no change to Story 1.1-1.5's modules.
"""

import asyncio

import pytest

from app.models.evidence import EvidenceBundle
from app.models.llm import DraftVerdict, LLMCallFailure, ThemeClusters
from app.models.product import InsufficientDataResult, ProductFacts, SourceFailure, SourceTier
from app.models.review import Review
from app.models.verdict import Citation, ProConItem, Verdict, VerdictLabel
from app.pipeline.orchestrator import (
    assemble_evidence_bundle,
    produce_verdict,
    resolve_product_facts,
)

VALID_URL = "https://www.amazon.com/dp/B08N5WRWNW"


class _StubSource:
    """A `ProductSource` stub returning pre-set results and recording calls."""

    def __init__(
        self,
        result: ProductFacts | SourceFailure,
        reviews: list[Review] | None = None,
        alternatives: list[ProductFacts] | None = None,
    ) -> None:
        self._result = result
        self._reviews = reviews if reviews is not None else []
        self._alternatives = alternatives if alternatives is not None else []
        self.fetch_calls: list[str] = []
        self.fetch_reviews_calls: list[str] = []
        self.find_candidate_alternatives_calls: list[str | None] = []

    async def fetch(self, url: str) -> ProductFacts | SourceFailure:
        self.fetch_calls.append(url)
        return self._result

    async def fetch_reviews(self, url: str) -> list[Review]:
        self.fetch_reviews_calls.append(url)
        return self._reviews

    async def find_candidate_alternatives(self, category: str) -> list[ProductFacts]:
        self.find_candidate_alternatives_calls.append(category)
        return self._alternatives


def _facts(
    category: str | None = None,
    review_count: int | None = None,
) -> ProductFacts:
    return ProductFacts(
        canonical_product_id="amazon:B08N5WRWNW",
        title="Echo Dot",
        price=39.99,
        specs={"Color": "Charcoal"},
        source_tier=SourceTier.TIER_2,
        category=category,
        review_count=review_count,
    )


def _review(rating: int = 5, body: str = "Great product.") -> Review:
    return Review(rating=rating, body=body)


def test_valid_url_with_successful_fetch_returns_facts_unchanged():
    facts = _facts()
    source = _StubSource(facts)

    result = asyncio.run(resolve_product_facts(VALID_URL, source))

    assert result is facts
    assert source.fetch_calls == [VALID_URL]


def test_non_amazon_url_returns_insufficient_data_without_calling_fetch():
    source = _StubSource(_facts())

    result = asyncio.run(resolve_product_facts("https://www.ebay.com/itm/123456", source))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "invalid_url"
    # canonicalize() failed -- nothing downstream of it was called.
    assert source.fetch_calls == []


@pytest.mark.parametrize("bad_url", ["", "not a url at all"])
def test_malformed_or_unparseable_url_returns_insufficient_data(bad_url):
    source = _StubSource(_facts())

    result = asyncio.run(resolve_product_facts(bad_url, source))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "invalid_url"
    assert source.fetch_calls == []


def test_domain_spoofing_url_returns_insufficient_data():
    # Well-formed and parseable, but "evil.com" is not an Amazon domain --
    # a different failure mode than the malformed/unparseable cases above.
    source = _StubSource(_facts())

    result = asyncio.run(resolve_product_facts("https://amazon.evil.com/dp/B08N5WRWNW", source))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "invalid_url"
    assert source.fetch_calls == []


def test_source_failure_maps_to_insufficient_data_carrying_its_fields():
    failure = SourceFailure(
        source_tier=SourceTier.TIER_2,
        reason="fetch_failed",
        detail="blocked by CAPTCHA",
    )
    source = _StubSource(failure)

    result = asyncio.run(resolve_product_facts(VALID_URL, source))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "fetch_failed"
    assert result.detail == "blocked by CAPTCHA"
    assert result.source_tier == SourceTier.TIER_2


def test_source_failure_never_raises_and_never_yields_partial_facts():
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="unsupported_layout")
    source = _StubSource(failure)

    result = asyncio.run(resolve_product_facts(VALID_URL, source))

    assert isinstance(result, InsufficientDataResult)
    assert not isinstance(result, ProductFacts)
    assert result.detail is None


# -- assemble_evidence_bundle() -----------------------------------------
#
# Covers the story's I/O & Edge-Case Matrix for Evidence Bundle assembly.


def test_happy_path_assembles_bundle_with_all_four_fields_populated():
    facts = _facts(category="Smart Speakers", review_count=25)
    reviews = [_review(rating=5), _review(rating=1, body="Broke after a week.")]
    alt = _facts(category="Smart Speakers")
    alt = alt.model_copy(update={"canonical_product_id": "amazon:ALT0000001"})
    source = _StubSource(facts, reviews=reviews, alternatives=[alt])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.product_facts is facts
    assert result.reviews == reviews
    assert result.review_signal.is_low_signal is False
    assert len(result.alternatives) == 1
    assert result.alternatives[0].canonical_product_id == "amazon:ALT0000001"
    # Every sub-stage ran, in order, with the expected inputs.
    assert source.fetch_calls == [VALID_URL]
    assert source.fetch_reviews_calls == [VALID_URL]
    assert source.find_candidate_alternatives_calls == ["Smart Speakers"]


def test_insufficient_extraction_short_circuits_before_review_or_alternatives_calls():
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="fetch_failed")
    source = _StubSource(failure)

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, InsufficientDataResult)
    assert not isinstance(result, EvidenceBundle)
    # No review or alternatives work was ever started.
    assert source.fetch_reviews_calls == []
    assert source.find_candidate_alternatives_calls == []


def test_invalid_url_short_circuits_before_fetch_review_or_alternatives_calls():
    source = _StubSource(_facts())

    result = asyncio.run(assemble_evidence_bundle("https://www.ebay.com/itm/123456", source))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "invalid_url"
    assert source.fetch_calls == []
    assert source.fetch_reviews_calls == []
    assert source.find_candidate_alternatives_calls == []


def test_no_reviews_found_yields_empty_reviews_and_low_signal():
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.reviews == []
    # review_signal is driven by facts.review_count (25, >= threshold), not
    # by the empty fetched/sampled review list -- per this story's Design
    # Notes, the two are deliberately independent signals.
    assert result.review_signal.is_low_signal is False


def test_low_review_count_on_facts_yields_low_signal_even_with_reviews_present():
    facts = _facts(category="Smart Speakers", review_count=3)
    source = _StubSource(facts, reviews=[_review()])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.review_signal.is_low_signal is True


def test_unknown_review_count_yields_low_signal_with_distinct_reason():
    facts = _facts(category="Smart Speakers", review_count=None)
    source = _StubSource(facts, reviews=[_review()])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.review_signal.is_low_signal is True
    # Distinct reason from the below-threshold case (test above) -- unknown
    # review count is "absence of evidence", not "evidence of low volume".
    assert result.review_signal.reason is not None
    assert "unknown" in result.review_signal.reason.lower()


def test_no_alternatives_found_yields_empty_alternatives_list():
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, alternatives=[])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.alternatives == []


def test_product_with_no_category_returns_empty_alternatives_without_raising():
    facts = _facts(category=None, review_count=25)
    source = _StubSource(facts)

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.alternatives == []
    # `None` is passed straight through to find_candidate_alternatives(),
    # which already guards this case (Story 1.5) -- no extra guard needed
    # here, and no exception propagates.
    assert source.find_candidate_alternatives_calls == [None]


def test_product_with_empty_string_category_returns_empty_alternatives_without_raising():
    facts = _facts(category="", review_count=25)
    source = _StubSource(facts)

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)
    assert result.alternatives == []
    # `""` is passed straight through to find_candidate_alternatives(),
    # which guards it identically to `None` (Story 1.5) -- no extra guard
    # needed here, and no exception propagates.
    assert source.find_candidate_alternatives_calls == [""]


# -- produce_verdict() ----------------------------------------------------
#
# Covers the end-to-end composition/short-circuit behavior added by this
# story: `assemble_evidence_bundle()` then `synthesize_verdict()`, with the
# `InsufficientDataResult` short-circuit from either stage.


def _themes() -> ThemeClusters:
    return ThemeClusters(pros_themes=["good sound"], cons_themes=["short battery life"])


def _resolvable_draft() -> DraftVerdict:
    return DraftVerdict(
        label=VerdictLabel.BUY,
        confidence=0.42,
        pros=[
            ProConItem(
                text="Great sound",
                citation=Citation(source_type="review", source_index=0, quote="Great product."),
            )
        ],
        cons=[],
        reasoning_summary="Positive signal.",
    )


def test_produce_verdict_happy_path_composes_bundle_assembly_and_synthesis(stub_llm_client):
    facts = _facts(category="Smart Speakers", review_count=25)
    reviews = [_review(rating=5)]
    source = _StubSource(facts, reviews=reviews)
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    result = asyncio.run(produce_verdict(VALID_URL, source, llm))

    assert isinstance(result, Verdict)
    assert result.label == VerdictLabel.BUY
    assert len(llm.calls) == 2


def test_produce_verdict_short_circuits_on_insufficient_bundle_without_calling_llm(stub_llm_client):
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="fetch_failed")
    source = _StubSource(failure)
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    result = asyncio.run(produce_verdict(VALID_URL, source, llm))

    assert isinstance(result, InsufficientDataResult)
    assert not isinstance(result, Verdict)
    assert llm.calls == []  # synthesis never invoked


def test_produce_verdict_short_circuits_on_invalid_url_without_calling_llm(stub_llm_client):
    source = _StubSource(_facts())
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    result = asyncio.run(produce_verdict("https://www.ebay.com/itm/123456", source, llm))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "invalid_url"
    assert llm.calls == []


def test_produce_verdict_returns_insufficient_data_when_synthesis_fails(stub_llm_client):
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[_review()])
    failure = LLMCallFailure(reason="llm_call_failed", detail="network error")
    llm = stub_llm_client([failure])

    result = asyncio.run(produce_verdict(VALID_URL, source, llm))

    assert isinstance(result, InsufficientDataResult)
    assert result.reason == "llm_call_failed"


# -- progress publishing (Story 1.9, AD-10) -------------------------------
#
# A stub `ProgressPublisher` that records every stage name it was called
# with, in call order -- used to assert each function publishes its
# documented stage name(s), and that omitting `progress` entirely still
# behaves exactly as before this story (covered by every test above, none
# of which pass a `progress` argument).


class _StubProgressPublisher:
    def __init__(self) -> None:
        self.stages: list[str] = []

    async def publish(self, stage: str) -> None:
        self.stages.append(stage)


def test_resolve_product_facts_publishes_resolving_product_stage():
    source = _StubSource(_facts())
    publisher = _StubProgressPublisher()

    asyncio.run(resolve_product_facts(VALID_URL, source, publisher))

    assert publisher.stages == ["resolving_product"]


def test_resolve_product_facts_with_no_progress_argument_is_unaffected():
    source = _StubSource(_facts())

    result = asyncio.run(resolve_product_facts(VALID_URL, source))

    assert result is not None  # behaves exactly as before this story


def test_assemble_evidence_bundle_publishes_stages_in_order():
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[_review()], alternatives=[])
    publisher = _StubProgressPublisher()

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source, publisher))

    assert isinstance(result, EvidenceBundle)
    assert publisher.stages == [
        "resolving_product",
        "sampling_reviews",
        "finding_alternatives",
    ]


def test_assemble_evidence_bundle_short_circuit_publishes_only_resolving_product():
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="fetch_failed")
    source = _StubSource(failure)
    publisher = _StubProgressPublisher()

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source, publisher))

    assert isinstance(result, InsufficientDataResult)
    assert publisher.stages == ["resolving_product"]


def test_assemble_evidence_bundle_with_no_progress_argument_is_unaffected():
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[_review()])

    result = asyncio.run(assemble_evidence_bundle(VALID_URL, source))

    assert isinstance(result, EvidenceBundle)


def test_produce_verdict_publishes_every_stage_in_order(stub_llm_client):
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[_review()])
    llm = stub_llm_client([_themes(), _resolvable_draft()])
    publisher = _StubProgressPublisher()

    result = asyncio.run(produce_verdict(VALID_URL, source, llm, publisher))

    assert isinstance(result, Verdict)
    assert publisher.stages == [
        "resolving_product",
        "sampling_reviews",
        "finding_alternatives",
        "synthesizing_verdict",
    ]


def test_produce_verdict_with_no_progress_argument_is_unaffected(stub_llm_client):
    facts = _facts(category="Smart Speakers", review_count=25)
    source = _StubSource(facts, reviews=[_review()])
    llm = stub_llm_client([_themes(), _resolvable_draft()])

    result = asyncio.run(produce_verdict(VALID_URL, source, llm))

    assert isinstance(result, Verdict)
