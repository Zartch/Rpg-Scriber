# CODEX_REFERENCE.md - Mapa rapido del proyecto

Documento de referencia generado a partir de:

- `README.md`
- `ANTIGRAVITY.md`
- `CLAUDE.md`
- `rpg-scribe-architecture.md`
- `architectural_differences.md`
- `implementation_fase2.md`

## 1) Que es RPG Scribe

RPG Scribe es una app Python que:

1. Escucha audio de partidas (Discord).
2. Transcribe por hablante.
3. Genera resumen narrativo incremental (in-game vs meta-rol).
4. Expone estado, transcripciones y resumen en web en tiempo real.
5. Persiste campañas/sesiones/transcripciones en SQLite.

## 2) Arquitectura funcional

Pipeline principal:

`Listener -> Transcriber -> Summarizer`

Todo se desacopla por `EventBus` (pub/sub async) con eventos tipados:

- `AudioChunkEvent`
- `TranscriptionEvent`
- `SummaryUpdateEvent`
- `SystemStatusEvent`

Salidas paralelas del bus:

- DB SQLite
- Web UI (FastAPI + WebSocket)
- Discord Bot / Publisher

## 3) Estructura de codigo (fuente)

Raiz: `src/rpg_scribe/`

- `main.py`: entrypoint/orquestacion de componentes.
- `config.py`: carga config de campaña + env vars.
- `logging_config.py`: logging estructurado.
- `core/`: `event_bus.py`, `events.py`, `models.py`, `database.py`, `resilience.py`.
- `listeners/`: `base.py`, `discord_listener.py`, `file_listener.py`.
- `transcribers/`: `base.py`, `openai_transcriber.py`, `faster_whisper_transcriber.py`.
- `summarizers/`: `base.py`, `claude_summarizer.py`.
- `discord_bot/`: `bot.py`, `commands.py`, `publisher.py`.
- `web/`: `app.py`, `routes.py`, `websocket.py`, `static/`.

## 4) Interfaces externas y stack

- Discord: `discord.py` + `discord-ext-voice-recv`.
- Transcripcion: OpenAI (`gpt-4o-transcribe`) y fallback local (`faster-whisper`).
- Resumen: Anthropic Claude (Sonnet).
- Backend web: FastAPI + WebSocket.
- Persistencia: SQLite async (`aiosqlite`).
- Calidad: `pytest`, `pytest-asyncio`, `ruff`.

## 5) Ejecucion y comandos utiles

Instalacion (dev):

```bash
pip install -e ".[dev]"
```

Ejecucion con campaña:

```bash
rpg-scribe --campaign config/campaigns/example.toml
```

Tests/lint:

```bash
pytest
ruff check src/ tests/
ruff format src/ tests/
```

Comandos slash confirmados:

- `/scribe start`
- `/scribe stop`
- `/scribe status`

## 6) Configuracion y datos

Variables de entorno clave:

- `DISCORD_BOT_TOKEN`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `RPG_SCRIBE_HOST`
- `RPG_SCRIBE_PORT`
- `RPG_SCRIBE_DB`
- `DISCORD_SUMMARY_CHANNEL_ID`
- `RPG_SCRIBE_SUMMARIZER_MODEL`
- `RPG_SCRIBE_SUMMARIZER_MAX_TOKENS`
- `RPG_SCRIBE_SUMMARIZER_MAX_INPUT_CHARS`

Configuracion de campaña:

- TOML en `config/campaigns/*.toml`

Persistencia principal (tabla segun docs):

- `campaigns`
- `players`
- `npcs`
- `sessions`
- `transcriptions`
- `questions`

## 7) Estado real vs plan (importante)

Segun `architectural_differences.md` e `implementation_fase2.md`, pendientes principales:

1. Comandos `/scribe summary` y `/scribe ask`.
2. Flujo completo de preguntas del summarizer al usuario.
3. Extraccion automatica de NPCs/localizaciones al cerrar sesion.
4. Historial de sesiones en frontend.
5. `config/default.toml` y `scripts/import_campaign.py`.

## 8) Ruta rapida para cambios

- Si el cambio toca audio/voz: `listeners/` + `discord_bot/`.
- Si toca STT: `transcribers/`.
- Si toca narrativa/contexto IA: `summarizers/`.
- Si toca API/UI: `web/routes.py` + `web/static/*`.
- Si toca modelos/eventos/persistencia: `core/events.py`, `core/models.py`, `core/database.py`.

Regla de seguridad tecnica:

- Mantener contratos async y eventos inmutables.
- Evitar acoplar modulos saltando el `EventBus`.
- Acompanhar cambios funcionales con tests.

## 9) Notas operativas para agentes

- El repo ya incluye `ANTIGRAVITY.md` y `CLAUDE.md`; este archivo unifica lo esencial para lectura rapida.
- Ante conflicto entre docs, priorizar `README.md` + codigo actual + `architectural_differences.md`.
- Para trabajo incremental, usar `implementation_fase2.md` como backlog inmediato.

