# Reconciliation: brainstorm-intent.md → prd.md / addendum.md

Input: `brainstorm-intent.md` (13 numbered "Chosen Directions" + Architecture Snapshot + "What Not To Build" critic room + 5 Open Questions, framed by a "decision engine, not review aggregator" / "5 minutes from Buy Now" bedrock statement).

User-provided scoping answers applied downstream: (a) Amazon-only for v1, (b) local-machine deployment, free/cheap API tiers preferred, (c) "Wait" in v1 = inconclusive evidence only, not price-history reasoning (deferred to v2).

## Item-by-item trace

| # | Brainstorm item | Landed where | Status |
|---|---|---|---|
| Bedrock | "Decision engine, not review aggregator"; user 5 min from Buy Now; fetch→extract→LLM interprets never invents→structured verdict | PRD §1 Vision (near-verbatim, including "minutes from clicking Buy Now") | Preserved, including tone |
| 1 | Schema-first architecture | PRD FR-9; addendum "Verdict Synthesis" | Preserved |
| 2 | Algorithmic confidence score, sparse evidence surfaced not hidden | PRD FR-11, FR-5, SM-C1 | Preserved |
| 3 | Data source hierarchy (Tier 1 API / Tier 2 scraper / Tier 3 graceful fail), "no arms race against bot detection" | PRD FR-1/2/3; addendum "Data Source Hierarchy" (near-verbatim) | Preserved |
| 4 | Review sampling strategy (top 20 helpful + 10 critical + 10 recent, dedup clustering, <10 reviews warning) | PRD FR-4/FR-5; addendum "Review Sampling Strategy" (verbatim numbers) | Preserved |
| 5 | Reddit signal quality (query template, 5-upvote/2-year filter, sentiment cross-check) | PRD FR-6/FR-7; addendum "Reddit Signal Quality" (verbatim, plus an added embedding-rerank step) | Preserved |
| 6 | Evidence trail as core feature | PRD FR-12; addendum "Verdict Synthesis" | Preserved |
| 6b | "Verdict stored with timestamp → 'verdict changed since you last checked' on repeat visits" | — | **Gap (see below)** |
| 7 | Multi-persona verdict, disagreement as signal | PRD FR-10; addendum "Verdict Synthesis" | Preserved |
| 8 | "Design top-down from the UI contract" (define verdict JSON first, derive LLM output, derive evidence needs; schema+prompt versioned as one contract) | — | **Gap (see below)** |
| 9 | Plugin scraper architecture (BeautifulSoup/Playwright per-domain flag, tiered site support) | addendum "Scraper Architecture" (near-verbatim); informs PRD FR-2 | Preserved |
| 10 | Request coalescing (lock-based dedup) | PRD FR-14; addendum "Caching & Request Handling" | Preserved |
| 11 | Separate LLM calls by cost (cheap extraction vs. strong synthesis) | addendum "Verdict Synthesis" cost-control note | Preserved |
| 12 | Structured logging from day one, null-rate alerting | addendum "Observability" (near-verbatim) | Preserved |
| 13a | Calibration caveat: "confidence scores mean nothing without calibration against real outcomes"; long-term community voting | PRD §5/§6.2, addendum "Deferred" list capture the *community voting* half | Partially preserved — see gap below |
| 13b | "Surface this honestly in the UI — 'based on N reviews and M Reddit threads'" for *all* verdicts | PRD FR-5 only requires this for the low-confidence case | Partially preserved — see gap below |
| Arch snapshot | Full pipeline diagram | addendum "Pipeline Shape" (near-verbatim, Google Shopping step generalized to "alternatives lookup") | Preserved |
| Critic: don't let LLM set confidence | FR-11 | Preserved |
| Critic: don't scrape Amazon as primary — "fragile, legally gray, expensive at scale" | addendum rationale keeps "cheaper and more reliable at scale" but drops "legally gray" | **Partial gap (see below)** |
| Critic: don't summarize all reviews | FR-4 | Preserved |
| Critic: don't ship without "not enough data" state | FR-3/FR-5/SM-C1 | Preserved |
| Critic: "don't ignore Reddit API ToS; PRAW free tier has rate limits, design around them" | addendum "Cost note" only covers Rainforest/Keepa free-tier limits, not Reddit/PRAW | **Gap (see below)** |
| Open Q1 (job queue) | addendum OQ1 | Preserved |
| Open Q2 (Postgres vs Redis) | PRD OQ3; addendum OQ2 | Preserved |
| Open Q3 (streaming UX) | PRD OQ2; addendum OQ3 | Preserved |
| Open Q4 (multi-persona UI) | PRD OQ5; addendum OQ4 | Preserved |
| Open Q5 (confidence formula weights) | PRD OQ4; addendum OQ5 | Preserved |

Deliberate, reasonable exclusions (per user's scoping answers, correctly reflected): non-Amazon retailers deferred to v2 (PRD §6.2, flagged with a `[NOTE FOR PM]` that the original brief said "ideally any e-commerce site" — good traceability); price-history-backed "Wait" / Keepa deferred to v2 (PRD FR-9, §6.2; addendum explicit note); hosted/remote deployment out of scope (PRD §6.2).

## Gaps found

1. **"Verdict changed since you last checked" repeat-visit signal — silently dropped.** Brainstorm item 6 explicitly calls for storing the verdict with a timestamp so a user revisiting the same product can see "verdict changed since you last checked." The PRD/addendum carry over *caching* (FR-13, TTL ~48h) but caching is about avoiding redundant computation, not about detecting and surfacing drift to a returning user. No FR, glossary entry, or addendum section addresses comparing a new Evidence Bundle/Verdict against a prior stored one for the purpose of flagging change. This looks like a distinct feature that fell through the cracks rather than a deliberate cut (no non-goal or out-of-scope line mentions it either).

2. **"Design top-down from the UI contract" methodology — not transferred.** Brainstorm item 8 is a build-sequencing principle for the architecture phase: define the exact verdict JSON contract first, derive required LLM output from it, then derive what evidence must be gathered — and treat the schema and prompt as one versioned contract, not two independent things. This is exactly the kind of "technical/implementation content" the addendum says it preserves for `bmad-architecture`, but it doesn't appear anywhere in addendum.md (the Verdict Synthesis section describes the schema itself but not this top-down derivation order, nor the "schema versions together with the prompt" point). Since this shapes how architecture should sequence its own work, its absence is a meaningful process-level gap, not just a minor omission.

3. **Reddit API ToS / PRAW rate-limit design constraint — dropped.** The brainstorm's critic-room list explicitly flags: "Don't ignore Reddit API ToS; PRAW on free tier has rate limits; design around them." The addendum's cost note only discusses free-tier limits for Rainforest and Keepa ("evaluate Rainforest/Keepa free-tier limits vs. scraper-fallback trade-off"), never mentioning Reddit/PRAW rate limits or ToS compliance at all, despite PRAW being named in the Stack section. Given Reddit search is a core v1 feature (FR-6/FR-7), this specific constraint should have carried forward alongside the other free-tier cost note.

4. **Confidence-score calibration honesty caveat — only half-preserved.** Brainstorm item 13 has two parts: (a) the epistemic caveat that "confidence scores mean nothing without calibration against real outcomes," and (b) a concrete UI requirement to always show the basis ("based on N reviews and M Reddit threads"), with (c) a long-term idea of community accuracy voting for calibration. Only (c) made it into the PRD/addendum as a deferred non-goal. The caveat itself (a) — i.e., an acknowledgment that the algorithmic score is uncalibrated/unvalidated and users shouldn't over-trust it — isn't surfaced anywhere (not in Vision, not as a non-goal, not as a known limitation). And the transparency requirement (b) is only wired into FR-5 for the *low-confidence* case; there's no requirement that a normal/high-confidence Verdict also show its N-reviews/M-threads basis, even though Evidence Trail (FR-12) and Confidence Score (FR-11) together make this largely achievable in practice.

5. **"Legally gray" risk framing for scraping — softened.** Minor: the critic-room reason for deprioritizing scraping was "fragile, legally gray, expensive at scale." The addendum's rationale for the Tier 1-first hierarchy keeps "cheaper and more reliable at scale" and "no arms race against bot detection" but never mentions legal/ToS risk as a motivating factor. Low severity (the resulting architecture decision is identical either way), but it quietly removes a risk consideration that a future contributor reading only the addendum wouldn't know was part of the original reasoning.

## Qualitative/tone check

The "decision engine, not a review aggregator" framing and the "minutes from clicking Buy Now" urgency are preserved essentially verbatim in PRD §1 Vision — the FR-driven structure did not flatten this framing out. The "when not to answer confidently is a first-class feature" idea survives clearly via FR-3/FR-5/SM-C1 (the counter-metric explicitly protects low-confidence/insufficient-data results from being "fixed" by inflating confidence). Persona-disagreement-as-signal (not noise) and Reddit-disagreement-as-signal (not noise) both survive with their original framing in FR-7 and FR-10. Overall the qualitative intent transferred well; the gaps above are concrete omitted items/claims, not a tone loss.
