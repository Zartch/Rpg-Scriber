# CLAUDE.md — RPG Scribe

Guía de referencia para Claude Code al trabajar en este proyecto.

## Descripción del Proyecto

RPG Scribe es una herramienta en Python que escucha partidas de rol en tiempo real (vía Discord), transcribe y diariza quién dice qué, y genera un resumen narrativo vivo de la sesión usando IA. Distingue entre diálogo in-game y meta-rol.

## Comandos Esenciales

```bash
# Instalar dependencias (modo desarrollo)
pip install -e ".[dev]"

# Instalar con transcripción local (faster-whisper)
pip install -e ".[local]"

# Ejecutar la aplicación
rpg-scribe --campaign config/campaigns/example.toml

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
├── main.py                  # CLI y orquestador principal (Application)
├── config.py                # Carga de configuración TOML + env vars
├── logging_config.py        # Logging estructurado con structlog
├── core/
│   ├── event_bus.py         # Bus de eventos async (pub/sub)
│   ├── events.py            # Dataclasses de eventos tipados
│   ├── models.py            # Modelos de dominio y config
│   ├── database.py          # Wrapper async SQLite
│   └── resilience.py        # Retry, circuit breaker, reconnection
├── listeners/
│   ├── base.py              # BaseListener ABC
│   ├── discord_listener.py  # Listener de canal de voz Discord
│   └── file_listener.py     # Listener de archivos (testing)
├── transcribers/
│   ├── base.py              # BaseTranscriber ABC
│   ├── openai_transcriber.py    # OpenAI API (gpt-4o-transcribe)
│   └── faster_whisper_transcriber.py  # Fallback local
├── summarizers/
│   ├── base.py              # BaseSummarizer ABC
│   └── claude_summarizer.py # Claude Sonnet API
├── discord_bot/
│   ├── bot.py               # Factory del bot Discord
│   ├── commands.py          # Slash commands (/scribe start/stop/status)
│   └── publisher.py         # Publica resúmenes como embeds en Discord
└── web/
    ├── app.py               # Factory de FastAPI
    ├── routes.py            # Endpoints REST + WebSocket
    ├── websocket.py         # WebSocket bridge y ConnectionManager
    └── static/              # Frontend (HTML/JS/CSS)
```

## Arquitectura

- **Patrón**: Event-driven async con pub/sub via `EventBus`
- **Eventos**: `AudioChunkEvent` → `TranscriptionEvent` → `SummaryUpdateEvent` + `SystemStatusEvent`
- **Flujo**: Listener captura audio → Transcriber genera texto → Summarizer resume narrativamente
- **Base de datos**: SQLite async (aiosqlite), 6 tablas: campaigns, players, npcs, sessions, transcriptions, questions
- **Web**: FastAPI con WebSocket para actualizaciones en tiempo real

## Convenciones de Código

- Python 3.11+
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
- Tests cubren: event bus, transcriber, summarizer, Discord listener, file listener, database, config, web, publisher, resilience, logging, main, integración
- Usar `pytest` sin argumentos para ejecutar toda la suite
- `pytest -k test_nombre` para tests específicos

## Notas Importantes

- El audio de Discord llega separado por usuario (SSRC), eliminando la necesidad de diarización
- Los eventos son `frozen=True` dataclasses (inmutables)
- El summarizer usa prompts en español orientados a juegos de rol (Akelarre, OSR)
- La configuración de campaña se define en archivos TOML (`config/campaigns/`)
- `pydub` del documento de arquitectura fue reemplazado por `soundfile` + `numpy`
- `webrtcvad` fue reemplazado por `webrtcvad-wheels` (versión precompilada)
