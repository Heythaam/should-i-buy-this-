"""The `ProductSource` port (AD-3).

Product-fact retrieval goes through this one interface -- one implementation
per Source Tier. Any stage needing product-page data (including a later
`alternatives` stage) calls `fetch`; none calls Playwright/BeautifulSoup or
writes its own HTTP fetch directly.
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
