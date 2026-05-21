"""Tests for the shared TTS synthesizer helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rpg_scribe.tts.cache import TTSCache


class TestSplitTextToChunks:
    """_split_text_to_chunks splits multi-paragraph text into TTS-sized chunks."""

    def test_single_paragraph_returns_one_chunk(self) -> None:
        from rpg_scribe.tts.synthesizer import _split_text_to_chunks

        assert _split_text_to_chunks("hola mundo") == ["hola mundo"]

    def test_multi_paragraph_split_on_double_newline(self) -> None:
        from rpg_scribe.tts.synthesizer import _split_text_to_chunks

        chunks = _split_text_to_chunks("First paragraph.\n\nSecond paragraph.")
        assert chunks == ["First paragraph.", "Second paragraph."]

    def test_empty_text_raises(self) -> None:
        from rpg_scribe.tts.synthesizer import _split_text_to_chunks

        with pytest.raises(ValueError):
            _split_text_to_chunks("   ")

    def test_very_long_paragraph_split_at_punctuation(self) -> None:
        from rpg_scribe.tts.synthesizer import _split_text_to_chunks, _TTS_CHAR_LIMIT

        # Build a paragraph longer than the char limit with a clear punctuation break.
        half = "a" * (_TTS_CHAR_LIMIT - 10)
        text = f"{half}. {half}."
        chunks = _split_text_to_chunks(text)
        assert len(chunks) >= 2
        # All chunks must fit within the limit.
        assert all(len(c) <= _TTS_CHAR_LIMIT for c in chunks)


class TestSynthesizeToWavPaths:
    """synthesize_to_wav_paths: split + synth + cache, returns ordered WAV paths."""

    @pytest.mark.asyncio
    async def test_cache_miss_synthesizes_and_writes_wav(self, tmp_path: Path) -> None:
        from rpg_scribe.tts.synthesizer import synthesize_to_wav_paths

        # 24 kHz mono int16 LE — 8 samples of silence
        fake_pcm = b"\x00\x00" * 8
        provider = MagicMock()
        provider.name = "openai"
        provider.synthesize = AsyncMock(return_value=fake_pcm)
        cache = TTSCache(str(tmp_path))

        paths = await synthesize_to_wav_paths(
            "hola mundo",
            voice="nova",
            provider=provider,
            cache=cache,
            model="tts-1",
        )
        assert len(paths) == 1
        assert paths[0].is_file()
        assert paths[0].read_bytes()[:4] == b"RIFF"
        provider.synthesize.assert_awaited_once_with(
            "hola mundo", "nova", response_format="pcm"
        )

    @pytest.mark.asyncio
    async def test_cache_hit_skips_provider(self, tmp_path: Path) -> None:
        from rpg_scribe.tts.synthesizer import synthesize_to_wav_paths

        cache = TTSCache(str(tmp_path))
        key = cache.make_key("cached", "openai", "nova", "tts-1")
        # Pre-populate cache with a fake WAV-ish blob
        cache.put(key, b"RIFFfakecache")

        provider = MagicMock()
        provider.name = "openai"
        provider.synthesize = AsyncMock(return_value=b"unused")

        paths = await synthesize_to_wav_paths(
            "cached",
            voice="nova",
            provider=provider,
            cache=cache,
            model="tts-1",
        )
        assert len(paths) == 1
        provider.synthesize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_paragraphs_return_ordered_paths(self, tmp_path: Path) -> None:
        from rpg_scribe.tts.synthesizer import synthesize_to_wav_paths

        fake_pcm = b"\x00\x00" * 8
        provider = MagicMock()
        provider.name = "openai"
        provider.synthesize = AsyncMock(return_value=fake_pcm)
        cache = TTSCache(str(tmp_path))

        text = "First.\n\nSecond.\n\nThird."
        paths = await synthesize_to_wav_paths(
            text,
            voice="nova",
            provider=provider,
            cache=cache,
            model="tts-1",
        )
        assert len(paths) == 3
        # Paths come from different cache keys (text differs per chunk).
        assert len({p.name for p in paths}) == 3
        # Provider was called once per uncached chunk, in order.
        calls = [c.args[0] for c in provider.synthesize.await_args_list]
        assert calls == ["First.", "Second.", "Third."]
