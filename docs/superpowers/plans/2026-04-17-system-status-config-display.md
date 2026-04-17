# System Status Config Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show relevant config for each component in the System Status panel, with per-token tooltips, fix the missing initial `/api/status` fetch, and add a TTS card and DB path footer.

**Architecture:** Backend extends `GET /api/status` with a `config` key built from `AppConfig`. Frontend fetches this on load, populates `.status-config` divs inside each status card with tooltip-bearing `<span>` tokens. Cards restructured from flat flex-row to column layout with a header row.

**Tech Stack:** Python/FastAPI backend, vanilla JS ES modules, CSS custom properties. No new dependencies.

---

### Task 1: Backend — extend `/api/status` with config payload

**Files:**
- Modify: `src/rpg_scribe/web/routers/status.py`
- Modify: `tests/test_web.py` (class `TestStatusEndpoint`)

- [ ] **Step 1: Write failing tests**

Add to `TestStatusEndpoint` in `tests/test_web.py`:

```python
async def test_status_config_null_when_no_config(self, client) -> None:
    resp = await client.get("/api/status")
    data = resp.json()
    assert "config" in data
    assert data["config"] is None

async def test_status_config_faster_whisper(self, client, app) -> None:
    from rpg_scribe.web import routes as _routes
    from rpg_scribe.config import AppConfig
    from rpg_scribe.core.models import (
        TranscriberConfig, SummarizerConfig, TTSConfig, ListenerConfig
    )
    cfg = AppConfig()
    cfg.transcriber = TranscriberConfig(
        transcriber_type="faster-whisper", local_model_size="large-v3",
        device="cpu", compute_type="int8", language="es",
        audio_filter_enabled=True, post_filter_enabled=True,
    )
    cfg.summarizer = SummarizerConfig(model="claude-test", extraction_every_n_updates=0)
    cfg.tts = TTSConfig(enabled=True, provider="openai", voice="nova", model="tts-1")
    cfg.listener = ListenerConfig(chunk_duration_s=10.0, vad_aggressiveness=2)
    cfg.database_path = "test.db"
    _routes.router.config = cfg
    try:
        resp = await client.get("/api/status")
        data = resp.json()
        c = data["config"]
        assert c["transcriber"]["transcriber_type"] == "faster-whisper"
        assert c["transcriber"]["model"] == "large-v3"
        assert c["transcriber"]["device"] == "cpu"
        assert c["transcriber"]["compute_type"] == "int8"
        assert c["listener"]["language"] == "es"
        assert c["listener"]["chunk_duration_s"] == 10.0
        assert c["listener"]["vad_aggressiveness"] == 2
        assert c["listener"]["audio_filter_enabled"] is True
        assert c["listener"]["post_filter_enabled"] is True
        assert c["summarizer"]["model"] == "claude-test"
        assert c["summarizer"]["extraction_every_n_updates"] == 0
        assert c["tts"]["enabled"] is True
        assert c["tts"]["voice"] == "nova"
        assert c["tts"]["model"] == "tts-1"
        assert c["tts"]["provider"] == "openai"
        assert c["database"]["path"] == "test.db"
    finally:
        _routes.router.config = None

async def test_status_config_openai_omits_local_fields(self, client, app) -> None:
    from rpg_scribe.web import routes as _routes
    from rpg_scribe.config import AppConfig
    from rpg_scribe.core.models import TranscriberConfig
    cfg = AppConfig()
    cfg.transcriber = TranscriberConfig(
        transcriber_type="openai", model="gpt-4o-transcribe", language="es"
    )
    _routes.router.config = cfg
    try:
        resp = await client.get("/api/status")
        t = resp.json()["config"]["transcriber"]
        assert t["transcriber_type"] == "openai"
        assert t["model"] == "gpt-4o-transcribe"
        assert "device" not in t
        assert "compute_type" not in t
    finally:
        _routes.router.config = None

async def test_status_config_tts_disabled(self, client, app) -> None:
    from rpg_scribe.web import routes as _routes
    from rpg_scribe.config import AppConfig
    from rpg_scribe.core.models import TTSConfig
    cfg = AppConfig()
    cfg.tts = TTSConfig(enabled=False)
    _routes.router.config = cfg
    try:
        resp = await client.get("/api/status")
        tts = resp.json()["config"]["tts"]
        assert tts["enabled"] is False
        assert "voice" not in tts
        assert "model" not in tts
    finally:
        _routes.router.config = None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web.py::TestStatusEndpoint -v -k "config"
```

Expected: FAIL — `"config" not in data`

- [ ] **Step 3: Implement `_build_config_payload` and extend `get_status`**

In `src/rpg_scribe/web/routers/status.py`, add the helper above the `get_status` function and update the return value:

```python
def _build_config_payload(config) -> dict[str, Any] | None:
    if config is None:
        return None
    t = config.transcriber
    is_local = t.transcriber_type != "openai"
    transcriber: dict[str, Any] = {
        "transcriber_type": t.transcriber_type,
        "model": t.local_model_size if is_local else t.model,
    }
    if is_local:
        transcriber["compute_type"] = t.compute_type
        transcriber["device"] = t.device

    s = config.summarizer
    li = config.listener
    tts = config.tts
    tts_data: dict[str, Any] = {"enabled": tts.enabled}
    if tts.enabled:
        tts_data["voice"] = tts.voice
        tts_data["model"] = tts.model
        tts_data["provider"] = tts.provider

    return {
        "listener": {
            "language": t.language,
            "chunk_duration_s": li.chunk_duration_s,
            "vad_aggressiveness": li.vad_aggressiveness,
            "audio_filter_enabled": t.audio_filter_enabled,
            "post_filter_enabled": t.post_filter_enabled,
        },
        "transcriber": transcriber,
        "summarizer": {
            "model": s.model,
            "extraction_every_n_updates": s.extraction_every_n_updates,
        },
        "tts": tts_data,
        "database": {"path": config.database_path},
    }
```

Then update the return dict in `get_status`:

```python
    return {
        "components": state.component_status,
        "active_session_id": state.active_session_id,
        "active_session_title": active_session_title,
        "websocket_clients": _get_manager().active_count,
        "web_limits": {
            "transcriptions_buffer_max_items": state.max_transcriptions,
            "live_feed_max_items": getattr(config, "web_feed_max_items", 1000),
        },
        "config": _build_config_payload(config),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_web.py::TestStatusEndpoint -v
```

Expected: all pass (including pre-existing tests — the new `config` key is additive).

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/routers/status.py tests/test_web.py
git commit -m "feat: extend /api/status with config payload"
```

---

### Task 2: HTML — restructure status cards and add TTS card + DB footer

**Files:**
- Modify: `src/rpg_scribe/web/static/index.html`

The current card structure is a flat flex-row:
```html
<div class="status-card" data-component="listener">
  <span class="status-dot idle"></span>
  <strong>Listener</strong>
  <span class="status-msg">idle</span>
</div>
```

It must become a column card with an inner header row, a latency span (currently missing from HTML despite JS expecting it), and a config div:
```html
<div class="status-card" data-component="listener">
  <div class="status-card-header">
    <span class="status-dot idle"></span>
    <strong>Listener</strong>
    <span class="status-msg">idle</span>
    <span class="status-latency"></span>
  </div>
  <div class="status-config"></div>
</div>
```

- [ ] **Step 1: Replace all three existing cards and add TTS card**

Replace the entire `<div id="component-status" class="status-grid">` block (lines ~433–449 in index.html) with:

```html
<div id="component-status" class="status-grid">
  <div class="status-card" data-component="listener">
    <div class="status-card-header">
      <span class="status-dot idle"></span>
      <strong>Listener</strong>
      <span class="status-msg">idle</span>
      <span class="status-latency"></span>
    </div>
    <div class="status-config"></div>
  </div>
  <div class="status-card" data-component="transcriber">
    <div class="status-card-header">
      <span class="status-dot idle"></span>
      <strong>Transcriber</strong>
      <span class="status-msg">idle</span>
      <span class="status-latency"></span>
    </div>
    <div class="status-config"></div>
  </div>
  <div class="status-card" data-component="summarizer">
    <div class="status-card-header">
      <span class="status-dot idle"></span>
      <strong>Summarizer</strong>
      <span class="status-msg">idle</span>
      <span class="status-latency"></span>
    </div>
    <div class="status-config"></div>
  </div>
  <div class="status-card" data-component="tts">
    <div class="status-card-header">
      <span class="status-dot idle"></span>
      <strong>TTS</strong>
      <span class="status-msg"></span>
    </div>
    <div class="status-config"></div>
  </div>
</div>
```

Add `<div id="status-db-path" class="status-db-path"></div>` immediately after the closing `</div>` of `component-status`, before `<div id="session-banner"`.

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/web/static/index.html
git commit -m "feat: restructure status cards with header+config layout, add TTS card and DB footer"
```

---

### Task 3: CSS — update status card styles

**Files:**
- Modify: `src/rpg_scribe/web/static/css/layout.css`

- [ ] **Step 1: Replace `.status-card` block and add new rules**

Current block (lines ~18–26 in layout.css):
```css
.status-card {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg);
  border-radius: 0.375rem;
  font-size: 0.85rem;
}
```

Replace with:
```css
.status-card {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg);
  border-radius: 0.375rem;
  font-size: 0.85rem;
}
.status-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.status-config {
  display: flex;
  flex-wrap: wrap;
  gap: 0 0.1rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  padding-left: 1.25rem;
  min-height: 1em;
}
.config-token {
  cursor: help;
  white-space: nowrap;
}
.config-token + .config-token::before {
  content: " · ";
}
.status-db-path {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 0.3rem;
  padding-left: 0.25rem;
  cursor: help;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/rpg_scribe/web/static/css/layout.css
git commit -m "feat: style status cards for column layout with config line"
```

---

### Task 4: JS — fetchStatus, renderStatusConfig, bootstrap fix

**Files:**
- Modify: `src/rpg_scribe/web/static/js/main.js`

- [ ] **Step 1: Add TOKEN_DEFS constant after the `latencyClass` function (line ~83)**

```js
// ── Config token definitions ─────────────────────────────────────────────────

var TOKEN_DEFS = {
  listener: [
    { key: "language",             label: function(v) { return String(v); },                                      tip: "Idioma de transcripción. Afecta al modelo de reconocimiento de voz." },
    { key: "chunk_duration_s",     label: function(v) { return "chunk: " + v + "s"; },                           tip: "Duración de cada chunk de audio antes de procesarse. Menor valor reduce latencia percibida; mayor valor mejora precisión." },
    { key: "vad_aggressiveness",   label: function(v) { return "vad: " + v; },                                   tip: "Agresividad del detector de actividad de voz (0–3). Mayor valor descarta más silencios pero puede cortar palabras." },
    { key: "audio_filter_enabled", label: function(v) { return "filter: " + (v ? "on" : "off"); },               tip: "Filtro de audio pre-procesamiento. Descarta chunks sin contenido de voz relevante antes de transcribir." },
    { key: "post_filter_enabled",  label: function(v) { return "post-filter: " + (v ? "on" : "off"); },          tip: "Filtro post-transcripción. Descarta salidas del modelo con características anómalas (p.ej. alucinaciones)." },
  ],
  transcriber: [
    { key: "transcriber_type", label: function(v) { return String(v); }, tip: "Tipo de motor de transcripción activo. Local = sin coste por uso, consume recursos del equipo. Remoto = coste por uso vía API." },
    { key: "model",            label: function(v) { return String(v); }, tip: "Modelo de transcripción configurado. Afecta a precisión, velocidad y, en backends remotos, a coste por uso." },
    { key: "compute_type",     label: function(v) { return String(v); }, tip: "Tipo de cómputo del modelo local. Afecta a velocidad de inferencia y compatibilidad con el hardware disponible." },
    { key: "device",           label: function(v) { return String(v); }, tip: "Dispositivo de inferencia configurado. Determina en qué hardware se ejecuta el modelo." },
  ],
  summarizer: [
    { key: "model",                      label: function(v) { return String(v); },                                                                   tip: "Modelo de lenguaje configurado para generar resúmenes y extraer entidades." },
    { key: "extraction_every_n_updates", label: function(v) { return v === 0 ? "extract: on finalize" : "extract: every " + v; },                    tip: "Frecuencia con la que se extraen entidades y relaciones desde los resúmenes generados." },
  ],
};

function _renderTtsConfig(tts, container) {
  container.innerHTML = "";
  if (!tts.enabled) {
    var span = document.createElement("span");
    span.className = "config-token";
    span.title = "Narración TTS desactivada. Activar con tts.enabled = true en la configuración.";
    span.textContent = "off";
    container.appendChild(span);
    return;
  }
  [
    { key: "voice",    tip: "Voz configurada para la síntesis de habla." },
    { key: "model",    tip: "Modelo de síntesis de voz. Afecta a la calidad y velocidad de generación de audio." },
    { key: "provider", tip: "Proveedor del servicio de síntesis de voz." },
  ].forEach(function(def) {
    if (tts[def.key] == null) return;
    var span = document.createElement("span");
    span.className = "config-token";
    span.title = def.tip;
    span.textContent = String(tts[def.key]);
    container.appendChild(span);
  });
}

function renderStatusConfig(config) {
  ["listener", "transcriber", "summarizer"].forEach(function(component) {
    var card = componentStatusEl ? componentStatusEl.querySelector('[data-component="' + component + '"]') : null;
    if (!card) return;
    var configEl = card.querySelector(".status-config");
    if (!configEl) return;
    configEl.innerHTML = "";
    var defs = TOKEN_DEFS[component] || [];
    var data = config[component] || {};
    defs.forEach(function(def) {
      if (data[def.key] == null) return;
      var span = document.createElement("span");
      span.className = "config-token";
      span.title = def.tip;
      span.textContent = def.label(data[def.key]);
      configEl.appendChild(span);
    });
  });
  var ttsCard = componentStatusEl ? componentStatusEl.querySelector('[data-component="tts"]') : null;
  if (ttsCard && config.tts) {
    var ttsConfigEl = ttsCard.querySelector(".status-config");
    if (ttsConfigEl) _renderTtsConfig(config.tts, ttsConfigEl);
  }
}
```

- [ ] **Step 2: Add `fetchStatus` function after `renderStatusConfig`**

```js
function fetchStatus() {
  fetch("/api/status")
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var components = data.components || {};
      Object.keys(components).forEach(function(key) {
        updateStatus(components[key]);
      });
      if (data.config) {
        renderStatusConfig(data.config);
      }
      var dbEl = document.getElementById("status-db-path");
      if (dbEl && data.config && data.config.database) {
        dbEl.title = "Ruta del fichero de base de datos activo.";
        dbEl.textContent = "DB: " + data.config.database.path;
      }
    })
    .catch(function() {});
}
```

- [ ] **Step 3: Call `fetchStatus()` in the bootstrap section**

Find the bootstrap block (around line 183):
```js
connectWS();
fetchCampaignInfo();
pollQuestions();
```

Add `fetchStatus();` right after `connectWS();`:
```js
connectWS();
fetchStatus();
fetchCampaignInfo();
pollQuestions();
```

- [ ] **Step 4: Manual verification**

Start the server:
```bash
rpg-scribe
```

Open `http://127.0.0.1:8000` in browser and verify:
- Status cards show config line below the dot/name/status row
- Hovering each token shows the tooltip text
- TTS card appears with voice/model/provider tokens (or "off" if disabled)
- DB path footer visible at bottom of panel
- Cards start with correct state on load (not all "idle" if system was running)
- No JS errors in browser console

- [ ] **Step 5: Commit**

```bash
git add src/rpg_scribe/web/static/js/main.js
git commit -m "feat: fetch and render config tokens in System Status panel"
```

---

### Task 5: Full test run

- [ ] **Step 1: Run full test suite**

```bash
pytest
```

Expected: same pass/fail ratio as before. The 4 known pre-existing failures listed in CLAUDE.md are acceptable. No new failures.

- [ ] **Step 2: If new failures appear, fix them before proceeding**

The most likely failure: a test that does `assert set(data.keys()) == {"components", ...}` — add `"config"` to the expected set. Check `tests/test_web.py` for exact equality assertions on `/api/status` response keys.
