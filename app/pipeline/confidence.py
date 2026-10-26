"""Confidence Score computation (confidence-score branch, AD-6).

`compute_confidence()` is a pure function -- no I/O, deterministic for
identical input, bounded to `[0.0, 1.0]`. It is the only thing that ever
writes `Verdict.confidence`; `pipeline/synthesis.py` calls this after
receiving the LLM's draft and overwrites whatever confidence value the LLM
produced (AD-6) -- that value is read and discarded, never surfaced.

The exact formula (source-tier weight + review-signal weight + sample-depth
weight, saturating at 20 reviews) is this story's own calibration -- the
architecture names the INPUTS (review volume, Source Tier) but not an exact
formula (see this story's Design Notes). A future story can retune the
weights below without changing this function's shape. The three weights sum
to `1.0` exactly, so the best possible case (Tier 2, sufficient review
signal, >= 20 sampled reviews) saturates at `1.0`, and every component is
individually non-negative and capped, so the sum is always within
`[0.0, 1.0]` without needing a defensive clamp -- one is still applied below
as a belt-and-suspenders guarantee against a future miscalibration.
"""

from app.models.evidence import EvidenceBundle
from app.models.product import SourceTier

_SOURCE_TIER_WEIGHT: dict[SourceTier, float] = {
    SourceTier.TIER_2: 0.4,
    SourceTier.TIER_3: 0.1,
}
_REVIEW_SIGNAL_WEIGHT = 0.3
_SAMPLE_DEPTH_WEIGHT = 0.3
_SAMPLE_DEPTH_SATURATION = 20


def compute_confidence(bundle: EvidenceBundle) -> float:
    """Compute a deterministic Confidence Score for `bundle`.

    Three additive components:
    - Source-tier weight: which `ProductSource` tier supplied the product
      facts (Tier 2 is more reliable than the degraded Tier 3 fallback).
    - Review-signal weight: full weight when `review_signal.is_low_signal`
      is `False`, zero otherwise (Story 1.4's low-signal flag feeds directly
      in here, rather than being a separate UI-only warning).
    - Sample-depth weight: scales linearly with the number of sampled
      reviews actually present in the bundle, saturating at
      `_SAMPLE_DEPTH_SATURATION` reviews -- more sampled evidence raises
      confidence up to a point, beyond which additional reviews don't add
      more certainty.
    """
    source_tier_component = _SOURCE_TIER_WEIGHT.get(bundle.product_facts.source_tier, 0.0)

    review_signal_component = 0.0 if bundle.review_signal.is_low_signal else _REVIEW_SIGNAL_WEIGHT

    depth_ratio = min(len(bundle.reviews), _SAMPLE_DEPTH_SATURATION) / _SAMPLE_DEPTH_SATURATION
    sample_depth_component = depth_ratio * _SAMPLE_DEPTH_WEIGHT

    confidence = source_tier_component + review_signal_component + sample_depth_component
    return max(0.0, min(1.0, confidence))
