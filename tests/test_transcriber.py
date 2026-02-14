"""Tests for the transcriber modules."""

from __future__ import annotations

import asyncio
import io
import struct
import time
import wave
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent, SystemStatusEvent
from rpg_scribe.core.models import TranscriberConfig
from rpg_scribe.transcribers.base import BaseTranscriber
from rpg_scribe.transcribers.openai_transcriber import OpenAITranscriber, _pcm_to_wav_bytes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pcm(duration_s: float = 1.0, sample_rate: int = 48000) -> bytes:
    """Generate mono PCM16 data."""
    n_samples = int(sample_rate * duration_s)
    return struct.pack(f"<{n_samples}h", *([500] * n_samples))


def _make_audio_event(
    session_id: str = "test-session",
    speaker_id: str = "user1",
    speaker_name: str = "TestUser",
    duration_s: float = 1.0,
) -> AudioChunkEvent:
    pcm = _make_pcm(duration_s)
    return AudioChunkEvent(
        session_id=session_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        audio_data=pcm,
        timestamp=time.time(),
        duration_ms=int(duration_s * 1000),
        source="test",
    )


# ---------------------------------------------------------------------------
# Concrete test transcriber (for testing BaseTranscriber)
# ---------------------------------------------------------------------------

class MockTranscriber(BaseTranscriber):
    """Concrete transcriber that returns canned text."""

    def __init__(
        self,
        event_bus: EventBus,
        config: TranscriberConfig,
        response_text: str = "Hello world",
    ) -> None:
        super().__init__(event_bus, config)
        self.response_text = response_text
        self.transcribe_calls: list[AudioChunkEvent] = []

    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        self.transcribe_calls.append(event)
        return TranscriptionEvent(
            session_id=event.session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=self.response_text,
            timestamp=event.timestamp,
            confidence=0.99,
            is_partial=False,
        )


class FailingTranscriber(BaseTranscriber):
    """Transcriber that always raises."""

    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        raise RuntimeError("transcription failed")


# ---------------------------------------------------------------------------
# Tests: BaseTranscriber
# ---------------------------------------------------------------------------

class TestBaseTranscriber:
    @pytest.fixture
    def bus(self) -> EventBus:
        return EventBus()

    @pytest.fixture
    def config(self) -> TranscriberConfig:
        return TranscriberConfig()

    @pytest.mark.asyncio
    async def test_start_subscribes_to_audio_events(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = MockTranscriber(bus, config)
        await transcriber.start()

        received: list[TranscriptionEvent] = []

        async def handler(event: TranscriptionEvent) -> None:
            received.append(event)

        bus.subscribe(TranscriptionEvent, handler)

        audio_event = _make_audio_event()
        await bus.publish(audio_event)

        assert len(received) == 1
        assert received[0].text == "Hello world"
        assert received[0].speaker_id == "user1"

        await transcriber.stop()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = MockTranscriber(bus, config)
        await transcriber.start()
        await transcriber.stop()

        audio_event = _make_audio_event()
        await bus.publish(audio_event)

        assert len(transcriber.transcribe_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_text_not_published(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = MockTranscriber(bus, config, response_text="")
        await transcriber.start()

        received: list[TranscriptionEvent] = []

        async def handler(event: TranscriptionEvent) -> None:
            received.append(event)

        bus.subscribe(TranscriptionEvent, handler)

        await bus.publish(_make_audio_event())
        assert len(received) == 0

        await transcriber.stop()

    @pytest.mark.asyncio
    async def test_whitespace_only_text_not_published(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = MockTranscriber(bus, config, response_text="   \n  ")
        await transcriber.start()

        received: list[TranscriptionEvent] = []

        async def handler(event: TranscriptionEvent) -> None:
            received.append(event)

        bus.subscribe(TranscriptionEvent, handler)

        await bus.publish(_make_audio_event())
        assert len(received) == 0

        await transcriber.stop()

    @pytest.mark.asyncio
    async def test_transcription_error_publishes_status(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = FailingTranscriber(bus, config)
        await transcriber.start()

        statuses: list[SystemStatusEvent] = []

        async def handler(event: SystemStatusEvent) -> None:
            statuses.append(event)

        bus.subscribe(SystemStatusEvent, handler)

        await bus.publish(_make_audio_event())

        error_statuses = [s for s in statuses if s.status == "error"]
        assert len(error_statuses) == 1
        assert "transcription failed" in error_statuses[0].message.lower()

        await transcriber.stop()

    @pytest.mark.asyncio
    async def test_start_publishes_running_status(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        statuses: list[SystemStatusEvent] = []

        async def handler(event: SystemStatusEvent) -> None:
            statuses.append(event)

        bus.subscribe(SystemStatusEvent, handler)

        transcriber = MockTranscriber(bus, config)
        await transcriber.start()

        running = [s for s in statuses if s.status == "running"]
        assert len(running) == 1
        assert running[0].component == "transcriber"

        await transcriber.stop()

    @pytest.mark.asyncio
    async def test_stop_publishes_idle_status(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        statuses: list[SystemStatusEvent] = []

        async def handler(event: SystemStatusEvent) -> None:
            statuses.append(event)

        bus.subscribe(SystemStatusEvent, handler)

        transcriber = MockTranscriber(bus, config)
        await transcriber.start()
        await transcriber.stop()

        idle = [s for s in statuses if s.status == "idle"]
        assert len(idle) == 1

    @pytest.mark.asyncio
    async def test_multiple_events_processed_sequentially(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = MockTranscriber(bus, config, response_text="ok")
        await transcriber.start()

        received: list[TranscriptionEvent] = []

        async def handler(event: TranscriptionEvent) -> None:
            received.append(event)

        bus.subscribe(TranscriptionEvent, handler)

        for i in range(5):
            await bus.publish(
                _make_audio_event(speaker_id=f"user{i}", speaker_name=f"User{i}")
            )

        assert len(received) == 5
        assert len(transcriber.transcribe_calls) == 5

        await transcriber.stop()


# ---------------------------------------------------------------------------
# Tests: PCM to WAV conversion
# ---------------------------------------------------------------------------

class TestPcmToWav:
    def test_produces_valid_wav(self) -> None:
        pcm = _make_pcm(0.5)
        wav_data = _pcm_to_wav_bytes(pcm)

        # Should be parseable as WAV
        buf = io.BytesIO(wav_data)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 48000
            frames = wf.readframes(wf.getnframes())
            assert frames == pcm

    def test_empty_pcm(self) -> None:
        wav_data = _pcm_to_wav_bytes(b"")
        buf = io.BytesIO(wav_data)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 0


# ---------------------------------------------------------------------------
# Tests: OpenAITranscriber
# ---------------------------------------------------------------------------

class TestOpenAITranscriber:
    @pytest.fixture
    def config(self) -> TranscriberConfig:
        return TranscriberConfig(
            model="whisper-1",
            language="es",
            max_retries=2,
            retry_base_delay_s=0.01,
            prompt_hint="Nombres: Aelar, Rodrigo, DM",
        )

    @pytest.fixture
    def bus(self) -> EventBus:
        return EventBus()

    @pytest.mark.asyncio
    async def test_transcribe_calls_openai_api(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = OpenAITranscriber(bus, config)

        mock_response = MagicMock()
        mock_response.text = "El caballero avanza por el sendero."

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        transcriber._client = mock_client

        event = _make_audio_event()
        result = await transcriber.transcribe(event)

        assert result.text == "El caballero avanza por el sendero."
        assert result.speaker_id == "user1"
        assert result.session_id == "test-session"
        assert result.is_partial is False
        assert result.confidence > 0

        mock_client.audio.transcriptions.create.assert_called_once()
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["model"] == "whisper-1"
        assert call_kwargs["language"] == "es"
        assert call_kwargs["prompt"] == "Nombres: Aelar, Rodrigo, DM"

    @pytest.mark.asyncio
    async def test_cache_avoids_duplicate_calls(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = OpenAITranscriber(bus, config)

        mock_response = MagicMock()
        mock_response.text = "Texto cacheado."

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        transcriber._client = mock_client

        event = _make_audio_event()
        await transcriber.transcribe(event)
        await transcriber.transcribe(event)  # Same audio data

        # Only one API call should be made
        assert mock_client.audio.transcriptions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_api_failure(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = OpenAITranscriber(bus, config)

        mock_response = MagicMock()
        mock_response.text = "Recovered."

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=[
                RuntimeError("Network error"),
                RuntimeError("Timeout"),
                mock_response,  # Third attempt succeeds
            ]
        )
        transcriber._client = mock_client

        event = _make_audio_event()
        result = await transcriber.transcribe(event)

        assert result.text == "Recovered."
        assert mock_client.audio.transcriptions.create.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = OpenAITranscriber(bus, config)

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=RuntimeError("Persistent failure")
        )
        transcriber._client = mock_client

        event = _make_audio_event()
        with pytest.raises(RuntimeError, match="failed after"):
            await transcriber.transcribe(event)

        # max_retries=2 means 3 total attempts
        assert mock_client.audio.transcriptions.create.call_count == 3

    @pytest.mark.asyncio
    async def test_concurrency_limited_by_semaphore(
        self, bus: EventBus
    ) -> None:
        config = TranscriberConfig(
            max_concurrent_requests=2,
            retry_base_delay_s=0.01,
        )
        transcriber = OpenAITranscriber(bus, config)

        concurrent_count = 0
        max_concurrent = 0

        async def slow_create(**kwargs: Any) -> MagicMock:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            resp = MagicMock()
            resp.text = "ok"
            return resp

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = slow_create
        transcriber._client = mock_client

        events = [
            _make_audio_event(speaker_id=f"user{i}")
            for i in range(6)
        ]

        # Run all transcriptions concurrently
        await asyncio.gather(*(transcriber.transcribe(e) for e in events))

        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_prompt_hint_empty(self, bus: EventBus) -> None:
        config = TranscriberConfig(prompt_hint="")
        transcriber = OpenAITranscriber(bus, config)

        mock_response = MagicMock()
        mock_response.text = "Text."

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        transcriber._client = mock_client

        event = _make_audio_event()
        await transcriber.transcribe(event)

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert "prompt" not in call_kwargs

    @pytest.mark.asyncio
    async def test_stop_clears_cache(
        self, bus: EventBus, config: TranscriberConfig
    ) -> None:
        transcriber = OpenAITranscriber(bus, config)
        transcriber._cache["some_hash"] = "cached text"

        mock_client = MagicMock()
        transcriber._client = mock_client

        await transcriber.stop()
        assert len(transcriber._cache) == 0


# ---------------------------------------------------------------------------
# Tests: Full integration through event bus
# ---------------------------------------------------------------------------

class TestTranscriberEventBusIntegration:
    @pytest.mark.asyncio
    async def test_end_to_end_audio_to_transcription(self) -> None:
        """Audio event → transcriber → transcription event via event bus."""
        bus = EventBus()
        config = TranscriberConfig()
        transcriber = MockTranscriber(bus, config, response_text="Aelar desenvaina su espada.")
        await transcriber.start()

        transcriptions: list[TranscriptionEvent] = []

        async def collector(event: TranscriptionEvent) -> None:
            transcriptions.append(event)

        bus.subscribe(TranscriptionEvent, collector)

        await bus.publish(
            AudioChunkEvent(
                session_id="session-42",
                speaker_id="player1",
                speaker_name="Ana",
                audio_data=_make_pcm(2.0),
                timestamp=time.time(),
                duration_ms=2000,
                source="discord",
            )
        )

        assert len(transcriptions) == 1
        t = transcriptions[0]
        assert t.session_id == "session-42"
        assert t.speaker_id == "player1"
        assert t.speaker_name == "Ana"
        assert t.text == "Aelar desenvaina su espada."

    @pytest.mark.asyncio
    async def test_openai_via_event_bus(self) -> None:
        """OpenAITranscriber receives audio via bus and publishes transcription."""
        bus = EventBus()
        config = TranscriberConfig(
            prompt_hint="Nombres: Aelar, Fray Bernardo",
        )
        transcriber = OpenAITranscriber(bus, config)

        mock_response = MagicMock()
        mock_response.text = "Fray Bernardo reza en silencio."

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        transcriber._client = mock_client

        await transcriber.start()

        transcriptions: list[TranscriptionEvent] = []

        async def collector(event: TranscriptionEvent) -> None:
            transcriptions.append(event)

        bus.subscribe(TranscriptionEvent, collector)

        await bus.publish(_make_audio_event(speaker_name="Pedro"))

        assert len(transcriptions) == 1
        assert transcriptions[0].text == "Fray Bernardo reza en silencio."

        await transcriber.stop()
