# Panel de control de voz del bot — Diseño

**Fecha:** 2026-07-03
**Estado:** Aprobado (pendiente de plan de implementación)

## Resumen

Cuando un bot activado por voz (hoy el bot de reglas) responde, el
`TriggerWatcher` sintetiza el audio y lo reproduce en el canal de voz de
Discord vía `DiscordTTSPlayer.start_queue()`. Hoy el Web UI no se entera de
que el bot está hablando, así que no hay forma de controlar esa reproducción
desde el navegador.

Este diseño añade un **panel de control en vivo** dentro de la sección
**System Status** del Web UI que **aparece cada vez que el bot habla** y
permite controlar el audio ya en reproducción: **Pausar/Reanudar, Retroceder
frase, Avanzar frase, Repetir (desde el inicio) y Descartar**.

## Objetivos

- El panel aparece automáticamente en el Web UI cuando un bot reproduce una
  respuesta hablada.
- Muestra el contexto: keyword del bot, quién preguntó, la pregunta y la
  respuesta escrita (markdown con la cita).
- Controles de **transporte sobre el audio ya sintetizado**: Pausar,
  Reanudar, Retroceder frase, Avanzar frase, Repetir, Descartar.
- Indicador de progreso "frase N/total" y estado (sonando / pausado).

## No-objetivos (fuera de alcance)

- **Re-generar** (volver a preguntar a Claude): explícitamente descartado.
  El panel opera solo sobre el audio ya generado; ninguna llamada nueva al
  retriever/answerer.
- **Gate de aprobación** antes de reproducir: el bot sigue reproduciendo
  automáticamente. El panel controla el audio en vivo, no lo retiene.
- Control del **narrador web** (que ya tiene su propio panel de controles);
  el disparo es exclusivo de respuestas de bot por voz.
- Resaltar la frase concreta que suena dentro del texto (posible mejora
  futura; requeriría transportar la lista de chunks de texto).

## Arquitectura

Enfoque elegido: **evento por WebSocket para el disparo + polling del endpoint
de estado existente para el transporte en vivo.** Reutiliza el 100% del
backend de transporte, que ya existe.

```
Bot responde
  → TriggerWatcher._finalize:
        synthesize_to_wav_paths(...)  →  paths (una WAV por frase)
        player.start_queue(paths)     →  empieza a sonar en Discord
        publish BotSpeechEvent(total_chunks=len(paths), ...)   ← NUEVO
  → WebSocketBridge reenvía  {type:"bot_speech", data:{...}}   ← NUEVO
  → Web UI (bot-panel.js): muestra el panel en #status-panel    ← NUEVO
        · pinta pregunta + respuesta + cita
        · hace polling de GET /api/tts/discord/status (~500 ms)
        · botones → POST /api/tts/discord/{pause,resume,stop,play-at}  (EXISTENTES)
```

### Lo que YA existe (se reutiliza sin cambios)

- `DiscordTTSPlayer` con `pause()`, `resume()`, `play_at(index)`, `stop()` y
  `status()` (`total`, `index`, `playing`, `paused`, `active`).
  Archivo: `src/rpg_scribe/discord_bot/tts_player.py`.
- Endpoints REST de transporte, ya cableados al player:
  - `POST /api/tts/discord/pause`
  - `POST /api/tts/discord/resume`
  - `POST /api/tts/discord/stop`
  - `POST /api/tts/discord/play-at`  (body `{"index": int}`)
  - `GET  /api/tts/discord/status`  (devuelve `{"connected": false}` si la
    voz no está conectada; si no, `{"connected": true, ...status()}`)
  Archivo: `src/rpg_scribe/web/routers/tts.py`.
- Infra de WebSocket: `ConnectionManager` + `WebSocketBridge`
  (`src/rpg_scribe/web/websocket.py`) y el registro de handlers del frontend
  `registerHandler(type, fn)` (`web/static/js/websocket.js`).

## Cambios en el backend

### 1. Evento `BotSpeechEvent` (nuevo)

En `src/rpg_scribe/core/events.py`, dataclass `frozen=True` (como el resto de
eventos):

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | `str` | Sesión activa |
| `bot_keyword` | `str` | Keyword del bot que respondió (p. ej. "bot reglas") |
| `speaker_name` | `str` | Quién invocó al bot |
| `question` | `str` | El comando/pregunta capturado |
| `answer_md` | `str` | La respuesta escrita (`BotResponse.written`, con la cita) |
| `total_chunks` | `int` | Nº de frases/WAVs en cola (= `len(paths)`) |
| `timestamp` | `float` | `time.time()` |

Nota: NO se transportan los textos por-frase (decisión de no resaltar la frase
que suena). `total_chunks` basta para el progreso "N/total".

### 2. Publicación desde `TriggerWatcher._finalize`

En `src/rpg_scribe/bots/watcher.py`, tras el `await self._player.start_queue(...)`
exitoso (actualmente ~línea 245), publicar `BotSpeechEvent` con
`total_chunks=len(paths)`.

- Se publica **solo si la reproducción arranca** (voz conectada y
  `start_queue` sin excepción). Si la voz no está conectada, hoy ya se hace
  `return` sin reproducir → tampoco se publica evento (el panel no aparece).
- Si `response.written` es vacío, `answer_md` va como `spoken` en su defecto
  (el panel siempre tiene algo que mostrar).

### 3. `WebSocketBridge` reenvía el evento

En `src/rpg_scribe/web/websocket.py`:
- Suscribirse a `BotSpeechEvent` en `start()` / desuscribir en `stop()`.
- Handler `_on_bot_speech` que hace
  `broadcast({"type": "bot_speech", "data": asdict(event)})`.

## Cambios en el frontend

Ubicación: **dentro de la sección System Status** (`#status-panel` en
`web/static/index.html:432`, bajo `<h2>System Status</h2>`), debajo de la
rejilla de `#component-status`.

### 4. Módulo nuevo `web/static/js/bot-panel.js`

- Exporta `initBotPanel()` y el handler del evento.
- Se registra en `main.js`: `registerHandler("bot_speech", onBotSpeech)`.
- Al recibir `bot_speech`:
  - Rellena el contenedor del panel: cabecera `[bot_keyword] · speaker_name`,
    la `question`, y el texto de `answer_md`. **Nota:** el frontend no tiene
    librería de markdown (usa plantillas con `innerHTML`), así que `answer_md`
    se muestra como texto escapado con saltos de línea preservados (`white-space:
    pre-wrap`), no como HTML renderizado. Enriquecerlo con markdown queda como
    mejora futura.
  - Muestra el panel y arranca un *poller* de `GET /api/tts/discord/status`
    cada ~500 ms mientras `active`/`playing` sea verdadero.
- Barra de transporte (botones → endpoints existentes):

  | Botón | Acción |
  |---|---|
  | ⏸ Pausar | `POST /api/tts/discord/pause` |
  | ▶ Reanudar | `POST /api/tts/discord/resume` |
  | ⏮ Frase anterior | `POST /api/tts/discord/play-at {index: status.index-1}` |
  | ⏭ Frase siguiente | `POST /api/tts/discord/play-at {index: status.index+1}` |
  | 🔁 Repetir | `POST /api/tts/discord/play-at {index: 0}` |
  | ⏹ Descartar | `POST /api/tts/discord/stop` |

- El botón Pausar/Reanudar alterna según `status.paused`.
- ⏮ se deshabilita en `index<=0`; ⏭ se deshabilita en `index>=total-1`.
- Progreso: "frase `{index+1}`/`{total}`" + un indicador sonando/pausado.
- **Ciclo de vida del panel:** aparece con `bot_speech`; persiste tras
  terminar la reproducción (para poder Repetir); se reemplaza con el siguiente
  `bot_speech`; botón de cerrar (✕) para ocultarlo manualmente.
- Si `/status` devuelve `{"connected": false}` (voz caída), deshabilita el
  transporte y muestra "voz desconectada".

### 5. HTML / CSS

- Contenedor del panel dentro de `#status-panel` en `index.html` (oculto por
  defecto, visible al recibir `bot_speech`).
- Estilos en `web/static/css/features/bot-panel.css`, enlazado como el resto
  de CSS de `features/`.

## Flujo de datos (resumen)

1. Usuario dice "bot reglas, ¿cómo funciona el netrunning?".
2. `TriggerWatcher` → retriever/answerer → `player.start_queue(paths)` → suena.
3. `TriggerWatcher` publica `BotSpeechEvent(total_chunks=len(paths), …)`.
4. `WebSocketBridge` → `{type:"bot_speech"}` a los clientes.
5. `bot-panel.js` muestra el panel y hace polling de `/status`.
6. El GM pulsa Pausar/Avanzar/Repetir/Descartar → endpoints existentes →
   `DiscordTTSPlayer`.

## Casos límite

- **Voz no conectada al hablar:** hoy `_finalize` hace `return` sin
  reproducir; no se publica `BotSpeechEvent` → el panel no aparece. Correcto.
- **Respuestas de bot en ráfaga:** `start_queue` reemplaza la cola; el nuevo
  `bot_speech` reemplaza el contenido del panel y reinicia el seguimiento de
  índice.
- **`play-at` fuera de rango:** el frontend deshabilita ⏮/⏭ en los límites; el
  backend además responde 400 (guardas ya existentes).
- **Voz cae a mitad:** `/status` pasa a `{"connected": false}`; el panel
  deshabilita el transporte.
- **Modo no-live / histórico:** `websocket.js` ya ignora mensajes live fuera
  de modo `live`; el panel solo opera en modo live. Aceptado.
- **Narrador web usando el mismo player:** el panel solo se *dispara* con
  `bot_speech`, pero `/status` refleja la reproducción activa sea cual sea
  (solo hay una a la vez). Aceptado: el transporte actúa sobre lo que suene.

## Testing

- **Backend (pytest):**
  - `TriggerWatcher._finalize` publica `BotSpeechEvent` con
    `total_chunks == len(paths)` tras un `start_queue` exitoso; y **no** lo
    publica si la voz no está conectada. Patrón: `tests/test_trigger_watcher.py`.
  - `WebSocketBridge` reenvía `BotSpeechEvent` como `{type:"bot_speech"}`.
    Patrón: tests existentes del bridge/websocket.
  - Endpoints de transporte: cobertura ya existente (sin cambios).
- **Frontend:** verificación manual (no hay harness JS en el proyecto):
  disparar una respuesta de bot y comprobar que el panel aparece dentro de
  System Status y que cada botón mueve el estado esperado.

## Archivos afectados

- `src/rpg_scribe/core/events.py` — nuevo `BotSpeechEvent`.
- `src/rpg_scribe/bots/watcher.py` — publicar el evento tras `start_queue`.
- `src/rpg_scribe/web/websocket.py` — suscribir + reenviar `bot_speech`.
- `web/static/index.html` — contenedor del panel en `#status-panel`.
- `web/static/js/bot-panel.js` — módulo nuevo del panel.
- `web/static/js/main.js` — `registerHandler("bot_speech", …)`.
- `web/static/css/features/bot-panel.css` — estilos + enlace del CSS.
- Tests: `tests/test_trigger_watcher.py` (y test del bridge).

## Documentación a actualizar

- `docs/rules-bot.md` — mencionar el panel de control de voz en el Web UI.
