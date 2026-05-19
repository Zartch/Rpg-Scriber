"""Tests for the Discord TTS endpoints (/narrate-discord + control endpoints)."""

from __future__ import annotations

import json as json_mod
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rpg_scribe.core.models import TTSConfig
from rpg_scribe.tts.cache import TTSCache
from rpg_scribe.web.routers import tts as tts_router
from rpg_scribe.web.routes import router as core_router
from rpg_scribe.web.state import WebState


def _make_app(*, tts_config=None, tts_provider=None, tts_cache=None, application=None) -> FastAPI:
    app = FastAPI()
    core_router.state = WebState()
    core_router.database = None
    core_router.config = None
    core_router.event_bus = None
    core_router.application = application
    core_router.export_root = None
    core_router.ws_manager = None
    core_router.tts_provider = tts_provider
    core_router.tts_cache = tts_cache
    core_router.tts_config = tts_config
    app.include_router(core_router)
    app.include_router(tts_router.router)
    return app


class TestNarrateDiscord:
    def test_returns_503_when_tts_disabled(self) -> None:
        app = _make_app(tts_config=TTSConfig(enabled=False))
        client = TestClient(app)
        resp = client.post("/api/tts/narrate-discord", json={"text": "hi"})
        assert resp.status_code == 503

    def test_returns_409_when_no_application(self, tmp_path) -> None:
        provider = MagicMock(name="provider")
        provider.name = "openai"
        app = _make_app(
            tts_config=TTSConfig(enabled=True),
            tts_provider=provider,
            tts_cache=TTSCache(str(tmp_path)),
            application=None,
        )
        client = TestClient(app)
        resp = client.post("/api/tts/narrate-discord", json={"text": "hi"})
        assert resp.status_code == 409
        assert "not connected" in resp.json()["detail"]

    def test_returns_409_when_no_voice_client(self, tmp_path) -> None:
        provider = MagicMock(name="provider")
        provider.name = "openai"
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=None)
        application = MagicMock()
        application.get_discord_tts_player = MagicMock(return_value=player)

        app = _make_app(
            tts_config=TTSConfig(enabled=True),
            tts_provider=provider,
            tts_cache=TTSCache(str(tmp_path)),
            application=application,
        )
        client = TestClient(app)
        resp = client.post("/api/tts/narrate-discord", json={"text": "hi"})
        assert resp.status_code == 409
        assert "not connected" in resp.json()["detail"]

    def test_happy_path_caches_wav_and_starts(self, tmp_path) -> None:
        # PCM 24kHz mono, 4 samples → 8 bytes.
        provider = MagicMock(name="provider")
        provider.name = "openai"
        provider.synthesize = AsyncMock(return_value=b"\x00\x00\x01\x00\x02\x00\x03\x00")

        started: list = []

        async def fake_start_queue(paths):
            started.extend(paths)

        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.start_queue = AsyncMock(side_effect=fake_start_queue)
        application = MagicMock()
        application.get_discord_tts_player = MagicMock(return_value=player)

        cache = TTSCache(str(tmp_path))
        app = _make_app(
            tts_config=TTSConfig(enabled=True),
            tts_provider=provider,
            tts_cache=cache,
            application=application,
        )
        client = TestClient(app)
        resp = client.post(
            "/api/tts/narrate-discord",
            json={"text": "Hola mundo.\n\nSegundo parrafo."},
        )
        assert resp.status_code == 200
        lines = [json_mod.loads(ln) for ln in resp.text.strip().split("\n") if ln.strip()]
        # Two chunk lines + one "started"
        chunk_lines = [ln for ln in lines if "audio_url" in ln]
        assert len(chunk_lines) == 2
        for ln in chunk_lines:
            assert ln["audio_url"].endswith(".wav")
        assert lines[-1]["status"] == "started"
        assert len(started) == 2  # two WAVs queued

    def test_reuses_browser_cache(self, tmp_path) -> None:
        """If /narrate ran first, /narrate-discord must NOT call synthesize again."""
        provider = MagicMock(name="provider")
        provider.name = "openai"
        provider.synthesize = AsyncMock(return_value=b"\x00\x00\x01\x00")

        cache = TTSCache(str(tmp_path))
        # Pre-populate the cache (simulating a prior /narrate call).
        key = cache.make_key("Cached text.", "openai", "nova", "tts-1")
        cache.put(key, b"RIFF\x00\x00\x00\x00WAVE")  # bogus but present

        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.start_queue = AsyncMock(return_value=None)
        application = MagicMock()
        application.get_discord_tts_player = MagicMock(return_value=player)

        app = _make_app(
            tts_config=TTSConfig(enabled=True, voice="nova", model="tts-1"),
            tts_provider=provider,
            tts_cache=cache,
            application=application,
        )
        client = TestClient(app)
        resp = client.post("/api/tts/narrate-discord", json={"text": "Cached text."})
        assert resp.status_code == 200
        provider.synthesize.assert_not_called()

    def test_shared_cache_end_to_end(self, tmp_path) -> None:
        """Real flow: /narrate fills cache, then /narrate-discord reuses every chunk."""
        call_count = 0

        async def fake_synthesize(text, voice, response_format="mp3"):
            nonlocal call_count
            call_count += 1
            # 24 kHz mono int16 LE silence; resampler will accept any even length
            return b"\x00\x00" * 16

        provider = MagicMock(name="provider")
        provider.name = "openai"
        provider.synthesize = AsyncMock(side_effect=fake_synthesize)

        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.start_queue = AsyncMock(return_value=None)
        application = MagicMock()
        application.get_discord_tts_player = MagicMock(return_value=player)

        cache = TTSCache(str(tmp_path))
        app = _make_app(
            tts_config=TTSConfig(enabled=True, voice="nova", model="tts-1"),
            tts_provider=provider,
            tts_cache=cache,
            application=application,
        )
        client = TestClient(app)
        text = "Primer parrafo.\n\nSegundo parrafo.\n\nTercer parrafo."

        # First call (browser): all 3 chunks synthesized.
        resp1 = client.post("/api/tts/narrate", json={"text": text})
        assert resp1.status_code == 200
        assert call_count == 3
        lines1 = [json_mod.loads(ln) for ln in resp1.text.strip().split("\n") if ln.strip()]
        assert all(ln["cached"] is False for ln in lines1 if "audio_url" in ln)

        # Second call (discord): the SAME 3 chunks must come from cache.
        call_count = 0
        resp2 = client.post("/api/tts/narrate-discord", json={"text": text})
        assert resp2.status_code == 200
        assert call_count == 0, "discord endpoint must reuse browser cache"
        lines2 = [json_mod.loads(ln) for ln in resp2.text.strip().split("\n") if ln.strip()]
        chunk_lines = [ln for ln in lines2 if "audio_url" in ln]
        assert all(ln["cached"] is True for ln in chunk_lines)
        # Same URLs in both responses (proves identical keys → identical files).
        urls1 = [ln["audio_url"] for ln in lines1 if "audio_url" in ln]
        urls2 = [ln["audio_url"] for ln in chunk_lines]
        assert urls1 == urls2


class TestControlEndpoints:
    def _app_with_player(self, player, tmp_path):
        application = MagicMock()
        application.get_discord_tts_player = MagicMock(return_value=player)
        return _make_app(
            tts_config=TTSConfig(enabled=True),
            tts_provider=MagicMock(name="prov"),
            tts_cache=TTSCache(str(tmp_path)),
            application=application,
        )

    def test_pause(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.status = MagicMock(return_value={"index": 0, "paused": True})
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.post("/api/tts/discord/pause")
        assert resp.status_code == 200
        player.pause.assert_called_once()

    def test_resume(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.status = MagicMock(return_value={"index": 0, "paused": False})
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.post("/api/tts/discord/resume")
        assert resp.status_code == 200
        player.resume.assert_called_once()

    def test_play_at(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.play_at = AsyncMock(return_value=None)
        player.status = MagicMock(return_value={"index": 2})
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.post("/api/tts/discord/play-at", json={"index": 2})
        assert resp.status_code == 200
        player.play_at.assert_awaited_once_with(2)

    def test_play_at_out_of_range(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.play_at = AsyncMock(side_effect=IndexError(99))
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.post("/api/tts/discord/play-at", json={"index": 99})
        assert resp.status_code == 400

    def test_stop(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.stop = AsyncMock(return_value=None)
        player.status = MagicMock(return_value={"index": -1, "total": 0})
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.post("/api/tts/discord/stop")
        assert resp.status_code == 200
        player.stop.assert_awaited_once()

    def test_status_when_disconnected(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=None)
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.get("/api/tts/discord/status")
        assert resp.status_code == 200
        assert resp.json() == {"connected": False}

    def test_status_when_connected(self, tmp_path) -> None:
        player = MagicMock()
        player.get_voice_client = MagicMock(return_value=MagicMock())
        player.status = MagicMock(return_value={"index": 1, "total": 3, "paused": False, "playing": True, "active": True})
        app = self._app_with_player(player, tmp_path)
        client = TestClient(app)
        resp = client.get("/api/tts/discord/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["index"] == 1
