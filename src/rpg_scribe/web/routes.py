"""REST API routes for RPG Scribe web interface."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge

router = APIRouter()


class WebState:
    """Shared mutable state for the web layer.

    Holds the latest snapshots of transcriptions, summaries, component
    statuses and questions so REST endpoints can serve them without
    requiring a database.
    """

    def __init__(self) -> None:
        self.transcriptions: list[dict[str, Any]] = []
        self.session_summary: str = ""
        self.campaign_summary: str = ""
        self.last_summary_update: float = 0.0
        self.component_status: dict[str, dict[str, Any]] = {}
        self.questions: list[dict[str, Any]] = []
        self.active_session_id: str | None = None
        self.active_campaign: dict[str, Any] | None = None

    def add_transcription(self, data: dict[str, Any]) -> None:
        self.transcriptions.append(data)

    def update_summary(self, data: dict[str, Any]) -> None:
        self.session_summary = data.get("session_summary", "")
        self.campaign_summary = data.get("campaign_summary", "")
        self.last_summary_update = data.get("last_updated", time.time())

    def update_component_status(self, data: dict[str, Any]) -> None:
        component = data.get("component", "unknown")
        self.component_status[component] = data

    def add_question(self, question_id: str, text: str) -> None:
        self.questions.append({
            "id": question_id,
            "question": text,
            "answer": None,
            "status": "pending",
            "created_at": time.time(),
        })

    def answer_question(self, question_id: str, answer: str) -> bool:
        for q in self.questions:
            if q["id"] == question_id and q["status"] == "pending":
                q["answer"] = answer
                q["status"] = "answered"
                q["answered_at"] = time.time()
                return True
        return False


def _get_state() -> WebState:
    """Access the global state attached to the router."""
    return router.state  # type: ignore[attr-defined]


def _get_manager() -> ConnectionManager:
    return router.ws_manager  # type: ignore[attr-defined]


def _get_database():
    """Access the optional database attached to the router."""
    return getattr(router, "database", None)


# ── REST endpoints ────────────────────────────────────────────────


@router.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Return current component statuses."""
    state = _get_state()
    return {
        "components": state.component_status,
        "active_session_id": state.active_session_id,
        "websocket_clients": _get_manager().active_count,
    }


@router.get("/api/sessions/{session_id}/transcriptions")
async def get_transcriptions(session_id: str) -> dict[str, Any]:
    """Return transcriptions for a session."""
    state = _get_state()
    filtered = [
        t for t in state.transcriptions if t.get("session_id") == session_id
    ]
    return {"session_id": session_id, "transcriptions": filtered}


@router.get("/api/sessions/{session_id}/summary")
async def get_summary(session_id: str) -> dict[str, Any]:
    """Return current summary for a session."""
    state = _get_state()
    return {
        "session_id": session_id,
        "session_summary": state.session_summary,
        "campaign_summary": state.campaign_summary,
        "last_updated": state.last_summary_update,
    }


@router.get("/api/questions")
async def get_questions() -> dict[str, Any]:
    """Return pending questions from the summarizer."""
    state = _get_state()
    pending = [q for q in state.questions if q["status"] == "pending"]
    return {"questions": pending}


@router.post("/api/questions/{question_id}/answer")
async def answer_question(question_id: str, body: dict[str, str]) -> dict[str, Any]:
    """Answer a pending question from the summarizer."""
    state = _get_state()
    answer_text = body.get("answer", "")
    if not answer_text:
        return {"ok": False, "error": "answer is required"}
    found = state.answer_question(question_id, answer_text)
    return {"ok": found}


@router.get("/api/campaigns")
async def get_campaigns() -> dict[str, Any]:
    """Return active campaign info (if any)."""
    state = _get_state()
    return {"campaign": state.active_campaign}


_SUMMARY_PREVIEW_LEN = 150


@router.get("/api/campaigns/{campaign_id}/sessions")
async def list_campaign_sessions(campaign_id: str) -> dict[str, Any]:
    """Return all sessions for a campaign, ordered by date descending."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    sessions = await db.list_sessions(campaign_id)
    result = []
    for s in sessions:
        summary = s.get("session_summary") or ""
        preview = summary[:_SUMMARY_PREVIEW_LEN]
        if len(summary) > _SUMMARY_PREVIEW_LEN:
            preview += "..."
        result.append({
            "id": s["id"],
            "started_at": s.get("started_at"),
            "ended_at": s.get("ended_at"),
            "status": s.get("status", ""),
            "summary_preview": preview,
        })
    return {"sessions": result}


# ── WebSocket endpoint ────────────────────────────────────────────


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    """WebSocket endpoint for live event streaming."""
    manager = _get_manager()
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client may send pings or commands
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
