"""The FastAPI app -- the first entry point into the v1 pipeline (`ui`
branch, AD-7, AD-10's "not yet" note for this story).

`GET /` accepts an optional `url` query param, runs the complete
`produce_verdict()` pipeline (Story 1.7) when one is present, and renders
everything -- form plus result, when there is one -- through the single
`templates/index.html` template (this story's "one screen" requirement).
No SSE/progress streaming yet (Story 1.9's job): the request simply blocks
until `produce_verdict()` resolves.

`get_product_source()`/`get_llm_client()` are FastAPI dependency providers
returning module-level singletons built once from a single `Settings()`
(NFR-1) at import time -- not reconstructed per-request, so a malformed env
var fails fast at startup rather than crashing every request. They exist
specifically so tests can override them via `app.dependency_overrides` with
stub `ProductSource`/`LLMClient` implementations (this project's established
port-based testing convention), rather than monkeypatching module-level
globals.
"""

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models.product import InsufficientDataResult
from app.models.verdict import Verdict
from app.pipeline.llm_client import LLMClient, OpenAIClient
from app.pipeline.orchestrator import produce_verdict
from app.pipeline.sources.base import ProductSource
from app.pipeline.sources.scraper_tier2 import ScraperTier2Source
from app.settings import Settings

logger = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent

# Built once at import time (NFR-1) -- never per-request. A per-request
# `Settings()` in a `Depends` provider would re-run its validators (e.g.
# `_validate_scraper_proxy_url`) on every request, so a single malformed env
# var would crash every request, including a plain form-only `GET /`.
_settings = Settings()
_product_source = ScraperTier2Source(_settings)
_llm_client = OpenAIClient(_settings)

# This story's own UI-layer calibration (see the spec's Design Notes) --
# separate from `compute_confidence()`'s internal weights (Story 1.7).
# Neither the PRD nor the architecture names an exact cutoff for "visually
# distinguish a low-confidence result," only that one must exist
# (FR-13/NFR-8); a future story can retune this without touching
# `compute_confidence()`.
_LOW_CONFIDENCE_THRESHOLD = 0.5

app = FastAPI(title="Should I Buy This?")
app.mount("/static", StaticFiles(directory=_APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=_APP_DIR / "templates")


def get_product_source() -> ProductSource:
    """The real `ProductSource` the app uses outside of tests.

    Returns the module-level instance built from `Settings()` (NFR-1) --
    never hardcoded config, and never reconstructed per-request. Tests
    override this via `app.dependency_overrides` with a stub, so no live
    network call ever happens in a test run.
    """
    return _product_source


def get_llm_client() -> LLMClient:
    """The real `LLMClient` the app uses outside of tests.

    Returns the module-level instance built from `Settings()` (NFR-1) --
    never hardcoded config, and never reconstructed per-request. Tests
    override this via `app.dependency_overrides` with a stub, so no live
    OpenAI call ever happens in a test run.
    """
    return _llm_client


def _result_kind(result: Verdict | InsufficientDataResult) -> str:
    """Classify `result` into the one of three styling buckets this story's
    I/O & Edge-Case Matrix requires: `"confident"`, `"low_confidence"`, or
    `"insufficient_data"`. Drives `class="result result--{{ result_kind }}"`
    in the template -- never the same class for two different kinds.
    """
    if isinstance(result, InsufficientDataResult):
        return "insufficient_data"
    # `<` vs `<=` at the exact threshold is moot in practice: an exact tie
    # is mathematically unreachable given `compute_confidence()`'s discrete
    # 0.015-increment components; `<` is used for the unambiguous case
    # (values strictly above the threshold) where the choice does matter.
    if result.confidence < _LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "confident"


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    url: str | None = None,
    source: ProductSource = Depends(get_product_source),
    llm: LLMClient = Depends(get_llm_client),
) -> HTMLResponse:
    """Render the URL-paste form, plus a result section when `url` is given.

    `url` is optional: with no `url` param (or a blank one), only the form
    renders -- no result section at all, matching this story's I/O Matrix.
    When present, the full `produce_verdict()` pipeline runs and the single
    template renders whichever result kind it returned, styled distinctly.
    """
    result: Verdict | InsufficientDataResult | None = None
    result_kind: str | None = None

    if url:
        try:
            result = await produce_verdict(url, source, llm)
        except Exception as exc:
            logger.exception("index: unexpected error while producing verdict for %s", url)
            result = InsufficientDataResult(reason="unexpected_error", detail=str(exc))
        result_kind = _result_kind(result)

    return templates.TemplateResponse(
        request,
        "index.html",
        {"url": url, "result": result, "result_kind": result_kind},
    )
