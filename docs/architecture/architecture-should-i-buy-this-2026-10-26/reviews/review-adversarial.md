---
name: 'Adversarial Review — Architecture Spine'
type: review
target: docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md
mandate: 'Construct two units one level down that each obey every AD to the letter yet still build incompatibly.'
units-under-test: ['scraper', 'reddit', 'alternatives', 'llm-synthesis', 'confidence-score', 'evidence-trail', 'caching', 'ui']
ad-count: 10
created: '2026-10-26'
verdict: FAIL — 8 concrete incompatible-but-compliant pairs constructed; several are severe (silent fabrication, silent crash, silent mis-render)
---

# Adversarial Review — Should I Buy This? Architecture Spine

## Method

For each pair of feature branches, I checked (a) whether any AD's `Binds` list actually covers both branches touching a shared boundary, and (b) whether the `Rule` text, read literally, leaves a degree of freedom both branches could fill differently while each remains individually compliant. Every finding below is a constructed concrete build, not an abstract risk category: two things a solo developer could plausibly write in two different work sessions, each citing a real AD as justification, that do not fit together.

## Verdict

**FAIL.** 8 concrete pairs found. Three (F1, F3, F4/F5) are structural — they stem from entities (the `alternatives` branch's exemption from AD-4/AD-9, `EvidenceBundle`'s model, `orchestrator.py` itself) that no AD actually assigns a sole owner to, despite being load-bearing shared state. These should be closed before any branch work starts, not discovered during integration.

---

## F1 — `alternatives` is the one branch AD-4 and AD-9 forgot (severe)

**AD-4 binds:** scraper, reddit, llm-synthesis. **AD-9 binds:** reddit, scraper. `alternatives` is in neither list, despite FR-8 requiring it to find comparable products — almost certainly by querying Amazon, the same unreliable external dependency AD-9 exists to protect against.

- **Unit A — `llm-synthesis` dev (reads AD-4 literally):** builds `synthesis.py` trusting that every stage's output flowing into `EvidenceBundle` is either real or an explicit typed failure, per AD-4's "no stage returns fabricated or partially-invented data disguised as success." Writes no defensive fabrication-detection on the `alternatives` field of the bundle — AD-5 already says the bundle is schema-validated and the *only* input, so by construction it should be trustworthy.
- **Unit B — `alternatives` dev (reads AD-4's `Binds` line literally):** notices `alternatives` is not named in AD-4 or AD-9. To ship FR-8 without building retry/timeout/typed-failure plumbing nothing compels, the dev takes the easy path: when the comparable-products search comes back empty or blocked, return a plausible-looking `list[Alternative]` anyway (e.g. ask the LLM for "similar products in this category" from its own knowledge, or hardcode category defaults) rather than a failure sentinel — because no rule requires `alternatives` to ever signal failure. Separately, any unhandled timeout/exception from the Amazon call is allowed to propagate, since AD-9's retry-then-degrade obligation doesn't name this branch either.
- **Why both are letter-compliant:** Unit A satisfies AD-4/AD-5 exactly as written. Unit B violates no AD text at all — the binds lists are the literal scope of the rule, and `alternatives` is outside both.
- **Concrete incompatibility:** Fabricated-but-well-formed "alternatives" data flows through `EvidenceBundle` (AD-5) into the LLM prompt and ultimately the Verdict as if it were scraped fact — directly contradicting the product's core "honest, evidence-based" value proposition, with zero AD violated. Separately, a stalled Amazon alternatives lookup can crash or hang the whole request, something AD-9 exists specifically to prevent everywhere else in the pipeline.
- **Close with:** Add `alternatives` to AD-4's and AD-9's `Binds` lists (or add a new AD-11 stating all stages that touch an external dependency or produce evidence are subject to AD-4/AD-9 by default, closing the "binds list as the only scope" loophole generally).

## F2 — `alternatives` has no AD-3 port obligation, so it can grow its own scraper

**AD-3 binds:** scraper stage only. `ProductSource.fetch(url) -> ProductFacts | SourceFailure` is the sanctioned, single way to pull Amazon HTML.

- **Unit A — `scraper` dev:** reads "the orchestrator calls the interface, never a concrete scraper class" as meaning *all* Amazon access in the system funnels through `sources/scraper_tier2.py` + `degraded_tier3.py`, and builds nothing else to handle Amazon fetches, trusting that's the only entry point in the codebase.
- **Unit B — `alternatives` dev:** needs product facts (price, rating, title) for candidate comparable products, but AD-3 doesn't bind `alternatives`, so nothing says it must go through the port. Writes its own inline Playwright/BeautifulSoup scrape inside `alternatives.py` — different wait strategy, different selectors, no Tier 2/Tier 3 fallback, not wrapped by AD-9 (per F1) — reasoning "AD-3 is `scraper`'s rule, not mine."
- **Why both are letter-compliant:** AD-3's `Binds` line names only `scraper`; nothing elsewhere compels `alternatives` to reuse the port.
- **Concrete incompatibility:** Two independent, diverging Amazon-scraping code paths exist in the same app — different failure modes, different ToS-risk posture (AD-3's own Deferred section calls Amazon ToS risk "higher-stakes"), and a second place that will silently break whenever Amazon's markup changes, with no shared fix.
- **Close with:** AD-3's rule should read "...the sole mechanism any stage uses to retrieve Amazon product data" and its `Binds` should include every stage that needs `ProductFacts` for *any* product, canonical or candidate (i.e. add `alternatives`).

## F3 — `EvidenceBundle` has no assigned owner, so its shape is two stages' guess (severe)

Neither the branch list, the structural seed, nor the Capability Map assigns `pipeline/evidence.py` (which assembles `EvidenceBundle`) to a specific one of the 8 branches. AD-5 binds only `llm-synthesis` and talks about *consuming* the bundle; AD-7 binds `evidence-trail` and talks about the *Verdict*, not the bundle. Nothing says who writes the `EvidenceBundle` Pydantic model.

- **Unit A — `llm-synthesis` dev:** since AD-5 makes `EvidenceBundle` llm-synthesis's only input, and this dev is the one who needs to hand it to the OpenAI structured-output call, treats designing the bundle as part of "my" branch — embeds full review text and Reddit thread excerpts inline (`reviews: list[ReviewText]`, `reddit_threads: list[RedditThread]`) so the prompt-builder has everything it needs in one flat object.
- **Unit B — `evidence-trail` dev:** since "evidence" is this branch's namesake and AD-7 (which binds `evidence-trail`) is about traceability of the Verdict back to sources, this dev also edits `models/` and shapes `EvidenceBundle` as a citation-first structure — `citations: list[Citation]` where each citation is a `source_id` pointer into separate lookup tables, deliberately *not* embedding raw text (to keep the trail lightweight and avoid duplicating data that's also cached in `cache/store.py`).
- **Why both are letter-compliant:** AD-1 says every stage has one typed input/output; AD-5 says llm-synthesis's input is "the finalized `EvidenceBundle` model" — neither says who defines that model or forbids either shape. The Consistency Conventions table only fixes the *name* (`EvidenceBundle`), not its fields.
- **Concrete incompatibility:** Whichever model lands second either breaks the import (model redefined, field names don't match) or silently coexists as two classes both called `EvidenceBundle` in different modules — a direct violation of the stated intent ("never duplicated or hand-rolled") that AD-5/AD-7 as written don't actually prevent, because neither AD assigns authorship.
- **Close with:** Add an explicit rule (or extend AD-5) naming exactly one owner for the `EvidenceBundle` model and the `evidence.py` assembly module — e.g. "the `evidence-trail` branch owns `models/evidence_bundle.py`; `llm-synthesis` only consumes it, and any field it needs that doesn't exist is a change request against `evidence-trail`, never a local redefinition."

## F4 — `orchestrator.py` is claimed by AD-8 and AD-10 but owned by none of the 8 branches (severe)

AD-8 says "the orchestrator checks cache → acquires lock → runs pipeline → writes cache → releases" — binding `caching`. AD-10 says "each pipeline stage, on entry, publishes its name to a per-job `asyncio.Queue` the orchestrator creates" — binding `ui, orchestrator`. But `orchestrator` is not one of the 8 feature branches; nothing says whether `caching` or `ui` (or neither) is the one who actually edits `pipeline/orchestrator.py`.

- **Unit A — `caching` dev:** implements AD-8's cache→lock→run→write sequence directly inside `orchestrator.py`, since AD-8 names the orchestrator as the owner of that logic and `caching` is the branch AD-8 binds. Treats `orchestrator.py` as caching's file to edit.
- **Unit B — `ui` dev:** implements AD-10's per-job `asyncio.Queue` creation and SSE-publishing hook directly inside `orchestrator.py`, since AD-10 also names the orchestrator and `ui` is the branch AD-10 binds. Also treats `orchestrator.py` as its file to edit, in a separate, later work session, without re-reading caching's prior change.
- **Why both are letter-compliant:** each dev is doing exactly what the AD binding them tells them to do, in the one module both ADs point at by name.
- **Concrete incompatibility:** two independent, uncoordinated edits to the same orchestrator run loop, written months apart by the same solo developer who has forgotten the other session's exact control flow — e.g. `ui`'s queue-creation might get inserted *before* `caching`'s cache-check (so a job_id and SSE stream get created even for what turns out to be a pure cache hit), or `caching`'s early-return-on-cache-hit might skip past the point where `ui`'s queue was supposed to be created, breaking whichever of the two assumptions the other wasn't told about. Neither AD specifies relative ordering between "check cache" and "create per-job queue."
- **Close with:** State explicitly in the spine which single branch owns `pipeline/orchestrator.py` (it reads most naturally as a 9th, ungoverned unit — either formally fold it into one existing branch, e.g. `caching`, or add an AD that fixes the orchestrator's internal step order: canonicalize → cache-check → [hit: return cached Verdict, no queue] → [miss: create queue → acquire lock → run stages → cache write → release → final SSE event]).

## F5 — Cache hits and the SSE job lifecycle disagree on whether a job always exists

Direct consequence of F4's ambiguity, but a distinct, testable behavioral clash worth calling out on its own.

- **Unit A — `caching` dev:** reads AD-8's "no stage writes its own ad-hoc cache" and "coalescing" intent as license to build a fast path: on a cache hit, return the cached `Verdict` straight from the `POST` handler, synchronously, with no `job_id` and no pipeline run at all — this is the entire point of caching, and AD-8 never says a job must be created regardless of cache state.
- **Unit B — `ui` dev:** reads AD-10 literally — "`GET /jobs/{job_id}/events` ... yields one SSE event per stage transition, then a final event carrying the `Verdict`" — and builds the frontend to *always* `POST` the URL, receive a `job_id`, then immediately open an `EventSource` against it, because AD-10 describes this as the one defined channel and gives no cache-hit exception.
- **Why both are letter-compliant:** AD-8 says nothing about SSE; AD-10 says nothing about cache hits. Each dev followed their own AD to the letter and never had to resolve the other's assumption.
- **Concrete incompatibility:** on a cache hit, the frontend opens an `EventSource` against a `job_id` that was never created — either a 404, a hang, or (if `ui` defensively falls back to polling the missing endpoint) a silent reintroduction of the exact "polling endpoint to keep in sync with the stream" AD-10 explicitly says not to build.
- **Close with:** AD-10 (or AD-8) should state the cache-hit contract explicitly: either every request still gets a `job_id` and a trivial one-event SSE stream (uniform client behavior, cache-hit cost is just "skip straight to the final event"), or the `POST` response itself carries a `cache_hit: bool` the UI branches on before deciding whether to open `EventSource` at all.

## F6 — Reddit's honest "degraded" signal is indistinguishable from "confirmed nothing found" one hop downstream

AD-9 requires reddit to "degrade to an explicit empty/partial result consumed by AD-4" on timeout/failure. AD-4 requires that result to be a typed failure/sentinel, never treated as complete. But `EvidenceBundle`'s schema (ownership gap per F3) is not specified to carry a per-source degraded flag.

- **Unit A — `reddit` dev:** fully AD-9/AD-4 compliant — on API failure/rate-limit, returns something like `RedditResult(status="degraded", threads=[], note="Reddit unavailable")`, a rich, explicit, typed sentinel distinguishing "degraded" from "checked and found nothing."
- **Unit B — whoever builds `evidence.py`/`EvidenceBundle` (F3's unresolved owner):** builds the bundle's Reddit field as simply `reddit_threads: list[RedditThread]` (empty list = no signal), because nothing in AD-5 or the Consistency Conventions table reserves a field for per-source degradation status, and an empty list is the obviously-compliant typed representation of "nothing to show."
- **Why both are letter-compliant:** AD-9/AD-4 only constrain what `reddit.py` returns, not what `EvidenceBundle` must preserve from it. AD-5 only constrains what shape reaches the LLM, not whether it's lossy relative to upstream.
- **Concrete incompatibility:** `status="degraded"` gets discarded at the `evidence.py` boundary; the LLM and `compute_confidence` (AD-6) both see "zero Reddit threads" and treat it as "this product has no online discussion" (a real, confidence-relevant fact) rather than "Reddit was unreachable, this says nothing about the product" (a missing-data fact that should *lower* confidence differently, or be disclosed to the user). The product silently violates its own "honest failure, no fabrication" value one module past the stage that was careful to uphold it.
- **Close with:** Extend AD-4 or AD-6 to require that `EvidenceBundle` (or `Verdict`) preserve a per-source availability flag (e.g. `reddit_status: Literal["ok","degraded","unavailable"]`) that `compute_confidence` must consume, closing the "typed sentinel gets flattened to an empty collection" gap.

## F7 — `Verdict` is "versioned" with no stated mechanism, so synthesis and ui drift across work sessions

AD-7 says the `Verdict` model is "defined once, versioned, imported by both sides — never duplicated or hand-rolled," but specifies no version field, migration rule, or contract test tying the UI templates to the model.

- **Unit A — `llm-synthesis` dev (a later work session):** needs to resolve PRD Open Question 5 (multi-persona disagreement flag) and changes `persona_results` from `list[PersonaResult]` to `dict[str, PersonaResult]` (keyed by persona name) because it makes the disagreement-detection code cleaner. Imports the one shared `Verdict` model, edits it in place — exactly what AD-7 asks for ("never duplicated").
- **Unit B — `ui` dev (an earlier work session, not revisited):** wrote `web/templates/verdict.html` against `Verdict` as it existed then: `{% for p in verdict.persona_results %}` iterating a list of `PersonaResult` objects.
- **Why both are letter-compliant:** AD-7 requires a single, imported, non-duplicated model — both sessions honor that. Nothing in AD-7, the Capability Map, or CI (lint/test/smoke, per the spine's CI section) forces a cross-branch check when the shared model's field *types* change, only that it not be duplicated.
- **Concrete incompatibility:** Jinja is permissive — iterating a `dict` yields its string keys, not `PersonaResult` objects. The template renders without raising (no loud failure), silently showing persona names where it meant to show persona verdicts/scores. This is exactly the "drift between work sessions" risk the spine is supposed to guard against, and it reaches production (or at least the smoke test, which only hits `GET /health`, not a rendered Verdict page) undetected.
- **Close with:** AD-7 should require (a) an explicit `schema_version` field on `Verdict`, and (b) at least one golden-output test in `tests/` that renders a real template against the current model and asserts on content, so a shape change that the smoke test can't see still fails CI.

## F8 — Confidence-score and evidence-trail both have a natural claim on "why is this uncertain"

AD-6 gives `confidence-score` a pure `compute_confidence(evidence) -> float`. AD-7 gives `evidence-trail` the `evidence_trail` field on `Verdict`. Neither AD says which of them owns the *narrative explanation* of low confidence — a thing both branches have an obvious, independent motive to add.

- **Unit A — `confidence-score` dev:** to make the deferred "low-confidence threshold" (PRD Open Question 4, explicitly left to this branch per Deferred section) legible to the user, adds `confidence_rationale: str` alongside the `confidence: float` field it already owns per AD-6 — e.g. "Low confidence: only 3 reviews sampled, Reddit unavailable."
- **Unit B — `evidence-trail` dev:** independently, to satisfy AD-7's "evidence trail" intent (explaining what evidence backs the Verdict), builds `evidence_trail: list[EvidenceCitation]` that *also* includes synthetic citations like `"Reddit: unavailable"` and `"Reviews: only 3 sampled (below threshold)"` — the same underlying facts, phrased independently, assembled at a different pipeline point (evidence_trail is built before/alongside synthesis; confidence is computed after the LLM draft per AD-6).
- **Why both are letter-compliant:** AD-6 only constrains the `confidence` float's computation method, not what else `confidence-score` may add nearby; AD-7 only constrains `Verdict`'s role as the single frontend contract, not what the evidence trail may describe.
- **Concrete incompatibility:** two independently-authored, possibly-contradictory explanations of the same low-confidence condition surface in the UI (e.g. one says "Reddit unavailable," the other, computed at a different pipeline stage/time, says "no Reddit discussion found" per F6) — a user-facing inconsistency with no single source of truth, even though every individual AD rule was followed.
- **Close with:** Name, in AD-7's rule, exactly one field as the sole owner of "why" text (e.g. `evidence_trail` is the only place explanatory strings live; `confidence-score` may only ever emit the float) so the two branches can't both reach for the same narrative real estate.

---

## Summary Table

| # | Pair | Shared boundary | Each complies with | Failure mode |
| --- | --- | --- | --- | --- |
| F1 | alternatives vs llm-synthesis/scraper/reddit | honesty + resilience norms | AD-4/AD-9 `Binds` lists (literal scope) | silent fabrication; silent crash |
| F2 | alternatives vs scraper | Amazon access | AD-3 `Binds` (literal scope) | duplicate, diverging scraper |
| F3 | llm-synthesis vs evidence-trail | `EvidenceBundle` shape | AD-5, AD-7 (no owner named) | model/field clash |
| F4 | caching vs ui | `orchestrator.py` | AD-8, AD-10 (no owner named) | uncoordinated control-flow edits |
| F5 | caching vs ui | cache-hit vs SSE job lifecycle | AD-8, AD-10 (no cache-hit case) | missing job_id / dead EventSource |
| F6 | reddit vs evidence assembly | degraded-signal fidelity | AD-9/AD-4 vs AD-5 (lossy schema) | confidence miscomputed silently |
| F7 | llm-synthesis vs ui | `Verdict` field shape over time | AD-7 (no version mechanism) | silent template mis-render |
| F8 | confidence-score vs evidence-trail | "why uncertain" narrative | AD-6, AD-7 (no sole owner of text) | duplicate/contradictory UI copy |

## Recommendation

Close F1–F4 first — they are the ones where an AD's `Binds` list or a missing-owner gap, not just an underspecified `Rule`, is the root cause, and they produce the worst failure modes (silent fabrication, silent crash, silent model clash, uncoordinated shared-file edits). F5–F8 are tightenings of existing ADs' `Rule` text and can be done as focused amendments without restructuring the spine.
