"""Tests for `resolve_product_facts()` (AD-1, AD-4).

Covers the story's I/O & Edge-Case Matrix using a stub `ProductSource` --
no real scraper/network needed, and no change to Story 1.1's modules.
"""

import asyncio

import pytest

from app.models.product import InsufficientDataResult, ProductFacts, SourceFailure, SourceTier
from app.pipeline.orchestrator import resolve_product_facts

VALID_URL = "https://www.amazon.com/dp/B08N5WRWNW"


class _StubSource:
    """A `ProductSource` stub returning a pre-set result and recording calls."""

    def __init__(self, result: ProductFacts | SourceFailure) -> None:
        self._result = result
        self.fetch_calls: list[str] = []

    async def fetch(self, url: str) -> ProductFacts | SourceFailure:
        self.fetch_calls.append(url)
        return self._result


def _facts() -> ProductFacts:
    return ProductFacts(
        canonical_product_id="amazon:B08N5WRWNW",
        title="Echo Dot",
        price=39.99,
        specs={"Color": "Charcoal"},
        source_tier=SourceTier.TIER_2,
    )


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
