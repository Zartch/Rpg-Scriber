"""Campaign endpoints."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from rpg_scribe.services.campaign_export_service import (
    CampaignExportData,
    CampaignExportService,
    CampaignExportSessionData,
)
from rpg_scribe.web.state import WebState

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_state() -> WebState:
    from rpg_scribe.web import routes as _routes
    return _routes.router.state  # type: ignore[attr-defined]


def _get_database():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "database", None)


def _get_config():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "config", None)


def _get_event_bus():
    from rpg_scribe.web import routes as _routes
    return getattr(_routes.router, "event_bus", None)


def _exports_root() -> Path:
    """Return the base directory for immutable exports."""
    from rpg_scribe.web import routes as _routes
    return Path(
        getattr(_routes.router, "export_root", Path("exports").resolve())
    ).resolve()


def _get_campaign_export_service() -> CampaignExportService:
    """Create the campaign export service using the configured exports root."""
    return CampaignExportService(_exports_root())


def _persist_campaign_toml(config: Any) -> None:
    """Persist in-memory campaign config back to its TOML file if configured."""
    from rpg_scribe.config import save_campaign_toml
    if not config or not getattr(config, "campaign", None):
        return
    campaign_path = getattr(config, "campaign_path", "")
    if not campaign_path:
        return
    save_campaign_toml(config.campaign, campaign_path)


async def _validate_campaign(campaign_id: str) -> bool:
    """Check campaign exists and ensure it is loaded into state."""
    state = _get_state()
    if state.active_campaign and state.active_campaign.get("id") == campaign_id:
        return True
    db = _get_database()
    if db:
        try:
            row = await db.campaigns.get_campaign(campaign_id)
            if row:
                campaign: dict[str, Any] = {
                    "id": row.get("id", ""),
                    "name": row.get("name", ""),
                    "game_system": row.get("game_system", ""),
                    "language": row.get("language", "es"),
                    "description": row.get("description", ""),
                    "custom_instructions": row.get("custom_instructions", ""),
                    "dm_speaker_id": row.get("dm_speaker_id", ""),
                    "is_generic": False,
                }
                campaign["players"] = await db.entities.get_players(campaign_id)
                campaign["npcs"] = await db.entities.get_npcs(campaign_id)
                campaign["locations"] = await db.entities.get_locations(campaign_id)
                campaign["entities"] = await db.entities.get_entities(campaign_id)
                campaign["relationships"] = (
                    await db.entities.get_character_relationships(campaign_id)
                )
                campaign["relationship_types"] = (
                    await db.entities.get_relationship_types(campaign_id)
                )
                state.active_campaign = campaign
                return True
        except Exception:
            pass
    return False


async def _load_campaign_context_from_db(db, campaign_id: str):
    """Build a full CampaignContext from the database."""
    from rpg_scribe.core.models import (
        CampaignContext,
        CharacterRelationshipInfo,
        EntityInfo,
        LocationInfo,
        NPCInfo,
        PlayerInfo,
        RelationshipTypeInfo,
    )

    camp_row = await db.campaigns.get_campaign(campaign_id)
    if not camp_row:
        return None

    players_rows = await db.entities.get_players(campaign_id)
    npcs_rows = await db.entities.get_npcs(campaign_id)
    locations_rows = await db.entities.get_locations(campaign_id)
    entities_rows = await db.entities.get_entities(campaign_id)
    rel_types_rows = await db.entities.get_relationship_types(campaign_id)
    rels_rows = await db.entities.get_character_relationships(campaign_id)

    return CampaignContext(
        campaign_id=campaign_id,
        name=camp_row.get("name", ""),
        game_system=camp_row.get("game_system", ""),
        language=camp_row.get("language", "es"),
        description=camp_row.get("description", ""),
        custom_instructions=camp_row.get("custom_instructions", ""),
        campaign_summary=camp_row.get("campaign_summary", ""),
        dm_speaker_id=camp_row.get("dm_speaker_id", ""),
        speaker_map=camp_row.get("speaker_map") or {},
        players=[
            PlayerInfo(
                discord_id=p.get("discord_id", ""),
                discord_name=p.get("discord_name", ""),
                character_name=p.get("character_name", ""),
                character_description=p.get("character_description", ""),
            )
            for p in players_rows
        ],
        known_npcs=[
            NPCInfo(name=n.get("name", ""), description=n.get("description", ""))
            for n in npcs_rows
        ],
        locations=[
            LocationInfo(
                name=loc.get("name", ""), description=loc.get("description", "")
            )
            for loc in locations_rows
        ],
        entities=[
            EntityInfo(
                name=e.get("name", ""),
                entity_type=e.get("entity_type", "group"),
                description=e.get("description", ""),
            )
            for e in entities_rows
        ],
        relation_types=[
            RelationshipTypeInfo(
                key=rt.get("canonical_key", ""),
                label=rt.get("label", ""),
                category=rt.get("category", "general"),
            )
            for rt in rel_types_rows
        ],
        relationships=[
            CharacterRelationshipInfo(
                source_key=r.get("source_key", ""),
                target_key=r.get("target_key", ""),
                relation_type_key=r.get("type_key", ""),
                relation_type_label=r.get("type_label", ""),
                notes=r.get("notes", ""),
            )
            for r in rels_rows
        ],
    )


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


async def _load_merged_children_maps(
    db: Any,
    campaign_id: str,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load merged children maps for npcs/locations/entities."""
    if db is None or not campaign_id:
        return {
            "merged_npcs_by_parent": {},
            "merged_locations_by_parent": {},
            "merged_entities_by_parent": {},
        }
    return {
        "merged_npcs_by_parent": await db.entities.get_merged_npcs_map(campaign_id),
        "merged_locations_by_parent": await db.entities.get_merged_locations_map(campaign_id),
        "merged_entities_by_parent": await db.entities.get_merged_entities_map(campaign_id),
    }


async def _load_campaign_export_data(
    campaign_id: str,
) -> CampaignExportData | None:
    """Load all data required to build a campaign export bundle from DB."""
    db = _get_database()
    if db is None:
        return None

    row = await db.campaigns.get_campaign(campaign_id)
    if not row:
        return None

    players = await db.entities.get_players(campaign_id)
    npcs = await db.entities.get_npcs(campaign_id)
    locations = await db.entities.get_locations(campaign_id)
    entities = await db.entities.get_entities(campaign_id)
    relationship_types = await db.entities.get_relationship_types(campaign_id)
    relationships = await db.entities.get_character_relationships(campaign_id)
    merged_maps = await _load_merged_children_maps(db, campaign_id)
    sessions_rows = await db.sessions.list_sessions(campaign_id)

    sessions: list[CampaignExportSessionData] = []
    for session in sessions_rows:
        session_id = str(session.get("id", "") or "")
        transcriptions = []
        if session_id:
            transcriptions = [
                dict(item)
                for item in await db.transcriptions.get_transcriptions(session_id)
            ]
        sessions.append(
            CampaignExportSessionData(
                session_id=session_id,
                title=str(session.get("title", "") or ""),
                started_at=session.get("started_at", ""),
                ended_at=session.get("ended_at", ""),
                status=str(session.get("status", "") or ""),
                session_summary=str(session.get("session_summary", "") or ""),
                session_chronology=str(session.get("session_chronology", "") or ""),
                transcriptions=transcriptions,
            )
        )

    return CampaignExportData(
        campaign_id=campaign_id,
        name=str(row.get("name", "") or ""),
        game_system=str(row.get("game_system", "") or ""),
        language=str(row.get("language", "es") or "es"),
        description=str(row.get("description", "") or ""),
        campaign_summary=str(row.get("campaign_summary", "") or ""),
        dm_speaker_id=str(row.get("dm_speaker_id", "") or ""),
        players=[dict(item) for item in players],
        npcs=[dict(item) for item in npcs],
        locations=[dict(item) for item in locations],
        entities=[dict(item) for item in entities],
        relationship_types=[dict(item) for item in relationship_types],
        relationships=[dict(item) for item in relationships],
        merged_npcs_by_parent=merged_maps["merged_npcs_by_parent"],
        merged_locations_by_parent=merged_maps["merged_locations_by_parent"],
        merged_entities_by_parent=merged_maps["merged_entities_by_parent"],
        sessions=sessions,
    )


_CAMPAIGN_SUMMARY_PREVIEW_LEN = 200


@router.get("/api/campaigns")
async def get_campaigns() -> dict[str, Any]:
    """Return active campaign info including players, NPCs and relationships."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    campaign = state.active_campaign

    # Fall back to DB if campaign is not in memory
    if (
        not campaign
        and config
        and hasattr(config, "campaign")
        and config.campaign
        and db
    ):
        try:
            row = await db.campaigns.get_campaign(config.campaign.campaign_id)
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
            campaign["players"] = await db.entities.get_players(campaign_id)
        except Exception as exc:
            logger.error("Error fetching players: %s", exc)
            campaign.setdefault("players", [])
        try:
            campaign["npcs"] = await db.entities.get_npcs(campaign_id)
        except Exception as exc:
            logger.error("Error fetching NPCs: %s", exc)
            campaign.setdefault("npcs", [])
        try:
            campaign["locations"] = await db.entities.get_locations(campaign_id)
        except Exception as exc:
            logger.error("Error fetching locations: %s", exc)
            campaign.setdefault("locations", [])
        try:
            campaign["entities"] = await db.entities.get_entities(campaign_id)
        except Exception as exc:
            logger.error("Error fetching entities: %s", exc)
            campaign.setdefault("entities", [])
        try:
            await db.entities.seed_canonical_relationship_types(campaign_id)
        except Exception as exc:
            logger.error("Error seeding canonical relationship types: %s", exc)
        try:
            campaign["relationship_types"] = await db.entities.get_relationship_types(
                campaign_id
            )
        except Exception as exc:
            logger.error("Error fetching relationship types: %s", exc)
            campaign.setdefault("relationship_types", [])
        try:
            campaign["relationships"] = await db.entities.get_character_relationships(
                campaign_id
            )
        except Exception as exc:
            logger.error("Error fetching relationships: %s", exc)
            campaign.setdefault("relationships", [])
        try:
            campaign.update(await _load_merged_children_maps(db, campaign_id))
        except Exception as exc:
            logger.error("Error fetching merged children maps: %s", exc)
            campaign.setdefault("merged_npcs_by_parent", {})
            campaign.setdefault("merged_locations_by_parent", {})
            campaign.setdefault("merged_entities_by_parent", {})
    else:
        campaign.setdefault("players", [])
        campaign.setdefault("npcs", [])
        campaign.setdefault("entities", [])
        campaign.setdefault("relationship_types", [])
        campaign.setdefault("relationships", [])
        campaign.setdefault("locations", [])
        campaign.setdefault("merged_npcs_by_parent", {})
        campaign.setdefault("merged_locations_by_parent", {})
        campaign.setdefault("merged_entities_by_parent", {})

    campaign.setdefault("locations", [])
    campaign.setdefault("entities", [])
    campaign.setdefault("merged_npcs_by_parent", {})
    campaign.setdefault("merged_locations_by_parent", {})
    campaign.setdefault("merged_entities_by_parent", {})

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
            rows = await db.campaigns.list_campaigns()
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
            row = await db.campaigns.get_campaign(campaign_id)
            if row:
                campaign = _flatten_campaign_row(row)
                campaign["players"] = await db.entities.get_players(campaign_id)
                campaign["npcs"] = await db.entities.get_npcs(campaign_id)
                campaign["locations"] = await db.entities.get_locations(campaign_id)
                campaign["entities"] = await db.entities.get_entities(campaign_id)
                campaign["relationship_types"] = await db.entities.get_relationship_types(
                    campaign_id
                )
                campaign["relationships"] = await db.entities.get_character_relationships(
                    campaign_id
                )
                campaign.update(await _load_merged_children_maps(db, campaign_id))
        except Exception as exc:
            logger.error("Error loading browse campaign %s: %s", campaign_id, exc)
            return {"campaign": None}

    if (
        campaign is None
        and state.active_campaign
        and state.active_campaign.get("id") == campaign_id
    ):
        campaign = dict(state.active_campaign)
        campaign.setdefault("campaign_summary", "")
        campaign.setdefault("players", [])
        campaign.setdefault("npcs", [])
        campaign.setdefault("entities", [])
        campaign.setdefault("relationship_types", [])
        campaign.setdefault("relationships", [])

        campaign.setdefault("locations", [])
        campaign.setdefault("entities", [])
        campaign.setdefault("merged_npcs_by_parent", {})
        campaign.setdefault("merged_locations_by_parent", {})
        campaign.setdefault("merged_entities_by_parent", {})
    if campaign is not None:
        campaign.setdefault("merged_npcs_by_parent", {})
        campaign.setdefault("merged_locations_by_parent", {})
        campaign.setdefault("merged_entities_by_parent", {})
    return {"campaign": campaign}


@router.post("/api/campaigns/{campaign_id}/export")
async def create_campaign_export(campaign_id: str) -> dict[str, Any]:
    """Generate a new immutable export bundle for a campaign."""
    if _get_database() is None:
        raise HTTPException(status_code=503, detail="Database not available")

    data = await _load_campaign_export_data(campaign_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    service = _get_campaign_export_service()
    manifest = service.build_export(data)
    export_id = str(manifest["export_id"])
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "export_id": export_id,
        "exported_at": manifest.get("created_at", ""),
        "display_date": manifest.get("display_date", ""),
        "zip_name": manifest.get("zip_name", ""),
        "files": manifest.get("files", []),
        "download_url": (
            f"/api/campaigns/{quote(campaign_id)}/export/download"
            f"?export_id={quote(export_id)}"
        ),
    }


@router.get("/api/campaigns/{campaign_id}/exports")
async def list_campaign_exports(campaign_id: str) -> dict[str, Any]:
    """List immutable export bundles previously generated for a campaign."""
    service = _get_campaign_export_service()
    exports = []
    for item in service.list_exports(campaign_id):
        export_id = str(item.get("export_id", ""))
        exports.append(
            {
                "campaign_id": item.get("campaign_id", campaign_id),
                "export_id": export_id,
                "created_at": item.get("created_at", ""),
                "display_date": item.get("display_date", ""),
                "zip_name": item.get("zip_name", ""),
                "files": item.get("files", []),
                "download_url": (
                    f"/api/campaigns/{quote(campaign_id)}/export/download"
                    f"?export_id={quote(export_id)}"
                ),
            }
        )
    return {"campaign_id": campaign_id, "exports": exports}


@router.get("/api/campaigns/{campaign_id}/export/download")
async def download_campaign_export(
    campaign_id: str,
    export_id: str = Query(default=""),
) -> FileResponse:
    """Download one concrete version of a campaign export bundle."""
    if not export_id.strip():
        raise HTTPException(status_code=400, detail="export_id is required")

    service = _get_campaign_export_service()
    zip_path = service.get_export_zip(campaign_id, export_id)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
    )


@router.patch("/api/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update editable fields of a campaign."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    editable = {
        "name",
        "game_system",
        "description",
        "language",
        "custom_instructions",
        "dm_speaker_id",
    }
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}

    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    for k, v in updates.items():
        state.active_campaign[k] = v

    if config and hasattr(config, "campaign") and config.campaign:
        campaign_obj = config.campaign
        field_map = {
            "name": "name",
            "game_system": "game_system",
            "description": "description",
            "language": "language",
            "custom_instructions": "custom_instructions",
            "dm_speaker_id": "dm_speaker_id",
        }
        for k, v in updates.items():
            attr = field_map.get(k, k)
            if hasattr(campaign_obj, attr):
                object.__setattr__(campaign_obj, attr, v)

    if db is not None:
        try:
            current = await db.campaigns.get_campaign(campaign_id)
            if current:
                await db.campaigns.upsert_campaign(
                    campaign_id=campaign_id,
                    name=updates.get("name", current.get("name", "")),
                    game_system=updates.get(
                        "game_system", current.get("game_system", "")
                    ),
                    language=updates.get("language", current.get("language", "es")),
                    description=updates.get(
                        "description", current.get("description", "")
                    ),
                    campaign_summary=current.get("campaign_summary", ""),
                    speaker_map=current.get("speaker_map"),
                    dm_speaker_id=updates.get(
                        "dm_speaker_id", current.get("dm_speaker_id", "")
                    ),
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


@router.put("/api/campaigns/{campaign_id}/campaign-summary")
async def update_campaign_summary_text(
    campaign_id: str, body: dict[str, str]
) -> dict[str, Any]:
    """Update the campaign summary cache text (overwrite, no history)."""
    db = _get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    text = body.get("campaign_summary", "")
    await db.campaigns.update_campaign_summary(campaign_id, text)

    state = _get_state()
    state.campaign_summary = text
    if state.active_campaign and state.active_campaign.get("id") == campaign_id:
        state.active_campaign["campaign_summary"] = text

    return {"ok": True}


@router.post("/api/campaigns/{campaign_id}/campaign-summaries/generate")
async def generate_campaign_summary_on_demand(campaign_id: str) -> dict[str, Any]:
    """Generate a campaign summary on demand."""
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

    from rpg_scribe.core.events import GenerationProgressEvent

    event_bus = _get_event_bus()

    # Step 1: Generate missing session summaries
    all_sessions = await db.sessions.list_sessions(campaign_id)
    missing = [
        s
        for s in all_sessions
        if s.get("status") == "completed"
        and not (s.get("session_summary") or "").strip()
    ]
    sessions_processed = 0
    for idx, session in enumerate(missing, 1):
        session_id = session["id"]
        await event_bus.publish(GenerationProgressEvent(
            target="campaign",
            message=f"Generating session summary {idx}/{len(missing)}...",
            campaign_id=campaign_id,
            session_id=session_id,
        ))
        try:
            rows = await db.transcriptions.get_transcriptions(session_id)
            if not rows:
                continue
            summary = await summarizer.generate_session_summary_from_transcriptions(
                rows
            )
            if summary:
                await db.sessions.update_session_summary(session_id, summary)
                sessions_processed += 1
                logger.info("Generated missing summary for session %s", session_id)
        except Exception as exc:
            logger.error(
                "Failed to generate summary for session %s: %s", session_id, exc
            )

    # Step 2: Generate campaign summary from all sessions that now have one
    all_sessions = await db.sessions.list_sessions(campaign_id)
    completed = sorted(
        [
            s
            for s in all_sessions
            if (s.get("session_summary") or "").strip()
            and s.get("status") == "completed"
        ],
        key=lambda s: s.get("started_at") or 0,
    )
    if not completed:
        raise HTTPException(
            status_code=422, detail="No completed sessions with summaries found"
        )

    await event_bus.publish(GenerationProgressEvent(
        target="campaign",
        message=f"Generating campaign summary from {len(completed)} sessions...",
        campaign_id=campaign_id,
    ))

    try:
        campaign_summary = await summarizer.generate_campaign_summary(
            completed, trigger_session_id=""
        )
    except Exception as exc:
        logger.error("Failed to generate campaign summary on demand: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if campaign_summary:
        await db.campaigns.save_campaign_summary(
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
        rows = await db.campaigns.list_campaign_summaries(campaign_id)
    except Exception as exc:
        logger.error("Error listing campaign summaries: %s", exc)
        return {"campaign_summaries": []}

    result = []
    for r in rows:
        content = r.get("content", "")
        preview = content[:_CAMPAIGN_SUMMARY_PREVIEW_LEN]
        if len(content) > _CAMPAIGN_SUMMARY_PREVIEW_LEN:
            preview += "..."
        result.append(
            {
                "id": r["id"],
                "campaign_id": r.get("campaign_id", ""),
                "generated_at": r.get("generated_at"),
                "trigger_session_id": r.get("trigger_session_id", ""),
                "session_count": r.get("session_count", 0),
                "preview": preview,
            }
        )
    return {"campaign_summaries": result}


@router.get("/api/campaigns/{campaign_id}/campaign-summaries/latest")
async def get_latest_campaign_summary(campaign_id: str) -> dict[str, Any]:
    """Return the most recently generated campaign summary."""
    db = _get_database()
    if db is None:
        return {"campaign_summary": None}
    try:
        row = await db.campaigns.get_latest_campaign_summary(campaign_id)
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
        row = await db.campaigns.get_campaign_summary_by_id(summary_id)
    except Exception as exc:
        logger.error("Error fetching campaign summary %s: %s", summary_id, exc)
        return {"campaign_summary": None}
    if row and row.get("campaign_id") != campaign_id:
        return {"campaign_summary": None}
    return {"campaign_summary": dict(row) if row else None}
