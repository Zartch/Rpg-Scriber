"""SQLite async database wrapper for RPG Scribe.

Implements the schema defined in architecture section 8.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
import time
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

def normalize_relationship_type_label(value: str) -> str:
    """Normalize a relationship type label for matching/deduplication."""
    text = value.strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"^(es|era|fue|son|esta|estaba|estuvieron)\s+", "", text)
    text = re.sub(r"^(el|la|los|las|un|una)\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "relacion"


def _relation_similarity(a: str, b: str) -> float:
    """Compute a robust fuzzy similarity between canonical labels."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        seq = max(seq, min(len(a), len(b)) / max(len(a), len(b)))
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
        return max(seq, jaccard)
    return seq

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

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    description TEXT,
    first_seen_session TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    question TEXT,
    answer TEXT,
    answered_at REAL,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS relationship_types (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    canonical_key TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    aliases_json TEXT,
    usage_count INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL,
    UNIQUE (campaign_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS character_relationships (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    type_key TEXT NOT NULL,
    type_label TEXT NOT NULL,
    notes TEXT,
    created_at REAL,
    updated_at REAL,
    UNIQUE (campaign_id, source_key, target_key, type_key)
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

    # -- Campaigns --------------------------------------------------

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


    async def list_campaigns(self) -> list[dict[str, Any]]:
        """List all campaigns ordered by most recently updated."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaigns ORDER BY updated_at DESC, created_at DESC"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for row in rows:
            if row.get("speaker_map"):
                try:
                    row["speaker_map"] = json.loads(row["speaker_map"])
                except Exception:
                    row["speaker_map"] = {}
        return rows

    async def update_campaign_summary(
        self, campaign_id: str, summary: str
    ) -> None:
        """Update the accumulated campaign summary."""
        await self.conn.execute(
            "UPDATE campaigns SET campaign_summary = ?, updated_at = ? WHERE id = ?",
            (summary, time.time(), campaign_id),
        )
        await self.conn.commit()

    # -- Sessions ---------------------------------------------------

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

    async def list_all_sessions(self) -> list[dict[str, Any]]:
        """List all sessions across all campaigns, ordered by date descending."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC",
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_uncategorized_sessions(self) -> list[dict[str, Any]]:
        """List sessions without campaign assignment."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions "
            "WHERE campaign_id IS NULL OR campaign_id = '' "
            "ORDER BY started_at DESC",
        )
        return [dict(r) for r in await cursor.fetchall()]

    # -- Transcriptions ---------------------------------------------

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

    # -- NPCs --------------------------------------------------------

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

    async def update_npc(self, npc_id: str, **fields: Any) -> None:
        """Update specific fields of an NPC record.

        Accepted fields: name, description.
        """
        allowed = {"name", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [npc_id]
        await self.conn.execute(
            f"UPDATE npcs SET {set_clause} WHERE id = ?", values
        )
        await self.conn.commit()

    # ── Locations ────────────────────────────────────────────────────

    async def save_location(
        self,
        campaign_id: str,
        name: str,
        description: str = "",
        first_seen_session: str = "",
    ) -> None:
        """Insert a new location record."""
        import uuid

        loc_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO locations (id, campaign_id, name, description, first_seen_session) "
            "VALUES (?, ?, ?, ?, ?)",
            (loc_id, campaign_id, name, description, first_seen_session),
        )
        await self.conn.commit()

    async def get_locations(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all locations for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM locations WHERE campaign_id = ? ORDER BY name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def location_exists(self, campaign_id: str, name: str) -> bool:
        """Check if a location with the given name already exists in a campaign.

        Uses case-insensitive comparison so "el bosque negro" and "El Bosque Negro"
        are treated as the same location.
        """
        cursor = await self.conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND lower(name) = lower(?) LIMIT 1",
            (campaign_id, name),
        )
        return await cursor.fetchone() is not None

    async def update_location(self, location_id: str, **fields: Any) -> None:
        """Update specific fields of a location record.

        Accepted fields: name, description.
        """
        allowed = {"name", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [location_id]
        await self.conn.execute(
            f"UPDATE locations SET {set_clause} WHERE id = ?", values
        )
        await self.conn.commit()

    # ── Players ─────────────────────────────────────────────────────

    async def save_player(
        self,
        campaign_id: str,
        discord_id: str,
        discord_name: str,
        character_name: str,
        character_description: str = "",
    ) -> str:
        """Insert a new player record and return its ID."""
        import uuid

        player_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO players (id, campaign_id, discord_id, discord_name, "
            "character_name, character_description) VALUES (?, ?, ?, ?, ?, ?)",
            (player_id, campaign_id, discord_id, discord_name,
             character_name, character_description),
        )
        await self.conn.commit()
        return player_id

    async def get_players(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all players for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM players WHERE campaign_id = ? ORDER BY discord_name",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def player_exists(self, campaign_id: str, discord_id: str) -> bool:
        """Check if a player with the given discord_id already exists."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM players WHERE campaign_id = ? AND discord_id = ? LIMIT 1",
            (campaign_id, discord_id),
        )
        return await cursor.fetchone() is not None

    async def update_player(self, player_id: str, **fields: Any) -> None:
        """Update specific fields of a player record.

        Accepted fields: discord_name, character_name, character_description.
        """
        allowed = {"discord_name", "character_name", "character_description"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [player_id]
        await self.conn.execute(
            f"UPDATE players SET {set_clause} WHERE id = ?", values
        )
        await self.conn.commit()

    # -- Questions --------------------------------------------------

    async def get_relationship_types(self, campaign_id: str) -> list[dict[str, Any]]:
        """List known relationship types for a campaign thesaurus."""
        cursor = await self.conn.execute(
            "SELECT * FROM relationship_types WHERE campaign_id = ? "
            "ORDER BY usage_count DESC, label ASC",
            (campaign_id,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for row in rows:
            aliases = row.get("aliases_json") or "[]"
            try:
                row["aliases"] = json.loads(aliases)
            except Exception:
                row["aliases"] = []
        return rows

    async def resolve_relationship_type(
        self,
        campaign_id: str,
        relation_label: str,
        *,
        category: str = "general",
    ) -> dict[str, Any]:
        """Resolve or create a canonical relationship type with fuzzy dedupe."""
        raw_label = relation_label.strip()
        canonical = normalize_relationship_type_label(raw_label)
        existing = await self.get_relationship_types(campaign_id)

        for row in existing:
            if row.get("canonical_key", "") == canonical:
                return row

        best: dict[str, Any] | None = None
        best_score = 0.0
        for row in existing:
            key = str(row.get("canonical_key", ""))
            score = _relation_similarity(canonical, key)
            if score > best_score:
                best_score = score
                best = row

        if best is not None and best_score >= 0.88:
            aliases = list(best.get("aliases") or [])
            if raw_label and raw_label not in aliases:
                aliases.append(raw_label)
                await self.conn.execute(
                    "UPDATE relationship_types SET aliases_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted(set(aliases))), time.time(), best["id"]),
                )
                await self.conn.commit()
                best["aliases"] = sorted(set(aliases))
            return best

        import uuid

        type_id = str(uuid.uuid4())
        now = time.time()
        display_label = raw_label or canonical
        aliases = [raw_label] if raw_label and raw_label != display_label else []
        await self.conn.execute(
            "INSERT INTO relationship_types "
            "(id, campaign_id, canonical_key, label, category, aliases_json, usage_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                type_id,
                campaign_id,
                canonical,
                display_label,
                category or "general",
                json.dumps(aliases),
                now,
                now,
            ),
        )
        await self.conn.commit()
        return {
            "id": type_id,
            "campaign_id": campaign_id,
            "canonical_key": canonical,
            "label": display_label,
            "category": category or "general",
            "aliases": aliases,
            "usage_count": 0,
            "created_at": now,
            "updated_at": now,
        }

    async def save_character_relationship(
        self,
        campaign_id: str,
        source_key: str,
        target_key: str,
        relation_label: str,
        *,
        notes: str = "",
        category: str = "general",
    ) -> dict[str, Any]:
        """Create or update a typed relationship between two entities."""
        source = source_key.strip()
        target = target_key.strip()
        if not source or not target:
            raise ValueError("source_key and target_key are required")
        if source == target:
            raise ValueError("source and target cannot be the same entity")

        relation_type = await self.resolve_relationship_type(
            campaign_id,
            relation_label,
            category=category,
        )

        import uuid

        rel_id = str(uuid.uuid4())
        now = time.time()
        await self.conn.execute(
            "INSERT INTO character_relationships "
            "(id, campaign_id, source_key, target_key, type_key, type_label, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, source_key, target_key, type_key) DO UPDATE SET "
            "type_label=excluded.type_label, notes=excluded.notes, updated_at=excluded.updated_at",
            (
                rel_id,
                campaign_id,
                source,
                target,
                relation_type["canonical_key"],
                relation_type["label"],
                notes.strip(),
                now,
                now,
            ),
        )
        await self.conn.execute(
            "UPDATE relationship_types SET usage_count = ("
            "SELECT COUNT(*) FROM character_relationships "
            "WHERE campaign_id = ? AND type_key = ?"
            "), updated_at = ? "
            "WHERE campaign_id = ? AND canonical_key = ?",
            (
                campaign_id,
                relation_type["canonical_key"],
                now,
                campaign_id,
                relation_type["canonical_key"],
            ),
        )
        await self.conn.commit()

        cursor = await self.conn.execute(
            "SELECT r.*, t.category AS type_category "
            "FROM character_relationships r "
            "LEFT JOIN relationship_types t "
            "ON t.campaign_id = r.campaign_id AND t.canonical_key = r.type_key "
            "WHERE r.campaign_id = ? AND r.source_key = ? AND r.target_key = ? AND r.type_key = ?",
            (campaign_id, source, target, relation_type["canonical_key"]),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "campaign_id": campaign_id,
            "source_key": source,
            "target_key": target,
            "type_key": relation_type["canonical_key"],
            "type_label": relation_type["label"],
            "notes": notes.strip(),
            "type_category": relation_type.get("category", "general"),
        }
    async def get_character_relationships(self, campaign_id: str) -> list[dict[str, Any]]:
        """List character relationships for a campaign."""
        cursor = await self.conn.execute(
            "SELECT r.*, t.category AS type_category "
            "FROM character_relationships r "
            "LEFT JOIN relationship_types t "
            "ON t.campaign_id = r.campaign_id AND t.canonical_key = r.type_key "
            "WHERE r.campaign_id = ? ORDER BY r.updated_at DESC, r.created_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    async def rename_relationship_entity_key(
        self,
        campaign_id: str,
        old_key: str,
        new_key: str,
    ) -> None:
        """Rename an entity key in relationships (source and target sides)."""
        if not old_key or not new_key or old_key == new_key:
            return
        await self.conn.execute(
            "UPDATE character_relationships SET "
            "source_key = CASE WHEN source_key = ? THEN ? ELSE source_key END, "
            "target_key = CASE WHEN target_key = ? THEN ? ELSE target_key END, "
            "updated_at = ? "
            "WHERE campaign_id = ? AND (source_key = ? OR target_key = ?)",
            (old_key, new_key, old_key, new_key, time.time(), campaign_id, old_key, old_key),
        )
        await self.conn.commit()
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



