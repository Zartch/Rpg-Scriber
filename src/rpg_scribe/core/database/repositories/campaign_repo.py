"""Campaign data access."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from rpg_scribe.core.database.connection import Database

logger = logging.getLogger(__name__)


class CampaignRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def conn(self):
        return self._db.conn

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
                campaign_id,
                name,
                game_system,
                language,
                description,
                campaign_summary,
                json.dumps(speaker_map or {}),
                dm_speaker_id,
                custom_instructions,
                now,
                now,
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

    async def update_campaign_summary(self, campaign_id: str, summary: str) -> None:
        """Update the accumulated campaign summary (latest-only cache)."""
        await self.conn.execute(
            "UPDATE campaigns SET campaign_summary = ?, updated_at = ? WHERE id = ?",
            (summary, time.time(), campaign_id),
        )
        await self.conn.commit()

    # ── Campaign summaries (history) ───────────────────────────────

    async def save_campaign_summary(
        self,
        campaign_id: str,
        content: str,
        trigger_session_id: str = "",
        session_count: int = 0,
    ) -> str:
        """Persist a new campaign summary snapshot and return its ID."""
        import uuid

        summary_id = str(uuid.uuid4())
        now = time.time()
        await self.conn.execute(
            "INSERT INTO campaign_summaries "
            "(id, campaign_id, content, trigger_session_id, session_count, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (summary_id, campaign_id, content, trigger_session_id, session_count, now),
        )
        await self.conn.commit()
        # Also refresh the latest-cache column on the campaign row
        await self.update_campaign_summary(campaign_id, content)
        return summary_id

    async def list_campaign_summaries(self, campaign_id: str) -> list[dict[str, Any]]:
        """Return all campaign summaries for a campaign, newest first."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_summaries WHERE campaign_id = ? "
            "ORDER BY generated_at DESC",
            (campaign_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_campaign_summary_by_id(
        self, summary_id: str
    ) -> dict[str, Any] | None:
        """Retrieve a single campaign summary by its UUID."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_summaries WHERE id = ?", (summary_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_latest_campaign_summary(
        self, campaign_id: str
    ) -> dict[str, Any] | None:
        """Return the most recently generated campaign summary."""
        cursor = await self.conn.execute(
            "SELECT * FROM campaign_summaries WHERE campaign_id = ? "
            "ORDER BY generated_at DESC LIMIT 1",
            (campaign_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
