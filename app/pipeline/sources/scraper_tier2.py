"""Tier 2 `ProductSource`: render with Playwright, parse with BeautifulSoup.

One code path -- always render the page first, then parse the resulting DOM
-- matching the single Tier 2 file named in the architecture's structural
seed. Reads `Settings.scraper_proxy_url` (NFR-1): the proxy is loaded from an
environment variable, never hardcoded, and simply omitted when unset.

Parsing is factored into module-level, Playwright-free functions
(`parse_product_facts`, `build_proxy_config`) specifically so tests can
exercise them against saved HTML fixtures without any live network or
browser dependency, per this story's "no live-network calls in tests" rule.
"""

import asyncio
import logging
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.models.product import ProductFacts, SourceFailure, SourceTier
from app.pipeline.canonicalize import CanonicalProductId, InvalidProductURLError, canonicalize
from app.settings import Settings

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_ATTEMPTS = 2  # first attempt + one retry (AD-9)
_RETRY_DELAY_SECONDS = 1.0


class ProductPageParseError(Exception):
    """Raised internally when a rendered page can't be parsed into facts.

    Caught by `fetch`'s retry loop and never escapes it -- a second (or
    final) occurrence degrades to a `SourceFailure` (AD-4).
    """


def build_proxy_config(proxy_url: str | None) -> dict[str, str] | None:
    """Translate `Settings.scraper_proxy_url` into a Playwright proxy config.

    Returns `None` (no proxy) when unset -- the value is never hardcoded and
    never defaulted to some real proxy.
    """
    if not proxy_url:
        return None
    return {"server": proxy_url}


def _extract_title(soup: BeautifulSoup) -> str | None:
    title_el = soup.select_one("#productTitle")
    if not title_el:
        return None
    text = title_el.get_text(strip=True)
    return text or None


def _extract_price(soup: BeautifulSoup) -> float | None:
    price_el = (
        soup.select_one(".a-price .a-offscreen")
        or soup.select_one("#priceblock_ourprice")
        or soup.select_one("#priceblock_dealprice")
    )
    if not price_el:
        return None
    return _parse_price_text(price_el.get_text(strip=True))


def _parse_price_text(text: str) -> float | None:
    """Parse a price string, handling both US ("1,234.56") and EU
    ("1.234,56", e.g. amazon.de/.fr/.it/.es/.nl/.se/.pl) decimal conventions.

    Returns `None` rather than guessing when comma usage is ambiguous (e.g.
    a lone comma that's neither clearly a decimal nor a thousands separator)
    -- an honest missing value beats a silently wrong one (AD-4).
    """
    cleaned = re.sub(r"[^0-9.,]", "", text)
    if not cleaned:
        return None

    has_comma = "," in cleaned
    has_dot = "." in cleaned

    if has_comma and has_dot:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # EU style, e.g. "1.234,56" -- comma is the decimal separator.
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US style, e.g. "1,234.56" -- dot is the decimal separator.
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        groups = cleaned.split(",")
        if len(groups) == 2 and len(groups[1]) == 2:
            cleaned = cleaned.replace(",", ".")  # "39,99" -- decimal comma
        elif all(len(group) == 3 for group in groups[1:]):
            cleaned = cleaned.replace(",", "")  # "1,234" -- thousands comma
        else:
            return None  # ambiguous comma usage -- don't guess

    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in soup.select("#productDetails_techSpec_section_1 tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = cells[0].get_text(strip=True)
        value = cells[1].get_text(strip=True)
        if key:
            specs.setdefault(key, value)  # first occurrence of a label wins
    return specs


def parse_product_facts(html: str, canonical_id: CanonicalProductId) -> ProductFacts:
    """Parse rendered product-page HTML into `ProductFacts`.

    Raises:
        ProductPageParseError: the page has no recognizable `#productTitle`
            -- e.g. a blocked/CAPTCHA page or an unsupported layout.
    """
    soup = BeautifulSoup(html, "html.parser")

    title = _extract_title(soup)
    if not title:
        raise ProductPageParseError("missing or empty #productTitle")

    return ProductFacts(
        canonical_product_id=str(canonical_id),
        title=title,
        price=_extract_price(soup),
        specs=_extract_specs(soup),
        source_tier=SourceTier.TIER_2,
    )


class ScraperTier2Source:
    """Tier 2 `ProductSource`: Playwright render + BeautifulSoup parse."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else Settings()

    async def fetch(self, url: str) -> ProductFacts | SourceFailure:
        try:
            canonical_id = canonicalize(url)
        except InvalidProductURLError as exc:
            return SourceFailure(
                source_tier=SourceTier.TIER_2,
                reason="invalid_url",
                detail=str(exc),
            )

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                html = await asyncio.wait_for(
                    self._render(url), timeout=_FETCH_TIMEOUT_SECONDS
                )
                return parse_product_facts(html, canonical_id)
            except Exception as exc:  # noqa: BLE001 -- AD-4: fetch() never raises out
                last_error = exc
                logger.warning(
                    "scraper_tier2 fetch attempt %s/%s failed for %s: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    url,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    # Give a transient block/CAPTCHA a moment before retrying
                    # instead of hammering the page again immediately.
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        logger.error(
            "scraper_tier2 giving up after %s attempts for %s: %s",
            _MAX_ATTEMPTS,
            url,
            last_error,
        )
        return SourceFailure(
            source_tier=SourceTier.TIER_2,
            reason="fetch_failed",
            detail=str(last_error) if last_error else "unknown error",
        )

    async def _render(self, url: str) -> str:
        proxy = build_proxy_config(self._settings.scraper_proxy_url)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(proxy=proxy)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                # Give JS-injected price/spec data a moment to hydrate before
                # reading the DOM, rather than racing it right after the
                # bare "domcontentloaded" navigation event.
                await page.wait_for_selector("#productTitle", timeout=5000)
                return await page.content()
            finally:
                await browser.close()
