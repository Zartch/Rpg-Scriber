"""Status, WebSocket and questions endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from rpg_scribe.web.state import WebState
from rpg_scribe.web.websocket import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_state() -> WebState:
    from rpg_scribe.web import routes as _routes
    return _routes.router.state  # type: ignore[attr-defined]


def _get_manager() -> ConnectionManager:
    from rpg_scribe.web import routes as _routes
    return _routes.router.ws_manager  # type: ignore[attr-defined]


def _get_database():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "database", None)


def _get_config():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "config", None)


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return 204 No Content to suppress browser favicon 404."""
    from starlette.responses import Response

    return Response(status_code=204)


@router.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Return current component statuses."""
    state = _get_state()
    config = _get_config()
    return {
        "components": state.component_status,
        "active_session_id": state.active_session_id,
        "websocket_clients": _get_manager().active_count,
        "web_limits": {
            "transcriptions_buffer_max_items": state.max_transcriptions,
            "live_feed_max_items": getattr(config, "web_feed_max_items", 1000),
        },
    }


@router.get("/api/questions")
async def get_questions() -> dict[str, Any]:
    """Return pending questions from the summarizer."""
    state = _get_state()
    db = _get_database()

    if db is not None and state.active_session_id:
        try:
            pending = await db.get_pending_questions(state.active_session_id)
            return {"questions": pending}
        except Exception as exc:
            logger.error("Error fetching pending questions from DB: %s", exc)

    pending = [q for q in state.questions if q["status"] == "pending"]
    return {"questions": pending}


@router.post("/api/questions/{question_id}/answer")
async def answer_question(question_id: str, body: dict[str, str]) -> dict[str, Any]:
    """Answer a pending question from the summarizer."""
    state = _get_state()
    db = _get_database()
    answer_text = body.get("answer", "")
    if not answer_text:
        return {"ok": False, "error": "answer is required"}

    if db is not None:
        try:
            qid = int(question_id)
            await db.answer_question(qid, answer_text)
            return {"ok": True}
        except ValueError:
            return {"ok": False, "error": "invalid question id"}
        except Exception as exc:
            logger.error("Error answering question in DB: %s", exc)
            return {"ok": False, "error": "failed to save answer"}

    found = state.answer_question(question_id, answer_text)
    return {"ok": found}


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    """WebSocket endpoint for live event streaming."""
    manager = _get_manager()
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
