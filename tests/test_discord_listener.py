"""Tests for DiscordListener components (UserAudioBuffer, chunking logic)."""

from __future__ import annotations

import struct
import time

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, SystemStatusEvent
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.discord_listener import (
    DiscordListener,
    UserAudioBuffer,
    _stereo_to_mono,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mono_pcm(duration_s: float, sample_rate: int = 48000, value: int = 1000) -> bytes:
    """Generate silent-ish mono PCM16 data of given duration."""
    n_samples = int(sample_rate * duration_s)
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


def _make_stereo_pcm(duration_s: float, sample_rate: int = 48000) -> bytes:
    """Generate stereo PCM16 data of given duration."""
    n_samples = int(sample_rate * duration_s)
    # Both channels same value
    samples = []
    for _ in range(n_samples):
        samples.extend([500, 500])
    return struct.pack(f"<{n_samples * 2}h", *samples)


# ---------------------------------------------------------------------------
# stereo_to_mono
# ---------------------------------------------------------------------------

class TestStereoToMono:
    def test_basic_conversion(self) -> None:
        stereo = struct.pack("<4h", 100, 200, 300, 400)  # 2 stereo samples
        mono = _stereo_to_mono(stereo)
        samples = struct.unpack(f"<{len(mono) // 2}h", mono)
        assert len(samples) == 2
        assert samples[0] == 150  # avg(100, 200)
        assert samples[1] == 350  # avg(300, 400)

    def test_empty_input(self) -> None:
        mono = _stereo_to_mono(b"")
        assert mono == b""


# ---------------------------------------------------------------------------
# UserAudioBuffer
# ---------------------------------------------------------------------------

class TestUserAudioBuffer:
    @pytest.fixture
    def config(self) -> ListenerConfig:
        return ListenerConfig(
            chunk_duration_s=10.0,
            silence_threshold_s=1.5,
            short_silence_threshold_s=0.5,
            min_chunk_duration_s=0.5,
        )

    def test_empty_buffer_does_not_emit(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        assert buf.duration_s == 0.0
        assert not buf.should_emit()

    def test_duration_calculation(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        # 1 second of mono 48kHz 16-bit = 96000 bytes
        pcm = _make_mono_pcm(1.0)
        buf.add_audio(pcm)
        assert abs(buf.duration_s - 1.0) < 0.01

    def test_emit_when_buffer_full(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(10.5)
        buf.add_audio(pcm)
        assert buf.should_emit()

    def test_no_emit_below_min(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(0.1)
        buf.add_audio(pcm)
        assert not buf.should_emit()

    def test_emit_on_long_silence(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(2.0)
        now = time.time()
        buf.add_audio(pcm, now=now)
        # Simulate 2s of silence
        assert buf.should_emit(now=now + 2.0)

    def test_emit_on_short_pause_with_enough_audio(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(6.0)
        now = time.time()
        buf.add_audio(pcm, now=now)
        # 0.6s pause with >5s audio
        assert buf.should_emit(now=now + 0.6)

    def test_no_emit_short_pause_not_enough_audio(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(3.0)
        now = time.time()
        buf.add_audio(pcm, now=now)
        # 0.6s pause but only 3s audio
        assert not buf.should_emit(now=now + 0.6)

    def test_flush_returns_data_and_resets(self, config: ListenerConfig) -> None:
        buf = UserAudioBuffer(config)
        pcm = _make_mono_pcm(2.0)
        buf.add_audio(pcm)
        audio, start_ts, duration_ms = buf.flush()
        assert len(audio) == len(pcm)
        assert duration_ms > 0
        assert buf.duration_s == 0.0


# ---------------------------------------------------------------------------
# DiscordListener integration (without real Discord)
# ---------------------------------------------------------------------------

class TestDiscordListenerIntegration:
    @pytest.fixture
    def config(self) -> ListenerConfig:
        return ListenerConfig(
            chunk_duration_s=1.0,
            silence_threshold_s=0.5,
            min_chunk_duration_s=0.1,
        )

    @pytest.mark.asyncio
    async def test_connect_requires_channel_or_client(self, config: ListenerConfig) -> None:
        bus = EventBus()
        listener = DiscordListener(bus, config)
        with pytest.raises(ValueError, match="voice_channel or voice_client"):
            await listener.connect("session-1")

    @pytest.mark.asyncio
    async def test_is_connected_initially_false(self, config: ListenerConfig) -> None:
        bus = EventBus()
        listener = DiscordListener(bus, config)
        assert not listener.is_connected()

    @pytest.mark.asyncio
    async def test_emit_chunk_publishes_event(self, config: ListenerConfig) -> None:
        """Directly test _emit_chunk by injecting a buffer."""
        bus = EventBus()
        received: list[AudioChunkEvent] = []

        async def handler(event: AudioChunkEvent) -> None:
            received.append(event)

        bus.subscribe(AudioChunkEvent, handler)

        listener = DiscordListener(bus, config)
        listener._session_id = "test-session"
        listener._user_names["user1"] = "TestUser"
        listener._user_buffers["user1"] = UserAudioBuffer(config)
        listener._user_buffers["user1"].add_audio(_make_mono_pcm(2.0))

        await listener._emit_chunk("user1")

        assert len(received) == 1
        assert received[0].session_id == "test-session"
        assert received[0].speaker_id == "user1"
        assert received[0].speaker_name == "TestUser"
        assert received[0].source == "discord"
        assert received[0].duration_ms > 0

    @pytest.mark.asyncio
    async def test_disconnect_flushes_buffers(self, config: ListenerConfig) -> None:
        bus = EventBus()
        received: list[AudioChunkEvent] = []

        async def handler(event: AudioChunkEvent) -> None:
            received.append(event)

        bus.subscribe(AudioChunkEvent, handler)

        listener = DiscordListener(bus, config)
        listener._session_id = "test-session"
        listener._connected = True
        listener._user_names["user1"] = "TestUser"
        listener._user_buffers["user1"] = UserAudioBuffer(config)
        listener._user_buffers["user1"].add_audio(_make_mono_pcm(2.0))

        await listener.disconnect()

        assert not listener.is_connected()
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_disconnect_publishes_status_idle(self, config: ListenerConfig) -> None:
        bus = EventBus()
        statuses: list[SystemStatusEvent] = []

        async def handler(event: SystemStatusEvent) -> None:
            statuses.append(event)

        bus.subscribe(SystemStatusEvent, handler)

        listener = DiscordListener(bus, config)
        listener._session_id = "test-session"
        listener._connected = True

        await listener.disconnect()

        assert any(s.status == "idle" for s in statuses)
