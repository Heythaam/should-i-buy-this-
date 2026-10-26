# Addendum: Technical Depth for "Should I Buy This?"

*Carried over from `brainstorm-intent.md` and the brainstorming session. This is implementation/architecture input, not PRD content — tech choices, not capabilities. Read alongside `prd.md`; FR references below point back to the PRD.*

## Stack (user-stated)
Python, FastAPI backend, Playwright + BeautifulSoup for scraping, PRAW for Reddit, OpenAI API for the LLM layer. Simple web UI (Jinja2/HTMX preferred over a heavy JS framework, given solo scope).

## Pipeline Shape
```
URL -> canonicalize product identity
    -> Tier 1 API fetch (or Tier 2 scraper fallback, or Tier 3 degraded)
    -> stratified review sample
    -> Reddit fetch + relevance filter + sentiment cross-check
    -> alternatives lookup (same category/price band — see Alternatives Lookup below)
    -> build Evidence Bundle (fixed schema)
    -> LLM: multi-persona reasoning -> structured Verdict
    -> compute Confidence Score algorithmically
    -> return Verdict JSON + Evidence Trail
    -> cache by Canonical Product ID
```
Every section below is the detail behind one box in this diagram.

## Data Source Hierarchy (informs FR-1, FR-2, FR-3)
- **Tier 1 (preferred):** Official APIs — Rainforest API (Amazon product data), Keepa (price history), Reddit API via PRAW.
- **Tier 2 (fallback):** Playwright scraper with rotating user agents/headers triggers a lower Confidence Score automatically.
- **Tier 3 (graceful fail):** Extract product name from the URL slug and fall back to a Google Shopping-style search for comparables rather than fabricating data.
- Rationale: no arms race against Amazon's bot detection — scraping Amazon at scale is also legally gray under its Conditions of Use, not just fragile; official data is cheaper and more reliable, scraping is the long-tail fallback, not the primary path.
- Keepa: listed here for general product data context, but v1's "Wait" verdict logic does not depend on price history (PRD FR-9, §6.2) — a price-history-backed "Wait" is deferred to v2, so Keepa can be deferred alongside it if not otherwise needed. If kept, evaluate its free-tier limits (alongside Rainforest's) against the scraper-fallback trade-off before committing — the user wants free tiers where possible (Open Question 1 in PRD).

## Scraper Architecture (informs FR-2)
- Plugin/adapter pattern: BeautifulSoup for static HTML, Playwright only for JS-heavy pages, selected via a per-domain config flag — keeps the fast path fast since Playwright is heavy.
- Tiered site support for future non-Amazon expansion: native adapters for top retailers → generic heuristic extractor → honest "unsupported site" message (never silently wrong data).

## Review Sampling Strategy (informs FR-4, FR-5)
- Stratified, not random, not full-corpus: top 20 by helpfulness votes + 10 most-critical (1-2 star) + 10 most recent.
- Cluster near-duplicate reviews before sampling to avoid repetition inflating sentiment.
- Minimum threshold: fewer than 10 reviews → warn user, suppress a confident verdict.

## Reddit Signal Quality (informs FR-6, FR-7)
- Query template: `"{product name}" (review OR worth it OR disappointed OR recommend OR regret)`.
- Filter: minimum 5 upvotes, posted within 2 years.
- Relevance re-rank candidates by embedding similarity to the product title before they reach the LLM.
- Cross-check: if Amazon review sentiment diverges sharply from Reddit sentiment, flag "reviews may be inflated."
- Constraint: PRAW's free tier carries real rate limits; design the Reddit step to degrade gracefully (informs PRD FR-6) rather than block the whole pipeline when rate-limited. Don't ignore this — it is a zero-budget project, so there's no paid-tier escape hatch.

## Alternatives Lookup (informs FR-8)
Reuses the same category + price-band matching described in the PRD (FR-8: same category, bounded price difference) against structured spec data — no separate mechanism from the rest of the pipeline.

## Verdict Synthesis (informs FR-9, FR-10, FR-11, FR-12)
- **Schema:** Build sequencing principle from the brainstorm — design top-down from the UI contract. Define the exact Verdict JSON the frontend renders first, then derive what the LLM must output to produce it, then derive what evidence must be gathered to support that output. The schema and the prompt are one contract, versioned together, not two independently evolving things. A fixed JSON evidence schema is built before any prompt is written; the LLM receives only this schema, never raw HTML/text. Separate fact fields (price, specs — must be exact) from opinion fields (pros, cons, verdict — probabilistic). JSON output is enforced via OpenAI structured outputs / function-calling schema validation, with a retry-on-validation-failure/auto-repair loop — never "please respond in JSON."
- **Confidence Score:** Formula inputs: review count, source diversity, Reddit corroboration, extractor tier (Tier 1/2/3), recency. The LLM never sets this value, only explains it.
- **Multi-persona:** 2-3 personas (for example, value buyer, longevity-focused, tech-specs reader) independently assess the Evidence Bundle; disagreement is itself a signal, not something to silently resolve.
- **Evidence Trail:** Citations required in the schema (grounding enforced server-side), surfaced as a UI feature — users see which reviews/threads were actually used.
- **Cost control:** Split LLM calls — cheap model for extraction/clustering (review theme grouping), stronger model for final synthesis — to control token cost without sacrificing verdict quality. This also lets models be swapped independently per stage.

## Caching & Request Handling (informs FR-13, FR-14)
- Cache full Evidence Bundle + Verdict per Canonical Product, TTL ~48h (default, open to tuning).
- Lock-based request coalescing keyed on Canonical Product ID — N concurrent requests for the same product become one fetch + N cache reads.

## Observability
- Structured, per-pipeline-stage timing and success/fail logging from day one — silent partial failures (empty reviews, zero Reddit hits) are expected to be the main debugging pain in a multi-source pipeline.
- Log extraction field null-rates; alert when a scraper silently breaks after a site redesign (contract-test against saved HTML fixtures where practical).

## Open Implementation Questions (architecture to resolve)
1. Job queue / async pipeline runner: Celery, ARQ, or plain asyncio — sizing depends on whether this ever needs to run more than one request at a time.
2. Postgres vs. Redis (or both) for evidence snapshots — what needs to persist vs. what's safe to be short-lived (PRD Open Question 3).
3. Streaming UX mechanism for the ~20-30s wait: Server-Sent Events, WebSocket, or simple polling (PRD FR-16 only requires *some* visible progress, not a specific mechanism).
4. Multi-persona disagreement UI treatment — how to show it without confusing a single at-a-glance verdict.
5. Confidence Score formula weights and the exact threshold that triggers a "low confidence" warning.

## Deferred (Dreamer-room) ideas, kept for later phases
- Browser extension overlay on the product page itself (no URL paste).
- Cart/wishlist watching with proactive "now's the time to buy" notifications.
- Community-sourced verdict-accuracy voting / calibration track record.
- Personal taste-profile learning from past buy/skip decisions.
- Voice/audio verdict summary.
