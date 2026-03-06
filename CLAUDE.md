# CLAUDE.md — RPG Scribe

Guía de referencia para Claude Code al trabajar en este proyecto.

## Descripción del Proyecto

RPG Scribe es una herramienta en Python que escucha partidas de rol en tiempo real (vía Discord), transcribe y diariza quién dice qué, y genera un resumen narrativo vivo de la sesión usando IA. Distingue entre diálogo in-game y meta-rol. Incluye un Web UI para monitorizar sesiones, editar campaña/jugadores/NPCs y revisar historial.

## Comandos Esenciales

```bash
# Instalar dependencias (modo desarrollo)
pip install -e ".[dev]"

# Instalar con transcripción local (faster-whisper)
pip install -e ".[local]"

# Ejecutar con campaña
rpg-scribe --campaign config/campaigns/example.toml

# Ejecutar en modo genérico (sin campaña, "Resume mode")
rpg-scribe

# Ejecutar tests
pytest

# Ejecutar tests con verbose
pytest -v

# Linter
ruff check src/ tests/

# Formatear código
ruff format src/ tests/
```

## Estructura del Proyecto

```
src/rpg_scribe/
├── __init__.py
├── main.py                  # CLI y orquestador principal (Application)
├── config.py                # Carga de configuración TOML + env vars
├── logging_config.py        # Logging estructurado con structlog
├── core/
│   ├── event_bus.py         # Bus de eventos async (pub/sub)
│   ├── events.py            # Dataclasses de eventos tipados
│   ├── models.py            # Modelos de dominio (CampaignContext, PlayerInfo, NPCInfo)
│   ├── database.py          # Wrapper async SQLite (CRUD campaigns/players/npcs/sessions)
│   └── resilience.py        # Retry, circuit breaker, reconnection
├── listeners/
│   ├── base.py              # BaseListener ABC
│   ├── discord_listener.py  # Listener Discord (con monkey-patches DAVE + PacketRouter)
│   └── file_listener.py     # Listener de archivos (testing)
├── transcribers/
│   ├── base.py              # BaseTranscriber ABC
│   ├── openai_transcriber.py    # OpenAI API (gpt-4o-transcribe)
│   └── faster_whisper_transcriber.py  # Fallback local
├── summarizers/
│   ├── base.py              # BaseSummarizer ABC
│   └── claude_summarizer.py # Claude Sonnet API (+ GENERIC_SYSTEM_PROMPT)
├── discord_bot/
│   ├── bot.py               # Factory del bot Discord
│   ├── commands.py          # Slash commands (/scribe start/stop/status/ask)
│   └── publisher.py         # Publica resúmenes como embeds en Discord
└── web/
    ├── app.py               # Factory de FastAPI (acepta config para campaign)
    ├── routes.py            # REST API + WebSocket (campaigns, players, NPCs, sessions)
    ├── websocket.py         # WebSocket bridge y ConnectionManager
    └── static/
        ├── index.html       # Frontend HTML (campaign bar, players, NPCs, sessions sidebar)
        ├── app.js           # Frontend JS (WebSocket, CRUD, session history)
        └── style.css        # Estilos dark theme

scripts/
├── import_campaign.py       # Utilidad para importar/generar TOML de campaña
└── setup_discord_bot.py     # Utilidad para configurar bot Discord

config/
├── default.toml             # Configuración por defecto
└── campaigns/
    └── example.toml         # Ejemplo de campaña
```

## Arquitectura

- **Patrón**: Event-driven async con pub/sub via `EventBus`
- **Eventos**: `AudioChunkEvent` → `TranscriptionEvent` → `SummaryUpdateEvent` + `SystemStatusEvent`
- **Flujo**: Listener captura audio → Transcriber genera texto → Summarizer resume narrativamente
- **Base de datos**: SQLite async (aiosqlite), 6 tablas: campaigns, players, npcs, sessions, transcriptions, questions
- **Web**: FastAPI con WebSocket para actualizaciones en tiempo real
- **Modo genérico**: Si no se pasa `--campaign`, crea un `CampaignContext.create_generic()` con prompt genérico

### Web UI Features

- **Campaign bar**: muestra/edita nombre, sistema, descripción, instrucciones (PATCH `/api/campaigns/{id}`)
- **Players**: sección colapsable, edición inline (PUT `/api/campaigns/{id}/players/{pid}`)
- **NPCs**: sección colapsable, edición inline + crear nuevos (POST/PUT `/api/campaigns/{id}/npcs`)
- **Session sidebar**: lista sesiones con duración, indicador de resumen, preview
- **Session history**: click en sesión histórica carga transcripciones + resumen desde DB
- **Live mode**: WebSocket para transcripciones y resúmenes en tiempo real
- **Questions**: panel de preguntas pendientes del summarizer con respuesta inline

### REST API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/status` | Estado de componentes y sesión activa |
| GET | `/api/campaigns` | Info campaña activa + players + NPCs |
| PATCH | `/api/campaigns/{id}` | Editar campaña |
| PUT | `/api/campaigns/{id}/players/{pid}` | Editar jugador |
| POST | `/api/campaigns/{id}/npcs` | Crear NPC |
| PUT | `/api/campaigns/{id}/npcs/{nid}` | Editar NPC |
| GET | `/api/sessions` | Listar todas las sesiones |
| GET | `/api/campaigns/{id}/sessions` | Sesiones de una campaña |
| GET | `/api/sessions/{id}/transcriptions` | Transcripciones (memoria o DB) |
| GET | `/api/sessions/{id}/summary` | Resumen (memoria o DB) |
| GET | `/api/questions` | Preguntas pendientes |
| POST | `/api/questions/{id}/answer` | Responder pregunta |
| WS | `/ws/live` | WebSocket para eventos en tiempo real |

## Convenciones de Código

- Python 3.10+
- Todo async (`async/await` con `asyncio`)
- Dataclasses para modelos y eventos (frozen=True para eventos)
- ABC para interfaces de componentes (BaseListener, BaseTranscriber, BaseSummarizer)
- Linter: ruff
- Tests: pytest + pytest-asyncio (asyncio_mode = "auto")
- Imports: `from __future__ import annotations` en todos los módulos

## Variables de Entorno

| Variable | Descripción | Requerida |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Token del bot de Discord | Sí |
| `OPENAI_API_KEY` | API key de OpenAI (transcripción) | Sí |
| `ANTHROPIC_API_KEY` | API key de Anthropic (resumen) | Sí |
| `RPG_SCRIBE_HOST` | Host del Web UI (default: 127.0.0.1) | No |
| `RPG_SCRIBE_PORT` | Puerto del Web UI (default: 8000) | No |
| `RPG_SCRIBE_DB` | Ruta de la base de datos (default: rpg_scribe.db) | No |
| `DISCORD_SUMMARY_CHANNEL_ID` | Canal de Discord para resúmenes | No |
| `HF_TOKEN` | Hugging Face token (futuro: pyannote) | No |

## Testing

- 14 archivos de test en `tests/`
- 256 tests totales (254 pass, 2 fallos pre-existentes)
- Tests cubren: event bus, transcriber, summarizer, Discord listener, file listener, database, config, web, publisher, resilience, logging, main, integración, discord bot
- Usar `pytest` sin argumentos para ejecutar toda la suite
- `pytest -k test_nombre` para tests específicos
- **Fallos pre-existentes**:
  - `test_defaults_from_toml_override_dataclass_defaults`: falla si `RPG_SCRIBE_HOST` está en env vars
  - `test_generate_toml_is_valid_toml`: requiere `tomllib` (Python 3.11+), no disponible en 3.10

## Notas Importantes

- El audio de Discord llega separado por usuario (SSRC), eliminando la necesidad de diarización
- Los eventos son `frozen=True` dataclasses (inmutables)
- El summarizer usa prompts en español orientados a juegos de rol (Akelarre, OSR)
- Existe un `GENERIC_SYSTEM_PROMPT` para modo sin campaña
- La configuración de campaña se define en archivos TOML (`config/campaigns/`)
- `pydub` del documento de arquitectura fue reemplazado por `soundfile` + `numpy`
- `webrtcvad` fue reemplazado por `webrtcvad-wheels` (versión precompilada)

### DAVE E2EE y Discord Voice

- discord.py 2.7+ incluye DAVE (Discord Audio-Visual Experience) E2EE para voz
- `discord-ext-voice-recv` NO soporta descifrado DAVE → audio es ruido, no silencio
- **Fix**: monkey-patch `_patch_disable_dave()` en `discord_listener.py` que fuerza `max_dave_protocol_version = 0`
- También hay `_patch_packet_router()` que hace PacketRouter resiliente a OpusError por paquete

### Particularidades Windows

- asyncio ProactorEventLoop requiere `os._exit(0)` para SIGINT handler
- uvicorn signal handlers deben ser `lambda: None` (no `False`)
- Python 3.10: no tiene `tomllib` → se usa `tomli` como fallback

### Sync TOML → DB

- Al arrancar con `--campaign`, los players y NPCs del TOML se persisten idempotentemente a la DB
- Si ya existen (por discord_id / name), no se duplican
- Cambios hechos via Web UI se guardan en DB y en memoria (no modifican el TOML)
