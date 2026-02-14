# RPG Scribe — Arquitectura y Plan de Implementación

## 1. Visión del Proyecto

**RPG Scribe** es una herramienta que escucha partidas de rol en tiempo real (inicialmente por Discord), transcribe y diariza quién dice qué, y genera un resumen narrativo vivo de la sesión — distinguiendo entre diálogo in-game y meta-rol.

Soporta múltiples campañas con diferentes sistemas de juego (Akelarre, Fading Suns, Ars Magica, etc.), mantiene un resumen acumulado por campaña, y permite visualizar el progreso en tiempo real.

---

## 2. Decisiones Técnicas Clave

### 2.1 Diarización: Discord nos la da "gratis"

**Decisión crítica:** Discord envía audio **separado por usuario** (cada usuario tiene su propio SSRC en el protocolo RTP). Esto significa que **no necesitamos modelos de diarización** (pyannote, NeMo, etc.) para el caso de Discord.

El bot recibe un stream PCM independiente por cada miembro del canal de voz. Sabemos exactamente quién habla en cada momento. Esto simplifica enormemente la arquitectura y elimina errores de atribución.

**Para fuentes futuras** (Teams, Slack, audio mezclado), sí necesitaríamos diarización real. Por eso la interfaz del módulo `Transcriber` acepta tanto audio pre-diarizado (con speaker_id) como audio mezclado.

### 2.2 Transcripción: API de OpenAI

Con presupuesto sin límite y sesiones de 4-6h, la mejor opción es la **API de OpenAI**:

- **Para transcripción por chunks:** `gpt-4o-transcribe` o `whisper-1` con `stream=True`
- **Alternativa local (fallback):** `faster-whisper` con modelo `medium` (cabe en la 1080 GTX 8GB)

La estrategia: enviar chunks de ~10-15 segundos de audio por usuario a la API. Con audio ya separado por usuario, cada chunk es mono-speaker, lo que maximiza la precisión.

### 2.3 Resumen: Claude API (Sonnet)

Para el resumidor usaremos **Claude Sonnet** vía API:

- Ventana de contexto grande (200K tokens) → puede mantener toda la sesión en contexto
- Excelente para narrativa, comprensión de contexto de juego de rol, y distinción in-game/meta
- Coste razonable para uso continuo durante sesiones largas

### 2.4 Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Bot Discord | `discord.py` + `discord-ext-voice-recv` |
| Transcripción (primario) | OpenAI API (`gpt-4o-transcribe`) |
| Transcripción (fallback) | `faster-whisper` local |
| Resumen | Anthropic API (Claude Sonnet) |
| Cola de mensajes interna | `asyncio.Queue` |
| Base de datos | SQLite (campañas, sesiones, personajes) |
| Visualización | Web local con FastAPI + WebSocket + HTML/JS |
| Configuración | YAML/TOML por campaña |

---

## 3. Arquitectura de Componentes

```
┌─────────────────────────────────────────────────────────┐
│                     RPG SCRIBE                          │
│                                                         │
│  ┌─────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │         │    │              │    │              │   │
│  │ Listener│───▶│ Transcriber  │───▶│  Summarizer  │   │
│  │         │    │              │    │              │   │
│  └─────────┘    └──────────────┘    └──────────────┘   │
│       │                │                   │            │
│       │                │                   │            │
│       ▼                ▼                   ▼            │
│  ┌──────────────────────────────────────────────┐      │
│  │              Event Bus (asyncio)              │      │
│  └──────────────────────────────────────────────┘      │
│       │                │                   │            │
│       ▼                ▼                   ▼            │
│  ┌──────────┐   ┌───────────┐    ┌──────────────┐     │
│  │ Session  │   │  Campaign  │    │    Web UI     │     │
│  │ Store    │   │  Store     │    │  (FastAPI)    │     │
│  └──────────┘   └───────────┘    └──────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Interfaces (Contratos entre módulos)

Cada módulo se comunica mediante **eventos tipados** a través de un bus de eventos async. Esto permite intercambiar cualquier módulo sin afectar al resto.

```python
# === EVENTOS (dataclasses) ===

@dataclass
class AudioChunkEvent:
    """Emitido por el Listener cuando tiene un chunk de audio listo."""
    session_id: str
    speaker_id: str          # ID del usuario en la plataforma
    speaker_name: str        # Nombre legible
    audio_data: bytes        # PCM 16-bit 48kHz mono
    timestamp: float         # Unix timestamp del inicio del chunk
    duration_ms: int         # Duración en milisegundos
    source: str              # "discord", "teams", "file", etc.

@dataclass
class TranscriptionEvent:
    """Emitido por el Transcriber cuando tiene texto."""
    session_id: str
    speaker_id: str
    speaker_name: str
    text: str
    timestamp: float
    confidence: float        # 0.0 - 1.0
    is_partial: bool         # True si es transcripción parcial/streaming

@dataclass
class SummaryUpdateEvent:
    """Emitido por el Summarizer cuando actualiza el resumen."""
    session_id: str
    session_summary: str     # Resumen de la sesión actual
    campaign_summary: str    # Resumen acumulado de la campaña
    last_updated: float
    update_type: str         # "incremental", "revision", "final"

@dataclass
class SystemStatusEvent:
    """Estado del sistema para la visualización."""
    component: str           # "listener", "transcriber", "summarizer"
    status: str              # "running", "error", "idle"
    message: str
    timestamp: float
```

### 3.2 Event Bus

```python
class EventBus:
    """Bus de eventos async. Patrón pub/sub desacoplado."""

    def subscribe(self, event_type: Type, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: Type, handler: Callable) -> None: ...
    async def publish(self, event: Any) -> None: ...
```

---

## 4. Módulo 1: Listener (Escuchador)

### 4.1 Responsabilidad

Conectarse a una fuente de audio, capturar audio por usuario, y emitir `AudioChunkEvent` de forma continua.

### 4.2 Interfaz abstracta

```python
class BaseListener(ABC):
    """Interfaz que cualquier listener debe implementar."""

    def __init__(self, event_bus: EventBus, config: ListenerConfig): ...

    @abstractmethod
    async def connect(self, session_id: str, **kwargs) -> None:
        """Conectarse a la fuente de audio."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Desconectarse limpiamente."""
        ...

    @abstractmethod
    def is_connected(self) -> bool: ...
```

### 4.3 Implementación Discord

```
DiscordListener
├── Usa discord.py + discord-ext-voice-recv
├── Se conecta al canal de voz como bot
├── Recibe audio PCM separado por usuario (SSRC → User mapping)
├── Acumula audio por usuario en buffers de ~10 segundos
├── Usa VAD (Voice Activity Detection) simple para detectar silencios
│   └── silenttools o webrtcvad para no enviar chunks vacíos
├── Emite AudioChunkEvent con speaker_id = discord_user_id
└── Comandos slash: /scribe start, /scribe stop, /scribe status
```

**Estrategia de chunking:**
- Buffer circular por usuario de 10 segundos
- Se emite un chunk cuando:
  - El buffer está lleno (10s)
  - Se detecta un silencio >1.5s (fin de frase probable)
  - Se lleva >5s de audio acumulado y hay una pausa >0.5s
- Esto permite transcripción quasi-real-time sin cortar palabras

### 4.4 Implementaciones futuras

| Fuente | Notas |
|---|---|
| `FileListener` | Lee un archivo de audio existente. Útil para testing y para re-procesar sesiones grabadas. |
| `TeamsListener` | Requiere Microsoft Graph API + permisos de aplicación. Audio mezclado → necesita diarización real. |
| `SlackListener` | Slack Huddles API. Similar a Teams. |

---

## 5. Módulo 2: Transcriber (Transcriptor + Diarización)

### 5.1 Responsabilidad

Recibir `AudioChunkEvent`, transcribir el audio a texto, y emitir `TranscriptionEvent`.

Cuando el audio viene pre-diarizado (Discord), simplemente transcribe. Cuando viene mezclado (futuro), también diariza.

### 5.2 Interfaz abstracta

```python
class BaseTranscriber(ABC):
    """Interfaz que cualquier transcriber debe implementar."""

    def __init__(self, event_bus: EventBus, config: TranscriberConfig): ...

    @abstractmethod
    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        """Transcribir un chunk de audio."""
        ...

    async def start(self) -> None:
        """Subscribirse al bus y empezar a procesar."""
        self.event_bus.subscribe(AudioChunkEvent, self._handle_audio)

    async def _handle_audio(self, event: AudioChunkEvent) -> None:
        result = await self.transcribe(event)
        if result.text.strip():  # No emitir transcripciones vacías
            await self.event_bus.publish(result)
```

### 5.3 Implementación OpenAI API

```
OpenAITranscriber
├── Envía chunks de audio a la API de OpenAI
├── Usa gpt-4o-transcribe para máxima calidad
├── Prompt contextual: incluye nombres de personajes como hint
│   └── "Nombres esperados: Rodrigo, Aelar, DM, Gandrik..."
├── Idioma fijado por configuración de campaña (es, en, etc.)
├── Cola de procesamiento async con concurrencia limitada (3-5 requests paralelos)
├── Retry con backoff exponencial
└── Caché de resultados por chunk_hash (por si se re-procesa)
```

### 5.4 Implementación Local (Fallback)

```
FasterWhisperTranscriber
├── Usa faster-whisper con modelo medium (o small para la 1080)
├── Procesamiento en GPU local
├── Mismo contrato de entrada/salida
├── Más lento pero sin coste por uso
└── Útil si hay problemas de red o para testing offline
```

### 5.5 Sobre la diarización

Para Discord, la diarización es trivial (ya viene con speaker_id). Para fuentes futuras con audio mezclado, se añadiría un paso de diarización:

```
MixedAudioTranscriber (futuro)
├── Recibe audio mezclado (speaker_id = "mixed")
├── Paso 1: pyannote-audio para diarización
│   └── Opcionalmente con voice profiles pre-entrenados
├── Paso 2: Para cada segmento diarizado, transcribir con Whisper
├── Paso 3: Emitir TranscriptionEvent con speaker_id estimado
└── Mapeo speaker_label → nombre real via embeddings de voz
```

---

## 6. Módulo 3: Summarizer (Resumidor)

### 6.1 Responsabilidad

Este es el cerebro. Recibe `TranscriptionEvent`, mantiene el contexto de la sesión y campaña, y genera/actualiza resúmenes continuamente.

### 6.2 Diseño de doble resumen

```
┌─────────────────────────┐     ┌─────────────────────────┐
│   RESUMEN DE SESIÓN     │     │   RESUMEN DE CAMPAÑA    │
│                         │     │                         │
│ Narrativa detallada de  │     │ Resumen acumulado de    │
│ lo que pasa en esta     │────▶│ toda la partida.        │
│ sesión específica.      │     │ Se actualiza al final   │
│ Se actualiza cada ~2min │     │ de cada sesión.         │
│ o cada N turnos.        │     │                         │
└─────────────────────────┘     └─────────────────────────┘
```

### 6.3 Interfaz abstracta

```python
class BaseSummarizer(ABC):
    """Interfaz que cualquier summarizer debe implementar."""

    def __init__(self, event_bus: EventBus, config: SummarizerConfig,
                 campaign: CampaignContext): ...

    @abstractmethod
    async def process_transcription(self, event: TranscriptionEvent) -> None:
        """Procesar una nueva transcripción."""
        ...

    @abstractmethod
    async def get_session_summary(self) -> str:
        """Obtener el resumen actual de la sesión."""
        ...

    @abstractmethod
    async def get_campaign_summary(self) -> str:
        """Obtener el resumen acumulado de la campaña."""
        ...

    @abstractmethod
    async def finalize_session(self) -> str:
        """Generar el resumen final pulido de la sesión."""
        ...
```

### 6.4 Implementación Claude

```
ClaudeSummarizer
├── Acumula transcripciones en un buffer
├── Cada ~2 minutos (o cada ~20 intervenciones):
│   ├── Envía al LLM el contexto + nuevas transcripciones
│   ├── System prompt con:
│   │   ├── Sistema de juego y reglas relevantes
│   │   ├── Lista de PJs con nombre real ↔ nombre de personaje
│   │   ├── PNJs conocidos
│   │   ├── Resumen de campaña hasta ahora
│   │   └── Instrucciones de formato y estilo
│   ├── Pide actualizar el resumen de sesión
│   └── Clasifica intervenciones como in-game vs meta-rol
│
├── Al finalizar la sesión:
│   ├── Genera resumen final pulido de la sesión
│   ├── Integra el resumen de sesión en el resumen de campaña
│   └── Extrae PNJs nuevos, localizaciones, eventos clave
│
└── Capacidad de preguntar al usuario (via Discord o Web UI)
    └── "No entiendo si Rodrigo habla como su personaje o como jugador.
         ¿Aelar le dijo eso al tabernero o fue Rodrigo preguntando al DM?"
```

### 6.5 Contexto de Campaña (CampaignContext)

```python
@dataclass
class CampaignContext:
    campaign_id: str
    name: str                          # "La Marca del Este"
    game_system: str                   # "Akelarre", "Fading Suns"
    language: str                      # "es", "en"
    description: str                   # Breve descripción del setting

    players: list[PlayerInfo]          # Jugadores y sus personajes
    known_npcs: list[NPCInfo]         # PNJs conocidos
    locations: list[str]               # Localizaciones visitadas
    campaign_summary: str              # Resumen acumulado
    session_history: list[SessionInfo] # Historial de sesiones previas

    # Mapeo Discord User → Personaje
    speaker_map: dict[str, str]        # {"discord_user_123": "Aelar"}
    dm_speaker_id: str                 # ID del master

    custom_instructions: str           # Instrucciones adicionales del usuario
```

### 6.6 System Prompt del Summarizer (esquema)

```
Eres un cronista experto de partidas de rol. Tu trabajo es escribir
un resumen narrativo de lo que ocurre en la sesión.

CONTEXTO DE LA CAMPAÑA:
- Sistema: {game_system}
- Campaña: {name} — {description}
- Resumen hasta ahora: {campaign_summary}

JUGADORES:
- {discord_name} juega como {character_name} ({character_description})
- {dm_name} es el Director de Juego (habla como PNJs y narra)

PNJS CONOCIDOS:
{known_npcs}

INSTRUCCIONES:
1. Escribe en tercera persona, estilo narrativo.
2. Distingue entre lo que dicen los personajes (in-game) y las
   conversaciones de los jugadores (meta-rol). El meta-rol NO va
   en el resumen narrativo, pero puedes anotarlo como [META] si
   es relevante (decisiones de grupo, dudas de reglas, etc.).
3. El DM ({dm_name}) habla como múltiples PNJs. Intenta identificar
   qué PNJ habla basándote en el contexto.
4. Mantén el resumen coherente y fluido. Reescribe secciones
   anteriores si nueva información las clarifica.
5. Si algo no está claro, márcalo con [PREGUNTA: ...].

TRANSCRIPCIÓN RECIENTE:
{recent_transcriptions}

RESUMEN ACTUAL DE LA SESIÓN:
{current_session_summary}

Actualiza el resumen incorporando la nueva transcripción.
```

---

## 7. Módulo 4: Visualización (Web UI)

### 7.1 Responsabilidad

Mostrar el estado del sistema y los resúmenes en tiempo real.

### 7.2 Stack

```
FastAPI (backend)
├── Endpoint REST: /api/sessions, /api/campaigns, /api/status
├── WebSocket: /ws/live → push de actualizaciones en tiempo real
└── Sirve archivos estáticos (HTML/JS/CSS)

Frontend (vanilla HTML + JS + algo de Tailwind)
├── Panel de estado: componentes activos, errores, latencia
├── Transcripción en vivo: scroll con quién dice qué
├── Resumen en vivo: el resumen que se va actualizando
├── Selector de campaña/sesión
├── Historial de sesiones con resúmenes finales
└── Panel de preguntas pendientes del Summarizer
```

### 7.3 También en Discord

Además de la web, el bot puede postear actualizaciones:
- Canal de texto dedicado para resúmenes live (actualiza un mensaje embed)
- Comando `/scribe summary` para ver el resumen actual
- Comando `/scribe ask` para responder preguntas del Summarizer

---

## 8. Almacenamiento (SQLite)

### 8.1 Esquema

```sql
-- Campañas
CREATE TABLE campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    game_system TEXT,
    language TEXT DEFAULT 'es',
    description TEXT,
    campaign_summary TEXT DEFAULT '',
    speaker_map JSON,          -- {"discord_id": "character_name"}
    dm_speaker_id TEXT,
    custom_instructions TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Jugadores/Personajes
CREATE TABLE players (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    discord_id TEXT,
    discord_name TEXT,
    character_name TEXT,
    character_description TEXT
);

-- PNJs conocidos
CREATE TABLE npcs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    description TEXT,
    first_seen_session TEXT
);

-- Sesiones
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    session_summary TEXT,
    status TEXT DEFAULT 'active'  -- active, paused, completed
);

-- Transcripciones (raw)
CREATE TABLE transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    speaker_id TEXT,
    speaker_name TEXT,
    text TEXT,
    timestamp REAL,
    confidence REAL,
    is_ingame BOOLEAN           -- clasificado por el summarizer
);

-- Preguntas del summarizer al usuario
CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    question TEXT,
    answer TEXT,
    answered_at TIMESTAMP,
    status TEXT DEFAULT 'pending'  -- pending, answered, dismissed
);
```

---

## 9. Estructura del Proyecto

```
rpg-scribe/
├── pyproject.toml                 # Dependencias y metadata
├── config/
│   ├── default.toml               # Configuración por defecto
│   └── campaigns/
│       └── example-campaign.toml  # Config de campaña ejemplo
│
├── src/
│   └── rpg_scribe/
│       ├── __init__.py
│       ├── main.py                # Entry point
│       ├── config.py              # Carga y validación de config
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── events.py          # Dataclasses de eventos
│       │   ├── event_bus.py       # Event bus async
│       │   ├── models.py          # Modelos de dominio
│       │   └── database.py        # SQLite wrapper
│       │
│       ├── listeners/
│       │   ├── __init__.py
│       │   ├── base.py            # BaseListener ABC
│       │   ├── discord_listener.py
│       │   └── file_listener.py   # Para testing/re-procesado
│       │
│       ├── transcribers/
│       │   ├── __init__.py
│       │   ├── base.py            # BaseTranscriber ABC
│       │   ├── openai_transcriber.py
│       │   └── faster_whisper_transcriber.py
│       │
│       ├── summarizers/
│       │   ├── __init__.py
│       │   ├── base.py            # BaseSummarizer ABC
│       │   └── claude_summarizer.py
│       │
│       ├── web/
│       │   ├── __init__.py
│       │   ├── app.py             # FastAPI app
│       │   ├── routes.py          # Endpoints REST
│       │   ├── websocket.py       # WebSocket handlers
│       │   └── static/
│       │       ├── index.html
│       │       ├── app.js
│       │       └── style.css
│       │
│       └── discord_bot/
│           ├── __init__.py
│           ├── bot.py             # Discord bot setup
│           └── commands.py        # Slash commands
│
├── tests/
│   ├── test_event_bus.py
│   ├── test_transcriber.py
│   ├── test_summarizer.py
│   └── fixtures/
│       └── sample_audio/          # Audio de test
│
└── scripts/
    ├── setup_discord_bot.py       # Helper para crear bot en Discord
    └── import_campaign.py         # Importar config de campaña
```

---

## 10. Configuración de Campaña (ejemplo TOML)

```toml
[campaign]
id = "akelarre-2025"
name = "El Aquelarre de las Sombras"
game_system = "Akelarre"
language = "es"
description = """
Castilla, 1342. Un grupo de viajeros se ve envuelto en extraños
sucesos en la villa de Tordesillas. Algo oscuro acecha en la noche.
"""

[campaign.dm]
discord_id = "123456789"
discord_name = "Carlos"

[[campaign.players]]
discord_id = "234567890"
discord_name = "Ana"
character_name = "María de Tordesillas"
character_description = "Curandera castellana, 28 años. Conoce hierbas y remedios."

[[campaign.players]]
discord_id = "345678901"
discord_name = "Pedro"
character_name = "Fray Bernardo"
character_description = "Fraile franciscano. Erudito pero con un pasado turbio."

[[campaign.players]]
discord_id = "456789012"
discord_name = "Laura"
character_name = "Urraca"
character_description = "Juglaresa. Ágil de lengua y de pies."

[[campaign.players]]
discord_id = "567890123"
discord_name = "Miguel"
character_name = "Gonzalo el Tuerto"
character_description = "Soldado veterano. Le falta un ojo pero no valor."

[[campaign.npcs]]
name = "Don Alfonso"
description = "Alcalde de Tordesillas. Nervioso y con secretos."

[[campaign.npcs]]
name = "La Vieja Inés"
description = "Anciana misteriosa que vive en las afueras."

[campaign.custom_instructions]
text = """
En Akelarre, la magia es oscura y peligrosa. Los personajes no
deberían saber de su existencia al principio. Marca como importante
cualquier momento donde los personajes descubran algo sobrenatural.
"""
```

---

## 11. Flujo de Datos Completo

```
1. Jugadores hablan en Discord
        │
        ▼
2. DiscordListener recibe audio PCM por usuario
   (cada usuario = stream separado via SSRC)
        │
        ▼
3. VAD detecta actividad → se acumula en buffer de ~10s
        │
        ▼
4. AudioChunkEvent → Event Bus
        │
        ▼
5. OpenAITranscriber recibe chunk
   → Envía a OpenAI API con contexto (nombres, idioma)
   → Recibe texto transcrito
        │
        ▼
6. TranscriptionEvent → Event Bus
        │
        ├──▶ Se guarda en SQLite (raw)
        ├──▶ Se envía al Web UI via WebSocket (live)
        │
        ▼
7. ClaudeSummarizer acumula transcripciones
   → Cada ~2 min o ~20 intervenciones:
     → Envía a Claude con contexto completo
     → Recibe resumen actualizado
     → Clasifica in-game vs meta-rol
        │
        ▼
8. SummaryUpdateEvent → Event Bus
        │
        ├──▶ Se actualiza en SQLite
        ├──▶ Se envía al Web UI via WebSocket
        └──▶ Se actualiza embed en Discord

9. Al finalizar sesión (/scribe stop):
   → Resumen final pulido
   → Integración en resumen de campaña
   → Extracción de nuevos PNJs/localizaciones
```

---

## 12. Plan de Implementación por Fases

### Fase 0: Fundamentos (Core)
**Estimación: 1-2 sesiones con Claude Code**

Qué construir:
- [ ] Estructura del proyecto (`pyproject.toml`, carpetas)
- [ ] Event bus async (`core/event_bus.py`)
- [ ] Eventos tipados (`core/events.py`)
- [ ] Modelos de dominio (`core/models.py`)
- [ ] Base de datos SQLite (`core/database.py`)
- [ ] Sistema de configuración TOML (`config.py`)
- [ ] Tests del event bus

Verificación: Los tests pasan. Se puede crear una campaña, publicar eventos y recibirlos.

---

### Fase 1: Listener de Discord
**Estimación: 2-3 sesiones con Claude Code**

Qué construir:
- [ ] Bot de Discord básico con `discord.py`
- [ ] Integración `discord-ext-voice-recv` para recibir audio por usuario
- [ ] VAD simple (webrtcvad) para detectar habla vs silencio
- [ ] Buffer y chunking inteligente (~10s, corte en silencios)
- [ ] Emisión de `AudioChunkEvent` al bus
- [ ] Comandos slash: `/scribe start`, `/scribe stop`, `/scribe status`
- [ ] FileListener para testing (lee .wav/.mp3)

Verificación: El bot se conecta al canal de voz, graba audio, se pueden guardar chunks como WAV y verificar que se separan correctamente por usuario.

---

### Fase 2: Transcriptor
**Estimación: 1-2 sesiones con Claude Code**

Qué construir:
- [ ] OpenAITranscriber: envía chunks a la API, gestiona cola async
- [ ] Prompt contextual con nombres de personajes
- [ ] Retry y error handling
- [ ] Emisión de `TranscriptionEvent`
- [ ] Guardado de transcripciones en SQLite
- [ ] FasterWhisperTranscriber (fallback local)

Verificación: Se puede alimentar con audio grabado de la Fase 1, y genera transcripciones correctas con speaker attribution.

---

### Fase 3: Resumidor
**Estimación: 2-3 sesiones con Claude Code**

Qué construir:
- [ ] ClaudeSummarizer con lógica de acumulación y actualización
- [ ] System prompt completo con contexto de campaña
- [ ] Clasificación in-game vs meta-rol
- [ ] Doble resumen: sesión + campaña
- [ ] Lógica de finalización de sesión
- [ ] Sistema de preguntas al usuario
- [ ] Integración con CampaignContext desde SQLite

Verificación: Se alimenta con transcripciones de ejemplo y genera resúmenes coherentes. Se puede probar manualmente inyectando transcripciones falsas.

---

### Fase 4: Visualización Web
**Estimación: 2 sesiones con Claude Code**

Qué construir:
- [ ] FastAPI app con WebSocket
- [ ] Dashboard: estado de componentes, logs
- [ ] Vista de transcripción en vivo
- [ ] Vista de resumen en vivo (actualización incremental)
- [ ] Selector de campaña y sesión
- [ ] Historial de sesiones con resúmenes
- [ ] Panel de preguntas pendientes
- [ ] Respuestas a preguntas del summarizer desde la web

Verificación: Se puede abrir el navegador, ver el estado del sistema, y ver transcripciones y resúmenes actualizándose.

---

### Fase 5: Integración y Pulido
**Estimación: 2 sesiones con Claude Code**

Qué construir:
- [ ] Integración completa de todos los módulos
- [ ] `main.py` que orquesta todo
- [ ] Manejo de errores robusto (reconexión Discord, API failures)
- [ ] Logging estructurado
- [ ] Documentación de usuario (README)
- [ ] Script de setup de bot de Discord
- [ ] Publicación de resúmenes en Discord (embeds en canal de texto)
- [ ] Prueba end-to-end con sesión real

Verificación: Se ejecuta `python -m rpg_scribe` y funciona todo junto.

---

## 13. Dependencias Python

```toml
[project]
name = "rpg-scribe"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Core
    "pydantic>=2.0",
    "tomli>=2.0",           # Para leer TOML (Python <3.11 compat)

    # Discord
    "discord.py[voice]>=2.3",
    "discord-ext-voice-recv>=0.5",

    # Audio processing
    "webrtcvad>=2.0.10",    # Voice Activity Detection
    "numpy>=1.24",
    "soundfile>=0.12",      # Lectura/escritura de audio

    # Transcription
    "openai>=1.0",          # OpenAI API
    "httpx>=0.25",          # HTTP async client

    # Summarization
    "anthropic>=0.30",      # Anthropic API

    # Web UI
    "fastapi>=0.100",
    "uvicorn[standard]>=0.23",
    "websockets>=12.0",

    # Database
    "aiosqlite>=0.19",      # SQLite async

    # Utils
    "structlog>=23.0",      # Logging estructurado
    "pydub>=0.25",          # Manipulación de audio
]

[project.optional-dependencies]
local = [
    "faster-whisper>=1.0",  # Transcripción local
    "torch>=2.0",
    "ctranslate2>=4.0",
]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "ruff>=0.1",
]
```

---

## 14. Variables de Entorno

```bash
# Discord
DISCORD_BOT_TOKEN=your_discord_bot_token

# OpenAI (transcripción)
OPENAI_API_KEY=your_openai_api_key

# Anthropic (resumen)
ANTHROPIC_API_KEY=your_anthropic_api_key

# Opcional: Hugging Face (para pyannote, futuro)
HF_TOKEN=your_huggingface_token
```

---

## 15. Instrucciones para Claude Code

Cuando uses este documento con Claude Code, sigue este enfoque:

1. **Fase por fase:** Implementa una fase completa antes de pasar a la siguiente.
2. **Tests primero:** Cada módulo debe tener tests que verifiquen el contrato.
3. **Interfaces antes que implementación:** Crea las clases base/ABC antes de las implementaciones concretas.
4. **Commits atómicos:** Un commit por funcionalidad coherente.
5. **Referencia este documento:** Cada vez que empieces una fase, referencia la sección correspondiente.

### Prompt sugerido para cada fase:

```
Lee el documento de arquitectura rpg-scribe-architecture.md.
Implementa la Fase [N]: [nombre].
Sigue las interfaces definidas en el documento.
Crea tests para verificar el comportamiento.
Usa el patrón de event bus async definido en la sección 3.
```

---

## 16. Notas y Decisiones Pendientes

1. **¿Pycord vs discord.py?** — Pycord tiene recording nativo más sencillo, pero discord.py + ext es más maduro. Investigar más durante Fase 1.

2. **Coste estimado por sesión (4-6h):**
   - Transcripción OpenAI: ~$5-15 (depende de modelo y volumen)
   - Resumen Claude Sonnet: ~$2-5 (depende de frecuencia de actualización)
   - Total estimado: ~$10-20/sesión

3. **Voice profiles para mejor diarización futura:** Se puede almacenar embeddings de voz por jugador para mejorar la diarización en fuentes mezcladas.

4. **Rate limits:** Con 5 usuarios hablando, podríamos generar ~30 chunks/minuto. La API de OpenAI tiene rate limits generosos, pero hay que monitorizarlo.

5. **Privacidad:** El audio se procesa y descarta. Solo se almacenan las transcripciones en texto. Esto es importante comunicarlo a los jugadores.
