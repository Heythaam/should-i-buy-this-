"""Tests for the `GET /` route (`ui` branch, this story).

Covers the story's I/O & Edge-Case Matrix using `fastapi.testclient.TestClient`
plus stub `ProductSource`/`LLMClient` implementations wired in via
`app.dependency_overrides` -- no live network/API call is ever made here,
mirroring every prior story's "no live network calls in tests" rule.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_llm_client, get_product_source
from app.models.llm import DraftVerdict, ThemeClusters
from app.models.product import ProductFacts, SourceFailure, SourceTier
from app.models.review import Review
from app.models.verdict import Citation, ProConItem, VerdictLabel
from app.pipeline.llm_client import OpenAIClient
from app.pipeline.sources.scraper_tier2 import ScraperTier2Source

VALID_URL = "https://www.amazon.com/dp/B08N5WRWNW"
NON_AMAZON_URL = "https://www.ebay.com/itm/123456"


class _StubSource:
    """A `ProductSource` stub returning pre-set results (mirrors
    `tests/pipeline/test_orchestrator.py::_StubSource`)."""

    def __init__(
        self,
        result: ProductFacts | SourceFailure,
        reviews: list[Review] | None = None,
        alternatives: list[ProductFacts] | None = None,
    ) -> None:
        self._result = result
        self._reviews = reviews if reviews is not None else []
        self._alternatives = alternatives if alternatives is not None else []

    async def fetch(self, url: str) -> ProductFacts | SourceFailure:
        return self._result

    async def fetch_reviews(self, url: str) -> list[Review]:
        return self._reviews

    async def find_candidate_alternatives(self, category: str | None) -> list[ProductFacts]:
        return self._alternatives


class _StubLLMClient:
    """An `LLMClient` stub returning pre-set responses in call order
    (mirrors `tests/pipeline/conftest.py::StubLLMClient`)."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)

    async def complete(self, *, system_prompt, user_prompt, response_model, model):
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def _client(source, llm) -> TestClient:
    app.dependency_overrides[get_product_source] = lambda: source
    app.dependency_overrides[get_llm_client] = lambda: llm
    return TestClient(app)


def _facts(
    source_tier: SourceTier = SourceTier.TIER_2,
    category: str | None = "Smart Speakers",
    review_count: int | None = 25,
    title: str = "Widget 3000 Pro Max",
    price: float | None = 39.99,
    canonical_product_id: str = "amazon:B08N5WRWNW",
) -> ProductFacts:
    return ProductFacts(
        canonical_product_id=canonical_product_id,
        title=title,
        price=price,
        specs={"Color": "Charcoal"},
        source_tier=source_tier,
        category=category,
        review_count=review_count,
    )


def _review(rating: int = 5, body: str = "Great sound quality and battery life.") -> Review:
    return Review(rating=rating, body=body)


def _themes() -> ThemeClusters:
    return ThemeClusters(pros_themes=["good sound"], cons_themes=[])


def test_no_url_submitted_renders_form_only_with_no_result_section():
    client = _client(_StubSource(_facts()), _StubLLMClient([]))

    response = client.get("/")

    assert response.status_code == 200
    assert "<form" in response.text
    assert 'class="result' not in response.text


def test_confident_verdict_renders_all_fields_with_confident_styling():
    facts = _facts(source_tier=SourceTier.TIER_2, review_count=25)
    reviews = [_review()]
    # Claim text and citation quote are deliberately distinct (unlike a
    # same-string fixture) so the test can tell whether the template's
    # separate claim/citation-quote/source_type rendering actually runs,
    # rather than one string happening to satisfy both assertions.
    draft = DraftVerdict(
        label=VerdictLabel.BUY,
        confidence=0.9,
        pros=[
            ProConItem(
                text="Sound quality impressed reviewers",
                citation=Citation(
                    source_type="review", source_index=0, quote="Great sound quality"
                ),
            )
        ],
        cons=[],
        reasoning_summary="Reviewers consistently praise the sound quality.",
    )
    # Price (34.90) is inside select_alternatives()'s +/-20% band around
    # facts.price (39.99) and uses a distinct canonical_product_id, so it
    # actually survives the real pipeline's alternatives filtering and the
    # alternatives-list loop body in index.html actually executes.
    alternative = _facts(
        title="Other Widget", price=34.9, canonical_product_id="amazon:OTHERWIDGET"
    )
    source = _StubSource(facts, reviews=reviews, alternatives=[alternative])
    llm = _StubLLMClient([_themes(), draft])

    response = _client(source, llm).get("/", params={"url": VALID_URL})

    assert response.status_code == 200
    assert 'class="result result--confident"' in response.text
    assert "result--low_confidence" not in response.text
    assert "result--insufficient_data" not in response.text
    assert "BUY" in response.text
    assert "Sound quality impressed reviewers" in response.text  # the claim
    assert "Great sound quality" in response.text  # the citation quote
    assert "(review)" in response.text  # the citation source_type
    assert "Reviewers consistently praise the sound quality." in response.text
    assert "1 review" in response.text  # evidence basis: len(sampled reviews) == 1
    assert "(low review signal)" not in response.text  # evidence_basis.is_low_signal is False
    assert "1 alternative(s) found" in response.text  # evidence_basis.alternatives_count
    assert "via TIER_2 source" in response.text  # evidence_basis.source_tier
    assert "Other Widget" in response.text  # alternatives-list loop: title
    assert "$34.90" in response.text  # alternatives-list loop: two-decimal price


def test_low_confidence_verdict_renders_with_distinct_styling():
    # TIER_3 + unknown review count + zero sampled reviews keeps
    # `compute_confidence()` well below this story's threshold, while a
    # product-fact citation (independent of any review) keeps the Verdict
    # resolvable rather than falling back to InsufficientDataResult.
    facts = _facts(source_tier=SourceTier.TIER_3, review_count=None, title="Widget 3000 Pro Max")
    draft = DraftVerdict(
        label=VerdictLabel.WAIT,
        confidence=0.9,
        pros=[],
        cons=[
            ProConItem(
                text="Limited evidence available",
                citation=Citation(
                    source_type="product_fact", source_index=None, quote="Widget 3000 Pro Max"
                ),
            )
        ],
        reasoning_summary="Too little evidence to be confident either way.",
    )
    source = _StubSource(facts, reviews=[])
    llm = _StubLLMClient([_themes(), draft])

    response = _client(source, llm).get("/", params={"url": VALID_URL})

    assert response.status_code == 200
    assert 'class="result result--low_confidence"' in response.text
    assert "result--confident" not in response.text
    assert "result--insufficient_data" not in response.text
    assert "WAIT" in response.text
    assert "This is a low-confidence verdict." in response.text


def test_insufficient_data_from_source_failure_renders_distinct_styling():
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="fetch_failed", detail="blocked")
    source = _StubSource(failure)
    llm = _StubLLMClient([_themes(), DraftVerdict(
        label=VerdictLabel.BUY, confidence=0.9, pros=[], cons=[], reasoning_summary=""
    )])

    response = _client(source, llm).get("/", params={"url": VALID_URL})

    assert response.status_code == 200
    assert 'class="result result--insufficient_data"' in response.text
    assert "result--confident" not in response.text
    assert "result--low_confidence" not in response.text
    assert "fetch_failed" in response.text
    assert "blocked" in response.text  # result.detail
    assert "TIER_2" in response.text  # result.source_tier.value


def test_non_amazon_url_renders_insufficient_data_with_invalid_url_reason():
    source = _StubSource(_facts())
    llm = _StubLLMClient([])

    response = _client(source, llm).get("/", params={"url": NON_AMAZON_URL})

    assert response.status_code == 200
    assert 'class="result result--insufficient_data"' in response.text
    assert "invalid_url" in response.text


def test_malformed_url_renders_insufficient_data():
    source = _StubSource(_facts())
    llm = _StubLLMClient([])

    response = _client(source, llm).get("/", params={"url": "not a url at all"})

    assert response.status_code == 200
    assert 'class="result result--insufficient_data"' in response.text
    assert "invalid_url" in response.text


def test_whitespace_only_url_renders_insufficient_data():
    source = _StubSource(_facts())
    llm = _StubLLMClient([])

    response = _client(source, llm).get("/", params={"url": " "})

    assert response.status_code == 200
    assert 'class="result result--insufficient_data"' in response.text
    assert "invalid_url" in response.text


def test_get_product_source_and_get_llm_client_return_real_port_instances():
    """The un-overridden providers (no `app.dependency_overrides` involved)
    must return the real I/O ports, constructed from a single module-level
    `Settings()` -- never a stub, and never reconstructed per call."""
    assert isinstance(get_product_source(), ScraperTier2Source)
    assert isinstance(get_llm_client(), OpenAIClient)
