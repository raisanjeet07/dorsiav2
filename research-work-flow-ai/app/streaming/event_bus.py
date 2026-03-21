"""In-process async pub/sub event bus for workflow events.

Supports multiple subscribers per workflow with per-workflow async queues.
Non-blocking publish with queue overflow handling.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator

import structlog

from app.streaming.events import WorkflowEvent, serialize_event

logger = structlog.get_logger(__name__)


class EventBus:
    """
    In-process async pub/sub for workflow events.

    Manages per-workflow channels with multiple subscribers.
    Publish is non-blocking; if queue is full, events are dropped with a warning.
    """

    def __init__(self, queue_size: int = 1000):
        """Initialize the event bus.

        Args:
            queue_size: Maximum number of events per subscriber queue.
        """
        self.queue_size = queue_size
        # workflow_id -> {subscriber_id -> queue}
        self.subscribers: dict[str, dict[str, asyncio.Queue[WorkflowEvent]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, workflow_id: str) -> AsyncGenerator[WorkflowEvent, None]:
        """Subscribe to events for a specific workflow.

        Yields events as they are published. When the generator is closed,
        the subscriber is automatically unregistered.

        Args:
            workflow_id: ID of the workflow to subscribe to.

        Yields:
            WorkflowEvent: Events published to this workflow.
        """
        subscriber_id = str(uuid.uuid4())
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self.queue_size)

        # Register subscriber
        async with self._lock:
            if workflow_id not in self.subscribers:
                self.subscribers[workflow_id] = {}
            self.subscribers[workflow_id][subscriber_id] = queue

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            # Auto-unsubscribe when generator closes
            await self.unsubscribe(workflow_id, subscriber_id)

    async def publish(self, workflow_id: str, event: WorkflowEvent) -> None:
        """Publish an event to all subscribers of a workflow.

        Non-blocking: if a queue is full, the event is dropped with a warning.

        Args:
            workflow_id: ID of the workflow.
            event: Event to publish.
        """
        async with self._lock:
            subscribers = self.subscribers.get(workflow_id, {})

        if not subscribers:
            logger.debug("publish.no_subscribers", workflow_id=workflow_id, event_type=event.type)
            return

        failed_subs = []

        for subscriber_id, queue in subscribers.items():
            try:
                # Non-blocking put; raises Full if queue is at max capacity
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "publish.queue_full",
                    workflow_id=workflow_id,
                    subscriber_id=subscriber_id,
                    event_type=event.type,
                    queue_size=self.queue_size,
                )
                failed_subs.append(subscriber_id)
            except Exception as e:
                logger.exception(
                    "publish.unexpected_error",
                    workflow_id=workflow_id,
                    subscriber_id=subscriber_id,
                    event_type=event.type,
                    error=str(e),
                )

        if failed_subs and logger.is_enabled_for("info"):
            logger.info(
                "publish.completed",
                workflow_id=workflow_id,
                total_subscribers=len(subscribers),
                failed_count=len(failed_subs),
                event_type=event.type,
            )

    async def unsubscribe(self, workflow_id: str, subscriber_id: str) -> None:
        """Unsubscribe a specific subscriber from a workflow.

        Args:
            workflow_id: ID of the workflow.
            subscriber_id: ID of the subscriber to remove.
        """
        async with self._lock:
            if workflow_id in self.subscribers:
                self.subscribers[workflow_id].pop(subscriber_id, None)
                # Clean up empty workflow entries
                if not self.subscribers[workflow_id]:
                    del self.subscribers[workflow_id]
                    logger.debug("unsubscribe.workflow_cleanup", workflow_id=workflow_id)

    async def get_subscriber_count(self, workflow_id: str) -> int:
        """Get the number of active subscribers for a workflow.

        Args:
            workflow_id: ID of the workflow.

        Returns:
            Number of active subscribers.
        """
        async with self._lock:
            return len(self.subscribers.get(workflow_id, {}))

    async def get_stats(self) -> dict[str, int]:
        """Get statistics about the event bus.

        Returns:
            Dict with 'workflows' (count of workflows with subscribers)
            and 'total_subscribers' (total across all workflows).
        """
        async with self._lock:
            total_subs = sum(len(subs) for subs in self.subscribers.values())
            return {
                "workflows": len(self.subscribers),
                "total_subscribers": total_subs,
            }


# Global singleton event bus instance
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus singleton.

    Returns:
        The global EventBus instance.
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus: EventBus) -> None:
    """Set the global event bus singleton (for testing).

    Args:
        bus: The EventBus instance to use globally.
    """
    global _event_bus
    _event_bus = bus
