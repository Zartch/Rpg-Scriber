"""End-to-end integration test for the RPG Scribe pipeline.

Tests the full event flow: AudioChunkEvent → TranscriptionEvent → SummaryUpdateEvent
through the event bus, verifying that all components communicate correctly.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpg_scribe.config import AppConfig, load_app_config
from rpg_scribe.core.database import Database
from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import (
    AudioChunkEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
from rpg_scribe.core.models import (
    CampaignContext,
    ListenerConfig,
    PlayerInfo,
    SummarizerConfig,
    TranscriberConfig,
)
from rpg_scribe.summarizers.base import BaseSummarizer
from rpg_scribe.transcribers.base import BaseTranscriber


class FakeTranscriber(BaseTranscriber):
    """A fake transcriber that returns fixed text for testing."""

    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        return TranscriptionEvent(
            session_id=event.session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=f"[Transcribed from {event.speaker_name}]",
            timestamp=event.timestamp,
            confidence=0.99,
            is_partial=False,
        )


class FakeSummarizer(BaseSummarizer):
    """A fake summarizer that concatenates transcriptions."""

    async def process_transcription(self, event: TranscriptionEvent) -> None:
        from rpg_scribe.summarizers.base import TranscriptionEntry

        self._pending.append(
            TranscriptionEntry(
                speaker_id=event.speaker_id,
                speaker_name=event.speaker_name,
                text=event.text,
                timestamp=event.timestamp,
            )
        )
        if self._should_update():
            lines = [f"{e.speaker_name}: {e.text}" for e in self._pending]
            self._session_summary += "\n".join(lines) + "\n"
            self._pending.clear()
            self._last_update_time = time.time()
            await self._publish_summary("incremental")

    async def get_session_summary(self) -> str:
        return self._session_summary

    async def get_campaign_summary(self) -> str:
        return self._campaign_summary

    async def finalize_session(self) -> str:
        if self._pending:
            lines = [f"{e.speaker_name}: {e.text}" for e in self._pending]
            self._session_summary += "\n".join(lines) + "\n"
            self._pending.clear()
        await self._publish_summary("final")
        return self._session_summary


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def campaign() -> CampaignContext:
    return CampaignContext(
        campaign_id="test-campaign",
        name="Integration Test Campaign",
        game_system="Test System",
        language="en",
        players=[
            PlayerInfo(
                discord_id="111",
                discord_name="Alice",
                character_name="Aria",
            ),
            PlayerInfo(
                discord_id="222",
                discord_name="Bob",
                character_name="Brom",
            ),
        ],
        speaker_map={"111": "Aria", "222": "Brom"},
    )


class TestFullPipelineIntegration:
    """Test the complete audio→transcription→summary pipeline."""

    async def test_audio_to_summary_pipeline(
        self, event_bus: EventBus, campaign: CampaignContext
    ) -> None:
        """Publish audio chunks and verify summaries are produced."""
        collected_summaries: list[SummaryUpdateEvent] = []
        collected_statuses: list[SystemStatusEvent] = []

        async def capture_summary(event: SummaryUpdateEvent) -> None:
            collected_summaries.append(event)

        async def capture_status(event: SystemStatusEvent) -> None:
            collected_statuses.append(event)

        event_bus.subscribe(SummaryUpdateEvent, capture_summary)
        event_bus.subscribe(SystemStatusEvent, capture_status)

        # Set up transcriber
        transcriber_config = TranscriberConfig()
        transcriber = FakeTranscriber(event_bus, transcriber_config)
        await transcriber.start()

        # Set up summarizer with low thresholds for testing
        summarizer_config = SummarizerConfig(
            max_pending_transcriptions=2,
            update_interval_s=0.1,
        )
        summarizer = FakeSummarizer(event_bus, summarizer_config, campaign)
        await summarizer.start("test-session")

        # Simulate audio chunks
        for i, (speaker_id, name) in enumerate(
            [("111", "Alice"), ("222", "Bob"), ("111", "Alice")]
        ):
            chunk = AudioChunkEvent(
                session_id="test-session",
                speaker_id=speaker_id,
                speaker_name=name,
                audio_data=b"\x00" * 1600,
                timestamp=1000.0 + i,
                duration_ms=100,
                source="test",
            )
            await event_bus.publish(chunk)

        # Wait for async processing
        await asyncio.sleep(0.1)

        # Verify transcriptions were produced (system status events show components running)
        running_statuses = [
            s for s in collected_statuses if s.status == "running"
        ]
        assert len(running_statuses) >= 2  # transcriber + summarizer

        # Verify summary was produced (2 transcriptions trigger update)
        assert len(collected_summaries) >= 1
        summary_text = collected_summaries[0].session_summary
        assert "Transcribed from" in summary_text

        # Finalize
        final = await summarizer.finalize_session()
        assert "Transcribed from" in final

        # Cleanup
        await transcriber.stop()
        await summarizer.stop()

    async def test_event_bus_isolation(self, event_bus: EventBus) -> None:
        """Verify that event types are properly isolated."""
        transcription_count = 0
        summary_count = 0

        async def on_transcription(event: TranscriptionEvent) -> None:
            nonlocal transcription_count
            transcription_count += 1

        async def on_summary(event: SummaryUpdateEvent) -> None:
            nonlocal summary_count
            summary_count += 1

        event_bus.subscribe(TranscriptionEvent, on_transcription)
        event_bus.subscribe(SummaryUpdateEvent, on_summary)

        # Publish only a TranscriptionEvent
        await event_bus.publish(
            TranscriptionEvent(
                session_id="s1",
                speaker_id="1",
                speaker_name="Test",
                text="Hello",
                timestamp=1.0,
                confidence=0.9,
                is_partial=False,
            )
        )

        assert transcription_count == 1
        assert summary_count == 0

    async def test_error_in_handler_doesnt_break_others(
        self, event_bus: EventBus
    ) -> None:
        """An error in one handler should not prevent other handlers."""
        results: list[str] = []

        async def failing_handler(event: TranscriptionEvent) -> None:
            raise RuntimeError("I failed!")

        async def working_handler(event: TranscriptionEvent) -> None:
            results.append("success")

        event_bus.subscribe(TranscriptionEvent, failing_handler)
        event_bus.subscribe(TranscriptionEvent, working_handler)

        await event_bus.publish(
            TranscriptionEvent(
                session_id="s1",
                speaker_id="1",
                speaker_name="Test",
                text="Hello",
                timestamp=1.0,
                confidence=0.9,
                is_partial=False,
            )
        )

        assert results == ["success"]


class TestDatabaseIntegration:
    """Test database integration with the event pipeline."""

    async def test_transcription_persistence(self, tmp_path) -> None:
        """Test that transcriptions flow through the bus to the database."""
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.upsert_campaign(campaign_id="c1", name="Test")
        await db.create_session("s1", "c1")

        event_bus = EventBus()

        async def persist(event: TranscriptionEvent) -> None:
            if not event.is_partial:
                await db.save_transcription(
                    session_id=event.session_id,
                    speaker_id=event.speaker_id,
                    speaker_name=event.speaker_name,
                    text=event.text,
                    timestamp=event.timestamp,
                    confidence=event.confidence,
                )

        event_bus.subscribe(TranscriptionEvent, persist)

        # Publish transcription events
        for i in range(5):
            await event_bus.publish(
                TranscriptionEvent(
                    session_id="s1",
                    speaker_id="1",
                    speaker_name="Test",
                    text=f"Message {i}",
                    timestamp=1000.0 + i,
                    confidence=0.9,
                    is_partial=False,
                )
            )

        rows = await db.get_transcriptions("s1")
        assert len(rows) == 5
        assert rows[0]["text"] == "Message 0"
        assert rows[4]["text"] == "Message 4"

        await db.close()

    async def test_session_lifecycle_with_db(self, tmp_path) -> None:
        """Test full session lifecycle with database."""
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.upsert_campaign(campaign_id="c1", name="Test")

        # Start session
        await db.create_session("s1", "c1")
        session = await db.get_session("s1")
        assert session is not None
        assert session["status"] == "active"

        # Add transcriptions
        for i in range(3):
            await db.save_transcription(
                "s1", "1", "Alice", f"Line {i}", 1000.0 + i, 0.9
            )

        # End session
        await db.end_session("s1", "The party defeated the dragon.")
        session = await db.get_session("s1")
        assert session["status"] == "completed"
        assert "dragon" in session["session_summary"]

        # List sessions
        sessions = await db.list_sessions("c1")
        assert len(sessions) == 1

        await db.close()
