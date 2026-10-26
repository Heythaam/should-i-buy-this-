"""Shared, typed contract for a single parsed product review (AD-11).

`models/` is core/shared: any branch may edit it in place when its work
requires it, but it is never forked or shadowed locally. `Review` is a
separate stage output from `ProductFacts` -- not nested on it -- because
Story 1.6's Evidence Bundle assembly consumes product facts and the review
sample as two independently-degradable inputs (see Design Notes in this
story's spec).
"""

from datetime import date

from pydantic import BaseModel, Field


class Review(BaseModel):
    """One parsed product review.

    `helpful_votes` defaults to `0` and `review_date` defaults to `None`
    when the source HTML's vote count or date text can't be parsed --
    an honest missing value rather than a fabricated one (AD-4).
    """

    rating: int = Field(ge=1, le=5)
    title: str | None = None
    body: str
    helpful_votes: int = 0
    review_date: date | None = None
