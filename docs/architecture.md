# Arquitectura — RPG Scribe

## Patrón General

Event-driven async con pub/sub via `EventBus`. Capas bien definidas:

```
Discord / File  →  Listener  →  [AudioChunkEvent]
                                    ↓
                               Transcriber  →  [TranscriptionEvent]
                                                    ↓
                                             Summarizer  →  [SummaryUpdateEvent]
                                                                    ↓
                                                             Web / Discord Bot
```

Cada capa depende solo del `EventBus` — nunca se llaman directamente entre sí.

## Capas Backend

```
Routers (web/routers/)          ← HTTP / WebSocket handlers
    ↓
Services (services/)            ← Lógica de negocio reutilizable
    ↓
Repositories (core/database/)   ← Acceso a SQLite
    ↓
Database (core/database/connection.py)  ← aiosqlite connection
```

- Los **Routers** son `APIRouter` de FastAPI, uno por dominio.
- Los **Services** son clases Python puras inyectadas desde `main.py` o desde los routers via `app.state`.
- Los **Repositories** acceden a SQLite y se instancian en `Database.__init__` usando deferred imports para evitar circular imports.

## Estructura de Archivos

```
src/rpg_scribe/
├── main.py                      # CLI + Application (orquestador)
├── config.py                    # Carga TOML + env vars → AppConfig
├── logging_config.py            # structlog setup
│
├── core/
│   ├── event_bus.py             # EventBus: subscribe / publish
│   ├── events.py                # Dataclasses frozen=True (AudioChunk, Transcription, Summary…)
│   ├── models.py                # Modelos de dominio (CampaignContext, PlayerInfo, NPCInfo…)
│   ├── resilience.py            # Retry, circuit breaker
│   └── database/
│       ├── __init__.py          # Re-exports Database
│       ├── connection.py        # Database class (connect/close/conn)
│       ├── schema.py            # SCHEMA_SQL DDL
│       └── repositories/
│           ├── campaign_repo.py
│           ├── session_repo.py
│           ├── transcription_repo.py
│           └── entity_repo.py
│
├── services/
│   ├── transcription_service.py  # persist() + word replacements
│   ├── audio_diagnostics.py      # AudioDiagnosticSaver, TranscriptionFileWriter
│   ├── campaign_service.py       # Lógica campaña (sync TOML→DB, etc.)
│   ├── session_service.py        # Lógica sesión (start/end/finalize)
│   ├── entity_service.py         # Merge de entidades
│   ├── tts_service.py            # Narración TTS (ElevenLabs)
│   └── exporter.py               # Export sesiones a texto/markdown
│
├── listeners/
│   ├── base.py                   # BaseListener ABC
│   ├── discord_listener.py       # Discord voice + monkey-patches DAVE/PacketRouter
│   └── file_listener.py          # Listener de archivos (testing)
│
├── transcribers/
│   ├── base.py                   # BaseTranscriber ABC
│   ├── openai_transcriber.py     # OpenAI gpt-4o-transcribe
│   └── faster_whisper_transcriber.py  # Fallback local
│
├── summarizers/
│   ├── base.py                   # BaseSummarizer ABC + TranscriptionEntry
│   ├── claude_summarizer.py      # Claude Sonnet API
│   ├── prompts.py                # SESSION_SYSTEM_PROMPT, FINALIZE_USER, etc.
│   └── entity_extractor.py       # Extracción de entidades del resumen
│
├── discord_bot/
│   ├── bot.py                    # Factory del bot Discord
│   ├── commands.py               # Slash commands (/scribe start/stop/status/summary/ask)
│   └── publisher.py              # Publica resúmenes como embeds en Discord
│
└── web/
    ├── app.py                    # Factory FastAPI, registra todos los routers
    ├── routes.py                 # Router raíz (proxy helpers + include_router calls)
    ├── state.py                  # WebState dataclass (estado compartido app↔web)
    ├── websocket.py              # ConnectionManager + WebSocket bridge
    └── routers/
        ├── campaigns.py          # GET/POST/PATCH /campaigns/*
        ├── sessions.py           # GET/POST /sessions/* + export/logs
        ├── entities.py           # Players, NPCs, Locations, Relationships, Questions
        ├── tts.py                # POST /tts/*
        ├── misc.py               # /config, /word-replacements, etc.
        └── ws.py                 # WebSocket endpoint

web/static/
├── index.html                    # SPA shell
├── campaign-summaries.html       # Historial de resúmenes
├── js/                           # ES modules (browser-native, no bundler)
│   ├── main.js                   # Entry point — wires all modules
│   ├── state.js                  # Shared mutable state
│   ├── api.js                    # apiGet/apiPost/apiPut/apiPatch/apiDelete
│   ├── utils.js                  # escapeHtml, formatTime, withLoading, showSkeleton…
│   ├── websocket.js              # registerHandler registry
│   ├── campaign.js               # Campaign load/edit
│   ├── sessions.js               # Session list + history
│   ├── transcription.js          # Live transcription feed
│   ├── summary.js                # Session summary display
│   ├── entities.js               # Players, NPCs, Locations CRUD
│   ├── tts.js                    # TTS narration controls
│   └── relationships/
│       ├── index.js              # Relationships CRUD + entry point
│       ├── graph-2d.js           # D3 2D graph
│       └── graph-3d.js           # Three.js 3D graph
└── css/
    ├── variables.css             # CSS custom properties (colors, spacing…)
    ├── base.css                  # Reset + typography
    ├── layout.css                # Grid, sidebars, panels
    ├── components.css            # Buttons, modals, forms, badges
    └── features/
        ├── campaign.css
        ├── entities.css
        ├── relationships.css
        ├── feed.css
        └── summary.css
```

## Notas de Implementación

### Circular imports en Database
Los repositorios importan `Database` y `Database` instancia los repositorios. Se resuelve con **deferred imports** dentro de `Database.__init__`:
```python
def __init__(self, db_path):
    from rpg_scribe.core.database.repositories.campaign_repo import CampaignRepository
    self.campaigns = CampaignRepository(self)
    # ...
```

### ES Modules y dependencias circulares en JS
El patrón de **callback injection** desacopla módulos sin imports circulares:
```js
// en sessions.js
let onSessionSelected = () => {};
export function setOnSessionSelected(fn) { onSessionSelected = fn; }
// main.js llama setOnSessionSelected(loadTranscriptions)
```

### Discord DAVE E2EE
`discord.py 2.7+` activa DAVE E2EE en canales de voz. `voice_recv` descifra la capa de transporte pero no DAVE, produciendo ruido. Se deshabilita via monkey-patch:
```python
# discord_listener.py → _patch_disable_dave()
VoiceConnectionState.max_dave_protocol_version = lambda self: 0
```

### Audio pipeline
```
Discord opus → voice_recv decrypt → opus decode → stereo PCM (3840 bytes/20ms)
→ stereo_to_mono → UserAudioBuffer → pcm_to_wav_bytes → OpenAI API
```

### Modo genérico
Sin `--campaign`, `Application` crea `CampaignContext.create_generic()` con `GENERIC_SYSTEM_PROMPT`. El summarizer funciona igual.
