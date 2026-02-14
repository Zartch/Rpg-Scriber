"""Discord voice listener – captures per-user audio and emits AudioChunkEvent."""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any

import discord

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, SystemStatusEvent
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.base import BaseListener

try:
    import webrtcvad
except ImportError:  # pragma: no cover
    webrtcvad = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Discord sends 48 kHz 16-bit stereo; we convert to mono.
DISCORD_SAMPLE_RATE = 48000
DISCORD_SAMPLE_WIDTH = 2  # 16-bit
DISCORD_CHANNELS = 2  # stereo from Discord
# webrtcvad only supports 10/20/30 ms frames
VAD_FRAME_MS = 20
VAD_FRAME_SAMPLES = DISCORD_SAMPLE_RATE * VAD_FRAME_MS // 1000  # 960 samples


def _stereo_to_mono(pcm_stereo: bytes) -> bytes:
    """Convert interleaved 16-bit stereo PCM to mono by averaging channels."""
    n_samples = len(pcm_stereo) // (DISCORD_SAMPLE_WIDTH * DISCORD_CHANNELS)
    samples = struct.unpack(f"<{n_samples * DISCORD_CHANNELS}h", pcm_stereo)
    mono = []
    for i in range(0, len(samples), 2):
        avg = (samples[i] + samples[i + 1]) // 2
        mono.append(avg)
    return struct.pack(f"<{len(mono)}h", *mono)


class UserAudioBuffer:
    """Accumulates mono PCM audio for a single user with VAD-based chunking."""

    def __init__(self, config: ListenerConfig) -> None:
        self.config = config
        self._buffer = bytearray()
        self._start_time: float | None = None
        self._last_voice_time: float = 0.0
        self._vad = None
        if webrtcvad is not None:
            self._vad = webrtcvad.Vad(config.vad_aggressiveness)

    @property
    def duration_s(self) -> float:
        """Current buffer duration in seconds."""
        bytes_per_second = (
            self.config.sample_rate * self.config.sample_width * self.config.channels
        )
        return len(self._buffer) / bytes_per_second if bytes_per_second else 0.0

    def add_audio(self, mono_pcm: bytes, now: float | None = None) -> None:
        """Append mono PCM data to the buffer."""
        now = now or time.time()
        if self._start_time is None:
            self._start_time = now
        self._buffer.extend(mono_pcm)

        # Check VAD on the new data to track last voice activity
        if self._vad is not None and len(mono_pcm) >= VAD_FRAME_SAMPLES * DISCORD_SAMPLE_WIDTH:
            frame = mono_pcm[: VAD_FRAME_SAMPLES * DISCORD_SAMPLE_WIDTH]
            try:
                if self._vad.is_speech(frame, DISCORD_SAMPLE_RATE):
                    self._last_voice_time = now
            except Exception:
                # VAD can fail on edge cases; treat as speech
                self._last_voice_time = now
        else:
            self._last_voice_time = now

    def should_emit(self, now: float | None = None) -> bool:
        """Decide whether the buffer should be emitted as a chunk.

        Conditions (from the architecture doc):
        - Buffer is full (>= chunk_duration_s)
        - Silence > silence_threshold_s (end of phrase)
        - >5s of audio accumulated and pause > short_silence_threshold_s
        """
        now = now or time.time()
        dur = self.duration_s
        if dur < self.config.min_chunk_duration_s:
            return False

        # Buffer full
        if dur >= self.config.chunk_duration_s:
            return True

        silence = now - self._last_voice_time if self._last_voice_time else 0.0

        # Long silence
        if silence >= self.config.silence_threshold_s:
            return True

        # Medium buffer + short pause
        if dur >= 5.0 and silence >= self.config.short_silence_threshold_s:
            return True

        return False

    def flush(self) -> tuple[bytes, float, int]:
        """Return (audio_bytes, start_timestamp, duration_ms) and reset."""
        audio = bytes(self._buffer)
        start = self._start_time or time.time()
        duration_ms = int(self.duration_s * 1000)
        self._buffer.clear()
        self._start_time = None
        return audio, start, duration_ms


class DiscordListener(BaseListener):
    """Listens to a Discord voice channel and emits AudioChunkEvent per user.

    Uses discord-ext-voice-recv to receive per-user PCM audio streams.
    """

    def __init__(self, event_bus: EventBus, config: ListenerConfig) -> None:
        super().__init__(event_bus, config)
        self._session_id: str | None = None
        self._voice_client: Any | None = None
        self._user_buffers: dict[str, UserAudioBuffer] = {}
        self._user_names: dict[str, str] = {}
        self._connected = False
        self._flush_task: asyncio.Task[None] | None = None

    def is_connected(self) -> bool:
        return self._connected

    async def connect(
        self,
        session_id: str,
        *,
        voice_channel: discord.VoiceChannel | None = None,
        voice_client: Any | None = None,
        **kwargs: object,
    ) -> None:
        """Connect to a Discord voice channel.

        Either pass a ``voice_channel`` to join, or a pre-existing
        ``voice_client`` (useful in tests).
        """
        self._session_id = session_id

        if voice_client is not None:
            self._voice_client = voice_client
        elif voice_channel is not None:
            try:
                from discord.ext import voice_recv  # type: ignore[import-untyped]

                self._voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)  # type: ignore[arg-type]
            except Exception as exc:
                await self.event_bus.publish(
                    SystemStatusEvent(
                        component="listener",
                        status="error",
                        message=f"Failed to connect: {exc}",
                    )
                )
                raise
        else:
            raise ValueError("Must provide either voice_channel or voice_client")

        self._connected = True
        self._start_receiving()
        self._flush_task = asyncio.create_task(self._periodic_flush())

        await self.event_bus.publish(
            SystemStatusEvent(
                component="listener",
                status="running",
                message=f"Connected to voice. Session: {session_id}",
            )
        )
        logger.info("DiscordListener connected for session %s", session_id)

    def _start_receiving(self) -> None:
        """Register the audio callback on the voice client."""
        try:
            from discord.ext import voice_recv  # type: ignore[import-untyped]

            def audio_callback(user: discord.User | discord.Member | None, data: voice_recv.VoiceData) -> None:  # type: ignore[name-defined]
                if user is None:
                    return
                uid = str(user.id)
                name = getattr(user, "display_name", str(user))
                self._user_names[uid] = name

                mono_pcm = _stereo_to_mono(data.pcm)

                if uid not in self._user_buffers:
                    self._user_buffers[uid] = UserAudioBuffer(self.config)

                self._user_buffers[uid].add_audio(mono_pcm)

            self._voice_client.listen(voice_recv.BasicSink(audio_callback))
        except ImportError:
            logger.warning(
                "discord-ext-voice-recv not installed; audio receiving disabled"
            )

    async def _periodic_flush(self) -> None:
        """Periodically check buffers and emit chunks."""
        try:
            while self._connected:
                await asyncio.sleep(0.25)
                now = time.time()
                for uid in list(self._user_buffers):
                    buf = self._user_buffers[uid]
                    if buf.should_emit(now):
                        await self._emit_chunk(uid)
        except asyncio.CancelledError:
            pass

    async def _emit_chunk(self, user_id: str) -> None:
        """Flush a user buffer and publish an AudioChunkEvent."""
        buf = self._user_buffers.get(user_id)
        if buf is None or buf.duration_s < self.config.min_chunk_duration_s:
            return
        audio, start_ts, duration_ms = buf.flush()
        event = AudioChunkEvent(
            session_id=self._session_id or "",
            speaker_id=user_id,
            speaker_name=self._user_names.get(user_id, user_id),
            audio_data=audio,
            timestamp=start_ts,
            duration_ms=duration_ms,
            source="discord",
        )
        await self.event_bus.publish(event)

    async def disconnect(self) -> None:
        """Disconnect from the voice channel, flushing remaining buffers."""
        self._connected = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush remaining audio
        for uid in list(self._user_buffers):
            await self._emit_chunk(uid)

        if self._voice_client is not None:
            try:
                await self._voice_client.disconnect()
            except Exception:
                pass
            self._voice_client = None

        self._user_buffers.clear()
        self._user_names.clear()

        await self.event_bus.publish(
            SystemStatusEvent(
                component="listener",
                status="idle",
                message="Disconnected from voice.",
            )
        )
        logger.info("DiscordListener disconnected")
