"""Abstract base class for all transcribers."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import wave
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent, SystemStatusEvent
from rpg_scribe.core.models import TranscriberConfig

logger = logging.getLogger(__name__)


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    sample_rate: int = 48000,
    sample_width: int = 2,
    channels: int = 1,
) -> bytes:
    """Convert raw PCM bytes to a WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


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

    def _save_discarded_chunk(
        self,
        event: AudioChunkEvent,
        filter_type: str,
        reason: str,
    ) -> None:
        """Save a discarded audio chunk as a WAV file for development analysis.

        Args:
            event: The original audio chunk event.
            filter_type: "AUDIO" for pre-transcription filter, "HALLU" for hallucination filter.
            reason: Human-readable discard reason (used in filename).
        """
        log_dir = Path(self.config.audio_debug_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        dt = datetime.fromtimestamp(event.timestamp).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        speaker = re.sub(r"[^\w]", "_", event.speaker_name)[:20]
        reason_short = re.sub(r"[^\w]", "_", reason)[:40]
        filename = f"{dt}_{speaker}_{event.duration_ms}ms_{filter_type}_{reason_short}.wav"

        wav_bytes = _pcm_to_wav_bytes(event.audio_data)
        (log_dir / filename).write_bytes(wav_bytes)
        logger.debug("💾 Chunk descartado guardado: %s", filename)

    async def _handle_audio(self, event: AudioChunkEvent) -> None:
        """Handle an AudioChunkEvent: filter, transcribe and publish result."""
        from rpg_scribe.transcribers.audio_filter import analyze_audio

        analysis = analyze_audio(
            event.audio_data,
            event.duration_ms,
            rms_threshold=self.config.audio_filter_rms_threshold,
            speech_ratio_threshold=self.config.audio_filter_speech_ratio_threshold,
            vad_aggressiveness=self.config.audio_filter_vad_aggressiveness,
            enabled=self.config.audio_filter_enabled,
        )

        if not analysis.should_transcribe:
            logger.debug(
                "Chunk de '%s' descartado pre-transcripción: %s "
                "(RMS=%.1f, speech=%.1f%%, dur=%dms)",
                event.speaker_name,
                analysis.discard_reason,
                analysis.rms_energy,
                analysis.speech_ratio * 100,
                event.duration_ms,
            )
            if self.config.audio_debug_log_dir:
                await asyncio.to_thread(
                    self._save_discarded_chunk, event, "AUDIO", analysis.discard_reason
                )
            return

        logger.info(
            "📨 Chunk de '%s' (id=%s) | %.1fs | sesión=%s | "
            "RMS=%.0f speech=%.0f%% → transcribiendo...",
            event.speaker_name,
            event.speaker_id,
            event.duration_ms / 1000,
            event.session_id,
            analysis.rms_energy,
            analysis.speech_ratio * 100,
        )
        try:
            result = await self.transcribe(event)
            if not result.text.strip():
                logger.debug(
                    "Chunk de '%s' descartado (sin texto tras transcribir)",
                    event.speaker_name,
                )
                return

            # Post-transcription hallucination filter
            if self.config.post_filter_enabled:
                from rpg_scribe.transcribers.audio_filter import is_hallucination

                is_hallu, reason = is_hallucination(
                    result.text,
                    event.duration_ms,
                    max_words_per_second=self.config.post_filter_max_words_per_second,
                )
                if is_hallu:
                    logger.info(
                        "🚫 Alucinación de '%s' descartada: \"%s\" (%s)",
                        event.speaker_name,
                        result.text[:80],
                        reason,
                    )
                    if self.config.audio_debug_log_dir:
                        await asyncio.to_thread(
                            self._save_discarded_chunk, event, "HALLU", reason
                        )
                    return

            preview = result.text[:100] + ("…" if len(result.text) > 100 else "")
            logger.info(
                "✅ Transcripción de '%s': \"%s\" → publicando al EventBus",
                result.speaker_name,
                preview,
            )
            await self.event_bus.publish(result)
        except Exception as exc:
            logger.error(
                "❌ Error transcribiendo chunk de '%s': %s",
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
