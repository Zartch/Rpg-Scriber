# System Status — Config Display & Panel Audit

**Date:** 2026-04-17
**Branch:** refactor_solid

---

## Problem

The System Status panel shows only live runtime state (component dots + message). There is no
visibility into how the system is configured. This caused a real incident: `compute_type = "float16"`
on CPU crashed faster-whisper on startup, and the mismatch was only visible in the error log.

Additionally, the panel has a silent bug: `/api/status` is never fetched on page load, so all cards
start as "idle" regardless of actual system state.

---

## Goals

1. Show the relevant config for each component inside its status card (always visible, even with no
   active session).
2. Every config token has a tooltip describing what the parameter controls and what it affects.
   Tooltips are vendor-agnostic and value-agnostic — they describe the dimension, not the current value.
3. Fix the missing initial `/api/status` fetch so cards reflect real state on load.
4. Add a TTS card alongside the existing three.
5. Add a subtle DB path footer line in the panel.

---

## Non-goals

- Editing config from the UI.
- Showing low-level values: timeouts, retries, buffer sizes, `verbose_logging`, `audio_debug_log_dir`.
- Any new backend service or DB table.
- Listing valid values or comparing options in tooltips.

---

## Architecture

### Backend — `GET /api/status` extension

`src/rpg_scribe/web/routers/status.py` — extend the response with a `config` key built from
`AppConfig`. If no config is attached to the router (standalone mode), `config` is `null`.

The backend emits **only fields that exist for the active configuration**. Fields that do not apply
to the current backend (e.g. `compute_type` is local-only) are simply absent from the response.
The `model` field is unified across transcriber types: for local backends it holds `local_model_size`,
for remote backends it holds `model`.

```python
"config": {
    "listener": {
        "language": "es",
        "chunk_duration_s": 10.0,
        "vad_aggressiveness": 2,
        "audio_filter_enabled": True,
        "post_filter_enabled": True,
    },
    "transcriber": {
        "transcriber_type": "faster-whisper",
        "model": "large-v3",        # unified: local_model_size or model depending on type
        "device": "auto",           # only emitted for local backends
        "compute_type": "int8",     # only emitted for local backends
    },
    "summarizer": {
        "model": "claude-sonnet-4-20250514",
        "extraction_every_n_updates": 0,
    },
    "tts": {
        "enabled": True,
        "provider": "openai",
        "voice": "nova",
        "model": "tts-1",
    },
    "database": {
        "path": "rpg_scribe.db",
    },
}
```

### Frontend

#### HTML — `index.html`

Each status card gains a `<div class="status-config"></div>` below the existing `.status-msg` /
`.status-latency` row. Config tokens are injected by JS as:

```html
<span class="config-token" title="[tooltip text]">value</span>
```

Add a **TTS card** with `data-component="tts"` alongside the existing three cards.

Add a **footer line** inside `#status-panel` below the card grid:

```html
<div id="status-db-path" class="status-db-path"></div>
```

#### JS — `main.js`

**Bug fix:** call `fetchStatus()` on bootstrap alongside `fetchCampaignInfo()`.

**`fetchStatus()`** — new function:
1. `GET /api/status`
2. Restore component states from `data.components` (apply `updateStatus` to each entry)
3. If `data.config` present, call `renderStatusConfig(data.config)`

**`renderStatusConfig(config)`** — iterates over a token definition map and populates
`.status-config` inside each card. Fields not present in the response are silently skipped —
no conditional logic per backend type needed in JS.

**Token definition map** (JS object, easy to extend):

```js
const TOKEN_DEFS = {
  listener: [
    { key: "language",             label: v => v,                        tip: "Idioma de transcripción. Afecta al modelo de reconocimiento de voz." },
    { key: "chunk_duration_s",     label: v => `chunk: ${v}s`,           tip: "Duración de cada chunk de audio antes de procesarse. Menor valor reduce latencia percibida; mayor valor mejora precisión." },
    { key: "vad_aggressiveness",   label: v => `vad: ${v}`,              tip: "Agresividad del detector de actividad de voz (0–3). Mayor valor descarta más silencios pero puede cortar palabras." },
    { key: "audio_filter_enabled", label: v => `filter: ${v?"on":"off"}`, tip: "Filtro de audio pre-procesamiento. Descarta chunks sin contenido de voz relevante antes de transcribir." },
    { key: "post_filter_enabled",  label: v => `post-filter: ${v?"on":"off"}`, tip: "Filtro post-transcripción. Descarta salidas del modelo con características anómalas (p.ej. alucinaciones)." },
  ],
  transcriber: [
    { key: "transcriber_type", label: v => v,                tip: "Tipo de motor de transcripción activo. Local = sin coste por uso, consume recursos del equipo. Remoto = coste por uso vía API." },
    { key: "model",            label: v => v,                tip: "Modelo de transcripción configurado. Afecta a precisión, velocidad y, en backends remotos, a coste por uso." },
    { key: "compute_type",     label: v => v,                tip: "Tipo de cómputo del modelo local. Afecta a velocidad de inferencia y compatibilidad con el hardware disponible." },
    { key: "device",           label: v => v,                tip: "Dispositivo de inferencia configurado. Determina en qué hardware se ejecuta el modelo." },
  ],
  summarizer: [
    { key: "model",                      label: v => v,       tip: "Modelo de lenguaje configurado para generar resúmenes y extraer entidades." },
    { key: "extraction_every_n_updates", label: v => v === 0 ? "extract: on finalize" : `extract: every ${v}`, tip: "Frecuencia con la que se extraen entidades y relaciones desde los resúmenes generados." },
  ],
  tts: [
    // "off" state handled separately: if enabled === false, render single "off" token
    { key: "voice",    label: v => v,    tip: "Voz configurada para la síntesis de habla." },
    { key: "model",    label: v => v,    tip: "Modelo de síntesis de voz. Afecta a la calidad y velocidad de generación de audio." },
    { key: "provider", label: v => v,    tip: "Proveedor del servicio de síntesis de voz." },
  ],
};
```

TTS `off` tooltip: `"Narración TTS desactivada. Activar con tts.enabled = true en la configuración."`

DB footer: `DB: {path}` — tooltip: `"Ruta del fichero de base de datos activo."`

#### CSS — `layout.css`

- `.status-card` changes from flat flex-row to flex-column. The dot + component name move into a
  `.status-card-header` inner wrapper (flex-row) so the existing layout is preserved.
- `.status-config` — small muted text, flex-wrap row of tokens separated by `·` characters or gaps.
- `.config-token` — `cursor: help` to hint at the tooltip. Relies on native browser `title` attribute
  (no JS tooltip library needed).

---

## Error handling

- If `config` is `null` in the API response, `renderStatusConfig` is a no-op — cards show state only.
- If a specific config field is absent, that token is silently omitted.
- Network error on `fetchStatus()` is silently swallowed (non-critical; state updates via WebSocket).
- Existing `/api/status` callers are unaffected — the `config` key is purely additive.

---

## Testing

- Existing tests in `test_web.py` that assert on `/api/status` need to accept the new `config` key
  (additive, no breaking change).
- Manual: open UI with faster-whisper configured → Transcriber card shows type, model, compute_type,
  device; hover each token shows generic tooltip.
- Manual: open UI with openai configured → Transcriber card shows type and model; no compute_type
  or device tokens rendered.
- Manual: open UI with no active session → cards show correct initial state from `/api/status` fetch,
  not all "idle".
- Manual: TTS disabled → TTS card shows single "off" token with tooltip.
