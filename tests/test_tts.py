"""Tests for TTS narration feature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rpg_scribe.core.models import TTSConfig
from rpg_scribe.tts.cache import TTSCache
from rpg_scribe.tts.openai_provider import OpenAITTSProvider


class TestTTSConfig:
    """Test TTSConfig dataclass defaults."""

    def test_defaults(self) -> None:
        """Test TTSConfig has correct default values."""
        config = TTSConfig()

        assert config.enabled is False
        assert config.provider == "openai"
        assert config.voice == "nova"
        assert config.model == "tts-1"
        assert config.cache_dir == "data/tts_cache"


class TestTTSConfigLoading:
    """Test TTSConfig loading from TOML configuration."""

    def test_tts_config_loaded_in_appconfig(self) -> None:
        """Test that AppConfig includes a tts field."""
        from rpg_scribe.config import AppConfig

        config = AppConfig()
        assert hasattr(config, 'tts')
        assert isinstance(config.tts, TTSConfig)

    def test_tts_config_from_toml(self) -> None:
        """Test that TTS config can be loaded from TOML data."""
        from rpg_scribe.config import load_app_config

        # This should load the default.toml which should include [tts] section
        config = load_app_config()

        assert hasattr(config, 'tts')
        assert isinstance(config.tts, TTSConfig)
        # Should have defaults from TOML
        assert config.tts.enabled is False
        assert config.tts.provider == "openai"


class TestTTSCache:
    """Test TTSCache disk cache behaviour."""

    def test_cache_key_is_deterministic(self, tmp_path) -> None:
        """Cache key for identical inputs must be stable across calls."""
        cache = TTSCache(tmp_path)
        key1 = cache.make_key("hello world", "openai", "nova", "tts-1")
        key2 = cache.make_key("hello world", "openai", "nova", "tts-1")
        assert key1 == key2

    def test_cache_key_differs_by_voice(self, tmp_path) -> None:
        """Different voices must produce different cache keys."""
        cache = TTSCache(tmp_path)
        key1 = cache.make_key("hello", "openai", "nova", "tts-1")
        key2 = cache.make_key("hello", "openai", "echo", "tts-1")
        assert key1 != key2

    def test_cache_miss_then_hit(self, tmp_path) -> None:
        """After put(), has() and get() must return the cached data."""
        cache = TTSCache(str(tmp_path))
        key = cache.make_key("test text", "openai", "nova", "tts-1")
        assert cache.has(key) is False
        assert cache.get(key) is None
        audio_data = b"\xff\xfb\x90\x00" * 100  # fake mp3 bytes
        cache.put(key, audio_data)
        assert cache.has(key) is True
        assert cache.get(key) == audio_data

    def test_cache_url_for(self, tmp_path) -> None:
        """url_for must return the expected static route path."""
        cache = TTSCache(str(tmp_path))
        key = cache.make_key("test", "openai", "nova", "tts-1")
        url = cache.url_for(key)
        assert url == f"/api/tts/cache/{key}.mp3"


class TestOpenAITTSProvider:
    """Test OpenAITTSProvider implementation."""

    def test_provider_name(self) -> None:
        """Provider name must be 'openai'."""
        provider = OpenAITTSProvider(model="tts-1")
        assert provider.name == "openai"

    def test_supported_voices(self) -> None:
        """Must return all 6 OpenAI TTS voices."""
        provider = OpenAITTSProvider(model="tts-1")
        voices = provider.supported_voices()
        assert "nova" in voices
        assert "alloy" in voices
        assert len(voices) == 6

    @pytest.mark.asyncio
    async def test_synthesize_calls_openai(self) -> None:
        """synthesize() must call OpenAI API with correct parameters."""
        fake_audio = b"\xff\xfb\x90\x00" * 50
        mock_response = MagicMock()
        mock_response.read = MagicMock(return_value=fake_audio)

        mock_speech = MagicMock()
        mock_speech.create = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.audio = MagicMock()
        mock_client.audio.speech = mock_speech

        provider = OpenAITTSProvider(model="tts-1")
        provider._client = mock_client

        result = await provider.synthesize("Hola mundo", "nova")
        assert result == fake_audio
        mock_speech.create.assert_called_once_with(
            model="tts-1",
            voice="nova",
            input="Hola mundo",
            response_format="mp3",
        )