"""WebSocket endpoint for real-time workflow event streaming."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.persistence.repositories import Repository
from app.streaming.events import serialize_event

logger = structlog.get_logger(__name__)


async def handle_workflow_websocket(websocket: WebSocket, workflow_id: str) -> None:
    """Handle WebSocket connection for a specific workflow.

    Args:
        websocket: The WebSocket connection
        workflow_id: The workflow ID
    """
    event_bus = websocket.app.state.event_bus
    orchestrator = websocket.app.state.orchestrator

    # Must accept the WebSocket before close/send; closing without accept can crash ASGI workers.
    await websocket.accept()

    # Validate workflow exists (per-request DB session — app.state has no shared repository)
    session = websocket.app.state.session_factory()
    repository = Repository(session)
    workflow = None
    lookup_error: Exception | None = None
    try:
        workflow = await repository.get_workflow(workflow_id)
    except Exception as exc:
        lookup_error = exc
        logger.exception(
            "websocket.workflow_lookup_failed",
            workflow_id=workflow_id,
            error=str(exc),
        )
    finally:
        await session.close()

    if lookup_error is not None:
        try:
            await websocket.close(code=1011, reason="Failed to load workflow")
        except Exception:
            pass
        return

    if not workflow:
        await websocket.close(code=1008, reason="Workflow not found")
        return

    logger.info("websocket.connected", workflow_id=workflow_id, client=websocket.client)

    # Send current state as first message
    try:
        state = await orchestrator.get_workflow_state(workflow_id)
        await websocket.send_json({
            "type": "connection.state",
            "workflow_id": workflow_id,
            "data": state,
        })
    except Exception as e:
        logger.exception("websocket.send_initial_state_failed", workflow_id=workflow_id, error=str(e))
        await websocket.close(code=1011, reason="Failed to send initial state")
        return

    # Replay gateway session snapshots (agent.session) so clients that connect
    # after the workflow already created sessions still see session rows.
    try:
        snap_store = getattr(websocket.app.state, "gateway_session_snapshots", None)
        if snap_store is not None:
            for row in snap_store.get_workflow(workflow_id):
                await websocket.send_json(row)
    except Exception as e:
        logger.exception(
            "websocket.snapshot_replay_failed",
            workflow_id=workflow_id,
            error=str(e),
        )

    # Create tasks for bidirectional communication
    subscribe_task = None
    receive_task = None

    try:
        async def event_stream() -> None:
            """Subscribe to events and send to client."""
            async for event in event_bus.subscribe(workflow_id):
                try:
                    event_dict = serialize_event(event)
                    await websocket.send_json(event_dict)
                except Exception as e:
                    logger.exception(
                        "websocket.send_event_failed",
                        workflow_id=workflow_id,
                        event_type=event.type,
                        error=str(e),
                    )
                    break

        async def message_handler() -> None:
            """Handle incoming client messages."""
            try:
                while True:
                    data = await websocket.receive_json()

                    if not isinstance(data, dict):
                        logger.warning("websocket.invalid_message_type", workflow_id=workflow_id)
                        continue

                    message_type = data.get("type")
                    payload = data.get("payload", {})

                    logger.info(
                        "websocket.message_received",
                        workflow_id=workflow_id,
                        message_type=message_type,
                    )

                    try:
                        if message_type == "user.message":
                            # Handle user chat message
                            message = payload.get("message", "")
                            if not message:
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_message",
                                    "message": "Message cannot be empty",
                                })
                                continue

                            # Stream response chunks
                            try:
                                # Assistant chunks are published on the event bus as
                                # ``user.chat_response`` and forwarded by event_stream().
                                await orchestrator.handle_user_message(
                                    workflow_id=workflow_id,
                                    message=message,
                                )
                            except ValueError as e:
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_state",
                                    "message": str(e),
                                })

                        elif message_type == "user.approve":
                            # Handle user approval
                            comment = payload.get("comment", "")
                            try:
                                result = await orchestrator.handle_user_approve(
                                    workflow_id=workflow_id,
                                    comment=comment,
                                )
                                await websocket.send_json({
                                    "type": "user.approval_accepted",
                                    "workflow_id": workflow_id,
                                    "data": result,
                                })
                            except ValueError as e:
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_state",
                                    "message": str(e),
                                })

                        elif message_type == "user.request_changes":
                            # Handle change request
                            changes = payload.get("changes", {})
                            if not isinstance(changes, dict):
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_changes",
                                    "message": "Changes must be a dictionary",
                                })
                                continue

                            try:
                                result = await orchestrator.handle_user_changes(
                                    workflow_id=workflow_id,
                                    changes=changes,
                                )
                                await websocket.send_json({
                                    "type": "user.changes_accepted",
                                    "workflow_id": workflow_id,
                                    "data": result,
                                })
                            except ValueError as e:
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_state",
                                    "message": str(e),
                                })

                        elif message_type == "user.cancel":
                            # Handle cancel request
                            try:
                                result = await orchestrator.cancel_workflow(workflow_id)
                                await websocket.send_json({
                                    "type": "user.cancel_accepted",
                                    "workflow_id": workflow_id,
                                    "data": result,
                                })
                            except ValueError as e:
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "invalid_state",
                                    "message": str(e),
                                })

                        else:
                            logger.warning(
                                "websocket.unknown_message_type",
                                workflow_id=workflow_id,
                                message_type=message_type,
                            )
                            await websocket.send_json({
                                "type": "error",
                                "code": "unknown_message_type",
                                "message": f"Unknown message type: {message_type}",
                            })

                    except ValidationError as e:
                        logger.warning(
                            "websocket.validation_error",
                            workflow_id=workflow_id,
                            error=str(e),
                        )
                        await websocket.send_json({
                            "type": "error",
                            "code": "validation_error",
                            "message": "Invalid message format",
                        })
                    except Exception as e:
                        logger.exception(
                            "websocket.message_handler_error",
                            workflow_id=workflow_id,
                            error=str(e),
                        )
                        await websocket.send_json({
                            "type": "error",
                            "code": "internal_error",
                            "message": "Internal error processing message",
                        })

            except WebSocketDisconnect:
                logger.info("websocket.client_disconnected", workflow_id=workflow_id)
            except Exception as e:
                logger.exception(
                    "websocket.message_handler_fatal_error",
                    workflow_id=workflow_id,
                    error=str(e),
                )

        # Run both tasks concurrently
        subscribe_task = asyncio.create_task(event_stream())
        receive_task = asyncio.create_task(message_handler())

        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [subscribe_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining task
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info("websocket.client_disconnected", workflow_id=workflow_id)
    except Exception as e:
        logger.exception("websocket.error", workflow_id=workflow_id, error=str(e))
    finally:
        # Cleanup
        if subscribe_task and not subscribe_task.done():
            subscribe_task.cancel()
        if receive_task and not receive_task.done():
            receive_task.cancel()

        try:
            await websocket.close()
        except Exception:
            pass

        logger.info("websocket.connection_closed", workflow_id=workflow_id)
