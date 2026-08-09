"""In-memory live state: the twin's "now", plus WebSocket fan-out.

The database is the twin's memory; this is its present moment. Keeping the latest
frame per system in memory means ``/state`` and new WebSocket subscribers answer
instantly without a query, and the ingest loop can broadcast each frame to every
connected client as it arrives.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class LatestState:
    """Newest telemetry envelope per system id."""

    def __init__(self) -> None:
        self._latest: dict[str, dict[str, Any]] = {}

    def update(self, system_id: str, envelope: dict[str, Any]) -> None:
        self._latest[system_id] = envelope

    def remove(self, system_id: str) -> None:
        """Drop a system's cached frame (on delete)."""
        self._latest.pop(system_id, None)

    def get(self, system_id: str) -> dict[str, Any] | None:
        return self._latest.get(system_id)

    def system_ids(self) -> list[str]:
        return sorted(self._latest.keys())

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """The full ``{system_id: envelope}`` map (for fleet aggregation)."""
        return self._latest


class WebSocketManager:
    """Tracks WebSocket subscribers per system and broadcasts frames to them."""

    def __init__(self) -> None:
        self._clients: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, system_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.setdefault(system_id, set()).add(ws)

    async def disconnect(self, system_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.get(system_id, set()).discard(ws)

    async def broadcast(self, system_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._clients.get(system_id, set()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:  # client vanished mid-send
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.get(system_id, set()).discard(ws)
