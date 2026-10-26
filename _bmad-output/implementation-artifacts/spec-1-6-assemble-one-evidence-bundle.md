---
title: 'Assemble one Evidence Bundle'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '69c06b0fa799eeccc240a8aebee60332100edd61'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Stories 1.1-1.5 each produce one honestly-degrading piece of evidence (facts, reviews, review signal, alternatives) but nothing yet combines them into the one consistent record a verdict must be grounded in -- without it, a future synthesis step would have to call each stage itself and could easily drop or flatten a degraded state.

**Approach:** Add an `EvidenceBundle` model carrying all four pieces as distinct, separately-typed fields, and an `assemble_evidence_bundle(url, source) -> EvidenceBundle | InsufficientDataResult` function in `pipeline/orchestrator.py` (core/shared, AD-11) that composes Story 1.2's `resolve_product_facts()` with Story 1.3-1.5's review/alternatives functions. A failed or insufficient extraction short-circuits before any review or alternatives work begins -- Story 1.2's honest-failure gate is never bypassed.

## Boundaries & Constraints

**Always:**
- `assemble_evidence_bundle()` is the one place that combines Stories 1.1/1.3/1.4/1.5's outputs into a single `EvidenceBundle`; a failed/insufficient extraction short-circuits immediately, returning `resolve_product_facts()`'s `InsufficientDataResult` unchanged, before any review or alternatives call is made.
- `EvidenceBundle` carries `product_facts`, `reviews`, `review_signal`, and `alternatives` as four distinct, separately-typed fields -- facts are never merged with opinion-bearing data.
- A degraded/empty result from any sub-stage (empty review list, low review signal, empty alternatives list) is carried through into the bundle as-is, never re-interpreted or flattened into a different meaning.
- Reuses Story 1.1-1.5's functions and types exactly as they are -- no changes to `resolve_product_facts()`, `sample_reviews()`, `assess_review_signal()`, `select_alternatives()`, or any `ProductSource` method.

**Never:**
- No LLM synthesis, Confidence Score computation, or Verdict production in this story -- that is Story 1.7's job.
- No FastAPI app, routes, or SSE progress events -- those are Story 1.8/1.9.
- No concurrency/parallelization of the sub-stage calls -- sequential composition is sufficient for now; a future story may revisit this for latency.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Happy path, everything succeeds | Valid URL; facts, reviews, and alternatives all resolve | `EvidenceBundle` with all four fields populated | N/A |
| Extraction fails or is insufficient | `resolve_product_facts()` returns `InsufficientDataResult` | That same result is returned immediately; no review or alternatives calls are made | N/A |
| No reviews found | `source.fetch_reviews()` returns `[]` | `EvidenceBundle.reviews == []`; `review_signal.is_low_signal is True` | N/A |
| No alternatives found | `find_candidate_alternatives()`/`select_alternatives()` return `[]` | `EvidenceBundle.alternatives == []` | N/A |
| Product has no category | `facts.category is None` | Alternatives lookup still returns `[]` safely (Story 1.5's existing guard), not raising | N/A |

</frozen-after-approval>

## Code Map

- `app/models/evidence.py` -- new (core/shared, AD-11): `EvidenceBundle(BaseModel)` -- `product_facts: ProductFacts`, `reviews: list[Review]`, `review_signal: ReviewSignalAssessment`, `alternatives: list[ProductFacts]`
- `app/pipeline/orchestrator.py` -- edit in place (core/shared, AD-11, AD-1): add `assemble_evidence_bundle(url: str, source: ProductSource) -> EvidenceBundle | InsufficientDataResult`, composing (in order) `resolve_product_facts()`, `source.fetch_reviews()`, `sample_reviews()`, `assess_review_signal()`, `source.find_candidate_alternatives()`, `select_alternatives()`
- `tests/pipeline/test_orchestrator.py` -- edit: extend the existing stub `ProductSource` (or add a richer one) to also support `fetch_reviews`/`find_candidate_alternatives`, and cover the I/O Matrix rows above

## Tasks & Acceptance

**Execution:**
- [x] `app/models/evidence.py` -- add `EvidenceBundle` model -- the one consistent record a verdict will be grounded in
- [x] `app/pipeline/orchestrator.py` -- implement `assemble_evidence_bundle()` -- composes the five existing stage functions into one bundle
- [x] `tests/pipeline/test_orchestrator.py` -- cover the I/O Matrix rows -- proves the short-circuit and degraded-state-preservation guarantees

**Acceptance Criteria:**
- Given product facts, a review sample, and alternatives have all been gathered, when assembled, then the Evidence Bundle holds all three as distinct, separately-typed fields.
- Given extraction fails or is insufficient, when assembling, then that `InsufficientDataResult` is returned immediately and no Evidence Bundle is produced.
- Given any sub-stage degrades to an empty or low-signal result, when assembled, then that state is preserved as-is in the Evidence Bundle rather than silently treated as "found nothing happened."

## Implementation Notes

- Added `app/models/evidence.py`'s `EvidenceBundle(BaseModel)` exactly as specified: `product_facts: ProductFacts`, `reviews: list[Review]`, `review_signal: ReviewSignalAssessment`, `alternatives: list[ProductFacts]` -- four distinct, separately-typed fields, no new computed fields.
- Added `assemble_evidence_bundle(url, source) -> EvidenceBundle | InsufficientDataResult` to `app/pipeline/orchestrator.py`, composing the five existing stage functions in the Code Map's order: `resolve_product_facts()` -> (if `InsufficientDataResult`, return immediately) -> `source.fetch_reviews()` -> `sample_reviews()` -> `assess_review_signal(facts.review_count)` -> `source.find_candidate_alternatives(facts.category)` -> `select_alternatives(facts, candidates)`. No existing function or `ProductSource` method was changed.
- `review_signal` is computed from `product_facts.review_count`, not `len(reviews)`/`len(sampled_reviews)`, per this spec's own Design Notes.
- `facts.category` (which may be `None` or `""`) is passed straight through to `source.find_candidate_alternatives()` without an extra guard at the call site -- `ScraperTier2Source.find_candidate_alternatives()` already has an `if not category: return []` guard from Story 1.5 covering both, so this relies on that existing contract rather than duplicating the check.
- **Review patch round:** all 4 `patch`-routed findings were fixed by the same implementation subagent: `ProductSource.find_candidate_alternatives()`'s `category` parameter is now typed `str | None` (matching what the orchestrator actually passes), `assemble_evidence_bundle()` now logs a warning on each of its three degraded outcomes (empty reviews, low review signal, empty alternatives), its comment now names both the `None` and `""` category cases, and two tests were added covering `review_count=None` and `category=""` through the full integration path. 2 findings were deferred (no defensive handling of a hypothetical future `ProductSource` that breaks its own never-raises contract; no aggregate timeout across the three sequential source calls -- both extend already-deferred Story 1.2 entries). 3 findings were rejected (deliberate, already-documented sequential-composition choice; `EvidenceBundle.alternatives`' type isn't a new decision; redundant re-testing of Story 1.5's own thoroughly-unit-tested `select_alternatives()`). Full suite is 114/114 passing, `ruff check` clean.
- Extended `tests/pipeline/test_orchestrator.py`'s stub `ProductSource` with `fetch_reviews`/`find_candidate_alternatives` (recording calls on each), added a `_review()` helper, and extended `_facts()` with optional `category`/`review_count` kwargs (defaults preserve the existing tests' behavior unchanged). Added 7 new tests for `assemble_evidence_bundle()`, one per I/O Matrix row plus the invalid-URL short-circuit and the low-signal-despite-reviews-present case.
- Full suite: 112/112 passing (`uv run pytest tests/pipeline -v`); `uv run ruff check app/ tests/` clean.

## Spec Change Log

## Review Triage Log

- **`ProductSource.find_candidate_alternatives()`'s `category: str` annotation is stale now that `assemble_evidence_bundle()` genuinely passes `facts.category: str | None` through it** (`app/pipeline/sources/base.py`, `app/pipeline/orchestrator.py`) — `low` — `patch`. Verified: the new call site (`orchestrator.py`) and the test stub both already pass/accept `None` at runtime (correctly, since `ScraperTier2Source`'s own implementation guards it), but the Protocol's declared type doesn't say so, so static typing can't catch a real `None`-handling regression here. Trivial fix (widen the annotation to `str | None`).
- **`assemble_evidence_bundle()` adds no logging on its own degraded outcomes** (empty reviews, low review signal, empty alternatives) (`app/pipeline/orchestrator.py`) — `low` — `patch`. Verified: `resolve_product_facts()` logs a warning on every degraded path; the new function logs nothing, breaking this file's own established observability convention right where it matters for diagnosing a thin bundle in production. Same category and precedent as Stories 1.3/1.4/1.5's patched logging gaps.
- **`review_count=None` is never exercised through `assemble_evidence_bundle()`'s integration path** (`tests/pipeline/test_orchestrator.py`) — `low` — `patch`. Verified: the new tests use `review_count=25` and `review_count=3` but never `None`, even though `assess_review_signal()` treats unknown count as its own distinct low-signal case. The unit-level branch is already proven elsewhere (Story 1.4); this is specifically about proving the orchestrator wires it through. Trivial fix (one more test).
- **`facts.category == ""` is only informally covered by the same guard as `None`, with no comment or test saying so** (`app/pipeline/orchestrator.py`) — `low` — `patch`. Verified harmless by trace: `ScraperTier2Source`'s existing `if not category: return []` (Story 1.5) already catches `""` identically to `None`, so no live bug exists -- but the orchestrator's comment only names the `None` case, and no test exercises `""` at this call site. Trivial fix (broaden the comment wording; optionally add a test case).
- **`assemble_evidence_bundle()` has no defensive handling if `source.fetch_reviews()`/`source.find_candidate_alternatives()` raise directly, trusting their "never raises" docstring** — `maybe-false` — `defer`. Same category as the already-deferred Story 1.2 finding for `resolve_product_facts()`/`source.fetch()`: unreachable against the only `ProductSource` that exists today (`ScraperTier2Source`, proven never-raising for both methods in Stories 1.3/1.5), would only matter if a future source implementation breaks its own contract; if true, severity would be `medium`. Logged to `deferred-work.md`, extending the existing entry's reasoning to the two new methods.
- **No aggregate timeout/cancellation budget across `assemble_evidence_bundle()`'s three sequential source calls** — `maybe-false` — `defer`. Same category as the already-deferred Story 1.2 finding (AD-9 assigns timeout responsibility to the stage level, satisfied today by each call's own 20s budget); now three sequential calls instead of one raise the aggregate worst-case latency proportionally. If true, severity would be `medium` (a slow-but-not-hanging bundle, not an indefinite hang). Logged to `deferred-work.md`.
- **Sub-stage calls run sequentially rather than concurrently, doubling/tripling wall-clock latency** — `low` — rejected. Explicitly decided and justified in this story's own Design Notes: no current requirement needs the latency win, and `asyncio.gather` would add error-aggregation complexity for no required benefit yet. Not an oversight the reviewer lacked visibility into the spec for.
- **`EvidenceBundle.alternatives: list[ProductFacts]` reuses the full fact-record shape with no comment justifying it over a narrower summary type** — `low` — rejected. Not a new decision introduced by this diff: `select_alternatives()` already returns `list[ProductFacts]` (Story 1.5); this story only carries that pre-existing type through into the new field unchanged.
- **The happy-path integration test only uses a single alternative candidate, never re-exercising `select_alternatives()`'s price-band/ordering/dedup logic end-to-end** — `low` — rejected. Redundant with Story 1.5's own thorough, dedicated unit tests of `select_alternatives()`; this story's test only needs to prove the *wiring* is correct (the right function is called with the right arguments and its result lands in the bundle), which it already does.
- **Product-page state could change between the separate `fetch()`/`fetch_reviews()`/`find_candidate_alternatives()` renders, so the bundle's fields could reflect slightly different page snapshots** — `low` — rejected. Inherent, pre-existing tradeoff of the multi-render architecture already accepted since Stories 1.1/1.3/1.5 (each already renders the page independently); not newly caused by this story, which only composes those existing calls. Self-correcting on the next request; a fix would mean a disproportionate single-render architecture redesign, well beyond this story's scope.

## Design Notes

- `EvidenceBundle` is a thin aggregate, not a new computation -- every field is the direct, unmodified output of an existing Story 1.1-1.5 function. This story's only real logic is the short-circuit-on-insufficient-data sequencing.
- Sub-stage calls run sequentially (facts, then reviews, then alternatives) rather than concurrently. Nothing in this story's scope needs the latency win, and introducing `asyncio.gather` here would add error-aggregation complexity (what happens if one of several concurrent calls raises) for no required benefit yet.
- `review_signal` is computed from `product_facts.review_count`, not from `len(reviews)` -- consistent with Story 1.4's own design (the aggregate ratings count is the more honest total-volume signal; the bounded sample is deliberately capped and would under-count on popular products).

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing tests plus the new Evidence Bundle assembly tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors
