# Diferencias Arquitectónicas: Documento vs Implementación

Comparación entre lo establecido en `rpg-scribe-architecture.md` y lo que realmente está implementado en el código fuente.

---

## 1. Estructura del Proyecto

### Documento (Sección 9)

```
rpg-scribe/
├── config/
│   ├── default.toml
│   └── campaigns/
│       └── example-campaign.toml
├── src/rpg_scribe/
│   └── discord_bot/
│       ├── bot.py
│       └── commands.py
├── tests/
│   ├── test_event_bus.py
│   ├── test_transcriber.py
│   ├── test_summarizer.py
│   └── fixtures/
│       └── sample_audio/
└── scripts/
    ├── setup_discord_bot.py
    └── import_campaign.py
```

### Implementación Real

```
rpg-scribe/
├── config/
│   └── campaigns/
│       └── example.toml          # Sin default.toml
├── src/rpg_scribe/
│   ├── logging_config.py         # No documentado en arquitectura
│   ├── discord_bot/
│   │   ├── bot.py
│   │   ├── commands.py
│   │   └── publisher.py          # No documentado en estructura
│   └── core/
│       └── resilience.py         # No documentado en estructura
├── tests/                        # 14 archivos (más de los 3 documentados)
│   ├── test_event_bus.py
│   ├── test_transcriber.py
│   ├── test_summarizer.py
│   ├── test_discord_listener.py
│   ├── test_file_listener.py
│   ├── test_database.py
│   ├── test_config.py
│   ├── test_main.py
│   ├── test_web.py
│   ├── test_publisher.py
│   ├── test_resilience.py
│   ├── test_logging_config.py
│   └── test_integration.py       # Sin directorio fixtures/sample_audio/
└── scripts/
    └── setup_discord_bot.py      # Sin import_campaign.py
```

### Diferencias

| Aspecto | Documento | Implementación | Estado |
|---|---|---|---|
| `config/default.toml` | Planificado | No existe | No implementado |
| `scripts/import_campaign.py` | Planificado | No existe | No implementado |
| `tests/fixtures/sample_audio/` | Planificado | No existe | No implementado |
| `discord_bot/publisher.py` | No en estructura (sí en texto, sección 7.3) | Implementado | Extra |
| `core/resilience.py` | No en estructura (sí en Fase 5) | Implementado | Extra |
| `logging_config.py` | No documentado | Implementado | Extra |
| Cobertura de tests | 3 archivos listados | 14 archivos | Supera lo documentado |

---

## 2. Eventos (Sección 3.1)

### Documento

```python
@dataclass
class AudioChunkEvent:
    session_id: str
    speaker_id: str
    speaker_name: str
    audio_data: bytes
    timestamp: float
    duration_ms: int
    source: str

@dataclass
class SystemStatusEvent:
    component: str
    status: str
    message: str
    timestamp: float
```

### Implementación (`core/events.py`)

- Todos los eventos usan `@dataclass(frozen=True)` — el documento usa `@dataclass` simple.
- `SystemStatusEvent.timestamp` tiene `default_factory=time.time` en la implementación; en el documento no tiene default.
- Los campos y tipos de los 4 eventos coinciden exactamente con el documento.

| Aspecto | Documento | Implementación |
|---|---|---|
| Inmutabilidad (frozen) | No especificado | `frozen=True` en todos |
| `SystemStatusEvent.timestamp` | Sin default | `default_factory=time.time` |
| Campos de eventos | 4 eventos definidos | 4 eventos idénticos |

---

## 3. Event Bus (Sección 3.2)

### Documento

```python
class EventBus:
    def subscribe(self, event_type: Type, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: Type, handler: Callable) -> None: ...
    async def publish(self, event: Any) -> None: ...
```

### Implementación

Coincide exactamente con la interfaz documentada. La implementación usa `asyncio.gather` con `return_exceptions=True` para ejecutar handlers concurrentemente sin que un fallo afecte a los demás. Incluye logging de excepciones por handler.

**Estado: Coincide completamente.**

---

## 4. Listener (Sección 4)

### Documento

```python
class BaseListener(ABC):
    def __init__(self, event_bus: EventBus, config: ListenerConfig): ...
    async def connect(self, session_id: str, **kwargs) -> None: ...
    async def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
```

Implementaciones planificadas:
- `DiscordListener` con VAD y chunking inteligente
- `FileListener` para testing
- `TeamsListener` (futuro)
- `SlackListener` (futuro)

### Implementación

- `BaseListener`: Coincide con la interfaz documentada.
- `DiscordListener`: Implementado con VAD (webrtcvad), chunking por silencios, separación por usuario.
- `FileListener`: Implementado para testing/re-procesado.
- `TeamsListener` / `SlackListener`: No implementados (marcados como futuros en el documento).

| Aspecto | Documento | Implementación |
|---|---|---|
| BaseListener ABC | Definido | Implementado, coincide |
| DiscordListener | Definido | Implementado |
| FileListener | Definido | Implementado |
| TeamsListener | Futuro | No implementado (esperado) |
| SlackListener | Futuro | No implementado (esperado) |

---

## 5. Transcriber (Sección 5)

### Documento

```python
class BaseTranscriber(ABC):
    def __init__(self, event_bus: EventBus, config: TranscriberConfig): ...
    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent: ...
    async def start(self) -> None: ...
    async def _handle_audio(self, event: AudioChunkEvent) -> None: ...
```

Implementaciones planificadas:
- `OpenAITranscriber` con cola async, retry, caché por hash
- `FasterWhisperTranscriber` como fallback local
- `MixedAudioTranscriber` (futuro, con pyannote para diarización)

### Implementación

- `OpenAITranscriber`: Implementado con cola async, concurrencia limitada, retry con backoff, caché por hash de audio, prompt contextual.
- `FasterWhisperTranscriber`: Implementado como fallback local.
- `MixedAudioTranscriber`: No implementado (marcado como futuro en el documento).

| Aspecto | Documento | Implementación |
|---|---|---|
| BaseTranscriber ABC | Definido | Implementado |
| OpenAITranscriber | Definido | Implementado con todas las features |
| FasterWhisperTranscriber | Definido | Implementado |
| MixedAudioTranscriber | Futuro | No implementado (esperado) |

---

## 6. Summarizer (Sección 6)

### Documento

```python
class BaseSummarizer(ABC):
    def __init__(self, event_bus, config, campaign): ...
    async def process_transcription(self, event) -> None: ...
    async def get_session_summary(self) -> str: ...
    async def get_campaign_summary(self) -> str: ...
    async def finalize_session(self) -> str: ...
```

Features planificadas:
- Doble resumen (sesión + campaña)
- Clasificación in-game vs meta-rol
- Sistema de preguntas al usuario
- Actualización cada ~2 min o ~20 intervenciones
- Extracción de PNJs/localizaciones al finalizar

### Implementación

- `ClaudeSummarizer`: Implementado con doble resumen, clasificación in-game/meta, acumulación y actualización periódica, finalización de sesión.
- El modelo usado es `claude-sonnet-4-20250514` (el documento menciona genéricamente "Claude Sonnet").
- System prompts en español orientados a campañas de rol.

| Aspecto | Documento | Implementación |
|---|---|---|
| BaseSummarizer ABC | Definido | Implementado |
| ClaudeSummarizer | Definido | Implementado |
| Doble resumen | Planificado | Implementado |
| Clasificación in-game/meta | Planificado | Implementado |
| Preguntas al usuario | Planificado | Parcial (DB soporta, pero no hay UI completa) |
| Extracción automática de PNJs | Planificado | No verificado en código |

---

## 7. Web UI (Sección 7)

### Documento

```
FastAPI (backend)
├── REST: /api/sessions, /api/campaigns, /api/status
├── WebSocket: /ws/live
└── Static HTML/JS/CSS

Frontend (vanilla HTML + JS + Tailwind)
├── Panel de estado
├── Transcripción en vivo
├── Resumen en vivo
├── Selector de campaña/sesión
├── Historial de sesiones
└── Panel de preguntas pendientes
```

### Implementación

- **Backend**: FastAPI implementado con todos los endpoints REST documentados + WebSocket.
- **Endpoints implementados**: `/api/status`, `/api/sessions/{id}/transcriptions`, `/api/sessions/{id}/summary`, `/api/questions`, `/api/questions/{id}/answer`, `/api/campaigns`.
- **WebSocket**: `/ws/live` implementado con `ConnectionManager` y `WebSocketBridge`.
- **Frontend**: HTML + JS + CSS vanilla (sin Tailwind). Ficheros: `index.html`, `app.js`, `style.css`.

| Aspecto | Documento | Implementación |
|---|---|---|
| FastAPI backend | Planificado | Implementado |
| REST endpoints | Planificado | Implementado |
| WebSocket live | Planificado | Implementado |
| Frontend con Tailwind | Planificado | Implementado sin Tailwind (CSS vanilla) |
| Selector de campaña/sesión | Planificado | Parcial (en-memory WebState, no persiste todas las sesiones) |
| Historial de sesiones | Planificado | No como endpoint REST dedicado |

---

## 8. Discord Bot (Secciones 4.3, 7.3)

### Documento

Comandos planificados:
- `/scribe start` — Iniciar grabación
- `/scribe stop` — Detener grabación
- `/scribe status` — Ver estado
- `/scribe summary` — Ver resumen actual
- `/scribe ask` — Responder preguntas del summarizer
- Canal de texto con embeds actualizados en vivo

### Implementación

- `/scribe start`, `/scribe stop`, `/scribe status`: Implementados en `commands.py` como `ScribeCog`.
- `/scribe summary`: **No implementado**.
- `/scribe ask`: **No implementado**.
- `DiscordSummaryPublisher`: Implementado en `publisher.py`, publica embeds actualizados en un canal de texto.

| Aspecto | Documento | Implementación |
|---|---|---|
| /scribe start | Planificado | Implementado |
| /scribe stop | Planificado | Implementado |
| /scribe status | Planificado | Implementado |
| /scribe summary | Planificado | No implementado |
| /scribe ask | Planificado | No implementado |
| Embeds en canal de texto | Planificado | Implementado (publisher.py) |

---

## 9. Base de Datos (Sección 8)

### Documento

6 tablas: campaigns, players, npcs, sessions, transcriptions, questions.

### Implementación

Esquema SQL idéntico al documento. Las 6 tablas están implementadas con los mismos campos y tipos. El wrapper `Database` incluye métodos CRUD para todas las tablas.

Diferencia menor:
- El documento usa `TIMESTAMP` como tipo de columna; la implementación usa `REAL` (Unix timestamps como float). Funcionalmente equivalente en SQLite.

**Estado: Coincide completamente (diferencia cosmética en tipos de columna).**

---

## 10. Dependencias (Sección 13)

| Dependencia | Documento | Implementación | Nota |
|---|---|---|---|
| `pydantic>=2.0` | Sí | Sí | Coincide |
| `discord.py[voice]>=2.3` | Sí | Sí | Coincide |
| `discord-ext-voice-recv>=0.5` | `>=0.5` | `>=0.5.0a167` | Versión más específica |
| `webrtcvad>=2.0.10` | `webrtcvad` | `webrtcvad-wheels` | Paquete diferente (precompilado) |
| `numpy>=1.24` | Sí | Sí | Coincide |
| `soundfile>=0.12` | Sí | Sí | Coincide |
| `openai>=1.0` | Sí | Sí | Coincide |
| `httpx>=0.25` | Sí | Sí | Coincide |
| `anthropic>=0.30` | Sí | Sí | Coincide |
| `fastapi>=0.100` | Sí | Sí | Coincide |
| `uvicorn[standard]>=0.23` | Sí | Sí | Coincide |
| `websockets>=12.0` | Sí | Sí | Coincide |
| `aiosqlite>=0.19` | Sí | Sí | Coincide |
| `structlog>=23.0` | Sí | Sí | Coincide |
| `tomli>=2.0` | Sí | Sí (condicional `python_version<'3.11'`) | Coincide |
| `pydub>=0.25` | Sí | **No** | Reemplazado por soundfile+numpy |
| `google-cloud-speech` | Mencionado como futuro | No | Esperado |

---

## 11. Configuración (Sección 10)

### Documento

Formato TOML con secciones: `[campaign]`, `[campaign.dm]`, `[[campaign.players]]`, `[[campaign.npcs]]`, `[campaign.custom_instructions]`.

### Implementación

El formato TOML coincide. `config.py` carga correctamente todos los campos documentados. Diferencia: la implementación usa `tomllib` (stdlib Python 3.11) con fallback a `tomli`, mientras que el documento solo menciona `tomli`.

**Estado: Coincide.**

---

## 12. Componentes No Documentados en la Arquitectura

Estos módulos existen en la implementación pero no aparecen en el documento de arquitectura:

1. **`logging_config.py`**: Configuración de logging estructurado con structlog. Soporta salida JSON y formateo para consola.
2. **`core/resilience.py`**: Módulo completo de resiliencia con:
   - `retry_async()` — Retry con backoff exponencial
   - `CircuitBreaker` — Patrón circuit breaker con estados CLOSED/OPEN/HALF_OPEN
   - `ReconnectionManager` — Gestión automática de reconexiones con monitoreo periódico
3. **`discord_bot/publisher.py`**: Publicador de resúmenes como embeds de Discord. Mencionado en la sección 7.3 del documento pero no incluido en la estructura de archivos.

---

## 13. Plan de Implementación por Fases

| Fase | Descripción | Estado |
|---|---|---|
| Fase 0 | Fundamentos (event bus, eventos, modelos, DB, config) | Completada |
| Fase 1 | Listener de Discord (bot, VAD, chunking, FileListener) | Completada |
| Fase 2 | Transcriptor (OpenAI + FasterWhisper) | Completada |
| Fase 3 | Resumidor (Claude, doble resumen, clasificación) | Completada |
| Fase 4 | Web UI (FastAPI, WebSocket, dashboard) | Completada |
| Fase 5 | Integración, resiliencia, publisher, orquestación | Completada |

Las 5 fases (+Fase 0) han sido completadas. Los items pendientes de la Fase 5 eran:
- "Documentación de usuario (README)" — **No realizado** (pendiente)
- "Prueba end-to-end con sesión real" — **No verificable desde el código**

---

## 14. Resumen de Diferencias

### Implementado pero no documentado en la estructura
- `logging_config.py`
- `core/resilience.py` (retry, circuit breaker, reconnection)
- `discord_bot/publisher.py`
- 14 archivos de test (vs 3 documentados)

### Documentado pero no implementado
- `config/default.toml`
- `scripts/import_campaign.py`
- `tests/fixtures/sample_audio/`
- Comandos `/scribe summary` y `/scribe ask`
- Frontend con Tailwind CSS (se usa CSS vanilla)
- Dependencia `pydub` (reemplazada por soundfile+numpy)

### Diferencias menores
- Eventos usan `frozen=True` (no especificado en documento)
- `webrtcvad` → `webrtcvad-wheels`
- Tipos de columna SQL: `TIMESTAMP` → `REAL`
- `tomli` → `tomllib` (stdlib) con fallback
