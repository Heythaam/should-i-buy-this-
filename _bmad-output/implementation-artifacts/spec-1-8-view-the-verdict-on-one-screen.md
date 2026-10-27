---
title: 'View the verdict on one screen'
type: 'feature'
created: '2026-10-27'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '69e1d6854bcede58653c67feddec53ee48869a5b'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `produce_verdict()` (Story 1.7) can compute a complete end-to-end result, but nothing yet lets a user actually paste a URL and see it -- there is no web app at all.

**Approach:** Add a minimal FastAPI app with one route that accepts a URL, runs `produce_verdict()` against real `ScraperTier2Source`/`OpenAIClient` instances, and renders label, confidence (with evidence basis), pros, cons, alternatives, and evidence trail together in one Jinja2 template. No SSE/progress streaming yet -- the request simply blocks until the pipeline resolves (Story 1.9's job). An insufficient-data result and a below-threshold-confidence `Verdict` are both styled distinctly from a normal confident `Verdict`.

## Boundaries & Constraints

**Always:**
- The `/` route accepts an optional `url` query param; when present, it runs the full `produce_verdict()` pipeline and renders the result in the same page/template as the form, never a separate navigation.
- A `Verdict` result's label, confidence (paired with its evidence basis in plain language), pros, cons, alternatives, and evidence trail (each pro/con's citation) all render together in one result section.
- An `InsufficientDataResult`, and a `Verdict` whose confidence falls below a defined low-confidence threshold, are both visually distinguishable from a normal confident `Verdict` via a distinct CSS class -- never styled identically.
- `ScraperTier2Source`/`OpenAIClient` instances used by the route are constructed from `Settings()`, the same NFR-1-compliant pattern as every prior story.
- Route logic is tested via FastAPI's `TestClient` with `ProductSource`/`LLMClient` dependency overrides (stubs) -- no live network/API calls in tests, same convention as every prior story.

**Never:**
- No SSE, job queue, or progress streaming in this story -- that is Story 1.9's job; a request simply blocks until `produce_verdict()` resolves.
- No changes to `produce_verdict()`, `EvidenceBundle`, `Verdict`, or any Story 1.1-1.7 function/type.
- No separate routes/pages per result kind -- confident, low-confidence, and insufficient-data all render through the same template with different styling, not different URLs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| No URL submitted yet | `GET /` with no `url` param | Renders the form only; no result section | N/A |
| Confident Verdict produced | Valid URL; `produce_verdict()` returns a `Verdict` with confidence at/above the threshold | Result section shows label/confidence/pros/cons/alternatives/evidence trail with "confident" styling | N/A |
| Low-confidence Verdict produced | Valid URL; `Verdict.confidence` below the threshold | Same fields shown, but with "low confidence" styling, visually distinct from confident | N/A |
| Insufficient data | `produce_verdict()` returns `InsufficientDataResult` | Result section shows the reason/detail with "insufficient data" styling, distinct from both Verdict stylings | N/A |
| Non-Amazon or malformed URL submitted | `url` doesn't canonicalize | Same insufficient-data rendering as any other `InsufficientDataResult` (`reason="invalid_url"`) | N/A |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- edit: add `fastapi`, `jinja2`, `uvicorn` dependencies
- `app/main.py` -- new: FastAPI app instance; `get_product_source() -> ProductSource` / `get_llm_client() -> LLMClient` dependency providers (constructed from `Settings()`); `GET /` route accepting an optional `url` query param, calling `produce_verdict()` when present, computing a `result_kind` (`"confident"` | `"low_confidence"` | `"insufficient_data"`) from the result, and rendering `templates/index.html`
- `app/templates/index.html` -- new: Jinja2 template -- the URL-paste form, plus (when a result is present) one result section rendering label/confidence+evidence basis/pros+citations/cons+citations/alternatives, with `class="result result--{{ result_kind }}"` driving the visual distinction
- `app/static/style.css` -- new: minimal styling, including visibly distinct treatments for `.result--confident`, `.result--low_confidence`, `.result--insufficient_data`
- `tests/test_main.py` -- new: `fastapi.testclient.TestClient` tests covering the I/O Matrix, using stub `ProductSource`/`LLMClient` via `app.dependency_overrides` -- no live network/API calls

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- add `fastapi`/`jinja2`/`uvicorn` dependencies
- [x] `app/main.py` -- add the FastAPI app, dependency providers, and `GET /` route -- the first entry point into the v1 pipeline
- [x] `app/templates/index.html` -- add the form + conditional result section template
- [x] `app/static/style.css` -- add styling with three visually distinct result-kind classes
- [x] `tests/test_main.py` -- cover the I/O Matrix with `TestClient` + stub dependency overrides -- proves the rendering/styling guarantees

**Acceptance Criteria:**
- Given a completed Verdict, when viewed, then label, confidence (with its evidence basis), pros, cons, alternatives, and evidence trail all appear together in one result section.
- Given an insufficient-data result or a Verdict below the low-confidence threshold, when viewed, then it renders with a visually distinct style (a different CSS class) from a normal confident Verdict.
- Given no URL has been submitted, when the page loads, then only the form is shown, with no result section.

## Implementation Notes

- Added a minimal FastAPI app (`app/main.py`) with one `GET /` route, `get_product_source()`/`get_llm_client()` dependency providers (overridable in tests via `app.dependency_overrides`), one Jinja2 template (`templates/index.html`) rendering the form plus a conditional result section, and minimal styling (`static/style.css`) with three visually distinct result-kind classes.
- `_result_kind()` classifies a result into `"confident"` / `"low_confidence"` / `"insufficient_data"` using a `_LOW_CONFIDENCE_THRESHOLD = 0.5` constant, this story's own UI-layer calibration (not derived from `compute_confidence()`'s internal weights).
- No live end-to-end verification was possible (no real scraper network access or OpenAI credentials in this environment); route/template/styling logic was verified against stub `ProductSource`/`LLMClient` dependencies, and the form-only page load was checked by starting the dev server and inspecting the HTTP response directly.
- **Review patch round:** all 12 `patch`-routed findings were fixed: an unhandled-exception guard around `produce_verdict()` now renders the same insufficient-data styling instead of a bare 500; `Settings()` and both real port instances are now built once at module import time instead of per-request (also closing the "a misconfigured env var crashes every request" gap); the confident test's claim text and citation quote are now distinct with a dedicated citation assertion; a real alternative now exercises the alternatives-list template branch; the insufficient-data/confident/low-confidence tests now assert `detail`/`source_tier`/`is_low_signal`/`alternatives_count`/the low-confidence flag text; a viewport meta tag and a `required` input attribute were added; whitespace-only-URL and real-dependency-provider tests were added; alternative prices now format to two decimals; and the confidence-threshold boundary choice is now documented as moot in practice. One finding was deferred (no server-side timeout on the overall blocking request, extending the already-twice-deferred Story 1.2/1.6 aggregate-timeout gap). Two findings were rejected (per-request port-object construction's performance framing was overstated given Playwright's browser launch is already scoped per-call regardless; a missing favicon is benign, standard browser behavior). One follow-up `ruff` nit (an unused `noqa` directive left over from the exception-guard patch) was fixed directly. Full suite is 150/150 passing, `ruff check` clean.

## Spec Change Log

## Review Triage Log

- **No `try`/`except` around `await produce_verdict(...)` in the `/` route** (`app/main.py`) — `medium` — `patch`. Verified: any exception not already converted to a typed failure deep in the pipeline (an unanticipated bug, a `BaseException` not caught by an inner `except Exception`) would bubble up as a bare Starlette 500 page, breaking the "one screen" guarantee this whole story is built around and the project's standing "never show a raw failure" ethos (AD-4). This is the first story with an actual HTTP boundary, so it's a genuinely new risk surface, not a pre-existing one. Fix: wrap the call and render the same insufficient-data-style section on an unexpected exception.
- **`get_product_source()`/`get_llm_client()` construct a fresh `Settings()` on every request via `Depends`, so a misconfigured env var (e.g. a malformed `SCRAPER_PROXY_URL`) would crash *every* request -- including a plain form-only `GET /` with no `url`** — `medium` — `patch`. Verified: `Settings._validate_scraper_proxy_url` can raise, and FastAPI resolves `Depends` providers unconditionally regardless of whether the route body ever needs them. Fix: construct `Settings()` (and the two real port instances) once at module scope rather than per-request -- this also incidentally avoids rebuilding lightweight wrapper objects on every request, though that alone wasn't the primary justification (see rejected finding below).
- **Pro/con citation ("evidence trail") rendering is unverified** -- the confident test's claim text and citation quote happen to be the identical string, so breaking `index.html`'s citation-quote interpolation wouldn't fail any test (`tests/test_main.py`) — `medium` — `patch` (verification-gap finding, pre-verified). This is specifically about proving the "evidence trail" acceptance criterion, one of this story's explicitly named ACs. Fix: give the confident test's claim text and citation quote distinct values (as the low-confidence test already does) and assert the citation's quote/source_type text renders.
- **The alternatives-list template branch is never executed by any test** -- every stub source in `tests/test_main.py` omits `alternatives`, defaulting to `[]` (`app/templates/index.html`) — `medium` — `patch` (verification-gap finding, pre-verified). Proving "alternatives" render is explicitly one of this story's named ACs; the loop body is currently exercised by zero tests. Fix: extend one test with a non-empty `alternatives` list and assert the title/price render.
- **Several result-section fields render with no assertion checking their content** (`result.detail`, `result.source_tier.value` in the insufficient-data branch; `is_low_signal`, `alternatives_count`, `source_tier`, and the low-confidence-flag span in the confidence paragraph) — `medium` — `patch`. The verification-gap layer filed this as `defer`, reasoning the CSS-class checks already cover the core "visually distinct" AC; overriding that here, since the fix is trivial (the fixtures already carry the right data, these are additive assertions on tests that already run) and the gap is caused by this story, not pre-existing -- that combination fits `patch`, not `defer`, under this build's own routing rules. Fix: add the missing assertions to the existing three tests.
- **No `<meta name="viewport">` tag** (`app/templates/index.html`) — `low` — `patch`. Verified absent; the `max-width: 42rem` layout would render zoomed-out on mobile. Trivial one-line fix.
- **The URL `<input>` has no `required` attribute** (`app/templates/index.html`) — `low` — `patch`. Verified. Server-side handling of a malformed/empty URL is already correct and tested; this is a cheap client-side UX nicety that saves an obviously-wrong round trip.
- **No test exercises a whitespace-only `url` (e.g. `" "`)** (`tests/test_main.py`) — `low` — `patch`. Verified: `if url:` treats a non-empty whitespace string as truthy, so it already flows correctly into the existing, already-tested `canonicalize()` failure path (Story 1.1) -- this is purely an integration-level coverage gap for an already-correct lower-layer behavior, same category as prior stories' analogous gaps. Trivial fix (one test).
- **No test asserts the real, un-overridden `get_product_source`/`get_llm_client` actually build `ScraperTier2Source(Settings())`/`OpenAIClient(Settings())`** (`tests/test_main.py`) — `low` — `patch`. Verified: every test replaces both via `app.dependency_overrides`, so a wiring mistake in the real providers would pass the whole suite silently. Trivial fix (call them directly and assert the returned type).
- **Alternative prices render unformatted** (e.g. `$39.9` instead of `$39.90`) (`app/templates/index.html`) — `low` — `patch`. Verified. Trivial fix (a two-decimal format filter).
- **`_result_kind()`'s `confidence < threshold` boundary choice (vs. `<=`) is undocumented** (`app/main.py`) — `low` — `patch`. Verified unreachable as an exact tie in practice -- `compute_confidence()`'s components can only sum to multiples of `0.015` plus a `0.4`/`0.1` tier offset, which mathematically never lands on exactly `0.5` (confirmed by enumeration: e.g. `0.4 + 0 + depth` skips from `0.49` to `0.505`). Not a live bug, but worth a one-line comment so a future reader doesn't have to re-derive this. Trivial fix.
- **A fresh `ScraperTier2Source`/`OpenAIClient` is constructed on every request instead of being reused across requests** — `low` — rejected. The actually-expensive resource (Playwright's browser launch) is already scoped per-scrape-call inside `_render()` regardless of this wrapper object's lifetime -- pre-existing Story 1.1 behavior, not made worse by per-request construction here. The marginal object-allocation overhead this finding describes isn't a meaningful problem yet; persistent client/connection lifecycle management belongs more naturally to Epic 4's caching work.
- **No favicon, causing a routine `/favicon.ico` 404 on every page load** — `low` — rejected. Completely benign, standard browser behavior with no functional or user-visible impact; outside this story's "view the verdict" scope.
- **No server-side timeout on the overall blocking pipeline call** — `maybe-false` — `defer`. Extends the already-twice-deferred Story 1.2/1.6 finding (no aggregate timeout across sequential stage calls) one level further, to the HTTP route itself. Each underlying call already bounds itself; the aggregate worst case is large but finite. If true, severity would be `medium` (a slow-but-not-hanging request, not an indefinite stall). Logged to `deferred-work.md`.

## Design Notes

- The low-confidence styling threshold (`_LOW_CONFIDENCE_THRESHOLD` in `main.py`) is this story's own UI-layer calibration, separate from `compute_confidence()`'s internal weights (Story 1.7) -- neither the PRD nor the architecture names an exact cutoff for "visually distinguish a low-confidence result," only that one must exist (FR-13/NFR-8). A future story can retune it without touching `compute_confidence()`.
- One combined template rather than a separate result page: the AC's "one screen" language is read literally -- the form and the result (when present) share one `GET /` route and one template, never a redirect or a second URL.
- `app/main.py`'s dependency providers (`get_product_source`/`get_llm_client`) exist specifically so tests can override them via `app.dependency_overrides` with stubs, mirroring this project's established port-based testing convention (`ProductSource`/`LLMClient` stubs) rather than monkeypatching module-level globals.
- No live end-to-end verification against the real scraper/OpenAI API is possible in this environment (no real network/API credentials); this story's tests exercise the route/template/styling logic against stub dependencies, and the actual page load (form-only state) is checked by starting the dev server, consistent with "start the dev server and use the feature in a browser" for UI changes.

## Verification

**Commands:**
- `uv run pytest tests/ -v` -- expected: all existing tests plus the new route/template tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors

**Manual checks:**
- Start the dev server (`uv run uvicorn app.main:app`) and load `/` in a browser: the form renders with no result section until a URL is submitted.
