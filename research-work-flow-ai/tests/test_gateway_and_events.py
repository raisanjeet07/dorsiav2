"""Tests for gateway client and event bus modules."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.gateway_client import GatewayClient, GatewayConnectionError
from app.streaming.event_bus import EventBus, get_event_bus, set_event_bus
from app.streaming.events import (
    AgentStreamDeltaEvent,
    AgentStreamEndEvent,
    AgentStreamStartEvent,
    AgentStatusEvent,
    EventType,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowStateChangedEvent,
    serialize_event,
)


class TestEventTypes:
    """Test event type models and serialization."""

    def test_workflow_state_changed_event(self):
        """Test WorkflowStateChangedEvent creation and serialization."""
        event = WorkflowStateChangedEvent(
            workflow_id="wf-123",
            from_state="INITIATED",
            to_state="RESEARCHING",
            trigger="auto",
            review_cycle=0,
        )

        assert event.type == EventType.WORKFLOW_STATE_CHANGED
        assert event.workflow_id == "wf-123"
        assert event.to_state == "RESEARCHING"

        serialized = serialize_event(event)
        assert serialized["type"] == EventType.WORKFLOW_STATE_CHANGED
        assert serialized["workflow_id"] == "wf-123"
        assert isinstance(serialized["timestamp"], str)

    def test_agent_stream_delta_event(self):
        """Test AgentStreamDeltaEvent."""
        event = AgentStreamDeltaEvent(
            workflow_id="wf-123",
            role="researcher",
            content_type="text",
            content="Some research findings...",
        )

        assert event.type == EventType.AGENT_STREAM_DELTA
        assert event.content == "Some research findings..."
        assert event.content_type == "text"

    def test_agent_status_event(self):
        """Test AgentStatusEvent."""
        event = AgentStatusEvent(
            workflow_id="wf-123",
            role="reviewer",
            status="thinking",
            details="Analyzing research findings",
        )

        assert event.status == "thinking"
        assert event.details == "Analyzing research findings"

    def test_workflow_error_event(self):
        """Test WorkflowErrorEvent."""
        event = WorkflowErrorEvent(
            workflow_id="wf-123",
            code="AGENT_TIMEOUT",
            message="Agent did not respond within timeout",
            recoverable=True,
            details={"timeout_seconds": 300},
        )

        assert event.code == "AGENT_TIMEOUT"
        assert event.recoverable is True
        assert event.details["timeout_seconds"] == 300

    def test_serialize_event_timestamp(self):
        """Test that serialize_event handles timestamps correctly."""
        event = AgentStreamStartEvent(
            workflow_id="wf-123",
            role="researcher",
            agent="gemini",
            session_id="sess-456",
        )

        serialized = serialize_event(event)
        assert isinstance(serialized["timestamp"], str)
        # Should be ISO 8601 format
        datetime.fromisoformat(serialized["timestamp"])


class TestEventBus:
    """Test in-process event bus pub/sub."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        """Test basic subscribe and publish."""
        bus = EventBus()
        workflow_id = "wf-test-123"

        # Start subscriber
        events_received = []

        async def subscribe_and_collect():
            async for event in bus.subscribe(workflow_id):
                events_received.append(event)
                if len(events_received) >= 2:
                    break

        sub_task = asyncio.create_task(subscribe_and_collect())
        await asyncio.sleep(0.1)  # Let subscriber start

        # Publish events
        event1 = AgentStreamStartEvent(
            workflow_id=workflow_id,
            role="researcher",
            agent="gemini",
            session_id="sess-1",
        )
        event2 = AgentStreamDeltaEvent(
            workflow_id=workflow_id,
            role="researcher",
            content="Finding 1",
        )

        await bus.publish(workflow_id, event1)
        await bus.publish(workflow_id, event2)

        # Wait for collection
        await asyncio.wait_for(sub_task, timeout=2.0)

        assert len(events_received) == 2
        assert events_received[0].type == EventType.AGENT_STREAM_START
        assert events_received[1].type == EventType.AGENT_STREAM_DELTA

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple subscribers to same workflow."""
        bus = EventBus()
        workflow_id = "wf-multi"

        received_by_sub1 = []
        received_by_sub2 = []

        async def sub1():
            async for event in bus.subscribe(workflow_id):
                received_by_sub1.append(event)
                if len(received_by_sub1) >= 1:
                    break

        async def sub2():
            async for event in bus.subscribe(workflow_id):
                received_by_sub2.append(event)
                if len(received_by_sub2) >= 1:
                    break

        task1 = asyncio.create_task(sub1())
        task2 = asyncio.create_task(sub2())
        await asyncio.sleep(0.1)

        # Publish to both
        event = AgentStatusEvent(
            workflow_id=workflow_id,
            role="reviewer",
            status="idle",
        )
        await bus.publish(workflow_id, event)

        await asyncio.wait_for(asyncio.gather(task1, task2), timeout=2.0)

        assert len(received_by_sub1) == 1
        assert len(received_by_sub2) == 1

    @pytest.mark.asyncio
    async def test_queue_full_handling(self):
        """Test handling of full queues (non-blocking publish)."""
        bus = EventBus(queue_size=2)
        workflow_id = "wf-full"

        # Start subscriber but don't consume
        sub_task = asyncio.create_task(bus.subscribe(workflow_id))
        await asyncio.sleep(0.1)

        # Publish more than queue size
        for i in range(5):
            event = AgentStreamDeltaEvent(
                workflow_id=workflow_id,
                role="researcher",
                content=f"Delta {i}",
            )
            # Should not raise, just log warning
            await bus.publish(workflow_id, event)

        # Clean up
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_auto_unsubscribe(self):
        """Test that closing generator unsubscribes automatically."""
        bus = EventBus()
        workflow_id = "wf-unsub"

        # Create and close subscriber immediately
        async for _ in bus.subscribe(workflow_id):
            break

        # Should have no subscribers now
        count = await bus.get_subscriber_count(workflow_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test statistics gathering."""
        bus = EventBus()

        # No subscribers initially
        stats = await bus.get_stats()
        assert stats["workflows"] == 0
        assert stats["total_subscribers"] == 0

        # Add some subscribers
        async def dummy_sub(wf_id):
            async for _ in bus.subscribe(wf_id):
                await asyncio.sleep(0.5)

        task1 = asyncio.create_task(dummy_sub("wf-1"))
        task2 = asyncio.create_task(dummy_sub("wf-1"))
        task3 = asyncio.create_task(dummy_sub("wf-2"))
        await asyncio.sleep(0.1)

        stats = await bus.get_stats()
        assert stats["workflows"] == 2
        assert stats["total_subscribers"] == 3

        # Clean up
        for task in [task1, task2, task3]:
            task.cancel()

    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test get_event_bus singleton."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

        # Test set_event_bus
        new_bus = EventBus()
        set_event_bus(new_bus)
        bus3 = get_event_bus()
        assert bus3 is new_bus


class TestGatewayClient:
    """Test WebSocket gateway client (mocked)."""

    def test_client_initialization(self):
        """Test GatewayClient initialization."""
        client = GatewayClient(
            ws_url="ws://localhost:8080/ws",
            http_url="http://localhost:8080",
        )

        assert client.ws_url == "ws://localhost:8080/ws"
        assert client.http_url == "http://localhost:8080"
        assert client.ws is None
        assert client.reconnect_max_attempts == 10

    def test_message_id_generation(self):
        """Test that message IDs are unique."""
        client = GatewayClient("ws://localhost:8080/ws", "http://localhost:8080")

        id1 = client._generate_message_id()
        id2 = client._generate_message_id()

        assert id1 != id2
        assert len(id1) == 36  # UUID format

    def test_timestamp_generation(self):
        """Test RFC 3339 timestamp generation."""
        client = GatewayClient("ws://localhost:8080/ws", "http://localhost:8080")

        ts = client._get_timestamp()
        # Should be parseable as ISO 8601
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    @pytest.mark.asyncio
    async def test_connection_error_not_connected(self):
        """Test error when trying to send without connection."""
        client = GatewayClient("ws://localhost:8080/ws", "http://localhost:8080")

        with pytest.raises(GatewayConnectionError):
            await client.send_message("test.message", "sess-1", "claude-code", {})

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test cleanup method."""
        client = GatewayClient("ws://localhost:8080/ws", "http://localhost:8080")

        # Mock the http_client
        client.http_client = AsyncMock()

        await client.cleanup()

        # HTTP client should be closed
        client.http_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_structure(self):
        """Test that send_message creates proper envelope."""
        client = GatewayClient("ws://localhost:8080/ws", "http://localhost:8080")

        # Mock websocket
        mock_ws = AsyncMock()
        mock_ws.closed = False
        client.ws = mock_ws

        msg_id = await client.send_message(
            msg_type="prompt.send",
            session_id="sess-123",
            flow="claude-code",
            payload={"content": "Test prompt"},
        )

        # Verify websocket.send was called
        assert mock_ws.send.called

        # Parse the message that was sent
        sent_msg = json.loads(mock_ws.send.call_args[0][0])

        assert sent_msg["id"] == msg_id
        assert sent_msg["type"] == "prompt.send"
        assert sent_msg["sessionId"] == "sess-123"
        assert sent_msg["flow"] == "claude-code"
        assert sent_msg["payload"]["content"] == "Test prompt"
        assert "timestamp" in sent_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
