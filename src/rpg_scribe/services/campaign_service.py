"""Campaign business logic."""
from __future__ import annotations

import logging
from typing import Any

from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
from rpg_scribe.core.database.repositories.entity_repo import EntityRepository
from rpg_scribe.core.models import (
    CampaignContext,
    CharacterRelationshipInfo,
    EntityInfo,
    LocationInfo,
    NPCInfo,
    PlayerInfo,
    RelationshipTypeInfo,
)

logger = logging.getLogger(__name__)


class CampaignService:
    def __init__(
        self,
        campaign_repo: CampaignRepository,
        entity_repo: EntityRepository,
    ) -> None:
        self._campaigns = campaign_repo
        self._entities = entity_repo

    async def load_full_context(self, campaign_id: str) -> CampaignContext | None:
        """Hydrate a full CampaignContext from the database."""
        camp_row = await self._campaigns.get_campaign(campaign_id)
        if not camp_row:
            return None

        players_rows = await self._entities.get_players(campaign_id)
        npcs_rows = await self._entities.get_npcs(campaign_id)
        locations_rows = await self._entities.get_locations(campaign_id)
        entities_rows = await self._entities.get_entities(campaign_id)
        rel_types_rows = await self._entities.get_relationship_types(campaign_id)
        rels_rows = await self._entities.get_character_relationships(campaign_id)

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

    async def get_flat(self, campaign_id: str) -> dict[str, Any] | None:
        """Get campaign as a flat dict for API responses."""
        return await self._campaigns.get_campaign(campaign_id)
