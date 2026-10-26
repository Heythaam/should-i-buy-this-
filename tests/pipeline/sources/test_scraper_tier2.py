"""Tests for the Tier 2 scraper.

Per this story's rules, no test here makes a live network call. Parsing is
tested against saved HTML fixtures only; `fetch()`'s render step is stubbed
out so retry/degrade/proxy behavior can be verified without Playwright or
network access.
"""

import asyncio
from datetime import date
from pathlib import Path

import pydantic
import pytest

from app.models.product import ProductFacts, SourceFailure, SourceTier
from app.models.review import Review
from app.pipeline.canonicalize import canonicalize
from app.pipeline.sources import scraper_tier2 as scraper_tier2_module
from app.pipeline.sources.scraper_tier2 import (
    ProductPageParseError,
    ScraperTier2Source,
    _parse_price_text,
    build_proxy_config,
    parse_product_facts,
    parse_reviews,
)
from app.settings import Settings

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


async def _no_delay_sleep(_seconds: float) -> None:
    """Stand-in for `asyncio.sleep` so retry-delay tests don't actually wait."""
    return


def test_parse_basic_fixture_yields_title_price_specs():
    html = _read_fixture("amazon_product_basic.html")
    canonical_id = canonicalize("https://www.amazon.com/dp/B08N5WRWNW")

    facts = parse_product_facts(html, canonical_id)

    assert isinstance(facts, ProductFacts)
    assert facts.canonical_product_id == "amazon:B08N5WRWNW"
    assert facts.source_tier == SourceTier.TIER_2
    assert "Charcoal" in facts.title
    assert facts.price == pytest.approx(39.99)
    assert facts.specs["Color"] == "Charcoal"
    assert facts.specs["Brand"] == "Amazon"


def test_parse_variant_fixture_yields_that_variants_own_facts():
    html = _read_fixture("amazon_product_variant.html")
    canonical_id = canonicalize("https://www.amazon.com/dp/B08N5KWB9H")

    facts = parse_product_facts(html, canonical_id)

    assert facts.canonical_product_id == "amazon:B08N5KWB9H"
    assert "Twilight Blue" in facts.title
    assert facts.specs["Color"] == "Twilight Blue"
    assert facts.price == pytest.approx(34.99)


def test_parse_page_without_title_raises_parse_error():
    html = "<html><body><div id='captcha'>Robot Check</div></body></html>"
    canonical_id = canonicalize("https://www.amazon.com/dp/B08N5WRWNW")

    with pytest.raises(ProductPageParseError):
        parse_product_facts(html, canonical_id)


def test_parse_price_text_handles_eu_comma_decimal():
    # amazon.de/.fr/.it/.es/.nl/.se/.pl style: comma is the decimal
    # separator. Must parse as 39.99, not 3999 (100x too large).
    assert _parse_price_text("39,99 €") == pytest.approx(39.99)


def test_parse_price_text_handles_us_thousands_and_decimal():
    assert _parse_price_text("$1,234.56") == pytest.approx(1234.56)


def test_parse_price_text_handles_eu_thousands_and_decimal():
    assert _parse_price_text("1.234,56 €") == pytest.approx(1234.56)


def test_parse_price_text_returns_none_for_ambiguous_comma_usage():
    # A lone comma that's neither a clean 2-digit decimal nor a clean
    # 3-digit-grouped thousands separator is ambiguous -- don't guess.
    assert _parse_price_text("12,3456") is None


def test_extract_specs_keeps_first_value_on_duplicate_label():
    html = """
    <html><body>
      <span id="productTitle">Widget</span>
      <div id="productDetails_techSpec_section_1">
        <table><tbody>
          <tr><th>Color</th><td>Charcoal</td></tr>
          <tr><th>Color</th><td>Overwritten</td></tr>
        </tbody></table>
      </div>
    </body></html>
    """
    canonical_id = canonicalize("https://www.amazon.com/dp/B08N5WRWNW")

    facts = parse_product_facts(html, canonical_id)

    assert facts.specs["Color"] == "Charcoal"


def test_build_proxy_config_none_when_unset():
    assert build_proxy_config(None) is None
    assert build_proxy_config("") is None


def test_build_proxy_config_wraps_url_when_set():
    assert build_proxy_config("http://proxy.example.com:8080") == {
        "server": "http://proxy.example.com:8080"
    }


def test_fetch_returns_source_failure_and_never_raises_when_render_fails(monkeypatch):
    monkeypatch.setattr(scraper_tier2_module.asyncio, "sleep", _no_delay_sleep)

    settings = Settings(scraper_proxy_url=None)
    source = ScraperTier2Source(settings=settings)

    call_count = 0

    async def failing_render(url: str) -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("blocked by CAPTCHA")

    source._render = failing_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, SourceFailure)
    assert result.source_tier == SourceTier.TIER_2
    # one initial attempt + one retry (AD-9), never an unhandled exception
    assert call_count == 2


def test_fetch_recovers_when_first_attempt_fails_and_retry_succeeds(monkeypatch):
    monkeypatch.setattr(scraper_tier2_module.asyncio, "sleep", _no_delay_sleep)

    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))
    html = _read_fixture("amazon_product_basic.html")

    call_count = 0

    async def flaky_render(url: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient block")
        return html

    source._render = flaky_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, ProductFacts)
    assert call_count == 2


def test_fetch_degrades_to_source_failure_when_render_times_out(monkeypatch):
    # Note: deliberately NOT patching asyncio.sleep here -- `hanging_render`
    # below relies on a real `asyncio.sleep` to simulate a hang that
    # `asyncio.wait_for` must actually time out and cancel.
    monkeypatch.setattr(scraper_tier2_module, "_FETCH_TIMEOUT_SECONDS", 0.05)

    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    async def hanging_render(url: str) -> str:
        await asyncio.sleep(10)
        return "<html></html>"

    source._render = hanging_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, SourceFailure)
    assert result.source_tier == SourceTier.TIER_2


def test_fetch_degrades_to_source_failure_on_unparseable_page():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    async def blocked_render(url: str) -> str:
        return "<html><body>Robot Check</body></html>"

    source._render = blocked_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, SourceFailure)
    assert result.source_tier == SourceTier.TIER_2


def test_fetch_returns_source_failure_for_non_amazon_url():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    result = asyncio.run(source.fetch("https://www.ebay.com/itm/123"))

    assert isinstance(result, SourceFailure)
    assert result.reason == "invalid_url"


def test_fetch_succeeds_via_stubbed_render_using_fixture_html():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))
    html = _read_fixture("amazon_product_basic.html")

    async def fake_render(url: str) -> str:
        return html

    source._render = fake_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, ProductFacts)
    assert result.source_tier == SourceTier.TIER_2
    assert result.canonical_product_id == "amazon:B08N5WRWNW"


def test_scraper_launches_through_configured_proxy(monkeypatch):
    """Settings.scraper_proxy_url, when set, reaches Playwright's launch call;
    when unset, no proxy is passed -- the value is never hardcoded (NFR-1)."""
    launched_with: dict = {}

    class _FakePage:
        async def goto(self, url, wait_until=None):
            return None

        async def wait_for_selector(self, selector, timeout=None):
            return None

        async def content(self):
            return "<html><body><span id='productTitle'>X</span></body></html>"

    class _FakeBrowser:
        async def new_page(self):
            return _FakePage()

        async def close(self):
            return None

    class _FakeChromium:
        async def launch(self, proxy=None):
            launched_with["proxy"] = proxy
            return _FakeBrowser()

    class _FakePlaywright:
        def __init__(self):
            self.chromium = _FakeChromium()

    class _FakeAsyncPlaywrightCtx:
        async def __aenter__(self):
            return _FakePlaywright()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(
        "app.pipeline.sources.scraper_tier2.async_playwright",
        lambda: _FakeAsyncPlaywrightCtx(),
    )

    with_proxy = ScraperTier2Source(settings=Settings(scraper_proxy_url="http://proxy.example.com:8080"))
    asyncio.run(with_proxy.fetch("https://www.amazon.com/dp/B08N5WRWNW"))
    assert launched_with["proxy"] == {"server": "http://proxy.example.com:8080"}

    without_proxy = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))
    asyncio.run(without_proxy.fetch("https://www.amazon.com/dp/B08N5WRWNW"))
    assert launched_with["proxy"] is None


def test_settings_accepts_a_well_formed_proxy_url():
    settings = Settings(scraper_proxy_url="http://proxy.example.com:8080")

    assert settings.scraper_proxy_url == "http://proxy.example.com:8080"


def test_settings_rejects_malformed_proxy_url_at_construction_time():
    # Fails fast here -- at Settings() construction -- rather than deep
    # inside Playwright's browser.launch() in ScraperTier2Source._render.
    with pytest.raises(pydantic.ValidationError):
        Settings(scraper_proxy_url="proxy.example.com:8080")  # missing scheme

    with pytest.raises(pydantic.ValidationError):
        Settings(scraper_proxy_url="not a url")


# -- parse_reviews() -----------------------------------------------------


def test_parse_reviews_fixture_yields_four_reviews_with_expected_fields():
    html = _read_fixture("amazon_product_reviews.html")

    reviews = parse_reviews(html)

    assert len(reviews) == 4
    assert all(isinstance(r, Review) for r in reviews)

    first = reviews[0]
    assert first.rating == 5
    assert first.title == "Great little speaker"
    assert "sound is surprisingly good" in first.body
    assert first.helpful_votes == 42
    assert first.review_date == date(2023, 1, 5)


def test_parse_reviews_includes_a_critical_review():
    html = _read_fixture("amazon_product_reviews.html")

    reviews = parse_reviews(html)

    critical = [r for r in reviews if r.rating <= 2]
    assert len(critical) == 1
    assert critical[0].title == "Stopped working after a week"


def test_parse_reviews_missing_helpful_vote_statement_defaults_to_zero():
    html = _read_fixture("amazon_product_reviews.html")

    reviews = parse_reviews(html)

    good_value_review = next(r for r in reviews if r.title == "Good value")
    assert good_value_review.helpful_votes == 0


def test_parse_reviews_unparseable_date_text_yields_none():
    html = _read_fixture("amazon_product_reviews.html")

    reviews = parse_reviews(html)

    undated_review = next(r for r in reviews if r.title == "It's okay")
    assert undated_review.review_date is None


def test_parse_reviews_skips_block_missing_rating_or_body():
    html = """
    <html><body>
      <div data-hook="review">
        <a data-hook="review-title"><span>No rating here</span></a>
        <span data-hook="review-body"><span>Body present but no star rating.</span></span>
      </div>
      <div data-hook="review">
        <i data-hook="review-star-rating"><span class="a-icon-alt">5.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>No body here</span></a>
      </div>
    </body></html>
    """

    assert parse_reviews(html) == []


def test_parse_reviews_returns_empty_list_when_no_review_blocks_present():
    assert parse_reviews("<html><body>Robot Check</body></html>") == []


# -- ScraperTier2Source.fetch_reviews() -----------------------------------


def test_fetch_reviews_returns_parsed_reviews_via_stubbed_render():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))
    html = _read_fixture("amazon_product_reviews.html")

    async def fake_render(url: str, wait_for_reviews: bool = False) -> str:
        return html

    source._render = fake_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch_reviews("https://www.amazon.com/dp/B08N5WRWNW"))

    assert isinstance(result, list)
    assert len(result) == 4
    assert all(isinstance(r, Review) for r in result)


def test_fetch_reviews_returns_empty_list_and_never_raises_when_render_fails(monkeypatch):
    monkeypatch.setattr(scraper_tier2_module.asyncio, "sleep", _no_delay_sleep)

    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    call_count = 0

    async def failing_render(url: str, wait_for_reviews: bool = False) -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("blocked by CAPTCHA")

    source._render = failing_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch_reviews("https://www.amazon.com/dp/B08N5WRWNW"))

    assert result == []
    # one initial attempt + one retry (AD-9), never an unhandled exception
    assert call_count == 2


def test_fetch_reviews_degrades_to_empty_list_when_render_times_out(monkeypatch):
    monkeypatch.setattr(scraper_tier2_module, "_FETCH_TIMEOUT_SECONDS", 0.05)

    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    async def hanging_render(url: str, wait_for_reviews: bool = False) -> str:
        await asyncio.sleep(10)
        return "<html></html>"

    source._render = hanging_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch_reviews("https://www.amazon.com/dp/B08N5WRWNW"))

    assert result == []


def test_fetch_reviews_returns_empty_list_for_non_amazon_url():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    result = asyncio.run(source.fetch_reviews("https://www.ebay.com/itm/123"))

    assert result == []


def test_fetch_reviews_returns_empty_list_when_page_has_no_reviews():
    source = ScraperTier2Source(settings=Settings(scraper_proxy_url=None))

    async def no_reviews_render(url: str, wait_for_reviews: bool = False) -> str:
        return "<html><body><span id='productTitle'>X</span></body></html>"

    source._render = no_reviews_render  # type: ignore[method-assign]

    result = asyncio.run(source.fetch_reviews("https://www.amazon.com/dp/B08N5WRWNW"))

    assert result == []
