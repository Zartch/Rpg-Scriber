# TTS Narration — Design Spec

**Fecha:** 2026-03-27
**Estado:** Aprobado

## Resumen

Agregar narración por voz (Text-to-Speech) a los resúmenes del Web UI. El usuario pulsa "Narrar" junto a cualquier resumen visible (narrative, chronology, campaign summary) y el audio se reproduce en el navegador con streaming por párrafos.

## Objetivos

- Reproducir cualquier resumen como audio narrado desde el Web UI
- Streaming por párrafos: empieza a sonar al llegar el primer párrafo
- Caché en disco: re-narrar no vuelve a llamar al TTS
- Arquitectura pluggable: múltiples providers TTS (OpenAI primero, luego Edge, ElevenLabs, local)
- Extensible a futuros tipos de resumen sin cambios en la infra

## No-objetivos (v1)

- Narración desde Discord (slash commands) — futuro
- Streaming real a nivel de bytes de audio
- Selección de voz desde el Web UI (se usa la configurada en TOML)
- TTL o limpieza automática del caché

---

## Arquitectura

### Flujo general

```
Botón "Narrar" (Web UI)
  → POST /api/tts/narrate { text, voice?, provider? }
  → Backend split texto en párrafos
  → Para cada párrafo (en orden):
      ¿Caché hit? → Sí → yield URL inmediato
                  → No → TTS provider → guardar en caché → yield URL
  → StreamingResponse NDJSON: cada línea = { index, total, audio_url }
  → Frontend reproduce primer chunk al llegar, encola el resto
```

### Componentes nuevos

```
src/rpg_scribe/tts/
├── __init__.py
├── base.py              # ABC BaseTTSProvider
├── openai_provider.py   # OpenAI TTS (tts-1 / tts-1-hd)
└── cache.py             # Caché en disco por hash
```

Modificaciones en archivos existentes:
- `config.py` — nuevo `TTSConfig` dataclass
- `config/default.toml` — sección `[tts]`
- `web/routes.py` — endpoints `/api/tts/narrate` y `/api/tts/cache/{hash}.mp3`
- `web/app.py` — montar directorio estático de caché TTS, instanciar provider
- `web/static/app.js` — botón "Narrar", reproductor con cola
- `web/static/style.css` — estilos del botón y estado de narración
- `main.py` — instanciar TTS provider si está habilitado

---

## Backend

### BaseTTSProvider (ABC)

```python
from abc import ABC, abstractmethod

class BaseTTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> bytes:
        """Genera audio mp3 a partir de un fragmento de texto."""
        ...

    @abstractmethod
    def supported_voices(self) -> list[str]:
        """Lista de voces disponibles en este provider."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador del provider (e.g., 'openai', 'edge', 'elevenlabs')."""
        ...
```

### OpenAITTSProvider

- Usa `openai.AsyncOpenAI().audio.speech.create()`
- Modelo configurable: `tts-1` (rápido, por defecto) o `tts-1-hd` (calidad)
- Voces: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`
- Formato de salida: `mp3`
- Requiere `OPENAI_API_KEY` (ya presente en el proyecto)

### TTSCache

- Directorio: `data/tts_cache/` (configurable)
- Clave: `sha256(text + provider_name + voice + model)` → `{hash}.mp3`
- Métodos:
  - `get(key: str) -> bytes | None` — lee archivo si existe
  - `put(key: str, audio: bytes) -> Path` — escribe archivo, retorna path
  - `url_for(key: str) -> str` — retorna `/api/tts/cache/{hash}.mp3`
  - `has(key: str) -> bool` — comprueba existencia
- Sin TTL ni limpieza automática en v1

### Configuración

**`TTSConfig` dataclass:**

```python
@dataclass
class TTSConfig:
    enabled: bool = False
    provider: str = "openai"
    voice: str = "nova"
    model: str = "tts-1"
    cache_dir: str = "data/tts_cache"
```

**`default.toml`:**

```toml
[tts]
enabled = false
provider = "openai"
voice = "nova"
model = "tts-1"
cache_dir = "data/tts_cache"
```

---

## API Endpoints

### POST /api/tts/narrate

**Request:**
```json
{
  "text": "El resumen completo a narrar...",
  "voice": "nova",
  "provider": "openai"
}
```

`voice` y `provider` son opcionales; usan los valores de config si se omiten.

**Response:** `StreamingResponse` con `content-type: application/x-ndjson`

Cada línea es un JSON independiente:
```json
{"index": 0, "total": 5, "audio_url": "/api/tts/cache/a1b2c3.mp3", "cached": true}
{"index": 1, "total": 5, "audio_url": "/api/tts/cache/d4e5f6.mp3", "cached": false}
```

**Lógica:**
1. Validar que TTS está habilitado (HTTP 503 si no)
2. Split texto por doble salto de línea (`\n\n`), filtrar párrafos vacíos
3. Calcular `total` = número de párrafos
4. Para cada párrafo en orden secuencial:
   a. Generar cache key: `sha256(paragraph + provider + voice + model)`
   b. Si caché hit: yield `{index, total, audio_url, cached: true}`
   c. Si caché miss: `await provider.synthesize(paragraph, voice)` → guardar en caché → yield `{index, total, audio_url, cached: false}`
5. En caso de error en un párrafo: yield `{index, total, error: "mensaje"}` y continuar con el siguiente

### GET /api/tts/cache/{hash}.mp3

Sirve archivos estáticos desde `data/tts_cache/`. Se monta como `StaticFiles` en FastAPI.

### GET /api/tts/voices

Retorna voces disponibles del provider activo:
```json
{
  "provider": "openai",
  "voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
  "current": "nova"
}
```

---

## Frontend

### Botón "Narrar"

- Aparece junto a cada resumen visible en el Web UI
- Ubicaciones: panel de resumen de sesión (narrative + chronology), resumen de campaña
- Icono de altavoz + texto "Narrar"
- Se transforma en "Detener" con icono diferente mientras narra

### Reproductor con cola

**Al pulsar "Narrar":**
1. `fetch('/api/tts/narrate', { method: 'POST', body: { text } })` con streaming
2. Leer response body como `ReadableStream`, parsear línea a línea (NDJSON)
3. Al recibir primer chunk: crear `<audio>` oculto, asignar `src = audio_url`, reproducir
4. Siguientes chunks: encolar URLs en array
5. Evento `ended` del `<audio>` → sacar siguiente URL de la cola → reproducir
6. Al terminar toda la cola: restaurar botón a "Narrar"

**Al pulsar "Detener":**
1. Pausar `<audio>` actual
2. Vaciar cola
3. Restaurar botón a "Narrar"

**Estado visual:**
- Botón usa `withLoading()` mientras espera el primer chunk
- Texto del botón durante narración: "Narrando (3/7)" con progreso
- Al terminar: feedback temporal "Narración completada" (2s)

### Reutilización del patrón de loading

Usar `withLoading(btn, asyncFn, { loadingText: 'Generando...' })` para el estado inicial. Una vez llega el primer chunk, el estado pasa a "Narrando" gestionado manualmente con el contador de progreso.

---

## Manejo de errores

- **TTS deshabilitado:** Botón no aparece si `/api/tts/voices` retorna 503
- **Error en párrafo individual:** Se salta, reproduce los demás. Log en consola del navegador
- **Error de red:** Se muestra notificación y se restaura el botón
- **Provider sin API key:** HTTP 503 con mensaje descriptivo al intentar narrar

---

## Testing

- **Unit tests:**
  - `test_tts_cache.py` — get/put/has/url_for, hash determinístico
  - `test_openai_provider.py` — mock de OpenAI API, verifica formato mp3
  - `test_tts_config.py` — carga desde TOML, valores por defecto
- **Integration tests:**
  - `test_tts_routes.py` — endpoint narrate con provider mockeado, verifica NDJSON streaming, verifica caché hit/miss
- **Manual testing:**
  - Verificar reproducción en navegador (Chrome, Firefox)
  - Verificar que re-narrar usa caché (no llama al TTS)
  - Verificar botón Detener interrumpe correctamente

---

## Extensibilidad futura

- **Nuevos providers:** Crear clase que extienda `BaseTTSProvider`, registrar en factory
- **Selección de voz en UI:** Endpoint `/api/tts/voices` ya existe, solo falta dropdown en frontend
- **Narración desde Discord:** Reutilizar provider + caché, añadir `voice_client.play()` con FFmpegPCMAudio
- **Streaming real:** Cambiar `synthesize()` para devolver `AsyncIterator[bytes]` en providers que lo soporten
- **Limpieza de caché:** Añadir TTL o limpieza por tamaño total
- **Nuevos tipos de resumen:** El botón funciona con cualquier bloque de texto, sin cambios en backend
