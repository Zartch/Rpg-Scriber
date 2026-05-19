"""Disk cache for TTS audio files."""
from __future__ import annotations

import hashlib
from pathlib import Path


class TTSCache:
    """Simple disk-based cache for generated TTS audio.

    Files are stored as ``{hash}.{ext}`` where the hash is a SHA-256 of
    the text + provider + voice + model combination. The extension
    defaults to ``"wav"`` so a single cache entry can be replayed both in
    the browser (``<audio>`` element) and through Discord voice (after
    stripping the WAV header to recover raw PCM).
    """

    def __init__(self, cache_dir: str | Path, *, extension: str = "wav") -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ext = extension.lstrip(".")

    def make_key(self, text: str, provider: str, voice: str, model: str) -> str:
        """Generate a deterministic cache key from the synthesis parameters."""
        raw = f"{text}|{provider}|{voice}|{model}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.{self._ext}"

    def has(self, key: str) -> bool:
        return self._path(key).is_file()

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if path.is_file():
            return path.read_bytes()
        return None

    def put(self, key: str, audio: bytes) -> Path:
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return path

    def url_for(self, key: str) -> str:
        return f"/api/tts/cache/{key}.{self._ext}"
