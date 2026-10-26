---
title: 'Warn when there is not enough review signal'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'd88bbc75a2f123a6bf05e11ae2c858b605faf797'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing yet distinguishes "we have plenty of reviews" from "we barely have any" — without that signal, a thin review sample could later be folded into the Confidence Score as if it were conclusive, exactly what FR-5 forbids.

**Approach:** Extract the product page's aggregate ratings count (e.g. "1,234 ratings", already visible near the title, same render as `fetch()`) into a new `ProductFacts.review_count` field, and add a pure `assess_review_signal(review_count) -> ReviewSignalAssessment` function (threshold: fewer than 10 is low signal, per the architecture's stated number) that Story 1.7's Confidence Score computation will later consume. No Confidence Score math here — only the honest signal it will fold in.

## Boundaries & Constraints

**Always:**
- `assess_review_signal()` is a pure function — no I/O, deterministic for identical input.
- `review_count < 10` is low signal; `review_count == 10` is not (the architecture's threshold is "fewer than 10", not "10 or fewer").
- An unparseable/unknown `review_count` (`None`) is also treated as low signal, with a reason distinct from the below-threshold case — absence of evidence of sufficient volume is not evidence of sufficiency (AD-4's honesty principle applied to this signal).
- `review_count` extraction reuses the existing `fetch()` render (Story 1.1) — no new page load, no change to `fetch_reviews()` or `sample_reviews()`.
- Reuses Story 1.1/1.3's `ProductFacts`, `Review`, `canonicalize()`, `ScraperTier2Source.fetch()` exactly as-is beyond the one new field/extraction.

**Never:**
- No Confidence Score computation in this story — that is Story 1.7 (confidence-score branch); this story only produces the input signal Story 1.7 will fold in.
- No orchestrator/pipeline wiring connecting this to Evidence Bundle/Verdict — that is Story 1.6/1.7's job.
- No FastAPI app, routes, or LLM synthesis in this story.
- `review_count` (the page's aggregate ratings count) is not reconciled or cross-checked against `len()` of `fetch_reviews()`'s result in this story — they are two separate, independently-sourced numbers.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Review count at the threshold | `review_count = 10` | `is_low_signal = False`, `reason = None` | N/A |
| Review count below the threshold | `review_count = 9` (or `0`) | `is_low_signal = True`, `reason` names the count | N/A |
| Review count unknown | `review_count = None` | `is_low_signal = True`, `reason` names the unavailability (distinct text from the below-threshold case) | N/A |
| Aggregate ratings-count element present | Product page HTML has an "X ratings"-style element | `ProductFacts.review_count` equals that parsed integer | N/A |
| Aggregate ratings-count element missing/unparseable | HTML lacks the element, or its text doesn't match the expected pattern | `ProductFacts.review_count` is `None` | N/A |

</frozen-after-approval>

## Code Map

- `app/models/product.py` -- edit in place (core/shared, AD-11): add `review_count: int | None = None` to `ProductFacts`
- `app/pipeline/sources/scraper_tier2.py` -- edit in place: add `_extract_review_count(soup) -> int | None` (parses the aggregate ratings-count text near the title, e.g. `#acrCustomerReviewText`, strips non-digit characters) and wire it into `parse_product_facts()`
- `app/models/review_signal.py` -- new (core/shared, AD-11): `ReviewSignalAssessment(BaseModel)` -- `is_low_signal: bool`, `reason: str | None`
- `app/pipeline/review_signal.py` -- new (core/shared, AD-11): `assess_review_signal(review_count: int | None) -> ReviewSignalAssessment`, `_LOW_REVIEW_THRESHOLD = 10`
- `tests/fixtures/amazon_product_basic.html` / `amazon_product_variant.html` -- edit: add an aggregate ratings-count element for the extraction tests
- `tests/pipeline/test_review_signal.py` -- new: covers the assessment I/O Matrix rows
- `tests/pipeline/sources/test_scraper_tier2.py` -- edit: extend with `_extract_review_count`/`parse_product_facts` coverage for the new field

## Tasks & Acceptance

**Execution:**
- [x] `app/models/product.py` -- add `review_count` field to `ProductFacts` -- carries the page's aggregate ratings count
- [x] `app/pipeline/sources/scraper_tier2.py` -- add `_extract_review_count()` and wire into `parse_product_facts()` -- populates the new field from the existing render
- [x] `app/models/review_signal.py` -- add `ReviewSignalAssessment` model -- typed low-signal result for Story 1.7 to consume
- [x] `app/pipeline/review_signal.py` -- implement `assess_review_signal()` -- FR-5's threshold check
- [x] `tests/fixtures/amazon_product_basic.html` / `amazon_product_variant.html` -- add ratings-count markup -- supports the new extraction tests without live network
- [x] `tests/pipeline/test_review_signal.py` -- cover the assessment I/O Matrix rows -- proves FR-5's threshold/unknown-handling guarantees
- [x] `tests/pipeline/sources/test_scraper_tier2.py` -- extend with `review_count` extraction edge cases -- proves the fetch-side degrades honestly

**Acceptance Criteria:**
- Given a `review_count` below 10, when assessed, then the result flags low signal and states a human-readable reason naming the count.
- Given a `review_count` of 10 or more, when assessed, then the result does not flag low signal.
- Given an unparseable/unknown `review_count`, when assessed, then the result flags low signal with a reason distinct from the below-threshold case.
- Given a product page with an aggregate ratings-count element, when facts are extracted, then `ProductFacts.review_count` reflects that count.

## Implementation Notes

- **Review patch round:** all 6 `patch`-routed findings were fixed by the same implementation subagent: the review-count regex is now anchored to "rating(s)" and strips both `,` and `.` before parsing (fixing both the unanchored-match and EU-dot-grouping gaps in one change), a `model_validator` now enforces `ReviewSignalAssessment`'s `reason`/`is_low_signal` invariant, a `Field(ge=0)` constraint was added to `ProductFacts.review_count`, a missing "0 ratings" extraction test was added, and the threshold-source doc comment was corrected to cite the PRD addendum instead of the architecture spine. Full suite is 75/75 passing, `ruff check` clean. Two findings were rejected: the review-sampling/review-signal module split (fix would be a spec-documentation edit, excluded from patch/defer routing by the triage rules) and the empty Implementation Notes/Review Triage Log sections flagged mid-review (expected workflow sequencing, populated at this point).

## Spec Change Log

## Review Triage Log

- **Review-count regex doesn't handle EU-style dot-grouped thousands separators (e.g. "1.234 ratings")** (`scraper_tier2.py::_extract_review_count`/`_REVIEW_COUNT_PATTERN`) — `medium` — `patch`. Verified: the regex `[\d,]+` stops at a `.`, so "1.234" parses as `1` instead of `1234` -- a silently *wrong* small number, not the honest `None` fallback the rest of this function uses elsewhere. Unlike price parsing, review counts have no fractional/decimal use case, so both `.` and `,` can be safely stripped before parsing with zero disambiguation needed -- a simple, contained fix.
- **Review-count regex isn't anchored to the "rating(s)" phrase, so it takes the first digit run anywhere in the element's text** (`scraper_tier2.py::_extract_review_count`) — `low` — `patch`. Verified: `[\d,]+` via `.search()` matches whatever digits appear first, with no check that they precede "rating(s)". Real but narrow risk if the selected element's text ever contains an unrelated leading number. Trivial fix (anchor the pattern to the phrase, mirroring how `_RATING_PATTERN` elsewhere in this file anchors to "out of 5 stars").
- **`ReviewSignalAssessment` has no validator enforcing its own documented invariant** (`reason is None` iff `is_low_signal is False`) (`app/models/review_signal.py`) — `low` — `patch`. Verified: nothing stops constructing an inconsistent instance; `assess_review_signal()` itself is always consistent today, but the type doesn't enforce it for future callers (e.g. Story 1.7). Trivial fix (one Pydantic model validator), same category as Story 1.3's `Review.rating` range-constraint patch.
- **No extraction-side test for a "0 ratings" page state** (`tests/pipeline/sources/test_scraper_tier2.py`) — `low` — `patch`. Verified: `assess_review_signal(0)` is tested directly, but `_extract_review_count`/`parse_product_facts` are never exercised against a zero-count element; traced the regex/match logic by hand and it already returns `0` correctly (a `re.Match` object is truthy regardless of matched text), so this is a coverage gap, not a live bug. Trivial fix (one more fixture-style test).
- **`ProductFacts.review_count` has no lower-bound constraint** (`app/models/product.py`) — `low` — `patch`. Verified: a bare `int | None` with no `Field(ge=0)`; a parsing anomaly could produce a negative value silently. Trivial fix, same pattern as Story 1.3's `Review.rating` range constraint.
- **Code comment attributes the `10`-review threshold to "the architecture['s stated number]" when the actual source is the PRD addendum** (`app/pipeline/review_signal.py` docstring) — `low` — `patch`. Verified: the Architecture Spine explicitly defers FR-5's numeric threshold as an implementation detail, not a cross-branch contract, and never states `10`; the number comes from the PRD addendum's "Review Sampling Strategy" section. The number itself is correct; only the citation wording is loose. Trivial rewording.
- **FR-4/FR-5 review logic now spans two separate pipeline modules (`review_sampling.py`, `review_signal.py`) without the spec's Design Notes explaining why, when the architecture's structural seed names one module for this area** — `low` — rejected. The smallest fix here is a spec-documentation edit (expanding Design Notes), which the triage rules exclude from patch/defer routing. No functional harm: both modules remain independently correct, tested, and clearly separated by concern (fact extraction/sampling vs. a derived judgment for a different future consumer).
- **Spec's `Implementation Notes`/`Review Triage Log` sections were empty while status was `in-review`** — rejected. Expected workflow sequencing: both sections are populated by this review step and the next (present) step, exactly as in every prior story in this epic; not a defect in the implementation.

## Design Notes

- `review_count` approximates FR-5's "total reviews" using Amazon's aggregate *ratings* count element (the number shown near the title, e.g. "1,234 ratings") rather than a true written-review count, since that is the only total-volume number visible without navigating to a separate reviews page (itself a known, already-deferred limitation from Story 1.3). This is named here rather than treated as exact.
- Unknown `review_count` is deliberately treated as low signal rather than defaulting to "assume enough" -- consistent with this project's standing honesty principle (AD-4): the system never treats an unmeasured quantity as if it were confirmed sufficient.
- `ReviewSignalAssessment` is kept as its own small model (mirroring `Review`'s own file from Story 1.3) rather than added as fields on `ProductFacts`, since it is a derived judgment about the data, not a fact extracted from the page.

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing tests plus the new review-signal and scraper extraction tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors
