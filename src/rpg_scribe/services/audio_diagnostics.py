"""Save audio chunks as WAV for manual inspection."""
from __future__ import annotations

import logging
from pathlib import Path

from rpg_scribe.core.events import AudioChunkEvent

logger = logging.getLogger(__name__)


class AudioDiagnosticSaver:
    """Saves audio chunks as WAV files for manual inspection.

    Saves the first ``max_files`` chunks per user as mono WAV files
    under ``<log_dir>/audio/``.
    """

    def __init__(self, log_dir: Path, max_files_per_user: int = 3) -> None:
        self._audio_dir = log_dir / "audio"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._max_per_user = max_files_per_user
        self._counts: dict[str, int] = {}

    async def save(self, event: AudioChunkEvent) -> None:
        """Save an audio chunk as a mono WAV file."""
        uid = event.speaker_id
        count = self._counts.get(uid, 0)
        if count >= self._max_per_user:
            return

        import io
        import wave

        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in event.speaker_name
        )
        filepath = self._audio_dir / f"{safe_name}_{uid}_{count:03d}.wav"

        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(event.audio_data)
            filepath.write_bytes(buf.getvalue())
            self._counts[uid] = count + 1
            logger.info(
                "🔍 Audio diagnóstico: %s (%.1fKB, %.1fs)",
                filepath.name,
                len(event.audio_data) / 1024,
                event.duration_ms / 1000,
            )
        except Exception as exc:
            logger.error("Error guardando audio diagnóstico: %s", exc)
