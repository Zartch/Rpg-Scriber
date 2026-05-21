"""Shared TTS helper: split text, synthesize chunks, cache as WAV.

Used by both the web narration endpoint and the bot trigger pipeline so
that they produce identical cache entries (same key for the same text +
voice + model + provider).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from rpg_scribe.tts.audio_utils import (
    pcm_24k_mono_to_48k_stereo,
    wrap_pcm_as_wav,
)
from rpg_scribe.tts.cache import TTSCache

logger = logging.getLogger(__name__)

_TTS_CHAR_LIMIT = 4096


class _ProviderLike(Protocol):
    name: str

    async def synthesize(
        self, text: str, voice: str, response_format: str = "mp3"
    ) -> bytes: ...


def _split_tts_chunks(text: str, limit: int = _TTS_CHAR_LIMIT) -> list[str]:
    """Recursively split a single paragraph so each piece fits ``limit``."""
    if len(text) <= limit:
        return [text]
    for sep in (".", ",", " "):
        cut = text.rfind(sep, 0, limit)
        if cut != -1:
            head = text[: cut + 1].strip()
            tail = text[cut + 1 :].strip()
            return _split_tts_chunks(head, limit) + _split_tts_chunks(tail, limit)
    return [text[:limit]] + _split_tts_chunks(text[limit:], limit)


def _split_text_to_chunks(text: str) -> list[str]:
    """Split multi-paragraph text into TTS-sized chunks.

    Raises:
        ValueError: if the input is empty or contains no non-whitespace text.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is required")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        raise ValueError("No paragraphs found in text")
    chunks: list[str] = []
    for paragraph in paragraphs:
        chunks.extend(_split_tts_chunks(paragraph))
    return chunks


async def _ensure_chunk_wav(
    chunk: str,
    voice: str,
    *,
    provider: _ProviderLike,
    cache: TTSCache,
    model: str,
    source: str,
) -> tuple[str, bool]:
    """Ensure a single chunk is cached as 48 kHz stereo WAV. Returns (key, was_cached)."""
    key = cache.make_key(chunk, provider.name, voice, model)
    if cache.has(key):
        logger.info("%s cache HIT key=%s chunk_chars=%d", source, key[:12], len(chunk))
        return key, True
    logger.info(
        "%s cache MISS key=%s chunk_chars=%d → synth", source, key[:12], len(chunk)
    )
    pcm_24k_mono = await provider.synthesize(chunk, voice, response_format="pcm")
    pcm_48k_stereo = pcm_24k_mono_to_48k_stereo(pcm_24k_mono)
    wav_bytes = wrap_pcm_as_wav(pcm_48k_stereo, sample_rate=48000, channels=2)
    cache.put(key, wav_bytes)
    return key, False


async def synthesize_to_wav_paths(
    text: str,
    voice: str,
    *,
    provider: _ProviderLike,
    cache: TTSCache,
    model: str,
    source: str = "tts",
) -> list[Path]:
    """Split ``text``, synthesize and cache each chunk, return WAV paths in order."""
    chunks = _split_text_to_chunks(text)
    paths: list[Path] = []
    for chunk in chunks:
        key, _ = await _ensure_chunk_wav(
            chunk,
            voice,
            provider=provider,
            cache=cache,
            model=model,
            source=source,
        )
        paths.append(cache._path(key))  # noqa: SLF001
    return paths
