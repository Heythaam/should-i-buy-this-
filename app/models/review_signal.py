"""Shared, typed result of the review-signal assessment (AD-11).

`models/` is core/shared: any branch may edit it in place when its work
requires it, but it is never forked or shadowed locally. `ReviewSignalAssessment`
is kept as its own small model -- mirroring `Review`'s own file from Story
1.3 -- rather than added as fields on `ProductFacts`, since it is a derived
judgment about the data, not a fact extracted from the page. Story 1.7's
Confidence Score computation is the eventual consumer; this story only
produces the input signal.
"""

from pydantic import BaseModel, model_validator


class ReviewSignalAssessment(BaseModel):
    """Whether a product's review volume is thin enough to flag (FR-5).

    `reason` is `None` only when `is_low_signal` is `False` -- a human-
    readable explanation accompanies every low-signal result, naming either
    the below-threshold count or the unavailability of a count, so the two
    cases are never conflated downstream (AD-4).
    """

    is_low_signal: bool
    reason: str | None = None

    @model_validator(mode="after")
    def _reason_only_when_low_signal(self) -> "ReviewSignalAssessment":
        if not self.is_low_signal and self.reason is not None:
            raise ValueError("reason must be None when is_low_signal is False")
        if self.is_low_signal and self.reason is None:
            raise ValueError("reason is required when is_low_signal is True")
        return self
