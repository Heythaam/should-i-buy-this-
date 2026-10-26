---
title: 'Resolve a product URL to a Canonical Product'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '4be35e737da7a98c1084b134ef040f9fbe7f3b9f'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The project has no code yet. Nothing can turn a pasted Amazon URL into a stable product identity with real price/title/spec data, so no later pipeline stage has anything to key off.

**Approach:** Scaffold the Python project, then implement `canonicalize(url) -> CanonicalProductId` (ASIN-based identity, AD-2) and a Tier 2 `ProductSource` (Playwright + BeautifulSoup) that fetches `ProductFacts` for that id, with proxy config loaded via a `Settings` object. No FastAPI app or orchestrator yet — this story doesn't need one.

## Boundaries & Constraints

**Always:**
- `canonicalize(url) -> CanonicalProductId` is the only source of product identity (AD-2); id format is `amazon:{ASIN}`.
- Product-page fetching goes through one `ProductSource.fetch(url) -> ProductFacts | SourceFailure` interface (AD-3) — no ad-hoc HTTP/Playwright calls elsewhere.
- All scraper config (proxy URL) loads from env vars via a `pydantic-settings` `Settings` object — nothing hardcoded (NFR-1).
- The scraper wraps its fetch with a timeout + one retry before degrading to `SourceFailure` (AD-9); it never raises an unhandled exception out of `fetch()` (AD-4).

**Never:**
- No FastAPI app, routes, orchestrator, or Evidence Bundle assembly in this story — those belong to later stories (1.6+).
- No Tier 1 API, Reddit, alternatives, or LLM code — out of scope here.
- No live-network calls inside automated tests — scraper parsing is tested against saved HTML fixtures only.
- Do not add CI/CD or Reddit/OpenAI `Settings` fields — `Settings` grows per-branch later (AD-11).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Standard product URL | `https://amazon.com/dp/B08N5WRWNW` | `CanonicalProductId("amazon:B08N5WRWNW")` | N/A |
| Same product, tracking params differ | Two URLs, same ASIN, different query strings | Identical `CanonicalProductId` | N/A |
| Color/size variant URL | URL with a variant-specific ASIN | Id + `ProductFacts` for that exact variant | N/A |
| Non-Amazon / malformed URL | e.g. an ebay.com URL, or unparseable string | — | `canonicalize` raises `InvalidProductURLError` |
| Scraper fetch succeeds | Valid ASIN, HTML with title/price/specs | `ProductFacts(source_tier=TIER_2, ...)` | N/A |
| Scraper fetch fails (blocked/CAPTCHA/timeout) | Valid ASIN, unreadable page | — | `fetch` returns `SourceFailure`, never raises |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- new: project metadata, deps (pydantic, pydantic-settings, playwright, beautifulsoup4; pytest, ruff as dev deps) — no fastapi/praw/openai/aiosqlite yet, not used by this story
- `.gitignore` -- new: `.env`, `__pycache__/`, `.venv/` (NFR-1: `.env` ignored from the first commit)
- `.env.example` -- new: documents optional `SCRAPER_PROXY_URL`
- `app/__init__.py`, `app/settings.py` -- new: `Settings(BaseSettings)` with `scraper_proxy_url: str | None = None`
- `app/models/__init__.py`, `app/models/product.py` -- new: `SourceTier` enum (`TIER_2`, `TIER_3`), `ProductFacts`, `SourceFailure`
- `app/pipeline/__init__.py`, `app/pipeline/canonicalize.py` -- new: `CanonicalProductId`, `canonicalize()`, ASIN regex, `InvalidProductURLError`
- `app/pipeline/sources/__init__.py`, `base.py` -- new: `ProductSource` Protocol, `fetch(url) -> ProductFacts | SourceFailure`
- `app/pipeline/sources/scraper_tier2.py` -- new: Playwright (render) + BeautifulSoup (parse) implementation; reads `Settings.scraper_proxy_url`
- `tests/pipeline/test_canonicalize.py`, `tests/pipeline/sources/test_scraper_tier2.py` -- new: cover the I/O Matrix
- `tests/fixtures/amazon_product_basic.html`, `amazon_product_variant.html` -- new: synthetic minimal HTML using documented Amazon DOM conventions, not copied from a real page

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml`, `.gitignore`, `.env.example` -- scaffold project, pin deps -- nothing else can run without this
- [x] `app/settings.py` -- add `Settings.scraper_proxy_url` -- establishes the NFR-1 pattern
- [x] `app/models/product.py` -- add `ProductFacts`, `SourceFailure`, `SourceTier` -- typed contract for the rest of this story
- [x] `app/pipeline/canonicalize.py` -- implement `canonicalize()` + `InvalidProductURLError` -- AD-2
- [x] `app/pipeline/sources/base.py` -- define `ProductSource` interface -- AD-3
- [x] `app/pipeline/sources/scraper_tier2.py` -- implement Tier 2 scraper against the interface -- AD-3, AD-9, AD-4
- [x] `tests/pipeline/**` + fixtures -- cover the I/O Matrix -- proves this story's ACs

**Acceptance Criteria:**
- Given a valid Amazon URL, when `canonicalize()` then `fetch()` run, then a `CanonicalProductId` and a `ProductFacts` with title/price/specs and `source_tier=TIER_2` are returned.
- Given two URLs for the same ASIN differing only by tracking params, when both are canonicalized, then both produce the identical `CanonicalProductId`.
- Given a color/size variant URL, when resolved, then the returned facts belong to that exact variant's ASIN.
- Given a non-Amazon or malformed URL, when `canonicalize()` runs, then it raises `InvalidProductURLError` rather than returning a guessed id.
- Given the scraper fetch fails for any reason, when `fetch()` runs, then it returns a `SourceFailure` — never an unhandled exception or a partially-filled `ProductFacts`.
- Given `Settings.scraper_proxy_url` is set via an environment variable, when the scraper runs, then Playwright launches through that proxy; given it's unset, no proxy is used — the value is never hardcoded.

## Implementation Notes

- `CanonicalProductId` is implemented as a `str` subclass (`__slots__ = ()`), not a Pydantic model -- it's a pure value: equality/hashing fall out of `str`, and it drops directly into dict/cache keys for AD-8 later without extra plumbing.
- Amazon-host validation uses an explicit allowlist of registrable Amazon domains (`amazon.com`, `amazon.co.uk`, ...) rather than a generic "ends with amazon.<letters>" regex. The generic form was tried first and failed its own test: `amazon.evil.com` wrongly passed, because "evil.com" is itself just letters and dots. The allowlist form correctly rejects both `notamazon.com` and `amazon.evil.com` while still accepting any subdomain (`www.`, `smile.`) of a real Amazon domain.
- `ProductFacts.canonical_product_id` is typed as a plain `str` (not `CanonicalProductId`), so `models/` (core/shared, AD-11) doesn't import from `pipeline/` -- avoids a reverse-direction dependency between the shared model layer and a stage module. `ScraperTier2Source.fetch()` calls `canonicalize(url)` itself and stringifies the result when building `ProductFacts`.
- `scraper_tier2.py` factors parsing into Playwright-free module-level functions (`parse_product_facts`, `build_proxy_config`) specifically so tests exercise real parsing logic against saved HTML fixtures with zero network/browser dependency, satisfying this story's "no live-network calls in tests" rule. `fetch()`'s retry/degrade and proxy-wiring behavior are covered by stubbing `_render` (and, for one test, monkeypatching `async_playwright` itself) rather than hitting a real browser.
- No `pytest-asyncio` dependency was added (the spec's dev-dep list names only `pytest`/`ruff`) -- async methods are tested by wrapping calls in `asyncio.run()` inside ordinary sync test functions.
- A third "blocked/CAPTCHA" HTML fixture was not added as a file; the one parse-failure test constructs that minimal HTML inline, keeping the fixture file list exactly as scoped in the Code Map (`amazon_product_basic.html`, `amazon_product_variant.html`).

- **Review patch round:** all 12 `patch`-routed findings from the review (see Review Triage Log) were fixed by the same implementation subagent: locale-aware price parsing (`_parse_price_text`, returns `None` on ambiguous comma usage rather than guessing), scheme validation + trailing-dot handling + `/gp/aw/d/` + `/exec/obidos/ASIN/` shapes in `canonicalize()`, a 1s retry backoff + final `logger.error` on retry exhaustion, a `wait_for_selector("#productTitle")` before reading page content, first-value-wins on duplicate spec labels, a fail-fast `field_validator` on `Settings.scraper_proxy_url` (deliberately not `pydantic.AnyUrl`, which was verified to wrongly accept a scheme-less proxy string), and expanded `.gitignore`. 14 new tests added; full suite is 35/35 passing, `ruff check` clean.

## Spec Change Log

## Review Triage Log

- **Comma-decimal price parsing** (`scraper_tier2.py::_extract_price`) — `medium` — `patch`. Verified: `re.sub(r"[^0-9.]", "", "39,99 €")` strips the comma, yielding `"3999"` → `float` 100x too large. Real for every EU-locale Amazon domain already in `_AMAZON_DOMAINS` (de/fr/it/es/nl/se/pl). Confirmed by both Blind Hunter and Edge Case Hunter independently.
- **`canonicalize()` doesn't validate URL scheme** — `low` — `patch`. A non-HTTP(S) scheme (e.g. `ftp://amazon.com/dp/...`) with an Amazon-looking host passes validation since only `parsed.hostname` is checked, never `parsed.scheme`.
- **No Amazon short-link support (`amzn.to`, `a.co`)** — `defer`. Confirmed gap, not caused by this story — resolving it needs redirect-following before ASIN extraction, a materially different (async/network-calling) design than `canonicalize()`'s current pure-function contract (AD-2). Logged to `deferred-work.md`.
- **Retry has no backoff; full browser relaunch per attempt** — `low` — `patch`. Real and will be hit on every fetch failure (not unlikely in everyday use) — AD-9 only requires "timeout plus one retry," not zero-delay, so a short delay between attempts is a trivial, bounded improvement.
- **Retry-success-path and timeout-path are untested** — `medium` — `patch`. Verified by reading `tests/pipeline/sources/test_scraper_tier2.py`: only "both attempts fail" and "first attempt succeeds" are covered; "fails once then succeeds" and the `asyncio.wait_for` timeout branch have zero test coverage.
- **No `wait_for_selector` before `page.content()`** — `medium` — `patch`. `wait_until="domcontentloaded"` fires before JS-hydrated price widgets may populate; a one-line `page.wait_for_selector("#productTitle", timeout=...)` bounds this risk.
- **No custom `user_agent`/viewport on Playwright launch** — `maybe-false` — rejected. Unverified whether this actually affects Amazon's bot detection in practice; if true, impact is only `low` since a resulting block already degrades gracefully to `SourceFailure` (AD-4) rather than producing wrong data.
- **`ProductFacts.price` as `float` not `Decimal`** — `maybe-false` — rejected. No price arithmetic exists anywhere in this story's diff; if a later story's math needs more precision than float gives, that is `low` severity for USD-scale amounts and best revisited then.
- **`SourceFailure.reason` as plain `str` not `Literal`/`Enum`** — `maybe-false` — rejected. No current consumer branches on this field; a future drift risk with no named current harm, only `low` if it ever matters.
- **`_extract_specs` silently overwrites duplicate spec-table keys** — `low` — `patch`. Real edge case (a page with a repeated spec label loses data silently); fix is a trivial `setdefault` swap (first-value-wins).
- **Missing `/gp/aw/d/{ASIN}` and `/exec/obidos/ASIN/{ASIN}` URL shapes** — `medium` — `patch`. These are legitimate Amazon product URL shapes (mobile/legacy) wrongly rejected as invalid; fix is a bounded regex-alternation extension, same mechanism as the existing `/dp/` and `/gp/product/` shapes.
- **`.gitignore` missing `.coverage`/`htmlcov/`/editor/OS entries** — `low` — `patch`. Trivial, direct addition.
- **`Settings.scraper_proxy_url` has no format validation** — `low` — `patch`. A malformed value currently fails deep inside `browser.launch()` instead of at `Settings` construction; bounded fix (validate at the boundary).
- **No error-level log when retries are exhausted** — `low` — `patch`. Only per-attempt `logger.warning` calls fire today; a final `logger.error` before returning `SourceFailure` is a trivial, direct addition.
- **Trailing-dot Amazon hostname (`"amazon.com."`) wrongly rejected** — `low` — `patch`. Valid FQDN syntax; verified experimentally by Edge Case Hunter. Fix: `rstrip(".")` before the host-allowlist check.
- **`asyncio.CancelledError` not caught by `fetch()`'s `except Exception`** — `low` (currently unreachable) — `defer`. Verified as a real gap against the frozen "never raises... for any reason" wording (AD-4) — `CancelledError` is a `BaseException`, not caught by `except Exception`. No current caller cancels `fetch()` (no orchestrator exists yet), so this is dormant. Blindly catching and swallowing `CancelledError` is itself an asyncio anti-pattern that could break future cooperative cancellation — this needs a human/design call once an orchestrator with real cancellation semantics is built (Epic 4 / Story 1.9 territory), not a one-line patch now. Logged to `deferred-work.md`.
- **`_render`'s `browser.close()` in `finally` isn't itself time-bounded** — `low` — rejected. Could in principle let cleanup outlast the nominal 20s fetch timeout, but low-likelihood in everyday use and a safe fix requires careful async-cancellation handling, not a trivial correction — rejected per both conditions of the low-finding rule.
- **Untested ASIN-shape-rejection branch (verification-gap)** — `medium` — `patch`. Pre-verified by the verification-gap layer: changing `_ASIN_SHAPE.fullmatch` to `.match` still passes all 21 existing tests, confirming no test exercises "ASIN segment present but wrong shape." Fix: add parametrized cases (e.g. a too-long ASIN segment) to `test_non_amazon_or_malformed_url_raises`.

## Design Notes

- ASIN is extracted via regex against common Amazon URL shapes (`/dp/{ASIN}`, `/gp/product/{ASIN}`). The ASIN — not the raw URL — is what encodes "which exact variant," so dedup and variant-correctness both fall out of this one extraction step for free.
- `scraper_tier2.py` always renders via Playwright first, then parses the resulting DOM with BeautifulSoup — one code path, matching the single Tier 2 file named in the Architecture Spine's structural seed.
- Test fixtures are hand-written minimal HTML using Amazon's publicly documented DOM id/class conventions (e.g. `#productTitle`) — not copied from a real page — avoiding both ToS risk and live-site flakiness in tests.
- A distinct `CanonicalProduct` model (beyond `CanonicalProductId` + `ProductFacts`) is deliberately not created yet — nothing through Story 1.9 needs one; AD-11 lets a later story add it to `models/` in place if Evidence Bundle assembly (1.6) turns out to need it.

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all canonicalize + scraper_tier2 tests pass -- **ran: 21/21 passed**
- `uv run ruff check app/ tests/` -- expected: no lint errors -- **ran: All checks passed!**

**Manual checks (if no CLI):**
- Run `canonicalize()` and the Tier 2 scraper against one real Amazon product URL by hand (not in CI) to confirm it extracts sane title/price/specs from the live site. -- **not run** (requires a real network call + Playwright browser binaries, out of scope for this automated session); flagged below as a remaining risk.
