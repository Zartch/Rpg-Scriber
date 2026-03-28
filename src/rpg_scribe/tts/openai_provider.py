"""OpenAI TTS provider."""
from __future__ import annotations

import logging

from rpg_scribe.tts.base import BaseTTSProvider

logger = logging.getLogger(__name__)

OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class OpenAITTSProvider(BaseTTSProvider):
    """TTS provider using OpenAI's text-to-speech API."""

    def __init__(self, model: str = "tts-1") -> None:
        self._model = model
        self._client: object | None = None

    def _get_client(self):
        """Lazy-init the OpenAI async client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI()
            except ImportError:
                raise ImportError(
                    "openai package is required for OpenAITTSProvider. "
                    "Install it with: pip install openai"
                )
        return self._client

    @property
    def name(self) -> str:
        return "openai"

    def supported_voices(self) -> list[str]:
        return list(OPENAI_VOICES)

    async def synthesize(self, text: str, voice: str) -> bytes:
        """Generate mp3 audio via OpenAI TTS API."""
        client = self._get_client()
        logger.debug("TTS request: voice=%s model=%s text=%s...", voice, self._model, text[:60])
        response = await client.audio.speech.create(
            model=self._model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        audio_bytes = response.read()
        logger.debug("TTS response: %d bytes", len(audio_bytes))
        return audio_bytes
