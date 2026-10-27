"""Tests for the in-memory job store and `run_job()` (Story 1.9, AD-10).

Covers `create_job()`/`get_job_queue()`/`run_job()` with stub
`ProductSource`/`LLMClient` implementations -- no live network/API calls,
matching this project's established testing convention.
"""

import asyncio

from app.jobs import CLOSE_SENTINEL, create_job, get_job_queue, run_job
from app.models.llm import DraftVerdict, ThemeClusters
from app.models.product import ProductFacts, SourceFailure, SourceTier
from app.models.review import Review
from app.models.verdict import Citation, ProConItem, VerdictLabel

VALID_URL = "https://www.amazon.com/dp/B08N5WRWNW"


class _StubSource:
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
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, *, system_prompt, user_prompt, response_model, model):
        self.calls.append({"model": model, "response_model": response_model})
        return self._responses.pop(0)


def _facts(
    category: str | None = "Smart Speakers",
    review_count: int | None = 25,
    source_tier: SourceTier = SourceTier.TIER_2,
) -> ProductFacts:
    return ProductFacts(
        canonical_product_id="amazon:B08N5WRWNW",
        title="Echo Dot",
        price=39.99,
        specs={"Color": "Charcoal"},
        source_tier=source_tier,
        category=category,
        review_count=review_count,
    )


def _review(rating: int = 5, body: str = "Great sound quality and battery life.") -> Review:
    return Review(rating=rating, body=body)


def _themes() -> ThemeClusters:
    return ThemeClusters(pros_themes=["good sound"], cons_themes=[])


def _resolvable_draft() -> DraftVerdict:
    return DraftVerdict(
        label=VerdictLabel.BUY,
        confidence=0.9,
        pros=[
            ProConItem(
                text="Great sound quality",
                citation=Citation(
                    source_type="review", source_index=0, quote="Great sound quality"
                ),
            )
        ],
        cons=[],
        reasoning_summary="Reviewers consistently praise the sound quality.",
    )


def _drain(queue: "asyncio.Queue") -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_create_job_returns_a_job_id_with_a_backing_queue():
    job_id = create_job()

    assert isinstance(job_id, str)
    assert job_id
    queue = get_job_queue(job_id)
    assert isinstance(queue, asyncio.Queue)


def test_create_job_returns_distinct_unguessable_ids():
    job_id_1 = create_job()
    job_id_2 = create_job()

    assert job_id_1 != job_id_2


def test_get_job_queue_returns_none_for_unknown_job_id():
    assert get_job_queue("not-a-real-job-id") is None


def test_run_job_happy_path_enqueues_stage_events_then_result_then_closes():
    job_id = create_job()
    facts = _facts()
    source = _StubSource(facts, reviews=[_review()])
    llm = _StubLLMClient([_themes(), _resolvable_draft()])

    asyncio.run(run_job(job_id, VALID_URL, source, llm))

    items = _drain(get_job_queue(job_id))
    assert items[-1] is CLOSE_SENTINEL
    stage_items = items[:-2]
    result_item = items[-2]

    assert [item["stage"] for item in stage_items] == [
        "resolving_product",
        "sampling_reviews",
        "finding_alternatives",
        "synthesizing_verdict",
    ]
    assert result_item["event"] == "result"
    assert result_item["result_kind"] == "confident"
    assert result_item["result"]["label"] == "BUY"


def test_run_job_insufficient_data_path_carries_insufficient_data_result_kind():
    job_id = create_job()
    failure = SourceFailure(source_tier=SourceTier.TIER_2, reason="fetch_failed")
    source = _StubSource(failure)
    llm = _StubLLMClient([_themes(), _resolvable_draft()])

    asyncio.run(run_job(job_id, VALID_URL, source, llm))

    items = _drain(get_job_queue(job_id))
    assert items[-1] is CLOSE_SENTINEL
    result_item = items[-2]
    assert result_item["event"] == "result"
    assert result_item["result_kind"] == "insufficient_data"
    assert result_item["result"]["reason"] == "fetch_failed"
    # No synthesis call -- the bundle short-circuited before synthesis ran.
    assert llm.calls == []


def test_run_job_invalid_url_path_carries_insufficient_data_result_kind():
    job_id = create_job()
    source = _StubSource(_facts())
    llm = _StubLLMClient([])

    asyncio.run(run_job(job_id, "https://www.ebay.com/itm/123456", source, llm))

    items = _drain(get_job_queue(job_id))
    result_item = items[-2]
    assert result_item["result_kind"] == "insufficient_data"
    assert result_item["result"]["reason"] == "invalid_url"
    assert items[-1] is CLOSE_SENTINEL


def test_run_job_unexpected_error_recovers_to_insufficient_data_then_closes():
    """Covers `run_job()`'s broad `except Exception` around `produce_verdict()`
    (AD-4/AD-9): a source that raises mid-pipeline must still resolve to an
    `insufficient_data` result event followed by `CLOSE_SENTINEL`, never an
    unhandled exception out of the background task."""

    class _RaisingSource:
        async def fetch(self, url: str) -> ProductFacts | SourceFailure:
            raise RuntimeError("boom")

        async def fetch_reviews(self, url: str) -> list[Review]:
            return []

        async def find_candidate_alternatives(self, category: str | None) -> list[ProductFacts]:
            return []

    job_id = create_job()
    llm = _StubLLMClient([])

    asyncio.run(run_job(job_id, VALID_URL, _RaisingSource(), llm))

    items = _drain(get_job_queue(job_id))
    assert items[-1] is CLOSE_SENTINEL
    result_item = items[-2]
    assert result_item["event"] == "result"
    assert result_item["result_kind"] == "insufficient_data"
    assert result_item["result"]["reason"] == "unexpected_error"


def test_run_job_with_unknown_job_id_returns_without_raising():
    source = _StubSource(_facts())
    llm = _StubLLMClient([_themes(), _resolvable_draft()])

    result = asyncio.run(run_job("not-a-real-job-id", VALID_URL, source, llm))

    assert result is None
