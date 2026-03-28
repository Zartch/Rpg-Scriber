# TTS Narration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add text-to-speech narration of summaries in the Web UI with paragraph-level streaming, disk caching, and pluggable provider architecture.

**Architecture:** Pluggable TTS provider (ABC pattern matching existing Transcriber/Summarizer), OpenAI as first backend. NDJSON streaming endpoint sends audio URLs paragraph-by-paragraph. Frontend plays first paragraph immediately, queues the rest. Disk cache keyed by content hash avoids redundant API calls.

**Tech Stack:** Python 3.10+, FastAPI StreamingResponse, openai (AsyncOpenAI), SHA-256 hashing, HTML5 `<audio>`, ReadableStream NDJSON parsing.

**Spec:** [`docs/superpowers/specs/2026-03-27-tts-narration-design.md`](../specs/2026-03-27-tts-narration-design.md)

---

## Phases

| Fase | Tareas | Paralelizable |
|------|--------|---------------|
| **Fase 1: Core backend** | Tasks 1-4 | Tasks 1, 2 en paralelo; Task 3 requiere ambas; Task 4 requiere Task 3 |
| **Fase 2: API endpoints** | Tasks 5-6 | Secuencial (5 → 6) |
| **Fase 3: Frontend** | Tasks 7-8 | Task 7 requiere Fase 2; Task 8 en paralelo con Task 7 |
| **Fase 4: Integración** | Task 9 | Requiere Fases 1-3 completadas |

---

## File Structure

**New files:**
- `src/rpg_scribe/tts/__init__.py` — Package init
- `src/rpg_scribe/tts/base.py` — `BaseTTSProvider` ABC
- `src/rpg_scribe/tts/openai_provider.py` — `OpenAITTSProvider` implementation
- `src/rpg_scribe/tts/cache.py` — `TTSCache` disk cache
- `tests/test_tts.py` — All TTS tests (cache, provider, routes)

**Modified files:**
- `src/rpg_scribe/core/models.py` — Add `TTSConfig` dataclass
- `src/rpg_scribe/config.py` — Load `[tts]` section from TOML
- `config/default.toml` — Add `[tts]` section
- `src/rpg_scribe/web/app.py` — Mount TTS cache dir, attach provider to router
- `src/rpg_scribe/web/routes.py` — Add `/api/tts/narrate`, `/api/tts/voices` endpoints
- `src/rpg_scribe/web/static/index.html` — Add "Narrar" buttons in summary tabs
- `src/rpg_scribe/web/static/app.js` — TTS playback logic with queue
- `src/rpg_scribe/web/static/style.css` — Narrate button and playback styles

---

## Fase 1: Core Backend (Tasks 1-4)

### Task 1: TTSConfig dataclass + TOML config (parallelizable with Task 2)

**Files:**
- Modify: `src/rpg_scribe/core/models.py` (after `SummarizerConfig`, ~line 185)
- Modify: `src/rpg_scribe/config.py` (in `AppConfig` ~line 41, in `_apply_defaults_to_config` ~line 77)
- Modify: `config/default.toml` (append at end)
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write failing test for TTSConfig defaults**

```python
# tests/test_tts.py
"""Tests for TTS narration feature."""
from __future__ import annotations

import pytest


class TestTTSConfig:
    def test_tts_config_defaults(self):
        from rpg_scribe.core.models import TTSConfig

        cfg = TTSConfig()
        assert cfg.enabled is False
        assert cfg.provider == "openai"
        assert cfg.voice == "nova"
        assert cfg.model == "tts-1"
        assert cfg.cache_dir == "data/tts_cache"

    def test_tts_config_custom(self):
        from rpg_scribe.core.models import TTSConfig

        cfg = TTSConfig(enabled=True, provider="edge", voice="alloy", model="tts-1-hd", cache_dir="/tmp/cache")
        assert cfg.enabled is True
        assert cfg.provider == "edge"
        assert cfg.voice == "alloy"
        assert cfg.model == "tts-1-hd"
        assert cfg.cache_dir == "/tmp/cache"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts.py::TestTTSConfig -v`
Expected: FAIL with `ImportError` (TTSConfig not defined yet)

- [ ] **Step 3: Add TTSConfig dataclass to models.py**

In `src/rpg_scribe/core/models.py`, after the `SummarizerConfig` class (line ~185), add:

```python
@dataclass
class TTSConfig:
    """Configuration for text-to-speech narration."""

    enabled: bool = False
    provider: str = "openai"
    voice: str = "nova"
    model: str = "tts-1"
    cache_dir: str = "data/tts_cache"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts.py::TestTTSConfig -v`
Expected: PASS

- [ ] **Step 5: Write failing test for config loading from TOML**

Append to `tests/test_tts.py`:

```python
class TestTTSConfigLoading:
    def test_app_config_has_tts(self):
        from rpg_scribe.config import AppConfig

        config = AppConfig()
        assert hasattr(config, "tts")
        assert config.tts.enabled is False

    def test_tts_loaded_from_toml(self, tmp_path):
        from rpg_scribe.config import load_app_config

        toml_content = b"""
[tts]
enabled = true
provider = "openai"
voice = "echo"
model = "tts-1-hd"
cache_dir = "custom/cache"
"""
        defaults_file = tmp_path / "defaults.toml"
        defaults_file.write_bytes(toml_content)
        config = load_app_config(defaults_path=defaults_file)
        assert config.tts.enabled is True
        assert config.tts.voice == "echo"
        assert config.tts.model == "tts-1-hd"
        assert config.tts.cache_dir == "custom/cache"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_tts.py::TestTTSConfigLoading -v`
Expected: FAIL (AppConfig has no `tts` attribute)

- [ ] **Step 7: Add tts field to AppConfig and load from TOML**

In `src/rpg_scribe/config.py`:

1. Add import of `TTSConfig` to the imports from `rpg_scribe.core.models`:
```python
from rpg_scribe.core.models import (
    ...,
    TTSConfig,
)
```

2. Add field to `AppConfig` (after `summarizer` field, ~line 58):
```python
    tts: TTSConfig = field(default_factory=TTSConfig)
```

3. Add TTS loading in `_apply_defaults_to_config` (after the Summarizer section, ~line 99):
```python
    # TTS
    tts_data = defaults.get("tts", {})
    for key, value in tts_data.items():
        if hasattr(config.tts, key):
            setattr(config.tts, key, value)
```

- [ ] **Step 8: Add [tts] section to default.toml**

Append to `config/default.toml`:

```toml

[tts]
enabled = false
provider = "openai"
voice = "nova"
model = "tts-1"
cache_dir = "data/tts_cache"
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_tts.py -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add src/rpg_scribe/core/models.py src/rpg_scribe/config.py config/default.toml tests/test_tts.py
git commit -m "feat(tts): add TTSConfig dataclass and TOML config loading"
```

---

### Task 2: TTSCache (parallelizable with Task 1)

**Files:**
- Create: `src/rpg_scribe/tts/__init__.py`
- Create: `src/rpg_scribe/tts/cache.py`
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write failing tests for TTSCache**

Append to `tests/test_tts.py`:

```python
class TestTTSCache:
    def test_cache_key_is_deterministic(self):
        from rpg_scribe.tts.cache import TTSCache

        cache = TTSCache("/tmp/test_cache")
        key1 = cache.make_key("hello world", "openai", "nova", "tts-1")
        key2 = cache.make_key("hello world", "openai", "nova", "tts-1")
        assert key1 == key2

    def test_cache_key_differs_by_voice(self):
        from rpg_scribe.tts.cache import TTSCache

        cache = TTSCache("/tmp/test_cache")
        key1 = cache.make_key("hello", "openai", "nova", "tts-1")
        key2 = cache.make_key("hello", "openai", "echo", "tts-1")
        assert key1 != key2

    def test_cache_miss_then_hit(self, tmp_path):
        from rpg_scribe.tts.cache import TTSCache

        cache = TTSCache(str(tmp_path))
        key = cache.make_key("test text", "openai", "nova", "tts-1")

        assert cache.has(key) is False
        assert cache.get(key) is None

        audio_data = b"\xff\xfb\x90\x00" * 100  # fake mp3 bytes
        cache.put(key, audio_data)

        assert cache.has(key) is True
        assert cache.get(key) == audio_data

    def test_cache_url_for(self, tmp_path):
        from rpg_scribe.tts.cache import TTSCache

        cache = TTSCache(str(tmp_path))
        key = cache.make_key("test", "openai", "nova", "tts-1")
        url = cache.url_for(key)
        assert url == f"/api/tts/cache/{key}.mp3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tts.py::TestTTSCache -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rpg_scribe.tts'`

- [ ] **Step 3: Create tts package and cache module**

Create `src/rpg_scribe/tts/__init__.py`:
```python
"""Text-to-speech narration for RPG Scribe."""
```

Create `src/rpg_scribe/tts/cache.py`:
```python
"""Disk cache for TTS audio files."""
from __future__ import annotations

import hashlib
from pathlib import Path


class TTSCache:
    """Simple disk-based cache for generated TTS audio.

    Files are stored as ``{hash}.mp3`` where hash is a SHA-256 of
    the text + provider + voice + model combination.
    """

    def __init__(self, cache_dir: str) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def make_key(self, text: str, provider: str, voice: str, model: str) -> str:
        """Generate a deterministic cache key from the synthesis parameters."""
        raw = f"{text}|{provider}|{voice}|{model}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.mp3"

    def has(self, key: str) -> bool:
        return self._path(key).is_file()

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if path.is_file():
            return path.read_bytes()
        return None

    def put(self, key: str, audio: bytes) -> Path:
        path = self._path(key)
        path.write_bytes(audio)
        return path

    def url_for(self, key: str) -> str:
        return f"/api/tts/cache/{key}.mp3"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tts.py::TestTTSCache -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/tts/__init__.py src/rpg_scribe/tts/cache.py tests/test_tts.py
git commit -m "feat(tts): add TTSCache disk cache with SHA-256 key"
```

---

### Task 3: BaseTTSProvider ABC (requires Tasks 1 & 2)

**Files:**
- Create: `src/rpg_scribe/tts/base.py`

- [ ] **Step 1: Create BaseTTSProvider ABC**

Create `src/rpg_scribe/tts/base.py`:
```python
"""Abstract base class for TTS providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):
    """Interface that any TTS provider must implement."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> bytes:
        """Generate mp3 audio bytes from a text fragment."""
        ...

    @abstractmethod
    def supported_voices(self) -> list[str]:
        """Return the list of available voice identifiers."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai', 'edge')."""
        ...
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/tts/base.py
git commit -m "feat(tts): add BaseTTSProvider ABC"
```

---

### Task 4: OpenAITTSProvider (requires Task 3)

**Files:**
- Create: `src/rpg_scribe/tts/openai_provider.py`
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write failing test for OpenAITTSProvider**

Append to `tests/test_tts.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch


class TestOpenAITTSProvider:
    def test_provider_name(self):
        from rpg_scribe.tts.openai_provider import OpenAITTSProvider

        provider = OpenAITTSProvider(model="tts-1")
        assert provider.name == "openai"

    def test_supported_voices(self):
        from rpg_scribe.tts.openai_provider import OpenAITTSProvider

        provider = OpenAITTSProvider(model="tts-1")
        voices = provider.supported_voices()
        assert "nova" in voices
        assert "alloy" in voices
        assert len(voices) == 6

    @pytest.mark.asyncio
    async def test_synthesize_calls_openai(self):
        from rpg_scribe.tts.openai_provider import OpenAITTSProvider

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts.py::TestOpenAITTSProvider -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement OpenAITTSProvider**

Create `src/rpg_scribe/tts/openai_provider.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tts.py::TestOpenAITTSProvider -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/tts/openai_provider.py tests/test_tts.py
git commit -m "feat(tts): add OpenAITTSProvider with lazy client init"
```

---

## Fase 2: API Endpoints (Tasks 5-6, sequential)

### Task 5: TTS narrate streaming endpoint (requires Fase 1)

**Files:**
- Modify: `src/rpg_scribe/web/routes.py`
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write failing test for narrate endpoint**

Append to `tests/test_tts.py`:

```python
from fastapi.testclient import TestClient


def _make_test_app(tts_provider=None, tts_cache=None, tts_config=None):
    """Create a minimal FastAPI app with TTS routes for testing."""
    from fastapi import FastAPI
    from rpg_scribe.web.routes import router, WebState

    app = FastAPI()
    state = WebState()
    router.state = state
    router.database = None
    router.config = None
    router.event_bus = None
    router.application = None
    router.export_root = None
    router.tts_provider = tts_provider
    router.tts_cache = tts_cache
    router.tts_config = tts_config
    app.include_router(router)
    return app


class TestTTSNarrateEndpoint:
    def test_narrate_disabled_returns_503(self):
        from rpg_scribe.core.models import TTSConfig

        tts_config = TTSConfig(enabled=False)
        app = _make_test_app(tts_config=tts_config)
        client = TestClient(app)
        resp = client.post("/api/tts/narrate", json={"text": "Hello"})
        assert resp.status_code == 503

    def test_narrate_streams_ndjson(self, tmp_path):
        from rpg_scribe.core.models import TTSConfig
        from rpg_scribe.tts.cache import TTSCache

        fake_audio = b"\xff\xfb\x90\x00" * 50

        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(return_value=fake_audio)

        tts_config = TTSConfig(enabled=True)
        tts_cache = TTSCache(str(tmp_path))

        app = _make_test_app(
            tts_provider=mock_provider,
            tts_cache=tts_cache,
            tts_config=tts_config,
        )
        client = TestClient(app)

        text = "First paragraph.\n\nSecond paragraph."
        resp = client.post("/api/tts/narrate", json={"text": text})
        assert resp.status_code == 200
        assert "application/x-ndjson" in resp.headers["content-type"]

        import json
        lines = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        assert lines[0]["index"] == 0
        assert lines[0]["total"] == 2
        assert lines[0]["audio_url"].startswith("/api/tts/cache/")
        assert lines[1]["index"] == 1

    def test_narrate_uses_cache(self, tmp_path):
        from rpg_scribe.core.models import TTSConfig
        from rpg_scribe.tts.cache import TTSCache

        fake_audio = b"\xff\xfb\x90\x00" * 50

        mock_provider = MagicMock()
        mock_provider.name = "openai"
        mock_provider.synthesize = AsyncMock(return_value=fake_audio)

        tts_config = TTSConfig(enabled=True, voice="nova", model="tts-1")
        tts_cache = TTSCache(str(tmp_path))

        # Pre-populate cache for the single paragraph
        key = tts_cache.make_key("Cached text.", "openai", "nova", "tts-1")
        tts_cache.put(key, fake_audio)

        app = _make_test_app(
            tts_provider=mock_provider,
            tts_cache=tts_cache,
            tts_config=tts_config,
        )
        client = TestClient(app)

        resp = client.post("/api/tts/narrate", json={"text": "Cached text."})
        assert resp.status_code == 200

        import json
        lines = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
        assert lines[0]["cached"] is True
        mock_provider.synthesize.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tts.py::TestTTSNarrateEndpoint -v`
Expected: FAIL (endpoint does not exist yet)

- [ ] **Step 3: Implement narrate endpoint in routes.py**

Add these imports at the top of `src/rpg_scribe/web/routes.py`:

```python
import json as json_mod
from fastapi.responses import StreamingResponse
```

Add the endpoint at the end of the file (before the last line, which is typically the static mount or EOF):

```python
@router.post("/api/tts/narrate")
async def tts_narrate(body: dict):
    """Stream TTS audio URLs for each paragraph via NDJSON."""
    tts_config = getattr(router, "tts_config", None)
    if tts_config is None or not tts_config.enabled:
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    tts_provider = getattr(router, "tts_provider", None)
    tts_cache = getattr(router, "tts_cache", None)
    if tts_provider is None or tts_cache is None:
        raise HTTPException(status_code=503, detail="TTS provider not configured")

    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    voice = body.get("voice") or tts_config.voice
    provider_name = tts_provider.name
    model = tts_config.model

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        raise HTTPException(status_code=400, detail="No paragraphs found in text")

    total = len(paragraphs)

    async def generate():
        for idx, paragraph in enumerate(paragraphs):
            key = tts_cache.make_key(paragraph, provider_name, voice, model)
            cached = tts_cache.has(key)
            if not cached:
                try:
                    audio = await tts_provider.synthesize(paragraph, voice)
                    tts_cache.put(key, audio)
                except Exception as exc:
                    line = json_mod.dumps({"index": idx, "total": total, "error": str(exc)})
                    yield line + "\n"
                    continue
            line = json_mod.dumps({
                "index": idx,
                "total": total,
                "audio_url": tts_cache.url_for(key),
                "cached": cached,
            })
            yield line + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tts.py::TestTTSNarrateEndpoint -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/routes.py tests/test_tts.py
git commit -m "feat(tts): add POST /api/tts/narrate NDJSON streaming endpoint"
```

---

### Task 6: TTS voices endpoint + cache static mount (requires Task 5)

**Files:**
- Modify: `src/rpg_scribe/web/routes.py`
- Modify: `src/rpg_scribe/web/app.py`
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write failing test for voices endpoint**

Append to `tests/test_tts.py`:

```python
class TestTTSVoicesEndpoint:
    def test_voices_when_enabled(self):
        from rpg_scribe.core.models import TTSConfig

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

    def test_voices_when_disabled(self):
        from rpg_scribe.core.models import TTSConfig

        tts_config = TTSConfig(enabled=False)
        app = _make_test_app(tts_config=tts_config)
        client = TestClient(app)

        resp = client.get("/api/tts/voices")
        assert resp.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts.py::TestTTSVoicesEndpoint -v`
Expected: FAIL (endpoint does not exist)

- [ ] **Step 3: Add voices endpoint to routes.py**

Add after the `tts_narrate` endpoint in `src/rpg_scribe/web/routes.py`:

```python
@router.get("/api/tts/voices")
async def tts_voices():
    """Return available TTS voices for the active provider."""
    tts_config = getattr(router, "tts_config", None)
    if tts_config is None or not tts_config.enabled:
        raise HTTPException(status_code=503, detail="TTS is not enabled")

    tts_provider = getattr(router, "tts_provider", None)
    if tts_provider is None:
        raise HTTPException(status_code=503, detail="TTS provider not configured")

    return {
        "provider": tts_provider.name,
        "voices": tts_provider.supported_voices(),
        "current": tts_config.voice,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tts.py::TestTTSVoicesEndpoint -v`
Expected: All PASS

- [ ] **Step 5: Wire TTS into app.py**

In `src/rpg_scribe/web/app.py`, update `create_app()`:

1. After the line `router.export_root = ...` (~line 134), add:
```python
    # TTS provider and cache
    tts_config = getattr(config, "tts", None)
    router.tts_config = tts_config  # type: ignore[attr-defined]
    router.tts_provider = None  # type: ignore[attr-defined]
    router.tts_cache = None  # type: ignore[attr-defined]

    if tts_config and tts_config.enabled:
        from rpg_scribe.tts.cache import TTSCache

        tts_cache = TTSCache(tts_config.cache_dir)
        router.tts_cache = tts_cache  # type: ignore[attr-defined]

        if tts_config.provider == "openai":
            from rpg_scribe.tts.openai_provider import OpenAITTSProvider

            router.tts_provider = OpenAITTSProvider(model=tts_config.model)  # type: ignore[attr-defined]
            logger.info("TTS enabled: provider=%s, voice=%s", tts_config.provider, tts_config.voice)
        else:
            logger.warning("Unknown TTS provider: %s", tts_config.provider)
```

2. After the audio static mount (`app.mount("/audio", ...)`, ~line 158), add:
```python
    # Serve TTS cache as static files
    if tts_config and tts_config.enabled:
        tts_cache_dir = Path(tts_config.cache_dir)
        tts_cache_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/api/tts/cache", StaticFiles(directory=str(tts_cache_dir)), name="tts_cache")
```

- [ ] **Step 6: Run full TTS test suite**

Run: `pytest tests/test_tts.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/rpg_scribe/web/routes.py src/rpg_scribe/web/app.py tests/test_tts.py
git commit -m "feat(tts): add /api/tts/voices endpoint and wire TTS into app factory"
```

---

## Fase 3: Frontend (Tasks 7-8, parallelizable)

### Task 7: Narrate button + playback JS (requires Fase 2)

**Files:**
- Modify: `src/rpg_scribe/web/static/index.html`
- Modify: `src/rpg_scribe/web/static/app.js`

- [ ] **Step 1: Add "Narrar" buttons to each summary tab in index.html**

In `src/rpg_scribe/web/static/index.html`, add a narrate button inside each `.tab-content-actions` div:

For session-summary tab (inside `<div id="session-summary">`, after the existing button ~line 341):
```html
              <button id="btn-narrate-session" class="btn-small btn-narrate" title="Narrate this summary aloud" style="display:none">&#x1f50a; Narrar</button>
```

For session-chronology tab (inside `<div id="session-chronology">`, after the existing button ~line 350):
```html
              <button id="btn-narrate-chronology" class="btn-small btn-narrate" title="Narrate this chronology aloud" style="display:none">&#x1f50a; Narrar</button>
```

For campaign-summary tab (inside `<div id="campaign-summary">`, after the "View all" link ~line 360):
```html
              <button id="btn-narrate-campaign" class="btn-small btn-narrate" title="Narrate this campaign summary aloud" style="display:none">&#x1f50a; Narrar</button>
```

- [ ] **Step 2: Add TTS narration module to app.js**

Add the following block inside the `DOMContentLoaded` listener in `src/rpg_scribe/web/static/app.js`, after the `renderEditableSummary` and `saveParagraphEdit` functions (~after line 807):

```javascript
  // ── TTS Narration ───────────────────────────────────────────────
  var ttsEnabled = false;
  var ttsAudio = null;
  var ttsQueue = [];
  var ttsActiveBtn = null;
  var ttsTotalChunks = 0;
  var ttsPlayedChunks = 0;

  // Check if TTS is available on load
  fetch("/api/tts/voices")
    .then(function (r) {
      if (r.ok) {
        ttsEnabled = true;
        document.querySelectorAll(".btn-narrate").forEach(function (btn) {
          btn.style.display = "";
        });
      }
    })
    .catch(function () { /* TTS not available, buttons stay hidden */ });

  function getNarrateText(btnId) {
    if (btnId === "btn-narrate-session") {
      return sessionSummaryEl.textContent.trim();
    } else if (btnId === "btn-narrate-chronology") {
      return sessionChronologyEl.textContent.trim();
    } else if (btnId === "btn-narrate-campaign") {
      return campaignSummaryEl.textContent.trim();
    }
    return "";
  }

  function stopNarration() {
    if (ttsAudio) {
      ttsAudio.pause();
      ttsAudio.src = "";
      ttsAudio = null;
    }
    ttsQueue = [];
    ttsTotalChunks = 0;
    ttsPlayedChunks = 0;
    if (ttsActiveBtn) {
      ttsActiveBtn.innerHTML = "&#x1f50a; Narrar";
      ttsActiveBtn.classList.remove("narrating");
      ttsActiveBtn = null;
    }
  }

  function updateNarrateProgress() {
    if (ttsActiveBtn) {
      ttsActiveBtn.textContent = "Narrando (" + ttsPlayedChunks + "/" + ttsTotalChunks + ")";
    }
  }

  function playNext() {
    if (ttsQueue.length === 0) {
      // All done
      if (ttsActiveBtn) {
        ttsActiveBtn.textContent = "Completado";
        var doneBtn = ttsActiveBtn;
        setTimeout(function () {
          if (doneBtn === ttsActiveBtn || !ttsActiveBtn) {
            doneBtn.innerHTML = "&#x1f50a; Narrar";
            doneBtn.classList.remove("narrating");
            if (doneBtn === ttsActiveBtn) ttsActiveBtn = null;
          }
        }, 2000);
      }
      ttsAudio = null;
      return;
    }
    var url = ttsQueue.shift();
    ttsPlayedChunks++;
    updateNarrateProgress();
    ttsAudio = new Audio(url);
    ttsAudio.addEventListener("ended", playNext);
    ttsAudio.addEventListener("error", function () {
      console.error("TTS audio playback error for:", url);
      playNext(); // skip to next chunk
    });
    ttsAudio.play().catch(function (err) {
      console.error("TTS play failed:", err);
      playNext();
    });
  }

  async function startNarration(btn) {
    var text = getNarrateText(btn.id);
    if (!text) return;

    // If already narrating this button, stop
    if (ttsActiveBtn === btn) {
      stopNarration();
      return;
    }
    // If narrating something else, stop that first
    if (ttsActiveBtn) stopNarration();

    ttsActiveBtn = btn;
    btn.classList.add("narrating");
    btn.disabled = true;
    btn.innerHTML = "";
    btn.appendChild(createSpinner());
    btn.appendChild(document.createTextNode("Generando..."));

    try {
      var resp = await fetch("/api/tts/narrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text }),
      });

      if (!resp.ok) throw new Error("TTS request failed: " + resp.status);

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var firstChunkPlayed = false;

      while (true) {
        var result = await reader.read();
        if (result.done) break;
        buffer += decoder.decode(result.value, { stream: true });

        var lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete line in buffer

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line) continue;
          try {
            var chunk = JSON.parse(line);
            if (chunk.error) {
              console.warn("TTS error for paragraph " + chunk.index + ":", chunk.error);
              continue;
            }
            ttsTotalChunks = chunk.total;
            if (!firstChunkPlayed) {
              firstChunkPlayed = true;
              btn.disabled = false;
              ttsPlayedChunks = 0;
              ttsQueue = [];
              // Play first chunk immediately
              ttsQueue.push(chunk.audio_url);
              playNext();
            } else {
              ttsQueue.push(chunk.audio_url);
            }
          } catch (e) {
            console.warn("Failed to parse NDJSON line:", line);
          }
        }
      }
    } catch (err) {
      console.error("TTS narration failed:", err);
      stopNarration();
    }
  }

  // Bind narrate buttons
  ["btn-narrate-session", "btn-narrate-chronology", "btn-narrate-campaign"].forEach(function (id) {
    var btn = document.getElementById(id);
    if (btn) {
      btn.addEventListener("click", function () {
        startNarration(btn);
      });
    }
  });
```

- [ ] **Step 3: Get references to summary content elements**

Verify that the existing variables `sessionSummaryEl`, `sessionChronologyEl`, `campaignSummaryEl` are already defined in app.js. They should be — check near the top of the DOMContentLoaded listener. The code at line ~10-14 references:
```javascript
var sessionSummaryTab = document.getElementById("session-summary");
```

Find the actual `.summary-content` child elements that hold the text. Look for where `renderEditableSummary` is called — it takes `sessionSummaryEl` etc. as first argument. These are likely the `.summary-content` div children. Make sure `getNarrateText` references the correct elements that `renderEditableSummary` populates.

Check the variable names near the top of app.js. They should be something like:
```javascript
var sessionSummaryEl = sessionSummaryTab.querySelector(".summary-content");
var sessionChronologyEl = ...
var campaignSummaryEl = ...
```

Adjust `getNarrateText` function if the variable names differ.

- [ ] **Step 4: Test manually in browser**

1. Enable TTS in `config/default.toml`: set `enabled = true`
2. Start the app: `rpg-scribe` (or with a campaign)
3. Open Web UI at http://127.0.0.1:8000
4. Verify "Narrar" buttons are visible on summary tabs
5. Load a session with existing summary
6. Click "Narrar" — verify audio starts playing
7. Click again while playing — verify it stops
8. Click again — verify cached playback (faster, no generation delay)

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/static/index.html src/rpg_scribe/web/static/app.js
git commit -m "feat(tts): add Narrar button and NDJSON streaming playback in Web UI"
```

---

### Task 8: CSS styles for narrate button (parallelizable with Task 7)

**Files:**
- Modify: `src/rpg_scribe/web/static/style.css`

- [ ] **Step 1: Add narrate button styles**

Add to the end of `src/rpg_scribe/web/static/style.css`:

```css
/* ── TTS Narrate ──────────────────────────────────────────── */
.btn-narrate {
  gap: 0.3em;
}

.btn-narrate.narrating {
  background: var(--accent);
  color: var(--bg);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/web/static/style.css
git commit -m "feat(tts): add CSS styles for narrate button states"
```

---

## Fase 4: Integration (Task 9)

### Task 9: Integration smoke test (requires Fases 1-3)

**Files:**
- Test: `tests/test_tts.py`

- [ ] **Step 1: Write integration test for full narration flow**

Append to `tests/test_tts.py`:

```python
class TestTTSIntegration:
    def test_full_narration_flow_with_cache(self, tmp_path):
        """End-to-end: narrate → cache → re-narrate uses cache."""
        from rpg_scribe.core.models import TTSConfig
        from rpg_scribe.tts.cache import TTSCache

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

        app = _make_test_app(
            tts_provider=mock_provider,
            tts_cache=tts_cache,
            tts_config=tts_config,
        )
        client = TestClient(app)

        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."

        # First narration — 3 API calls
        resp1 = client.post("/api/tts/narrate", json={"text": text})
        assert resp1.status_code == 200
        assert call_count == 3

        import json
        lines1 = [json.loads(l) for l in resp1.text.strip().split("\n") if l.strip()]
        assert all(l["cached"] is False for l in lines1)

        # Second narration — 0 API calls (all cached)
        call_count = 0
        resp2 = client.post("/api/tts/narrate", json={"text": text})
        assert resp2.status_code == 200
        assert call_count == 0

        lines2 = [json.loads(l) for l in resp2.text.strip().split("\n") if l.strip()]
        assert all(l["cached"] is True for l in lines2)

        # URLs are the same
        assert [l["audio_url"] for l in lines1] == [l["audio_url"] for l in lines2]

    def test_narrate_handles_provider_error_gracefully(self, tmp_path):
        """If a paragraph fails, the endpoint yields an error and continues."""
        from rpg_scribe.core.models import TTSConfig
        from rpg_scribe.tts.cache import TTSCache

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

        app = _make_test_app(
            tts_provider=mock_provider,
            tts_cache=tts_cache,
            tts_config=tts_config,
        )
        client = TestClient(app)

        text = "Good paragraph.\n\nThis will fail.\n\nAnother good one."
        resp = client.post("/api/tts/narrate", json={"text": text})
        assert resp.status_code == 200

        import json
        lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) == 3
        assert "audio_url" in lines[0]
        assert "error" in lines[1]
        assert "audio_url" in lines[2]
```

- [ ] **Step 2: Run all TTS tests**

Run: `pytest tests/test_tts.py -v`
Expected: All PASS

- [ ] **Step 3: Run full project test suite**

Run: `pytest -v`
Expected: No new failures (existing 5 pre-existing failures are acceptable)

- [ ] **Step 4: Commit**

```bash
git add tests/test_tts.py
git commit -m "test(tts): add integration tests for full narration flow"
```

- [ ] **Step 5: Final commit — update CLAUDE.md with TTS docs**

Add a TTS section to `CLAUDE.md` under the existing documentation sections, after `### Loading States & UX Patterns`:

```markdown
### TTS Narration

- Configurable TTS provider architecture: `BaseTTSProvider` ABC in `src/rpg_scribe/tts/base.py`
- First provider: OpenAI TTS (`tts-1` / `tts-1-hd`) in `openai_provider.py`
- Disk cache in `data/tts_cache/` keyed by `sha256(text + provider + voice + model)`
- Streaming endpoint `POST /api/tts/narrate` returns NDJSON (one line per paragraph)
- Frontend plays audio paragraph-by-paragraph, queuing subsequent chunks
- Config: `[tts]` section in `default.toml` (enabled, provider, voice, model, cache_dir)
- "Narrar" button appears on session summary, chronology, and campaign summary tabs
```

```bash
git add CLAUDE.md
git commit -m "docs: add TTS narration section to CLAUDE.md"
```
