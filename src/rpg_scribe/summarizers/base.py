"""Abstract base class for all summarizers."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.core.models import CampaignContext, SummarizerConfig

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionEntry:
    """A single transcription stored in the buffer."""

    speaker_id: str
    speaker_name: str
    text: str
    timestamp: float


class BaseSummarizer(ABC):
    """Interface that any summarizer must implement.

    A summarizer receives TranscriptionEvent from the event bus,
    accumulates context, and periodically generates/updates summaries
    which are published as SummaryUpdateEvent.
    """

    def __init__(
        self,
        event_bus: EventBus,
        config: SummarizerConfig,
        campaign: CampaignContext,
    ) -> None:
        self.event_bus = event_bus
        self.config = config
        self.campaign = campaign

        self._session_id: str = ""
        self._session_summary: str = ""
        self._campaign_summary: str = campaign.campaign_summary

        # Buffer of transcriptions pending summarization
        self._pending: list[TranscriptionEntry] = []
        self._last_update_time: float = 0.0

    @abstractmethod
    async def process_transcription(self, event: TranscriptionEvent) -> None:
        """Process a new transcription and decide whether to trigger an update."""
        ...

    @abstractmethod
    async def get_session_summary(self) -> str:
        """Return the current session summary."""
        ...

    @abstractmethod
    async def get_campaign_summary(self) -> str:
        """Return the accumulated campaign summary."""
        ...

    @abstractmethod
    async def finalize_session(self) -> str:
        """Generate the final polished session summary and update the campaign summary."""
        ...

    async def start(self, session_id: str) -> None:
        """Subscribe to the event bus and start processing transcriptions."""
        self._session_id = session_id
        self._session_summary = ""
        self._pending.clear()
        self._last_update_time = time.time()
        self.event_bus.subscribe(TranscriptionEvent, self._handle_transcription)
        await self.event_bus.publish(
            SystemStatusEvent(
                component="summarizer",
                status="running",
                message=f"Summarizer started ({type(self).__name__})",
            )
        )
        logger.info("%s started for session %s", type(self).__name__, session_id)

    async def stop(self) -> None:
        """Unsubscribe from the event bus."""
        self.event_bus.unsubscribe(TranscriptionEvent, self._handle_transcription)
        await self.event_bus.publish(
            SystemStatusEvent(
                component="summarizer",
                status="idle",
                message="Summarizer stopped",
            )
        )
        logger.info("%s stopped", type(self).__name__)

    async def _handle_transcription(self, event: TranscriptionEvent) -> None:
        """Handle a TranscriptionEvent: buffer it and maybe trigger update."""
        if event.is_partial:
            return  # Skip partial transcriptions

        if event.session_id != self._session_id:
            return  # Ignore events from other sessions

        try:
            await self.process_transcription(event)
        except Exception as exc:
            logger.error("Summarizer error processing transcription: %s", exc)
            await self.event_bus.publish(
                SystemStatusEvent(
                    component="summarizer",
                    status="error",
                    message=f"Summarizer error: {exc}",
                )
            )

    def _should_update(self) -> bool:
        """Check whether we should trigger a summary update."""
        if not self._pending:
            return False
        if len(self._pending) >= self.config.max_pending_transcriptions:
            return True
        elapsed = time.time() - self._last_update_time
        if elapsed >= self.config.update_interval_s and len(self._pending) > 0:
            return True
        return False

    async def _publish_summary(self, update_type: str = "incremental") -> None:
        """Publish a SummaryUpdateEvent to the bus."""
        event = SummaryUpdateEvent(
            session_id=self._session_id,
            session_summary=self._session_summary,
            campaign_summary=self._campaign_summary,
            last_updated=time.time(),
            update_type=update_type,
        )
        await self.event_bus.publish(event)
