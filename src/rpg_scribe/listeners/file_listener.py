"""FileListener – reads audio files and emits AudioChunkEvent.

Useful for testing and re-processing recorded sessions.
"""

from __future__ import annotations

import logging
import math
import time

import soundfile as sf
import numpy as np

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, SystemStatusEvent
from rpg_scribe.core.models import ListenerConfig
from rpg_scribe.listeners.base import BaseListener

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 48000


class FileListener(BaseListener):
    """Reads a WAV/FLAC/OGG file and emits AudioChunkEvent chunks.

    Parameters
    ----------
    speaker_id, speaker_name:
        Identify the speaker for emitted events.
    file_path:
        Path to the audio file (resolved at connect time or via constructor).
    """

    def __init__(
        self,
        event_bus: EventBus,
        config: ListenerConfig,
        *,
        speaker_id: str = "file_speaker",
        speaker_name: str = "File Speaker",
    ) -> None:
        super().__init__(event_bus, config)
        self.speaker_id = speaker_id
        self.speaker_name = speaker_name
        self._connected = False
        self._session_id: str | None = None

    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, session_id: str, *, file_path: str | None = None, **kwargs: object) -> None:  # type: ignore[override]
        """'Connect' by loading and chunking the audio file.

        The entire file is read and emitted as AudioChunkEvent chunks.
        """
        if file_path is None:
            raise ValueError("file_path is required for FileListener")

        self._session_id = session_id
        self._connected = True

        await self.event_bus.publish(
            SystemStatusEvent(
                component="listener",
                status="running",
                message=f"Reading file: {file_path}",
            )
        )

        try:
            data, sr = sf.read(file_path, dtype="int16")
        except Exception as exc:
            self._connected = False
            await self.event_bus.publish(
                SystemStatusEvent(
                    component="listener",
                    status="error",
                    message=f"Failed to read file: {exc}",
                )
            )
            raise

        # Convert to mono if stereo
        if data.ndim > 1:
            data = data.mean(axis=1).astype(np.int16)

        # Resample to 48 kHz if needed
        if sr != TARGET_SAMPLE_RATE:
            ratio = TARGET_SAMPLE_RATE / sr
            n_out = int(len(data) * ratio)
            indices = np.linspace(0, len(data) - 1, n_out).astype(int)
            data = data[indices]
            sr = TARGET_SAMPLE_RATE

        pcm_bytes = data.tobytes()
        bytes_per_second = sr * self.config.sample_width * self.config.channels
        chunk_bytes = int(self.config.chunk_duration_s * bytes_per_second)

        base_time = time.time()
        n_chunks = math.ceil(len(pcm_bytes) / chunk_bytes) if chunk_bytes > 0 else 0

        for i in range(n_chunks):
            start = i * chunk_bytes
            end = min(start + chunk_bytes, len(pcm_bytes))
            chunk = pcm_bytes[start:end]
            duration_ms = int(len(chunk) / bytes_per_second * 1000)

            event = AudioChunkEvent(
                session_id=session_id,
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                audio_data=chunk,
                timestamp=base_time + i * self.config.chunk_duration_s,
                duration_ms=duration_ms,
                source="file",
            )
            await self.event_bus.publish(event)

        self._connected = False
        await self.event_bus.publish(
            SystemStatusEvent(
                component="listener",
                status="idle",
                message="File playback complete.",
            )
        )

    async def disconnect(self) -> None:
        self._connected = False
