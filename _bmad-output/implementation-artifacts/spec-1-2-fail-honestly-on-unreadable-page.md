---
title: 'Fail honestly when a page cannot be read'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'a148f0fa6d188821888883836f941af1a9aa4662'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.1 made `canonicalize()` raise and `ScraperTier2Source.fetch()` return a typed `SourceFailure` on bad input or an unreadable page, but nothing yet turns either of those into the one explicit, user-facing "insufficient data" outcome FR-3 requires — there's no single place that guarantees a failure never silently produces a fabricated or partial result.

**Approach:** Add `InsufficientDataResult` to `models/` and a `resolve_product_facts(url, source) -> ProductFacts | InsufficientDataResult` function in a new `pipeline/orchestrator.py` (core/shared, AD-11) that calls `canonicalize()` then `source.fetch()`, mapping any failure from either step to `InsufficientDataResult` — never raising, never returning a partial `ProductFacts`. No FastAPI app or LLM synthesis exists yet, so "never reaches synthesis" holds structurally: this function has no code path that calls it.

## Boundaries & Constraints

**Always:**
- `resolve_product_facts()` is the only place that decides whether a request became `ProductFacts` or `InsufficientDataResult` — it never lets a `canonicalize()` exception or a `SourceFailure` propagate past itself unconverted (AD-4).
- `InsufficientDataResult` is a `models/` type (core/shared, AD-11), not owned by any one branch.
- Reuses Story 1.1's `ProductSource`, `SourceFailure`, `ProductFacts`, `canonicalize()`, `InvalidProductURLError` exactly as they are — no changes to `scraper_tier2.py` or `canonicalize.py`.

**Never:**
- No FastAPI app, routes, Evidence Bundle assembly, or LLM synthesis in this story — those belong to later stories (1.6+).
- No change to Story 1.1's existing modules or their tests.
- `resolve_product_facts()` takes a `ProductSource` as a parameter rather than constructing `ScraperTier2Source` itself — it must not hardcode a specific tier, so a future Tier 1/3 source can be passed in without changing this function.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Valid URL, scrape succeeds | Valid Amazon URL, source returns `ProductFacts` | Returns the `ProductFacts` unchanged | N/A |
| Non-Amazon URL | e.g. an ebay.com URL | `InsufficientDataResult(reason="invalid_url")` | N/A |
| Malformed/unparseable URL | Empty string, garbage text | `InsufficientDataResult(reason="invalid_url")` | N/A |
| Blocked/CAPTCHA/unsupported-layout page | Valid URL, `source.fetch()` returns `SourceFailure` | `InsufficientDataResult` carrying that failure's `reason`/`detail`/`source_tier` | N/A |
| Any failure case | — | — | Never raises; never returns a partially-filled `ProductFacts` |

</frozen-after-approval>

## Code Map

- `app/models/product.py` -- edit in place (core/shared, AD-11): add `InsufficientDataResult(reason: str, detail: str | None, source_tier: SourceTier | None)` next to the existing `SourceFailure`
- `app/pipeline/orchestrator.py` -- new (core/shared, AD-11, AD-1): `resolve_product_facts(url: str, source: ProductSource) -> ProductFacts | InsufficientDataResult`; catches `InvalidProductURLError` from `app/pipeline/canonicalize.py::canonicalize`, awaits `source.fetch(url)`, maps a `SourceFailure` 1:1 into `InsufficientDataResult`
- `tests/pipeline/test_orchestrator.py` -- new: covers the I/O Matrix using a stub `ProductSource` (no real scraper/network needed)

## Tasks & Acceptance

**Execution:**
- [x] `app/models/product.py` -- add `InsufficientDataResult` -- typed FR-3 result, distinct from the internal `SourceFailure` sentinel
- [x] `app/pipeline/orchestrator.py` -- implement `resolve_product_facts()` -- AD-1, AD-4
- [x] `tests/pipeline/test_orchestrator.py` -- cover the I/O Matrix with a stub source -- proves this story's ACs

**Acceptance Criteria:**
- Given a broken, CAPTCHA-blocked, or unsupported-layout URL, when `resolve_product_facts()` runs, then it returns an `InsufficientDataResult` and the call never raises.
- Given a non-Amazon or malformed URL, when `resolve_product_facts()` runs, then it returns the same kind of `InsufficientDataResult` rather than fabricated data.
- Given a valid URL whose fetch succeeds, when `resolve_product_facts()` runs, then it returns the `ProductFacts` unchanged.
- Given any failure path, when `resolve_product_facts()` returns, then nothing downstream is called — there is no code path in this function that reaches an LLM/synthesis step.

## Implementation Notes

- **Review patch round:** all 4 `patch`-routed findings from the review were fixed by the same implementation subagent: added `logger.warning` calls on both `InsufficientDataResult` paths in `orchestrator.py`; split the mislabeled `amazon.evil.com` domain-spoofing case into its own test; added a missing `result.detail is None` assertion; reformatted the over-length parametrize line. Full suite is 42/42 passing, `ruff check` and `ruff format --check` both clean on the two files this story touched. (Three pre-existing Story 1.1 files were found not `ruff format`-clean during independent re-verification — out of this story's scope per its own "no changes to Story 1.1's modules" boundary; logged to `deferred-work.md` as a standalone repo-wide formatting chore.)

## Spec Change Log

## Review Triage Log

- **No logging on `resolve_product_facts()`'s failure paths** (`orchestrator.py`) — `low` — `patch`. Verified: zero `logger` calls in the file, unlike `scraper_tier2.py` which already logs on degradation. A legitimate NFR-4 observability gap at the one choke point meant to guarantee failures are never silent; trivial fix (add a `logger.warning`/`logger.info` call on each `InsufficientDataResult` path).
- **Test naming mismatch: `amazon.evil.com` mislabeled as "malformed/unparseable"** (`test_orchestrator.py::test_malformed_or_unparseable_url_returns_insufficient_data`) — `low` — `patch`. Verified: that URL is well-formed and parseable; it fails host-allowlist matching (domain spoofing), a different failure mode than the other two parametrized cases. Real risk of misleading whoever next edits AD-2 host-matching logic; trivial fix (split it into its own test or rename).
- **Missing assertion that `SourceFailure.detail=None` propagates correctly** (`test_source_failure_never_raises_and_never_yields_partial_facts`) — `low` — `patch`. Verified: the test only asserts `isinstance`/`not isinstance`, never pins down `result.detail is None`. Trivial one-line addition.
- **Line-length violation in `test_orchestrator.py`'s parametrize decorator** — `low` — `patch`. Verified: line is 102 chars against the project's configured `line-length = 100`; `ruff check` doesn't flag it (E501 isn't in ruff's default rule-set) but `uv run ruff format --check` confirms it would be reformatted — quiet drift from declared style. Trivial fix (wrap the line / run `ruff format`).
- **`source.fetch()` raising directly is not caught by `resolve_product_facts()`** — `maybe-false` — `defer`. The frozen Boundaries bullet specifically scopes the never-propagate guarantee to "a `canonicalize()` exception or a `SourceFailure`," which the code satisfies exactly; the broader Intent-paragraph wording ("never raising... for any reason") is looser and only matters if a future Tier 1/3 `ProductSource` implementation breaks its own never-raises contract — no such source exists yet (`ScraperTier2Source` is proven never-raising per Story 1.1). If a future source did break this, severity would be `medium` (an uncaught exception reaching whatever eventually calls this function). Logged to `deferred-work.md` along with the matching missing-test-coverage gap.
- **No orchestrator-level timeout on `await source.fetch(url)`** — `maybe-false` — `defer`. AD-9 assigns timeout responsibility to the stage level, already satisfied today by `ScraperTier2Source`'s own 20s timeout (Story 1.1); adding a second, redundant timeout here would only matter for a future source that fails to bound its own `fetch()`. If true, severity would be `medium` (indefinite hang). Logged to `deferred-work.md`.
- **`source.fetch()`'s return value isn't runtime-type-checked before being treated as `ProductFacts`** — `low` — rejected. Today's only `ProductSource` (`ScraperTier2Source`) is fully Pydantic-typed and can't produce a malformed return value; if a future source did, the failure mode is an immediate, loud `AttributeError`/`TypeError` downstream, not a silent wrong-data bug — exactly the "code that loudly fails on a situation you never showed the program can reach" case the triage rules call correct behavior, not a defect. Fix (defensive `isinstance` guards) is speculative over-engineering against a contract already enforced by the type system.
- **`"invalid_url"` reason string duplicated across `orchestrator.py` and `scraper_tier2.py` with no shared constant/enum** — `maybe-false` — rejected. No current consumer branches on this string in a way that would diverge; if it ever drifted, impact would only be `low`.
- **Claim: `scraper_tier2.py`'s `SourceFailure(reason="invalid_url")` branch is now dead code** — `false` — rejected. Refuted: that branch remains live and tested via direct `ProductSource` usage — Story 1.1's own `test_fetch_returns_source_failure_for_non_amazon_url` exercises it today and still passes. It's only unreached along the specific path where a caller goes through `resolve_product_facts()` first, not dead in the codebase.
- **`canonicalize(url)` runs twice on every successful request** (once in `orchestrator.py` for its exception side-effect, once again inside `scraper_tier2.py`'s `parse_product_facts`) — `low` — rejected. Real but harmless (deterministic, cheap regex, no wrong output); the only real fix would mean changing `ProductSource.fetch()`'s AD-3 signature to accept a pre-resolved id, a disproportionate architecture change for a negligible, non-functional cost.

## Design Notes

- `InsufficientDataResult` is kept distinct from `SourceFailure` even though their fields overlap: `SourceFailure` is `scraper_tier2.py`'s internal, per-tier signal (AD-3); `InsufficientDataResult` is the FR-3-level outcome a future API/UI will actually render instead of a Verdict. Collapsing them into one type would couple the eventual frontend contract to the scraper's internal vocabulary.
- `resolve_product_facts()` is the first code in `pipeline/orchestrator.py` — intentionally minimal (one function) rather than building out job/queue/SSE machinery now, since that belongs to Story 1.9 (AD-10); AD-11 lets that story extend this same file in place.
- "Never reaches LLM synthesis" (the AC's exact wording) is satisfied structurally rather than by an explicit guard: no synthesis module exists yet, and this function contains no call to one.

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing Story 1.1 tests plus the new orchestrator tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors
