"""Database connection and infrastructure — base Database class."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from rpg_scribe.core.database.schema import SCHEMA_SQL

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite wrapper for RPG Scribe persistence (infrastructure layer)."""

    def __init__(self, db_path: str | Path = "rpg_scribe.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        # Deferred imports to break circular dependency (repos import Database)
        from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
        from rpg_scribe.core.database.repositories.session_repo import SessionRepository
        from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
        from rpg_scribe.core.database.repositories.entity_repo import EntityRepository
        self.campaigns = CampaignRepository(self)
        self.sessions = SessionRepository(self)
        self.transcriptions = TranscriptionRepository(self)
        self.entities = EntityRepository(self)

    async def connect(self) -> None:
        """Open the database connection and create tables if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._run_schema_migrations()
        await self._conn.commit()

        logger.info("Database connected: %s", self._db_path)

    async def _run_schema_migrations(self) -> None:
        """Apply lightweight in-place schema migrations for legacy DB files."""
        await self._ensure_column("npcs", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("locations", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("campaign_entities", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("sessions", "merged_into", "TEXT DEFAULT ''")
        await self._ensure_column("sessions", "session_chronology", "TEXT DEFAULT ''")
        await self._ensure_column("sessions", "title", "TEXT NOT NULL DEFAULT ''")

        # Canonical graph model — character_relationships enrichment
        await self._ensure_column("character_relationships", "relation_family", "TEXT DEFAULT ''")
        await self._ensure_column("character_relationships", "strength", "REAL DEFAULT 0.5")
        await self._ensure_column("character_relationships", "confidence", "REAL DEFAULT 0.5")
        await self._ensure_column("character_relationships", "polarity", "TEXT DEFAULT 'neutral'")
        await self._ensure_column("character_relationships", "certainty", "TEXT DEFAULT 'explicit'")
        await self._ensure_column("character_relationships", "origin", "TEXT DEFAULT 'extracted'")
        await self._ensure_column("character_relationships", "is_active", "INTEGER DEFAULT 1")
        await self._ensure_column("character_relationships", "source_session_id", "TEXT DEFAULT ''")
        await self._ensure_column("character_relationships", "evidence_snippets_json", "TEXT DEFAULT '[]'")
        await self._ensure_column("character_relationships", "tags_json", "TEXT DEFAULT '[]'")
        await self._ensure_column("character_relationships", "type_label_raw", "TEXT DEFAULT ''")

        # relationship_types enrichment
        await self._ensure_column("relationship_types", "relation_family", "TEXT DEFAULT ''")
        await self._ensure_column("relationship_types", "polarity", "TEXT DEFAULT 'neutral'")
        await self._ensure_column("relationship_types", "is_canonical", "INTEGER DEFAULT 0")

        # campaign_entities enrichment
        await self._ensure_column("campaign_entities", "tags_json", "TEXT DEFAULT '[]'")
        await self._ensure_column("campaign_entities", "status", "TEXT DEFAULT 'active'")

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
