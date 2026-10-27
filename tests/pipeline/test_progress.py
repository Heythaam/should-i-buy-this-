"""Tests for `ProgressPublisher`/`NullProgressPublisher`/`QueueProgressPublisher`
(Story 1.9, AD-4, AD-9, AD-10).
"""

import asyncio

from app.pipeline.progress import NullProgressPublisher, QueueProgressPublisher


def test_null_progress_publisher_is_a_complete_no_op():
    publisher = NullProgressPublisher()

    result = asyncio.run(publisher.publish("resolving_product"))

    assert result is None


def test_queue_progress_publisher_puts_stage_payload_onto_the_queue():
    queue: asyncio.Queue = asyncio.Queue()
    publisher = QueueProgressPublisher(queue)

    asyncio.run(publisher.publish("resolving_product"))

    assert queue.get_nowait() == {"stage": "resolving_product"}


def test_queue_progress_publisher_preserves_publish_order():
    queue: asyncio.Queue = asyncio.Queue()
    publisher = QueueProgressPublisher(queue)

    async def _publish_all():
        await publisher.publish("resolving_product")
        await publisher.publish("sampling_reviews")
        await publisher.publish("finding_alternatives")

    asyncio.run(_publish_all())

    assert queue.get_nowait() == {"stage": "resolving_product"}
    assert queue.get_nowait() == {"stage": "sampling_reviews"}
    assert queue.get_nowait() == {"stage": "finding_alternatives"}


def test_queue_progress_publisher_never_raises_on_a_full_queue():
    # maxsize=1 and one item already enqueued -- the queue is full, so a
    # naive put would raise `QueueFull`; `publish()` must swallow it (AD-4,
    # AD-9: a publisher never raises and never blocks on a slow/stuck
    # consumer).
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"stage": "already_here"})
    publisher = QueueProgressPublisher(queue)

    result = asyncio.run(publisher.publish("resolving_product"))

    assert result is None
    # The original item is untouched -- the new one was dropped, not forced in.
    assert queue.get_nowait() == {"stage": "already_here"}
    assert queue.empty()
