# ANTIGRAVITY.md — RPG Scribe

Guía de referencia rápida y documentación del proyecto para Antigravity (IA), generada tras la revisión inicial del proyecto.

## Resumen del Proyecto

RPG Scribe es un bot de Discord / aplicación web escrita en Python (3.11+) que graba canales de voz en Discord, los transcribe separando por usuario y resume las partidas de rol usando modelos de lenguaje (Claude). Distingue metajuego de diálogo de personajes y provee un dashboard en vivo (FastAPI + WebSockets) para gestionar la campaña, jugadores y NPCs.

## Arquitectura Base

El sistema está completamente desacoplado mediante eventos asíncronos (`EventBus`). Sigue una arquitectura de Pipeline (Listener -> Transcriber -> Summarizer), donde cada componente reacciona a los eventos emitidos por el anterior sin acoplamiento directo.

```
[Discord Listener] --(AudioChunkEvent)--> [Transcriber (OpenAI/Whisper)] --(TranscriptionEvent)--> [Summarizer (Claude)] --(SummaryUpdateEvent)
```
- **Persistencia**: SQLite asíncrono (`aiosqlite`). 6 tablas core (campaigns, players, npcs, sessions, transcriptions, questions).
- **Web UI**: Servido con FastAPI, permitiendo ajustes a la campaña en vivo por REST y actualizaciones por WS (`/ws/live`).
- **Bot Discord**: Usa `discord.py` y `discord-ext-voice-recv` con un monkey-patch crucial para desactivar E2EE DAVE temporalmente, dado que `discord-ext-voice-recv` no lo soporta todavía para el descifrado.

## Comandos Útiles para el Agente

```bash
# Entorno virtual y dependencias
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\Activate.ps1 # Windows
pip install -e ".[dev]"    # Instalar modo dev

# Pruebas y Linting
pytest                     # Ejecutar todos los test
pytest -v -k test_name     # Test específico
ruff check src/ tests/     # Linting manual
ruff format src/ tests/    # Formateo automático

# Ejecución
rpg-scribe --campaign config/campaigns/example.toml
```

## Convenciones de Código y Detalles a Tener en Cuenta

1. **Todo es asíncrono**: Uso estricto de `async/await` y `asyncio`.
2. **Dataclasses**: Extensivo uso de `dataclasses`, especialmente para los eventos que son `frozen=True` (inmutables).
3. **Manejo de Tareas e Hilos**: En Windows (SO del usuario), hay particularidades con los signals (p. ej., `os._exit(0)` necesario a veces para salir limpiamente del ProactorEventLoop).
4. **Resiliencia Modular**: El módulo `core/resilience.py` se encarga de reintentos y circuit breakers. Al añadir llamadas a redes (APIs como OpenAI/Anthropic), se debe emplear este sistema.
5. **Configuración DB vs TOML**: Al cargar una campaña por TOML, la app persiste a la DB de manera idempotente. Editables in-app usan REST (PATCH, POST) pero guardan a DB y memoria local sin escribir back al `.toml`.
6. **Manejo de Versionado**: No utilizar `tomllib` de `sys` si estamos probando compatibilidad Python 3.10; se requiere `tomli` como fallback en esos entornos.

## Mapeo del Árbol de Directorios

- `src/rpg_scribe/`: Raíz del código fuente.
  - `core/`: Bus de eventos, base de datos (dataclasses/logica SQL), resiliencia de la app.
  - `listeners/`: Entrada de audio (Discord SSRC en vez de VAD puramente, o archivos locales).
  - `transcribers/`: Adapters para APIs (Whisper/OpenAI).
  - `summarizers/`: Lógica de prompts (in-game vs meta) enviada a Anthropic.
  - `telegram/`, `discord_bot/`, etc.: Interfaces de notificación/control.
  - `web/`: Backend FastAPI y los endpoints estáticos.
- `tests/`: Batería extensa de pytest (asyncio_mode="auto").
- `config/campaigns/`: Plantillas TOML de campaña.

## Workflow Recomendado para Cambios

1. **Identificar la Capa Afectada**: Si el USER pide "Añadir un nuevo LLM", dirigirse a `/summarizers/` o `/transcribers/`, creando una nueva subclase que herede del `BaseTranscriber` o `BaseSummarizer` correspondiente.
2. **Actualizar el Event Bus / Eventos**: Si el nuevo feature requiere pasar nueva información, editar `/core/events.py` antes que la implementación, recordando mantener los dataclasses estables e inmutables.
3. **Tests Unitarios**: El proyecto tiene más de 250 test. Añadir test unitario antes/durante el parche.
4. **Formato final**: Siempre corroborar el estilo con `ruff check src/ tests/` y resolver dependencias/lints antes de dar por terminado un task.
