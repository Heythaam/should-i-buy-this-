"""Pure comparable-alternatives selection (alternatives branch, AD-3, AD-4, AD-9).

`select_alternatives()` takes a reference `ProductFacts` and a list of
candidate `ProductFacts` -- typically the output of
`ProductSource.find_candidate_alternatives(reference.category)` -- and
returns up to 3 same-category candidates within a similar price band,
closest-price-first. No I/O, deterministic for identical input (FR-6).

This function deliberately does not re-check category: the candidates it
receives are trusted to already be category-scoped by whatever search query
`find_candidate_alternatives()` ran (see this story's Design Notes) --
re-verifying that here would be redundant double-checking of a guarantee the
caller already provides.
"""

from app.models.product import ProductFacts

# This story's own default (neither the PRD nor the architecture states an
# exact percentage, only "a similar price range" -- FR-6/FR-8). A future
# story can tune this without changing this function's shape.
_PRICE_BAND_FRACTION = 0.20
_MAX_ALTERNATIVES = 3


def select_alternatives(
    reference: ProductFacts, candidates: list[ProductFacts]
) -> list[ProductFacts]:
    """Select up to `_MAX_ALTERNATIVES` comparable alternatives to `reference`.

    Never fails: an unknown reference price, an empty candidate list, or no
    in-band candidates all legitimately resolve to `[]` (FR-6) -- this is a
    non-failing outcome, never padded and never an error. The reference
    product itself (matched by `canonical_product_id`) is always excluded,
    and a candidate with an unknown price is excluded from matching rather
    than guessed into or out of the band. Candidates are also deduplicated
    against each other by `canonical_product_id` (first occurrence wins)
    before the top 3 are taken, so a duplicate listing for the same product
    can't occupy more than one returned slot. Ties in price distance are
    broken by preserving the candidates' input order (stable sort).
    """
    if reference.price is None:
        return []

    low, high = sorted(
        (
            reference.price * (1 - _PRICE_BAND_FRACTION),
            reference.price * (1 + _PRICE_BAND_FRACTION),
        )
    )

    in_band = [
        candidate
        for candidate in candidates
        if candidate.canonical_product_id != reference.canonical_product_id
        and candidate.price is not None
        and low <= candidate.price <= high
    ]

    deduped: list[ProductFacts] = []
    seen_ids: set[str] = set()
    for candidate in in_band:
        if candidate.canonical_product_id in seen_ids:
            continue
        seen_ids.add(candidate.canonical_product_id)
        deduped.append(candidate)

    deduped.sort(key=lambda candidate: abs(candidate.price - reference.price))
    return deduped[:_MAX_ALTERNATIVES]
