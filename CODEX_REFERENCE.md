# CODEX_REFERENCE.md - mapa rapido del proyecto

## 1) Que es RPG Scribe

RPG Scribe es una app Python que:

1. Escucha partidas (Discord u origen de archivo).
2. Transcribe por hablante.
3. Genera resumen incremental de sesion y de campana.
4. Publica estado en Web UI y Discord.
5. Persiste campanas, sesiones y transcripciones en SQLite.

## 2) Arquitectura funcional

Pipeline principal:

`Listener -> Transcriber -> Summarizer`

Desacople por `EventBus` async con eventos tipados (`AudioChunkEvent`, `TranscriptionEvent`, `SummaryUpdateEvent`, `SystemStatusEvent`, etc.).

Consumidores paralelos:

- DB SQLite
- Web UI (REST + WebSocket)
- Discord publisher/bot

## 3) Estructura de codigo (fuente)

Raiz: `src/rpg_scribe/`

- `main.py`: orquestacion y ciclo de vida.
- `config.py`: carga config de campana + env vars.
- `core/`: eventos, modelos, DB, resiliencia.
- `listeners/`: fuentes de audio/eventos.
- `transcribers/`: STT OpenAI y faster-whisper.
- `summarizers/`: resumen incremental con Claude.
- `discord_bot/`: comandos slash y publicacion.
- `web/`: FastAPI, rutas REST, bridge WS, frontend estatico.

## 4) UI web actual (revisado en codigo)

Frontend: `src/rpg_scribe/web/static/index.html`, `app.js`, `style.css`  
Backend UI: `src/rpg_scribe/web/app.py`, `routes.py`, `websocket.py`

Que hace hoy:

1. Muestra conexion WS (`/ws/live`) y estado de componentes (`listener`, `transcriber`, `summarizer`).
2. Renderiza transcripcion en vivo y resumen de sesion/campana.
3. Panel de campana editable (nombre, sistema, descripcion, instrucciones) con `PATCH /api/campaigns/{campaign_id}`.
4. Gestion de jugadores:
   - lista y edicion inline (`PUT /api/campaigns/{campaign_id}/players/{player_id}`).
5. Gestion de NPCs:
   - lista, alta y edicion (`POST/PUT /api/campaigns/{campaign_id}/npcs...`).
6. Preguntas pendientes:
   - polling cada 5s a `/api/questions` y respuesta por `POST /api/questions/{id}/answer`.
7. Historial de sesiones en sidebar:
   - carga por campana (`/api/campaigns/{campaign_id}/sessions`) o global (`/api/sessions`).
   - permite abrir una sesion historica y cargar transcripciones + resumen por REST.
   - modo "Back to Live" para volver al stream en tiempo real.
8. Finalizacion manual de sesion activa:
   - boton "Finalize Session" -> `POST /api/sessions/{session_id}/finalize`.

Comportamiento tecnico:

- `create_app()` suscribe `WebState` y `WebSocketBridge` al `EventBus`.
- REST sirve snapshot actual (memoria) y, para historico, fallback a DB.
- El frontend ignora mensajes WS cuando visualiza una sesion historica.

## 5) Stack e integraciones

- Web: FastAPI + WebSocket.
- DB: SQLite async (`aiosqlite`).
- STT: OpenAI + faster-whisper.
- LLM resumen: Anthropic Claude.
- Discord: `discord.py` + `discord-ext-voice-recv`.
- Calidad: `pytest`, `pytest-asyncio`, `ruff`.

## 6) Ejecucion rapida

```bash
pip install -e ".[dev]"
rpg-scribe --campaign config/campaigns/example.toml
pytest
ruff check src/ tests/
```

## 7) Estado real vs backlog

Pendientes importantes (segun docs + codigo actual):

1. Completar flujo end-to-end de preguntas generadas por summarizer (UI ya responde preguntas, pero la generacion automatica sigue incompleta).
2. Comandos slash adicionales (`/scribe summary`, `/scribe ask`).
3. Extraccion automatica de NPCs/localizaciones al cierre de sesion.

Nota: el historial de sesiones en frontend ya esta implementado.

## 8) Ruta rapida para cambios

- Audio/voz: `listeners/` + `discord_bot/`.
- STT: `transcribers/`.
- Resumen/IA: `summarizers/`.
- API/UI: `web/routes.py` + `web/static/*`.
- Modelos/eventos/DB: `core/models.py`, `core/events.py`, `core/database.py`.

Reglas:

- Mantener contratos async y eventos inmutables.
- Evitar acople directo saltando el `EventBus`.
- Acompanhar cambios funcionales con tests.
