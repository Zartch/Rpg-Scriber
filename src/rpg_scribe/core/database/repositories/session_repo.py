"""SessionRepository — session CRUD extracted from Database."""

from __future__ import annotations

import time
from typing import Any


class SessionRepository:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    async def create_session(self, session_id: str, campaign_id: str) -> None:
        """Create a new session record."""
        await self.conn.execute(
            "INSERT INTO sessions (id, campaign_id, started_at, status) VALUES (?, ?, ?, ?)",
            (session_id, campaign_id, time.time(), "active"),
        )
        await self.conn.commit()

    async def end_session(
        self, session_id: str, summary: str = "", chronology: str = ""
    ) -> None:
        """Mark a session as completed."""
        await self.conn.execute(
            "UPDATE sessions SET ended_at = ?, session_summary = ?, session_chronology = ?, status = ? WHERE id = ?",
            (time.time(), summary, chronology, "completed", session_id),
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
            "SELECT * FROM sessions WHERE campaign_id = ? "
            "AND (merged_into IS NULL OR merged_into = '') "
            "ORDER BY started_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_all_sessions(self) -> list[dict[str, Any]]:
        """List all sessions across all campaigns, ordered by date descending."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions "
            "WHERE (merged_into IS NULL OR merged_into = '') "
            "ORDER BY started_at DESC",
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_uncategorized_sessions(self) -> list[dict[str, Any]]:
        """List sessions without campaign assignment."""
        cursor = await self.conn.execute(
            "SELECT * FROM sessions "
            "WHERE (campaign_id IS NULL OR campaign_id = '') "
            "AND (merged_into IS NULL OR merged_into = '') "
            "ORDER BY started_at DESC",
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def merge_sessions(
        self,
        source_id: str,
        target_id: str,
    ) -> None:
        """Merge one session into another, combining transcriptions and summaries.

        The source session is tombstoned (merged_into = target_id).
        Transcriptions and questions are reassigned to the target.
        Summaries are concatenated.  Timestamps are expanded to cover both.
        """
        if not source_id or not target_id or source_id == target_id:
            raise ValueError("source_id and target_id must be different")

        cursor = await self.conn.execute(
            "SELECT * FROM sessions WHERE id = ? LIMIT 1", (source_id,)
        )
        source_row = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT * FROM sessions WHERE id = ? LIMIT 1", (target_id,)
        )
        target_row = await cursor.fetchone()
        if source_row is None or target_row is None:
            raise ValueError("Session source or target not found")

        # Both must belong to the same campaign (or both NULL)
        source_campaign = source_row["campaign_id"]
        target_campaign = target_row["campaign_id"]
        if source_campaign != target_campaign:
            raise ValueError("Cannot merge sessions from different campaigns")

        # Neither can be active
        if source_row["status"] == "active":
            raise ValueError("Cannot merge an active session (source)")
        if target_row["status"] == "active":
            raise ValueError("Cannot merge an active session (target)")

        # Neither can already be merged
        if source_row["merged_into"]:
            raise ValueError("Source session is already merged")
        if target_row["merged_into"]:
            raise ValueError("Target session is already merged")

        # Expand target timestamps to cover both sessions
        source_start = source_row["started_at"]
        target_start = target_row["started_at"]
        source_end = source_row["ended_at"]
        target_end = target_row["ended_at"]

        new_start = (
            min(t for t in (source_start, target_start) if t is not None)
            if (source_start is not None or target_start is not None)
            else None
        )
        new_end = (
            max(t for t in (source_end, target_end) if t is not None)
            if (source_end is not None or target_end is not None)
            else None
        )

        await self.conn.execute(
            "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
            (new_start, new_end, target_id),
        )

        # Reassign transcriptions from source to target
        await self.conn.execute(
            "UPDATE transcriptions SET session_id = ? WHERE session_id = ?",
            (target_id, source_id),
        )

        # Reassign questions from source to target
        await self.conn.execute(
            "UPDATE questions SET session_id = ? WHERE session_id = ?",
            (target_id, source_id),
        )

        # Concatenate summaries
        target_summary = self._merge_text_fields(
            str(target_row["session_summary"] or ""),
            str(source_row["session_summary"] or ""),
        )
        target_chronology = self._merge_text_fields(
            str(target_row["session_chronology"] or ""),
            str(source_row["session_chronology"] or ""),
        )
        await self.conn.execute(
            "UPDATE sessions SET session_summary = ?, session_chronology = ? WHERE id = ?",
            (target_summary, target_chronology, target_id),
        )

        # Tombstone source session
        await self.conn.execute(
            "UPDATE sessions SET merged_into = ? WHERE id = ?",
            (target_id, source_id),
        )

        # Update campaign_summaries that referenced the source session
        await self.conn.execute(
            "UPDATE campaign_summaries SET trigger_session_id = ? "
            "WHERE trigger_session_id = ?",
            (target_id, source_id),
        )

        await self.conn.commit()

    async def update_session_summary(self, session_id: str, summary: str) -> bool:
        """Update the session summary text. Returns True if updated."""
        cursor = await self.conn.execute(
            "UPDATE sessions SET session_summary = ? WHERE id = ?",
            (summary, session_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def update_session_chronology(self, session_id: str, chronology: str) -> bool:
        """Update the session chronology text. Returns True if updated."""
        cursor = await self.conn.execute(
            "UPDATE sessions SET session_chronology = ? WHERE id = ?",
            (chronology, session_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def update_session_title(self, session_id: str, title: str) -> bool:
        """Update the session title. Returns True if a row was updated."""
        cursor = await self.conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def update_session_status(self, session_id: str, status: str) -> bool:
        """Force-set session status. Returns True if a row was updated.

        Only 'active' and 'completed' are valid values.
        Raises ValueError for invalid status.
        """
        if status not in ("active", "completed"):
            raise ValueError(
                f"status must be 'active' or 'completed', got {status!r}"
            )
        cursor = await self.conn.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (status, session_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_previous_session_chronology(
        self, campaign_id: str, current_session_id: str
    ) -> str:
        """Return the chronology of the most recently completed session that ended
        before *current_session_id* within *campaign_id*.

        When *current_session_id* has no ``ended_at`` (still active), the filter
        is skipped and the most recently completed session is returned instead.

        Returns "" if no qualifying session exists or its chronology is empty.
        """
        cursor = await self.conn.execute(
            """
            SELECT session_chronology FROM sessions
            WHERE campaign_id = ?
              AND id != ?
              AND status = 'completed'
              AND (merged_into IS NULL OR merged_into = '')
              AND ended_at IS NOT NULL
              AND (
                  (SELECT ended_at FROM sessions WHERE id = ?) IS NULL
                  OR ended_at < (SELECT ended_at FROM sessions WHERE id = ?)
              )
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            (campaign_id, current_session_id, current_session_id, current_session_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return ""
        return row["session_chronology"] or ""

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
