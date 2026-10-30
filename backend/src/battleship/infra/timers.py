"""Cancellable asyncio timers owned per room (ticket #12).

The legacy stack used eventlet `start_background_task` + `sleep`, which cannot be
cancelled and kept running after a room was dropped. Chain response windows,
the 1.2s display delay and the AI response delay are all background waits, so
they must be:

* cancelable per room (room dissolved / match ended / server shutdown);
* generation-tokened, so a stale task can never resolve the current stack;
* observable (`pending(room_id)`) so a leak fails a test instead of hiding.

This registry is infrastructure only: it knows nothing about chains.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from .logging import get_logger

logger = get_logger("timers")


class TaskRegistry:
    """Spawn and cancel background tasks, grouped by room id."""

    def __init__(self) -> None:
        self._tasks: dict[str, set[asyncio.Task]] = {}

    def spawn(self, room_id: str, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task | None:
        """Start a task on the running loop; returns None outside a loop.

        A `None` result is not an error by itself: callers that need the work
        done regardless must fall back to doing it inline (the chain engine
        resolves immediately in that case, exactly like the legacy
        "background task could not be scheduled" branch).
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coroutine.close()
            return None
        task = loop.create_task(coroutine)
        self._tasks.setdefault(room_id, set()).add(task)

        def _finished(done: asyncio.Task) -> None:
            bucket = self._tasks.get(room_id)
            if bucket is not None:
                bucket.discard(done)
                if not bucket:
                    self._tasks.pop(room_id, None)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.error(
                    "background timer failed",
                    extra={"room_id": room_id, "error_type": type(error).__name__},
                    exc_info=error,
                )

        task.add_done_callback(_finished)
        return task

    def pending(self, room_id: str | None = None) -> int:
        if room_id is None:
            return sum(len(bucket) for bucket in self._tasks.values())
        return len(self._tasks.get(room_id, ()))

    def cancel_room(self, room_id: str) -> int:
        """Cancel every timer owned by one room. Idempotent."""

        bucket = self._tasks.pop(room_id, set())
        for task in bucket:
            task.cancel()
        return len(bucket)

    async def cancel_all(self) -> None:
        pending = [task for bucket in self._tasks.values() for task in bucket]
        self._tasks.clear()
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown
                pass


__all__ = ["TaskRegistry"]
