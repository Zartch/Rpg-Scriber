"""Writes transcriptions to rotating text files."""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from rpg_scribe.core.events import TranscriptionEvent

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPTION_FILE_MB = 5


class TranscriptionFileWriter:
    """Writes transcriptions to text files inside the logs directory.

    Each log run (identified by a unix-timestamp folder) gets its own
    ``transcriptions_NNN.txt`` file.  When a file exceeds
    ``_MAX_TRANSCRIPTION_FILE_MB`` a new numbered file is created.
    """

    def __init__(
        self, log_dir: Path, max_size_mb: float = _MAX_TRANSCRIPTION_FILE_MB
    ) -> None:
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = int(max_size_mb * 1024 * 1024)
        self._file_index = 0
        self._path = self._next_path()
        self._disabled = False

    def _next_path(self) -> Path:
        """Return the next numbered transcription file path."""
        while True:
            suffix = f"_{self._file_index}" if self._file_index > 0 else ""
            path = self._dir / f"transcriptions{suffix}.txt"
            if not path.exists() or path.stat().st_size < self._max_bytes:
                return path
            self._file_index += 1

    def write(self, event: "TranscriptionEvent") -> None:
        """Append a transcription line to the current file.

        Format:  [HH:MM:SS] Speaker: text
        """
        if not event.text.strip():
            return

        # Rotate if current file is too large
        if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
            self._file_index += 1
            self._path = self._next_path()
            logger.info(
                "📄 Transcription file rotated to %s",
                self._path.name,
            )

        if self._disabled:
            return

        ts = datetime.datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
        line = f"[{ts}] {event.speaker_name}: {event.text}\n"
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except FileNotFoundError:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as exc:
                self._disabled = True
                logger.error(
                    "Directorio de transcripciones desaparecido, escritura deshabilitada para esta sesión: %s",
                    exc,
                )
