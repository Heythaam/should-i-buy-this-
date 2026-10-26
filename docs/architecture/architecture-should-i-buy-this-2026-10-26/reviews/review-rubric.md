---
name: 'Rubric Walker Review — ARCHITECTURE-SPINE.md'
type: review
reviewer: rubric-walker
target: docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md
cross-referenced: docs/prds/prd-should-i-buy-this-2026-10-26/prd.md, addendum.md, brainstorm-intent.md
created: '2026-10-26'
---

# Rubric Walker Review — "Should I Buy This?" Architecture Spine

## Overall Verdict

**Conditional pass.** This is a well-constructed spine for the stated altitude: all 16 FRs are mapped, the AD rules are mostly concrete and mechanically enforceable, the Deferred section correctly reasons about why each deferral is cross-branch-safe, and AD-10 in particular shows genuine design work (reconsidered from an earlier draft, with its trade-off written down). It should not ship to the 8 branch-builders as-is, though: there is one structural gap that directly violates the spine's own premise ("a single orchestrator module sequences them" / "each branch owns one or more filters and nothing else") because three pipeline modules are never assigned to an owning branch, one named branch (`evidence-trail`) has no actual Rule telling it what to build, and the external-dependency resilience rule (AD-9) silently excludes the LLM call despite it being on the same C4 diagram as Reddit and the scraper. These are fixable without re-architecting — they're gaps in explicitness, not in the overall shape — but they are exactly the "real divergence points for the 8 branches" the rubric asks this review to catch.

## Finding Counts

- Critical: 1
- High: 3
- Medium: 2
- Low: 2

Total: 8

---

## Critical

### C1 — Three pipeline modules have no owning branch

Every module in the Structural Seed except three is explicitly pinned to one of the 8 feature branches via an AD's `Binds` field: `canonicalize.py` and `sources/` → scraper (AD-2, AD-3); `reddit.py` → reddit (AD-2, AD-9); `alternatives.py` → alternatives (AD-2); `synthesis.py` → llm-synthesis (AD-5, AD-6); `confidence.py` → confidence-score (AD-6); `cache/store.py` → caching (AD-8); `web/` + routes → ui (AD-7, AD-10).

Three modules get no such assignment anywhere in the document:

- **`pipeline/orchestrator.py`** — AD-1 says "a single orchestrator module sequences them" and AD-8 says "the orchestrator checks cache → acquires lock → runs pipeline" — central integration logic — but no AD's `Binds` list names a branch as its owner. The Capability → Architecture Map lists it under "FR-13, FR-14 ... Lives in: `cache/store.py`, `pipeline/orchestrator.py`" which only weakly implies the `caching` branch by proximity, but AD-10 separately binds **"ui, orchestrator"** as if `orchestrator` were itself an independent actor outside the 8 branches, which contradicts that implication.
- **`pipeline/reviews.py`** (FR-4, FR-5 — review sampling, one of the PRD's 7 feature areas) — never named in any AD's `Binds` list under any branch. It is plausible the `scraper` branch is meant to own it (the Mermaid pipeline diagram shows `S[Scraper stage] --> R[Review sampling]`), but this is never stated, unlike every other module.
- **`pipeline/evidence.py`** (Evidence Bundle assembly) — not mentioned in the Capability → Architecture Map at all, and not bound by any AD to a branch. Its natural-sounding owner, by name, would be `evidence-trail`, but the map instead routes evidence-trail's one FR (FR-12) to `synthesis.py`, leaving `evidence.py` an orphan.

**Why this matters at this altitude:** the 8 branches are built independently and squash-merged; "which branch's PR adds this file" is precisely the kind of question an architecture spine exists to answer so two builders don't both skip it (or both write it with incompatible assumptions, e.g. two different orchestrator-cache-locking strategies landing in sequential PRs). Right now a builder reading only this spine cannot determine who writes `orchestrator.py`, `reviews.py`, or `evidence.py`.

**Fix:** add explicit ownership — e.g. state in prose or in a `Binds` field that `caching` owns `orchestrator.py` (consistent with the Capability Map's row), `scraper` owns `reviews.py`, and either fold `evidence.py` explicitly into `evidence-trail`'s remit or state which branch owns it.

---

## High

### H1 — The `evidence-trail` branch has no Rule, only a mention

Of the 8 named branches, `evidence-trail` is the only one that never appears as the primary binder of any AD — it's listed only as a secondary bind on AD-7 ("Verdict schema is the single frontend contract"), which is about field-naming consistency, not about what evidence-trail must actually build or enforce. FR-12's testable requirements are specific and non-trivial: "a claim with no supporting citation is not included in the Verdict," and citations must be literal, inspectable review/Reddit quotes (not LLM-paraphrased approximations). AD-5 restricts llm-synthesis's *input* to the EvidenceBundle, but nothing in the spine requires that citations in the *output* Verdict be validated against — i.e., actually resolve to — real items in that bundle. Two independently-built branches (`evidence-trail` and `llm-synthesis`) could each assume the other is responsible for this grounding check, and it could silently fall through the cracks (the LLM emits a citation-shaped string that isn't actually traceable to a bundle item, and nothing catches it).

**Fix:** add an AD (or extend AD-5/AD-7) requiring e.g. that the EvidenceBundle assigns stable IDs to every review/Reddit excerpt, that the Verdict's evidence_trail entries reference those IDs (not free text), and that synthesis validates every citation ID resolves before returning — with the id-assignment + validation step explicitly owned by `evidence-trail`.

### H2 — AD-9's external-dependency resilience rule excludes the LLM call

AD-9 ("Graceful degradation on external dependency failure") binds only `reddit, scraper`. The C4 diagram, however, shows three external dependencies: Amazon (scraper), Reddit (PRAW), and OpenAI. The OpenAI call is arguably the *most* failure-prone step in practice (rate limits, transient 5xxs, occasional hangs) and is on the critical path for every request (no synthesis → no Verdict at all, not even a degraded one). Yet no AD gives it a timeout, a retry count, or a defined degrade/fail behavior the way Reddit and the scraper get. AD-4 ("honest failure") only guarantees that *if* llm-synthesis fails it returns a typed failure rather than crashing — it says nothing about *when* to give up on a hanging or rate-limited call, which is the actual content of AD-9's rule for the other two dependencies. Without this, `llm-synthesis` could be built by its branch to retry indefinitely or not at all, and nothing here would catch the mismatch.

**Fix:** either add `llm-synthesis` to AD-9's `Binds` and rule text, or add a sibling AD with the same timeout+retry+degrade shape for the OpenAI call specifically.

### H3 — No secrets-management rule for a public repo that requires API credentials

The project requires an OpenAI API key and Reddit/PRAW credentials (client id/secret) to run at all, and the repo is explicitly public with an MIT license. The "State & cross-cutting" convention row covers config loading (one `pydantic-settings` `Settings` object, no scattered `os.getenv`) and logging (structured JSON per stage) but never states how secrets are kept out of the public repo — no mention of `.env`/`.gitignore`, no mention of keeping credentials out of the structured JSON logs (which log per-stage activity and could easily end up logging a request object containing a key if a builder isn't careful). This is exactly the kind of whole-dimension silence the rubric flags: for a public repo with required third-party credentials, "how secrets are handled" is part of the operational envelope this altitude owns, and it's the one with a real, concrete downside (a leaked OpenAI key on a public GitHub repo is a billing/abuse incident, not a hypothetical).

**Fix:** one line in the Consistency Conventions or Deployment & environments section: secrets load via `Settings` from a non-committed `.env` (with `.env.example` committed instead), and are never written to logs.

---

## Medium

### M1 — Inconsistent hedging on version claims

The rubric asks that version claims be "honest about confidence, not asserted from stale training data." The Stack table does this well for three entries — Python ("verify current 3.x at setup"), FastAPI ("verify exact pin on PyPI at setup — churns fast"), praw ("verify latest 7.x at setup") — but not for the rest: Pydantic `~=2.13`, Uvicorn `>=0.47`, Playwright (Python) `~=1.62`, beautifulsoup4 `>=4.12`, aiosqlite `~=0.22`, pytest `>=8.0`, ruff `~=0.15`, and GitHub Actions `actions/checkout`/`actions/setup-python` pinned to `v7` are all stated as if settled. The document itself is dated 2026-10-26, past the point where any of these specific minor/patch numbers can be verified from training data with real confidence — the hedge should be applied uniformly (or removed uniformly with an explicit "verify all pins at setup" blanket note) rather than applied to three entries and silently omitted from the other eight, which reads as uneven confidence rather than a reasoned distinction.

**Fix:** either hedge all version pins the same way, or add one blanket sentence ("all exact versions above are starting points; pin real current versions at `pip install` time") instead of selectively hedging three of eleven.

### M2 — Low-confidence display threshold is implicitly duplicated between `confidence-score` and `ui`

The Deferred section says the Confidence Score formula weights and low-confidence threshold are "owned entirely by the `confidence-score` branch behind AD-6's interface ... no cross-branch risk." But FR-15 requires the UI to visually distinguish a low-confidence Verdict from a normal confident one — which means `ui` needs *some* rule for when to apply that treatment. Since `Verdict.confidence` is just a float in `[0.0, 1.0]` (per the Consistency Conventions) with no accompanying boolean/flag, `ui` is left to either (a) invent its own magic-number threshold independently of whatever `confidence-score` uses internally to "cap" scores (per FR-5), risking two different numbers meaning "low confidence" in two branches, or (b) the spine is silently assuming the UI never needs a threshold at all, which contradicts FR-15's explicit testable requirement. This isn't a contradiction that breaks things outright (the number itself is still a consistent single source of truth), but it is a real, unaddressed small divergence risk the "no cross-branch risk" claim glosses over.

**Fix:** either add a `low_confidence: bool` (or similar) field to the `Verdict` model under AD-7 so `ui` never needs its own threshold, or explicitly state in the Deferred entry that `ui` is expected to pick its own independent display threshold and that this is acceptable.

---

## Low

### L1 — AD-8's coalescing guarantee is implicitly single-process

AD-8's `asyncio.Lock` registry only coalesces concurrent requests within one Python process. FR-14 ("N simultaneous requests ... result in exactly one ... pass, not N") would silently break under `uvicorn --workers N>1` or any multi-process deployment, since each worker gets its own lock registry. Given the stated local-single-user scope this is a reasonable assumption, but the spine never states "single process" as a deployment constraint anywhere (the Deployment & environments paragraph describes local-only but not single-vs-multi-worker), so the FR-14 guarantee rests on an unwritten assumption.

**Fix:** one clause in Deployment & environments: "runs as a single process (no multi-worker Uvicorn) — required for AD-8's lock registry to coalesce correctly."

### L2 — AD-7's "versioned" claim for the Verdict model isn't backed by a mechanism

AD-7 says the Verdict model is "Defined once, versioned, imported by both sides." No convention anywhere (Consistency Conventions, Stack, or Structural Seed) says *how* it's versioned — a `schema_version` field, a module path with a version suffix, or just "don't break the shape without bumping something." For a solo hobby project this is a minor miss, not a cross-branch risk by itself (nothing currently depends on reading the version), but the word "versioned" is asserted without any rule making it true, which is worth tightening given everything else in the AD is this specific.

---

## What the spine does well (for context, not a finding)

- Full FR-1…FR-16 coverage in the Capability → Architecture Map, with no PRD feature area silently dropped.
- AD-10 (SSE) shows real design work: it records that it reconsidered an earlier polling-only draft, states the trade-off it accepted (orchestrator must explicitly publish, straight-line async doesn't emit events on its own), and ties the decision to a specific PRD Open Question (2) and FR (16).
- The Deferred section mostly reasons correctly about why each deferral doesn't create cross-branch incompatibility (the Tier-1 API deferral explicitly leans on AD-3's port so a future adapter doesn't require touching the rest of the pipeline; the persona-disagreement visual deferral correctly keeps the *data contract* fixed in AD-7 while leaving only the *rendering* open).
- Honest about the brainstorm's wrong assumption (Rainforest/Keepa "free tier" claim) rather than quietly dropping it.
- `[ASSUMPTION]` tags are used appropriately and the assumptions themselves (e.g. v1 ships Tier 2/3 only, no job queue) are reasonable for a solo/hobby scope — consistent with the stated Fast-path context.
