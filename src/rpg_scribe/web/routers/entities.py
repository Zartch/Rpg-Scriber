"""Player, NPC, location, entity and relationship endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from rpg_scribe.core.models import (
    CharacterRelationshipInfo,
    EntityInfo,
    LocationInfo,
    NPCInfo,
    RelationshipTypeInfo,
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


def _persist_campaign_toml(config: Any) -> None:
    """Persist in-memory campaign config back to its TOML file if configured."""
    from rpg_scribe.config import save_campaign_toml
    if not config or not getattr(config, "campaign", None):
        return
    campaign_path = getattr(config, "campaign_path", "")
    if not campaign_path:
        return
    save_campaign_toml(config.campaign, campaign_path)


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
        normalized.append(
            {
                "name": name,
                "description": _extract_location_description(raw),
            }
        )
    return normalized


def _extract_entity_name(value: Any) -> str:
    """Extract entity name from dict/dataclass-like value."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    if hasattr(value, "name"):
        return str(getattr(value, "name", "")).strip()
    return ""


def _extract_entity_type(value: Any) -> str:
    """Extract entity type from dict/dataclass-like value."""
    if isinstance(value, dict):
        return str(value.get("entity_type", "group") or "group").strip() or "group"
    if hasattr(value, "entity_type"):
        return str(getattr(value, "entity_type", "group") or "group").strip() or "group"
    return "group"


def _extract_entity_description(value: Any) -> str:
    """Extract entity description from dict/dataclass-like value."""
    if isinstance(value, dict):
        return str(value.get("description", "")).strip()
    if hasattr(value, "description"):
        return str(getattr(value, "description", "")).strip()
    return ""


def _normalize_entities(values: list[Any] | None) -> list[dict[str, str]]:
    """Normalize entities into a list of {name, entity_type, description} objects."""
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values or []:
        name = _extract_entity_name(raw)
        if not name:
            continue
        folded = name.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(
            {
                "name": name,
                "entity_type": _extract_entity_type(raw),
                "description": _extract_entity_description(raw),
            }
        )
    return normalized


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
        "merged_npcs_by_parent": await db.get_merged_npcs_map(campaign_id),
        "merged_locations_by_parent": await db.get_merged_locations_map(campaign_id),
        "merged_entities_by_parent": await db.get_merged_entities_map(campaign_id),
    }


async def _validate_campaign(campaign_id: str) -> bool:
    """Check campaign exists and ensure it is loaded into state."""
    from rpg_scribe.web.routers.campaigns import _validate_campaign as _vc
    return await _vc(campaign_id)


# -- Player endpoints ----------------------------------------------


@router.put("/api/campaigns/{campaign_id}/players/{player_id}")
async def update_player(
    campaign_id: str, player_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Update a player's editable fields."""
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    editable = {"discord_name", "character_name", "character_description"}
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}
    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    if db is not None:
        try:
            await db.update_player(player_id, **updates)
        except Exception as exc:
            logger.error("Error updating player: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    if config and hasattr(config, "campaign") and config.campaign:
        campaign_obj = config.campaign
        discord_id = body.get("discord_id", "")
        for p in campaign_obj.players:
            if p.discord_id == discord_id:
                for k, v in updates.items():
                    object.__setattr__(p, k, v)
                if (
                    "character_name" in updates
                    and p.discord_id in campaign_obj.speaker_map
                ):
                    campaign_obj.speaker_map[p.discord_id] = updates["character_name"]
                break

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
async def create_npc(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Create a new NPC."""
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    if not name:
        return {"ok": False, "error": "NPC name is required"}

    if db is not None:
        try:
            if await db.npc_exists(campaign_id, name):
                return {"ok": False, "error": "NPC already exists"}
            await db.save_npc(campaign_id, name, description)
        except Exception as exc:
            logger.error("Error saving NPC: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    if config and hasattr(config, "campaign") and config.campaign:
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
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
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


@router.post("/api/campaigns/{campaign_id}/npcs/merge")
async def merge_npcs_endpoint(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Merge one NPC into another NPC in the same campaign."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_name = str(body.get("source_name", "")).strip()
    target_name = str(body.get("target_name", "")).strip()
    if not source_name or not target_name:
        return {"ok": False, "error": "source_name and target_name are required"}

    try:
        await db.merge_npcs(campaign_id, source_name, target_name)
        npcs = await db.get_npcs(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["npcs"] = npcs
        state.active_campaign["relationships"] = relationships

        if config and getattr(config, "campaign", None):
            config.campaign.known_npcs = [
                NPCInfo(
                    name=str(n.get("name", "")),
                    description=str(n.get("description", "")),
                )
                for n in npcs
                if n.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error merging NPCs: %s", exc)
        return {"ok": False, "error": "Failed to merge NPCs"}

    return {"ok": True, "npcs": state.active_campaign.get("npcs", [])}


@router.put("/api/campaigns/{campaign_id}/npcs/merged/{npc_id}")
async def update_merged_npc_endpoint(
    campaign_id: str,
    npc_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Update a merged NPC alias and optionally move/unmerge it."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    merged_into = str(body.get("merged_into", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    try:
        await db.update_merged_npc(
            campaign_id,
            npc_id,
            name=name,
            description=description,
            merged_into=merged_into,
        )
        state.active_campaign["npcs"] = await db.get_npcs(campaign_id)
        state.active_campaign["merged_npcs_by_parent"] = await db.get_merged_npcs_map(
            campaign_id
        )
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["relationships"] = relationships
        if config and getattr(config, "campaign", None):
            config.campaign.known_npcs = [
                NPCInfo(
                    name=str(npc.get("name", "")),
                    description=str(npc.get("description", "")),
                )
                for npc in state.active_campaign.get("npcs", [])
                if npc.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error updating merged NPC: %s", exc)
        return {"ok": False, "error": "Failed to update merged NPC"}
    return {"ok": True}


# -- Location endpoints --------------------------------------------


@router.post("/api/campaigns/{campaign_id}/locations")
async def create_location_endpoint(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Add a location to the active campaign context."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    if not name:
        return {"ok": False, "error": "Location name is required"}

    current = _normalize_locations(state.active_campaign.get("locations", []))
    existing_keys = {loc["name"].casefold() for loc in current}
    if name.casefold() in existing_keys:
        return {"ok": False, "error": "Location already exists"}

    if db is not None:
        try:
            if await db.location_exists(campaign_id, name):
                return {"ok": False, "error": "Location already exists"}
            await db.save_location(
                campaign_id=campaign_id,
                name=name,
                description=description,
                first_seen_session=state.active_session_id or "",
            )
        except Exception as exc:
            logger.error("Error saving location: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    current.append({"name": name, "description": description})
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
async def update_location_endpoint(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Update a location (name/description) in the active campaign context."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    old_name = str(body.get("old_name", "")).strip()
    new_name = str(body.get("name", "")).strip()
    has_description = "description" in body
    new_description = (
        str(body.get("description", "")).strip() if has_description else ""
    )
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
            "description": (
                new_description
                if (loc["name"] == old_name and has_description)
                else loc.get("description", "")
            ),
        }
        for loc in locations
    ]
    state.active_campaign["locations"] = updated_locations

    for rel in state.active_campaign.get("relationships", []) or []:
        source_key = str(rel.get("source_key", ""))
        target_key = str(rel.get("target_key", ""))
        if source_key in {f"loc:{old_name}", f"location:{old_name}"}:
            rel["source_key"] = f"loc:{new_name}"
        if target_key in {f"loc:{old_name}", f"location:{old_name}"}:
            rel["target_key"] = f"loc:{new_name}"

    if db is not None:
        try:
            db_locations = await db.get_locations(campaign_id)
            for row in db_locations:
                if str(row.get("name", "")).casefold() == old_name.casefold():
                    db_updates: dict[str, Any] = {"name": new_name}
                    if has_description:
                        db_updates["description"] = new_description
                    await db.update_location(str(row.get("id", "")), **db_updates)
                    break
            await db.rename_relationship_entity_key(
                campaign_id, f"loc:{old_name}", f"loc:{new_name}"
            )
            await db.rename_relationship_entity_key(
                campaign_id, f"location:{old_name}", f"loc:{new_name}"
            )
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


@router.post("/api/campaigns/{campaign_id}/locations/merge")
async def merge_locations_endpoint(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Merge one location into another location in the same campaign."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_name = str(body.get("source_name", "")).strip()
    target_name = str(body.get("target_name", "")).strip()
    if not source_name or not target_name:
        return {"ok": False, "error": "source_name and target_name are required"}

    try:
        await db.merge_locations(campaign_id, source_name, target_name)
        locations = await db.get_locations(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["locations"] = locations
        state.active_campaign["relationships"] = relationships

        if config and getattr(config, "campaign", None):
            config.campaign.locations = [
                LocationInfo(
                    name=str(loc.get("name", "")),
                    description=str(loc.get("description", "")),
                )
                for loc in locations
                if loc.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error merging locations: %s", exc)
        return {"ok": False, "error": "Failed to merge locations"}

    return {"ok": True, "locations": state.active_campaign.get("locations", [])}


@router.put("/api/campaigns/{campaign_id}/locations/merged/{location_id}")
async def update_merged_location_endpoint(
    campaign_id: str,
    location_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Update a merged location alias and optionally move/unmerge it."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    merged_into = str(body.get("merged_into", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    try:
        await db.update_merged_location(
            campaign_id,
            location_id,
            name=name,
            description=description,
            merged_into=merged_into,
        )
        state.active_campaign["locations"] = await db.get_locations(campaign_id)
        state.active_campaign[
            "merged_locations_by_parent"
        ] = await db.get_merged_locations_map(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["relationships"] = relationships
        if config and getattr(config, "campaign", None):
            config.campaign.locations = [
                LocationInfo(
                    name=str(loc.get("name", "")),
                    description=str(loc.get("description", "")),
                )
                for loc in state.active_campaign.get("locations", [])
                if loc.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error updating merged location: %s", exc)
        return {"ok": False, "error": "Failed to update merged location"}
    return {"ok": True}


# -- Entity endpoints ----------------------------------------------


@router.post("/api/campaigns/{campaign_id}/entities")
async def create_entity_endpoint(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Create a new campaign entity (clan, corporation, faction, group...)."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    name = str(body.get("name", "")).strip()
    entity_type = str(body.get("entity_type", "group") or "group").strip() or "group"
    description = str(body.get("description", "")).strip()
    if not name:
        return {"ok": False, "error": "Entity name is required"}

    entities = _normalize_entities(state.active_campaign.get("entities", []))
    if any(e["name"].casefold() == name.casefold() for e in entities):
        return {"ok": False, "error": "Entity already exists"}
    if db is not None:
        try:
            if await db.entity_exists(campaign_id, name):
                return {"ok": False, "error": "Entity already exists"}
            await db.save_entity(
                campaign_id=campaign_id,
                name=name,
                entity_type=entity_type,
                description=description,
                first_seen_session=state.active_session_id or "",
            )
        except Exception as exc:
            logger.error("Error saving entity: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    entities.append(
        {
            "name": name,
            "entity_type": entity_type,
            "description": description,
        }
    )
    state.active_campaign["entities"] = entities

    if config and hasattr(config, "campaign") and config.campaign:
        config.campaign.entities = [
            EntityInfo(
                name=e["name"],
                entity_type=e.get("entity_type", "group"),
                description=e.get("description", ""),
            )
            for e in entities
        ]

    try:
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)

    return {"ok": True, "entities": entities}


@router.put("/api/campaigns/{campaign_id}/entities/{entity_id}")
async def update_entity_endpoint(
    campaign_id: str, entity_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Update a campaign entity (name, entity_type, description)."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}

    editable = {"name", "entity_type", "description"}
    updates = {k: v for k, v in body.items() if k in editable and isinstance(v, str)}
    if not updates:
        return {"ok": False, "error": "No valid fields to update"}

    old_name = str(body.get("old_name", "")).strip()
    new_name = str(updates.get("name", old_name)).strip()
    if not new_name:
        return {"ok": False, "error": "Entity name is required"}

    if db is not None:
        try:
            await db.update_entity(entity_id, **updates)
            if old_name and new_name and old_name != new_name:
                await db.rename_relationship_entity_key(
                    campaign_id,
                    f"ent:{old_name}",
                    f"ent:{new_name}",
                )
                await db.rename_relationship_entity_key(
                    campaign_id,
                    f"entity:{old_name}",
                    f"ent:{new_name}",
                )
        except Exception as exc:
            logger.error("Error updating entity: %s", exc)
            return {"ok": False, "error": "Failed to save"}

    state_entities = _normalize_entities(state.active_campaign.get("entities", []))
    for entity in state_entities:
        if entity["name"] == old_name:
            entity.update({k: v for k, v in updates.items() if isinstance(v, str)})
            if "entity_type" not in entity or not entity["entity_type"]:
                entity["entity_type"] = "group"
            break
    state.active_campaign["entities"] = state_entities
    for rel in state.active_campaign.get("relationships", []) or []:
        source_key = str(rel.get("source_key", ""))
        target_key = str(rel.get("target_key", ""))
        if source_key in {f"ent:{old_name}", f"entity:{old_name}"}:
            rel["source_key"] = f"ent:{new_name}"
        if target_key in {f"ent:{old_name}", f"entity:{old_name}"}:
            rel["target_key"] = f"ent:{new_name}"

    if config and hasattr(config, "campaign") and config.campaign:
        for entity in config.campaign.entities:
            if entity.name == old_name:
                for k, v in updates.items():
                    object.__setattr__(entity, k, v)
                break
        for rel in config.campaign.relationships:
            if rel.source_key in {f"ent:{old_name}", f"entity:{old_name}"}:
                object.__setattr__(rel, "source_key", f"ent:{new_name}")
            if rel.target_key in {f"ent:{old_name}", f"entity:{old_name}"}:
                object.__setattr__(rel, "target_key", f"ent:{new_name}")

    try:
        if db is not None:
            await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except Exception as exc:
        logger.error("Error persisting campaign TOML: %s", exc)
    return {"ok": True}


@router.post("/api/campaigns/{campaign_id}/entities/merge")
async def merge_entities_endpoint(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Merge one campaign entity into another entity in same campaign."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_name = str(body.get("source_name", "")).strip()
    target_name = str(body.get("target_name", "")).strip()
    if not source_name or not target_name:
        return {"ok": False, "error": "source_name and target_name are required"}

    try:
        await db.merge_entities(campaign_id, source_name, target_name)
        entities = await db.get_entities(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["entities"] = entities
        state.active_campaign["relationships"] = relationships

        if config and getattr(config, "campaign", None):
            config.campaign.entities = [
                EntityInfo(
                    name=str(e.get("name", "")),
                    entity_type=str(e.get("entity_type", "group") or "group"),
                    description=str(e.get("description", "")),
                )
                for e in entities
                if e.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error merging entities: %s", exc)
        return {"ok": False, "error": "Failed to merge entities"}

    return {"ok": True, "entities": state.active_campaign.get("entities", [])}


@router.put("/api/campaigns/{campaign_id}/entities/merged/{entity_id}")
async def update_merged_entity_endpoint(
    campaign_id: str,
    entity_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Update a merged campaign entity alias and optionally move/unmerge it."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    name = str(body.get("name", "")).strip()
    entity_type = str(body.get("entity_type", "")).strip() or "group"
    description = str(body.get("description", "")).strip()
    merged_into = str(body.get("merged_into", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    try:
        await db.update_merged_entity(
            campaign_id,
            entity_id,
            name=name,
            description=description,
            entity_type=entity_type,
            merged_into=merged_into,
        )
        state.active_campaign["entities"] = await db.get_entities(campaign_id)
        state.active_campaign[
            "merged_entities_by_parent"
        ] = await db.get_merged_entities_map(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["relationships"] = relationships
        if config and getattr(config, "campaign", None):
            config.campaign.entities = [
                EntityInfo(
                    name=str(ent.get("name", "")),
                    entity_type=str(ent.get("entity_type", "group") or "group"),
                    description=str(ent.get("description", "")),
                )
                for ent in state.active_campaign.get("entities", [])
                if ent.get("name")
            ]
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error updating merged entity: %s", exc)
        return {"ok": False, "error": "Failed to update merged entity"}
    return {"ok": True}


# -- Relationship endpoints ----------------------------------------


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

    if not await _validate_campaign(campaign_id):
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


@router.post("/api/campaigns/{campaign_id}/relationship-types/merge")
async def merge_relationship_types(
    campaign_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Merge one relationship type label into another canonical type."""
    state = _get_state()
    db = _get_database()
    config = _get_config()
    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    source_type_key = str(body.get("source_type_key", "")).strip()
    target_type_key = str(body.get("target_type_key", "")).strip()
    if not source_type_key or not target_type_key:
        return {
            "ok": False,
            "error": "source_type_key and target_type_key are required",
        }

    try:
        await db.merge_relationship_types(campaign_id, source_type_key, target_type_key)
        relationship_types = await db.get_relationship_types(campaign_id)
        relationships = await db.get_character_relationships(campaign_id)
        state.active_campaign["relationship_types"] = relationship_types
        state.active_campaign["relationships"] = relationships
        await _sync_relationships_to_config(config, db, campaign_id)
        _persist_campaign_toml(config)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Error merging relationship types: %s", exc)
        return {"ok": False, "error": "Failed to merge relationship types"}

    return {
        "ok": True,
        "relationship_types": state.active_campaign.get("relationship_types", []),
        "relationships": state.active_campaign.get("relationships", []),
    }


@router.put("/api/campaigns/{campaign_id}/relationships")
async def update_relationship(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Edit a typed relationship between two campaign entities."""
    state = _get_state()
    db = _get_database()
    config = _get_config()

    if not await _validate_campaign(campaign_id):
        return {"ok": False, "error": "Campaign not found"}
    if db is None:
        return {"ok": False, "error": "Database not available"}

    old_source_key = str(body.get("old_source_key", "")).strip()
    old_target_key = str(body.get("old_target_key", "")).strip()
    old_type_key = str(body.get("old_type_key", "")).strip()
    source_key = str(body.get("source_key", "")).strip()
    target_key = str(body.get("target_key", "")).strip()
    relation_type = str(body.get("relation_type", "")).strip()
    notes = str(body.get("notes", "")).strip()
    category = str(body.get("category", "general") or "general").strip()

    if not old_source_key or not old_target_key or not old_type_key:
        return {
            "ok": False,
            "error": "old_source_key, old_target_key and old_type_key are required",
        }
    if not source_key or not target_key:
        return {"ok": False, "error": "source_key and target_key are required"}
    if source_key == target_key:
        return {"ok": False, "error": "Source and target cannot be the same"}
    if not relation_type:
        return {"ok": False, "error": "relation_type is required"}

    try:
        await db.delete_character_relationship(
            campaign_id,
            old_source_key,
            old_target_key,
            old_type_key,
        )
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
        logger.error("Error updating relationship: %s", exc)
        return {"ok": False, "error": "Failed to update relationship"}

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
