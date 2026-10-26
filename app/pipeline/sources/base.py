"""The `ProductSource` port (AD-3).

Product-fact retrieval goes through this one interface -- one implementation
per Source Tier. Any stage needing product-page data (including the
`alternatives` stage) calls `fetch`/`find_candidate_alternatives`; none
calls Playwright/BeautifulSoup or writes its own HTTP fetch directly.
"""

from typing import Protocol

from app.models.product import ProductFacts, SourceFailure
from app.models.review import Review


class ProductSource(Protocol):
    """A source of `ProductFacts` (and reviews) for a given product URL."""

    async def fetch(self, url: str) -> ProductFacts | SourceFailure:
        """Fetch product facts for `url`.

        Never raises (AD-4): any failure -- network error, timeout, a
        blocked/CAPTCHA page, unparseable DOM -- degrades to a `SourceFailure`
        instead of propagating an exception or returning a partial
        `ProductFacts`.
        """
        ...

    async def fetch_reviews(self, url: str) -> list[Review]:
        """Fetch the review sample input for `url`.

        Never raises (AD-4, AD-9): any failure -- network error, timeout, a
        blocked/CAPTCHA page, unparseable DOM -- degrades to an empty list
        instead of propagating an exception. Unlike `fetch`, there is no
        failure sentinel here: an unreadable review section is an honest
        empty review set, not a page-level failure.
        """
        ...

    async def find_candidate_alternatives(self, category: str) -> list[ProductFacts]:
        """Search for same-category candidate products for `category`.

        Never raises (AD-4, AD-9): any failure -- an unreachable or blocked
        search page, a parse failure, a timeout after retries -- degrades to
        an empty list, the same honest-failure principle as `fetch_reviews`.
        Candidates returned here are not yet price-band-matched or
        self-excluded against a reference product; that pure selection step
        is `pipeline/alternatives.py::select_alternatives`.
        """
        ...
