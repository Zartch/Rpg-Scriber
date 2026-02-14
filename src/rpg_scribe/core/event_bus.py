"""Async event bus implementing the pub/sub pattern."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Type

logger = logging.getLogger(__name__)


class EventBus:
    """Async event bus. Decoupled pub/sub pattern.

    Subscribers register handlers for specific event types.
    When an event is published, all handlers for that type are called concurrently.
    """

    def __init__(self) -> None:
        self._handlers: dict[Type, list[Callable[..., Coroutine[Any, Any, None]]]] = (
            defaultdict(list)
        )

    def subscribe(
        self,
        event_type: Type,
        handler: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Register a handler for an event type."""
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: Type,
        handler: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Remove a handler for an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Any) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are called concurrently via asyncio.gather.
        Exceptions in individual handlers are logged but do not
        prevent other handlers from running.
        """
        event_type = type(event)
        handlers = list(self._handlers.get(event_type, []))
        if not handlers:
            return

        results = await asyncio.gather(
            *(h(event) for h in handlers),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Handler %s raised %s for event %s: %s",
                    handlers[i].__qualname__,
                    type(result).__name__,
                    event_type.__name__,
                    result,
                )
