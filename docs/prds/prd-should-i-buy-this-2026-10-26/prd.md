---
title: Should I Buy This? - Product Research Tool
status: final
created: 2026-10-26
updated: 2026-10-26
---

# PRD: Should I Buy This?

## 0. Document Purpose

This PRD defines what "Should I Buy This?" must do for its one real user — its builder — before implementation and architecture work begin. It builds on a completed brainstorming session (`brainstorm-intent.md`), whose technical decisions (library choices, API selections, prompt/query templates, data schemas) are preserved in `addendum.md` for `bmad-architecture` to consume directly; this document stays at the capability level.

## 1. Vision

"Should I Buy This?" is a personal decision engine, not a review aggregator. The user is minutes from clicking "Buy Now" on an Amazon product and wants one trustworthy answer — Buy, Skip, or Wait — backed by real evidence, not another wall of reviews to read themselves.

The user pastes a product URL. The tool gathers evidence (product facts, a representative sample of reviews, real Reddit discussion, a few comparable alternatives), then has an LLM reason over that evidence — never invent it — to produce a Verdict with pros, cons, a Confidence Score, and a visible Evidence Trail back to the sources it used. The tool is only useful if its answers can be trusted at a glance; evidence and confidence are the product, not the verdict label alone.

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional:** Get a fast, evidence-backed Buy/Skip/Wait answer for a specific Amazon product without personally reading hundreds of reviews or searching Reddit.
- **Emotional:** Reduce the anxiety and second-guessing of a purchase decision; avoid buyer's remorse.
- **Contextual:** Used in the moment of deciding — tab open, cart loaded, product page in front of them — not as a browsing or discovery tool.
- This is a tool the builder is making to use on themselves; "for me as the builder" is the only audience, and that is a valid scope for v1.

### 2.2 Key User Journeys

- **UJ-1.** The builder is standing between an Amazon product page and the "Buy Now" button. Instead of opening ten review tabs, they paste the URL into their own locally running app and get back a Buy/Skip/Wait Verdict — Confidence Score, pros/cons, alternatives, and a link-back Evidence Trail — in time to decide before checking out.

## 3. Glossary

- **Canonical Product** — The stable, de-duplicated identity (brand + model + category) a scraped product URL resolves to. All evidence, caching, and alternative-lookup is keyed to this, not the raw URL.
- **Evidence Bundle** — The fixed set of structured facts and opinions gathered for a Canonical Product (price, specs, review sample, Reddit sample, alternatives) before it is handed to the LLM.
- **Verdict** — The final structured output: Buy, Skip, or Wait, plus pros, cons, alternatives, a Confidence Score, and an Evidence Trail.
- **Confidence Score** — A numeric measure of how much evidence quality and quantity support the Verdict. Computed algorithmically from the Evidence Bundle, never set by the LLM.
- **Evidence Trail** — The set of literal source citations (review quotes, Reddit quotes) that ground each claim in the Verdict.
- **Source Tier** — The reliability/method ranking for how a piece of evidence was obtained (Tier 1: official API, Tier 2: scraper fallback, Tier 3: best-effort/degraded). Lower tiers reduce the Confidence Score.
- **Reasoning Persona** — One of several distinct LLM reasoning lenses (for example, value-focused or longevity-focused) used to independently assess the Evidence Bundle before the Verdict is synthesized.

## 4. Features

### 4.1 Product Evidence Extraction
**Description:** Given an Amazon product URL, the system resolves it to a Canonical Product and extracts price, title, specs, and aggregate rating — preferring reliable structured sources over scraping, and failing honestly rather than guessing. `[ASSUMPTION: v1 handles one Amazon product URL per request; batch/bulk lookup is out of scope.]`

**Functional Requirements:**

#### FR-1: Resolve a pasted Amazon URL to a Canonical Product
The system takes a pasted Amazon product URL and resolves it to a single Canonical Product, extracting title, price, and key specs.

**Consequences (testable):**
- A product URL pointing to a specific color/size variant resolves specs and price for that exact variant, not a different variant of the same listing.
- The same product reached via two different URLs (for example, with or without tracking parameters) resolves to the same Canonical Product.

#### FR-2: Tiered extraction with graceful fallback
The system attempts extraction via the most reliable available Source Tier first, falling back to lower tiers only when needed, and recording which tier was used.

**Consequences (testable):**
- Every Evidence Bundle records which Source Tier supplied price/spec data.
- A lower-tier extraction visibly reduces the Confidence Score for that request.

#### FR-3: Honest failure on blocked or unextractable pages
When a product page cannot be extracted (blocked, CAPTCHA, broken URL, unsupported layout), the system returns an explicit "insufficient data" result rather than a fabricated or partial Verdict.

**Consequences (testable):**
- A broken or non-Amazon URL never reaches the LLM synthesis step; the user sees a clear reason instead of a verdict.

**Out of Scope:** Non-Amazon retailers (deferred — see §6.2).

### 4.2 Review Evidence Sampling
**Description:** Instead of reading or summarizing every review, the system pulls a small, representative sample sufficient to ground a Verdict, and says so when there isn't enough signal to be confident.

**Functional Requirements:**

#### FR-4: Representative review sampling
The system selects a bounded, representative sample of a product's reviews (spanning helpful, critical, and recent reviews) rather than processing the full review corpus.

**Consequences (testable):**
- Review sample size stays bounded regardless of whether the product has 50 or 50,000 reviews.
- The sample includes at least one critical (low-star) review when critical reviews exist.

#### FR-5: Low-review-volume warning
When a product has too few reviews to support a confident read, the system flags this explicitly rather than treating a thin sample as conclusive.

**Consequences (testable):**
- Below a defined review-count threshold, the resulting Verdict's Confidence Score is capped low and the UI surfaces why.

### 4.3 Reddit Discussion Signal
**Description:** The system searches Reddit for real discussion of the specific product (not just the brand) and uses it as an independent check on the review data.

**Functional Requirements:**

#### FR-6: Entity-matched Reddit search
The system searches Reddit for discussion specifically about the Canonical Product, filtering out results that only mention the brand or category in passing.

**Consequences (testable):**
- Returned threads reference the specific product (by name/model), not just an unrelated product from the same brand.
- Low-quality or off-topic matches (for example, zero-upvote, years-old, or unrelated-product threads) are excluded before reaching synthesis.
- When Reddit is unavailable or rate-limited, the pipeline degrades gracefully (proceeds with a Reddit-free Evidence Bundle at reduced Confidence Score) rather than failing the whole request.

#### FR-7: Sentiment cross-check against reviews
The system compares sentiment found on Reddit against sentiment from the product's reviews and flags a meaningful divergence (for example, reviews that are much more positive than Reddit discussion).

**Consequences (testable):**
- A Verdict is annotated when Reddit and review sentiment diverge sharply, calling out the discrepancy rather than silently averaging it away.

### 4.4 Alternatives Discovery
**Description:** The system surfaces 2-3 comparable alternative products so a "Skip" or "Wait" verdict isn't a dead end.

**Functional Requirements:**

#### FR-8: Comparable alternatives
The system finds 2-3 alternative products in the same category and a similar price range as the original product.

**Consequences (testable):**
- Every suggested alternative is in the same product category and within a bounded price difference of the original.

### 4.5 Verdict Synthesis
**Description:** All gathered evidence is assembled into one Evidence Bundle and handed to the LLM, whose job is to reason over it and produce a structured Verdict — never to invent facts, never to set its own Confidence Score.

**Functional Requirements:**

#### FR-9: Structured, schema-validated Verdict output
The system produces a Verdict as a single structured object (Verdict label, pros, cons, alternatives, reasoning summary, Confidence Score, Evidence Trail) that is validated against a fixed schema before being shown to the user.

**Consequences (testable):**
- Malformed or incomplete LLM output is caught and either auto-repaired or rejected before reaching the UI — the UI never receives an invalid Verdict object.
- Every Verdict contains all required fields; none are silently omitted.
- A "Wait" label means the evidence is inconclusive — not confidently Buy, not confidently Skip — meaning the purchase shouldn't be rushed. In v1, "Wait" is never backed by price-history reasoning (for example, "price usually drops in a month"); it reflects evidence ambiguity only. A price-history-backed "Wait" is deferred to v2 (see §6.2).

#### FR-10: Multi-persona reasoning with disagreement surfaced
The Verdict is derived from 2-3 distinct Reasoning Personas assessing the same Evidence Bundle; when personas disagree, that disagreement is surfaced to the user rather than silently resolved.

**Consequences (testable):**
- When personas reach different verdict labels, the final result visibly communicates the disagreement rather than picking one silently.

**Notes:** Multiple personas mean multiple LLM calls per request — an accepted cost/latency trade-off in exchange for disagreement being a usable confidence signal (see §7 SM-2, §8 Open Question 6). If this trade-off proves too slow or costly in practice, reducing to 2 personas is preferable to dropping the disagreement signal entirely.

#### FR-11: Algorithmic Confidence Score
The Confidence Score is computed from measurable properties of the Evidence Bundle (for example, review volume, Source Tier, or Reddit corroboration) rather than being generated or self-assessed by the LLM.

**Consequences (testable):**
- Two requests with identical Evidence Bundle inputs produce the same Confidence Score.
- The LLM's output is never used directly as the Confidence Score value.

#### FR-12: Evidence Trail
Every factual claim and pro/con in the Verdict links back to a literal source (a specific review excerpt or Reddit quote) that the user can inspect.

**Consequences (testable):**
- Each pro/con shown in the UI has at least one linked source citation the user can view.
- A claim with no supporting citation is not included in the Verdict.
- The Verdict always states its evidence basis in plain terms (for example, "based on 23 reviews and 4 Reddit threads") alongside the Confidence Score — a number alone is not enough; the user can see what it's built on. A Confidence Score is a useful relative signal, not a calibrated probability — it has not been validated against real purchase outcomes (see §8 Open Question 4).

### 4.6 Caching & Request Handling
**Description:** Since many requests will repeat or overlap on the same product, the system avoids redundant work.

**Functional Requirements:**

#### FR-13: Evidence Bundle caching
A completed Evidence Bundle and Verdict for a Canonical Product are cached and reused for a bounded time window instead of being recomputed on every request.

**Consequences (testable):**
- A repeat request for the same Canonical Product within the cache window returns the cached Verdict without re-running extraction, Reddit search, or the LLM call.
- Every cached Verdict carries a timestamp; if the user revisits a Canonical Product they've seen before, the result indicates whether the Verdict has changed since their last visit.

#### FR-14: Duplicate-request coalescing
Concurrent requests for the same Canonical Product share a single evidence-gathering pass rather than each triggering their own.

**Consequences (testable):**
- N simultaneous requests for the same uncached product result in exactly one extraction/Reddit/LLM pass, not N.

### 4.7 Web UI
**Description:** A simple local web interface for pasting a URL and viewing the result — no account system, no multi-user concerns, since this runs on the user's own machine for their own use.

**Functional Requirements:**

#### FR-15: Submit a URL and view the Verdict
The user can paste an Amazon product URL into a web form and view the resulting Verdict, including Confidence Score, pros/cons, alternatives, and Evidence Trail, once processing completes.

**Consequences (testable):**
- The result view shows the Verdict label, Confidence Score, pros, cons, alternatives, and Evidence Trail together on one screen.
- An "insufficient data" result (FR-3) and a low-confidence result (FR-5) are visually distinguishable from a normal confident Verdict, not styled identically.

#### FR-16: Visible progress during processing
While a request is being processed, the user has some indication of progress rather than a silent frozen page for the full duration. `[ASSUMPTION: exact mechanism — polling vs. streaming partial results — is an architecture decision, not a PRD requirement; v1 only needs visible progress, not necessarily progressive reveal of each stage.]`

**Consequences (testable):**
- The user receives feedback that the request is in progress within a few seconds of submitting a URL, and is not left wondering whether the app has stalled during the full processing time.

## 5. Non-Goals (Explicit)

- Not a general-purpose review browser or product-discovery tool — it answers one decision about one product at a time.
- No multi-user accounts, authentication, or sharing in v1 — single local user only.
- No mobile app.

*(Other deferred capabilities — browser extension, price tracking/alerts, community voting, taste-profile learning — are listed once, in §6.2 Out of Scope for MVP, to avoid stating the same boundary twice.)*

## 6. MVP Scope

### 6.1 In Scope
- Amazon product URLs only.
- Tiered evidence extraction (reliable source first, scraper fallback, honest failure) for product facts.
- Representative review sampling with a low-volume warning.
- Reddit search scoped to the specific product, with sentiment cross-check against reviews.
- 2-3 comparable alternatives.
- Schema-validated, multi-persona Verdict synthesis with an algorithmic Confidence Score and Evidence Trail.
- Evidence/Verdict caching and duplicate-request coalescing.
- A simple local web UI for submitting a URL and viewing the result.

### 6.2 Out of Scope for MVP
- Price-history-backed "Wait" verdicts (for example, reasoning about expected price drops) — deferred to v2. In v1, "Wait" reflects inconclusive evidence only (see FR-9); it does not require or use price-history data.
- Non-Amazon retailers — deferred to v2. `[NOTE FOR PM: this was explicitly called out as "ideally any e-commerce site" in the original brief — revisit once Amazon flow is solid.]`
- Browser extension / overlay UI — deferred.
- Price-drop tracking and proactive alerts — deferred.
- Community verdict-accuracy voting / calibration — deferred.
- Personal taste-profile personalization — deferred.
- Hosted/remote deployment — v1 runs on the user's own machine only.

## 7. Success Metrics

**Primary**
- **SM-1:** The builder actually uses it before real Amazon purchases and keeps using it past the first month, rather than abandoning it after the novelty wears off. Validates FR-15.

**Secondary**
- **SM-2:** A typical request (submit URL → Verdict shown) completes, before the user checks out, within a wait time they're willing to tolerate — without feeling broken or stalled. Validates FR-16.

**Counter-metrics (do not optimize)**
- **SM-C1:** Do not optimize for the Verdict always being confident — a correctly low-confidence or "insufficient data" result (FR-3, FR-5) is a success when the evidence genuinely doesn't support more, not a failure to fix by inflating confidence. Counterbalances SM-1.

## 8. Open Questions

1. Which specific Tier-1 data source(s) to use for Amazon product facts, and whether their free tiers are sufficient given the stated preference to keep costs low — feeds into `bmad-architecture`.
2. Exact mechanism for "visible progress" (FR-16): simple polling vs. streaming partial results.
3. Persistent storage choice for cached Evidence Bundles/Verdicts (and whether an ephemeral cache is sufficient vs. something longer-lived).
4. Exact Confidence Score formula — which inputs, what weights, what threshold triggers a low-confidence warning.
5. How multi-persona disagreement (FR-10) is best presented in the UI without confusing the user.
6. What counts as an acceptable wait time for SM-2 — no target number is set yet; depends on how slow the tiered extraction + Reddit + multi-persona LLM pipeline turns out to be in practice.
7. The specific numeric defaults used in FR-5 (review-count threshold) and FR-8 (price-band width) are starting points carried from `addendum.md`, not validated — revisit once the tool is in real use.
8. Reddit API / PRAW free-tier rate limits are a real constraint for a zero-budget personal project — confirm they're workable for expected usage, or identify a fallback, before relying on FR-6 in daily use.

## 9. Assumptions Index

- §4.1 — v1 handles one Amazon product URL per request; no batch/bulk lookup.
- §4.7 FR-16 — "Visible progress" only requires the user know something is happening; progressive per-stage reveal (streaming) is not required for MVP, exact mechanism deferred to architecture.
