"""Tests for the audio retrain/discard endpoints."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import rpg_scribe.web.routers.audio as audio_module
from rpg_scribe.web.routers.audio import router


@pytest.fixture
def audio_app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
async def client(audio_app):
    transport = ASGITransport(app=audio_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRetrainEndpoint:
    async def test_copies_wav_and_creates_json(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        resp = await client.post(
            "/api/audio/sess1/1234.56_Ana.wav/retrain",
            json={
                "original": "hola mundo",
                "corrected": "hola mundo!",
                "speaker": "Ana",
                "timestamp": 1234.56,
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert (tmp_path / "retrain" / "sess1" / "1234.56_Ana.wav").read_bytes() == b"RIFF"
        meta = json.loads(
            (tmp_path / "retrain" / "sess1" / "1234.56_Ana.json").read_text(encoding="utf-8")
        )
        assert meta["original"] == "hola mundo"
        assert meta["corrected"] == "hola mundo!"
        assert meta["speaker"] == "Ana"
        assert meta["timestamp"] == 1234.56

    async def test_source_wav_remains_after_retrain(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        await client.post(
            "/api/audio/sess1/1234.56_Ana.wav/retrain",
            json={"original": "x", "corrected": "y", "speaker": "Ana", "timestamp": 1234.56},
        )
        assert src.exists()  # copy, not move

    async def test_returns_404_if_wav_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        resp = await client.post(
            "/api/audio/sess1/missing.wav/retrain",
            json={"original": "", "corrected": "", "speaker": "", "timestamp": 0},
        )
        assert resp.status_code == 404


class TestDiscardEndpoint:
    async def test_moves_wav_to_discard(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        src = tmp_path / "sess1" / "1234.56_Ana.wav"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"RIFF")

        resp = await client.post("/api/audio/sess1/1234.56_Ana.wav/discard")
        assert resp.status_code == 200
        assert not src.exists()
        assert (tmp_path / "discard" / "sess1" / "1234.56_Ana.wav").read_bytes() == b"RIFF"

    async def test_idempotent_if_wav_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(audio_module, "_audio_base", lambda: tmp_path)
        resp = await client.post("/api/audio/sess1/nonexistent.wav/discard")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
