"""FastAPI application factory for RPG Scribe web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.web.routes import WebState, router
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(event_bus: EventBus, database: object | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    The app subscribes to the event bus so that incoming events are
    both stored in ``WebState`` (for REST queries) and broadcast to
    all connected WebSocket clients via ``WebSocketBridge``.
    """
    state = WebState()
    manager = ConnectionManager()
    bridge = WebSocketBridge(event_bus, manager)

    # ── Event handlers that keep WebState in sync ────────────────

    async def _on_transcription(event: TranscriptionEvent) -> None:
        state.add_transcription(asdict(event))

    async def _on_summary(event: SummaryUpdateEvent) -> None:
        state.update_summary(asdict(event))

    async def _on_status(event: SystemStatusEvent) -> None:
        state.update_component_status(asdict(event))

    # Subscribe eagerly — EventBus.subscribe is synchronous and the
    # handlers are valid as soon as the app object exists.
    event_bus.subscribe(TranscriptionEvent, _on_transcription)
    event_bus.subscribe(SummaryUpdateEvent, _on_summary)
    event_bus.subscribe(SystemStatusEvent, _on_status)
    bridge.event_bus = event_bus
    # Bridge also subscribes eagerly (its start is sync-safe)
    event_bus.subscribe(TranscriptionEvent, bridge._on_transcription)
    event_bus.subscribe(SummaryUpdateEvent, bridge._on_summary)
    event_bus.subscribe(SystemStatusEvent, bridge._on_status)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("RPG Scribe Web UI started")
        yield
        # Cleanup: unsubscribe on shutdown
        event_bus.unsubscribe(TranscriptionEvent, _on_transcription)
        event_bus.unsubscribe(SummaryUpdateEvent, _on_summary)
        event_bus.unsubscribe(SystemStatusEvent, _on_status)
        event_bus.unsubscribe(TranscriptionEvent, bridge._on_transcription)
        event_bus.unsubscribe(SummaryUpdateEvent, bridge._on_summary)
        event_bus.unsubscribe(SystemStatusEvent, bridge._on_status)
        logger.info("RPG Scribe Web UI stopped")

    app = FastAPI(title="RPG Scribe", version="0.1.0", lifespan=lifespan)

    # Attach shared objects to the router so route handlers can access them.
    router.state = state  # type: ignore[attr-defined]
    router.ws_manager = manager  # type: ignore[attr-defined]
    router.database = database  # type: ignore[attr-defined]

    app.include_router(router)

    # Serve static files (HTML/JS/CSS) at the root path — mounted
    # last so API and WS routes take priority.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
