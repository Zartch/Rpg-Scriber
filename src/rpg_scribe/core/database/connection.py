"""Database connection and infrastructure — base Database class."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from rpg_scribe.core.database.schema import SCHEMA_SQL

if TYPE_CHECKING:
    from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
    from rpg_scribe.core.database.repositories.session_repo import SessionRepository
    from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
    from rpg_scribe.core.database.repositories.entity_repo import EntityRepository

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite wrapper for RPG Scribe persistence (infrastructure layer)."""

    def __init__(self, db_path: str | Path = "rpg_scribe.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self.campaigns: CampaignRepository = None  # type: ignore[assignment]
        self.sessions: SessionRepository = None  # type: ignore[assignment]
        self.transcriptions: TranscriptionRepository = None  # type: ignore[assignment]
        self.entities: EntityRepository = None  # type: ignore[assignment]

    async def connect(self) -> None:
        """Open the database connection and create tables if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._run_schema_migrations()
        await self._conn.commit()

        # Initialize repositories after connection is established
        from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
        from rpg_scribe.core.database.repositories.session_repo import SessionRepository
        from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
        from rpg_scribe.core.database.repositories.entity_repo import EntityRepository

        self.campaigns = CampaignRepository(self)
        self.sessions = SessionRepository(self)
        self.transcriptions = TranscriptionRepository(self)
        self.entities = EntityRepository(self)

        logger.info("Database connected: %s", self._db_path)

    async def _run_schema_migrations(self) -> None:
        """Apply lightweight in-place schema migrations for legacy DB files."""
        await self._ensure_column("npcs", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("locations", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("campaign_entities", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("sessions", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("sessions", "session_chronology", "TEXT DEFAULT ''")

    async def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cursor = await self.conn.execute(f"PRAGMA table_info({table})")
        cols = [str(r["name"]) for r in await cursor.fetchall()]
        if column in cols:
            return
        await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    @staticmethod
    def _merge_text_fields(primary: str, secondary: str) -> str:
        """Merge two description-like fields without losing unique text."""
        a = (primary or "").strip()
        b = (secondary or "").strip()
        if not a:
            return b
        if not b:
            return a
        if b.casefold() in a.casefold():
            return a
        return f"{a}\n{b}"

    # --- Backward-compat delegations (temporary — removed once all callers migrate) ---

    # CampaignRepository delegations
    async def upsert_campaign(self, *args, **kwargs):
        return await self.campaigns.upsert_campaign(*args, **kwargs)

    async def get_campaign(self, *args, **kwargs):
        return await self.campaigns.get_campaign(*args, **kwargs)

    async def list_campaigns(self, *args, **kwargs):
        return await self.campaigns.list_campaigns(*args, **kwargs)

    async def update_campaign_summary(self, *args, **kwargs):
        return await self.campaigns.update_campaign_summary(*args, **kwargs)

    async def save_campaign_summary(self, *args, **kwargs):
        return await self.campaigns.save_campaign_summary(*args, **kwargs)

    async def list_campaign_summaries(self, *args, **kwargs):
        return await self.campaigns.list_campaign_summaries(*args, **kwargs)

    async def get_campaign_summary_by_id(self, *args, **kwargs):
        return await self.campaigns.get_campaign_summary_by_id(*args, **kwargs)

    async def get_latest_campaign_summary(self, *args, **kwargs):
        return await self.campaigns.get_latest_campaign_summary(*args, **kwargs)

    # SessionRepository delegations
    async def create_session(self, *args, **kwargs):
        return await self.sessions.create_session(*args, **kwargs)

    async def end_session(self, *args, **kwargs):
        return await self.sessions.end_session(*args, **kwargs)

    async def get_session(self, *args, **kwargs):
        return await self.sessions.get_session(*args, **kwargs)

    async def list_sessions(self, *args, **kwargs):
        return await self.sessions.list_sessions(*args, **kwargs)

    async def list_all_sessions(self, *args, **kwargs):
        return await self.sessions.list_all_sessions(*args, **kwargs)

    async def list_uncategorized_sessions(self, *args, **kwargs):
        return await self.sessions.list_uncategorized_sessions(*args, **kwargs)

    async def merge_sessions(self, *args, **kwargs):
        return await self.sessions.merge_sessions(*args, **kwargs)

    async def update_session_summary(self, *args, **kwargs):
        return await self.sessions.update_session_summary(*args, **kwargs)

    async def update_session_chronology(self, *args, **kwargs):
        return await self.sessions.update_session_chronology(*args, **kwargs)

    # TranscriptionRepository delegations
    async def save_transcription(self, *args, **kwargs):
        return await self.transcriptions.save_transcription(*args, **kwargs)

    async def get_transcriptions(self, *args, **kwargs):
        return await self.transcriptions.get_transcriptions(*args, **kwargs)

    async def update_transcription_text(self, *args, **kwargs):
        return await self.transcriptions.update_transcription_text(*args, **kwargs)

    async def delete_transcription(self, *args, **kwargs):
        return await self.transcriptions.delete_transcription(*args, **kwargs)

    async def update_transcription_is_ingame(self, *args, **kwargs):
        return await self.transcriptions.update_transcription_is_ingame(*args, **kwargs)

    async def save_transcription_edit(self, *args, **kwargs):
        return await self.transcriptions.save_transcription_edit(*args, **kwargs)

    async def get_transcription_edits(self, *args, **kwargs):
        return await self.transcriptions.get_transcription_edits(*args, **kwargs)

    async def save_word_replacement(self, *args, **kwargs):
        return await self.transcriptions.save_word_replacement(*args, **kwargs)

    async def get_word_replacements(self, *args, **kwargs):
        return await self.transcriptions.get_word_replacements(*args, **kwargs)

    async def delete_word_replacement(self, *args, **kwargs):
        return await self.transcriptions.delete_word_replacement(*args, **kwargs)

    async def apply_word_replacements(self, *args, **kwargs):
        return await self.transcriptions.apply_word_replacements(*args, **kwargs)

    # EntityRepository delegations
    async def save_npc(self, *args, **kwargs):
        return await self.entities.save_npc(*args, **kwargs)

    async def get_npcs(self, *args, **kwargs):
        return await self.entities.get_npcs(*args, **kwargs)

    async def merge_npcs(self, *args, **kwargs):
        return await self.entities.merge_npcs(*args, **kwargs)

    async def save_location(self, *args, **kwargs):
        return await self.entities.save_location(*args, **kwargs)

    async def get_locations(self, *args, **kwargs):
        return await self.entities.get_locations(*args, **kwargs)

    async def merge_locations(self, *args, **kwargs):
        return await self.entities.merge_locations(*args, **kwargs)

    async def save_entity(self, *args, **kwargs):
        return await self.entities.save_entity(*args, **kwargs)

    async def get_entities(self, *args, **kwargs):
        return await self.entities.get_entities(*args, **kwargs)

    async def merge_entities(self, *args, **kwargs):
        return await self.entities.merge_entities(*args, **kwargs)

    async def save_player(self, *args, **kwargs):
        return await self.entities.save_player(*args, **kwargs)

    async def get_players(self, *args, **kwargs):
        return await self.entities.get_players(*args, **kwargs)

    async def player_exists(self, *args, **kwargs):
        return await self.entities.player_exists(*args, **kwargs)

    async def update_player(self, *args, **kwargs):
        return await self.entities.update_player(*args, **kwargs)

    async def get_relationship_types(self, *args, **kwargs):
        return await self.entities.get_relationship_types(*args, **kwargs)

    async def resolve_relationship_type(self, *args, **kwargs):
        return await self.entities.resolve_relationship_type(*args, **kwargs)

    async def merge_relationship_types(self, *args, **kwargs):
        return await self.entities.merge_relationship_types(*args, **kwargs)

    async def save_character_relationship(self, *args, **kwargs):
        return await self.entities.save_character_relationship(*args, **kwargs)

    async def get_character_relationships(self, *args, **kwargs):
        return await self.entities.get_character_relationships(*args, **kwargs)

    async def delete_character_relationship(self, *args, **kwargs):
        return await self.entities.delete_character_relationship(*args, **kwargs)

    async def relationship_exists(self, *args, **kwargs):
        return await self.entities.relationship_exists(*args, **kwargs)

    async def rename_relationship_entity_key(self, *args, **kwargs):
        return await self.entities.rename_relationship_entity_key(*args, **kwargs)

    async def save_question(self, *args, **kwargs):
        return await self.entities.save_question(*args, **kwargs)

    async def answer_question(self, *args, **kwargs):
        return await self.entities.answer_question(*args, **kwargs)

    async def get_pending_questions(self, *args, **kwargs):
        return await self.entities.get_pending_questions(*args, **kwargs)

    async def get_answered_unprocessed_questions(self, *args, **kwargs):
        return await self.entities.get_answered_unprocessed_questions(*args, **kwargs)

    async def mark_questions_processed(self, *args, **kwargs):
        return await self.entities.mark_questions_processed(*args, **kwargs)

    async def npc_exists(self, *args, **kwargs):
        return await self.entities.npc_exists(*args, **kwargs)

    async def update_npc(self, *args, **kwargs):
        return await self.entities.update_npc(*args, **kwargs)

    async def update_merged_npc(self, *args, **kwargs):
        return await self.entities.update_merged_npc(*args, **kwargs)

    async def location_exists(self, *args, **kwargs):
        return await self.entities.location_exists(*args, **kwargs)

    async def update_location(self, *args, **kwargs):
        return await self.entities.update_location(*args, **kwargs)

    async def update_merged_location(self, *args, **kwargs):
        return await self.entities.update_merged_location(*args, **kwargs)

    async def entity_exists(self, *args, **kwargs):
        return await self.entities.entity_exists(*args, **kwargs)

    async def update_entity(self, *args, **kwargs):
        return await self.entities.update_entity(*args, **kwargs)

    async def update_merged_entity(self, *args, **kwargs):
        return await self.entities.update_merged_entity(*args, **kwargs)

    async def get_merged_npcs_map(self, *args, **kwargs):
        return await self.entities.get_merged_npcs_map(*args, **kwargs)

    async def get_merged_locations_map(self, *args, **kwargs):
        return await self.entities.get_merged_locations_map(*args, **kwargs)

    async def get_merged_entities_map(self, *args, **kwargs):
        return await self.entities.get_merged_entities_map(*args, **kwargs)
