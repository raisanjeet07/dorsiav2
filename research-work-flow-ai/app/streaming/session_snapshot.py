"""In-memory snapshot of gateway agent.session events for late WebSocket clients.

The event bus only delivers to *current* subscribers. UI clients that open after a
phase has already started would otherwise never see ``agent.session`` payloads.
This store is updated on every ``AgentSessionLifecycleEvent`` publish and replayed
on WebSocket connect after ``connection.state``.
"""

from __future__ import annotations

from typing import Any


class GatewaySessionSnapshotStore:
    """Keeps the latest row per (workflow_id, session_id, flow)."""

    def __init__(self, max_per_workflow: int = 64) -> None:
        self._max = max_per_workflow
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def record(self, workflow_id: str, event_dict: dict[str, Any]) -> None:
        """Upsert a serialized ``agent.session`` event."""
        lst = self._rows.setdefault(workflow_id, [])
        sid = event_dict.get("session_id")
        flow = event_dict.get("flow")
        key = (sid, flow)
        for i, row in enumerate(lst):
            if (row.get("session_id"), row.get("flow")) == key:
                lst[i] = event_dict
                break
        else:
            lst.append(event_dict)
            if len(lst) > self._max:
                del lst[: len(lst) - self._max]

    def get_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        """Return a shallow copy of snapshots for replay."""
        return list(self._rows.get(workflow_id, []))
