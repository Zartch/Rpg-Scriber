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
    SessionEndRequestEvent,
    SessionStartRequestEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.web.routes import WebState, router
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    event_bus: EventBus,
    database: object | None = None,
    config: object | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    The app subscribes to the event bus so that incoming events are
    both stored in ``WebState`` (for REST queries) and broadcast to
    all connected WebSocket clients via ``WebSocketBridge``.
    """
    max_transcriptions = max(1, int(getattr(config, "web_transcriptions_max_items", 5000)))
    state = WebState(max_transcriptions=max_transcriptions)
    manager = ConnectionManager()
    bridge = WebSocketBridge(event_bus, manager)

    # ── Event handlers that keep WebState in sync ────────────────

    async def _on_transcription(event: TranscriptionEvent) -> None:
        state.add_transcription(asdict(event))

    async def _on_summary(event: SummaryUpdateEvent) -> None:
        state.update_summary(asdict(event))

    async def _on_status(event: SystemStatusEvent) -> None:
        state.update_component_status(asdict(event))

    async def _on_session_start(event: SessionStartRequestEvent) -> None:
        state.active_session_id = event.session_id

    async def _on_session_end(event: SessionEndRequestEvent) -> None:
        # Session ID cleared after finalization completes; for now mark as
        # "finalizing" so the UI can show progress. The actual clearing
        # happens when a SummaryUpdateEvent with update_type="final" arrives.
        pass

    # Subscribe eagerly � EventBus.subscribe is synchronous and the
    # handlers are valid as soon as the app object exists.
    event_bus.subscribe(TranscriptionEvent, _on_transcription)
    event_bus.subscribe(SummaryUpdateEvent, _on_summary)
    event_bus.subscribe(SystemStatusEvent, _on_status)
    event_bus.subscribe(SessionStartRequestEvent, _on_session_start)
    event_bus.subscribe(SessionEndRequestEvent, _on_session_end)
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
        event_bus.unsubscribe(SessionStartRequestEvent, _on_session_start)
        event_bus.unsubscribe(SessionEndRequestEvent, _on_session_end)
        logger.info("RPG Scribe Web UI stopped")

    app = FastAPI(title="RPG Scribe", version="0.1.0", lifespan=lifespan)

    # Attach shared objects to the router so route handlers can access them.
    router.state = state  # type: ignore[attr-defined]
    router.ws_manager = manager  # type: ignore[attr-defined]
    router.database = database  # type: ignore[attr-defined]
    router.config = config  # type: ignore[attr-defined]
    router.event_bus = event_bus  # type: ignore[attr-defined]

    # Populate campaign info in WebState from config
    if config and hasattr(config, "campaign") and config.campaign:
        state.active_campaign = {
            "id": config.campaign.campaign_id,
            "name": config.campaign.name,
            "game_system": config.campaign.game_system,
            "language": config.campaign.language,
            "description": config.campaign.description,
            "custom_instructions": config.campaign.custom_instructions,
            "dm_speaker_id": config.campaign.dm_speaker_id,
            "relationship_types": [asdict(rt) for rt in getattr(config.campaign, "relation_types", [])],
            "relationships": [asdict(rel) for rel in getattr(config.campaign, "relationships", [])],
            "locations": [asdict(loc) for loc in getattr(config.campaign, "locations", [])],
            "is_generic": getattr(config.campaign, "is_generic", False),
        }

    app.include_router(router)

    # Serve static files (HTML/JS/CSS) at the root path � mounted
    # last so API and WS routes take priority.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app

