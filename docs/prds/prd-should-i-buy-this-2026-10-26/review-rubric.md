# PRD Quality Review — Should I Buy This?

## Overall verdict

This is a well-built hobby-tier PRD: it has a real thesis ("evidence and confidence are the product, not the verdict label alone"), FRs that almost all carry testable consequences, honest de-scoping, and a glossary that stays consistent across every FR. It is correctly shaped for a single-operator tool — one UJ, operational success metrics, no compliance/NFR boilerplate — and the addendum.md handoff to architecture is clean and well-traced. The main soft spots are a success metric (SM-2) left fully unbound where a number was available, and a couple of deferred thresholds (FR-5, FR-8) that didn't make it into the Open Questions list the way comparable deferrals did. Nothing here is a structural break; the gaps are refinement, not rework.

## Decision-readiness — adequate

Open Questions (§8) are genuinely open — e.g. "Which specific Tier-1 data source(s)... and whether their free tiers are sufficient" (Q1) has no answer buried in the next sentence. The `[NOTE FOR PM]` at §6.2 lands on a real tension (the original brief wanted "ideally any e-commerce site"; v1 narrows to Amazon only) rather than a safe checkpoint — this is the PRD's best decision-readiness moment. The v1/v2 split on "Wait" (§4.5 FR-9: evidence-ambiguity only in v1, price-history-backed Wait deferred to v2) also names what's given up, not just what's kept.

Where it's thinner: FR-10's multi-persona reasoning (2-3 independent LLM passes per request) is presented purely as a benefit ("disagreement is itself a signal") with no acknowledgment of the cost/latency this adds — every Verdict now costs multiple LLM calls instead of one, and SM-2's time-to-result target has to absorb that. The addendum's cost-control note (cheap model for extraction, strong model for synthesis) is a technical mitigation, not a PRD-level trade-off statement, so a reader of the PRD alone wouldn't see the cost named as a cost.

### Findings
- **medium** Multi-persona reasoning cost/latency trade-off unstated (§4.5 FR-10) — Running 2-3 Reasoning Personas per request is framed only as a quality win; the PRD never states that this multiplies LLM calls and therefore cost and wait time, which directly bears on SM-2. *Fix:* Add a line acknowledging the cost/latency cost of multi-persona synthesis, even briefly, so the trade-off is visible rather than implicit in the addendum.

## Substance over theater — strong

No padding found. There is exactly one real persona (the builder, §2.1), framed through Functional/Emotional/Contextual JTBD rather than a demographic sketch, and it drives real decisions (e.g. "used in the moment of deciding" shapes FR-16's progress-indicator requirement). The Vision statement (§1) is specific to this product's mechanics ("gathers evidence... never invent it... visible trail back to the sources") rather than swappable boilerplate. There is no separate NFR section padded with "must be scalable/secure/reliable" — the PRD correctly omits one rather than filling it with adjectives. Glossary terms (Canonical Product, Evidence Bundle, Source Tier, Reasoning Persona) are used because they're load-bearing in FRs, not decorative.

## Strategic coherence — strong

The thesis is explicit and the feature set follows it: extraction → review sampling → Reddit cross-check → alternatives → synthesis → confidence → caching → UI, each section earning its place by feeding the Evidence Bundle or the Verdict. SM-C1 ("do not optimize for the Verdict always being confident") is a real counter-metric that protects the thesis against the obvious failure mode (inflating confidence to look more useful) rather than a token checkbox. SM-1 (continued personal use past the first month) is an honest metric for a one-user tool rather than a vanity activity metric.

### Findings
- **low** Success metrics don't individually trace to most FRs (§7) — SM-1 and SM-2 are the only metrics, and neither directly validates FR-1–FR-14 (extraction accuracy, Reddit relevance, alternatives quality, caching correctness); SM-1 is a holistic "do I keep using it" catch-all. For a solo tool this is a reasonable and honest choice, not a defect, but worth naming as a deliberate scope decision rather than leaving it implicit.

## Done-ness clarity — adequate

This is the PRD's strongest mechanical habit: nearly every FR (FR-1 through FR-16) carries a "Consequences (testable)" block with a concrete, checkable condition — e.g. FR-1's "the same product reached via two different URLs... resolves to the same Canonical Product," or FR-11's "two requests with identical Evidence Bundle inputs produce the same Confidence Score." Vague-adjective language ("handles gracefully," "user-friendly") is essentially absent from the FRs themselves.

It slips at the Success Metrics layer. SM-2 (§7) reads: "completes in a time the user is willing to wait for before checking out, without feeling broken or stalled" — this is the exact "reasonable performance" pattern the rubric calls out, and unlike FR-16 (which at least commits to "within a few seconds" for the progress indicator), SM-2 gives no number anywhere in the PRD. The addendum's pipeline note mentions "~20-30s wait" but that's framed as an implementation estimate, not a PRD-level commitment, and SM-2 isn't listed in §8 Open Questions as an unresolved threshold the way the Confidence Score formula (Q4) is.

Separately, two FR consequences defer a numeric bound without a matching Open Question entry: FR-5's "defined review-count threshold" and FR-8's "bounded price difference" are both left unspecified in the PRD (the addendum has FR-5's number — fewer than 10 reviews — but not FR-8's), yet neither appears in §8 or §9 the way the cache TTL and Confidence Score formula do.

### Findings
- **medium** SM-2 has no stated bound (§7) — "a time the user is willing to wait for... without feeling broken or stalled" is unmeasurable as written; nothing in the PRD itself commits to a number, even though the addendum has one (~20-30s) that never made it back into the PRD or into §8 Open Questions. *Fix:* Either state a target range in SM-2 directly, or add it to §8 as an explicitly open threshold.
- **low** FR-5 and FR-8 numeric bounds undetermined and untracked (§4.2 FR-5, §4.4 FR-8) — "a defined review-count threshold" and "a bounded price difference" are left unspecified in the PRD, and unlike the Confidence Score formula (§8 Q4) or cache window, neither is listed as an Open Question. *Fix:* Add both to §8, or pull FR-5's addendum value (10 reviews) into the PRD now that it exists.

## Scope honesty — strong

§5 Non-Goals is substantive and specific (no accounts, no browser extension, no price alerts, no community voting, no mobile app) rather than generic. §6.2 Out of Scope goes further and is honest about what was walked back: the `[NOTE FOR PM]` explicitly flags that "any e-commerce site" was the original ambition and Amazon-only is a deliberate narrowing, not a silent one. Two inline `[ASSUMPTION]` tags (§4.1, §4.7 FR-16) are both indexed in §9. Open-items density (5 Open Questions, 2 inline assumptions, 1 NOTE FOR PM) is proportionate for a single-user hobby tool — neither empty nor inflated.

## Downstream usability — strong

The PRD explicitly declares its downstream consumer (§0: "preserved in addendum.md for bmad-architecture to consume directly") and the addendum reciprocates well — every technical section is tagged "(informs FR-X, FR-Y...)" back to specific FR IDs, making the handoff traceable in both directions. Glossary terms (Canonical Product, Evidence Bundle, Verdict, Confidence Score, Evidence Trail, Source Tier, Reasoning Persona) are used identically everywhere they appear — spot-checked across FR-1, FR-9, FR-10, FR-11, FR-13 with no drift found. FR IDs are contiguous (FR-1–FR-16, no gaps or duplicates); the one UJ and three SMs are likewise clean.

## Shape fit — strong

Correctly built as a capability spec for a single-operator tool rather than forced into a consumer-product shape: exactly one UJ (appropriate — there's one real user and one real workflow), SM-1 is explicitly personal/operational ("the builder actually uses it... past the first month") rather than a manufactured user-facing metric, and there is no compliance, SLA, or multi-stakeholder scaffolding anywhere. This matches the stated hobby/solo scope cleanly and doesn't over- or under-formalize.

## Mechanical notes

- **Assumptions Index roundtrip gap (§9):** the third entry ("Throughout — single local user, no authentication...") has no corresponding inline `[ASSUMPTION]` tag anywhere in the body; the entry itself self-discloses this ("confirmed intent, not inferred, but recorded here"). Low risk since it's self-flagged, but technically breaks strict roundtrip.
- **Unresolved placeholder:** the document header still reads "*Working title — confirm.*" (line 9) — a loose end that should be closed before this PRD is treated as final.
- **UJ-1 protagonist is generic** ("the user," §2.2) rather than a named individual. Given the product has exactly one real-world user (the builder), this is defensible, but it's worth noting it departs from the "named protagonist" convention other PRDs in this rubric are checked against.
- No glossary drift found; no ID gaps or duplicates; cross-references (§6.2 ↔ FR-9, §8 Q1 ↔ addendum) all resolve correctly.
