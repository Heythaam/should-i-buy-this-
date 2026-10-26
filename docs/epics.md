---
stepsCompleted: [1, 2, 3-epic1, 3-epic2, 3-epic3, 3-epic4]
inputDocuments: ['docs/prds/prd-should-i-buy-this-2026-10-26/prd.md', 'docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', 'brainstorm-intent.md', 'docs/prds/prd-should-i-buy-this-2026-10-26/addendum.md']
---

# Should I Buy This? - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Should I Buy This?, decomposing the requirements from the PRD and Architecture Spine (plus the brainstorm intent doc and PRD addendum as supporting technical context) into implementable stories, organized around the 8 feature branches plus shared core.

## Requirements Inventory

### Functional Requirements

```
FR-1: The system takes a pasted Amazon product URL and resolves it to a single Canonical Product, extracting title, price, and key specs - the same product reached via two different URLs resolves to the same Canonical Product, and a specific variant (color/size) resolves that exact variant's data.
FR-2: The system attempts extraction via the most reliable available Source Tier first, falling back to lower tiers only when needed, and records which tier was used on every Evidence Bundle. A lower-tier extraction visibly reduces the Confidence Score.
FR-3: When a product page cannot be extracted (blocked, CAPTCHA, broken URL, unsupported layout), the system returns an explicit "insufficient data" result rather than a fabricated or partial Verdict.
FR-4: The system selects a bounded, representative sample of a product's reviews (spanning helpful, critical, and recent) rather than processing the full review corpus - sample size stays bounded regardless of total review count, and includes at least one critical review when they exist.
FR-5: When a product has too few reviews to support a confident read, the system flags this explicitly and caps the Confidence Score rather than treating a thin sample as conclusive.
FR-6: The system searches Reddit for discussion specifically about the Canonical Product (not just the brand), excludes low-quality/off-topic matches, and degrades gracefully (reduced-confidence, Reddit-free Evidence Bundle) rather than failing the whole request when Reddit is unavailable or rate-limited.
FR-7: The system compares sentiment found on Reddit against sentiment from the product's reviews and flags a meaningful divergence (e.g. reviews much more positive than Reddit) on the Verdict.
FR-8: The system finds 2-3 alternative products in the same category and a similar price range as the original product.
FR-9: The system produces a Verdict as a single structured object validated against a fixed schema before being shown to the user; malformed/incomplete LLM output is auto-repaired or rejected, never shown. A "Wait" label means the evidence is inconclusive only - in v1 it is never backed by price-history reasoning (deferred to v2).
FR-10: The Verdict is derived from 2-3 distinct Reasoning Personas assessing the same Evidence Bundle; when personas disagree on the label, that disagreement is surfaced to the user rather than silently resolved.
FR-11: The Confidence Score is computed from measurable properties of the Evidence Bundle (review volume, Source Tier, Reddit corroboration, etc.) and is never generated or self-assessed by the LLM; identical inputs always produce the identical score.
FR-12: Every factual claim and pro/con in the Verdict links back to a literal source (a specific review excerpt or Reddit quote) the user can inspect; the Verdict always states its evidence basis in plain terms (e.g. "based on 23 reviews and 4 Reddit threads") alongside the Confidence Score.
FR-13: A completed Evidence Bundle and Verdict for a Canonical Product are cached and reused for a bounded time window instead of being recomputed on every request; every cached Verdict carries a timestamp and indicates whether it has changed since the user's last visit.
FR-14: Concurrent requests for the same Canonical Product share a single evidence-gathering pass rather than each independently re-running the pipeline.
FR-15: The user can paste an Amazon product URL into a web form and view the resulting Verdict - label, Confidence Score, pros/cons, alternatives, and Evidence Trail - together on one screen once processing completes; an "insufficient data" or low-confidence result is visually distinguishable from a normal confident Verdict.
FR-16: While a request is being processed, the user has visible indication of progress rather than a silent frozen page for the full duration.
```

### NonFunctional Requirements

```
NFR-1 (Secrets/Security): The OpenAI API key and Reddit/PRAW client id+secret are environment variables only, loaded through a single Settings object - never hard-coded, never logged, never committed. `.env` is in `.gitignore` from the first commit (non-negotiable on a public MIT-licensed repo).
NFR-2 (Reliability/Graceful degradation): Every call to an external dependency (Reddit via PRAW, the Amazon scraper, the OpenAI API) is wrapped with a timeout plus one retry, then degrades to an explicit empty/partial/failure result - none may raise an unhandled exception out of its stage or crash the request.
NFR-3 (Data integrity/No fabrication): No stage may return fabricated or partially-invented data disguised as success. A stage's failure/degraded sentinel must be preserved as a distinct value all the way through Evidence Bundle assembly, never silently flattened to "confirmed empty."
NFR-4 (Observability): Structured, per-stage-module logging (JSON output). The scraper additionally logs field-level null-rates per extraction and logs a WARNING when null-rates spike (the signal a site redesign broke it).
NFR-5 (Performance/UX, informal target): A typical request completes, before the user checks out, within a wait time they are willing to tolerate, without feeling broken or stalled (no hard numeric target set - PRD Open Question remains); the user must see feedback that a request is in progress within a few seconds of submitting a URL.
NFR-6 (Auth posture): No multi-user accounts, authentication, or sessions anywhere in v1 - single local user only, running on their own machine.
NFR-7 (Honesty over confident-looking output): The system must not be tuned to always produce a confident Verdict - a correctly low-confidence or "insufficient data" result is success, not failure, and must never be visually dressed up to look the same as a confident one.
NFR-8 (Confidence transparency): The Confidence Score is never shown alone - it is always paired with its evidence basis (review count, Reddit thread count) in plain language, and is understood as a relative signal, not a calibrated probability.
```

### Additional Requirements

```
- No starter template specified in Architecture - the project is built from scratch (plain FastAPI + Python project layout), not scaffolded from a generator.
- Stack (Architecture Spine Stack table, each version flagged with a confidence level to re-verify at setup time since several move fast): Python 3.12+, FastAPI >=0.115, Pydantic ~=2.13, Uvicorn >=0.47, Playwright (Python) ~=1.62, beautifulsoup4 >=4.12, praw >=7.7, openai Python SDK (latest, Structured Outputs support required), aiosqlite ~=0.22, pytest >=9.0, ruff ~=0.16, GitHub Actions actions/checkout v7 and actions/setup-python v7.
- Deployment & environments: local-only in v1, no staging/production hosting; CI runs only in ephemeral GitHub Actions runners, no deployment target exists.
- CI/CD: a GitHub Actions workflow (.github/workflows/ci.yml) triggered on pull_request targeting main and push to main, with three jobs - lint (ruff check), test (pytest), smoke (FastAPI TestClient boots the app and hits GET /health). Recommended repo setting: branch protection on main requiring these checks, squash-merge enabled.
- Persistent storage: SQLite via aiosqlite, not Postgres/Redis - one table for the Evidence Bundle/Verdict cache keyed by Canonical Product Id with a TTL timestamp (~48h default), one table for job status.
- No external job queue (no Celery/ARQ) - a single orchestrator run via FastAPI BackgroundTasks/asyncio.create_task.
- Data Source Port: a ProductSource interface (fetch(url) -> ProductFacts | SourceFailure) with one implementation per Source Tier. v1 ships only Tier 2 (Playwright + BeautifulSoup scraper) and Tier 3 (URL-slug + search fallback) - Tier 1 (Rainforest API / Keepa) is explicitly deferred because neither has a usable free tier as of this project's research.
- Branch/module ownership (Architecture Spine Branch Ownership table): the 8 feature branches each own specific modules; pipeline/orchestrator.py, pipeline/evidence.py, and everything in models/ are core/shared, owned by none of the 8 branches individually and edited in place by whichever branch needs the change.
- Progress reporting: Server-Sent Events via GET /jobs/{job_id}/events, backed by a per-job asyncio.Queue the orchestrator publishes stage-transition events to; a cache hit (FR-13) returns the Verdict synchronously with no job created and no SSE connection opened at all.
- Verdict schema (models/, shared, versioned): schema_version field; evidence_basis structured counts; persona_results plus persona_disagreement; sentiment_divergence; evidence_trail citations that must resolve to real Evidence Bundle items (a non-resolving citation is a validation failure, not a shown Verdict); on structured-output validation failure, retry once with the error appended to the prompt, then fail to FR-3's insufficient-data result.
- Review sampling specifics (addendum.md): stratified sample of top 20 by helpfulness votes + 10 most-critical (1-2 star) + 10 most recent; cluster near-duplicate reviews before sampling; fewer than 10 reviews triggers the FR-5 warning.
- Reddit query specifics (addendum.md): query template `"{product name}" (review OR worth it OR disappointed OR recommend OR regret)`; minimum 5 upvotes, posted within 2 years; embedding-similarity re-rank before candidates reach the LLM.
- LLM cost control (addendum.md / Architecture Spine): two LLM calls in llm-synthesis - a cheaper model for review/Reddit theme clustering, a stronger model for the final structured Verdict synthesis; both model names configured via Settings, swappable independently.
- Public GitHub repo, MIT license; 8 feature branches (scraper, reddit, alternatives, llm-synthesis, confidence-score, evidence-trail, caching, ui) squash-merged to main; solo builder.
- Deferred (brainstorm-intent.md Dreamer-room ideas, explicitly out of scope for all epics below): browser extension overlay, cart/wishlist price-drop watching, community verdict-accuracy voting, personal taste-profile learning, voice/audio verdict summary, non-Amazon retailers.
```

### UX Design Requirements

```
None - no UX design contract exists for this project (bmad-ux was not run). The web UI's look and interaction details are left to implementation within the Architecture Spine's constraints (AD-7, AD-10, AD-11) and the PRD's FR-15/FR-16.
```

### FR Coverage Map

```
FR-1: Epic 1 - Resolve a pasted Amazon URL to a Canonical Product
FR-2: Epic 1 - Tiered extraction with graceful fallback
FR-3: Epic 1 - Honest failure on blocked/unextractable pages
FR-4: Epic 1 - Representative review sampling
FR-5: Epic 1 - Low-review-volume warning
FR-6: Epic 2 - Entity-matched Reddit search
FR-7: Epic 2 - Sentiment cross-check against reviews
FR-8: Epic 1 - Comparable alternatives
FR-9: Epic 1 - Structured, schema-validated Verdict output
FR-10: Epic 3 - Multi-persona reasoning with disagreement surfaced
FR-11: Epic 1 - Algorithmic Confidence Score
FR-12: Epic 1 - Evidence Trail
FR-13: Epic 4 - Evidence Bundle caching
FR-14: Epic 4 - Duplicate-request coalescing
FR-15: Epic 1 - Submit a URL and view the Verdict
FR-16: Epic 1 - Visible progress during processing
```

## Epic List

### Epic 1: Core Verdict Loop
Paste an Amazon URL and get a grounded Buy/Skip/Wait verdict with confidence, evidence trail, and - if the verdict is Skip or Wait - 2-3 comparable alternatives so it's never a dead end. Built from scraped product facts and a representative review sample alone; no Reddit cross-check or multi-persona reasoning yet (those are real enhancements layered on in later epics, not required for this to be a genuinely useful, complete capability).
**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-8, FR-9, FR-11, FR-12, FR-15, FR-16
**Branches touched:** scraper, alternatives, llm-synthesis, confidence-score, evidence-trail, ui, core/shared (orchestrator, evidence, models)

### Epic 2: Reddit Reality-Check
The verdict now cross-checks against real Reddit discussion of the specific product and flags when reviews look inflated relative to what people actually say.
**FRs covered:** FR-6, FR-7
**Branches touched:** reddit (+ light wiring into llm-synthesis/evidence-trail to carry the new signal into the Verdict)

### Epic 3: Multi-Persona Trust
The verdict is now reasoned from 2-3 independent personas assessing the same evidence; when they disagree on the label, that disagreement is surfaced to the user rather than silently resolved.
**FRs covered:** FR-10
**Branches touched:** llm-synthesis (+ evidence-trail/ui to display the disagreement)

### Epic 4: Don't Make Me Wait Twice
Repeat checks on the same product are instant, concurrent requests for the same product don't duplicate work, and the user is told if the verdict changed since they last looked.
**FRs covered:** FR-13, FR-14
**Branches touched:** caching (+ core/shared orchestrator)

## Epic 1: Core Verdict Loop

Paste an Amazon URL and get a grounded Buy/Skip/Wait verdict with confidence, evidence trail, and - if the verdict is Skip or Wait - 2-3 comparable alternatives so it's never a dead end. Built from scraped product facts and a representative review sample alone; no Reddit cross-check or multi-persona reasoning yet.

**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-8, FR-9, FR-11, FR-12, FR-15, FR-16

### Story 1.1: Resolve a product URL to a Canonical Product

As a user,
I want pasting an Amazon product URL to resolve to a stable product identity with its title, price, and key specs,
So that the rest of the pipeline works from one dependable record instead of raw scraped text.

**Acceptance Criteria:**

**Given** a valid Amazon URL
**When** I submit it
**Then** it resolves to a Canonical Product id with title, price, and specs extracted.

**Given** a URL for a specific color/size variant
**When** resolved
**Then** the extracted data matches that exact variant, not a different one.

**Given** the same product reached via two URLs differing only by tracking parameters
**When** both are resolved
**Then** they produce the same Canonical Product id.

**Given** extraction succeeds via the Tier 2 scraper (the only tier shipped in v1)
**When** the Evidence Bundle is built
**Then** it records Tier 2 as the source and the Confidence Score reflects that tier.

**Given** the scraper needs proxy settings or any credentials
**When** it runs
**Then** all such config is loaded from environment variables via the shared `Settings` object - nothing hardcoded (establishes NFR-1 from the first story).

### Story 1.2: Fail honestly when a page can't be read

As a user,
I want a clear "insufficient data" result instead of a guess when a product page can't be extracted,
So that I never mistake a broken scrape for a real verdict.

**Acceptance Criteria:**

**Given** a broken, CAPTCHA-blocked, or unsupported-layout URL
**When** I submit it
**Then** the system returns an explicit "insufficient data" result and never reaches LLM synthesis.

**Given** a non-Amazon URL
**When** I submit it
**Then** the same honest-failure result is returned rather than fabricated data.

### Story 1.3: Sample reviews instead of reading all of them

As a user,
I want the verdict grounded in a representative review sample, not every review,
So that products with thousands of reviews don't blow up cost or time.

**Acceptance Criteria:**

**Given** a product with thousands of reviews
**When** sampled
**Then** the sample size stays bounded regardless of total count.

**Given** at least one critical (1-2 star) review exists
**When** sampled
**Then** at least one is included.

### Story 1.4: Warn when there isn't enough review signal

As a user,
I want to be told when a product has too few reviews,
So that I don't mistake a thin sample for a settled answer.

**Acceptance Criteria:**

**Given** a product below the review-count threshold
**When** the Verdict is produced
**Then** its Confidence Score is capped low and the result states why.

### Story 1.5: Surface comparable alternatives

As a user,
I want 2-3 comparable alternatives,
So that a Skip or Wait verdict gives me somewhere to go.

**Acceptance Criteria:**

**Given** a resolved Canonical Product
**When** alternatives are looked up
**Then** 2-3 alternatives in the same category and a similar price range are returned.

**Given** no alternatives exist in that band
**When** looked up
**Then** the Verdict is still produced without alternatives rather than failing the whole request.

### Story 1.6: Assemble one Evidence Bundle

As a user,
I want all gathered evidence combined into one consistent record before any verdict is produced,
So that the verdict is always grounded in the same complete picture.

**Acceptance Criteria:**

**Given** product facts, a review sample, and alternatives have been gathered
**When** assembled
**Then** the Evidence Bundle holds all three as distinct, separately-typed fields (facts separate from opinion-bearing data).

**Given** a stage failed or degraded
**When** assembled
**Then** that state is preserved as a distinct value, never silently treated as "found nothing."

### Story 1.7: Produce a schema-validated verdict

As a user,
I want one structured verdict - label, pros, cons, reasoning, confidence basis - built only from the Evidence Bundle,
So that I get a trustworthy answer, not raw model output.

**Acceptance Criteria:**

**Given** a complete Evidence Bundle
**When** the LLM responds
**Then** it's validated against the fixed Verdict schema; a failing response gets one retry with the validation error appended to the prompt.

**Given** both attempts fail validation
**When** this happens
**Then** the request resolves to the FR-3 "insufficient data" result, never a hand-patched Verdict.

**Given** a successful Verdict
**When** produced
**Then** its Confidence Score is overwritten by `compute_confidence()`, and any LLM-produced confidence value is discarded.

**Given** a successful Verdict
**When** produced
**Then** it states its evidence basis in plain terms alongside the score, and every pro/con links to a citation that resolves to a real Evidence Bundle item.

**Given** no price-history data exists in the Evidence Bundle (Tier 1 deferred)
**When** the label is "Wait"
**Then** the reasoning reflects inconclusive evidence only, never a price-trend prediction.

### Story 1.8: View the verdict on one screen

As a user,
I want to paste a URL and see the full verdict together on one screen,
So that I can decide without hunting across views.

**Acceptance Criteria:**

**Given** a completed Verdict
**When** I view the result
**Then** label, confidence, pros, cons, alternatives, and evidence trail all appear together.

**Given** an "insufficient data" or low-confidence result
**When** I view it
**Then** it's visually distinguishable from a normal confident Verdict.

### Story 1.9: See progress instead of a frozen page

As a user,
I want to see progress while my request processes,
So that I don't think the app stalled during the ~20-30s wait.

**Acceptance Criteria:**

**Given** I submit a URL
**When** processing begins
**Then** I get visible feedback within a few seconds via the SSE stream at `GET /jobs/{job_id}/events`.

**Given** each stage starts
**When** it publishes to the job's event queue
**Then** the UI reflects that transition via `EventSource`.

**Given** the request resolves
**When** the final event is sent
**Then** the stream closes.

## Epic 2: Reddit Reality-Check

The verdict now cross-checks against real Reddit discussion of the specific product and flags when reviews look inflated relative to what people actually say.

**FRs covered:** FR-6, FR-7

### Story 2.1: Search Reddit for the specific product

As a user,
I want the verdict to include real Reddit discussion about my specific product,
So that I get an independent check beyond the retailer's own reviews.

**Acceptance Criteria:**

**Given** a resolved Canonical Product
**When** Reddit is searched
**Then** returned threads reference the specific product by name/model, not just the brand or category.

**Given** low-quality matches (zero-upvote, years-old, unrelated-product)
**When** filtering
**Then** they're excluded before reaching synthesis.

**Given** Reddit is unavailable or rate-limited
**When** this happens
**Then** the pipeline proceeds with a Reddit-free Evidence Bundle at reduced Confidence Score rather than failing the whole request.

### Story 2.2: Flag when reviews look inflated vs. Reddit

As a user,
I want to know when Amazon reviews are much more positive than real Reddit discussion,
So that I don't trust a potentially-inflated review score.

**Acceptance Criteria:**

**Given** both review sentiment and Reddit sentiment are available
**When** compared
**Then** a meaningful divergence sets `sentiment_divergence: true` and the Verdict surfaces it.

**Given** no meaningful divergence
**When** compared
**Then** the flag is false and no false alarm is shown.

## Epic 3: Multi-Persona Trust

The verdict is now reasoned from 2-3 independent personas assessing the same evidence; when they disagree, that disagreement is surfaced rather than silently resolved.

**FRs covered:** FR-10

### Story 3.1: Reason from multiple independent personas

As a user,
I want the verdict reasoned from 2-3 independent personas assessing the same evidence,
So that a single model's quirks don't masquerade as a settled answer.

**Acceptance Criteria:**

**Given** a complete Evidence Bundle
**When** synthesis runs
**Then** 2-3 distinct Reasoning Personas (e.g. value buyer, longevity-focused, tech-specs reader) each independently assess it.

**Given** persona results are produced
**When** the Verdict is assembled
**Then** `persona_results` holds each persona's individual assessment.

### Story 3.2: Surface disagreement instead of hiding it

As a user,
I want to know when the personas disagree on Buy/Skip/Wait,
So that I can see genuine ambiguity instead of a falsely confident single answer.

**Acceptance Criteria:**

**Given** persona results with different verdict labels
**When** the Verdict is assembled
**Then** `persona_disagreement: true` is set.

**Given** persona results all agree
**When** the Verdict is assembled
**Then** `persona_disagreement: false` is set.

**Given** `persona_disagreement` is true
**When** I view the result
**Then** the UI visibly communicates the disagreement rather than silently picking one persona's answer.

## Epic 4: Don't Make Me Wait Twice

Repeat checks on the same product are instant, concurrent requests for the same product don't duplicate work, and the user is told if the verdict changed since they last looked.

**FRs covered:** FR-13, FR-14

### Story 4.1: Reuse a cached verdict instead of recomputing it

As a user,
I want a repeat check on a product I already looked up to return instantly,
So that I don't wait through the full pipeline again for no new information.

**Acceptance Criteria:**

**Given** a Canonical Product with a completed Evidence Bundle/Verdict cached within the TTL window (~48h default)
**When** I submit its URL again
**Then** the cached Verdict is returned synchronously, no job is created, and no SSE connection is opened.

**Given** a cached Verdict is returned
**When** I view it
**Then** it carries the timestamp of when it was originally computed.

**Given** the cache entry has expired past the TTL
**When** I submit the URL
**Then** the full pipeline re-runs rather than serving stale data.

### Story 4.2: Know if the verdict changed since I last looked

As a user,
I want to be told whether a cached verdict has changed since my last visit,
So that I don't have to re-read the whole thing to spot what's different.

**Acceptance Criteria:**

**Given** a cached Verdict I've seen before
**When** I view it again unchanged
**Then** it indicates nothing has changed since my last visit.

**Given** the cache was refreshed with a new Verdict since my last visit
**When** I view it
**Then** it indicates the verdict has changed since I last looked.

### Story 4.3: Share one evidence-gathering pass across concurrent requests

As a user,
I want concurrent requests for the same product to share a single pipeline run,
So that the system doesn't waste time and cost re-scraping and re-querying in parallel for the same thing.

**Acceptance Criteria:**

**Given** two requests for the same Canonical Product arrive while no cached Verdict exists yet
**When** the second request arrives
**Then** it attaches to the in-flight job's SSE stream rather than starting a second pipeline run.

**Given** the in-flight job completes
**When** it resolves
**Then** both requests receive the same Verdict and the result is cached for subsequent requests.
