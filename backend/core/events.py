"""
core/events.py
--------------
In-process event bus. Used to broadcast WebSocket events from Celery worker
to the FastAPI WebSocket handler via Redis Pub/Sub.

NOTE: Cross-process events go through Redis (see swarm_controller.py).
This module handles in-process subscriptions only (used in tests).
"""
import asyncio
from collections import defaultdict
from typing import Callable


class EventBus:
    """Simple async event bus for in-process pub/sub."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers[event_type] = [
            h for h in self._subscribers[event_type] if h != handler
        ]

    async def publish(self, event_type: str, data: dict) -> None:
        for handler in self._subscribers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception:
                pass  # Never let a subscriber crash the publisher


# Module-level singleton
event_bus = EventBus()
