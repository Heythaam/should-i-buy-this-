"""Two-call LLM verdict synthesis (llm-synthesis branch, AD-5, AD-7, AD-9).

`synthesize_verdict()` is the only place a `Verdict` is constructed. It:

1. Calls the cheap model (`Settings.llm_cheap_model`) to cluster the bundle's
   sampled review text into pros/cons themes (`ThemeClusters`).
2. Calls the strong model (`Settings.llm_strong_model`) to synthesize a
   `DraftVerdict` from those themes plus product facts and alternatives.
3. Resolves every pro/con's citation against the real `EvidenceBundle`
   (`_resolve_citation`); anything that doesn't resolve is dropped rather
   than shown (AD-4) -- never fabricated.
4. If zero pros AND zero cons remain after dropping, retries step 2 once
   with the validation error appended to the prompt.
5. If the retry also leaves nothing resolvable, or any LLM call fails
   outright, returns `InsufficientDataResult` -- never a hand-patched
   `Verdict`.
6. On success, overwrites `confidence` with `compute_confidence(bundle)`'s
   output (AD-6) and assembles `evidence_basis`/`alternatives` directly from
   the bundle (AD-5, AD-7) -- never from the LLM.

Note on the strong-model prompt: the architecture's Stack section frames the
cheap/strong split as "the strong model synthesizes from themes plus product
facts and alternatives -- never from raw review text directly" as a
cost-control detail. That holds for *primary signal* here (themes drive the
pros/cons content), but AD-7's citation-resolution requirement means the
strong model still needs an indexed view of the actual reviews/alternatives
to produce a citation that can resolve at all -- so the synthesis prompt
below includes the bundle's already-bounded, already-sampled review/
alternatives lists (never the raw, un-sampled page) alongside the themes,
trading a small amount of the cost-control framing for citations that are
checkable rather than guaranteed-unresolvable.
"""

import logging

from app.models.evidence import EvidenceBundle
from app.models.llm import DraftVerdict, LLMCallFailure, ThemeClusters
from app.models.product import InsufficientDataResult
from app.models.verdict import Citation, EvidenceBasis, ProConItem, Verdict
from app.pipeline.confidence import compute_confidence
from app.pipeline.llm_client import LLMClient
from app.pipeline.progress import NullProgressPublisher, ProgressPublisher
from app.settings import Settings

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

# Minimum citation quote length before attempting a containment match: short
# or generic quotes (e.g. "good") would spuriously match almost any
# review/fact text, so anything shorter than this is rejected outright. Kept
# short enough that a real single-word spec value (e.g. "Charcoal") still
# resolves -- this guards against generic short quotes, not short facts.
_MIN_QUOTE_LENGTH = 8

_THEME_SYSTEM_PROMPT = """You cluster raw product review text into short, \
recurring pros/cons themes for a downstream synthesis step.

Rules:
- Base every theme only on content actually present in the reviews you were \
given -- never invent a theme unsupported by the review text.
- Never mention or infer anything about price history or price trends -- no \
price-history data exists in this system.
- Keep each theme to a short phrase, not a full sentence."""

_SYNTHESIS_SYSTEM_PROMPT = """You are the final synthesis step of a product-\
verdict pipeline. Produce a BUY, SKIP, or WAIT verdict as structured output \
matching the provided schema.

Rules:
- Every pro and con must carry a citation grounded in evidence actually \
provided to you: either a specific review index with a verbatim excerpt \
from that review's text, a specific alternative index with its title, or a \
verbatim quote from the product's own facts (its title, price, or a spec \
value).
- Never invent a citation, index, or quote that is not literally present in \
the evidence you were given -- an uncited or fabricated claim is worse than \
no claim.
- Never reason about price history or price trends, and never cite one -- \
no price-history data exists in this system. A WAIT verdict reflects \
inconclusive evidence only, never a price prediction.
- Your own confidence value is advisory only: it will be discarded and \
replaced by a deterministic calculation. Still provide your best estimate."""

_VALIDATION_ERROR_MESSAGE = (
    "Validation failed: zero resolvable pros/cons remained after citation "
    "resolution. Every pro/con's citation must resolve to an item actually "
    "present in the evidence above -- a review index within range whose "
    "quote is drawn verbatim from that review's text, an alternative index "
    "within range, or a quote drawn verbatim from the product's own facts. "
    "Produce a new draft where every citation satisfies this."
)


def _resolve_citation(citation: Citation, bundle: EvidenceBundle) -> str | None:
    """Resolve `citation` against the real `bundle`.

    Returns the resolved excerpt (the review body, the alternative's title,
    or the matched fact text) on success, or `None` if it doesn't resolve --
    callers drop the citation's owning pro/con rather than show it (AD-4).
    """
    quote = citation.quote.strip() if citation.quote else ""
    if len(quote) < _MIN_QUOTE_LENGTH:
        return None

    if citation.source_type == "review":
        if citation.source_index is None:
            return None
        reviews = bundle.reviews
        if not (0 <= citation.source_index < len(reviews)):
            return None
        review = reviews[citation.source_index]
        if quote.lower() not in review.body.lower():
            return None
        return review.body

    if citation.source_type == "alternative":
        if citation.source_index is None:
            return None
        alternatives = bundle.alternatives
        if not (0 <= citation.source_index < len(alternatives)):
            return None
        alternative = alternatives[citation.source_index]
        if quote.lower() not in alternative.title.lower():
            return None
        return alternative.title

    if citation.source_type == "product_fact":
        # No index: a bundle carries exactly one `ProductFacts` record to
        # point at. A price-trend claim has no field here to match against
        # (there is no price-history data in v1), so it is uncitable by
        # construction and falls through to the `None` below.
        facts = bundle.product_facts
        candidates = [facts.title]
        if facts.price is not None:
            candidates.append(str(facts.price))
        for key, value in facts.specs.items():
            candidates.append(value)
            candidates.append(f"{key}: {value}")
        lowered_quote = quote.lower()
        for candidate in candidates:
            if lowered_quote in candidate.lower():
                return candidate
        return None

    return None


def _resolve_items(items: list[ProConItem], bundle: EvidenceBundle) -> list[ProConItem]:
    """Keep only the items whose citation resolves against `bundle`."""
    return [item for item in items if _resolve_citation(item.citation, bundle) is not None]


def _format_review_line(index: int, review) -> str:
    if review.title:
        return f"[{index}] ({review.rating}/5 stars) {review.title}: {review.body}"
    return f"[{index}] ({review.rating}/5 stars) {review.body}"


def _build_theme_user_prompt(bundle: EvidenceBundle) -> str:
    lines = [f"Product: {bundle.product_facts.title}", "", "Reviews:"]
    if bundle.reviews:
        for index, review in enumerate(bundle.reviews):
            lines.append(_format_review_line(index, review))
    else:
        lines.append("(no reviews available)")
    return "\n".join(lines)


def _build_synthesis_user_prompt(bundle: EvidenceBundle, themes: ThemeClusters) -> str:
    facts = bundle.product_facts
    lines = [
        f"Product: {facts.title}",
        f"Price: {facts.price if facts.price is not None else 'unknown'}",
        "Specs:",
    ]
    if facts.specs:
        lines.extend(f"- {key}: {value}" for key, value in facts.specs.items())
    else:
        lines.append("(none available)")

    lines.append("")
    lines.append("Pros themes (from review clustering):")
    if themes.pros_themes:
        lines.extend(f"- {theme}" for theme in themes.pros_themes)
    else:
        lines.append("(none)")

    lines.append("")
    lines.append("Cons themes (from review clustering):")
    if themes.cons_themes:
        lines.extend(f"- {theme}" for theme in themes.cons_themes)
    else:
        lines.append("(none)")

    lines.append("")
    lines.append("Indexed reviews (cite by index + a verbatim excerpt when grounding a claim):")
    if bundle.reviews:
        for index, review in enumerate(bundle.reviews):
            lines.append(_format_review_line(index, review))
    else:
        lines.append("(none available)")

    lines.append("")
    lines.append("Indexed alternatives (cite by index + its title when referencing one):")
    if bundle.alternatives:
        for index, alternative in enumerate(bundle.alternatives):
            alt_price = alternative.price if alternative.price is not None else "unknown"
            lines.append(f"[{index}] {alternative.title} (price: {alt_price})")
    else:
        lines.append("(none available)")

    lines.append("")
    signal_note = "LOW" if bundle.review_signal.is_low_signal else "sufficient"
    if bundle.review_signal.reason:
        signal_note += f" -- {bundle.review_signal.reason}"
    lines.append(f"Review signal: {signal_note}")

    return "\n".join(lines)


async def synthesize_verdict(
    bundle: EvidenceBundle,
    llm: LLMClient,
    progress: ProgressPublisher | None = None,
) -> Verdict | InsufficientDataResult:
    """Synthesize a schema-validated `Verdict` from `bundle`, or fail honestly.

    Never raises (AD-4, AD-9): any `LLMCallFailure` from either call, and
    both attempts leaving zero resolvable pros/cons, both resolve to
    `InsufficientDataResult`.

    Publishes `"synthesizing_verdict"` on entry when `progress` is given
    (Story 1.9, AD-10); a complete no-op otherwise.
    """
    publisher = progress if progress is not None else NullProgressPublisher()
    await publisher.publish("synthesizing_verdict")

    settings = Settings()

    theme_result = await llm.complete(
        system_prompt=_THEME_SYSTEM_PROMPT,
        user_prompt=_build_theme_user_prompt(bundle),
        response_model=ThemeClusters,
        model=settings.llm_cheap_model,
    )
    if isinstance(theme_result, LLMCallFailure):
        logger.warning(
            "synthesize_verdict: theme-clustering call failed: %s (%s)",
            theme_result.reason,
            theme_result.detail,
        )
        return InsufficientDataResult(
            reason=theme_result.reason,
            detail=theme_result.detail,
            source_tier=bundle.product_facts.source_tier,
        )

    themes = theme_result
    synthesis_prompt = _build_synthesis_user_prompt(bundle, themes)

    draft_result = await llm.complete(
        system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=synthesis_prompt,
        response_model=DraftVerdict,
        model=settings.llm_strong_model,
    )
    if isinstance(draft_result, LLMCallFailure):
        logger.warning(
            "synthesize_verdict: synthesis call failed: %s (%s)",
            draft_result.reason,
            draft_result.detail,
        )
        return InsufficientDataResult(
            reason=draft_result.reason,
            detail=draft_result.detail,
            source_tier=bundle.product_facts.source_tier,
        )

    draft = draft_result
    resolved_pros = _resolve_items(draft.pros, bundle)
    resolved_cons = _resolve_items(draft.cons, bundle)

    if not resolved_pros and not resolved_cons:
        logger.warning(
            "synthesize_verdict: zero resolvable pros/cons on first attempt, retrying once"
        )
        retry_prompt = f"{synthesis_prompt}\n\n{_VALIDATION_ERROR_MESSAGE}"
        retry_result = await llm.complete(
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=retry_prompt,
            response_model=DraftVerdict,
            model=settings.llm_strong_model,
        )
        if isinstance(retry_result, LLMCallFailure):
            logger.warning(
                "synthesize_verdict: retry call failed: %s (%s)",
                retry_result.reason,
                retry_result.detail,
            )
            return InsufficientDataResult(
                reason=retry_result.reason,
                detail=retry_result.detail,
                source_tier=bundle.product_facts.source_tier,
            )

        draft = retry_result
        resolved_pros = _resolve_items(draft.pros, bundle)
        resolved_cons = _resolve_items(draft.cons, bundle)

        if not resolved_pros and not resolved_cons:
            logger.warning(
                "synthesize_verdict: retry also left zero resolvable pros/cons"
            )
            return InsufficientDataResult(
                reason="no_resolvable_citations",
                detail=(
                    "Both the original and retried LLM responses left zero "
                    "resolvable pros/cons after citation resolution."
                ),
                source_tier=bundle.product_facts.source_tier,
            )

    evidence_basis = EvidenceBasis(
        review_count=len(bundle.reviews),
        is_low_signal=bundle.review_signal.is_low_signal,
        alternatives_count=len(bundle.alternatives),
        source_tier=bundle.product_facts.source_tier,
    )

    return Verdict(
        schema_version=_SCHEMA_VERSION,
        label=draft.label,
        confidence=compute_confidence(bundle),
        evidence_basis=evidence_basis,
        pros=resolved_pros,
        cons=resolved_cons,
        alternatives=bundle.alternatives,
        reasoning_summary=draft.reasoning_summary,
    )
