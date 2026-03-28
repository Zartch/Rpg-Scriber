"""REST API routes for RPG Scribe web interface.

This module defines the central ``router`` object whose attributes hold all
shared state (WebState, database, config, event bus, etc.).  The actual
endpoint handlers live in domain-specific sub-routers under
``rpg_scribe/web/routers/``.
"""

from __future__ import annotations

from fastapi import APIRouter

from rpg_scribe.web.state import WebState
from rpg_scribe.web.websocket import ConnectionManager

router = APIRouter()


def _get_state() -> WebState:
    """Access the global state attached to the router."""
    return router.state  # type: ignore[attr-defined]


def _get_manager() -> ConnectionManager:
    return router.ws_manager  # type: ignore[attr-defined]


def _get_database():
    """Access the optional database attached to the router."""
    return getattr(router, "database", None)


def _get_config():
    """Access the optional AppConfig attached to the router."""
    return getattr(router, "config", None)


def _get_event_bus():
    """Access the optional EventBus attached to the router."""
    return getattr(router, "event_bus", None)


def _get_application():
    """Access the optional Application attached to the router."""
    return getattr(router, "application", None)
