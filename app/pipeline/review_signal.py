"""Review-signal assessment (scraper branch, FR-5).

`assess_review_signal()` is a pure function -- no I/O, deterministic for
identical input -- distinguishing "we have plenty of reviews" from "we
barely have any" so a thin review sample is never later folded into the
Confidence Score (Story 1.7) as if it were conclusive.

Threshold is "fewer than 10", per the PRD addendum's "Review Sampling
Strategy" section (the Architecture Spine defers this threshold as an
implementation detail and never states a number): `review_count == 10`
is NOT low signal. An unknown (`None`) `review_count`
is also low signal, but with a reason distinct from the below-threshold
case -- absence of evidence of sufficient volume is not evidence of
sufficiency (AD-4's honesty principle applied to this signal).
"""

from app.models.review_signal import ReviewSignalAssessment

_LOW_REVIEW_THRESHOLD = 10


def assess_review_signal(review_count: int | None) -> ReviewSignalAssessment:
    """Assess whether `review_count` represents enough review signal."""
    if review_count is None:
        return ReviewSignalAssessment(
            is_low_signal=True,
            reason="Review count is unknown, so review signal cannot be confirmed as sufficient.",
        )

    if review_count < _LOW_REVIEW_THRESHOLD:
        return ReviewSignalAssessment(
            is_low_signal=True,
            reason=f"Only {review_count} review(s) found, below the low-signal threshold of {_LOW_REVIEW_THRESHOLD}.",
        )

    return ReviewSignalAssessment(is_low_signal=False, reason=None)
