# Panel de control de voz del bot — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir al Web UI un panel dentro de "System Status" que aparece cuando un bot de voz reproduce su respuesta y permite controlar el audio (pausar/reanudar, frase anterior/siguiente, repetir, descartar).

**Architecture:** El `TriggerWatcher` publica un `BotSpeechEvent` al arrancar la reproducción; el `WebSocketBridge` lo reenvía al Web UI como `{type:"bot_speech"}`. Un módulo JS nuevo (`bot-panel.js`) muestra el panel y controla el audio vía los endpoints REST de transporte **ya existentes** (`/api/tts/discord/{pause,resume,stop,play-at,status}`), sincronizándose por polling de `/status`. No se crea ningún endpoint nuevo.

**Tech Stack:** Python 3.10 async, dataclasses frozen, pytest + pytest-asyncio, FastAPI WebSocket, JS ES-modules vanilla (sin framework), ruff.

**Spec:** `docs/superpowers/specs/2026-07-03-bot-speech-control-panel-design.md`

**Política de commits (IMPORTANTE):** El `CLAUDE.md` del proyecto prohíbe hacer commits salvo que el usuario lo pida explícitamente ("El usuario probará antes de hacer commit"). Por eso **este plan NO incluye pasos de `git commit`**. Cada tarea termina en un checkpoint de verificación (tests + ruff); el usuario decide cuándo commitear.

**Estructura de archivos:**
- `src/rpg_scribe/core/events.py` — nuevo evento `BotSpeechEvent`.
- `src/rpg_scribe/bots/watcher.py` — publica el evento tras `start_queue`.
- `src/rpg_scribe/web/websocket.py` — suscribe y reenvía como `bot_speech`.
- `src/rpg_scribe/web/static/js/bot-panel.js` — módulo del panel (nuevo).
- `src/rpg_scribe/web/static/js/main.js` — registra el handler e inicializa.
- `src/rpg_scribe/web/static/index.html` — contenedor del panel + link CSS.
- `src/rpg_scribe/web/static/css/features/bot-panel.css` — estilos (nuevo).
- Tests: `tests/test_trigger_watcher.py`, `tests/test_websocket_bridge.py` (nuevo).

---

## Task 1: Backend — publicar `BotSpeechEvent` desde el watcher

**Files:**
- Modify: `src/rpg_scribe/core/events.py` (añadir evento al final, tras `BotTextResponseEvent`)
- Modify: `src/rpg_scribe/bots/watcher.py` (import + publicación en `_finalize`)
- Test: `tests/test_trigger_watcher.py` (nueva clase de test al final)

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_trigger_watcher.py`:

```python
class TestBotSpeechEventPublished:
    @pytest.mark.asyncio
    async def test_event_published_when_playback_starts(self, tmp_path: Path) -> None:
        from rpg_scribe.core.events import BotSpeechEvent

        bot = _BotForTesting()  # keyword "echo", reply "ok"
        player = _mk_player()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)

        collected: list[BotSpeechEvent] = []

        async def _collect(ev: BotSpeechEvent) -> None:
            collected.append(ev)

        watcher._bus.subscribe(BotSpeechEvent, _collect)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola mundo"))
        await asyncio.sleep(0.2)

        assert len(collected) == 1
        ev = collected[0]
        assert ev.bot_keyword == "echo"
        assert ev.speaker_name == "Alice"
        assert ev.question == "hola mundo"
        # str reply → written is None, so answer_md falls back to spoken ("ok")
        assert ev.answer_md == "ok"
        # total_chunks matches the number of WAVs queued on the player
        queued = player.start_queue.await_args.args[0]
        assert ev.total_chunks == len(queued)
        assert ev.total_chunks >= 1

    @pytest.mark.asyncio
    async def test_no_event_when_voice_disconnected(self, tmp_path: Path) -> None:
        from rpg_scribe.core.events import BotSpeechEvent

        bot = _BotForTesting()
        player = MagicMock()
        player.get_voice_client.return_value = None  # not connected
        player.start_queue = AsyncMock()
        watcher = _mk_watcher([bot], tmp_path=tmp_path, player=player)

        collected: list = []

        async def _collect(ev) -> None:
            collected.append(ev)

        watcher._bus.subscribe(BotSpeechEvent, _collect)
        await watcher.start()

        await watcher._on_transcription(_mk_event("echo, hola"))
        await asyncio.sleep(0.2)

        assert collected == []
        player.start_queue.assert_not_called()
```

- [ ] **Step 2: Ejecutar el test y ver que falla**

Run: `python -m pytest tests/test_trigger_watcher.py::TestBotSpeechEventPublished -v`
Expected: FAIL con `ImportError: cannot import name 'BotSpeechEvent'`.

- [ ] **Step 3: Añadir el evento `BotSpeechEvent`**

En `src/rpg_scribe/core/events.py`, al final del archivo (después de la clase `BotTextResponseEvent`). Los imports `field` y `time` ya existen en el módulo (los usan `EntitiesUpdatedEvent`, `SystemStatusEvent`, etc.).

```python
@dataclass(frozen=True)
class BotSpeechEvent:
    """Emitido por TriggerWatcher cuando un bot EMPIEZA a reproducir su respuesta hablada.

    Lo consume WebSocketBridge para avisar al Web UI, que muestra un panel de
    control de transporte sobre el audio en reproducción. Solo se publica si la
    reproducción arrancó (voz conectada y ``start_queue`` sin error).
    """

    session_id: str
    bot_keyword: str
    speaker_name: str
    question: str
    answer_md: str
    total_chunks: int  # nº de frases/WAVs en la cola (= len(paths))
    timestamp: float = field(default_factory=time.time)
```

- [ ] **Step 4: Publicar el evento en el watcher**

En `src/rpg_scribe/bots/watcher.py`:

4a. Añadir `BotSpeechEvent` al import de eventos (bloque en las líneas ~32-36):

```python
from rpg_scribe.core.events import (
    BotSpeechEvent,
    BotTextResponseEvent,
    TranscriptionEvent,
    TriggerActivatedEvent,
)
```

4b. Reemplazar el bloque final de `_finalize` (el `try/except` de `start_queue`, actualmente ~líneas 244-251):

```python
        try:
            await self._player.start_queue([str(p) for p in paths])
        except Exception as exc:
            logger.exception(
                "Discord playback for bot %s failed: %s",
                cap.bot.keyword,
                exc,
            )
```

por:

```python
        try:
            await self._player.start_queue([str(p) for p in paths])
        except Exception as exc:
            logger.exception(
                "Discord playback for bot %s failed: %s",
                cap.bot.keyword,
                exc,
            )
            return

        await self._bus.publish(
            BotSpeechEvent(
                session_id=ev.session_id,
                bot_keyword=cap.bot.keyword,
                speaker_name=ev.speaker_name,
                question=command,
                answer_md=response.written or spoken,
                total_chunks=len(paths),
            )
        )
```

- [ ] **Step 5: Ejecutar el test y ver que pasa**

Run: `python -m pytest tests/test_trigger_watcher.py -v`
Expected: PASS (incluidos los tests previos de la suite del watcher).

- [ ] **Step 6: Checkpoint de verificación (sin commit)**

Run: `ruff check src/rpg_scribe/core/events.py src/rpg_scribe/bots/watcher.py tests/test_trigger_watcher.py`
Expected: `All checks passed!`
No hacer commit (política del proyecto).

---

## Task 2: Backend — `WebSocketBridge` reenvía `bot_speech`

**Files:**
- Modify: `src/rpg_scribe/web/websocket.py`
- Test: `tests/test_websocket_bridge.py` (nuevo)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_websocket_bridge.py`:

```python
"""Tests for WebSocketBridge broadcasting the bot speech event."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import BotSpeechEvent
from rpg_scribe.web.websocket import ConnectionManager, WebSocketBridge


@pytest.mark.asyncio
async def test_bot_speech_event_is_broadcast() -> None:
    bus = EventBus()
    manager = ConnectionManager()
    manager.broadcast = AsyncMock()  # capture broadcasts without real sockets
    bridge = WebSocketBridge(bus, manager)
    await bridge.start()

    await bus.publish(
        BotSpeechEvent(
            session_id="s-1",
            bot_keyword="bot reglas",
            speaker_name="Alice",
            question="¿cómo funciona el netrunning?",
            answer_md="Respuesta con cita...",
            total_chunks=3,
            timestamp=0.0,
        )
    )

    manager.broadcast.assert_awaited_once()
    msg = manager.broadcast.await_args.args[0]
    assert msg["type"] == "bot_speech"
    assert msg["data"]["bot_keyword"] == "bot reglas"
    assert msg["data"]["total_chunks"] == 3
    assert msg["data"]["question"] == "¿cómo funciona el netrunning?"
```

- [ ] **Step 2: Ejecutar el test y ver que falla**

Run: `python -m pytest tests/test_websocket_bridge.py -v`
Expected: FAIL — `manager.broadcast` no se llama (el bridge no está suscrito a `BotSpeechEvent`), así que `assert_awaited_once()` falla.

- [ ] **Step 3: Suscribir y reenviar en el bridge**

En `src/rpg_scribe/web/websocket.py`:

3a. Añadir `BotSpeechEvent` al import de eventos (bloque en las líneas ~14-20):

```python
from rpg_scribe.core.events import (
    BotSpeechEvent,
    EntitiesUpdatedEvent,
    GenerationProgressEvent,
    SummaryUpdateEvent,
    SystemStatusEvent,
    TranscriptionEvent,
)
```

3b. En `WebSocketBridge.start()`, añadir la suscripción (junto a las demás, antes del `logger.info`):

```python
        self._event_bus.subscribe(BotSpeechEvent, self._on_bot_speech)
```

3c. En `WebSocketBridge.stop()`, añadir la desuscripción (junto a las demás):

```python
        self._event_bus.unsubscribe(BotSpeechEvent, self._on_bot_speech)
```

3d. Añadir el handler (junto a los otros `_on_*`, p. ej. tras `_on_generation_progress`):

```python
    async def _on_bot_speech(self, event: BotSpeechEvent) -> None:
        await self._manager.broadcast({
            "type": "bot_speech",
            "data": asdict(event),
        })
```

- [ ] **Step 4: Ejecutar el test y ver que pasa**

Run: `python -m pytest tests/test_websocket_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint de verificación (sin commit)**

Run: `ruff check src/rpg_scribe/web/websocket.py tests/test_websocket_bridge.py`
Expected: `All checks passed!`
No hacer commit.

---

## Task 3: Frontend — módulo `bot-panel.js`

**Files:**
- Create: `src/rpg_scribe/web/static/js/bot-panel.js`

No hay harness de tests JS en el proyecto, así que este módulo se verifica manualmente en la Task 5. Los botones llaman a los endpoints REST existentes; el patrón de `fetch`/polling replica el de `tts.js` (driver de Discord) pero con estado local propio (no comparte estado con el narrador web).

- [ ] **Step 1: Crear el módulo completo**

Crear `src/rpg_scribe/web/static/js/bot-panel.js` con este contenido exacto:

```javascript
/* RPG Scribe - Panel de control de voz del bot.
 *
 * Aparece dentro de #status-panel cuando un bot reproduce una respuesta
 * (evento WebSocket "bot_speech") y controla el audio en Discord vía los
 * endpoints /api/tts/discord/*. Solo transporte: no re-consulta a Claude.
 */

var els = {};            // nodos DOM cacheados
var pollTimer = null;
var st = { index: 0, total: 0, paused: false, active: false };

function _post(path, body) {
  return fetch("/api/tts/discord/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
    .then(function (s) { _applyStatus(s); })
    .catch(function (err) { console.error("bot-panel control failed:", err); });
}

function _applyStatus(s) {
  if (!s) return;
  if (typeof s.index === "number") st.index = s.index;
  if (typeof s.total === "number") st.total = s.total;
  if (typeof s.paused === "boolean") st.paused = s.paused;
  if (typeof s.active === "boolean") st.active = s.active;
  _render();
}

function _startPolling() {
  _stopPolling();
  pollTimer = setInterval(function () {
    fetch("/api/tts/discord/status")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s) return;
        if (s.connected === false) { _setDisconnected(); return; }
        _applyStatus(s);
        if (s.active === false) _stopPolling();  // reproducción terminada
      })
      .catch(function () { /* errores transitorios: ignorar */ });
  }, 500);
}

function _stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function _setDisconnected() {
  _stopPolling();
  if (els.status) els.status.textContent = "voz desconectada";
  [els.prev, els.next, els.restart, els.playpause, els.stop].forEach(function (b) {
    if (b) b.disabled = true;
  });
}

function _render() {
  if (!els.playpause) return;
  var progress = (st.index + 1) + "/" + (st.total || "?");
  var estado = st.paused ? " · pausado" : (st.active ? " · sonando" : "");
  els.status.textContent = "frase " + progress + estado;
  els.prev.disabled = st.index <= 0;
  els.next.disabled = st.index >= (st.total - 1);
  els.restart.disabled = false;
  els.stop.disabled = false;
  els.playpause.disabled = false;
  els.playpause.textContent = st.paused ? "▶ Reanudar" : "⏸ Pausar";
}

function _hide() {
  _stopPolling();
  if (els.root) els.root.classList.add("hidden");
}

export function initBotPanel() {
  els.root = document.getElementById("bot-speech-panel");
  if (!els.root) return;
  els.header = els.root.querySelector(".bot-panel-header");
  els.question = els.root.querySelector(".bot-panel-question");
  els.answer = els.root.querySelector(".bot-panel-answer");
  els.status = els.root.querySelector(".bot-panel-status");
  els.prev = els.root.querySelector(".bot-panel-prev");
  els.next = els.root.querySelector(".bot-panel-next");
  els.restart = els.root.querySelector(".bot-panel-restart");
  els.playpause = els.root.querySelector(".bot-panel-playpause");
  els.stop = els.root.querySelector(".bot-panel-stop");
  els.close = els.root.querySelector(".bot-panel-close");

  els.prev.addEventListener("click", function () {
    if (st.index > 0) _post("play-at", { index: st.index - 1 });
  });
  els.next.addEventListener("click", function () {
    if (st.index < st.total - 1) _post("play-at", { index: st.index + 1 });
  });
  els.restart.addEventListener("click", function () { _post("play-at", { index: 0 }); });
  els.playpause.addEventListener("click", function () {
    if (st.paused) _post("resume"); else _post("pause");
  });
  els.stop.addEventListener("click", function () { _post("stop").then(_hide); });
  els.close.addEventListener("click", _hide);
}

export function showBotPanel(data) {
  if (!els.root) return;
  els.header.textContent = "🔊 " + (data.bot_keyword || "bot") +
    (data.speaker_name ? " · " + data.speaker_name : "");
  els.question.textContent = data.question || "";
  els.answer.textContent = data.answer_md || "";  // texto escapado; CSS pre-wrap
  st.index = 0;
  st.total = typeof data.total_chunks === "number" ? data.total_chunks : 0;
  st.paused = false;
  st.active = true;
  els.root.classList.remove("hidden");
  _render();
  _startPolling();
}
```

- [ ] **Step 2: Verificar sintaxis del módulo**

Run: `node --check src/rpg_scribe/web/static/js/bot-panel.js`
Expected: sin salida (exit 0). Si `node` no está disponible, abrir el archivo en el navegador vía la app (Task 5) y comprobar que no hay error de sintaxis en la consola.

---

## Task 4: Frontend — HTML, CSS y cableado en `main.js`

**Files:**
- Modify: `src/rpg_scribe/web/static/index.html` (link CSS + contenedor del panel)
- Create: `src/rpg_scribe/web/static/css/features/bot-panel.css`
- Modify: `src/rpg_scribe/web/static/js/main.js` (import + registerHandler + init)

- [ ] **Step 1: Añadir el link del CSS en el `<head>`**

En `src/rpg_scribe/web/static/index.html`, tras la línea `<link rel="stylesheet" href="/css/features/summary.css">` (línea ~15), añadir:

```html
  <link rel="stylesheet" href="/css/features/bot-panel.css">
```

- [ ] **Step 2: Añadir el contenedor del panel dentro de `#status-panel`**

En `src/rpg_scribe/web/static/index.html`, insertar el panel entre el cierre de la rejilla `#component-status` y el `#status-db-path`. Reemplazar:

```html
        </div>
        <div id="status-db-path" class="status-db-path"></div>
```

por:

```html
        </div>
        <div id="bot-speech-panel" class="bot-speech-panel hidden">
          <div class="bot-panel-top">
            <span class="bot-panel-header"></span>
            <button class="bot-panel-close" type="button" title="Cerrar">✕</button>
          </div>
          <div class="bot-panel-question"></div>
          <div class="bot-panel-answer"></div>
          <div class="bot-panel-controls">
            <button class="bot-panel-prev" type="button" title="Frase anterior">⏮</button>
            <button class="bot-panel-restart" type="button" title="Repetir desde el inicio">🔁</button>
            <button class="bot-panel-playpause" type="button">⏸ Pausar</button>
            <button class="bot-panel-next" type="button" title="Frase siguiente">⏭</button>
            <button class="bot-panel-stop" type="button" title="Descartar">⏹</button>
          </div>
          <div class="bot-panel-status"></div>
        </div>
        <div id="status-db-path" class="status-db-path"></div>
```

Nota: la clase `hidden` (display:none) ya está definida globalmente en el CSS del proyecto (la usan `#session-banner`, etc.); no hay que redefinirla.

- [ ] **Step 3: Crear el CSS del panel**

Crear `src/rpg_scribe/web/static/css/features/bot-panel.css`:

```css
/* Panel de control de voz del bot (dentro de System Status) */
.bot-speech-panel {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border-color, #3a3a4a);
  border-radius: 8px;
  background: var(--panel-bg, #1e1e28);
}

.bot-panel-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.bot-panel-header { font-weight: 600; }

.bot-panel-close {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}

.bot-panel-question {
  margin: 6px 0;
  font-style: italic;
  opacity: 0.85;
}

.bot-panel-answer {
  margin: 6px 0;
  white-space: pre-wrap;
  max-height: 220px;
  overflow-y: auto;
}

.bot-panel-controls {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.bot-panel-controls button {
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #3a3a4a);
  background: var(--btn-bg, #2a2a38);
  color: inherit;
}

.bot-panel-controls button:disabled {
  opacity: 0.4;
  cursor: default;
}

.bot-panel-status {
  margin-top: 6px;
  font-size: 0.85rem;
  opacity: 0.75;
}
```

- [ ] **Step 4: Cablear en `main.js`**

En `src/rpg_scribe/web/static/js/main.js`:

4a. Añadir el import junto a los demás imports de módulos (tras la línea `import { initTTS } from "./tts.js";`):

```javascript
import { initBotPanel, showBotPanel } from "./bot-panel.js";
```

4b. Registrar el handler del WebSocket junto a los otros `registerHandler(...)` (tras el de `generation_progress`):

```javascript
registerHandler("bot_speech", function (data) {
  showBotPanel(data);
});
```

4c. Inicializar el panel en la sección "Init all module listeners" (junto a `initTTS();`):

```javascript
initBotPanel();
```

- [ ] **Step 5: Verificar sintaxis de `main.js`**

Run: `node --check src/rpg_scribe/web/static/js/main.js`
Expected: exit 0 (si `node` está disponible; si no, se valida en la Task 5).

---

## Task 5: Verificación end-to-end (manual) + docs

**Files:**
- Modify: `docs/rules-bot.md` (mención del panel)

- [ ] **Step 1: Arrancar la app y conectar la voz**

Run: `rpg-scribe --campaign config/campaigns/cyberpunk-build-lab.toml`
Abrir el Web UI (por defecto `http://127.0.0.1:8000`). En Discord, unir el bot a un canal de voz (`/scribe start`).

- [ ] **Step 2: Disparar una respuesta del bot y verificar el panel**

Por voz: "bot reglas, ¿cómo funciona el netrunning?". Comprobar en el Web UI (modo Live), dentro de **System Status**:
  - Aparece el panel con `🔊 bot reglas · <hablante>`, la pregunta y el texto de la respuesta.
  - "frase N/total" avanza mientras suena.
  - **⏸ Pausar** pausa el audio en Discord y el botón pasa a **▶ Reanudar**; Reanudar continúa.
  - **⏭ / ⏮** saltan de frase (se deshabilitan en los extremos).
  - **🔁 Repetir** reinicia desde la frase 1.
  - **⏹ Descartar** corta el audio y oculta el panel.
  - **✕** cierra el panel sin cortar.

- [ ] **Step 3: Verificar el caso de voz desconectada**

Con el panel visible, desconectar el bot de la voz (`/scribe stop`). El polling detecta `connected:false` → el panel muestra "voz desconectada" y deshabilita los controles.

- [ ] **Step 4: Documentar**

En `docs/rules-bot.md`, en la sección de Web UI / componentes, añadir una nota:

```markdown
## Panel de control de voz (Web UI)

Cuando el bot reproduce una respuesta hablada, aparece un panel dentro de
**System Status** con controles de transporte sobre el audio en Discord:
Pausar/Reanudar, frase anterior/siguiente, Repetir (desde el inicio) y
Descartar. Es solo transporte (no re-consulta a Claude). Implementación:
`BotSpeechEvent` (watcher) → WebSocket `bot_speech` → `bot-panel.js`, que usa
los endpoints existentes `/api/tts/discord/*`.
```

- [ ] **Step 5: Checkpoint final (sin commit)**

Run: `python -m pytest tests/test_trigger_watcher.py tests/test_websocket_bridge.py -q`
Expected: PASS.
Run: `ruff check src/ tests/`
Expected: `All checks passed!`
No hacer commit — el usuario prueba y decide cuándo commitear.

---

## Notas de implementación

- **Cero endpoints nuevos:** todo el transporte reutiliza `/api/tts/discord/{pause,resume,stop,play-at,status}` (`src/rpg_scribe/web/routers/tts.py`) y el `DiscordTTSPlayer` (`src/rpg_scribe/discord_bot/tts_player.py`).
- **`answer_md` como texto:** el frontend no tiene librería de markdown; se muestra con `textContent` + `white-space: pre-wrap` (decisión del spec).
- **Solo modo Live:** `websocket.js` ignora mensajes fuera de modo `live`, así que el panel solo opera en Live (aceptado en el spec).
- **Player compartido:** el panel solo se *dispara* con `bot_speech`, pero `/status` refleja cualquier reproducción activa (solo hay una a la vez). Aceptado.
