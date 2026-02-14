"""Abstract base class for all transcribers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent, SystemStatusEvent
from rpg_scribe.core.models import TranscriberConfig

logger = logging.getLogger(__name__)


class BaseTranscriber(ABC):
    """Interface that any transcriber must implement.

    A transcriber receives AudioChunkEvent from the event bus,
    converts audio to text, and publishes TranscriptionEvent.
    """

    def __init__(self, event_bus: EventBus, config: TranscriberConfig) -> None:
        self.event_bus = event_bus
        self.config = config

    @abstractmethod
    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        """Transcribe a single audio chunk and return a TranscriptionEvent."""
        ...

    async def start(self) -> None:
        """Subscribe to the event bus and start processing audio chunks."""
        self.event_bus.subscribe(AudioChunkEvent, self._handle_audio)
        await self.event_bus.publish(
            SystemStatusEvent(
                component="transcriber",
                status="running",
                message=f"Transcriber started ({type(self).__name__})",
            )
        )
        logger.info("%s started and subscribed to AudioChunkEvent", type(self).__name__)

    async def stop(self) -> None:
        """Unsubscribe from the event bus."""
        self.event_bus.unsubscribe(AudioChunkEvent, self._handle_audio)
        await self.event_bus.publish(
            SystemStatusEvent(
                component="transcriber",
                status="idle",
                message="Transcriber stopped",
            )
        )
        logger.info("%s stopped", type(self).__name__)

    async def _handle_audio(self, event: AudioChunkEvent) -> None:
        """Handle an AudioChunkEvent: transcribe and publish result."""
        try:
            result = await self.transcribe(event)
            if result.text.strip():
                await self.event_bus.publish(result)
        except Exception as exc:
            logger.error(
                "Transcription failed for chunk from %s: %s",
                event.speaker_name,
                exc,
            )
            await self.event_bus.publish(
                SystemStatusEvent(
                    component="transcriber",
                    status="error",
                    message=f"Transcription error: {exc}",
                )
            )
