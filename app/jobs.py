"""The in-memory per-job event queue and background runner (AD-10).

`GET /jobs?url=...` (in `app/main.py`) creates a job here, then schedules
`run_job()` as a background `asyncio.create_task()` -- the request returns
the new `job_id` immediately, before the pipeline itself has even started.
`GET /jobs/{job_id}/events` then reads the same job's queue to stream SSE
events as `run_job()`'s pipeline run publishes them.

The job store is in-memory only, keyed by a random (unguessable) job id --
no persistence, no cross-process sharing, no expiry/cleanup in this story
(Epic 4's job, or a future chore, per this story's Boundaries & Constraints).
"""

import asyncio
import logging
import uuid

from app.models.product import InsufficientDataResult
from app.pipeline.llm_client import LLMClient
from app.pipeline.orchestrator import produce_verdict
from app.pipeline.progress import QueueProgressPublisher
from app.pipeline.result_kind import result_kind
from app.pipeline.sources.base import ProductSource

logger = logging.getLogger(__name__)

CLOSE_SENTINEL = object()
"""Enqueued as the last item on a job's queue once `run_job()` finishes.
`GET /jobs/{job_id}/events` reads the queue until it sees this exact object,
then stops reading and closes the stream."""

_jobs: dict[str, "asyncio.Queue"] = {}


def create_job() -> str:
    """Create a new job and its backing (unbounded) queue.

    Returns the new, randomly-generated job id. The queue is created here --
    not lazily inside `run_job()` -- so `GET /jobs/{job_id}/events` can start
    reading immediately, even if it beats `run_job()`'s first `publish()`
    call (no event is ever lost to a race between the two).
    """
    job_id = uuid.uuid4().hex
    _jobs[job_id] = asyncio.Queue()
    return job_id


def get_job_queue(job_id: str) -> "asyncio.Queue | None":
    """Return the queue for `job_id`, or `None` if no such job exists.

    Used both by `GET /jobs/{job_id}/events` (an unknown id is a 404 -- see
    `app/main.py`) and by `run_job()` itself.
    """
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    """Drop `job_id`'s entry from the job store, if present.

    Called once `GET /jobs/{job_id}/events` has read through
    `CLOSE_SENTINEL`, so a later request for the same (now-finished) job id
    -- a page reload, or `EventSource`'s own auto-reconnect -- correctly
    falls into the 404 path instead of blocking forever on a queue nothing
    will ever fill again. Also keeps `_jobs` from growing unbounded over the
    process lifetime.
    """
    _jobs.pop(job_id, None)


async def run_job(job_id: str, url: str, source: ProductSource, llm: LLMClient) -> None:
    """Run the full pipeline for `url`, publishing progress onto `job_id`'s queue.

    Builds a `QueueProgressPublisher` wrapping the job's queue and calls
    `produce_verdict(url, source, llm, progress=publisher)` so every stage
    transition the pipeline publishes lands on the queue as it happens
    (AD-10). Once the pipeline resolves, enqueues exactly one final
    `{"event": "result", ...}` payload -- the resolved `Verdict`/
    `InsufficientDataResult`'s fields plus the same `result_kind`
    classification `GET /` already computes
    (`app.pipeline.result_kind.result_kind()`), so the confidence-threshold
    business logic stays server-side and isn't duplicated in client-side JS
    -- then enqueues `CLOSE_SENTINEL` so the SSE route knows to stop reading
    and close the stream.

    Scheduled via `asyncio.create_task()` by `GET /jobs`; the request that
    creates the job never awaits this function directly, so it must never
    raise an unhandled exception out of an orphaned task -- any unexpected
    failure here is caught and turned into an `InsufficientDataResult`
    result event instead of leaving the job's stream open forever. This
    includes failures while building the result payload itself (computing
    `result_kind`, `model_dump()`, enqueueing either item): both are wrapped
    in a `try`/`finally` so `CLOSE_SENTINEL` is still guaranteed to be
    enqueued even if that fails.
    """
    queue = get_job_queue(job_id)
    if queue is None:
        logger.error("run_job: no queue for job_id %s -- job was never created", job_id)
        return

    try:
        result = await produce_verdict(
            url, source, llm, progress=QueueProgressPublisher(queue)
        )
    except Exception as exc:  # run_job must never raise (AD-4, AD-9)
        logger.exception("run_job: unexpected error running pipeline for job %s", job_id)
        result = InsufficientDataResult(reason="unexpected_error", detail=str(exc))

    try:
        queue.put_nowait(
            {
                "event": "result",
                "result_kind": result_kind(result),
                "result": result.model_dump(mode="json"),
            }
        )
    finally:
        queue.put_nowait(CLOSE_SENTINEL)
