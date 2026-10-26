# Should I Buy This? — Brainstorm Intent Doc
_Distilled from BMad brainstorming session · First Principles + Reverse Brainstorming + Disney Method_

---

## What This Tool Is (Bedrock)

A decision engine, not a review aggregator. The user is 5 minutes from clicking "Buy Now." They need one confident answer, fast, with enough evidence to trust it.

**Core pipeline:** Fetch evidence → extract decision-relevant slices → LLM interprets (never invents) → structured verdict.

---

## Chosen Directions

### 1. Schema-First Architecture (settled — validated 3×)
- Define a fixed evidence schema before writing any scraper or prompt
- Every data source fills fields in that schema; the LLM receives the schema, not raw HTML
- LLM role: reasoning and formatting only — never research, never fact generation
- JSON output enforced via structured outputs + validation + auto-repair on failure

### 2. Algorithmic Confidence Score (settled — validated 3×)
- LLM never sets the confidence score
- Score computed from: review count, source diversity, Reddit corroboration, extractor quality tier, recency
- Sparse evidence → low confidence surfaced explicitly, not hidden behind a clean card
- "When not to answer confidently" is a first-class feature, not an edge case

### 3. Data Source Hierarchy (settled — scraping is fallback, not primary)
- **Tier 1 (preferred):** Official APIs — Rainforest API (Amazon), Keepa (price history), Reddit API via PRAW
- **Tier 2 (fallback):** Playwright scraper with rotating agents — triggers lower confidence score automatically
- **Tier 3 (graceful fail):** Extract product name from URL slug → Google Shopping search
- No arms race against Amazon bot detection — official data is cheaper and more reliable at scale

### 4. Review Sampling Strategy
- Never random, never full corpus
- Stratified sample: top 20 by helpfulness votes + 10 most-critical (1–2 star) + 10 most recent
- Cluster near-duplicate reviews before sampling to avoid repetition inflating sentiment
- Minimum threshold: < 10 reviews → warn user, suppress confident verdict

### 5. Reddit Signal Quality
- Query template: `"{product name}" (review OR worth it OR disappointed OR recommend OR regret)`
- Filter: minimum 5 upvotes, posted within 2 years
- Cross-check: if Amazon review sentiment diverges sharply from Reddit sentiment → flag "reviews may be inflated"
- Reddit disagreement with product page = signal, not noise

### 6. Evidence Trail as Core Feature
- Every claim in the verdict links to a source quote
- Grounding enforced server-side (citations required in schema), surfaced as UI feature
- Users see which reviews were sampled, which Reddit threads were used
- Verdict stored with timestamp → "verdict changed since you last checked" on repeat visits

### 7. Multi-Persona Verdict (Dreamer → Critic answer)
- Generate verdict from 2–3 reasoning personas (e.g. value buyer, longevity-focused, tech specs reader)
- Persona *disagreement* is itself a confidence signal — surfaces ambiguity instead of hiding it
- Directly solves "confidently wrong verdict indistinguishable from correct one in clean JSON"

---

### 8. Design Top-Down From the UI Contract
- Define the exact verdict JSON the frontend renders first
- Derive what the LLM must output from that, then derive what evidence must be gathered
- Separates fact fields (price, specs — must be exact) from opinion fields (pros, cons, verdict — probabilistic)
- Schema versions together with the prompt — they are one contract, not two independent things

### 9. Plugin Scraper Architecture
- BeautifulSoup for static HTML sites (fast, lightweight)
- Playwright only for JS-heavy sites — selected by per-domain config flag
- Keeps the fast path fast; Playwright is heavy, don't use it where it isn't needed
- Tiered site support: native adapters for top retailers → generic heuristic extractor → honest "unsupported site" message

### 10. Request Coalescing
- N concurrent requests for the same product → one scrape + N cache reads
- Lock-based dedup keyed on canonical product ID
- Easy win, easy to forget — build it on day one

### 11. Separate LLM Calls by Cost
- Cheap extraction/clustering calls (review theme grouping) separate from the strong synthesis call (final verdict)
- Keeps token cost controlled without sacrificing verdict quality
- Lets you swap models independently per stage

### 12. Structured Logging From Day One
- Per-stage timing and success/fail tracing throughout the pipeline
- Silent partial failures (empty reviews, zero Reddit hits) are the main debugging nightmare
- Log extraction field null rates — alert when scraper silently breaks after a site redesign

### 13. Confidence Score Calibration Caveat
- Confidence scores mean nothing without calibration against real outcomes
- Surface this honestly in the UI — "based on N reviews and M Reddit threads"
- Long-term: community verdict accuracy voting to build a real calibration track record

## Architecture Snapshot

```
URL → canonicalize product identity
    → Tier 1 API fetch (or Tier 2 scraper fallback)
    → stratified review sample
    → Reddit fetch + relevance filter
    → Google Shopping alternatives (2–3 products)
    → build evidence object (fixed schema)
    → LLM: interpret evidence, multi-persona, structured output
    → compute confidence score algorithmically
    → return verdict JSON + evidence trail
    → cache by product ID, TTL 48h
```

---

## What Not To Build (Critic Room)

- Don't let LLM set confidence — vibes with decimals
- Don't scrape Amazon as primary strategy — fragile, legally gray, expensive at scale
- Don't summarize all reviews — sample intelligently instead
- Don't ship without a "not enough data" state — sparse products need a different UX
- Don't ignore Reddit API ToS — PRAW on free tier has rate limits; design around them

---

## Open Questions (Feed Into bmad-architecture)

1. Job queue architecture — async pipeline needs a task runner (Celery? ARQ? Simple asyncio?)
2. Postgres evidence snapshots vs. Redis cache — what needs to persist vs. what's ephemeral?
3. Streaming UX — SSE or WebSocket for the 20–30 second wait?
4. Multi-persona verdict UI — how to show disagreement without confusing the user?
5. Confidence score formula — what weights, what floor triggers the "low confidence" warning?

---

_Ready to feed into: `bmad-architecture` · `bmad-spec`_