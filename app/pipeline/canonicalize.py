"""Resolve a product URL to its Canonical Product id (AD-2).

One `canonicalize(url) -> CanonicalProductId` function is the only source of
product identity in the whole pipeline. The ASIN -- not the raw URL -- is
what encodes "which exact variant": two URLs for the same ASIN that differ
only by tracking query params resolve to the identical id, and a color/size
variant (a different ASIN) resolves to a different id. Both properties fall
out of this one extraction step for free.
"""

import re
from urllib.parse import urlparse

# Amazon storefront domains this pipeline resolves against. A generic regex
# (e.g. "ends with amazon.<letters>") would wrongly accept a host like
# "amazon.evil.com" -- "evil.com" is itself just letters and dots -- so this
# matches against an explicit allowlist of registrable Amazon domains
# instead, with any subdomain (e.g. "www.", "smile.") permitted in front.
_AMAZON_DOMAINS = (
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.ca",
    "amazon.com.au",
    "amazon.co.jp",
    "amazon.in",
    "amazon.com.br",
    "amazon.com.mx",
    "amazon.nl",
    "amazon.se",
    "amazon.pl",
    "amazon.sg",
    "amazon.ae",
    "amazon.sa",
)


def _is_amazon_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in _AMAZON_DOMAINS)

# The ASIN lives in the path segment right after one of these known Amazon
# URL shapes: "/dp/", "/gp/product/" (desktop), "/gp/aw/d/" (mobile), and
# "/exec/obidos/ASIN/" (legacy). Capture the whole segment (up to the next
# "/" or the end of the path) and validate its shape separately, rather than
# baking the length into the regex -- that avoids the regex engine silently
# sliding the match window when a segment is longer than 10 characters.
_ASIN_SEGMENT = re.compile(
    r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/([^/?]+)", re.IGNORECASE
)
_ASIN_SHAPE = re.compile(r"[A-Z0-9]{10}", re.IGNORECASE)


class CanonicalProductId(str):
    """A stable, source-agnostic product identity (AD-2).

    Format: ``amazon:{ASIN}``. This is a plain string (not a URL), so two
    URLs that resolve to the same ASIN compare equal regardless of tracking
    query params, and it is usable directly as a cache/dict key (AD-8).
    """

    __slots__ = ()


class InvalidProductURLError(ValueError):
    """Raised when a URL cannot be resolved to a Canonical Product id.

    Covers non-Amazon hosts, unparseable strings, and Amazon URLs with no
    recognizable ASIN -- `canonicalize` never guesses an id in these cases.
    """


def canonicalize(url: str) -> CanonicalProductId:
    """Resolve ``url`` to its Canonical Product id.

    Raises:
        InvalidProductURLError: ``url`` is not a parseable Amazon product
            URL (non-Amazon host, malformed string, or no ASIN found).
    """
    if not url or not isinstance(url, str):
        raise InvalidProductURLError(f"Not a valid product URL: {url!r}")

    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        raise InvalidProductURLError(f"Could not parse URL: {url!r}") from exc

    if parsed.scheme not in ("http", "https"):
        raise InvalidProductURLError(f"Unsupported URL scheme: {url!r}")

    # Strip a trailing "." -- "amazon.com." is a valid FQDN (root-zone dot)
    # that must resolve the same as "amazon.com", not be rejected as unknown.
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not _is_amazon_host(host):
        raise InvalidProductURLError(f"Not an Amazon product URL: {url!r}")

    segment_match = _ASIN_SEGMENT.search(parsed.path)
    if not segment_match or not _ASIN_SHAPE.fullmatch(segment_match.group(1)):
        raise InvalidProductURLError(f"No ASIN found in Amazon URL: {url!r}")

    asin = segment_match.group(1).upper()
    return CanonicalProductId(f"amazon:{asin}")
