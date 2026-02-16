"""SQLite async database wrapper for RPG Scribe.

Implements the schema defined in architecture section 8.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    game_system TEXT,
    language TEXT DEFAULT 'es',
    description TEXT,
    campaign_summary TEXT DEFAULT '',
    speaker_map JSON,
    dm_speaker_id TEXT,
    custom_instructions TEXT,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    discord_id TEXT,
    discord_name TEXT,
    character_name TEXT,
    character_description TEXT
);

CREATE TABLE IF NOT EXISTS npcs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    description TEXT,
    first_seen_session TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    started_at REAL,
    ended_at REAL,
    session_summary TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    speaker_id TEXT,
    speaker_name TEXT,
    text TEXT,
    timestamp REAL,
    confidence REAL,
    is_ingame BOOLEAN
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    question TEXT,
    answer TEXT,
    answered_at REAL,
    status TEXT DEFAULT 'pending'
);
"""


class Database:
    """Async SQLite wrapper for RPG Scribe persistence."""

    def __init__(self, db_path: str | Path = "rpg_scribe.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and create tables if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        logger.info("Database connected: %s", self._db_path)

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

    # ── Campaigns ──────────────────────────────────────────────────

    async def upsert_campaign(
        self,
        campaign_id: str,
        name: str,
        game_system: str = "",
        language: str = "es",
        description: str = "",
        campaign_summary: str = "",
        speaker_map: dict[str, str] | None = None,
        dm_speaker_id: str = "",
        custom_instructions: str = "",
    ) -> None:
        """Insert or update a campaign record."""
        now = time.time()
        await self.conn.execute(
            """INSERT INTO campaigns (id, name, game_system, language, description,
               campaign_summary, speaker_map, dm_speaker_id, custom_instructions,
               created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, game_system=excluded.game_system,
               language=excluded.language, description=excluded.description,
               campaign_summary=excluded.campaign_summary,
               speaker_map=excluded.speaker_map,
               dm_speaker_id=excluded.dm_speaker_id,
               custom_instructions=excluded.custom_instructions,
               updated_at=excluded.updated_at
            """,
            (
                campaign_id, name, game_system, language, description,
                campaign_summary, json.dumps(speaker_map or {}),
                dm_speaker_id, custom_instructions, now, now,
            ),
        )
        await self.conn.commit()

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        """Retrieve a campaign by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("speaker_map"):
            result["speaker_map"] = json.loads(result["speaker_map"])
        return result

    async def update_campaign_summary(
        self, campaign_id: str, summary: str
    ) -> None:
        """Update the accumulated campaign summary."""
        await self.conn.execute(
            "UPDATE campaigns SET campaign_summary = ?, updated_at = ? WHERE id = ?",
            (summary, time.time(), campaign_id),
        )
        await self.conn.commit()

    # ── Sessions ───────────────────────────────────────────────────

    async def create_session(
        self, session_id: str, campaign_id: str
    ) -> None:
        """Create a new session record."""
        await self.conn.execute(
            "INSERT INTO sessions (id, campaign_id, started_at, status) VALUES (?, ?, ?, ?)",
            (session_id, campaign_id, time.time(), "active"),
        )
        await self.conn.commit()

    async def end_session(
        self, session_id: str, summary: str = ""
    ) -> None:
        """Mark a session as completed."""
        await self.conn.execute(
            "UPDATE sessions SET ended_at = ?, session_summary = ?, status = ? WHERE id = ?",
            (time.time(), summary, "completed", session_id),
        )
        await self.conn.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve a session by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_sessions(self, campaign_id: str) -> list[dict[str, Any]]:
        """List all sessions for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions WHERE campaign_id = ? ORDER BY started_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # ── Transcriptions ─────────────────────────────────────────────

    async def save_transcription(
        self,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
        text: str,
        timestamp: float,
        confidence: float,
        is_ingame: bool | None = None,
    ) -> int:
        """Save a raw transcription and return its row ID."""
        cursor = await self.conn.execute(
            """INSERT INTO transcriptions
               (session_id, speaker_id, speaker_name, text, timestamp, confidence, is_ingame)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, speaker_id, speaker_name, text, timestamp, confidence, is_ingame),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_transcriptions(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Get all transcriptions for a session, ordered by timestamp."""
        cursor = await self.conn.execute(
            "SELECT * FROM transcriptions WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # ── NPCs ────────────────────────────────────────────────────────

    async def save_npc(
        self,
        campaign_id: str,
        name: str,
        description: str = "",
        first_seen_session: str = "",
    ) -> None:
        """Insert a new NPC record."""
        import uuid

        npc_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO npcs (id, campaign_id, name, description, first_seen_session) "
            "VALUES (?, ?, ?, ?, ?)",
            (npc_id, campaign_id, name, description, first_seen_session),
        )
        await self.conn.commit()

    async def get_npcs(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all NPCs for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? ORDER BY name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def npc_exists(self, campaign_id: str, name: str) -> bool:
        """Check if an NPC with the given name already exists in a campaign."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM npcs WHERE campaign_id = ? AND name = ? LIMIT 1",
            (campaign_id, name),
        )
        return await cursor.fetchone() is not None

    # ── Questions ──────────────────────────────────────────────────

    async def save_question(
        self, session_id: str, question: str
    ) -> int:
        """Save a question from the summarizer."""
        cursor = await self.conn.execute(
            "INSERT INTO questions (session_id, question, status) VALUES (?, ?, ?)",
            (session_id, question, "pending"),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def answer_question(
        self, question_id: int, answer: str
    ) -> None:
        """Answer a pending question."""
        await self.conn.execute(
            "UPDATE questions SET answer = ?, answered_at = ?, status = ? WHERE id = ?",
            (answer, time.time(), "answered", question_id),
        )
        await self.conn.commit()

    async def get_pending_questions(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Get all pending questions for a session."""
        cursor = await self.conn.execute(
            "SELECT * FROM questions WHERE session_id = ? AND status = 'pending'",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_answered_unprocessed_questions(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Get questions that have been answered but not yet processed by the summarizer."""
        cursor = await self.conn.execute(
            "SELECT * FROM questions WHERE session_id = ? AND status = 'answered'",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def mark_questions_processed(self, question_ids: list[int]) -> None:
        """Mark answered questions as processed after the summarizer has consumed them."""
        if not question_ids:
            return
        placeholders = ",".join("?" for _ in question_ids)
        await self.conn.execute(
            f"UPDATE questions SET status = 'processed' WHERE id IN ({placeholders})",
            question_ids,
        )
        await self.conn.commit()
