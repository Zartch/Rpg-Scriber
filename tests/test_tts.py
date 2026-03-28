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

from fastapi.testclient import TestClient


def _make_test_app(tts_provider=None, tts_cache=None, tts_config=None):
    """Create a minimal FastAPI app with TTS routes for testing."""
    from fastapi import FastAPI
    from rpg_scribe.web.routes import router
    from rpg_scribe.web.routers import tts as tts_router
    from rpg_scribe.web.state import WebState

    app = FastAPI()
    state = WebState()
    router.state = state
    router.database = None
    router.config = None
    router.event_bus = None
    router.application = None
    router.export_root = None
    router.ws_manager = None
    router.tts_provider = tts_provider
    router.tts_cache = tts_cache
    router.tts_config = tts_config
    app.include_router(router)
    app.include_router(tts_router.router)
    return app


class TestTTSNarrateEndpoint:
    """Test POST /api/tts/narrate streaming endpoint."""

    def test_narrate_disabled_returns_503(self) -> None:
        """Endpoint must return 503 when TTS is disabled."""
        tts_config = TTSConfig(enabled=False)
        app = _make_test_app(tts_config=tts_config)
        client = TestClient(app)
        resp = client.post("/api/tts/narrate", json={"text": "Hello"})
        assert resp.status_code == 503

    def test_narrate_streams_ndjson(self, tmp_path) -> None:
        """Endpoint must stream one NDJSON line per paragraph with audio_url."""
        import json
        fake_audio = b"\xff\xfb\x90\x00" * 50
        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(return_value=fake_audio)

        tts_config = TTSConfig(enabled=True)
        tts_cache = TTSCache(str(tmp_path))
        app = _make_test_app(tts_provider=mock_provider, tts_cache=tts_cache, tts_config=tts_config)
        client = TestClient(app)

        resp = client.post("/api/tts/narrate", json={"text": "First paragraph.\n\nSecond paragraph."})
        assert resp.status_code == 200
        assert "application/x-ndjson" in resp.headers["content-type"]

        lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) == 2
        assert lines[0]["index"] == 0
        assert lines[0]["total"] == 2
        assert lines[0]["audio_url"].startswith("/api/tts/cache/")
        assert lines[1]["index"] == 1

    def test_narrate_uses_cache(self, tmp_path) -> None:
        """When paragraph is cached, synthesize() must not be called."""
        import json
        fake_audio = b"\xff\xfb\x90\x00" * 50
        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(return_value=fake_audio)

        tts_config = TTSConfig(enabled=True, voice="nova", model="tts-1")
        tts_cache = TTSCache(str(tmp_path))
        key = tts_cache.make_key("Cached text.", "openai", "nova", "tts-1")
        tts_cache.put(key, fake_audio)

        app = _make_test_app(tts_provider=mock_provider, tts_cache=tts_cache, tts_config=tts_config)
        client = TestClient(app)

        resp = client.post("/api/tts/narrate", json={"text": "Cached text."})
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
        assert lines[0]["cached"] is True
        mock_provider.synthesize.assert_not_called()


class TestTTSVoicesEndpoint:
    """Test GET /api/tts/voices endpoint."""

    def test_voices_when_enabled(self) -> None:
        """Must return provider name, voices list, and current voice."""
        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.supported_voices.return_value = ["alloy", "nova", "echo"]
        tts_config = TTSConfig(enabled=True, voice="nova")
        app = _make_test_app(tts_provider=mock_provider, tts_config=tts_config)
        client = TestClient(app)

        resp = client.get("/api/tts/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert "nova" in data["voices"]
        assert data["current"] == "nova"

    def test_voices_when_disabled(self) -> None:
        """Must return 503 when TTS is disabled."""
        tts_config = TTSConfig(enabled=False)
        app = _make_test_app(tts_config=tts_config)
        client = TestClient(app)

        resp = client.get("/api/tts/voices")
        assert resp.status_code == 503


class TestTTSIntegration:
    """End-to-end integration tests for the full narration flow."""

    def test_full_narration_flow_with_cache(self, tmp_path) -> None:
        """Second narration of same text must use cache (0 API calls)."""
        import json
        fake_audio = b"\xff\xfb\x90\x00" * 50
        call_count = 0

        async def mock_synthesize(text, voice):
            nonlocal call_count
            call_count += 1
            return fake_audio

        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(side_effect=mock_synthesize)

        tts_config = TTSConfig(enabled=True, voice="nova", model="tts-1")
        tts_cache = TTSCache(str(tmp_path))
        app = _make_test_app(tts_provider=mock_provider, tts_cache=tts_cache, tts_config=tts_config)
        client = TestClient(app)

        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."

        # First narration — 3 API calls
        resp1 = client.post("/api/tts/narrate", json={"text": text})
        assert resp1.status_code == 200
        assert call_count == 3
        lines1 = [json.loads(l) for l in resp1.text.strip().split("\n") if l.strip()]
        assert all(l["cached"] is False for l in lines1)

        # Second narration — 0 API calls (all cached)
        call_count = 0
        resp2 = client.post("/api/tts/narrate", json={"text": text})
        assert resp2.status_code == 200
        assert call_count == 0
        lines2 = [json.loads(l) for l in resp2.text.strip().split("\n") if l.strip()]
        assert all(l["cached"] is True for l in lines2)
        assert [l["audio_url"] for l in lines1] == [l["audio_url"] for l in lines2]

    def test_narrate_handles_provider_error_gracefully(self, tmp_path) -> None:
        """If one paragraph fails, endpoint yields an error and continues."""
        import json
        fake_audio = b"\xff\xfb\x90\x00" * 50

        async def flaky_synthesize(text, voice):
            if "fail" in text.lower():
                raise RuntimeError("API timeout")
            return fake_audio

        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(side_effect=flaky_synthesize)

        tts_config = TTSConfig(enabled=True, voice="nova", model="tts-1")
        tts_cache = TTSCache(str(tmp_path))
        app = _make_test_app(tts_provider=mock_provider, tts_cache=tts_cache, tts_config=tts_config)
        client = TestClient(app)

        text = "Good paragraph.\n\nThis will fail.\n\nAnother good one."
        resp = client.post("/api/tts/narrate", json={"text": text})
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) == 3
        assert "audio_url" in lines[0]
        assert "error" in lines[1]
        assert "audio_url" in lines[2]
