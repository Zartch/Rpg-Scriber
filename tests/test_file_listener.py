"""Tests for the FileListener."""

from __future__ import annotations

import os
import struct
import tempfile

import numpy as np
import pytest
import soundfile as sf

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, SystemStatusEvent
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.file_listener import FileListener


def _create_wav(path: str, duration_s: float = 3.0, sample_rate: int = 48000) -> None:
    """Write a simple WAV file for testing."""
    n_samples = int(sample_rate * duration_s)
    # Generate a 440Hz sine wave
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    data = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    sf.write(path, data, sample_rate, subtype="PCM_16")


@pytest.fixture
def config() -> ListenerConfig:
    return ListenerConfig(
        chunk_duration_s=1.0,
        min_chunk_duration_s=0.1,
    )


@pytest.mark.asyncio
async def test_file_listener_emits_chunks(config: ListenerConfig) -> None:
    bus = EventBus()
    chunks: list[AudioChunkEvent] = []

    async def handler(event: AudioChunkEvent) -> None:
        chunks.append(event)

    bus.subscribe(AudioChunkEvent, handler)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        _create_wav(wav_path, duration_s=3.0)

        listener = FileListener(
            bus, config, speaker_id="tester", speaker_name="Tester"
        )
        await listener.connect("session-1", file_path=wav_path)

        # With 3s audio and 1s chunks, we expect 3 chunks
        assert len(chunks) == 3
        for chunk in chunks:
            assert chunk.session_id == "session-1"
            assert chunk.speaker_id == "tester"
            assert chunk.speaker_name == "Tester"
            assert chunk.source == "file"
            assert len(chunk.audio_data) > 0
    finally:
        os.unlink(wav_path)


@pytest.mark.asyncio
async def test_file_listener_requires_file_path(config: ListenerConfig) -> None:
    bus = EventBus()
    listener = FileListener(bus, config)
    with pytest.raises(ValueError, match="file_path is required"):
        await listener.connect("session-1")


@pytest.mark.asyncio
async def test_file_listener_nonexistent_file(config: ListenerConfig) -> None:
    bus = EventBus()
    statuses: list[SystemStatusEvent] = []

    async def handler(event: SystemStatusEvent) -> None:
        statuses.append(event)

    bus.subscribe(SystemStatusEvent, handler)

    listener = FileListener(bus, config)
    with pytest.raises(Exception):
        await listener.connect("session-1", file_path="/nonexistent/file.wav")

    assert any(s.status == "error" for s in statuses)


@pytest.mark.asyncio
async def test_file_listener_emits_status_events(config: ListenerConfig) -> None:
    bus = EventBus()
    statuses: list[SystemStatusEvent] = []

    async def handler(event: SystemStatusEvent) -> None:
        statuses.append(event)

    bus.subscribe(SystemStatusEvent, handler)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        _create_wav(wav_path, duration_s=1.0)

        listener = FileListener(bus, config)
        await listener.connect("session-1", file_path=wav_path)

        status_messages = [s.status for s in statuses]
        assert "running" in status_messages
        assert "idle" in status_messages
    finally:
        os.unlink(wav_path)


@pytest.mark.asyncio
async def test_file_listener_not_connected_after_playback(config: ListenerConfig) -> None:
    bus = EventBus()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        _create_wav(wav_path, duration_s=1.0)

        listener = FileListener(bus, config)
        assert not listener.is_connected()
        await listener.connect("session-1", file_path=wav_path)
        assert not listener.is_connected()
    finally:
        os.unlink(wav_path)


@pytest.mark.asyncio
async def test_file_listener_stereo_file(config: ListenerConfig) -> None:
    """Stereo files should be converted to mono."""
    bus = EventBus()
    chunks: list[AudioChunkEvent] = []

    async def handler(event: AudioChunkEvent) -> None:
        chunks.append(event)

    bus.subscribe(AudioChunkEvent, handler)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        # Create stereo file
        n_samples = 48000  # 1 second
        data = np.zeros((n_samples, 2), dtype=np.int16)
        data[:, 0] = 1000
        data[:, 1] = -1000
        sf.write(wav_path, data, 48000, subtype="PCM_16")

        listener = FileListener(bus, config)
        await listener.connect("session-1", file_path=wav_path)

        assert len(chunks) == 1
        assert len(chunks[0].audio_data) > 0
    finally:
        os.unlink(wav_path)
