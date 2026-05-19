"""Abstract base class for TTS providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):
    """Interface that any TTS provider must implement."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str, response_format: str = "mp3") -> bytes:
        """Generate audio bytes from a text fragment.

        ``response_format`` controls the encoding: ``"mp3"`` (default) for
        browser playback, ``"pcm"`` for raw 24 kHz mono int16 LE suitable
        for further resampling and direct Discord voice output.
        """
        ...

    @abstractmethod
    def supported_voices(self) -> list[str]:
        """Return the list of available voice identifiers."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai', 'edge')."""
        ...
