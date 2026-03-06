"""REST API routes for RPG Scribe web interface."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from rpg_scribe.core.events import (
    SessionEndRequestEvent,
    SummaryRefreshRequestEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge

logger = logging.getLogger(__name__)

router = APIRouter()


class WebState:
    """Shared mutable state for the web layer.

    Holds the latest snapshots of transcriptions, summaries, component
    statuses and questions so REST endpoints can serve them without
    requiring a database.
    """

    def __init__(self, max_transcriptions: int = 5000) -> None:
        self.transcriptions: list[dict[str, Any]] = []
        self.max_transcriptions = max(1, max_transcriptions)
        self.session_summary: str = ""
        self.campaign_summary: str = ""
        self.last_summary_update: float = 0.0
        self.component_status: dict[str, dict[str, Any]] = {}
        self.questions: list[dict[str, Any]] = []
        self.active_session_id: str | None = None
        self.active_campaign: dict[str, Any] | None = None

    def add_transcription(self, data: dict[str, Any]) -> None:
        self.transcriptions.append(data)
        overflow = len(self.transcriptions) - self.max_transcriptions
        if overflow > 0:
            del self.transcriptions[:overflow]

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


def _get_config():
    """Access the optional AppConfig attached to the router."""
    return getattr(router, "config", None)


def _get_event_bus():
    """Access the optional EventBus attached to the router."""
    return getattr(router, "event_bus", None)


# â”€â”€ REST endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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

@router.get("/api/sessions/{session_id}/transcriptions")
async def get_transcriptions(session_id: str) -> dict[str, Any]:
    """Return transcriptions for a session.

    For the active live session (or when no DB is available), returns
    in-memory data.  For historical sessions, queries the database.
    """
    state = _get_state()

    # Check in-memory first
    filtered = [
        t for t in state.transcriptions if t.get("session_id") == session_id
    ]

    # Return in-memory data if we found results, or if this is the live session
    if filtered or session_id == state.active_session_id:
        return {"session_id": session_id, "transcriptions": filtered}

    # Fall back to database for historical data
    db = _get_database()
    if db is not None:
        try:
            rows = await db.get_transcriptions(session_id)
            return {"session_id": session_id, "transcriptions": rows}
        except Exception as exc:
            logger.error("Error fetching transcriptions from DB: %s", exc)

    return {"session_id": session_id, "transcriptions": filtered}


@router.get("/api/sessions/{session_id}/transcriptions/full")
async def get_full_transcriptions(session_id: str) -> dict[str, Any]:
    """Return full stored transcriptions for a session (DB-first)."""
    db = _get_database()
    state = _get_state()

    if db is not None:
        try:
            rows = await db.get_transcriptions(session_id)
            return {"session_id": session_id, "transcriptions": rows}
        except Exception as exc:
            logger.error("Error fetching full transcriptions from DB: %s", exc)

    # Fallback when no DB is available: return in-memory snapshot for this session.
    filtered = [
        t for t in state.transcriptions if t.get("session_id") == session_id
    ]
    return {"session_id": session_id, "transcriptions": filtered}

@router.get("/api/sessions/{session_id}/summary")
async def get_summary(session_id: str) -> dict[str, Any]:
    """Return current summary for a session.

    For the active live session (or when no DB is available), returns
    in-memory data.  For historical sessions, queries the database.
    """
    state = _get_state()

    # Return in-memory data only for the live session. Historical
    # sessions should come from DB when available.
    if session_id == state.active_session_id:
        return {
            "session_id": session_id,
            "session_summary": state.session_summary,
            "campaign_summary": state.campaign_summary,
            "last_updated": state.last_summary_update,
        }

    # Fall back to database for historical data
    db = _get_database()
    if db is not None:
        try:
            session = await db.get_session(session_id)
            if session:
                campaign_summary = ""
                campaign_id = session.get("campaign_id", "")
                if campaign_id:
                    campaign = await db.get_campaign(campaign_id)
                    if campaign:
                        campaign_summary = campaign.get("campaign_summary", "")
                return {
                    "session_id": session_id,
                    "session_summary": session.get("session_summary", ""),
                    "campaign_summary": campaign_summary,
                    "last_updated": session.get("ended_at", 0),
                }
        except Exception as exc:
            logger.error("Error fetching summary from DB: %s", exc)

    # If there is no DB wired (e.g. isolated tests), return in-memory snapshot.
    if db is None:
        return {
            "session_id": session_id,
            "session_summary": state.session_summary,
            "campaign_summary": state.campaign_summary,
            "last_updated": state.last_summary_update,
        }

    return {
        "session_id": session_id,
        "session_summary": "",
        "campaign_summary": "",
        "last_updated": 0,
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

@router.get("/api/campaigns")
async def get_campaigns() -> dict[str, Any]:
    """Return active campaign info including players and NPCs.

    Tries in-memory state first, then falls back to the database.
    """
    state = _get_state()
    db = _get_database()
    config = _get_config()

    campaign = state.active_campaign

    # Fall back to DB if campaign is not in memory
    if not campaign and config and hasattr(config, "campaign") and config.campaign and db:
        try:
            row = await db.get_campaign(config.campaign.campaign_id)
            if row:
                campaign = {
                    "id": row.get("id", ""),
                    "name": row.get("name", ""),
                    "game_system": row.get("game_system", ""),
                    "language": row.get("language", "es"),
                    "description": row.get("description", ""),
                    "custom_instructions": row.get("custom_instructions", ""),
                    "is_generic": False,
                }
                state.active_campaign = campaign
        except Exception as exc:
            logger.error("Error fetching campaign from DB: %s", exc)

    if not campaign:
        return {"campaign": None}

    # Attach players and NPCs from DB
    campaign_id = campaign.get("id", "")
    if db and campaign_id and not campaign.get("is_generic"):
        try:
            campaign["players"] = await db.get_players(campaign_id)
        except Exception as exc:
            logger.error("Error fetching players: %s", exc)
            campaign.setdefault("players", [])
        try:
            campaign["npcs"] = await db.get_npcs(campaign_id)
        except Exception as exc:
            logger.error("Error fetching NPCs: %s", exc)
            campaign.setdefault("npcs", [])
    else:
        campaign.setdefault("players", [])
        campaign.setdefault("npcs", [])

    return {"campaign": campaign}


@router.patch("/api/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update editable fields of a campaign.

    Accepts a JSON body with any of: name, game_system, description,
    language, custom_instructions.  Updates both the database and
    the in-memory state so changes are reflected immediately.
    """
    state = _get_state()
    db = _get_database()
    config = _get_config()

    # Validate that we have a campaign to update
    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    # Fields that can be edited from the UI
    editable = {"name", "game_system", "description", "language", "custom_instructions"}
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}

    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    # Update in-memory WebState
    for k, v in updates.items():
        state.active_campaign[k] = v

    # Update in-memory config.campaign (CampaignContext dataclass)
    if config and hasattr(config, "campaign") and config.campaign:
        campaign_obj = config.campaign
        field_map = {"name": "name", "game_system": "game_system",
                     "description": "description", "language": "language",
                     "custom_instructions": "custom_instructions"}
        for k, v in updates.items():
            attr = field_map.get(k, k)
            if hasattr(campaign_obj, attr):
                object.__setattr__(campaign_obj, attr, v)

    # Persist to database
    if db is not None:
        try:
            current = await db.get_campaign(campaign_id)
            if current:
                await db.upsert_campaign(
                    campaign_id=campaign_id,
                    name=updates.get("name", current.get("name", "")),
                    game_system=updates.get("game_system", current.get("game_system", "")),
                    language=updates.get("language", current.get("language", "es")),
                    description=updates.get("description", current.get("description", "")),
                    campaign_summary=current.get("campaign_summary", ""),
                    speaker_map=current.get("speaker_map"),
                    dm_speaker_id=current.get("dm_speaker_id", ""),
                    custom_instructions=updates.get(
                        "custom_instructions",
                        current.get("custom_instructions", ""),
                    ),
                )
        except Exception as exc:
            logger.error("Error persisting campaign update: %s", exc)
            return {"ok": False, "error": "Failed to save to database"}

    logger.info("Campaign %s updated: %s", campaign_id, list(updates.keys()))
    return {"ok": True, "campaign": state.active_campaign}


# â”€â”€ Player endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.put("/api/campaigns/{campaign_id}/players/{player_id}")
async def update_player(
    campaign_id: str, player_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Update a player's editable fields.

    Accepts: discord_name, character_name, character_description.
    If character_name changes, also updates speaker_map.
    """
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    editable = {"discord_name", "character_name", "character_description"}
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}
    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    # Persist to database
    if db is not None:
        try:
            await db.update_player(player_id, **updates)
        except Exception as exc:
            logger.error("Error updating player: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    # Update in-memory config (CampaignContext.players and speaker_map)
    if config and hasattr(config, "campaign") and config.campaign:
        campaign_obj = config.campaign
        discord_id = body.get("discord_id", "")
        for p in campaign_obj.players:
            if p.discord_id == discord_id:
                for k, v in updates.items():
                    object.__setattr__(p, k, v)
                # Update speaker_map if character_name changed
                if "character_name" in updates and p.discord_id in campaign_obj.speaker_map:
                    campaign_obj.speaker_map[p.discord_id] = updates["character_name"]
                break

        # Persist updated speaker_map to DB
        if db is not None and "character_name" in updates:
            try:
                current = await db.get_campaign(campaign_id)
                if current:
                    await db.upsert_campaign(
                        campaign_id=campaign_id,
                        name=current["name"],
                        game_system=current.get("game_system", ""),
                        language=current.get("language", "es"),
                        description=current.get("description", ""),
                        campaign_summary=current.get("campaign_summary", ""),
                        speaker_map=campaign_obj.speaker_map,
                        dm_speaker_id=current.get("dm_speaker_id", ""),
                        custom_instructions=current.get("custom_instructions", ""),
                    )
            except Exception as exc:
                logger.error("Error persisting speaker_map: %s", exc)

    logger.info("Player %s updated: %s", player_id, list(updates.keys()))
    return {"ok": True}


# â”€â”€ NPC endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/api/campaigns/{campaign_id}/npcs")
async def create_npc(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Create a new NPC."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    if not name:
        return {"ok": False, "error": "NPC name is required"}

    # Save to DB
    if db is not None:
        try:
            if await db.npc_exists(campaign_id, name):
                return {"ok": False, "error": "NPC already exists"}
            await db.save_npc(campaign_id, name, description)
        except Exception as exc:
            logger.error("Error saving NPC: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    # Update in-memory config
    if config and hasattr(config, "campaign") and config.campaign:
        from rpg_scribe.core.models import NPCInfo

        config.campaign.known_npcs.append(NPCInfo(name=name, description=description))

    logger.info("NPC '%s' created in campaign %s", name, campaign_id)
    return {"ok": True}


@router.put("/api/campaigns/{campaign_id}/npcs/{npc_id}")
async def update_npc_endpoint(
    campaign_id: str, npc_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Update an NPC's editable fields (name, description)."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    editable = {"name", "description"}
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}
    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    if db is not None:
        try:
            await db.update_npc(npc_id, **updates)
        except Exception as exc:
            logger.error("Error updating NPC: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    # Update in-memory config
    if config and hasattr(config, "campaign") and config.campaign:
        old_name = body.get("old_name", "")
        for npc in config.campaign.known_npcs:
            if npc.name == old_name:
                for k, v in updates.items():
                    object.__setattr__(npc, k, v)
                break

    logger.info("NPC %s updated: %s", npc_id, list(updates.keys()))
    return {"ok": True}


_SUMMARY_PREVIEW_LEN = 150


@router.get("/api/sessions")
async def list_all_sessions() -> dict[str, Any]:
    """Return all sessions across campaigns, ordered by date descending."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.list_all_sessions()
    except Exception as exc:
        logger.error("Error listing all sessions: %s", exc)
        return {"sessions": []}
    return {"sessions": _format_session_list(sessions)}


@router.get("/api/campaigns/{campaign_id}/sessions")
async def list_campaign_sessions(campaign_id: str) -> dict[str, Any]:
    """Return all sessions for a campaign, ordered by date descending."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.list_sessions(campaign_id)
    except Exception as exc:
        logger.error("Error listing campaign sessions: %s", exc)
        return {"sessions": []}
    return {"sessions": _format_session_list(sessions)}


def _format_session_list(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format session rows into a list suitable for the API response."""
    result = []
    for s in sessions:
        summary = s.get("session_summary") or ""
        preview = summary[:_SUMMARY_PREVIEW_LEN]
        if len(summary) > _SUMMARY_PREVIEW_LEN:
            preview += "..."

        # Compute duration in minutes if both timestamps are numeric
        started = s.get("started_at")
        ended = s.get("ended_at")
        duration_minutes = None
        if started and ended:
            try:
                duration_minutes = round((float(ended) - float(started)) / 60, 1)
            except (TypeError, ValueError):
                duration_minutes = None

        result.append({
            "id": s["id"],
            "campaign_id": s.get("campaign_id", ""),
            "started_at": started,
            "ended_at": ended,
            "duration_minutes": duration_minutes,
            "status": s.get("status", ""),
            "summary_preview": preview,
            "has_summary": bool(summary),
        })
    return result


# â”€â”€ Session finalize endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/api/sessions/{session_id}/finalize")
async def finalize_session(session_id: str) -> dict[str, Any]:
    """Trigger finalization of the active session from the web UI.

    Publishes a ``SessionEndRequestEvent`` which the Application handles
    in the background.
    """
    state = _get_state()
    event_bus = _get_event_bus()

    if event_bus is None:
        return {"ok": False, "error": "Event bus not available"}

    if state.active_session_id is None:
        return {"ok": False, "error": "No active session"}

    if state.active_session_id != session_id:
        return {"ok": False, "error": "Session ID does not match active session"}

    await event_bus.publish(
        SessionEndRequestEvent(session_id=session_id, source="web")
    )
    state.active_session_id = None
    return {"ok": True, "status": "finalizing"}


# â”€â”€ WebSocket endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€



@router.post("/api/sessions/{session_id}/refresh-summary")
async def refresh_summary(session_id: str) -> dict[str, Any]:
    """Trigger an on-demand summary refresh for the active session."""
    state = _get_state()
    event_bus = _get_event_bus()

    if event_bus is None:
        return {"ok": False, "error": "Event bus not available"}

    if state.active_session_id is None:
        return {"ok": False, "error": "No active session"}

    if state.active_session_id != session_id:
        return {"ok": False, "error": "Session ID does not match active session"}

    await event_bus.publish(
        SummaryRefreshRequestEvent(session_id=session_id, source="web")
    )
    return {"ok": True, "status": "refresh_requested"}

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






