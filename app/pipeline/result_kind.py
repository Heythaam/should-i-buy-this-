"""The `result_kind()` classification shared by `app/main.py` and `app/jobs.py`
(Story 1.9 follow-up).

Lives here -- rather than in `app.main`, where it was originally defined --
so `app/jobs.py`'s `run_job()` can import it at module scope. `app.main`
imports `app.jobs` at module scope, so a top-level `from app.main import
result_kind` inside `app/jobs.py` would be a circular import; this module
has no dependency on either, so both import it normally.
"""

from app.models.product import InsufficientDataResult
from app.models.verdict import Verdict

# This story's own UI-layer calibration (see the spec's Design Notes) --
# separate from `compute_confidence()`'s internal weights (Story 1.7).
# Neither the PRD nor the architecture names an exact cutoff for "visually
# distinguish a low-confidence result," only that one must exist
# (FR-13/NFR-8); a future story can retune this without touching
# `compute_confidence()`.
LOW_CONFIDENCE_THRESHOLD = 0.5


def result_kind(result: Verdict | InsufficientDataResult) -> str:
    """Classify `result` into the one of three styling buckets this story's
    I/O & Edge-Case Matrix requires: `"confident"`, `"low_confidence"`, or
    `"insufficient_data"`. Drives `class="result result--{{ result_kind }}"`
    in the template -- never the same class for two different kinds.
    """
    if isinstance(result, InsufficientDataResult):
        return "insufficient_data"
    # `<` vs `<=` at the exact threshold is moot in practice: an exact tie
    # is mathematically unreachable given `compute_confidence()`'s discrete
    # 0.015-increment components; `<` is used for the unambiguous case
    # (values strictly above the threshold) where the choice does matter.
    if result.confidence < LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "confident"
