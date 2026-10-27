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

Story 1.9 (AD-10) additionally adds `GET /jobs` and `GET /jobs/{job_id}/events`
below: a per-job `asyncio.Queue`-backed event stream so the client can see
per-stage progress instead of a frozen page during the ~20-30s pipeline run.
`GET /` above is untouched and remains the no-JS fallback -- it still blocks
until `produce_verdict()` resolves, exactly as before this story.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.jobs import CLOSE_SENTINEL, create_job, get_job_queue, remove_job, run_job
from app.models.product import InsufficientDataResult
from app.models.verdict import Verdict
from app.pipeline.llm_client import LLMClient, OpenAIClient
from app.pipeline.orchestrator import produce_verdict
from app.pipeline.result_kind import result_kind as compute_result_kind
from app.pipeline.sources.base import ProductSource
from app.pipeline.sources.scraper_tier2 import ScraperTier2Source
from app.settings import Settings

logger = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent

# Built once at import time (NFR-1) -- never per-request. A per-request
# `Settings()` in a `Depends` provider would re-run its validators (e.g.
# `_validate_optional_url`) on every request, so a single malformed env var
# would crash every request, including a plain form-only `GET /`.
_settings = Settings()
_product_source = ScraperTier2Source(_settings)
_llm_client = OpenAIClient(_settings)

app = FastAPI(title="Should I Buy This?")
app.mount("/static", StaticFiles(directory=_APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=_APP_DIR / "templates")

# `GET /jobs` triggers a real scrape plus up to 3 billed OpenAI calls per
# request, with no auth -- rate limiting it is the minimum guard against
# runaway cost from repeat/abusive hits. Per-client-IP, in-memory (no shared
# store needed for this single-process app). `limiter.reset()` exists
# specifically so tests can clear accumulated state between cases.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Holds every `run_job()` background task while it runs. `asyncio.create_task()`
# on its own leaves the event loop holding only a weak reference to the task
# (per `asyncio.create_task()`'s own documentation), so an otherwise-unreferenced
# task can be garbage-collected mid-run. Adding it here, then discarding it via
# `add_done_callback()` once it finishes, keeps a strong reference alive for
# exactly as long as needed and no longer.
_background_tasks: set[asyncio.Task] = set()


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
        result_kind = compute_result_kind(result)

    return templates.TemplateResponse(
        request,
        "index.html",
        {"url": url, "result": result, "result_kind": result_kind},
    )


def _format_sse_event(event: str, data: dict) -> str:
    """Format one SSE `event:`/`data:` pair. `data` is JSON-encoded on one
    line -- SSE's wire format splits on newlines, so the payload must never
    contain a literal unescaped newline, which `json.dumps()` guarantees."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_job_events(job_id: str, queue: "asyncio.Queue") -> AsyncIterator[str]:
    """Read `queue` until `CLOSE_SENTINEL`, yielding one SSE event per item.

    A `QueueProgressPublisher` item (`{"stage": ...}`, see `pipeline/progress.py`)
    becomes an `event: stage` frame. `run_job()`'s own final payload
    (`{"event": "result", "result_kind": ..., "result": ...}`, see
    `app/jobs.py`) becomes the one `event: result` frame that always
    immediately precedes `CLOSE_SENTINEL` -- this generator returns right
    after yielding it, closing the stream (this story's I/O Matrix).

    Once `CLOSE_SENTINEL` is read, removes `job_id` from the job store
    (`remove_job()`) -- otherwise `get_job_queue(job_id)` would keep
    returning this same, already-drained queue forever, and a later request
    for the same job id (a page reload, or `EventSource`'s own
    auto-reconnect) would hang on `await queue.get()` with nothing left to
    ever fill it, instead of correctly 404-ing.
    """
    while True:
        item = await queue.get()
        if item is CLOSE_SENTINEL:
            remove_job(job_id)
            return
        if "stage" in item:
            yield _format_sse_event("stage", {"stage": item["stage"]})
        else:
            yield _format_sse_event(
                "result",
                {"result_kind": item["result_kind"], "result": item["result"]},
            )


@app.get("/jobs")
@limiter.limit("5/minute")
async def create_job_route(
    request: Request,
    url: str,
    source: ProductSource = Depends(get_product_source),
    llm: LLMClient = Depends(get_llm_client),
) -> dict:
    """Create a job for `url` and schedule its pipeline run in the background.

    Returns `{"job_id": ...}` immediately -- before the pipeline itself has
    even started -- so the client can open `GET /jobs/{job_id}/events` right
    away. `url` has no default, so FastAPI itself returns a 422 when it's
    missing, matching this story's I/O Matrix ("No `url` param to `/jobs`").

    The scheduled task is kept in `_background_tasks` until it finishes --
    `asyncio.create_task()` on its own leaves the event loop holding only a
    weak reference, so an unreferenced task can otherwise be garbage
    collected mid-run.

    Rate-limited to 5 requests/minute per client IP (`request` is required
    by `@limiter.limit` to inspect the caller's address) -- this endpoint
    triggers a real scrape plus billed OpenAI calls, so an unbounded caller
    could otherwise run up real cost with no other guard in front of it.
    """
    job_id = create_job()
    task = asyncio.create_task(run_job(job_id, url, source, llm))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """Stream `job_id`'s SSE event stream, or a 404 for an unknown job id.

    `media_type="text/event-stream"` plus `_stream_job_events()` below is
    the entire implementation: zero or more `event: stage` events, then
    exactly one `event: result` event, then the stream closes (this story's
    I/O Matrix) -- never a hanging connection for a bad `job_id`. The extra
    headers disable any intermediary/proxy response buffering so events
    actually reach the client as they're published rather than being held
    back until the stream closes.
    """
    queue = get_job_queue(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return StreamingResponse(
        _stream_job_events(job_id, queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
