"""Abstract base class for TTS providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):
    """Interface that any TTS provider must implement."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> bytes:
        """Generate mp3 audio bytes from a text fragment."""
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
