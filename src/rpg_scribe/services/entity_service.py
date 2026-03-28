"""Entity business logic and normalization."""
from __future__ import annotations

import logging
from typing import Any

from rpg_scribe.core.database.repositories.entity_repo import EntityRepository

logger = logging.getLogger(__name__)


class EntityService:
    def __init__(self, entity_repo: EntityRepository) -> None:
        self._repo = entity_repo

    @staticmethod
    def extract_location_name(value: Any) -> str:
        """Extract location name from str/dict/dataclass-like value."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return str(value.get("name", "")).strip()
        if hasattr(value, "name"):
            return str(getattr(value, "name", "")).strip()
        return ""

    @staticmethod
    def extract_location_description(value: Any) -> str:
        """Extract location description from dict/dataclass-like value."""
        if isinstance(value, dict):
            return str(value.get("description", "")).strip()
        if hasattr(value, "description"):
            return str(getattr(value, "description", "")).strip()
        return ""

    @staticmethod
    def normalize_locations(values: list[Any] | None) -> list[dict[str, str]]:
        """Normalize location values into {name, description} dicts."""
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in values or []:
            name = EntityService.extract_location_name(raw)
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            normalized.append(
                {
                    "name": name,
                    "description": EntityService.extract_location_description(raw),
                }
            )
        return normalized

    @staticmethod
    def _extract_entity_name(value: Any) -> str:
        """Extract entity name from dict/dataclass-like value."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return str(value.get("name", "")).strip()
        if hasattr(value, "name"):
            return str(getattr(value, "name", "")).strip()
        return ""

    @staticmethod
    def _extract_entity_type(value: Any) -> str:
        """Extract entity type from dict/dataclass-like value."""
        if isinstance(value, dict):
            return str(value.get("entity_type", "group") or "group").strip() or "group"
        if hasattr(value, "entity_type"):
            return str(getattr(value, "entity_type", "group") or "group").strip() or "group"
        return "group"

    @staticmethod
    def _extract_entity_description(value: Any) -> str:
        """Extract entity description from dict/dataclass-like value."""
        if isinstance(value, dict):
            return str(value.get("description", "")).strip()
        if hasattr(value, "description"):
            return str(getattr(value, "description", "")).strip()
        return ""

    @staticmethod
    def normalize_entities(values: list[Any] | None) -> list[dict[str, str]]:
        """Normalize entity values into {name, entity_type, description} dicts."""
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in values or []:
            name = EntityService._extract_entity_name(raw)
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            normalized.append(
                {
                    "name": name,
                    "entity_type": EntityService._extract_entity_type(raw),
                    "description": EntityService._extract_entity_description(raw),
                }
            )
        return normalized

    async def load_merged_children_maps(
        self, campaign_id: str
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Load merged children maps for npcs/locations/entities."""
        if not campaign_id:
            return {
                "merged_npcs_by_parent": {},
                "merged_locations_by_parent": {},
                "merged_entities_by_parent": {},
            }
        return {
            "merged_npcs_by_parent": await self._repo.get_merged_npcs_map(campaign_id),
            "merged_locations_by_parent": await self._repo.get_merged_locations_map(campaign_id),
            "merged_entities_by_parent": await self._repo.get_merged_entities_map(campaign_id),
        }
