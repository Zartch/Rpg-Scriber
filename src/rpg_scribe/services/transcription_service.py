"""Transcription business logic: persist, word replacements."""
from __future__ import annotations

import logging
import re
from typing import Any

from rpg_scribe.core.database.repositories.transcription_repo import TranscriptionRepository
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import TranscriptionEvent

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(
        self,
        transcription_repo: TranscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self._repo = transcription_repo
        self._event_bus = event_bus
        self._word_replacements: list[tuple[re.Pattern, str]] = []

    async def reload_replacements(self, campaign_id: str) -> None:
        """Load word replacements from DB into memory."""
        rows = await self._repo.get_word_replacements(campaign_id)
        self._word_replacements = [
            (re.compile(re.escape(r["original_word"]), re.IGNORECASE), r["replacement_word"])
            for r in rows
        ]

    def apply_replacements(self, text: str) -> str:
        """Apply word replacements to text."""
        for pattern, replacement in self._word_replacements:
            text = pattern.sub(replacement, text)
        return text

    async def persist(
        self,
        event: TranscriptionEvent,
        campaign_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Persist transcription to DB, apply word replacements, return data dict."""
        text = self.apply_replacements(event.text) if self._word_replacements else event.text
        original_text = event.text if text != event.text else None

        transcription_id = await self._repo.save_transcription(
            session_id=session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=text,
            timestamp=event.timestamp,
            confidence=event.confidence,
            is_ingame=event.is_ingame,
        )

        return {
            "id": transcription_id,
            "speaker_id": event.speaker_id,
            "speaker_name": event.speaker_name,
            "text": text,
            "original_text": original_text,
            "timestamp": event.timestamp,
            "is_ingame": event.is_ingame,
        }
