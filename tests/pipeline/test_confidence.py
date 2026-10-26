"""Tests for `compute_confidence()` (AD-6).

Covers boundedness and determinism -- the two properties this story's spec
requires of the function's shape, without pinning the exact calibration
(explicitly deferred to future tuning in the Design Notes).
"""

from app.models.evidence import EvidenceBundle
from app.models.product import ProductFacts, SourceTier
from app.models.review import Review
from app.models.review_signal import ReviewSignalAssessment
from app.pipeline.confidence import compute_confidence


def _facts(source_tier: SourceTier = SourceTier.TIER_2) -> ProductFacts:
    return ProductFacts(
        canonical_product_id="amazon:B08N5WRWNW",
        title="Echo Dot",
        price=39.99,
        source_tier=source_tier,
        review_count=25,
    )


def _review(rating: int = 5) -> Review:
    return Review(rating=rating, body="Great product.")


def _bundle(
    source_tier: SourceTier = SourceTier.TIER_2,
    is_low_signal: bool = False,
    review_count: int = 20,
) -> EvidenceBundle:
    reason = "low signal" if is_low_signal else None
    return EvidenceBundle(
        product_facts=_facts(source_tier=source_tier),
        reviews=[_review() for _ in range(review_count)],
        review_signal=ReviewSignalAssessment(is_low_signal=is_low_signal, reason=reason),
        alternatives=[],
    )


def test_best_case_saturates_at_one():
    bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=20)

    assert compute_confidence(bundle) == 1.0


def test_more_than_saturation_reviews_does_not_exceed_one():
    bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=50)

    assert compute_confidence(bundle) == 1.0


def test_worst_case_is_bounded_at_or_above_zero():
    bundle = _bundle(source_tier=SourceTier.TIER_3, is_low_signal=True, review_count=0)

    confidence = compute_confidence(bundle)

    assert 0.0 <= confidence <= 1.0


def test_every_confidence_value_is_within_bounds():
    for source_tier in (SourceTier.TIER_2, SourceTier.TIER_3):
        for is_low_signal in (True, False):
            for review_count in (0, 1, 10, 20, 40):
                bundle = _bundle(
                    source_tier=source_tier,
                    is_low_signal=is_low_signal,
                    review_count=review_count,
                )
                confidence = compute_confidence(bundle)
                assert 0.0 <= confidence <= 1.0


def test_deterministic_for_identical_input():
    bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=15)

    first = compute_confidence(bundle)
    second = compute_confidence(bundle)

    assert first == second


def test_tier_2_scores_higher_than_tier_3_all_else_equal():
    tier_2_bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=15)
    tier_3_bundle = _bundle(source_tier=SourceTier.TIER_3, is_low_signal=False, review_count=15)

    assert compute_confidence(tier_2_bundle) > compute_confidence(tier_3_bundle)


def test_low_signal_scores_lower_than_sufficient_signal_all_else_equal():
    low_signal_bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=True, review_count=15)
    sufficient_bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=15)

    assert compute_confidence(low_signal_bundle) < compute_confidence(sufficient_bundle)


def test_more_sampled_reviews_scores_higher_up_to_saturation():
    fewer_reviews_bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=2)
    more_reviews_bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=10)

    assert compute_confidence(more_reviews_bundle) > compute_confidence(fewer_reviews_bundle)


def test_zero_sampled_reviews_does_not_raise_and_is_bounded():
    bundle = _bundle(source_tier=SourceTier.TIER_2, is_low_signal=False, review_count=0)

    confidence = compute_confidence(bundle)

    assert 0.0 <= confidence <= 1.0
