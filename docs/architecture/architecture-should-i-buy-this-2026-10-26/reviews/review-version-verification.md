---
name: 'Version Verification Review — Should I Buy This? Architecture Spine'
type: review
target: docs/architecture/architecture-should-i-buy-this-2026-10-26/ARCHITECTURE-SPINE.md
reviewed: '2026-10-26'
---

# Version Verification Review

**Mandate:** Verify every committed decision in the spine's Stack table (and any bare technology assertion elsewhere) was web-researched or reality-checked rather than asserted from training data. Spot-check specific version claims via web search; flag anything stale or unverified, including facts stated *without* a caveat that should have had one.

**Method:** Live web search (2026-10-26) against PyPI release trackers, GitHub release/changelog mirrors, and vendor blogs for each named technology. Results below are cross-checked across multiple sources where the first source was ambiguous or stale.

## Overall Verdict

**Mostly solid, with one stale pin and two under-caveated risks.** The prior research pass's caveats ("verify at setup") were correctly placed on the genuinely volatile items (FastAPI, praw, OpenAI SDK version, Python patch) and those items hold up. However: the **ruff pin (`~=0.15`) is now stale** — a full minor line behind, with a real default-behavior change in the line it excludes — and carries no caveat at all. The **pytest pin (`>=8.0`) is unbounded across an already-shipped major version** (9.0, with documented breaking changes) and also carries no caveat. The **OpenAI Structured Outputs call shape is stated as a settled implementation fact** (not just "verify SDK version") without any caveat, despite being one of the fastest-moving surfaces of the OpenAI API. None of this blocks starting work — all are "verify/adjust at setup" fixes, not architectural rework — but the Stack table should be corrected before it's treated as ground truth by the 8 feature branches.

## Findings

### High

**1. `ruff ~=0.15` is stale and uncaveated — current line (0.16.x) changed default lint behavior.**
- Spine states: `ruff | ~=0.15` (compatible-release pin, i.e. `>=0.15,<0.16`), no caveat.
- Verified: Ruff 0.16.0 shipped 2026-07-23 (confirmed via Astral's own blog post and PyPI release trackers), with patch releases through at least 0.16.6 (September 2026) — i.e., three months old relative to this spine's 2026-10-26 date, not a same-week release that could excuse missing it.
- Why it matters: 0.16.0 is not a routine bump — it changed what `ruff check` enforces by default (the default rule set grew from 59 to 413 rules; 18 previously-default pycodestyle/pyflakes rules such as E401, E402, E701, F403 were *removed* from the default set). The spine's `~=0.15` pin locks the `lint` CI job (AD, CI/CD section) to the old default set and silently excludes this change rather than deliberately choosing it.
- Contrast: Python, FastAPI, and praw all got "verify at setup" caveats precisely because they churn; ruff — which churns at least as fast and just had a behavior-affecting release — got none.
- Suggested fix: change to `ruff | >=0.15 (verify current minor at setup — 0.16.x changed the default rule set; confirm before adopting)`.

### Medium

**2. `pytest >=8.0` has no upper bound and no caveat, but pytest has already shipped a major version with documented breaking changes.**
- Spine states: `pytest | >=8.0`, no caveat.
- Verified: pytest 9.0.0 released 2025-11-05 (per the official pytest release-announcement page), whose own release notes state it "contains new features, improvements, bug fixes, **and breaking changes**." Current latest at review time is in the 9.1.x line.
- Why it matters: an unbounded `>=8.0` resolves to 9.x today, not the 8.x line the spine's author was presumably reasoning about. This is exactly the "churns fast, needs a floor-and-verify note" pattern the spine applied to FastAPI (`>=0.115 (verify exact pin ... churns fast)`) — pytest should have gotten the same treatment and didn't.
- Suggested fix: add `(verify current major at setup — 9.x has shipped with breaking changes vs. 8.x)`.

**3. OpenAI Structured Outputs call shape is asserted as settled fact, not just "verify SDK version."**
- Spine states: `openai (Python SDK) | latest at setup — must support Structured Outputs (response_format={"type":"json_schema",...})`.
- The *version* half of this is correctly deferred ("latest at setup" — a good pattern, not flagged). The *shape* half is not deferred: `response_format={"type":"json_schema",...}` is stated as the mechanism, full stop.
- Verified: that shape is the Chat Completions endpoint's structured-output mechanism. OpenAI has been steering new feature development toward the newer Responses API, which expresses the equivalent constraint differently (a `text.format` block with `type:"json_schema"`, rather than `response_format`), and the Python SDK also offers higher-level `.parse()` helpers that take a Pydantic model directly. OpenAI's own prior public guidance says Chat Completions will continue to be supported "indefinitely," so this isn't a broken claim today — but it is a specific, named API parameter shape, in the single fastest-moving corner of the stack (LLM provider SDKs), stated with the same confidence as `praw >=7.7` got a caveat for being merely a minor-version question.
- Suggested fix: add a caveat such as `(confirm response_format vs. Responses API text.format shape against current OpenAI docs at setup — this SDK surface changes often)`, and note in AD-7 or AD-5 that the exact call shape is an implementation detail of `synthesis.py`, not a locked architectural contract.

### Low

**4. Inconsistent caveat coverage between Uvicorn and FastAPI despite comparable churn risk.**
- FastAPI got: `>=0.115 (verify exact pin on PyPI at setup — churns fast)`.
- Uvicorn got: `>=0.47`, no caveat, despite shipping on a comparable cadence (current latest found: ~0.51.x).
- The floor (`>=0.47`) still holds true today, so this isn't a correctness error — but it's the same risk profile as FastAPI without the same caveat, which is the kind of gap the review mandate asks to surface. Recommend adding the same "verify at setup" phrasing for consistency, since both are maintained by the same close-knit ecosystem and tend to release in step.

**5. GitHub Actions major versions (`actions/checkout v7`, `actions/setup-python v7`) are correct but stated as bare fact with no caveat.**
- Verified both: `actions/checkout` v7.0.0/v7.0.1 is current (headline change: blocks fork-PR checkout for `pull_request_target`/`workflow_run` triggers, runs on Node 24). `actions/setup-python` v7.0.0 is also current (ESM migration, removed the `pip-install` input, confirmed via multiple independent dependency-bump PRs referencing the v6→v7 changelog).
- Both pins are accurate as of 2026-10-26 — no correction needed. Flagging only because, like FastAPI/Uvicorn, these are versions that move (checkout went v6→v7, setup-python went v6→v7) and the table gives no indication either was actually checked vs. assumed. Since they happen to be right, this is informational, not a defect — but worth a one-line "confirmed current" note so a future reader doesn't have to re-derive that these were actually checked rather than guessed.

## Claims That Held Up (no correction needed)

For completeness, since the mandate also calls for reporting what's confirmed, not just what's wrong:

| Claim | Spot-check result |
| --- | --- |
| Python `3.12+` floor | Still valid: Python 3.12 (Oct 2023) remains in security-support status through roughly 2028 under CPython's 5-year lifecycle; current latest lines are 3.13/3.14/3.15. Floor-plus-caveat framing is appropriate as-is. |
| FastAPI `>=0.115` | Floor holds; current latest found ~0.130–0.131. "Churns fast" caveat is well warranted and correctly applied. |
| Pydantic `~=2.13` | Current latest minor confirmed as 2.13.x (latest patch ~2.13.1) — pin matches reality despite no caveat being present. |
| Playwright (Python) `~=1.62` | Matches almost exactly: 1.62.0 confirmed released 2026-07-31, i.e., this appears to have been genuinely checked near time of writing, not guessed. |
| beautifulsoup4 `>=4.12` | Floor holds; current latest ~4.15.0. |
| praw `>=7.7 (verify latest 7.x at setup)` | Caveat is appropriate; most recent widely-indexed stable release found was 7.8.1. Given PRAW's slower release cadence, this is plausible and the existing caveat correctly anticipates the need to double check at setup rather than asserting a specific patch. |
| aiosqlite `~=0.22` | Matches current latest (0.22.1). |
| GitHub Actions `actions/checkout v7`, `actions/setup-python v7` | Both confirmed current (see Finding 5 — correct, just uncaveated). |
| `openai (Python SDK) | latest at setup` (version half only) | Good pattern — correctly defers to setup-time check rather than asserting a specific SDK version from training data. |

## Summary

| Severity | Count |
| --- | --- |
| High | 1 |
| Medium | 2 |
| Low | 2 |

Top issues, in order of what to fix first:
1. `ruff ~=0.15` — stale pin, excludes a default-behavior change already three months old; add a verify caveat (or re-pin to `~=0.16`).
2. `pytest >=8.0` — unbounded floor silently spans a major version with breaking changes; add a verify caveat.
3. OpenAI Structured Outputs call shape (`response_format={"type":"json_schema",...}`) — stated as settled implementation fact in the fastest-moving part of the stack; add a caveat distinguishing it from the newer Responses API shape.
4. Uvicorn and the GitHub Actions pins are accurate today but inconsistently caveated relative to sibling entries that got the "verify at setup" treatment — low risk, but worth aligning for consistency.
