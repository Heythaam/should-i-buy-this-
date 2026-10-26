"""Stratified review sampling (scraper branch, FR-4).

`sample_reviews()` is a pure function -- no I/O, deterministic for
identical input -- so a thousands-of-reviews product never blows up
LLM cost/time once synthesis exists, while a thin sample still can't be
mistaken for a settled answer (near-duplicates removed, at least one
critical review kept when one exists).

Stratified selection order (see this story's spec Design Notes):
1. Dedup the full input on exact, normalized body text (first occurrence
   wins).
2. Take the top 20 by `helpful_votes` descending.
3. Add up to 10 not-already-included reviews with `rating <= 2`, sorted by
   rating ascending then `helpful_votes` descending.
4. Add up to 10 not-already-included reviews with a non-`None`
   `review_date`, sorted descending (most recent first).

A review already included via an earlier bucket is never duplicated into a
later one, so the 40-cap holds even when buckets overlap.
"""

from app.models.review import Review

_HELPFUL_BUCKET_SIZE = 20
_CRITICAL_BUCKET_SIZE = 10
_RECENT_BUCKET_SIZE = 10
_CRITICAL_RATING_CEILING = 2


def _normalize(body: str) -> str:
    return " ".join(body.lower().split())


def _deduplicate(reviews: list[Review]) -> list[Review]:
    """Drop near-duplicates (identical normalized body text AND rating);
    first wins. Rating is part of the key so that two reviews sharing body
    text but differing in rating -- e.g. a critical review that happens to
    quote the same text as a non-critical one -- are never collapsed into
    a single entry, which would risk silently discarding the critical one
    before the critical-rescue bucket ever sees it."""
    seen: set[tuple[str, int]] = set()
    deduped: list[Review] = []
    for review in reviews:
        key = (_normalize(review.body), review.rating)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(review)
    return deduped


def sample_reviews(reviews: list[Review]) -> list[Review]:
    """Reduce `reviews` to a bounded (<=40), stratified, representative sample."""
    deduped = _deduplicate(reviews)

    sample: list[Review] = sorted(deduped, key=lambda r: r.helpful_votes, reverse=True)[
        :_HELPFUL_BUCKET_SIZE
    ]
    included_ids = {id(review) for review in sample}

    critical_candidates = [
        review
        for review in deduped
        if review.rating <= _CRITICAL_RATING_CEILING and id(review) not in included_ids
    ]
    critical_candidates.sort(key=lambda r: (r.rating, -r.helpful_votes))
    critical_picks = critical_candidates[:_CRITICAL_BUCKET_SIZE]
    sample.extend(critical_picks)
    included_ids.update(id(review) for review in critical_picks)

    recent_candidates = [
        review
        for review in deduped
        if review.review_date is not None and id(review) not in included_ids
    ]
    recent_candidates.sort(key=lambda r: r.review_date, reverse=True)
    recent_picks = recent_candidates[:_RECENT_BUCKET_SIZE]
    sample.extend(recent_picks)

    return sample
