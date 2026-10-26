---
title: 'Surface comparable alternatives'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '9786236bdb226ca110cc3ec0109804ca4ca7dfc6'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A Skip or Wait verdict currently leaves the user with nowhere to go — nothing yet finds comparable products in the same category and a similar price range.

**Approach:** Extract the product's category from the page's breadcrumb into a new `ProductFacts.category` field. Extend the `ProductSource` port with `find_candidate_alternatives(category) -> list[ProductFacts]`, implemented by searching Amazon for that category (same port, same honest-failure principle as `fetch`/`fetch_reviews` -- never raises, degrades to `[]`). Add a pure `select_alternatives(reference, candidates) -> list[ProductFacts]` that excludes the reference product itself and candidates outside a similar price band, returning up to 3 matches, never failing when none exist (FR-6).

## Boundaries & Constraints

**Always:**
- `find_candidate_alternatives()` never raises (AD-4, AD-9): any failure -- unreachable search page, parse failure, timeout -- degrades to `[]`, same principle as `fetch_reviews()`.
- `select_alternatives()` is a pure function -- no I/O, deterministic for identical input.
- The reference product itself (matched by `canonical_product_id`) is never included in the result.
- Alternatives are capped at 3; returning fewer (including zero) is a legitimate, non-failing outcome -- never padded, never an error.
- A candidate with an unknown price, or a reference with an unknown price, is excluded from price-band matching rather than guessed into or out of it.
- Reuses Story 1.1/1.3/1.4's `ProductFacts`, `canonicalize()`, `ScraperTier2Source.fetch()` exactly as-is beyond the new field/methods below.

**Never:**
- No orchestrator/pipeline wiring connecting this to Evidence Bundle/Verdict -- that is Story 1.6's job.
- No FastAPI app, routes, or LLM synthesis in this story.
- `select_alternatives()` does not re-verify category similarity -- that scoping is trusted to `find_candidate_alternatives()`'s own category-filtered search query, not re-checked field-by-field.
- No same-base-product/variant deduplication beyond the exact-`canonical_product_id` self-exclusion -- detecting "a different color/size variant of the same base product" is unspecified and out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| 3+ in-band candidates available | Reference + many same-category candidates within the price band | Returns the 3 closest by price | N/A |
| Fewer than 3 in-band candidates | Reference + 1-2 matching candidates | Returns those 1-2; never padded | N/A |
| No candidates in band | All candidates outside the price band, or none at all | Returns `[]`; caller still produces its result | N/A |
| Reference product appears among candidates | A candidate shares the reference's `canonical_product_id` | That candidate is excluded | N/A |
| Reference or a candidate's price is unknown | `reference.price is None`, or a candidate's `price is None` | That candidate is excluded from matching (unknown reference price → empty result) | N/A |
| Search page unreachable/blocked | Valid category string, render/parse fails after retries | `find_candidate_alternatives()` returns `[]` | Never raises |
| Search result missing a parseable title/price/link | Malformed result card on an otherwise-valid page | That card is skipped; other cards still parsed | N/A |

</frozen-after-approval>

## Code Map

- `app/models/product.py` -- edit in place (core/shared, AD-11): add `category: str | None = None` to `ProductFacts`
- `app/pipeline/sources/base.py` -- edit in place: add `async def find_candidate_alternatives(self, category: str) -> list[ProductFacts]` to the `ProductSource` Protocol
- `app/pipeline/sources/scraper_tier2.py` -- edit in place:
  - `_extract_category(soup) -> str | None` -- parses the breadcrumb (`#wayfinding-breadcrumbs_feedback li a`), takes the last (most specific) item's text; wired into `parse_product_facts()`
  - `build_search_url(category: str) -> str` -- pure, mirrors `build_proxy_config`; builds an Amazon search URL (`k=` query param) for `category`
  - `parse_search_results(html: str, category: str) -> list[ProductFacts]` -- Playwright-free, mirrors `parse_product_facts`; parses `[data-component-type="s-search-result"]` cards (title, price via the existing `_extract_price` pattern, product link resolved to an absolute URL then passed through `canonicalize()`); skips any card missing a parseable title, price, or canonicalizable link; tags each result `category=category`, `source_tier=SourceTier.TIER_2`
  - `ScraperTier2Source.find_candidate_alternatives()` -- builds the search URL, renders it via the existing render/retry/timeout pattern, parses via `parse_search_results`; never raises, returns `[]` on exhaustion
- `app/pipeline/alternatives.py` -- new (core/shared, AD-11): `select_alternatives(reference: ProductFacts, candidates: list[ProductFacts]) -> list[ProductFacts]`
- `tests/fixtures/amazon_search_results.html` -- new: a handful of `s-search-result` cards for `parse_search_results` tests
- `tests/pipeline/test_alternatives.py` -- new: covers the selection I/O Matrix rows with synthetic `ProductFacts`
- `tests/pipeline/sources/test_scraper_tier2.py` -- edit: extend with `_extract_category`/`build_search_url`/`parse_search_results`/`find_candidate_alternatives` coverage

## Tasks & Acceptance

**Execution:**
- [x] `app/models/product.py` -- add `category` field to `ProductFacts` -- carries the page's breadcrumb category
- [x] `app/pipeline/sources/base.py` -- add `find_candidate_alternatives()` to the `ProductSource` Protocol -- extends the Data Source Port to alternatives lookup (AD-3)
- [x] `app/pipeline/sources/scraper_tier2.py` -- add `_extract_category()`, `build_search_url()`, `parse_search_results()`, `ScraperTier2Source.find_candidate_alternatives()` -- reuses the render/retry/timeout pattern
- [x] `app/pipeline/alternatives.py` -- implement `select_alternatives()` -- price-band matching, self-exclusion, capped at 3
- [x] `tests/fixtures/amazon_search_results.html` -- add fixture -- supports `parse_search_results()` tests without live network
- [x] `tests/pipeline/test_alternatives.py` -- cover the I/O Matrix's selection scenarios -- proves FR-6's bounded/non-failing guarantees
- [x] `tests/pipeline/sources/test_scraper_tier2.py` -- extend with category/search-side edge cases -- proves the search-side degrades honestly

**Acceptance Criteria:**
- Given a resolved Canonical Product with same-category, similar-price candidates available, when alternatives are looked up, then 2-3 alternatives in that category and price range are returned.
- Given no candidates exist in that band, when looked up, then an empty list is returned rather than raising or failing.
- Given a candidate that is the reference product itself, when selecting, then it is excluded from the result.

## Implementation Notes

- Implemented all seven Code Map items as specified: `ProductFacts.category`, the `find_candidate_alternatives()` Protocol method, the scraper-side `_extract_category()`/`build_search_url()`/`parse_search_results()`/`ScraperTier2Source.find_candidate_alternatives()`, and the pure `select_alternatives()` in a new `app/pipeline/alternatives.py`.
- `ScraperTier2Source._render()` previously hardcoded waiting on `#productTitle`, which doesn't exist on a search-results page. Generalized it with a `wait_selector` parameter (default unchanged at `#productTitle`) so `find_candidate_alternatives()` can wait on `[data-component-type="s-search-result"]` instead -- additive, backward-compatible, and the only deviation from the Code Map's literal text (which didn't mention `_render` needing a change, but "reuses the existing render/retry/timeout pattern" requires it, since the pattern as written only targeted the product-page shape).
- 23 new tests added (9 in `test_alternatives.py`, 14 in `test_scraper_tier2.py`), no existing tests modified in a way that changes their assertions.
- **Review patch round:** all 8 `patch`-routed findings were fixed: `find_candidate_alternatives()`/`build_search_url()` now guard `if not category: return []` before building the search URL so a missing or empty breadcrumb category degrades to `[]` instead of raising; `select_alternatives()`'s price band is now computed with `sorted()` so it's correct for a negative `reference.price`; candidates are deduplicated by `canonical_product_id` (first occurrence wins) before the top 3 are taken; `_extract_search_result_link()` now checks for a non-empty `href` before accepting a selector match instead of stopping at the first matching element; `find_candidate_alternatives()` now logs on the success path (including the zero-result-cards case), not just on retry/failure; a test covering `select_alternatives()`'s documented "doesn't re-check category" behavior was added; a test covering `parse_search_results()` skipping a card with an absolute off-Amazon href was added; and the tie-breaking rule for equidistant candidates (stable sort over input order) is now documented in `select_alternatives()`'s docstring. One finding was rejected (the first-match `.a-price .a-offscreen` selector ambiguity mirrors Story 1.1's already-accepted pattern and wasn't re-flagged there).
- Full suite after the patch round: 105/105 passing, `ruff check app/ tests/` clean.

## Spec Change Log

## Review Triage Log

- **Unguarded `category` input: `None` crashes uncaught, `""` silently returns irrelevant results, both violating the "never raises, degrades to `[]`" contract** (`scraper_tier2.py::find_candidate_alternatives`/`build_search_url`) — `high` — `patch`. Verified: `url = build_search_url(category)` runs *before* (outside) the retry loop's `try`/`except`, so `quote_plus(None)` raises an uncaught `TypeError` instead of degrading to `[]` -- a real contract violation, since `ProductFacts.category` is exactly the nullable field this same story introduces and will commonly be `None` whenever the breadcrumb is absent. An empty string instead silently hits a generic search page and returns its results as if they were real candidates. Fix: guard `if not category: return []` before building the URL.
- **`select_alternatives()`'s price-band bounds assume `reference.price` is non-negative** (`app/pipeline/alternatives.py`) — `medium` — `patch`. Verified: `low = price*(1-0.2)`, `high = price*(1+0.2)` inverts for a negative price (e.g. `price=-10` gives `low=-8, high=-12`), making `low <= candidate.price <= high` always false and silently returning `[]` even for genuinely matching candidates -- indistinguishable from the honest "no candidates in band" case. `ProductFacts.price` has no sign constraint today, so this isn't provably unreachable. Fix: compute the band with `sorted()`/`min()`/`max()` so it's correct regardless of sign -- smaller and more targeted than adding model-level validation.
- **`select_alternatives()` never deduplicates candidates against each other, only against the reference** (`app/pipeline/alternatives.py`) — `medium` — `patch`. Verified: the list comprehension excludes `candidate.canonical_product_id == reference.canonical_product_id` but applies no uniqueness check among candidates themselves; Amazon search results commonly list the same ASIN twice (e.g. a sponsored slot plus the organic listing), so one real product could occupy two of the three returned "alternative" slots. Trivial fix (dedupe by `canonical_product_id`, first occurrence wins, matching this project's established convention).
- **`_extract_search_result_link()`'s selector fallback breaks when the first selector matches an element lacking `href`** (`scraper_tier2.py`) — `low` — `patch`. Verified: `card.select_one("h2 a") or card.select_one("a.a-link-normal")` short-circuits on *finding an element*, not on finding one with a usable `href` -- if an `<a>` inside `<h2>` exists without an `href`, the second selector is never tried even though it might have one. Trivial fix (check for a non-empty `href` before accepting a match).
- **`find_candidate_alternatives()` logs on every retry/failure but never on success, including the "rendered fine, zero result cards" case** (`scraper_tier2.py`) — `low` — `patch`. Verified: no `logger` call on the return path; can't distinguish "genuinely no alternatives in this category" from "selector/markup drift silently broke matching" from logs alone. Same category and precedent as Story 1.3's patched `parse_reviews()` logging gap.
- **No test exercises `select_alternatives()`'s documented "doesn't re-check category" behavior** (`tests/pipeline/test_alternatives.py`) — `low` — `patch`. Verified: the `_facts()` helper never sets `category`, so the Boundaries' explicit claim that mixed-category candidates still pass through unaffected is asserted in prose only. Trivial fix (one test with mixed-category candidates).
- **`parse_search_results()`'s "never raises" claim is untested against an absolute off-Amazon href** (`tests/pipeline/sources/test_scraper_tier2.py`) — `low` — `patch`. Verified by trace: `urljoin` preserves an already-absolute href, so `canonicalize()` correctly raises `InvalidProductURLError` (non-Amazon host) and the card is skipped -- the logic is already correct, this is a coverage gap. Trivial fix (one test).
- **Tie-breaking for equidistant candidates is undocumented** (`app/pipeline/alternatives.py`) — `low` — `patch`. Verified: ties fall back to Python's stable sort over `candidates`' input order, which is deterministic but not stated anywhere as the rule. Trivial fix (one docstring line).
- **`_extract_search_result_price()` takes the first `.a-price .a-offscreen` match, which could in theory pick a struck-through list price over the current price on a multi-price card** — `low` — rejected. Mirrors the exact, already-accepted selector pattern Story 1.1's `_extract_price` uses for single product pages (identical ambiguity, never flagged there); typical Amazon markup places the current/sale price first in document order, so the common case already resolves correctly. A robust fix would need genuine sale-vs-list-price disambiguation logic -- more than a direct correction -- and it's unlikely to be hit in everyday use given the existing precedent.

## Design Notes

- The ±20% price-band width (`_PRICE_BAND_FRACTION` in `alternatives.py`) is this story's own default -- neither the PRD nor the architecture states an exact percentage, only "a similar price range" (FR-6). A future story can tune it without changing this function's shape.
- `select_alternatives()` deliberately does not re-check category: `find_candidate_alternatives(category)` already scopes candidates to that category by construction (it searched for exactly that string), so re-verifying it in the pure selection step would be redundant double-checking of a guarantee the caller already provides.
- Category comes from the breadcrumb's last entry (most specific node) rather than the full breadcrumb path, since that is what should drive the search query -- the top-level breadcrumb entries (e.g. "Electronics") are too broad to produce comparable results.
- Amazon search-result cards link via a relative path (e.g. `/AmazonBasics-Dot-Speaker/dp/B08N5WRWNW/ref=...`); `parse_search_results()` must resolve each link against the product's own domain before calling `canonicalize()`, which requires an absolute URL.
- When fewer than 3 (including exactly 1) in-band candidates exist, `select_alternatives()` returns what it has rather than requiring a minimum of 2 -- the epic's "2-3" is read as a cap, not a floor; the explicit non-failing floor is zero (FR-6's second scenario).

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing tests plus the new alternatives and scraper search-extraction tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors
