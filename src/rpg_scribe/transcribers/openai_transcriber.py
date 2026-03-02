"""OpenAI API transcriber with async queue and concurrency control."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import struct
import time
import wave

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent, SystemStatusEvent
from rpg_scribe.core.models import TranscriberConfig
from rpg_scribe.transcribers.base import BaseTranscriber

logger = logging.getLogger(__name__)


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    sample_rate: int = 48000,
    sample_width: int = 2,
    channels: int = 1,
) -> bytes:
    """Convert raw PCM bytes to a WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


class OpenAITranscriber(BaseTranscriber):
    """Transcriber using OpenAI's API (gpt-4o-transcribe / whisper-1).

    Features:
    - Async processing queue with bounded concurrency
    - Retry with exponential backoff
    - Result cache by audio content hash
    """

    def __init__(self, event_bus: EventBus, config: TranscriberConfig) -> None:
        super().__init__(event_bus, config)
        self._client: object | None = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        self._cache: dict[str, str] = {}

    def _get_client(self) -> object:
        """Lazy-init the OpenAI async client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI()
            except ImportError:
                raise RuntimeError(
                    "openai package is required for OpenAITranscriber. "
                    "Install it with: pip install openai"
                )
        return self._client

    @staticmethod
    def _audio_hash(audio_data: bytes) -> str:
        """Compute a short hash of audio data for caching."""
        return hashlib.md5(audio_data).hexdigest()

    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        """Transcribe an audio chunk via OpenAI API with retry."""
        cache_key = self._audio_hash(event.audio_data)
        if cache_key in self._cache:
            logger.debug(
                "Cache hit para chunk de '%s' (hash=%s)", event.speaker_name, cache_key[:8]
            )
            return TranscriptionEvent(
                session_id=event.session_id,
                speaker_id=event.speaker_id,
                speaker_name=event.speaker_name,
                text=self._cache[cache_key],
                timestamp=event.timestamp,
                confidence=1.0,
                is_partial=False,
            )

        wav_data = _pcm_to_wav_bytes(event.audio_data)

        logger.info(
            "🌐 Enviando a OpenAI (%s) | hablante='%s' | tamaño=%.1fKB | idioma=%s",
            self.config.model,
            event.speaker_name,
            len(wav_data) / 1024,
            self.config.language,
        )
        text = await self._call_api_with_retry(wav_data)
        logger.debug("Respuesta OpenAI en bruto para '%s': \"%s\"", event.speaker_name, text[:120])

        self._cache[cache_key] = text

        return TranscriptionEvent(
            session_id=event.session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=text,
            timestamp=event.timestamp,
            confidence=0.95,
            is_partial=False,
        )

    async def _call_api_with_retry(self, wav_data: bytes) -> str:
        """Call the OpenAI transcription API with retry and backoff."""
        last_exc: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                async with self._semaphore:
                    return await self._call_api(wav_data)
            except Exception as exc:
                last_exc = exc
                if attempt < self.config.max_retries:
                    delay = self.config.retry_base_delay_s * (2 ** attempt)
                    logger.warning(
                        "OpenAI API attempt %d/%d failed: %s. Retrying in %.1fs",
                        attempt + 1,
                        self.config.max_retries + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"OpenAI API failed after {self.config.max_retries + 1} attempts: {last_exc}"
        )

    async def _call_api(self, wav_data: bytes) -> str:
        """Make a single call to the OpenAI transcription API."""
        client = self._get_client()

        audio_file = io.BytesIO(wav_data)
        audio_file.name = "audio.wav"

        response = await client.audio.transcriptions.create(  # type: ignore[union-attr]
            model=self.config.model,
            file=audio_file,
            language=self.config.language,
        )
        return response.text

    async def start(self) -> None:
        """Start the transcriber, verifying the client can be created."""
        self._get_client()
        await super().start()

    async def stop(self) -> None:
        """Stop the transcriber and clear cache."""
        self._cache.clear()
        await super().stop()
