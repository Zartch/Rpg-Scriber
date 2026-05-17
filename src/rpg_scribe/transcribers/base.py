"""Abstract base class for all transcribers."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
import wave
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent, SystemStatusEvent
from rpg_scribe.core.models import TranscriberConfig

logger = logging.getLogger(__name__)

# Emit a stats line every N seconds while the transcriber is running.
_STATS_INTERVAL_S = 30.0
# Warn if no successful transcription has been emitted for this long while
# chunks are still being received — strong signal of a degraded audio stream.
_STALL_WARNING_S = 120.0


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
        # Health/observability counters (cumulative since last start)
        self._chunks_received = 0
        self._chunks_pre_filtered = 0
        self._chunks_transcribed = 0
        self._chunks_hallucination = 0
        self._chunks_empty = 0
        self._chunks_errored = 0
        self._first_chunk_ts: float | None = None
        self._last_success_ts: float | None = None
        self._last_stats_snapshot: tuple[int, ...] = (0, 0, 0, 0, 0, 0)
        self._stall_warned = False
        self._stats_task: asyncio.Task[None] | None = None

    @abstractmethod
    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        """Transcribe a single audio chunk and return a TranscriptionEvent."""
        ...

    async def start(self) -> None:
        """Subscribe to the event bus and start processing audio chunks."""
        self.event_bus.subscribe(AudioChunkEvent, self._handle_audio)
        self._stats_task = asyncio.create_task(
            self._periodic_stats(), name="transcriber-stats"
        )
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
        if self._stats_task is not None:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass
            self._stats_task = None
        self._log_stats(final=True)
        await self.event_bus.publish(
            SystemStatusEvent(
                component="transcriber",
                status="idle",
                message="Transcriber stopped",
            )
        )
        logger.info("%s stopped", type(self).__name__)

    async def _periodic_stats(self) -> None:
        """Emit a stats line every ``_STATS_INTERVAL_S`` while running."""
        try:
            while True:
                await asyncio.sleep(_STATS_INTERVAL_S)
                self._log_stats()
        except asyncio.CancelledError:
            pass

    def _log_stats(self, *, final: bool = False) -> None:
        """Log cumulative counters + stall warning if audio is being received
        but nothing has transcribed successfully for a while."""
        snapshot = (
            self._chunks_received,
            self._chunks_pre_filtered,
            self._chunks_transcribed,
            self._chunks_hallucination,
            self._chunks_empty,
            self._chunks_errored,
        )
        # Skip noisy "all zeros" lines unless this is the final summary.
        if not final and snapshot == self._last_stats_snapshot:
            return
        self._last_stats_snapshot = snapshot

        if self._last_success_ts is None:
            last_success_str = "never"
            stalled_for: float | None = None
            if self._first_chunk_ts is not None:
                stalled_for = time.time() - self._first_chunk_ts
        else:
            stalled_for = time.time() - self._last_success_ts
            last_success_str = f"{stalled_for:.0f}s ago"

        prefix = "📊 Final transcriber stats" if final else "📊 Transcriber stats"
        logger.info(
            "%s: received=%d pre_filtered=%d transcribed=%d hallu=%d empty=%d errored=%d | last_success=%s",
            prefix,
            *snapshot,
            last_success_str,
        )

        # Stall detection: audio arriving but nothing transcribes
        if (
            not final
            and self._chunks_received > 0
            and stalled_for is not None
            and stalled_for > _STALL_WARNING_S
            and not self._stall_warned
        ):
            logger.warning(
                "⚠️  Transcriber stall: %d chunks received but no successful transcription "
                "in %.0fs (pre_filtered=%d hallu=%d). Probable causa: stream de audio "
                "degradado (DAVE/voice_recv).",
                self._chunks_received,
                stalled_for,
                self._chunks_pre_filtered,
                self._chunks_hallucination,
            )
            self._stall_warned = True
        elif (
            stalled_for is not None
            and stalled_for < _STALL_WARNING_S
            and self._stall_warned
        ):
            # Recovered — allow re-warning on next stall
            self._stall_warned = False

    def _save_audio_chunk(self, event: AudioChunkEvent) -> None:
        """Save an audio chunk as WAV in data/audio/{session_id}/ for playback."""
        audio_dir = Path("data/audio") / event.session_id
        audio_dir.mkdir(parents=True, exist_ok=True)

        speaker = re.sub(r"[^\w]", "_", event.speaker_name)[:30]
        filename = f"{event.timestamp}_{speaker}.wav"

        wav_bytes = _pcm_to_wav_bytes(event.audio_data)
        (audio_dir / filename).write_bytes(wav_bytes)
        logger.debug("Audio chunk saved: %s", audio_dir / filename)

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
        log_dir = Path(self.config.audio_debug_log_dir) / event.session_id
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

        self._chunks_received += 1
        if self._first_chunk_ts is None:
            self._first_chunk_ts = time.time()

        analysis = analyze_audio(
            event.audio_data,
            event.duration_ms,
            rms_threshold=self.config.audio_filter_rms_threshold,
            speech_ratio_threshold=self.config.audio_filter_speech_ratio_threshold,
            vad_aggressiveness=self.config.audio_filter_vad_aggressiveness,
            enabled=self.config.audio_filter_enabled,
        )

        if not analysis.should_transcribe:
            self._chunks_pre_filtered += 1
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
                try:
                    await asyncio.to_thread(
                        self._save_discarded_chunk,
                        event,
                        "AUDIO",
                        analysis.discard_reason,
                    )
                except Exception:
                    logger.exception(
                        "Error guardando chunk descartado (AUDIO) de '%s'",
                        event.speaker_name,
                    )
            return

        chunk_log = logger.info if self.config.verbose_logging else logger.debug
        chunk_log(
            "📨 Chunk de '%s' (id=%s) | %.1fs | sesión=%s | "
            "RMS=%.0f speech=%.0f%% → transcribiendo...",
            event.speaker_name,
            event.speaker_id,
            event.duration_ms / 1000,
            event.session_id,
            analysis.rms_energy,
            analysis.speech_ratio * 100,
        )
        # Save audio chunk to disk for web playback
        try:
            await asyncio.to_thread(self._save_audio_chunk, event)
        except Exception as exc:
            logger.warning("Failed to save audio chunk: %s", exc)

        try:
            result = await self.transcribe(event)
            if not result.text.strip():
                self._chunks_empty += 1
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
                    self._chunks_hallucination += 1
                    logger.info(
                        "🚫 Alucinación de '%s' descartada: \"%s\" (%s) | "
                        "audio: %dms RMS=%.0f speech=%.0f%% (umbral RMS=%.0f) | "
                        "hallu_total=%d",
                        event.speaker_name,
                        result.text[:80],
                        reason,
                        event.duration_ms,
                        analysis.rms_energy,
                        analysis.speech_ratio * 100,
                        self.config.audio_filter_rms_threshold,
                        self._chunks_hallucination,
                    )
                    if self.config.audio_debug_log_dir:
                        try:
                            await asyncio.to_thread(
                                self._save_discarded_chunk, event, "HALLU", reason
                            )
                        except Exception:
                            logger.exception(
                                "Error guardando chunk descartado (HALLU) de '%s'",
                                event.speaker_name,
                            )
                    return

            self._chunks_transcribed += 1
            self._last_success_ts = time.time()
            preview = result.text[:100] + ("…" if len(result.text) > 100 else "")
            chunk_log(
                "✅ Transcripción de '%s': \"%s\" → publicando al EventBus",
                result.speaker_name,
                preview,
            )
            await self.event_bus.publish(result)
        except Exception as exc:
            self._chunks_errored += 1
            logger.exception(
                "❌ Error transcribiendo chunk de '%s' (dur=%dms RMS=%.0f speech=%.0f%%): %s",
                event.speaker_name,
                event.duration_ms,
                analysis.rms_energy,
                analysis.speech_ratio * 100,
                exc,
            )
            await self.event_bus.publish(
                SystemStatusEvent(
                    component="transcriber",
                    status="error",
                    message=f"Transcription error: {exc}",
                )
            )
