"""Session lifecycle business logic."""
from __future__ import annotations

import logging

from rpg_scribe.core.database.repositories.session_repo import SessionRepository
from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository,
        transcription_repo: TranscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self._sessions = session_repo
        self._transcriptions = transcription_repo
        self._event_bus = event_bus

    async def merge(self, source_id: str, target_id: str) -> dict:
        """Merge source session into target."""
        await self._sessions.merge_sessions(source_id, target_id)
        return {"ok": True, "target_id": target_id}

    async def finalize(self, session_id: str) -> None:
        """Mark session as ended."""
        await self._sessions.end_session(session_id)
