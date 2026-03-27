"""Test TTS configuration."""

from __future__ import annotations

import pytest

from rpg_scribe.core.models import TTSConfig


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