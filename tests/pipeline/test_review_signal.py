"""Tests for review-signal assessment (FR-5).

Covers this story's I/O Matrix scenarios. `assess_review_signal()` is a pure
function, so no fixtures/network are needed here.
"""

from app.models.review_signal import ReviewSignalAssessment
from app.pipeline.review_signal import assess_review_signal


def test_review_count_at_threshold_is_not_low_signal():
    result = assess_review_signal(10)

    assert isinstance(result, ReviewSignalAssessment)
    assert result.is_low_signal is False
    assert result.reason is None


def test_review_count_above_threshold_is_not_low_signal():
    result = assess_review_signal(1234)

    assert result.is_low_signal is False
    assert result.reason is None


def test_review_count_just_below_threshold_is_low_signal_and_names_count():
    result = assess_review_signal(9)

    assert result.is_low_signal is True
    assert result.reason is not None
    assert "9" in result.reason


def test_review_count_zero_is_low_signal_and_names_count():
    result = assess_review_signal(0)

    assert result.is_low_signal is True
    assert "0" in result.reason


def test_review_count_none_is_low_signal_with_distinct_reason():
    below_threshold = assess_review_signal(9)
    unknown = assess_review_signal(None)

    assert unknown.is_low_signal is True
    assert unknown.reason is not None
    # The unknown-count reason must be distinct text from the
    # below-threshold reason -- absence of evidence of sufficient volume
    # is not evidence of sufficiency (AD-4).
    assert unknown.reason != below_threshold.reason
    assert "9" not in unknown.reason
