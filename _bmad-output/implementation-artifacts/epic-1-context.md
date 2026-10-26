# Epic 1 Context: Core Verdict Loop

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Let the user paste an Amazon product URL and receive a grounded Buy/Skip/Wait verdict — with a Confidence Score, pros/cons, an Evidence Trail, and (on a Skip/Wait) 2-3 comparable alternatives — all on one screen, with visible progress while it computes. This is the complete, standalone end-to-end loop built from scraped product facts and a representative review sample alone: no Reddit cross-check and no multi-persona reasoning yet (those are real enhancements added in later epics, not prerequisites for this to be genuinely useful). Every other epic builds on top of this loop.

## Stories

- Story 1.1: Resolve a product URL to a Canonical Product
- Story 1.2: Fail honestly when a page can't be read
- Story 1.3: Sample reviews instead of reading all of them
- Story 1.4: Warn when there isn't enough review signal
- Story 1.5: Surface comparable alternatives
- Story 1.6: Assemble one Evidence Bundle
- Story 1.7: Produce a schema-validated verdict
- Story 1.8: View the verdict on one screen
- Story 1.9: See progress instead of a frozen page

## Requirements & Constraints

- A pasted URL resolves to one stable Canonical Product identity (different URLs/tracking params for the same product → same identity; a color/size variant → that exact variant's data), with title, price, and key specs extracted.
- Extraction tries the most reliable available method first, falls back only when needed, and records which method supplied the data; a lower-reliability extraction visibly lowers the Confidence Score. v1 ships only one scraper-based method plus one degraded fallback — no official product-data API yet.
- An unreadable page (blocked, CAPTCHA, broken URL, unsupported layout, or non-Amazon URL) produces an explicit "insufficient data" result and never reaches LLM synthesis — never a fabricated or partial verdict.
- Review grounding uses a small, bounded, representative sample regardless of total review count, including at least one critical review when critical reviews exist. Too few reviews visibly caps the Confidence Score and states why, rather than being treated as conclusive.
- 2-3 alternatives in the same category and similar price range are surfaced when relevant; if none exist in that band, the verdict is still produced without alternatives rather than failing.
- The verdict is one structured object validated against a fixed schema before being shown; malformed/incomplete model output is auto-repaired (one retry) or rejected, never shown. A "Wait" label reflects inconclusive evidence only, never price-trend reasoning (no price-history data exists in v1).
- The Confidence Score is always computed algorithmically from measurable evidence properties, never produced or self-assessed by the model; identical inputs always yield the identical score, and it is never shown without its evidence basis in plain language (e.g. "based on 23 reviews").
- Every pro/con/claim resolves to a literal, inspectable source citation; an uncited claim is dropped rather than shown.
- The user sees visible progress within a few seconds of submitting a URL — no silent frozen page for the ~20-30s wait — and the final result is visually distinct by kind (confident vs. low-confidence vs. insufficient-data).
- Config/credentials load only from environment variables via one shared `Settings` object, never hardcoded. Every external-dependency call (scraper, LLM) is wrapped with a timeout plus one retry, then degrades to an explicit failure/partial sentinel rather than crashing the request; that sentinel is never silently flattened into "confirmed empty." A correctly low-confidence or insufficient-data result is a success, not a defect to mask.

## Technical Decisions

- **Pipeline (pipes-and-filters):** canonicalize → extract facts → sample reviews → find alternatives → assemble Evidence Bundle → LLM synthesis → compute confidence → return Verdict. One orchestrator sequences stages; each stage is an async function with one typed Pydantic input/output; stages never call each other directly or redefine shared `models/` types locally.
- **Canonical Product id:** one `canonicalize(url) -> CanonicalProductId` function (format `amazon:{ASIN}`); every stage keys off this id, none invent their own.
- **Data Source Port:** one `ProductSource` interface, `fetch(url) -> ProductFacts | SourceFailure`, one implementation per tier. v1 ships only a scraper tier (Playwright + BeautifulSoup) and a degraded tier (URL-slug + search fallback). Any stage needing product-page data (including alternatives) goes through this port, never a custom fetcher.
- **Honest failure:** every stage returns a populated typed result or an explicit typed failure/sentinel, never `None`-as-success. A scraper failure maps directly to the insufficient-data result rather than propagating into Evidence Bundle assembly.
- **Evidence Bundle as sole LLM input:** synthesis's only input is the finalized Evidence Bundle — no raw HTML/text. Fact fields (price, specs) are a distinct, separately-typed section from opinion fields (review excerpts) and pass through to the Verdict unmodified.
- **Confidence outside the LLM:** a deterministic function takes the Evidence Bundle and returns a float in `[0.0, 1.0]`, applied after the model's draft Verdict; any model-produced confidence is discarded. This function never writes prose — the "why" lives in the Verdict's reasoning summary.
- **Verdict schema is the single frontend contract:** one Verdict model for structured-output enforcement, the API response, and UI rendering — defined once, never duplicated. Carries `schema_version`, `confidence`, `evidence_basis` (structured counts), `evidence_trail` (citations that must resolve to real Evidence Bundle items — non-resolving = validation failure), plus label/pros/cons/alternatives/reasoning summary. On validation failure, retry once with the error appended to the prompt; if that also fails, resolve to insufficient-data — never a hand-patched Verdict.
- **Review sampling:** stratified — top 20 by helpfulness + 10 most-critical (1-2 star) + 10 most recent; cluster near-duplicates before sampling; fewer than 10 total reviews triggers the low-signal warning.
- **Alternatives:** same category + price-band matching against structured spec data, via the same Data Source Port — no separate mechanism.
- **LLM cost control:** synthesis uses two calls — a cheaper model for theme clustering, a stronger model for final structured synthesis — both configured independently via `Settings`.
- **Progress reporting:** each stage publishes its name on entry to a per-job queue created on a cache miss; `GET /jobs/{job_id}/events` streams one SSE event per stage transition plus a final event carrying the Verdict (or insufficient-data result), then closes. Applies only on a cache miss.
- **Stack:** Python 3.12+, FastAPI, Pydantic, Playwright + BeautifulSoup, OpenAI SDK with Structured Outputs, Jinja2/HTMX-style UI; no job queue, plain asyncio/BackgroundTasks.
- **Branch ownership:** `scraper` owns canonicalize + source tiers + review sampling; `alternatives` owns the alternatives lookup; `llm-synthesis` owns the two-call synthesis step; `confidence-score` owns the pure confidence function; `evidence-trail` is the citation-resolution check inside synthesis's output validation, not a separate module; `ui` owns templates/static and routes other than the SSE endpoint; core/shared (any branch may edit in place, never fork) owns the orchestrator, Evidence Bundle assembly, and all `models/` types.

## UX & Interaction Patterns

- No formal UX design contract exists; look and interaction details are left to implementation within these constraints.
- Result view: verdict label, Confidence Score (always paired with its evidence basis, never a bare number), pros, cons, alternatives, and Evidence Trail appear together on one screen.
- "Insufficient data" and low-confidence results are visually distinguishable from a normal confident verdict — never styled identically.
- Progress is delivered via Server-Sent Events consumed with `EventSource`: the UI reflects each stage transition as published, then the stream closes on the final Verdict/insufficient-data event. The user must perceive feedback within a few seconds of submitting; full progressive reveal of every stage's detail is not required.

## Cross-Story Dependencies

- Story 1.6 (Evidence Bundle assembly) depends on the outputs of 1.1 (Canonical Product + facts), 1.3 (review sample), and 1.5 (alternatives); it must preserve any of their degraded/failed states as distinct values rather than flattening them.
- Story 1.2's honest-failure path short-circuits before 1.6/1.7 entirely — a failed extraction must never reach Evidence Bundle assembly or LLM synthesis.
- Story 1.4's low-review warning doesn't produce its own UI path — it feeds into the Confidence Score computed in Story 1.7, which Story 1.8 then renders.
- Story 1.7 depends on a complete Evidence Bundle from 1.6, and its output (or the insufficient-data result) is what 1.8 displays and what 1.9's final SSE event carries.
- Story 1.9's per-stage events depend on whichever stages 1.1, 1.3, 1.5, and 1.7 implement actually publishing stage-transition events to the orchestrator's job queue — this is a shared contract between those stories and the `ui`/core-shared orchestrator work, not something 1.9 can build in isolation.
- Epic 4 (caching, not in this epic's scope) determines whether a job/SSE connection is created at all on a repeat request; Story 1.9's SSE flow assumes the cache-miss path and should not assume every request creates a job.
