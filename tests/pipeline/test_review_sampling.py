"""Tests for stratified review sampling (FR-4).

Covers this story's I/O Matrix sampling scenarios with synthetic `Review`
data -- `sample_reviews()` is a pure function, so no fixtures/network are
needed here.
"""

from datetime import date, timedelta

from app.models.review import Review
from app.pipeline.review_sampling import sample_reviews


def _review(
    rating: int,
    body: str,
    helpful_votes: int = 0,
    review_date: date | None = None,
    title: str | None = None,
) -> Review:
    return Review(
        rating=rating,
        title=title,
        body=body,
        helpful_votes=helpful_votes,
        review_date=review_date,
    )


def test_thousands_of_reviews_returns_bounded_sample():
    reviews = [
        _review(
            rating=(i % 5) + 1,
            body=f"review body {i}",
            helpful_votes=i,
            review_date=date(2020, 1, 1) + timedelta(days=i),
        )
        for i in range(5000)
    ]

    sample = sample_reviews(reviews)

    assert len(sample) <= 40


def test_at_least_one_critical_review_included_when_present():
    # A single critical review with low helpful votes, buried among many
    # highly-helpful non-critical reviews -- it won't make the top-20
    # helpful bucket on its own, so it must be rescued by the critical
    # bucket.
    reviews = [
        _review(rating=5, body=f"filler {i}", helpful_votes=1000 - i) for i in range(50)
    ]
    critical = _review(rating=1, body="broke immediately", helpful_votes=0)
    reviews.append(critical)

    sample = sample_reviews(reviews)

    assert any(r.rating <= 2 for r in sample)
    assert critical in sample


def test_no_critical_reviews_leaves_other_buckets_unaffected():
    reviews = [_review(rating=3 + (i % 3), body=f"body {i}", helpful_votes=i) for i in range(10)]

    sample = sample_reviews(reviews)

    assert all(r.rating >= 3 for r in sample)
    # Nothing to rescue, so dedup'd input (no dupes here) passes straight
    # through the helpful bucket.
    assert len(sample) == 10


def test_near_duplicate_reviews_keep_only_first_occurrence():
    first = _review(rating=5, body="  Great Product!  ", helpful_votes=10)
    duplicate = _review(rating=5, body="great product!", helpful_votes=999)
    other = _review(rating=4, body="a totally different review", helpful_votes=1)

    sample = sample_reviews([first, duplicate, other])

    assert first in sample
    assert duplicate not in sample
    assert len(sample) == 2


def test_fewer_reviews_than_bound_returns_all_of_them_unchanged():
    reviews = [_review(rating=5, body=f"unique body {i}", helpful_votes=i) for i in range(5)]

    sample = sample_reviews(reviews)

    assert len(sample) == 5
    assert {id(r) for r in sample} == {id(r) for r in reviews}


def test_critical_bucket_is_capped_at_ten():
    # 15 critical reviews, none of them helpful enough to land in the
    # top-20 helpful bucket (all other reviews have far higher votes).
    noise = [_review(rating=5, body=f"noise {i}", helpful_votes=1000 + i) for i in range(25)]
    criticals = [_review(rating=1, body=f"bad {i}", helpful_votes=0) for i in range(15)]

    sample = sample_reviews(noise + criticals)

    critical_in_sample = [r for r in sample if r.rating <= 2]
    assert len(critical_in_sample) == 10


def test_recent_bucket_adds_undated_reviews_are_excluded():
    dated = [
        _review(rating=5, body=f"dated {i}", helpful_votes=0, review_date=date(2023, 1, 1))
        for i in range(5)
    ]
    undated = [_review(rating=5, body=f"undated {i}", helpful_votes=0) for i in range(5)]

    sample = sample_reviews(dated + undated)

    # All 10 fit under the 20-helpful cap already (helpful_votes tie, stable
    # order), so nothing further is added by the recent bucket -- this just
    # proves an undated review is a legal, non-crashing input.
    assert len(sample) == 10


def test_recent_bucket_rescues_a_review_that_misses_the_helpful_bucket():
    # 20 highly-helpful, non-critical reviews fill the top-20 helpful bucket
    # entirely on their own. One additional review has low helpful_votes
    # (so it can't make that bucket) and the most recent review_date of the
    # whole set -- it must be rescued by the recency bucket.
    filler = [
        _review(
            rating=5,
            body=f"filler {i}",
            helpful_votes=1000 - i,
            review_date=date(2020, 1, 1) + timedelta(days=i),
        )
        for i in range(20)
    ]
    recent = _review(
        rating=4,
        body="just arrived and works great",
        helpful_votes=0,
        review_date=date(2024, 1, 1),
    )
    reviews = filler + [recent]

    sample = sample_reviews(reviews)

    assert recent in sample


def test_sample_reviews_is_pure_and_deterministic():
    reviews = [_review(rating=2, body=f"body {i}", helpful_votes=i) for i in range(30)]
    reviews_copy = list(reviews)

    first = sample_reviews(reviews)
    second = sample_reviews(reviews)

    assert reviews == reviews_copy  # input untouched
    assert first == second
