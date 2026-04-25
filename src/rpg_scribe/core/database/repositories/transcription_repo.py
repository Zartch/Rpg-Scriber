"""TranscriptionRepository — transcription CRUD extracted from Database."""

from __future__ import annotations

import time
from typing import Any


class TranscriptionRepository:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

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
            (
                session_id,
                speaker_id,
                speaker_name,
                text,
                timestamp,
                confidence,
                is_ingame,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_transcriptions(self, session_id: str) -> list[dict[str, Any]]:
        """Get all transcriptions for a session, ordered by timestamp."""
        cursor = await self.conn.execute(
            "SELECT * FROM transcriptions WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def update_transcription_text(
        self, transcription_id: int, new_text: str
    ) -> bool:
        """Update the text of a transcription. Returns True if a row was updated."""
        cursor = await self.conn.execute(
            "UPDATE transcriptions SET text = ? WHERE id = ?",
            (new_text, transcription_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_transcription(self, transcription_id: int) -> bool:
        """Delete a transcription by ID. Returns True if a row was deleted."""
        cursor = await self.conn.execute(
            "DELETE FROM transcriptions WHERE id = ?",
            (transcription_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_transcription_by_id(self, transcription_id: int) -> dict[str, Any] | None:
        """Get a single transcription by ID. Returns None if not found."""
        cursor = await self.conn.execute(
            "SELECT * FROM transcriptions WHERE id = ?",
            (transcription_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_transcription_is_ingame(
        self, transcription_id: int, is_ingame: bool
    ) -> bool:
        """Toggle the is_ingame flag. Returns True if a row was updated."""
        cursor = await self.conn.execute(
            "UPDATE transcriptions SET is_ingame = ? WHERE id = ?",
            (is_ingame, transcription_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def save_transcription_edit(
        self,
        transcription_id: int,
        original_word: str,
        new_word: str,
        position: int,
    ) -> int:
        """Record a word-level edit for audit history. Returns the edit ID."""
        cursor = await self.conn.execute(
            "INSERT INTO transcription_edits "
            "(transcription_id, original_word, new_word, word_position, edited_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (transcription_id, original_word, new_word, position, time.time()),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_transcription_edits(
        self, transcription_id: int
    ) -> list[dict[str, Any]]:
        """Get all edits for a transcription, ordered by time."""
        cursor = await self.conn.execute(
            "SELECT * FROM transcription_edits WHERE transcription_id = ? "
            "ORDER BY edited_at",
            (transcription_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def save_word_replacement(
        self, campaign_id: str, original: str, replacement: str
    ) -> int:
        """Create a word replacement rule. Returns the rule ID."""
        cursor = await self.conn.execute(
            "INSERT INTO word_replacements "
            "(campaign_id, original_word, replacement_word, created_at) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, original, replacement, time.time()),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_word_replacements(self, campaign_id: str) -> list[dict[str, Any]]:
        """Get all word replacement rules for a campaign."""
        cursor = await self.conn.execute(
            "SELECT * FROM word_replacements WHERE campaign_id = ? "
            "ORDER BY created_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def delete_word_replacement(self, replacement_id: int) -> bool:
        """Delete a word replacement rule. Returns True if deleted."""
        cursor = await self.conn.execute(
            "DELETE FROM word_replacements WHERE id = ?", (replacement_id,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def apply_word_replacements(self, campaign_id: str) -> int:
        """Apply all replacement rules retroactively to existing transcriptions.

        Returns the number of transcriptions modified.
        """
        rules = await self.get_word_replacements(campaign_id)
        if not rules:
            return 0
        modified = 0
        for rule in rules:
            cursor = await self.conn.execute(
                "UPDATE transcriptions SET text = REPLACE(text, ?, ?) "
                "WHERE session_id IN (SELECT id FROM sessions WHERE campaign_id = ?) "
                "AND text LIKE '%' || ? || '%'",
                (
                    rule["original_word"],
                    rule["replacement_word"],
                    campaign_id,
                    rule["original_word"],
                ),
            )
            modified += cursor.rowcount
        await self.conn.commit()
        return modified
