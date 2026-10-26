"""Tests for `select_alternatives()` (alternatives branch, FR-6).

A pure function -- no I/O, no mocking needed. Each test maps to a row in the
story's I/O & Edge-Case Matrix, exercised with synthetic `ProductFacts`.
"""

from app.models.product import ProductFacts, SourceTier
from app.pipeline.alternatives import select_alternatives


def _facts(
    canonical_product_id: str,
    price: float | None,
    title: str = "Some Product",
    category: str | None = None,
) -> ProductFacts:
    return ProductFacts(
        canonical_product_id=canonical_product_id,
        title=title,
        price=price,
        source_tier=SourceTier.TIER_2,
        category=category,
    )


REFERENCE = _facts("amazon:REF0000001", 100.0, title="Reference Widget")


def test_returns_three_closest_in_band_candidates_when_more_exist():
    candidates = [
        _facts("amazon:ALT0000001", 90.0),  # distance 10
        _facts("amazon:ALT0000002", 95.0),  # distance 5
        _facts("amazon:ALT0000003", 110.0),  # distance 10
        _facts("amazon:ALT0000004", 105.0),  # distance 5
        _facts("amazon:ALT0000005", 119.0),  # distance 19 -- in band but farthest
    ]

    result = select_alternatives(REFERENCE, candidates)

    assert len(result) == 3
    assert [c.canonical_product_id for c in result] == [
        "amazon:ALT0000002",
        "amazon:ALT0000004",
        "amazon:ALT0000001",
    ]


def test_returns_fewer_than_three_without_padding():
    candidates = [
        _facts("amazon:ALT0000001", 95.0),
        _facts("amazon:ALT0000002", 105.0),
    ]

    result = select_alternatives(REFERENCE, candidates)

    assert len(result) == 2
    assert {c.canonical_product_id for c in result} == {
        "amazon:ALT0000001",
        "amazon:ALT0000002",
    }


def test_returns_a_single_candidate_when_only_one_is_in_band():
    candidates = [_facts("amazon:ALT0000001", 95.0)]

    result = select_alternatives(REFERENCE, candidates)

    assert len(result) == 1
    assert result[0].canonical_product_id == "amazon:ALT0000001"


def test_returns_empty_list_when_all_candidates_outside_price_band():
    candidates = [
        _facts("amazon:ALT0000001", 500.0),
        _facts("amazon:ALT0000002", 10.0),
    ]

    assert select_alternatives(REFERENCE, candidates) == []


def test_returns_empty_list_when_no_candidates_at_all():
    assert select_alternatives(REFERENCE, []) == []


def test_deduplicates_candidates_sharing_a_canonical_product_id():
    # A duplicate listing (e.g. a sponsored slot plus the organic listing
    # for the same ASIN) must only occupy one of the returned slots.
    candidates = [
        _facts("amazon:ALT0000001", 95.0, title="Sponsored Duplicate"),
        _facts("amazon:ALT0000001", 95.0, title="Organic Listing"),
        _facts("amazon:ALT0000002", 105.0),
        _facts("amazon:ALT0000003", 110.0),
    ]

    result = select_alternatives(REFERENCE, candidates)

    ids = [c.canonical_product_id for c in result]
    assert ids == ["amazon:ALT0000001", "amazon:ALT0000002", "amazon:ALT0000003"]
    # first occurrence wins
    assert result[0].title == "Sponsored Duplicate"


def test_price_band_handles_negative_reference_price():
    # A negative reference price must not invert the band into an empty
    # range -- sorted()/min()/max() keep low <= high regardless of sign.
    reference = _facts("amazon:REF0000004", -100.0, title="Negative Price Ref")
    candidates = [
        _facts("amazon:ALT0000001", -95.0),
        _facts("amazon:ALT0000002", -500.0),
    ]

    result = select_alternatives(reference, candidates)

    assert len(result) == 1
    assert result[0].canonical_product_id == "amazon:ALT0000001"


def test_excludes_candidate_sharing_reference_canonical_product_id():
    candidates = [
        _facts(REFERENCE.canonical_product_id, 100.0),
        _facts("amazon:ALT0000001", 95.0),
    ]

    result = select_alternatives(REFERENCE, candidates)

    assert len(result) == 1
    assert result[0].canonical_product_id == "amazon:ALT0000001"


def test_excludes_candidate_with_unknown_price():
    candidates = [
        _facts("amazon:ALT0000001", None),
        _facts("amazon:ALT0000002", 95.0),
    ]

    result = select_alternatives(REFERENCE, candidates)

    assert len(result) == 1
    assert result[0].canonical_product_id == "amazon:ALT0000002"


def test_returns_empty_list_when_reference_price_is_unknown():
    unknown_price_reference = _facts("amazon:REF0000002", None)
    candidates = [_facts("amazon:ALT0000001", 50.0)]

    assert select_alternatives(unknown_price_reference, candidates) == []


def test_does_not_re_check_category_mixed_categories_all_pass_through():
    # select_alternatives() is documented not to re-check category -- a
    # candidate from a different category still passes through as long as
    # it's in the price band; filtering is by price alone.
    reference = _facts(
        "amazon:REF0000003", 100.0, title="Reference Widget", category="Widgets"
    )
    candidates = [
        _facts("amazon:ALT0000001", 95.0, category="Widgets"),  # matching category
        _facts("amazon:ALT0000002", 105.0, category="Gadgets"),  # different category
        _facts("amazon:ALT0000003", 110.0, category=None),  # unknown category
        _facts("amazon:ALT0000004", 500.0, category="Widgets"),  # out of band, excluded
    ]

    result = select_alternatives(reference, candidates)

    assert {c.canonical_product_id for c in result} == {
        "amazon:ALT0000001",
        "amazon:ALT0000002",
        "amazon:ALT0000003",
    }


def test_price_band_boundaries_are_inclusive():
    # +-20% of 100.0 -> [80.0, 120.0]
    candidates = [
        _facts("amazon:ALT0000001", 80.0),
        _facts("amazon:ALT0000002", 120.0),
        _facts("amazon:ALT0000003", 79.99),
        _facts("amazon:ALT0000004", 120.01),
    ]

    result = select_alternatives(REFERENCE, candidates)

    ids = {c.canonical_product_id for c in result}
    assert ids == {"amazon:ALT0000001", "amazon:ALT0000002"}
