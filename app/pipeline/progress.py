"""The additive progress-publishing contract (core/shared, AD-10).

`ProgressPublisher` is the one interface every pipeline stage calls on entry
to announce its stage name. It is deliberately tiny and fire-and-forget:

- `NullProgressPublisher` is the implicit default every pipeline function
  falls back to when no `progress` argument is given -- publishing is then a
  complete no-op, so every existing call site/test from Stories 1.1-1.7 is
  unaffected (this story's own boundary).
- `QueueProgressPublisher` wraps the per-job `asyncio.Queue` created in
  `app/jobs.py` and is what `run_job()` actually passes into
  `produce_verdict()`. `publish()` never raises and never blocks pipeline
  execution on a slow/stuck consumer (AD-4, AD-9): it uses `put_nowait()`
  wrapped in a broad `except Exception` so a full/closed/misbehaving queue
  degrades to "the event was dropped" rather than crashing or stalling the
  stage that published it.
"""

import logging
from asyncio import Queue, QueueFull
from typing import Protocol

logger = logging.getLogger(__name__)


class ProgressPublisher(Protocol):
    """Publishes a pipeline stage's name on entry."""

    async def publish(self, stage: str) -> None:
        """Announce that `stage` has started.

        Never raises (AD-4, AD-9): implementations degrade silently rather
        than propagate an exception into the pipeline stage that called
        them.
        """
        ...


class NullProgressPublisher:
    """A complete no-op `ProgressPublisher`.

    Used as the implicit default whenever a pipeline function is called
    without a `progress` argument -- publishes nothing, so behavior is
    identical to before this story.
    """

    async def publish(self, stage: str) -> None:
        return None


class QueueProgressPublisher:
    """A `ProgressPublisher` backed by one job's `asyncio.Queue`.

    `publish()` puts `{"stage": stage}` onto the wrapped queue. It is a
    fire-and-forget `put_nowait()` -- it never awaits a slow/stuck consumer
    and never raises out of the calling pipeline stage, even if the queue is
    full or otherwise misbehaves.
    """

    def __init__(self, queue: "Queue") -> None:
        self._queue = queue

    async def publish(self, stage: str) -> None:
        try:
            self._queue.put_nowait({"stage": stage})
        except QueueFull:
            logger.warning("QueueProgressPublisher: queue full, dropping stage %s", stage)
        except Exception:  # AD-4/AD-9: publish() never raises out
            logger.exception(
                "QueueProgressPublisher: unexpected error publishing stage %s", stage
            )
