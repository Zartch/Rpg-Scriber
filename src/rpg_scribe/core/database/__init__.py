"""Database package — backward-compatible re-export."""
from __future__ import annotations

from rpg_scribe.core.database.schema import SCHEMA_SQL  # noqa: F401
from rpg_scribe.core.database.connection import Database
from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
from rpg_scribe.core.database.repositories.session_repo import SessionRepository
from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.database.repositories.entity_repo import (
    EntityRepository,
    normalize_relationship_type_label,
    _relation_similarity,
)

__all__ = [
    "Database",
    "SCHEMA_SQL",
    "CampaignRepository",
    "SessionRepository",
    "TranscriptionRepository",
    "EntityRepository",
    "normalize_relationship_type_label",
    "_relation_similarity",
]
