---
title: 'See progress instead of a frozen page'
type: 'feature'
created: '2026-10-27'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '948f4fd111b0fc911cf8940cc621c627ab61fa64'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.8's `/` route blocks silently for the full ~20-30s pipeline run -- the user has no way to tell the page is working rather than stuck.

**Approach:** Add a per-job `asyncio.Queue`-backed event stream: `GET /jobs?url=...` creates a job and schedules `produce_verdict()` as a background task; `GET /jobs/{job_id}/events` streams one SSE event per stage transition, then one final event carrying the Verdict/InsufficientDataResult, then closes. Each existing pipeline function gains an optional `progress` parameter (a `ProgressPublisher`, defaulting to a no-op) that it calls on entry -- additive, so every existing call site and test keeps working unchanged. The existing `/` route and its form-based flow (Story 1.8) are untouched and remain the no-JS fallback; the page's form is progressively enhanced with JS to use the job/SSE flow when available.

## Boundaries & Constraints

**Always:**
- `progress: ProgressPublisher | None = None` is added to `resolve_product_facts()`, `assemble_evidence_bundle()`, `synthesize_verdict()`, and `produce_verdict()`; each publishes its own stage name on entry when a publisher is given, and is a complete no-op (publishes nothing) when `progress` is `None` -- existing callers/tests that don't pass it are unaffected.
- A publisher never raises and never blocks pipeline execution on a slow/stuck consumer (AD-4, AD-9) -- publishing is a fire-and-forget `put` onto an in-memory `asyncio.Queue`.
- `GET /jobs/{job_id}/events` streams SSE events in order: zero or more `event: stage` events, then exactly one `event: result` event carrying the final `Verdict`/`InsufficientDataResult` (plus the same `result_kind` classification `/` already computes), then the stream closes.
- The job store is in-memory, keyed by a random UUID; no persistence, no cross-process sharing, no expiry/cleanup in this story.
- The existing `/` route, its template rendering, and its own tests (Story 1.8) are not modified in behavior -- it remains a fully working, JS-free fallback.
- Route/job logic is tested via FastAPI's `TestClient` with stub `ProductSource`/`LLMClient` dependency overrides -- no live network/API calls, same convention as every prior story.

**Never:**
- No caching, job expiry, or multi-process job sharing -- that is Epic 4's job or a future chore.
- No changes to `compute_confidence()`, `Verdict`, `EvidenceBundle`, citation resolution, or any Story 1.1-1.7 business logic -- only an additive progress hook.
- No authentication or per-user job isolation beyond an unguessable random job ID -- this app has no login system.
- No automated test for the new client-side JS itself (no browser/JS runtime in this test environment) -- only the server-side SSE endpoint is tested.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Job created and pipeline succeeds | Valid URL submitted to `GET /jobs?url=...` | A `job_id` is returned; `GET /jobs/{job_id}/events` streams stage events then a `result` event carrying a `Verdict`, then closes | N/A |
| Job created and pipeline resolves to insufficient data | Invalid/non-Amazon URL, or a pipeline-stage failure | Same stream shape; the `result` event carries `InsufficientDataResult` instead | N/A |
| Unknown job ID | `GET /jobs/{bad_id}/events` | A clear 404, not a hanging connection | N/A |
| No `url` param to `/jobs` | `GET /jobs` with no `url` | A clear 4xx, no job created | N/A |
| Progress publisher given a no-op default | Any existing call to `resolve_product_facts()`/`assemble_evidence_bundle()`/`synthesize_verdict()`/`produce_verdict()` with no `progress` argument | Behaves exactly as before this story -- no event published, no error | N/A |

</frozen-after-approval>

## Code Map

- `app/pipeline/progress.py` -- new (core/shared, AD-10): `ProgressPublisher` Protocol (`async def publish(self, stage: str) -> None`); `NullProgressPublisher` (no-op, used as the implicit default); `QueueProgressPublisher` (wraps an `asyncio.Queue`, `publish()` puts `{"stage": stage}` onto it)
- `app/pipeline/orchestrator.py` -- edit in place: add `progress: ProgressPublisher | None = None` to `resolve_product_facts()` (publishes `"resolving_product"`), `assemble_evidence_bundle()` (threads `progress` into `resolve_product_facts()`; publishes `"sampling_reviews"` before `fetch_reviews`, `"finding_alternatives"` before `find_candidate_alternatives`), `produce_verdict()` (threads `progress` into both sub-calls)
- `app/pipeline/synthesis.py` -- edit in place: add `progress: ProgressPublisher | None = None` to `synthesize_verdict()` (publishes `"synthesizing_verdict"` on entry)
- `app/jobs.py` -- new: in-memory `JobStore` (dict of `job_id -> asyncio.Queue`); `create_job() -> str`; `get_job_queue(job_id: str) -> asyncio.Queue | None`; `run_job(job_id, url, source, llm) -> None` (builds a `QueueProgressPublisher` for the job's queue, calls `produce_verdict(url, source, llm, progress=publisher)`, enqueues the final `{"event": "result", ...}` payload including `result_kind`, then enqueues a close sentinel)
- `app/main.py` -- edit in place: add `GET /jobs` (query param `url`, creates a job via `create_job()`, schedules `run_job()` via `asyncio.create_task`, returns `{"job_id": ...}` JSON; a missing `url` is a 422/400); `GET /jobs/{job_id}/events` (a `StreamingResponse`, `media_type="text/event-stream"`, reading the job's queue until the close sentinel, formatting each item as an SSE `event:`/`data:` pair; an unknown `job_id` is a 404)
- `app/templates/index.html` -- edit: add a `<div id="progress">` and a `<div id="result-mount">` placeholder, plus `<script src="/static/app.js" defer></script>`; the form keeps its existing `action="/"`/`method="get"` for the no-JS fallback
- `app/static/app.js` -- new: on form submit, if JS runs, `preventDefault()`, `fetch` `/jobs?url=...` for a `job_id`, open `new EventSource('/jobs/' + job_id + '/events')`, update `#progress` on each `stage` event, and on the `result` event render the verdict/insufficient-data result into `#result-mount` (mirroring `index.html`'s existing field choices: label, confidence + evidence basis, pros/cons + citations, alternatives) before closing
- `tests/pipeline/test_progress.py` -- new: covers `NullProgressPublisher`/`QueueProgressPublisher`
- `tests/pipeline/test_orchestrator.py` / `tests/pipeline/test_synthesis.py` -- edit: add a stub publisher and assert each function publishes its documented stage name, and that omitting `progress` still works exactly as before
- `tests/test_jobs.py` -- new: covers `create_job()`/`run_job()`/`get_job_queue()` with stub `ProductSource`/`LLMClient`
- `tests/test_main.py` -- edit: add `GET /jobs` and `GET /jobs/{job_id}/events` tests (stage events in order, final `result` event, stream closes, unknown job 404, missing `url` 4xx) via `TestClient`

## Tasks & Acceptance

**Execution:**
- [x] `app/pipeline/progress.py` -- add `ProgressPublisher`/`NullProgressPublisher`/`QueueProgressPublisher` -- the additive progress-publishing contract
- [x] `app/pipeline/orchestrator.py` -- thread `progress` through `resolve_product_facts()`/`assemble_evidence_bundle()`/`produce_verdict()` -- publishes stage transitions
- [x] `app/pipeline/synthesis.py` -- thread `progress` through `synthesize_verdict()` -- publishes the synthesis stage
- [x] `app/jobs.py` -- add the in-memory job store and `run_job()` -- the background-task/event-queue wiring
- [x] `app/main.py` -- add `GET /jobs` and `GET /jobs/{job_id}/events` -- the job-creation and SSE endpoints
- [x] `app/templates/index.html` -- add progress/result mount points and the script tag -- keeps the no-JS fallback working
- [x] `app/static/app.js` -- add the `EventSource`-driven progressive enhancement
- [x] `tests/pipeline/test_progress.py` -- cover the publisher types
- [x] `tests/pipeline/test_orchestrator.py` / `tests/pipeline/test_synthesis.py` -- cover stage-name publishing and the no-`progress`-passed case
- [x] `tests/test_jobs.py` -- cover job creation/running with stubs
- [x] `tests/test_main.py` -- cover the new routes' I/O Matrix rows

**Acceptance Criteria:**
- Given a URL submitted to `GET /jobs?url=...`, when processing begins, then a `job_id` is returned and the first SSE event arrives at `GET /jobs/{job_id}/events` within a few seconds (i.e., before the pipeline itself finishes).
- Given each pipeline stage starts, when it publishes, then a corresponding SSE `stage` event is observable on the job's event stream, in the order the stages actually ran.
- Given the pipeline resolves (to a `Verdict` or an `InsufficientDataResult`), when the final event is sent, then the stream closes immediately after.
- Given an existing caller does not pass `progress`, when any of the four pipeline functions run, then behavior is identical to before this story.

## Implementation Notes

- `app/jobs.py::run_job()` needs the `result_kind()` classifier (per this story's Design Notes). Initially resolved with a deferred import inside `run_job()`'s body to dodge a circular import with `app.main`; the review patch round below moved the classifier into its own `app/pipeline/result_kind.py` module so both `app/main.py` and `app/jobs.py` import it normally.
- Verified live (not just via `TestClient`): started `uvicorn app.main:app`, confirmed `GET /jobs?url=...` returns a `job_id` immediately, `GET /jobs/{job_id}/events` streams valid `event: stage`/`event: result` SSE framing and closes, `GET /jobs/{bad_id}/events` returns 404, and `GET /jobs` with no `url` returns 422. The one `stage` event seen in that manual run was `resolving_product`, followed immediately by an `insufficient_data` result -- Playwright's browser binaries aren't installed in this dev environment, so `ScraperTier2Source.fetch()` degraded exactly as AD-4/AD-9 intend rather than erroring.
- **Review patch round:** all 11 `patch`-routed findings were fixed: a job's `_jobs` entry is now removed once its SSE stream is fully drained (fixing both the second-connection hang and the unbounded-growth concern in one change); the background task from `asyncio.create_task()` is now held in a module-level set with a done-callback, preventing mid-run garbage collection; `run_job()`'s result/`CLOSE_SENTINEL` enqueue is now wrapped so the sentinel is guaranteed even if building the result payload fails; a new test exercises the unexpected-exception recovery path end-to-end; `result_kind()`/`LOW_CONFIDENCE_THRESHOLD` moved to their own module, removing the deferred-import circular-dependency workaround; the SSE response now carries anti-buffering headers; `app.js` now clears any stale server-rendered `.result` section and guards against overlapping submissions by closing the previous `EventSource` first; `onerror` no longer kills the connection on a transient blip, letting native auto-reconnect proceed; `#progress` now has `aria-live="polite"`; and a test's assertions now match its own name. One finding was deferred (no SSE heartbeat/keep-alive, relevant only once a real reverse-proxy deployment exists). Three findings were rejected (a disproportionate broadcast-architecture fix for a scenario this app's fresh-job-id-per-submission design doesn't naturally produce; intentional forward-compatible dead code; a speculative future field-rename risk against an already-accepted lack of JS test infrastructure). Full suite is 176/176 passing, `ruff check` clean.
- `tests/test_main.py`'s two new `/jobs` + `/jobs/{job_id}/events` tests use `with _client(...) as client:` rather than a bare call -- `TestClient` opens a fresh blocking portal (event loop) per request unless used as a context manager, and both requests must share the same loop for the `asyncio.create_task()` scheduled by `GET /jobs` to still be running when `GET /jobs/{job_id}/events` awaits its queue.

## Spec Change Log

## Review Triage Log

- **A second connection to an already-finished job hangs forever, and `_jobs` grows without bound** (`app/jobs.py`, `app/main.py`) — `high` — `patch`. Verified: `_jobs` never removes an entry, so `get_job_queue()` keeps returning the same, already-drained queue after `CLOSE_SENTINEL` has been read once; a later request for that same valid `job_id` (a page reload, or EventSource's own built-in auto-reconnect after a transient drop reconnecting to the same URL) calls `await queue.get()` on a queue nothing will ever fill again -- an indefinitely hanging HTTP connection, the exact failure mode this story's I/O Matrix requires never happen (that row names only an *unknown* id, but the same hang applies to a known-but-exhausted one). Real and likely: EventSource's default reconnect behavior alone can trigger it. Fix: delete the job's `_jobs` entry once `_stream_job_events()` has read through `CLOSE_SENTINEL`; a later request for that `job_id` then correctly falls into the existing 404 path. This single fix also resolves the separately-flagged unbounded-growth concern.
- **`asyncio.create_task(run_job(...))` discards its return value** (`app/main.py`) — `medium` — `patch`. Verified against Python's own documented behavior: with no other strong reference, the event loop holds only a weak one, so the task can be garbage-collected mid-run, silently killing the job. Standard, well-known fix: store it in a module-level set with a done-callback to discard it on completion.
- **`run_job()`'s `try/except` only wraps the `produce_verdict()` call, not the result/`CLOSE_SENTINEL` enqueue that follows it** (`app/jobs.py`) — `medium` — `patch`. Verified: `_result_kind()`/`model_dump()`/`put_nowait()` all run after the `try` block exits; today none of them can realistically raise (the queue is unbounded, `result` is always a well-formed `Verdict`/`InsufficientDataResult`), so this isn't currently reachable, but the function's own docstring promises a *broader* guarantee ("any unexpected failure here is caught") than the code delivers -- a real documentation/implementation mismatch at the single choke point responsible for preventing hung SSE connections. Fix: wrap the tail in `try`/`finally` so `CLOSE_SENTINEL` is guaranteed to be enqueued no matter what.
- **`run_job()`'s existing exception-recovery path (around `produce_verdict()`) has zero test coverage** (`tests/test_jobs.py`) — `medium` — `patch` (verification-gap finding, pre-verified). No test constructs a `ProductSource`/`LLMClient` stub that raises, so the `except Exception -> InsufficientDataResult(reason="unexpected_error")` branch -- the thing standing between a real pipeline bug and a permanently hung SSE connection -- is entirely unverified. Fix: add the test the reviewer specified (a raising stub, assert the drained queue ends in a `result`/`unexpected_error` event followed by `CLOSE_SENTINEL`).
- **`app/jobs.py` has to deferred-import `_result_kind` from `app.main` inside `run_job()` to dodge a circular import** — `low` — `patch`. Verified: `app.main` imports `app.jobs` at module scope, and `_result_kind` lives in `app.main`, forcing the reverse import inline. A low-level job runner depending on the top-level app entrypoint is backwards. Fix: move `_result_kind()` (and `_LOW_CONFIDENCE_THRESHOLD`) into a small shared module both files import normally.
- **No anti-buffering headers on the `StreamingResponse`** (`app/main.py`) — `low` — `patch`. Verified absent. A buffering intermediary (nginx's default behavior is the classic case) could hold the whole response instead of flushing each SSE event as produced, defeating the purpose of streaming. Trivial, costless fix (`Cache-Control: no-cache`, `X-Accel-Buffering: no`) with no downside in this project's current no-proxy dev/test setup.
- **The server-rendered `.result` section from a prior full-page `GET /?url=...` is never cleared when `app.js` later intercepts a resubmit** (`app/templates/index.html`, `app/static/app.js`) — `medium` — `patch`. Verified reachable: land on `/?url=X` (server-rendered result present), then resubmit the form on that same loaded page -- JS now intercepts normally, but the old section stays in the DOM alongside the new `#result-mount`, directly undermining this story's "one screen" clarity. Fix: also clear/hide the existing `.result` section in the submit handler.
- **`#progress` has no `aria-live` attribute** (`app/templates/index.html`) — `medium` — `patch`. Verified absent. This story's entire purpose is surfacing live progress instead of a frozen page; without `aria-live`, that's invisible to screen-reader users -- a real, named accessibility gap directly undermining this story's own stated goal for that audience. Trivial fix (`aria-live="polite"`).
- **No guard against overlapping form submissions in `app.js`** — `medium` — `patch`. Verified: resubmitting while a previous job's `EventSource` is still open leaves it running, orphaned; a slower first job's result can arrive after and overwrite a faster second job's already-rendered result. A plausible, common real interaction (impatient resubmission), not a contrived edge case. Fix: track the current `EventSource` in outer scope and `.close()` it before starting a new job.
- **`onerror` unconditionally calls `source.close()`, defeating `EventSource`'s built-in auto-reconnect on any transient network blip** (`app/static/app.js`) — `medium` — `patch`. Verified: closing on every error (not just a terminal one) permanently abandons the progress/result display even though the job keeps running server-side and might have delivered a result the client never sees. Fix: remove the `.close()` call in `onerror` and let the browser's native reconnect proceed; still update the progress text to acknowledge the blip.
- **A test's name promises a check it doesn't perform** (`test_jobs_route_with_no_url_param_is_a_clear_4xx_and_creates_no_job` only asserts the status code, never that no job was created) (`tests/test_main.py`) — `low` — `patch`. Verified. Trivial fix (add the missing assertion).
- **Two concurrent readers on the same job's queue split events instead of each seeing the full stream** (`app/jobs.py`) — `low` — rejected. Real `asyncio.Queue` single-consumer semantics, but this app mints a fresh, unguessable `job_id` per form submission -- there is no natural way for two simultaneous readers to end up on the *same still-active* job without a user deliberately copying the SSE URL across tabs, which isn't how this app is used. A proper fix (broadcast to N subscribers) needs a materially different pub/sub architecture, not a contained patch -- both reject conditions hold.
- **`QueueProgressPublisher`'s `except QueueFull` branch is dead code against today's unbounded production queue** — `low` — rejected. Intentional, forward-compatible defensive coding for a configuration (a bounded queue) that doesn't exist yet but reasonably could; not a live bug, and removing it would be a pure regression in robustness for no benefit.
- **`app.js`'s rendering functions hardcode `Verdict`/`EvidenceBasis`/`Citation` field names with no guard against a future backend rename** — `low` — rejected. Verified the names currently match; this is a speculative, forward-looking developer-time risk, and a proper fix (a JS test runner/browser automation) is new test infrastructure well beyond this story's scope -- already an explicitly-accepted limitation per this spec's own Boundaries ("no browser/JS runtime in this test environment").
- **No SSE heartbeat/keep-alive between stage events** — `maybe-false` — `defer`. Real risk if ever deployed behind a reverse proxy with an idle-connection timeout (a common nginx/ALB default), but this project has no deployment target or proxy configuration yet to validate against, and a proper fix (a timeout-based heartbeat loop in `_stream_job_events()`) is a non-trivial control-flow change, not a one-liner. If true, severity would be `medium` (a killed connection on a slow stage, not data loss -- the job keeps running server-side). Revisit once a real deployment topology is chosen.

## Design Notes

- `GET /jobs` uses GET (not POST) for consistency with this app's existing all-GET routing (Story 1.8's `/`), even though it has a side effect (creating a job and scheduling background work). A REST purist would prefer POST; this project's small, single-user, no-auth scope doesn't need that distinction yet.
- Stage names are coarse (one per existing function-level boundary: resolving the product, sampling reviews, finding alternatives, synthesizing the verdict) rather than one per every internal sub-step (e.g. the two separate LLM calls inside `synthesize_verdict()`), matching the architecture's "each stage publishes its name on entry" language at the level stages already exist in this codebase's pipeline, not a finer-grained breakdown invented for this story.
- The final SSE `result` event carries the already-computed `result_kind` (reusing `main.py`'s existing `_result_kind()` classification) alongside the raw `Verdict`/`InsufficientDataResult` fields, so the confidence-threshold business logic stays server-side and isn't duplicated in `app.js`.
- The job store has no eviction/expiry; a long-running process would accumulate completed jobs' queues in memory indefinitely. Acceptable for v1 (no persistent deployment yet); worth a defer note if review flags it as a real operational concern.
- `app.js` is intentionally not unit-tested here -- there is no browser/JS runtime in this project's test environment (pytest-only), consistent with how `ScraperTier2Source._render()`'s own Playwright calls are never directly unit-tested either, only their pure helper functions. The server-side SSE endpoint it consumes is fully tested via `TestClient`.

## Verification

**Commands:**
- `uv run pytest tests/ -v` -- expected: all existing tests plus the new progress/jobs/SSE tests pass
- `uv run ruff check app/ tests/` -- expected: no lint errors

**Manual checks:**
- Start the dev server (`uv run uvicorn app.main:app`) and, with stub-free real dependencies unavailable in this environment, at minimum confirm `GET /jobs?url=...` returns a `job_id` and `GET /jobs/{job_id}/events` is reachable and streams valid SSE framing.
