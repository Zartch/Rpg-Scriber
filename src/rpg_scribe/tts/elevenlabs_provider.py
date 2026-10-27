"""ElevenLabs TTS provider."""
from __future__ import annotations

import logging

from rpg_scribe.tts.base import BaseTTSProvider

logger = logging.getLogger(__name__)

# Default multilingual voice — the sessions are in Spanish, so the provider
# defaults to a voice + model that handle non-English text well.
DEFAULT_VOICE = "t9LRTh3y1ioN00e9wsNh"

# Known ElevenLabs voice_ids. Kept as a static module constant (the simplest
# option): listing voices via the API would require a network round-trip and a
# valid API key just to answer ``GET /api/tts/voices``. Extend this list as
# more voices are curated for the project.
ELEVENLABS_VOICES = [DEFAULT_VOICE]

# Shared TTS ``response_format`` vocabulary → ElevenLabs ``output_format``.
# "pcm" MUST map to ``pcm_24000`` (raw 24 kHz mono int16 LE): that buffer is
# fed as-is to ``pcm_24k_mono_to_48k_stereo()`` for Discord voice output. Any
# other format here would make Discord audio come out as noise.
_OUTPUT_FORMATS = {
    "pcm": "pcm_24000",
    "mp3": "mp3_44100_128",
}
_DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


class ElevenLabsTTSProvider(BaseTTSProvider):
    """TTS provider using ElevenLabs' text-to-speech API."""

    def __init__(self, model: str = "eleven_multilingual_v2") -> None:
        self._model = model
        self._client: object | None = None

    def _get_client(self):
        """Lazy-init the ElevenLabs async client.

        The client reads ``ELEVENLABS_API_KEY`` from the environment
        automatically (mirroring how the OpenAI client reads
        ``OPENAI_API_KEY``).
        """
        if self._client is None:
            try:
                from elevenlabs.client import AsyncElevenLabs

                self._client = AsyncElevenLabs()
            except ImportError:
                raise ImportError(
                    "elevenlabs package is required for ElevenLabsTTSProvider. "
                    "Install it with: pip install elevenlabs"
                )
        return self._client

    @property
    def name(self) -> str:
        return "elevenlabs"

    def supported_voices(self) -> list[str]:
        return list(ELEVENLABS_VOICES)

    async def synthesize(self, text: str, voice: str, response_format: str = "mp3") -> bytes:
        """Generate audio via the ElevenLabs TTS API.

        ``response_format`` uses the shared, provider-agnostic TTS vocabulary:
        ``"mp3"`` (default, browser playback) and ``"pcm"`` (raw 24 kHz mono
        int16 LE, used for Discord). It is translated to ElevenLabs'
        ``output_format`` before the request.

        In elevenlabs 2.x the async ``convert`` is an *async generator
        function*: calling it returns an ``AsyncIterator[bytes]`` directly (it
        is NOT awaitable). We iterate it and concatenate the chunks into a
        single contiguous ``bytes`` payload, which is what the rest of the
        pipeline expects.
        """
        client = self._get_client()
        output_format = _OUTPUT_FORMATS.get(response_format, _DEFAULT_OUTPUT_FORMAT)
        logger.debug(
            "TTS request: voice=%s model=%s format=%s (%s) text=%s...",
            voice, self._model, response_format, output_format, text[:60],
        )
        audio_iter = client.text_to_speech.convert(
            text=text,
            voice_id=voice,
            model_id=self._model,
            output_format=output_format,
        )
        chunks: list[bytes] = []
        async for chunk in audio_iter:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)
        logger.debug("TTS response: %d bytes (format=%s)", len(audio_bytes), output_format)
        return audio_bytes
