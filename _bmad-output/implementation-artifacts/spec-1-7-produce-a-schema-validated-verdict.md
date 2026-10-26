---
title: 'Produce a schema-validated verdict'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '631b0478734ac57edcf2cd636ec91f1cfd067f96'
context: ['docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md', '_bmad-output/implementation-artifacts/epic-1-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Evidence Bundle (Story 1.6) is assembled but nothing turns it into a trustworthy, structured verdict -- without validation and a deterministic confidence score, raw model output could reach the user unchecked, with a self-reported confidence number and uncited claims.

**Approach:** Add a `Verdict` schema (label, pros/cons with citations, reasoning, confidence, evidence basis) and a two-call LLM synthesis pipeline behind a new `LLMClient` port (mirroring `ProductSource`'s mockable-port pattern): a cheap model clusters review themes, a strong model synthesizes the final structured draft. Every pro/con's citation is resolved against the real Evidence Bundle; unresolved ones are dropped. If nothing resolvable remains, retry once with the error appended to the prompt; if that still leaves nothing, resolve to `InsufficientDataResult` rather than a hand-patched Verdict. `Verdict.confidence` is always overwritten by a new pure `compute_confidence()` function -- the LLM's own confidence value is discarded.

## Boundaries & Constraints

**Always:**
- `synthesize_verdict()` resolves every pro/con's citation against the real `EvidenceBundle`; any citation that doesn't resolve is dropped rather than shown (AD-4, never fabricated).
- If, after dropping unresolved citations, zero pros AND zero cons remain, that counts as a validation failure: retry once with the validation error appended to the prompt; if the retry also leaves nothing resolvable (or the underlying LLM call fails outright), return `InsufficientDataResult` -- never a hand-patched Verdict.
- `Verdict.confidence` is always `compute_confidence(bundle)`'s output; any confidence value the LLM produces is discarded, never surfaced.
- `Verdict.evidence_basis` and `Verdict.alternatives` are assembled by this code directly from the `EvidenceBundle`, never produced or chosen by the LLM.
- `compute_confidence()` is a pure function -- no I/O, deterministic for identical input, bounded to `[0.0, 1.0]`.
- `LLMClient.complete()` never raises (AD-4, AD-9): any failure -- network error, timeout, a malformed response -- degrades to `LLMCallFailure`, same retry/timeout pattern as `ScraperTier2Source`.
- The LLM's structured-output schema has no field for price history/trends, and the system prompt instructs it never to reason about price direction -- consistent with no price-history data existing in the Evidence Bundle (Tier 1 deferred). Any such claim is also uncitable by construction (`Citation.source_type` has no price-history option) and gets dropped by the same citation check every other claim goes through.
- `openai_api_key` and both model names load only from `Settings` (NFR-1) -- never hardcoded, never logged.
- Reuses Story 1.1-1.6's `EvidenceBundle`, `InsufficientDataResult`, and all their constituent types exactly as they are.

**Never:**
- No FastAPI app, routes, or SSE progress events in this story -- those are Story 1.8/1.9.
- No Reddit cross-check or multi-persona reasoning -- those are Epic 2/3.
- No live network calls to OpenAI in tests -- `synthesize_verdict()`/`compute_confidence()` are tested against a stub `LLMClient`, mirroring this project's `ProductSource` testing convention.
- No changes to `EvidenceBundle`, `assemble_evidence_bundle()`, or any Story 1.1-1.6 function/type.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Complete bundle, LLM succeeds first try | Valid `EvidenceBundle`; draft response has resolvable citations | Final `Verdict`, `confidence` overwritten by `compute_confidence()` | N/A |
| Zero resolvable claims on first try, retry succeeds | First draft resolves to zero pros/cons; retried draft (error appended) has resolvable ones | Final `Verdict` from the retry's output | N/A |
| Both attempts leave zero resolvable claims | Draft and retry both resolve to zero pros/cons | `InsufficientDataResult` | N/A |
| Underlying LLM call fails outright | `LLMClient.complete()` returns `LLMCallFailure` | `InsufficientDataResult` | Never raises |
| Some but not all citations unresolved | Draft has a mix of resolvable and unresolvable pros/cons | Unresolvable ones dropped; resolvable ones kept in the final Verdict | N/A |
| "Wait" label, no price-history data | Bundle has no price-history field at all | Reasoning/citations can only reference facts/reviews/alternatives -- never a price-trend claim | N/A |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- edit: add `openai` dependency
- `app/settings.py` -- edit in place (core/shared, AD-11, NFR-1): add `openai_api_key: str | None = None`, `llm_cheap_model: str = "gpt-4o-mini"`, `llm_strong_model: str = "gpt-4o"`
- `app/models/verdict.py` -- new (core/shared, AD-11): `VerdictLabel(str, Enum)` (BUY/SKIP/WAIT); `Citation(BaseModel)` (`source_type: Literal["review", "alternative", "product_fact"]`, `source_index: int | None`, `quote: str`); `ProConItem(BaseModel)` (`text: str`, `citation: Citation`); `EvidenceBasis(BaseModel)` (`review_count: int`, `is_low_signal: bool`, `alternatives_count: int`, `source_tier: SourceTier`); `Verdict(BaseModel)` (`schema_version: int`, `label`, `confidence`, `evidence_basis`, `pros: list[ProConItem]`, `cons: list[ProConItem]`, `alternatives: list[ProductFacts]`, `reasoning_summary: str`)
- `app/models/llm.py` -- new: `LLMCallFailure(BaseModel)` (`reason`, `detail`); `DraftVerdict(BaseModel)` (the LLM's own structured-output target: `label`, `confidence` [discarded], `pros`, `cons`, `reasoning_summary` -- no `evidence_basis`/`alternatives`, those are code-assembled); `ThemeClusters(BaseModel)` (`pros_themes: list[str]`, `cons_themes: list[str]`, the cheap-model call's output)
- `app/pipeline/llm_client.py` -- new (core/shared, AD-3-style port): `LLMClient` Protocol (`async def complete(self, *, system_prompt: str, user_prompt: str, response_model: type[T], model: str) -> T | LLMCallFailure`); `OpenAIClient` implementation wrapping `openai.AsyncOpenAI().chat.completions.parse(...)`, same timeout/retry pattern as `ScraperTier2Source`, never raises
- `app/pipeline/confidence.py` -- new (core/shared, AD-11): `compute_confidence(bundle: EvidenceBundle) -> float` -- pure, deterministic, bounded `[0.0, 1.0]`
- `app/pipeline/synthesis.py` -- new (core/shared, AD-11): `async def synthesize_verdict(bundle: EvidenceBundle, llm: LLMClient) -> Verdict | InsufficientDataResult` -- the two-call, citation-resolution, retry-once pipeline; `_resolve_citation(citation, bundle) -> str | None` (returns the resolved excerpt or `None`)
- `app/pipeline/orchestrator.py` -- edit in place (core/shared, AD-11, AD-1): add `produce_verdict(url: str, source: ProductSource, llm: LLMClient) -> Verdict | InsufficientDataResult`, composing `assemble_evidence_bundle()` then `synthesize_verdict()`, short-circuiting on `InsufficientDataResult` from either
- `tests/pipeline/test_confidence.py` -- new: covers `compute_confidence()`'s bounded/deterministic behavior
- `tests/pipeline/test_synthesis.py` -- new: covers the I/O Matrix using a stub `LLMClient` (no live OpenAI calls)
- `tests/pipeline/test_orchestrator.py` -- edit: add tests for `produce_verdict()`'s composition/short-circuit behavior

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- add `openai` dependency
- [x] `app/settings.py` -- add `openai_api_key`/model-name fields -- NFR-1 config loading
- [x] `app/models/verdict.py` -- add `Verdict` and its constituent types -- the single frontend contract
- [x] `app/models/llm.py` -- add `LLMCallFailure`, `DraftVerdict`, `ThemeClusters` -- typed LLM-facing contracts
- [x] `app/pipeline/llm_client.py` -- add `LLMClient` Protocol + `OpenAIClient` -- the mockable LLM port
- [x] `app/pipeline/confidence.py` -- implement `compute_confidence()` -- deterministic, LLM-independent score
- [x] `app/pipeline/synthesis.py` -- implement `synthesize_verdict()` -- two-call synthesis, citation resolution, retry-once
- [x] `app/pipeline/orchestrator.py` -- add `produce_verdict()` -- completes the end-to-end v1 pipeline
- [x] `tests/pipeline/test_confidence.py` -- cover `compute_confidence()` -- proves boundedness/determinism
- [x] `tests/pipeline/test_synthesis.py` -- cover the I/O Matrix with a stub `LLMClient` -- proves the retry/drop/fail guarantees
- [x] `tests/pipeline/test_orchestrator.py` -- cover `produce_verdict()`'s composition -- proves the short-circuit chain

**Acceptance Criteria:**
- Given a complete Evidence Bundle, when the LLM's draft response has at least one resolvable pro or con, then it is accepted and its confidence is overwritten by `compute_confidence()`.
- Given a draft response with zero resolvable pros/cons, when this happens, then one retry is attempted with the validation error appended to the prompt.
- Given both the original and retried responses leave zero resolvable pros/cons (or the LLM call fails outright), when this happens, then the result is `InsufficientDataResult`, never a hand-patched Verdict.
- Given a successful Verdict, when produced, then its `evidence_basis` and `alternatives` come from the Evidence Bundle, not the LLM, and every pro/con's citation resolves to a real bundle item.

## Implementation Notes

- Added `openai>=3.39.0` via `uv add openai` (updates `pyproject.toml` and `uv.lock`).
- `app/settings.py`: added `openai_api_key: str | None = None`, `llm_cheap_model: str = "gpt-4o-mini"`, `llm_strong_model: str = "gpt-4o"`; also documented the three new keys in `.env.example` for consistency with `scraper_proxy_url`'s existing entry (not in the Code Map, low-risk documentation-only addition).
- `app/models/verdict.py`: added `VerdictLabel`, `Citation` (`source_type: Literal["review", "alternative", "product_fact"]` -- deliberately no price-history option, per AD-3/FR-9's structural guardrail), `ProConItem`, `EvidenceBasis`, `Verdict` (`confidence` and `schema_version` both `Field`-constrained: confidence to `[0.0, 1.0]`, schema_version fixed at `1` for this story).
- `app/models/llm.py`: added `LLMCallFailure`, `DraftVerdict` (reuses `verdict.py`'s `ProConItem`/`VerdictLabel` rather than duplicating shapes), `ThemeClusters`.
- `app/pipeline/llm_client.py`: `LLMClient` Protocol plus `OpenAIClient` wrapping `openai.AsyncOpenAI().chat.completions.parse(...)`, same timeout (30s) + one-retry pattern as `ScraperTier2Source`. One robustness fix beyond the spec's literal wording: `AsyncOpenAI(...)` itself raises `openai.OpenAIError` at construction time when `openai_api_key` is unset/invalid, which would have let `OpenAIClient.__init__` raise -- inconsistent with this codebase's "never raises" convention for external-dependency clients (AD-4, AD-9). Fixed by constructing the `AsyncOpenAI` client lazily inside `complete()`'s own try/except, so a missing/invalid key degrades to the same `LLMCallFailure` as any other call failure instead of crashing at instantiation. Verified manually (see Verification).
- `app/pipeline/confidence.py`: `compute_confidence()` -- three additive, independently-capped components (source-tier weight 0.4/0.1, review-signal weight 0.3, sample-depth weight 0.3 saturating at 20 reviews) summing to at most `1.0` and at least `0.0` by construction, with a defensive `max(0.0, min(1.0, ...))` clamp as a belt-and-suspenders guarantee.
- `app/pipeline/synthesis.py`: `synthesize_verdict()` implements the two-call pipeline exactly per the Boundaries/I-O Matrix: theme-clustering call (cheap model) -> synthesis call (strong model) -> `_resolve_citation()`-based citation resolution -> retry-once-with-validation-error-appended if zero pros/cons resolve -> `InsufficientDataResult` if the retry also leaves nothing resolvable or any LLM call fails outright. `confidence`/`evidence_basis`/`alternatives` are always code-assembled, never taken from the LLM. One deliberate deviation from the architecture Stack section's literal framing, documented in the module docstring: the strong-model synthesis prompt includes the bundle's already-bounded, already-sampled indexed reviews/alternatives (not the themes alone) because AD-7's citation-resolution requirement means the model needs an indexed view of real evidence to produce a citation that can resolve at all -- themes still drive the primary pros/cons signal, but citations need something real to point at.
- `app/pipeline/orchestrator.py`: added `produce_verdict(url, source, llm) -> Verdict | InsufficientDataResult`, composing `assemble_evidence_bundle()` then `synthesize_verdict()` with the short-circuit the spec requires.
- Tests: `tests/pipeline/test_confidence.py` (new, 9 tests covering boundedness/determinism/monotonicity without pinning the exact calibration), `tests/pipeline/test_synthesis.py` (new, 15 tests covering every I/O Matrix row plus the price-history structural guardrail and model-routing), `tests/pipeline/test_orchestrator.py` (extended with a stub `LLMClient` and 4 new tests covering `produce_verdict()`'s happy path and both short-circuit paths).
- **Review patch round:** all 9 `patch`-routed findings were fixed: `openai_api_key` now normalizes an empty string to `None` (mirroring `scraper_proxy_url`'s pattern); `_resolve_citation()` now rejects quotes shorter than 8 characters before attempting a containment match; all three `InsufficientDataResult` constructions in `synthesize_verdict()` now carry `source_tier`; both prompt-builders now include `review.title` alongside the body; the alternatives section of the synthesis prompt now falls back to "unknown" for a missing price; the model-routing test now overrides `LLM_CHEAP_MODEL`/`LLM_STRONG_MODEL` via `monkeypatch.setenv` and asserts the override threaded through, rather than comparing against a freshly-built `Settings()` from the same ambient environment; `_StubLLMClient` was deduplicated into a shared `tests/pipeline/conftest.py` fixture; two new tests prove a `None`-indexed review/alternative citation is dropped rather than raising; and `orchestrator.py`'s module docstring no longer implies no code path anywhere in the file calls LLM synthesis. One finding was deferred (no prompt-injection defense for untrusted review text -- open-ended, research-level fix, logged to `deferred-work.md`). Four findings were rejected: a false claim that `openai>=3.39.0` doesn't exist (refuted by direct import/version/API-signature check against the installed package); two findings mirroring already-accepted patterns from Stories 1.1/1.2/1.3/1.5 (raw-exception-text passthrough into `InsufficientDataResult.detail`; blanket exception retry with no status-code-aware exemption); and a retry-prompt-specificity enhancement judged a quality improvement rather than a correctness defect. Full suite is 142/142 passing, `ruff check` clean.
- Full suite: 140/140 passing (`uv run pytest tests/pipeline -v`); `uv run ruff check app/ tests/` clean.
- No review-loop pass (blind-hunter/edge-case-hunter/verification-gap, as Story 1.6's Review Triage Log shows) was run against this implementation -- only self-review during implementation (including the `OpenAIClient` construction-time fix above, caught by manually exercising it rather than by an automated reviewer). `review_loop_iteration` is left at `0` and `status` at `in-progress` so a review pass can still run before this story is closed out.

## Spec Change Log

## Review Triage Log

- **`Settings.openai_api_key` has no validator normalizing an empty string to `None`, unlike `scraper_proxy_url`'s own `_validate_scraper_proxy_url`** (`app/settings.py`) — `medium` — `patch`. Verified: if the actual `.env` file ships a literal blank `OPENAI_API_KEY=` (e.g. copied from `.env.example` without filling it in), `Settings().openai_api_key` becomes `""`, and `OpenAIClient._get_client()` passes that explicit empty string to `AsyncOpenAI(api_key="")` -- worse than `None`, since the SDK can no longer fall back to its own env-var lookup or raise a clear missing-key error. Same footgun class this project already solved once for `scraper_proxy_url`. Trivial fix (the same strip-and-normalize pattern).
- **`_resolve_citation()`'s case-insensitive substring match has no minimum quote length**, so a short/generic quote (e.g. "good") could spuriously resolve against almost any review/fact text (`app/pipeline/synthesis.py`) — `low` — `patch`. Verified: the check is pure `in` containment with no length/word-count floor. Doesn't break the core "must exist in real text" guarantee, but meaningfully weakens it. Trivial fix (require a minimum quote length before attempting the match).
- **`InsufficientDataResult` returned from `synthesize_verdict()`'s three failure paths never sets `source_tier`, even though `bundle.product_facts.source_tier` is already known** (`app/pipeline/synthesis.py`) — `low` — `patch`. Verified: inconsistent with `resolve_product_facts()`'s own pattern, which does populate it from `SourceFailure.source_tier`. Trivial fix (pass it through on all three constructions).
- **`Review.title` is collected by the scraper but never included in either LLM prompt** (`app/pipeline/synthesis.py`) — `low` — `patch`. Verified: `_build_theme_user_prompt`/`_build_synthesis_user_prompt` only emit `review.body`. Free, directionally-positive signal left on the table. Trivial fix (include the title alongside the body where present).
- **`test_theme_call_uses_cheap_model_and_synthesis_call_uses_strong_model` doesn't prove the setting is genuinely threaded through** (`tests/pipeline/test_synthesis.py`) — `low` — `patch`. Verified: it builds its own `Settings()` from the same unmodified environment `synthesize_verdict()` reads from and compares against that, so it would pass even if the code bypassed `Settings` entirely and hardcoded today's default literals. It does still catch a cheap/strong model-name swap. Trivial fix (override the env var before calling, assert the stub received the overridden value).
- **`_StubLLMClient` is duplicated verbatim across `test_orchestrator.py` and `test_synthesis.py`** — `low` — `patch`. Verified by direct comparison. This port has already been extended twice before (`fetch_reviews`, `find_candidate_alternatives`) and now a third time (`LLMClient`) -- duplicated stubs are a recurring, not hypothetical, maintenance cost in this project. Fix (move to a shared `tests/pipeline/conftest.py` fixture/helper) is small and mechanical, not disproportionate.
- **The alternatives section of the synthesis prompt shows a literal "price: None" instead of the "unknown" fallback used for the product's own price** (`app/pipeline/synthesis.py`) — `low` — `patch`. Verified: `_build_synthesis_user_prompt`'s alternatives loop interpolates `alternative.price` directly with no `None` guard, unlike `facts.price` just above it in the same function. Trivial fix (mirror the existing fallback).
- **No test proves a `"review"`/`"alternative"`-typed citation with `source_index=None` is dropped rather than crashing** (`tests/pipeline/test_synthesis.py`) — `medium` — `patch` (verification-gap finding, pre-verified). The guard against this (`if citation.source_index is None: return None`) already exists and is correct in the current code, but no test exercises it -- a regression that removed or inverted it would ship silently, defeating `synthesize_verdict()`'s own "never raises" guarantee. Fix: add the two tests (review- and alternative-typed citations with a `None` index).
- **`orchestrator.py`'s module docstring still says "No FastAPI app or LLM synthesis exists yet... this function has no code path that calls one," but this same file now defines `produce_verdict()`, which does call `synthesize_verdict()`** — `low` — `patch`. Verified directly. The sentence is stale and could mislead a future reader. Trivial fix (qualify it as describing `resolve_product_facts()` specifically, not the whole file).
- **No defense against prompt-injection in untrusted, scraped review text passed into both LLM prompts** — `maybe-false` — `defer`. Real, named risk class (adversarial review text steering `draft.label`/`reasoning_summary`, which aren't citation-gated the way individual pros/cons are) but genuinely open-ended to fix -- a proper defense (content delimiting, output-side sanity checks, or a classifier) is research-level design work, not a contained patch. If exploited, severity would be `medium` (a manipulated verdict label/reasoning, not a system compromise). Logged to `deferred-work.md`.
- **`pyproject.toml` pins `openai>=3.39.0`, claimed not to exist on PyPI (the SDK being on a 1.x series)** — `false` — rejected. Refuted directly: `uv run python -c "import openai; print(openai.__version__)"` prints `3.39.0`, and `AsyncOpenAI().chat.completions.parse` exists at that version with exactly the `messages`/`model`/`response_format` signature this code calls (confirmed via `inspect.signature`). The reviewer's own knowledge of the SDK's version line is stale relative to this project's October 2026 "now."
- **`LLMCallFailure.detail` (raw `str(exc)`) flows unfiltered into the user-facing `InsufficientDataResult.detail`** — `low` — rejected. Mirrors the exact, already-accepted pattern from Story 1.1/1.2 (`SourceFailure.detail` → `InsufficientDataResult.detail` already does the same raw-exception passthrough); not a new regression introduced by this diff, and redacting it would be a broader, cross-cutting concern touching multiple prior stories' code, not specific to this one.
- **`OpenAIClient.complete()` retries every exception identically, never distinguishing retryable (timeout/5xx) from non-retryable (401/400) failures** — `low` — rejected. Mirrors the exact, already-accepted blanket-retry pattern from `ScraperTier2Source.fetch()`/`fetch_reviews()`/`find_candidate_alternatives()` (Stories 1.1/1.3/1.5); a status-aware retry policy is absent from every retry loop in this codebase today, not unique to this diff.
- **The retry prompt (`_VALIDATION_ERROR_MESSAGE`) repeats generic validation rules rather than naming which specific indices/quotes were fabricated** — `low` — rejected. A retry-success-rate quality enhancement, not a correctness defect -- the bounded fallback (one retry, then an honest `InsufficientDataResult`) already satisfies this story's ACs. Threading structured per-citation failure detail into the retry prompt is a non-trivial enhancement, not a direct correction.

## Design Notes

- `compute_confidence()`'s exact formula (source-tier weight + review-signal weight + sample-depth weight, saturating at 20 reviews) is this story's own calibration -- the architecture names the INPUTS (review volume, Source Tier) but not an exact formula; a future story can retune the weights without changing the function's shape.
- Two LLM calls per the architecture's cost-control decision: a cheap model clusters raw review text into pros/cons THEMES first; the strong model synthesizes the final structured draft from those themes plus product facts and alternatives. **Correction during implementation:** the architecture's "never from raw review text directly" framing turned out to be incompatible with this same story's citation-resolution requirement -- a model given only abstracted themes has no quotable text to cite that could ever resolve. The strong-model prompt therefore also includes the bundle's already-bounded, already-sampled reviews/alternatives (never the raw, un-sampled page) alongside the themes, so citations are checkable rather than guaranteed-unresolvable. This supersedes the line above; see `pipeline/synthesis.py`'s module docstring for the full reasoning.
- "Validation failure" in this story's retry logic specifically means "zero resolvable pros/cons after citation-checking," not a raw JSON-parse failure -- OpenAI's Structured Outputs feature already guarantees schema-shape conformance, so the domain-level citation check is the validation layer this codebase actually needs to own.
- The "Wait" label's price-trend guardrail is enforced structurally, not by scanning reasoning text: `Citation.source_type` has no price-history option, so any such claim is uncitable by construction and gets dropped by the same citation-resolution check every other claim goes through -- consistent with Story 1.2's "never reaches synthesis" structural pattern.
- `OpenAIClient` (the real `LLMClient` implementation) is not itself unit-tested against a live API, mirroring `ScraperTier2Source._render()`'s own untested-via-live-network status -- only `synthesize_verdict()`/`compute_confidence()` are tested, against a stub `LLMClient`.

## Verification

**Commands:**
- `uv run pytest tests/pipeline -v` -- expected: all existing tests plus the new confidence/synthesis/orchestrator tests pass. Actual: 140/140 passed.
- `uv run ruff check app/ tests/` -- expected: no lint errors. Actual: `All checks passed!`
- Manual check (not a Code Map item, done to verify an issue found during implementation): constructed `OpenAIClient(Settings(openai_api_key=None))` and called `complete()` directly -- confirmed it degrades to `LLMCallFailure` (two logged attempts, then `reason="llm_call_failed"`) instead of raising at construction, after the lazy-client fix described in Implementation Notes.
