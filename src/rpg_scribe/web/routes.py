"""REST API routes for RPG Scribe web interface."""

from __future__ import annotations

import html
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from rpg_scribe.core.events import (
    SessionEndRequestEvent,
    SummaryRefreshRequestEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.core.models import CharacterRelationshipInfo, LocationInfo, RelationshipTypeInfo
from rpg_scribe.config import save_campaign_toml
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


def _persist_campaign_toml(config: Any) -> None:
    """Persist in-memory campaign config back to its TOML file if configured."""
    if not config or not getattr(config, "campaign", None):
        return
    campaign_path = getattr(config, "campaign_path", "")
    if not campaign_path:
        return
    save_campaign_toml(config.campaign, campaign_path)



def _logs_root() -> Path:
    """Return the base logs directory."""
    return Path("logs").resolve()


def _session_logs_dir(session_id: str) -> Path:
    """Return the logs directory for a session."""
    return (_logs_root() / session_id).resolve()


def _flatten_campaign_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a DB campaign row for API responses."""
    return {
        "id": row.get("id", ""),
        "name": row.get("name", ""),
        "game_system": row.get("game_system", ""),
        "language": row.get("language", "es"),
        "description": row.get("description", ""),
        "campaign_summary": row.get("campaign_summary", ""),
        "dm_speaker_id": row.get("dm_speaker_id", ""),
        "custom_instructions": row.get("custom_instructions", ""),
        "created_at": row.get("created_at", 0),
        "updated_at": row.get("updated_at", 0),
    }


def _extract_location_name(value: Any) -> str:
    """Extract location name from str/dict/dataclass-like value."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    if hasattr(value, "name"):
        return str(getattr(value, "name", "")).strip()
    return ""


def _extract_location_description(value: Any) -> str:
    """Extract location description from dict/dataclass-like value."""
    if isinstance(value, dict):
        return str(value.get("description", "")).strip()
    if hasattr(value, "description"):
        return str(getattr(value, "description", "")).strip()
    return ""


def _normalize_locations(values: list[Any] | None) -> list[dict[str, str]]:
    """Normalize locations into a list of {name, description} objects."""
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values or []:
        name = _extract_location_name(raw)
        if not name:
            continue
        folded = name.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append({
            "name": name,
            "description": _extract_location_description(raw),
        })
    return normalized
# -- REST endpoints ------------------------------------------------



async def _sync_relationships_to_config(config: Any, db: Any, campaign_id: str) -> None:
    """Refresh relationship thesaurus + relations from DB into config.campaign."""
    if not config or not getattr(config, "campaign", None) or db is None:
        return
    if config.campaign.campaign_id != campaign_id:
        return

    types = await db.get_relationship_types(campaign_id)
    rels = await db.get_character_relationships(campaign_id)

    config.campaign.relation_types = [
        RelationshipTypeInfo(
            key=str(t.get("canonical_key", "")),
            label=str(t.get("label", "")),
            category=str(t.get("category", "general") or "general"),
        )
        for t in types
        if t.get("canonical_key")
    ]

    config.campaign.relationships = [
        CharacterRelationshipInfo(
            source_key=str(r.get("source_key", "")),
            target_key=str(r.get("target_key", "")),
            relation_type_key=str(r.get("type_key", "")),
            relation_type_label=str(r.get("type_label", "")),
            notes=str(r.get("notes", "") or ""),
        )
        for r in rels
        if r.get("source_key") and r.get("target_key") and r.get("type_key")
    ]

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
    """Return active campaign info including players, NPCs and relationships."""
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
                    "dm_speaker_id": row.get("dm_speaker_id", ""),
                    "is_generic": False,
                }
                state.active_campaign = campaign
        except Exception as exc:
            logger.error("Error fetching campaign from DB: %s", exc)

    if not campaign:
        return {"campaign": None}

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
        try:
            campaign["relationship_types"] = await db.get_relationship_types(campaign_id)
        except Exception as exc:
            logger.error("Error fetching relationship types: %s", exc)
            campaign.setdefault("relationship_types", [])
        try:
            campaign["relationships"] = await db.get_character_relationships(campaign_id)
        except Exception as exc:
            logger.error("Error fetching relationships: %s", exc)
            campaign.setdefault("relationships", [])
    else:
        campaign.setdefault("players", [])
        campaign.setdefault("npcs", [])
        campaign.setdefault("relationship_types", [])
        campaign.setdefault("relationships", [])
        campaign.setdefault("locations", [])

    campaign.setdefault("locations", [])

    campaign.setdefault("dm_speaker_id", "")
    return {"campaign": campaign}


@router.get("/api/browse/campaigns")
async def list_browse_campaigns() -> dict[str, Any]:
    """Return all campaigns for Browse mode."""
    state = _get_state()
    db = _get_database()
    active_campaign_id = ""
    if state.active_campaign:
        active_campaign_id = str(state.active_campaign.get("id", ""))

    campaigns: list[dict[str, Any]] = []
    if db is not None:
        try:
            rows = await db.list_campaigns()
            campaigns = [_flatten_campaign_row(r) for r in rows]
        except Exception as exc:
            logger.error("Error listing campaigns for browse: %s", exc)

    if not campaigns and state.active_campaign:
        fallback = dict(state.active_campaign)
        fallback.setdefault("campaign_summary", "")
        campaigns = [_flatten_campaign_row(fallback)]

    for c in campaigns:
        c["is_active"] = c.get("id") == active_campaign_id

    return {"campaigns": campaigns, "active_campaign_id": active_campaign_id or None}


@router.get("/api/browse/campaigns/{campaign_id}")
async def get_browse_campaign(campaign_id: str) -> dict[str, Any]:
    """Return a campaign with entities for Browse mode (read-only)."""
    state = _get_state()
    db = _get_database()

    campaign: dict[str, Any] | None = None
    if db is not None:
        try:
            row = await db.get_campaign(campaign_id)
            if row:
                campaign = _flatten_campaign_row(row)
                campaign["players"] = await db.get_players(campaign_id)
                campaign["npcs"] = await db.get_npcs(campaign_id)
                campaign["relationship_types"] = await db.get_relationship_types(campaign_id)
                campaign["relationships"] = await db.get_character_relationships(campaign_id)
                campaign.setdefault("locations", [])
        except Exception as exc:
            logger.error("Error loading browse campaign %s: %s", campaign_id, exc)
            return {"campaign": None}

    if campaign is None and state.active_campaign and state.active_campaign.get("id") == campaign_id:
        campaign = dict(state.active_campaign)
        campaign.setdefault("campaign_summary", "")
        campaign.setdefault("players", [])
        campaign.setdefault("npcs", [])
        campaign.setdefault("relationship_types", [])
        campaign.setdefault("relationships", [])

        campaign.setdefault("locations", [])
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
    editable = {"name", "game_system", "description", "language", "custom_instructions", "dm_speaker_id"}
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
                     "custom_instructions": "custom_instructions", "dm_speaker_id": "dm_speaker_id"}
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
                    dm_speaker_id=updates.get("dm_speaker_id", current.get("dm_speaker_id", "")),
                    custom_instructions=updates.get(
                        "custom_instructions",
                        current.get("custom_instructions", ""),
                    ),
                )
        except Exception as exc:
            logger.error("Error persisting campaign update: %s", exc)
            return {"ok": False, "error": "Failed to save to database"}

    logger.info("Campaign %s updated: %s", campaign_id, list(updates.keys()))
    try:
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)
    return {"ok": True, "campaign": state.active_campaign}


# -- Player endpoints ----------------------------------------------


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
    try:
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)
    return {"ok": True}


# -- NPC endpoints -------------------------------------------------


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
    try:
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)
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

    old_name = str(body.get("old_name", "")).strip()

    if db is not None:
        try:
            await db.update_npc(npc_id, **updates)
            new_name = str(updates.get("name", old_name)).strip()
            if old_name and new_name and old_name != new_name:
                await db.rename_relationship_entity_key(
                    campaign_id,
                    f"npc:{old_name}",
                    f"npc:{new_name}",
                )
        except Exception as exc:
            logger.error("Error updating NPC: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    # Update in-memory config
    if config and hasattr(config, "campaign") and config.campaign:
        for npc in config.campaign.known_npcs:
            if npc.name == old_name:
                for k, v in updates.items():
                    object.__setattr__(npc, k, v)
                break

    logger.info("NPC %s updated: %s", npc_id, list(updates.keys()))
    try:
        if db is not None:
            await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)
    return {"ok": True}




@router.post("/api/campaigns/{campaign_id}/locations")
async def create_location_endpoint(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Add a location name to the active campaign context."""
    state = _get_state()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    name = str(body.get("name", "")).strip()
    if not name:
        return {"ok": False, "error": "Location name is required"}

    current = _normalize_locations(state.active_campaign.get("locations", []))
    existing_keys = {loc["name"].casefold() for loc in current}
    if name.casefold() in existing_keys:
        return {"ok": False, "error": "Location already exists"}

    current.append({"name": name, "description": ""})
    state.active_campaign["locations"] = current

    if config and hasattr(config, "campaign") and config.campaign:
        config.campaign.locations = [
            LocationInfo(name=loc["name"], description=loc.get("description", ""))
            for loc in current
        ]

    try:
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)

    return {"ok": True, "locations": current}

@router.put("/api/campaigns/{campaign_id}/locations")
async def update_location_endpoint(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Rename a location in the active campaign context."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}

    old_name = str(body.get("old_name", "")).strip()
    new_name = str(body.get("name", "")).strip()
    if not old_name or not new_name:
        return {"ok": False, "error": "old_name and name are required"}

    locations = _normalize_locations(state.active_campaign.get("locations", []))
    location_names = [loc["name"] for loc in locations]
    if old_name not in location_names:
        return {"ok": False, "error": "Location not found"}

    for loc in location_names:
        if loc.casefold() == new_name.casefold() and loc != old_name:
            return {"ok": False, "error": "Location already exists"}

    updated_locations = [
        {
            "name": new_name if loc["name"] == old_name else loc["name"],
            "description": loc.get("description", ""),
        }
        for loc in locations
    ]
    state.active_campaign["locations"] = updated_locations

    # Keep in-memory relationship keys aligned when a location is renamed.
    for rel in state.active_campaign.get("relationships", []) or []:
        source_key = str(rel.get("source_key", ""))
        target_key = str(rel.get("target_key", ""))
        if source_key in {f"loc:{old_name}", f"location:{old_name}"}:
            rel["source_key"] = f"loc:{new_name}"
        if target_key in {f"loc:{old_name}", f"location:{old_name}"}:
            rel["target_key"] = f"loc:{new_name}"

    if db is not None:
        try:
            await db.rename_relationship_entity_key(campaign_id, f"loc:{old_name}", f"loc:{new_name}")
            await db.rename_relationship_entity_key(campaign_id, f"location:{old_name}", f"loc:{new_name}")
        except Exception as exc:
            logger.error("Error renaming location relationship keys: %s", exc)
            return {"ok": False, "error": "Failed to update relationship links"}

    if config and hasattr(config, "campaign") and config.campaign:
        config.campaign.locations = [
            LocationInfo(name=loc["name"], description=loc.get("description", ""))
            for loc in updated_locations
        ]
        for rel in config.campaign.relationships:
            if rel.source_key in {f"loc:{old_name}", f"location:{old_name}"}:
                object.__setattr__(rel, "source_key", f"loc:{new_name}")
            if rel.target_key in {f"loc:{old_name}", f"location:{old_name}"}:
                object.__setattr__(rel, "target_key", f"loc:{new_name}")

    try:
        if db is not None:
            await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)

    return {"ok": True, "locations": updated_locations}
@router.get("/api/campaigns/{campaign_id}/relationships")
async def list_relationships(campaign_id: str) -> dict[str, Any]:
    """List relationship thesaurus + relationships for a campaign."""
    db = _get_database()
    if db is None:
        return {"relationship_types": [], "relationships": []}

    try:
        relationship_types = await db.get_relationship_types(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
    except Exception as exc:
        logger.error("Error listing relationships: %s", exc)
        return {"relationship_types": [], "relationships": []}

    return {
        "relationship_types": relationship_types,
        "relationships": relationships,
    }


@router.post("/api/campaigns/{campaign_id}/relationships")
async def create_relationship(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Create or update a typed relationship between two campaign entities."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not state.active_campaign or state.active_campaign.get("id") != campaign_id:
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_key = str(body.get("source_key", "")).strip()
    target_key = str(body.get("target_key", "")).strip()
    relation_type = str(body.get("relation_type", "")).strip()
    notes = str(body.get("notes", "")).strip()
    category = str(body.get("category", "general") or "general").strip()

    if not source_key or not target_key:
        return {"ok": False, "error": "source_key and target_key are required"}
    if source_key == target_key:
        return {"ok": False, "error": "Source and target cannot be the same"}
    if not relation_type:
        return {"ok": False, "error": "relation_type is required"}

    try:
        relationship = await db.save_character_relationship(
            campaign_id,
            source_key,
            target_key,
            relation_type,
            notes=notes,
            category=category,
        )
        relationship_types = await db.get_relationship_types(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error saving relationship: %s", exc)
        return {"ok": False, "error": "Failed to save relationship"}

    state.active_campaign["relationship_types"] = relationship_types
    state.active_campaign["relationships"] = relationships

    try:
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting relationship TOML sync: %s", exc)

    return {
        "ok": True,
        "relationship": relationship,
        "relationship_types": relationship_types,
        "relationships": relationships,
    }

_SUMMARY_PREVIEW_LEN = 150

# ── Campaign summary history endpoints ────────────────────────────

_CAMPAIGN_SUMMARY_PREVIEW_LEN = 200


@router.post("/api/campaigns/{campaign_id}/campaign-summaries/generate")
async def generate_campaign_summary_on_demand(campaign_id: str) -> dict[str, Any]:
    """Generate a campaign summary on demand.

    Before generating the campaign summary, also generates and persists
    session summaries for any completed sessions that are missing one.
    """
    db = _get_database()
    config = _get_config()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    if config is None or not getattr(config, "campaign", None):
        raise HTTPException(status_code=503, detail="Campaign config not available")

    campaign = config.campaign
    if campaign.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Campaign not found")

    from rpg_scribe.summarizers.claude_summarizer import ClaudeSummarizer

    summarizer = ClaudeSummarizer(
        _get_event_bus(),
        config.summarizer,
        campaign,
        database=db,
    )

    # Step 1: Generate missing session summaries
    all_sessions = await db.list_sessions(campaign_id)
    missing = [
        s for s in all_sessions
        if s.get("status") == "completed" and not (s.get("session_summary") or "").strip()
    ]
    sessions_processed = 0
    for session in missing:
        session_id = session["id"]
        try:
            rows = await db.get_transcriptions(session_id)
            if not rows:
                continue
            summary = await summarizer.generate_session_summary_from_transcriptions(rows)
            if summary:
                await db.end_session(session_id, summary)
                sessions_processed += 1
                logger.info("Generated missing summary for session %s", session_id)
        except Exception as exc:
            logger.error("Failed to generate summary for session %s: %s", session_id, exc)

    # Step 2: Generate campaign summary from all sessions that now have one
    all_sessions = await db.list_sessions(campaign_id)
    completed = sorted(
        [s for s in all_sessions if (s.get("session_summary") or "").strip() and s.get("status") == "completed"],
        key=lambda s: s.get("started_at") or 0,
    )
    if not completed:
        raise HTTPException(status_code=422, detail="No completed sessions with summaries found")

    try:
        campaign_summary = await summarizer.generate_campaign_summary(
            completed, trigger_session_id=""
        )
    except Exception as exc:
        logger.error("Failed to generate campaign summary on demand: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if campaign_summary:
        await db.save_campaign_summary(
            campaign_id=campaign_id,
            content=campaign_summary,
            trigger_session_id="",
            session_count=len(completed),
        )
        campaign.campaign_summary = campaign_summary
        _persist_campaign_toml(config)

    return {
        "status": "ok",
        "sessions_processed": sessions_processed,
        "session_count": len(completed),
        "campaign_summary": campaign_summary,
    }


@router.get("/api/campaigns/{campaign_id}/campaign-summaries")
async def list_campaign_summaries(campaign_id: str) -> dict[str, Any]:
    """Return all campaign summaries for a campaign, newest first."""
    db = _get_database()
    if db is None:
        return {"campaign_summaries": []}
    try:
        rows = await db.list_campaign_summaries(campaign_id)
    except Exception as exc:
        logger.error("Error listing campaign summaries: %s", exc)
        return {"campaign_summaries": []}

    result = []
    for r in rows:
        content = r.get("content", "")
        preview = content[:_CAMPAIGN_SUMMARY_PREVIEW_LEN]
        if len(content) > _CAMPAIGN_SUMMARY_PREVIEW_LEN:
            preview += "..."
        result.append({
            "id": r["id"],
            "campaign_id": r.get("campaign_id", ""),
            "generated_at": r.get("generated_at"),
            "trigger_session_id": r.get("trigger_session_id", ""),
            "session_count": r.get("session_count", 0),
            "preview": preview,
        })
    return {"campaign_summaries": result}


@router.get("/api/campaigns/{campaign_id}/campaign-summaries/latest")
async def get_latest_campaign_summary(campaign_id: str) -> dict[str, Any]:
    """Return the most recently generated campaign summary."""
    db = _get_database()
    if db is None:
        return {"campaign_summary": None}
    try:
        row = await db.get_latest_campaign_summary(campaign_id)
    except Exception as exc:
        logger.error("Error fetching latest campaign summary: %s", exc)
        return {"campaign_summary": None}
    return {"campaign_summary": dict(row) if row else None}


@router.get("/api/campaigns/{campaign_id}/campaign-summaries/{summary_id}")
async def get_campaign_summary(campaign_id: str, summary_id: str) -> dict[str, Any]:
    """Return a specific campaign summary by ID."""
    db = _get_database()
    if db is None:
        return {"campaign_summary": None}
    try:
        row = await db.get_campaign_summary_by_id(summary_id)
    except Exception as exc:
        logger.error("Error fetching campaign summary %s: %s", summary_id, exc)
        return {"campaign_summary": None}
    if row and row.get("campaign_id") != campaign_id:
        return {"campaign_summary": None}
    return {"campaign_summary": dict(row) if row else None}


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



@router.get("/api/browse/sessions/uncategorized")
async def list_uncategorized_sessions() -> dict[str, Any]:
    """Return sessions not linked to any campaign."""
    db = _get_database()
    if db is None:
        return {"sessions": []}
    try:
        sessions = await db.list_uncategorized_sessions()
    except Exception as exc:
        logger.error("Error listing uncategorized sessions: %s", exc)
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



@router.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: str) -> dict[str, Any]:
    """Return log artifacts available for a session."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        return {
            "session_id": session_id,
            "exists": False,
            "explorer_url": None,
            "files": [],
        }

    files: list[dict[str, Any]] = []
    for path in sorted(session_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(session_dir).as_posix()
        files.append({
            "name": rel,
            "size": path.stat().st_size,
            "url": f"/api/sessions/{session_id}/logs/file/{quote(rel)}",
        })

    return {
        "session_id": session_id,
        "exists": True,
        "explorer_url": f"/api/sessions/{session_id}/logs/explorer",
        "files": files,
    }


@router.get("/api/sessions/{session_id}/logs/file/{file_path:path}")
async def get_session_log_file(session_id: str, file_path: str) -> FileResponse:
    """Serve one log artifact file for a session."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Session logs not found")

    target = (session_dir / file_path).resolve()
    if session_dir not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(path=target, filename=target.name)


@router.get("/api/sessions/{session_id}/logs/explorer")
async def get_session_logs_explorer(session_id: str) -> HTMLResponse:
    """Render a simple file explorer page for session logs."""
    session_dir = _session_logs_dir(session_id)
    if not session_dir.is_dir():
        return HTMLResponse(
            "<h1>Logs not found</h1><p>No log folder for this session.</p>",
            status_code=404,
        )

    items: list[str] = []
    for path in sorted(session_dir.rglob("*")):
        rel = path.relative_to(session_dir).as_posix()
        safe_rel = html.escape(rel)
        if path.is_dir():
            items.append(f"<li><strong>{safe_rel}/</strong></li>")
            continue
        file_url = f"/api/sessions/{session_id}/logs/file/{quote(rel)}"
        size = path.stat().st_size
        items.append(
            f"<li><a href=\"{file_url}\" target=\"_blank\" rel=\"noopener\">{safe_rel}</a> "
            f"<span>({size} bytes)</span></li>"
        )

    title = html.escape(f"Session {session_id} logs")
    body = "\n".join(items) if items else "<li>No files found.</li>"
    page = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\" />"
        f"<title>{title}</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;padding:1rem;}"
        "ul{line-height:1.6;}span{color:#666;}</style></head><body>"
        f"<h1>{title}</h1><p>Directory: {html.escape(str(session_dir))}</p>"
        f"<ul>{body}</ul></body></html>"
    )
    return HTMLResponse(page)

# -- Session finalize endpoint -------------------------------------


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


# -- WebSocket endpoint --------------------------------------------



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

