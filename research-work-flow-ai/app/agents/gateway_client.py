"""WebSocket client for the CLI Agent Gateway.

Handles connection lifecycle, message routing, and session management.
Provides async streaming for prompts and sync REST methods for skill/MCP management.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import httpx
import structlog
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.connection import State

logger = structlog.get_logger(__name__)


class GatewayConnectionError(Exception):
    """Raised when connection to gateway fails or is lost."""


class GatewayClient:
    """
    WebSocket client for the CLI Agent Gateway.

    Manages session lifecycle, message routing via replyTo, and provides both
    streaming and REST-based operations for agent interaction.

    Connection automatically reconnects with exponential backoff on failure.
    """

    def __init__(self, ws_url: str, http_url: str, reconnect_max_attempts: int = 10, reconnect_base_delay: float = 2.0):
        """Initialize the gateway client.

        Args:
            ws_url: WebSocket URL (e.g., 'ws://localhost:8080/ws')
            http_url: HTTP base URL (e.g., 'http://localhost:8080')
            reconnect_max_attempts: Max reconnection attempts before giving up
            reconnect_base_delay: Initial delay for exponential backoff (seconds)
        """
        self.ws_url = ws_url
        self.http_url = http_url
        self.reconnect_max_attempts = reconnect_max_attempts
        self.reconnect_base_delay = reconnect_base_delay

        self.ws: ClientConnection | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._connection_event = asyncio.Event()

        # Per-session event queues: {(sessionId, flow) -> asyncio.Queue}
        self._session_queues: dict[tuple[str, str], asyncio.Queue[dict[str, Any]]] = {}
        self._queue_lock = asyncio.Lock()

        # HTTP client
        self.http_client = httpx.AsyncClient(base_url=http_url, timeout=30.0)

        logger.info("gateway_client.initialized", ws_url=ws_url, http_url=http_url)

    async def connect(self) -> None:
        """Connect to the gateway WebSocket with exponential backoff retry.

        Raises:
            GatewayConnectionError: If connection fails after max retries.
        """
        for attempt in range(self.reconnect_max_attempts):
            try:
                self.ws = await websockets.connect(self.ws_url)
                self._connection_event.set()
                logger.info("gateway_client.connected", attempt=attempt)

                # Start the read loop
                self._read_task = asyncio.create_task(self._read_loop())
                return
            except Exception as e:
                if attempt == self.reconnect_max_attempts - 1:
                    raise GatewayConnectionError(f"Failed to connect after {self.reconnect_max_attempts} attempts: {e}") from e

                delay = self.reconnect_base_delay * (2**attempt)
                logger.warning(
                    "gateway_client.reconnect_attempt",
                    attempt=attempt,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

    async def disconnect(self) -> None:
        """Close the WebSocket connection and clean up resources."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self.ws:
            await self.ws.close()
            self.ws = None

        self._connection_event.clear()
        logger.info("gateway_client.disconnected")

    async def _ensure_connected(self) -> None:
        """Ensure WebSocket is connected, raise if not."""
        if not self.ws or self.ws.state != State.OPEN:
            raise GatewayConnectionError("Not connected to gateway")

    def _generate_message_id(self) -> str:
        """Generate a unique message ID."""
        return str(uuid.uuid4())

    def _get_timestamp(self) -> str:
        """Get current timestamp in RFC 3339 format."""
        return datetime.now(timezone.utc).isoformat()

    async def send_message(
        self,
        msg_type: str,
        session_id: str,
        flow: str,
        payload: dict[str, Any],
    ) -> str:
        """Send a raw envelope message to the gateway.

        Args:
            msg_type: Message type (e.g., 'prompt.send', 'session.create')
            session_id: Session identifier
            flow: Flow name (e.g., 'claude-code', 'gemini')
            payload: Message-specific payload

        Returns:
            The message ID that was sent.

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()

        msg_id = self._generate_message_id()
        envelope = {
            "id": msg_id,
            "type": msg_type,
            "sessionId": session_id,
            "flow": flow,
            "timestamp": self._get_timestamp(),
            "payload": payload,
        }

        try:
            await self.ws.send(json.dumps(envelope))
            logger.debug(
                "send_message",
                msg_type=msg_type,
                session_id=session_id,
                flow=flow,
                msg_id=msg_id,
            )
            return msg_id
        except Exception as e:
            logger.exception(
                "send_message.error",
                msg_type=msg_type,
                session_id=session_id,
                flow=flow,
            )
            raise

    async def _read_loop(self) -> None:
        """Read WebSocket messages and route to per-session queues.

        Runs continuously in the background. Matches responses by replyTo/sessionId.
        """
        try:
            async for message in self.ws:
                try:
                    envelope = json.loads(message)
                    session_id = envelope.get("sessionId")
                    flow = envelope.get("flow")

                    # Route to session queue
                    if session_id and flow:
                        queue_key = (session_id, flow)
                        async with self._queue_lock:
                            queue = self._session_queues.get(queue_key)

                        if queue:
                            try:
                                queue.put_nowait(envelope)
                            except asyncio.QueueFull:
                                logger.warning(
                                    "_read_loop.queue_full",
                                    session_id=session_id,
                                    flow=flow,
                                    msg_type=envelope.get("type"),
                                )
                        else:
                            logger.debug(
                                "_read_loop.no_queue",
                                session_id=session_id,
                                flow=flow,
                                msg_type=envelope.get("type"),
                            )
                    else:
                        logger.warning(
                            "_read_loop.missing_routing",
                            session_id=session_id,
                            flow=flow,
                        )
                except json.JSONDecodeError as e:
                    logger.warning("_read_loop.invalid_json", error=str(e))
                except Exception as e:
                    logger.exception("_read_loop.process_error", error=str(e))
        except asyncio.CancelledError:
            logger.debug("_read_loop.cancelled")
        except Exception as e:
            logger.exception("_read_loop.fatal_error", error=str(e))
            self._connection_event.clear()

    async def create_session(
        self,
        session_id: str,
        flow: str,
        working_dir: str | None = None,
        model: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new session with the gateway.

        Sends session.create and waits for session.created response.

        Args:
            session_id: Unique session identifier
            flow: Agent flow (e.g., 'claude-code', 'gemini')
            working_dir: Working directory for the agent
            model: Model to use (e.g., 'claude-sonnet-4-6')
            config: Additional session configuration

        Returns:
            The session.created payload.

        Raises:
            GatewayConnectionError: If not connected.
            asyncio.TimeoutError: If no response within timeout.
        """
        await self._ensure_connected()

        # Create queue for this session
        queue_key = (session_id, flow)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        async with self._queue_lock:
            self._session_queues[queue_key] = queue

        payload: dict[str, Any] = {
            "workingDir": working_dir or "/workspace",
            "model": model or "",
        }
        # SessionCreatePayload expects nested `config`, not flat keys
        if config:
            payload["config"] = config

        await self.send_message("session.create", session_id, flow, payload)

        try:
            # Wait for session.created response (timeout 10 seconds)
            response = await asyncio.wait_for(queue.get(), timeout=10.0)
            if response.get("type") != "session.created":
                raise GatewayConnectionError(f"Unexpected response: {response.get('type')}")
            logger.info("create_session.success", session_id=session_id, flow=flow)
            return response.get("payload", {})
        except asyncio.TimeoutError:
            logger.error("create_session.timeout", session_id=session_id, flow=flow)
            raise
        except Exception as e:
            logger.exception("create_session.error", session_id=session_id, flow=flow)
            raise

    async def send_prompt(
        self,
        session_id: str,
        flow: str,
        content: str,
        attachments: list[dict[str, str]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send a prompt to the agent and stream responses.

        This is an async generator that yields events as they arrive:
        - stream.start: Streaming began
        - stream.delta: Content chunk
        - stream.end: Streaming complete
        - agent.status: Status update (thinking, tool_use, etc)
        - tool.use.start: Tool invocation started
        - tool.use.result: Tool completed

        Args:
            session_id: Session identifier
            flow: Agent flow
            content: Prompt text
            attachments: Optional list of attachments (e.g., file paths)
            options: Additional prompt options

        Yields:
            Event dicts with at minimum: {"type": "...", "payload": {...}}

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()

        queue_key = (session_id, flow)
        async with self._queue_lock:
            queue = self._session_queues.get(queue_key)
            if not queue:
                queue = asyncio.Queue(maxsize=1000)
                self._session_queues[queue_key] = queue

        payload = {
            "content": content,
            "attachments": attachments or [],
        }
        if options:
            payload.update(options)

        msg_id = await self.send_message("prompt.send", session_id, flow, payload)
        logger.info("send_prompt.sent", session_id=session_id, flow=flow, msg_id=msg_id)

        # Yield events until stream.end
        stream_ended = False
        while not stream_ended:
            try:
                # Wait for events with timeout
                event = await asyncio.wait_for(queue.get(), timeout=300.0)  # 5 min timeout
                msg_type = event.get("type", "")

                # Yield the event
                yield {
                    "type": msg_type,
                    "payload": event.get("payload", {}),
                    "sessionId": event.get("sessionId"),
                    "timestamp": event.get("timestamp"),
                }

                # Check if stream ended
                if msg_type == "stream.end":
                    stream_ended = True
                    logger.info(
                        "send_prompt.complete",
                        session_id=session_id,
                        flow=flow,
                        finish_reason=event.get("payload", {}).get("finishReason"),
                    )
            except asyncio.TimeoutError:
                logger.error("send_prompt.timeout", session_id=session_id, flow=flow)
                raise
            except asyncio.CancelledError:
                logger.info("send_prompt.cancelled", session_id=session_id, flow=flow)
                # Try to send cancel to gateway
                try:
                    await self.cancel_prompt(session_id, flow)
                except Exception as e:
                    logger.warning("send_prompt.cancel_failed", error=str(e))
                raise

    async def end_session(self, session_id: str, flow: str) -> None:
        """End a session with the gateway.

        Args:
            session_id: Session identifier
            flow: Agent flow

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()
        await self.send_message("session.end", session_id, flow, {})

        # Clean up queue
        queue_key = (session_id, flow)
        async with self._queue_lock:
            self._session_queues.pop(queue_key, None)

        logger.info("end_session.complete", session_id=session_id, flow=flow)

    async def cancel_prompt(self, session_id: str, flow: str) -> None:
        """Cancel an in-flight prompt.

        Args:
            session_id: Session identifier
            flow: Agent flow

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()
        await self.send_message("prompt.cancel", session_id, flow, {})
        logger.info("cancel_prompt.sent", session_id=session_id, flow=flow)

    async def approve_tool_use(self, session_id: str, flow: str, tool_use_id: str) -> None:
        """Approve a tool use request from the agent.

        Args:
            session_id: Session identifier
            flow: Agent flow
            tool_use_id: ID of the tool use to approve

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()
        await self.send_message("tool.approve", session_id, flow, {"toolUseId": tool_use_id})
        logger.info("approve_tool_use.sent", session_id=session_id, flow=flow, tool_use_id=tool_use_id)

    async def reject_tool_use(self, session_id: str, flow: str, tool_use_id: str, reason: str = "") -> None:
        """Reject a tool use request from the agent.

        Args:
            session_id: Session identifier
            flow: Agent flow
            tool_use_id: ID of the tool use to reject
            reason: Reason for rejection

        Raises:
            GatewayConnectionError: If not connected.
        """
        await self._ensure_connected()
        await self.send_message(
            "tool.reject",
            session_id,
            flow,
            {"toolUseId": tool_use_id, "reason": reason},
        )
        logger.info("reject_tool_use.sent", session_id=session_id, flow=flow, tool_use_id=tool_use_id)

    async def register_skill(self, name: str, prompt: str, scope: str = "global", description: str = "") -> dict[str, Any]:
        """Register a skill with the gateway.

        Args:
            name: Skill name
            prompt: Skill prompt template
            scope: Scope ('global', 'session', etc)
            description: Skill description

        Returns:
            Registration response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.post(
            "/skills",
            json={
                "name": name,
                "prompt": prompt,
                "scope": scope,
                "description": description,
            },
        )
        response.raise_for_status()
        logger.info("register_skill.success", skill_name=name)
        return response.json()

    async def attach_skill(self, session_id: str, skill_name: str) -> dict[str, Any]:
        """Attach a skill to a session.

        Args:
            session_id: Session identifier
            skill_name: Name of the skill

        Returns:
            Attachment response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.post(f"/sessions/{session_id}/skills/{skill_name}")
        response.raise_for_status()
        logger.info("attach_skill.success", session_id=session_id, skill_name=skill_name)
        return response.json()

    async def register_mcp(self, name: str, mcp_config: dict[str, Any]) -> dict[str, Any]:
        """Register an MCP with the gateway.

        Args:
            name: MCP name
            mcp_config: MCP configuration dict

        Returns:
            Registration response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.post(
            "/mcps",
            json={
                "name": name,
                "config": mcp_config,
            },
        )
        response.raise_for_status()
        logger.info("register_mcp.success", mcp_name=name)
        return response.json()

    async def attach_mcp(self, session_id: str, mcp_name: str) -> dict[str, Any]:
        """Attach an MCP to a session.

        Args:
            session_id: Session identifier
            mcp_name: Name of the MCP

        Returns:
            Attachment response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.post(f"/sessions/{session_id}/mcps/{mcp_name}")
        response.raise_for_status()
        logger.info("attach_mcp.success", session_id=session_id, mcp_name=mcp_name)
        return response.json()

    async def check_agent_auth(self, agent_name: str) -> dict[str, Any]:
        """Check authentication status of an agent.

        Args:
            agent_name: Name of the agent (e.g., 'claude-code', 'gemini')

        Returns:
            Auth status response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.get(f"/agents/{agent_name}/auth")
        response.raise_for_status()
        logger.info("check_agent_auth.success", agent_name=agent_name)
        return response.json()

    async def check_health(self) -> dict[str, Any]:
        """Check health of the gateway.

        Returns:
            Health status response.

        Raises:
            httpx.RequestError: If HTTP request fails.
        """
        response = await self.http_client.get("/health")
        response.raise_for_status()
        return response.json()

    async def cleanup(self) -> None:
        """Clean up resources (HTTP client, queues, etc)."""
        await self.disconnect()
        await self.http_client.aclose()
        async with self._queue_lock:
            self._session_queues.clear()
        logger.info("gateway_client.cleanup_complete")
