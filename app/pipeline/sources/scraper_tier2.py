"""Tier 2 `ProductSource`: render with Playwright, parse with BeautifulSoup.

One code path -- always render the page first, then parse the resulting DOM
-- matching the single Tier 2 file named in the architecture's structural
seed. Reads `Settings.scraper_proxy_url` (NFR-1): the proxy is loaded from an
environment variable, never hardcoded, and simply omitted when unset.

Parsing is factored into module-level, Playwright-free functions
(`parse_product_facts`, `parse_reviews`, `build_proxy_config`) specifically
so tests can exercise them against saved HTML fixtures without any live
network or browser dependency, per this story's "no live-network calls in
tests" rule.
"""

import asyncio
import logging
import re
from datetime import date, datetime
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.models.product import ProductFacts, SourceFailure, SourceTier
from app.models.review import Review
from app.pipeline.canonicalize import CanonicalProductId, InvalidProductURLError, canonicalize
from app.settings import Settings

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_ATTEMPTS = 2  # first attempt + one retry (AD-9)
_RETRY_DELAY_SECONDS = 1.0

# Domain the search-based alternatives lookup runs against. Matches the one
# `canonicalize()` and the fixture product pages already target -- v1 is
# Amazon-only, so a single locale's search endpoint is sufficient (see the
# architecture's "Non-Amazon retailers" deferral).
_SEARCH_BASE_URL = "https://www.amazon.com"
_SEARCH_RESULT_SELECTOR = '[data-component-type="s-search-result"]'


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


_REVIEW_COUNT_PATTERN = re.compile(r"([\d,.]+)\s*ratings?", re.IGNORECASE)


def _extract_review_count(soup: BeautifulSoup) -> int | None:
    """Parse the page's aggregate ratings-count text (e.g. "1,234 ratings"),
    shown near the title via `#acrCustomerReviewText` on a standard product
    page.

    Anchored to the "rating(s)" phrase (mirroring `_RATING_PATTERN`'s anchor
    to "out of 5 stars" below) so it never matches an unrelated digit run in
    the element's text. Both `,` and `.` are stripped before parsing --
    review counts have no fractional use case, so a dot-grouped EU-style
    count (e.g. "1.234 ratings") is treated the same as "1,234 ratings"
    rather than misread as a decimal.

    Returns `None` -- rather than guessing -- when the element is missing or
    its text doesn't contain a recognizable count (AD-4): this is Story 1.4's
    "unknown signal" case, distinct from a genuinely low count.
    """
    count_el = soup.select_one("#acrCustomerReviewText")
    if not count_el:
        return None
    match = _REVIEW_COUNT_PATTERN.search(count_el.get_text(strip=True))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", "").replace(".", ""))
    except ValueError:
        return None


def _extract_category(soup: BeautifulSoup) -> str | None:
    """Parse the page's breadcrumb trail and return its most specific entry.

    The breadcrumb's last `<a>` (e.g. "Smart Speakers", not the top-level
    "Electronics") is what should drive the alternatives search query --
    see this story's Design Notes. Returns `None` -- rather than guessing --
    when the breadcrumb is absent.
    """
    breadcrumb_links = soup.select("#wayfinding-breadcrumbs_feedback li a")
    if not breadcrumb_links:
        return None
    text = breadcrumb_links[-1].get_text(strip=True)
    return text or None


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
        review_count=_extract_review_count(soup),
        category=_extract_category(soup),
    )


_RATING_PATTERN = re.compile(r"([\d.]+)\s*out of\s*5\s*stars", re.IGNORECASE)
_HELPFUL_VOTES_PATTERN = re.compile(r"(\d+)\s*(?:person|people)", re.IGNORECASE)
_REVIEW_DATE_FORMAT = "%B %d, %Y"


def _extract_review_rating(review_el) -> int | None:
    rating_el = review_el.select_one('[data-hook="review-star-rating"] .a-icon-alt')
    if not rating_el:
        return None
    match = _RATING_PATTERN.search(rating_el.get_text(strip=True))
    if not match:
        return None
    try:
        return round(float(match.group(1)))
    except ValueError:
        return None


def _extract_review_title(review_el) -> str | None:
    title_el = review_el.select_one('[data-hook="review-title"]')
    if not title_el:
        return None
    text = title_el.get_text(strip=True)
    return text or None


def _extract_review_body(review_el) -> str | None:
    body_el = review_el.select_one('[data-hook="review-body"]')
    if not body_el:
        return None
    text = body_el.get_text(strip=True)
    return text or None


def _extract_review_helpful_votes(review_el) -> int:
    """Defaults to `0` when the vote-count text is missing or unparseable."""
    votes_el = review_el.select_one('[data-hook="helpful-vote-statement"]')
    if not votes_el:
        return 0
    text = votes_el.get_text(strip=True)
    if re.search(r"\bone\s+person\b", text, re.IGNORECASE):
        return 1
    match = _HELPFUL_VOTES_PATTERN.search(text.replace(",", ""))
    if not match:
        return 0
    return int(match.group(1))


def _extract_review_date(review_el) -> date | None:
    """`None` when the date text is missing or doesn't match the expected
    "... on <Month> <Day>, <Year>" format -- excluded from the recent
    bucket rather than guessed (AD-4)."""
    date_el = review_el.select_one('[data-hook="review-date"]')
    if not date_el:
        return None
    text = date_el.get_text(strip=True)
    _, _, date_text = text.rpartition(" on ")
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, _REVIEW_DATE_FORMAT).date()
    except ValueError:
        return None


def parse_reviews(html: str) -> list[Review]:
    """Parse rendered review-section HTML into a list of `Review`.

    Playwright-free, mirrors `parse_product_facts`. Never raises: a review
    block missing a parseable rating or body is skipped rather than
    fabricating a value (AD-4) -- the page's other reviews are still
    returned.
    """
    soup = BeautifulSoup(html, "html.parser")

    reviews: list[Review] = []
    for review_el in soup.select('[data-hook="review"]'):
        rating = _extract_review_rating(review_el)
        body = _extract_review_body(review_el)
        if rating is None or not body:
            logger.debug(
                "scraper_tier2 parse_reviews skipped a review block "
                "(rating=%r, body missing=%s)",
                rating,
                not body,
            )
            continue
        reviews.append(
            Review(
                rating=rating,
                title=_extract_review_title(review_el),
                body=body,
                helpful_votes=_extract_review_helpful_votes(review_el),
                review_date=_extract_review_date(review_el),
            )
        )
    return reviews


def build_search_url(category: str) -> str:
    """Build an Amazon search-results URL for `category`.

    Pure, mirrors `build_proxy_config`: a plain string transform, no I/O.
    """
    return f"{_SEARCH_BASE_URL}/s?k={quote_plus(category)}"


def _extract_search_result_title(card) -> str | None:
    title_el = card.select_one("h2 a span") or card.select_one("h2 span")
    if not title_el:
        return None
    text = title_el.get_text(strip=True)
    return text or None


def _extract_search_result_price(card) -> float | None:
    price_el = card.select_one(".a-price .a-offscreen")
    if not price_el:
        return None
    return _parse_price_text(price_el.get_text(strip=True))


def _extract_search_result_link(card) -> str | None:
    """Try each selector in turn, falling through when a match lacks a
    usable `href` rather than stopping at the first element found."""
    for selector in ("h2 a", "a.a-link-normal"):
        link_el = card.select_one(selector)
        href = link_el.get("href") if link_el else None
        if href:
            return href
    return None


def parse_search_results(html: str, category: str) -> list[ProductFacts]:
    """Parse a rendered Amazon search-results page into candidate `ProductFacts`.

    Playwright-free, mirrors `parse_product_facts`. Never raises: a
    `[data-component-type="s-search-result"]` card missing a parseable
    title, price, or canonicalizable link is skipped -- other cards on the
    same page are still parsed (AD-4). Each result's relative product link
    is resolved to an absolute URL against the search domain before being
    passed through `canonicalize()`, which requires one.
    """
    soup = BeautifulSoup(html, "html.parser")

    results: list[ProductFacts] = []
    for card in soup.select(_SEARCH_RESULT_SELECTOR):
        title = _extract_search_result_title(card)
        price = _extract_search_result_price(card)
        href = _extract_search_result_link(card)
        if not title or price is None or not href:
            logger.debug(
                "scraper_tier2 parse_search_results skipped a card "
                "(title=%r, price=%r, href=%r)",
                title,
                price,
                href,
            )
            continue

        absolute_url = urljoin(_SEARCH_BASE_URL, href)
        try:
            canonical_id = canonicalize(absolute_url)
        except InvalidProductURLError:
            logger.debug(
                "scraper_tier2 parse_search_results skipped a card with an "
                "uncanonicalizable link: %r",
                href,
            )
            continue

        results.append(
            ProductFacts(
                canonical_product_id=str(canonical_id),
                title=title,
                price=price,
                source_tier=SourceTier.TIER_2,
                category=category,
            )
        )
    return results


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

    async def fetch_reviews(self, url: str) -> list[Review]:
        """Fetch and parse `url`'s review section.

        Reuses `fetch()`'s render/retry/timeout budget, but renders the
        page independently of `fetch()` rather than sharing one render (a
        real double page-load cost for v1 -- see this story's Design
        Notes). Unlike `fetch()`, exhausting retries degrades to `[]`
        rather than a `SourceFailure`: absence of reviews is an honest
        degraded value here, not a page-level failure (AD-4, AD-9).
        """
        try:
            canonicalize(url)
        except InvalidProductURLError as exc:
            logger.warning("scraper_tier2 fetch_reviews invalid_url for %s: %s", url, exc)
            return []

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                html = await asyncio.wait_for(
                    self._render(url, wait_for_reviews=True), timeout=_FETCH_TIMEOUT_SECONDS
                )
                return parse_reviews(html)
            except Exception as exc:  # noqa: BLE001 -- AD-4: never raises out
                last_error = exc
                logger.warning(
                    "scraper_tier2 fetch_reviews attempt %s/%s failed for %s: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    url,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        logger.error(
            "scraper_tier2 fetch_reviews giving up after %s attempts for %s: %s",
            _MAX_ATTEMPTS,
            url,
            last_error,
        )
        return []

    async def find_candidate_alternatives(self, category: str) -> list[ProductFacts]:
        """Search Amazon for `category` and parse candidate `ProductFacts`.

        Reuses the render/retry/timeout pattern shared with `fetch()` and
        `fetch_reviews()`. Never raises (AD-4, AD-9): exhausting retries
        degrades to `[]`, the same honest-failure principle as
        `fetch_reviews()` -- a search page is never a `SourceFailure`-level
        concern the way a single product page is.
        """
        if not category:
            return []

        url = build_search_url(category)

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                html = await asyncio.wait_for(
                    self._render(url, wait_selector=_SEARCH_RESULT_SELECTOR),
                    timeout=_FETCH_TIMEOUT_SECONDS,
                )
                results = parse_search_results(html, category)
                logger.info(
                    "scraper_tier2 find_candidate_alternatives succeeded for "
                    "category %r: %s result(s)",
                    category,
                    len(results),
                )
                return results
            except Exception as exc:  # noqa: BLE001 -- AD-4/AD-9: never raises out
                last_error = exc
                logger.warning(
                    "scraper_tier2 find_candidate_alternatives attempt %s/%s "
                    "failed for category %r: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    category,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        logger.error(
            "scraper_tier2 find_candidate_alternatives giving up after %s "
            "attempts for category %r: %s",
            _MAX_ATTEMPTS,
            category,
            last_error,
        )
        return []

    async def _render(
        self,
        url: str,
        wait_for_reviews: bool = False,
        wait_selector: str = "#productTitle",
    ) -> str:
        proxy = build_proxy_config(self._settings.scraper_proxy_url)
        async with async_playwright() as playwright:
            executable_path = self._settings.playwright_executable_path or None
            browser = await playwright.chromium.launch(proxy=proxy, executable_path=executable_path)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                # Give JS-injected price/spec data a moment to hydrate before
                # reading the DOM, rather than racing it right after the
                # bare "domcontentloaded" navigation event. `wait_selector`
                # lets callers targeting a different page shape (e.g. a
                # search-results page) wait on their own landmark element.
                await page.wait_for_selector(wait_selector, timeout=5000)
                if wait_for_reviews:
                    # The review widget can hydrate later than the rest of
                    # the page. Give it a short, best-effort grace period --
                    # but a product can legitimately have zero reviews, so
                    # a timeout here must never fail the fetch.
                    try:
                        await page.wait_for_selector(
                            '[data-hook="review"]', timeout=2000
                        )
                    except Exception as exc:  # noqa: BLE001 -- best-effort only
                        logger.debug("no review section hydrated for %s: %s", url, exc)
                return await page.content()
            finally:
                await browser.close()
