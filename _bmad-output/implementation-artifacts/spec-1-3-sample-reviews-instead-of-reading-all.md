---
title: 'Sample reviews instead of reading all of them'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '31bfedfc26da418917d7c5b9ab730fd18ed55cbb'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing yet retrieves a product's reviews or reduces them to a bounded, representative sample — without one, a product with thousands of reviews would blow up LLM cost/time once synthesis exists, and a thin sample could be mistaken for a settled answer (FR-4).

**Approach:** Add a `Review` model and a `sample_reviews(reviews) -> list[Review]` pure function implementing the architecture's stratified sample (top 20 by helpfulness + 10 most-critical + 10 most recent, near-duplicates removed first). Extend the `ProductSource` port with `fetch_reviews(url) -> list[Review]` so `ScraperTier2Source` can supply real input, reusing Story 1.1's render/retry/timeout pattern. Never raises; an unreadable review section degrades to an empty list, same honesty principle as `fetch()` (AD-4).

## Boundaries & Constraints

**Always:**
- `sample_reviews()` is a pure function — no I/O, deterministic for identical input.
- Output size never exceeds 40 (20 helpful + 10 critical + 10 recent), regardless of input size.
- At least one critical (rating ≤ 2) review is included whenever at least one exists in the input, subject to the 10-critical cap.
- Near-duplicate reviews (identical normalized body text) are deduplicated before sampling; first occurrence wins.
- `fetch_reviews()` never raises (AD-4, AD-9): any render/parse failure, after the same retry/timeout budget as `fetch()`, degrades to `[]` rather than propagating.
- Reuses Story 1.1/1.2's `ProductFacts`, `SourceFailure`, `canonicalize()` exactly as-is.

**Never:**
- `Review`s are not added as a field on `ProductFacts` — the epic treats "review sample" as a separate stage output from "product facts" (both feed Story 1.6's Evidence Bundle independently), not nested data.
- No orchestrator/pipeline wiring connecting this stage to the rest of the pipeline — that is Story 1.6's job.
- No embedding/ML-based near-duplicate clustering — v1 dedup is exact, normalized-text matching only.
- No FastAPI app, routes, or LLM synthesis in this story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Thousands of reviews | Large synthetic set, mixed ratings/dates | `sample_reviews()` returns ≤ 40 reviews | N/A |
| Critical review(s) exist | ≥1 review with rating ≤ 2 among many | Output includes ≥1 of them | N/A |
| No critical reviews | All ratings ≥ 3 | No critical-bucket entries; other buckets unaffected | N/A |
| Near-duplicate reviews | Two reviews, identical normalized body text | Only the first occurrence is kept | N/A |
| Fewer reviews than the bound | 5 total, no duplicates | All 5 returned unchanged | N/A |
| Review section unreadable/blocked | Valid URL, render/parse fails after retries | `fetch_reviews()` returns `[]` | Never raises |
| Missing helpful-vote count | Review HTML lacks a parseable vote count | `helpful_votes` defaults to `0` | N/A |
| Missing/unparseable review date | Review HTML date text doesn't match the expected format | `review_date` is `None`; excluded from the recent bucket | N/A |

</frozen-after-approval>

## Code Map

- `app/models/review.py` -- new: `Review(BaseModel)` -- `rating: int`, `title: str | None`, `body: str`, `helpful_votes: int = 0`, `review_date: date | None = None`
- `app/pipeline/sources/base.py` -- edit in place (core/shared, AD-11): add `async def fetch_reviews(self, url: str) -> list[Review]` to the `ProductSource` Protocol
- `app/pipeline/sources/scraper_tier2.py` -- edit in place: add `parse_reviews(html) -> list[Review]` (Playwright-free, mirrors `parse_product_facts`) and `ScraperTier2Source.fetch_reviews()` (reuses `_render`, `_FETCH_TIMEOUT_SECONDS`, `_MAX_ATTEMPTS`, `_RETRY_DELAY_SECONDS`; on exhaustion returns `[]` instead of `SourceFailure` — absence of reviews is an honest degraded value here, not a page-level failure)
- `app/pipeline/review_sampling.py` -- new (core/shared, AD-11): `sample_reviews(reviews: list[Review]) -> list[Review]`
- `tests/fixtures/amazon_product_reviews.html` -- new: a handful of review blocks (`[data-hook="review"]`-style markup) for `parse_reviews()` tests
- `tests/pipeline/test_review_sampling.py` -- new: covers the I/O Matrix's sampling scenarios with synthetic data
- `tests/pipeline/sources/test_scraper_tier2.py` -- edit: extend with `parse_reviews()`/`fetch_reviews()` coverage, same style as the existing `fetch()` tests

## Tasks & Acceptance

**Execution:**
- [x] `app/models/review.py` -- add `Review` model -- typed contract for one parsed review
- [x] `app/pipeline/sources/base.py` -- add `fetch_reviews()` to the `ProductSource` Protocol -- extends the Data Source Port to review data (AD-3)
- [x] `app/pipeline/sources/scraper_tier2.py` -- add `parse_reviews()` + `ScraperTier2Source.fetch_reviews()` -- reuses the render/retry/timeout pattern from `fetch()`
- [x] `app/pipeline/review_sampling.py` -- implement `sample_reviews()` -- stratified, bounded, dedup'd sample per FR-4
- [x] `tests/fixtures/amazon_product_reviews.html` -- add fixture -- supports `parse_reviews()` tests without live network
- [x] `tests/pipeline/test_review_sampling.py` -- cover the I/O Matrix's sampling scenarios -- proves FR-4's bounded/critical-inclusion guarantees
- [x] `tests/pipeline/sources/test_scraper_tier2.py` -- extend with fetch/parse edge cases -- proves the fetch-side degrades honestly

**Acceptance Criteria:**
- Given a product with thousands of reviews, when sampled, then the returned sample size stays bounded (≤ 40) regardless of total input count.
- Given at least one critical (1-2 star) review exists in the input, when sampled, then the output includes at least one of them.
- Given two or more reviews with identical normalized body text, when sampled, then only the first occurrence survives deduplication.
- Given a product's review section fails to render or parse after retries, when `fetch_reviews()` is called, then it returns an empty list rather than raising.

## Implementation Notes

- **Review patch round:** all 7 `patch`-routed findings were fixed by the same implementation subagent: comma-stripping and a singular "One person" special case in the helpful-vote regex, a best-effort review-section hydration wait in `fetch_reviews()`'s render path (never fails the fetch on a genuinely review-free product), a `Field(ge=1, le=5)` constraint on `Review.rating`, a `(normalized_body, rating)` dedup key in `_deduplicate()`, a `logger.debug` call on `parse_reviews()`'s skip path, and a new test proving the recency bucket actually rescues a review the helpful/critical buckets miss. One follow-up ruff `S110` violation introduced by the hydration-wait's `try`/`except`/`pass` was fixed directly (changed to `logger.debug` the caught exception) rather than looping back to the subagent for something this small. Full suite is 62/62 passing, `ruff check` clean on all touched files. Two forward-looking gaps (no review-pagination beyond one page load; non-English-locale review markup unrecognized) were logged to `deferred-work.md` rather than patched, matching Story 1.1's precedent for disproportionate-fix, real-but-deferrable findings.

## Spec Change Log

## Review Triage Log

- **Helpful-vote count truncated by a thousands comma** (`scraper_tier2.py::_extract_review_helpful_votes`/`_HELPFUL_VOTES_PATTERN`) — `medium` — `patch`. Verified: `\d+` can't cross a comma, so "1,234 people found this helpful" matches only the trailing group, yielding `234` not `1234`. Feeds directly into the top-20-by-helpfulness bucket — the primary, 20-of-40-slot sampling criterion — on exactly the popular, high-review-volume products this story targets. Trivial fix (strip commas before matching).
- **Singular "One person found this helpful" not matched** (`scraper_tier2.py::_extract_review_helpful_votes`) — `low` — `patch`. Verified: the regex requires `\d+`, which "One" (word) never satisfies; falls back to `0` instead of `1`. Low impact (a 1-vote review is already near the bottom of the helpfulness ranking) but the fix is a trivial one-line special case, so the low-reject rule's "fix is more than trivial" condition fails and this is kept.
- **`_render()` never waits for the review section before `fetch_reviews()` reads page content** (`scraper_tier2.py::_render`, reused unchanged by `fetch_reviews()`) — `medium` — `patch`. Verified: only `#productTitle` is awaited; Story 1.1's own precedent (`_render()`'s existing comment) is that JS-injected content needs an explicit hydration wait, and reviews are plausibly lazy-loaded/below-fold on real pages. A late-hydrating widget would make `fetch_reviews()` see zero/partial reviews, undermining the "bounded sample of many reviews" premise. Fix must not hard-fail when a product legitimately has zero reviews (short timeout, no raise).
- **`Review.rating` has no value-range constraint** (`app/models/review.py`) — `low` — `patch`. Verified: a bare `int` with no `Field(ge=1, le=5)`; a parsing anomaly would construct an out-of-range rating silently. Trivial fix, so kept despite low everyday likelihood.
- **Dedup ignores rating, risking silent loss of the one critical review on a body-text collision** (`review_sampling.py::_deduplicate`) — `medium` — `patch`. Verified: the dedup key is normalized body text only, applied *before* the critical-rescue bucket runs; two reviews sharing identical (often short/generic) body text but different ratings collapse to whichever came first, regardless of rating. Real risk specifically in the "thousands of reviews" scenario this story targets, where short-text collisions are more likely — directly threatens the "at least one critical review included" acceptance criterion. Trivial fix (key on `(normalized_body, rating)` instead of body alone).
- **`parse_reviews()` silently skips malformed review blocks with no log trace** (`scraper_tier2.py::parse_reviews`) — `low` — `patch`. Verified: no `logger` call on the skip path, unlike `fetch()`/`fetch_reviews()` which log every failed attempt; a page-wide selector break would be indistinguishable from "no reviews on this page." Same category and trivial fix as Story 1.2's analogous logging gap.
- **Recency bucket's additive selection has no test that would fail if it broke** (`tests/pipeline/test_review_sampling.py`) — `medium` — `patch` (verification-gap finding, pre-verified). The one test with "recent" in its name never reaches a non-empty `recent_picks` (its own reviews all fit in the top-20-helpful bucket first); deleting the recency-bucket code outright would still pass the full suite. Code itself reads correctly on inspection; this is a coverage gap, not a functional bug. Fix: add a test mirroring the critical-bucket rescue test, shaped for recency.
- **`fetch_reviews()` can only ever see the handful of reviews on one product-page load — no pagination to a dedicated review-listing page** — `medium` — `defer`. Verified as a real, caused-by-this-story design limitation: Amazon's product page typically surfaces only a handful of "top reviews" inline; reaching "thousands" would require crawling a separate, paginated review-listing endpoint — a materially different, disproportionate scraping concern, same category as Story 1.1's deferred amzn.to short-link gap. `sample_reviews()`'s stratification logic is correctly implemented and will work correctly once given a larger pool; this gap is about what `fetch_reviews()` can supply it today.
- **Non-English Amazon-locale review markup isn't recognized, so `fetch_reviews()` silently returns `[]` for any of the 17 non-English-language domains `canonicalize()` already accepts** (`scraper_tier2.py::_extract_review_rating`/`_RATING_PATTERN`) — `medium` — `defer`. Verified: `_RATING_PATTERN` only matches the English "X out of 5 stars" phrasing, and `parse_reviews()` skips any block whose rating can't be parsed — on a non-English site, every review is skipped, a full-dataset loss (unlike the date-locale case below, which loses only one field). Real regression relative to Story 1.1's locale-agnostic price/title extraction, but a full fix is a disproportionate i18n effort needing a deliberate design decision, not a patch.
- **Non-English/unparseable review-date text yields `None`** (`scraper_tier2.py::_extract_review_date`) — `false` — rejected. Refuted: this is exactly the designed, already-tested "unparseable date text → `None`, excluded from the recent bucket" fallback this story's own Boundaries require — zero review-data loss (unlike the rating-locale gap above, which drops the whole review), just one more instance of an already-anticipated case.
- **Half-star rating rounds via Python's banker's-rounding bias** (`scraper_tier2.py::_extract_review_rating`) — `false` — rejected. Refuted: Amazon's per-review star rating (the `data-hook="review-star-rating"` element this function targets) is always a whole-star integer — reviewers cannot submit half-star ratings; only the page's separate aggregate/average rating uses fractional values, and that is not what this selector reads. Confirmed by the fixture's own four examples, all whole numbers. `round()`'s half-to-even behavior on a `.5` input is therefore unreachable in practice.
- **`fetch_reviews()` duplicates `fetch()`'s entire retry/timeout/logging loop instead of sharing a helper** (`scraper_tier2.py`) — `low` — rejected. Real, named developer-only risk (the two copies could drift), but it's a future-maintenance concern rather than something hit in everyday use, and the smallest correct fix (extracting a shared retry helper used by both methods) is a non-trivial refactor of two methods' control flow, not a direct correction — both reject conditions hold.

## Design Notes

- Reviews are a separate stage output from `ProductFacts`, not a nested field, because Story 1.6's Evidence Bundle assembly consumes them as two independently-degradable inputs (epic context's Cross-Story Dependencies) — collapsing them would make a facts-only failure and a reviews-only failure indistinguishable.
- Dedup uses exact matching on normalized body text (lowercased, whitespace-collapsed), first occurrence wins — same "first wins" convention as `scraper_tier2.py`'s spec extraction. The architecture's "cluster near-duplicates" language is satisfied at v1 scope; fuzzy/embedding-based clustering is a future enhancement only if exact-match proves insufficient in practice.
- Stratified selection order: (1) dedup the full input, (2) take top 20 by `helpful_votes` descending, (3) add up to 10 not-already-included reviews with `rating <= 2`, sorted by rating ascending then `helpful_votes` descending, (4) add up to 10 not-already-included reviews with a non-`None` `review_date`, sorted descending. A review already included via an earlier bucket is never duplicated into a later one, so the 40-cap holds even when buckets overlap.
- `fetch_reviews()` renders the page independently of `fetch()` rather than sharing one render — a real double page-load cost for v1. Reusing a single render across both would require changing `fetch()`'s return shape, a larger change this story's "no changes to `fetch()`'s existing behavior" boundary rules out; left as a known, named tradeoff for whoever wires Story 1.6's orchestration to reconsider.

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing tests plus the new review-sampling and scraper review-parsing tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors
