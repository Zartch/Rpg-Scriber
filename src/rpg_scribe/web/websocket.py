"""WebSocket manager for broadcasting live updates to connected clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket client connected (%d active)", self.active_count)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket client disconnected (%d active)", self.active_count)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to all connected clients."""
        payload = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.remove(ws)


class WebSocketBridge:
    """Bridges the EventBus to WebSocket clients.

    Subscribes to TranscriptionEvent, SummaryUpdateEvent, and
    SystemStatusEvent, then broadcasts them to all connected WebSocket
    clients as JSON messages.
    """

    def __init__(self, event_bus: EventBus, manager: ConnectionManager) -> None:
        self._event_bus = event_bus
        self._manager = manager

    async def start(self) -> None:
        """Subscribe to relevant events on the bus."""
        self._event_bus.subscribe(TranscriptionEvent, self._on_transcription)
        self._event_bus.subscribe(SummaryUpdateEvent, self._on_summary)
        self._event_bus.subscribe(SystemStatusEvent, self._on_status)
        logger.info("WebSocketBridge started")

    async def stop(self) -> None:
        """Unsubscribe from the bus."""
        self._event_bus.unsubscribe(TranscriptionEvent, self._on_transcription)
        self._event_bus.unsubscribe(SummaryUpdateEvent, self._on_summary)
        self._event_bus.unsubscribe(SystemStatusEvent, self._on_status)
        logger.info("WebSocketBridge stopped")

    async def _on_transcription(self, event: TranscriptionEvent) -> None:
        await self._manager.broadcast({
            "type": "transcription",
            "data": asdict(event),
        })

    async def _on_summary(self, event: SummaryUpdateEvent) -> None:
        await self._manager.broadcast({
            "type": "summary",
            "data": asdict(event),
        })

    async def _on_status(self, event: SystemStatusEvent) -> None:
        await self._manager.broadcast({
            "type": "status",
            "data": asdict(event),
        })
