# Alarma de Transcripción Detenida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un watchdog en el navegador que hace sonar una alarma (sonido + banner + flash del título) cuando, con una partida activa, la transcripción en vivo deja de fluir — ya sea porque el servidor murió (WebSocket caído) o porque el audio se degradó (sin transcripciones con WS vivo).

**Architecture:** Módulo JS aislado. La lógica de decisión (pura, sin DOM/audio) vive en `alarm-decision.js` y se testea con el runner nativo de Node. Los efectos (sonido Web Audio, banner, título) y el cableado viven en `alarm.js`, que recibe las señales que ya viajan por el WebSocket/API existentes vía `main.js` y un nuevo hook de conexión en `websocket.js`. Cero cambios en el backend Python.

**Tech Stack:** JavaScript ES modules nativos de navegador (sin build step), Web Audio API, Node 22 `node:test` para los tests de la lógica pura.

## Global Constraints

- **Regla del proyecto (CLAUDE.md): NO hacer commits salvo que el usuario lo pida explícitamente.** Los pasos `git commit` de abajo son los checkpoints previstos del flujo TDD; durante la ejecución, **deténte en el estado testeado/staged y deja que el usuario commitee**, salvo que ya te haya autorizado.
- Sin build step: los `.js` se sirven tal cual al navegador como ES modules. No introducir bundlers ni transpiladores.
- Autocontenido (CSP estricta): la alarma sonora se genera con Web Audio API. **No** empaquetar ni referenciar ficheros de audio externos.
- Estilo de código JS existente: `var`, funciones como expresiones (`function () {}`), sin arrow functions salvo trivial. Imitar `web/static/js/*.js`.
- Parámetros del watchdog (exactos): `TRANSCRIPTION_TIMEOUT_MS = 120000`, `WS_GRACE_MS = 20000`, `CHECK_INTERVAL_MS = 5000`.
- `registerHandler(type, fn)` en `websocket.js` guarda **un solo handler por tipo**. NO registrar `"status"` ni `"transcription"` desde `alarm.js` (clobbering). Las señales de esos tipos entran vía llamadas explícitas desde `main.js`.

---

## File Structure

- **Create** `package.json` (raíz) — `{"private": true, "type": "module"}`. Solo para que Node interprete los `.js` como ES modules al correr los tests. Inerte para el lado Python y para el navegador.
- **Create** `src/rpg_scribe/web/static/js/alarm-decision.js` — lógica pura: `evaluateAlarm(state, now)`, `formatBannerMessage(reason, silentSeconds)`, y las constantes. Sin DOM ni audio.
- **Create** `tests/js/alarm-decision.test.js` — tests con `node:test` de la lógica pura.
- **Create** `src/rpg_scribe/web/static/js/alarm.js` — estado del watchdog, efectos (sonido/banner/título), y funciones de entrada (`initAlarm`, `onStatus`, `onTranscription`).
- **Create** `src/rpg_scribe/web/static/css/features/alarm.css` — estilos del banner.
- **Modify** `src/rpg_scribe/web/static/js/websocket.js` — añadir `setConnectionListener(fn)` invocado en `onopen`/`onclose`.
- **Modify** `src/rpg_scribe/web/static/js/main.js` — importar y cablear `alarm.js`.
- **Modify** `src/rpg_scribe/web/static/index.html` — elemento banner + `<link>` del CSS.

---

## Task 1: Lógica de decisión pura (`alarm-decision.js`)

**Files:**
- Create: `package.json`
- Create: `src/rpg_scribe/web/static/js/alarm-decision.js`
- Test: `tests/js/alarm-decision.test.js`

**Interfaces:**
- Produces:
  - `const TRANSCRIPTION_TIMEOUT_MS = 120000`
  - `const WS_GRACE_MS = 20000`
  - `const CHECK_INTERVAL_MS = 5000`
  - `evaluateAlarm(state, now)` → `{ shouldAlarm: boolean, reason: "ws-down"|"transcription-timeout"|null, silentSeconds: number }`
    - `state` = `{ armed: boolean, wsConnected: boolean, wsDownSince: number|null, lastTranscriptionAt: number|null }`
    - `now` = epoch en ms
  - `formatBannerMessage(reason, silentSeconds)` → `string`

- [ ] **Step 1: Crear `package.json` en la raíz**

```json
{
  "private": true,
  "type": "module"
}
```

- [ ] **Step 2: Escribir el test que falla**

Create `tests/js/alarm-decision.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  evaluateAlarm,
  formatBannerMessage,
  TRANSCRIPTION_TIMEOUT_MS,
  WS_GRACE_MS,
} from "../../src/rpg_scribe/web/static/js/alarm-decision.js";

var NOW = 1_000_000_000_000;

function baseState(overrides) {
  return Object.assign(
    {
      armed: true,
      wsConnected: true,
      wsDownSince: null,
      lastTranscriptionAt: NOW,
    },
    overrides || {}
  );
}

test("no alarma si no está armada", function () {
  var r = evaluateAlarm(baseState({ armed: false, lastTranscriptionAt: 0 }), NOW);
  assert.equal(r.shouldAlarm, false);
  assert.equal(r.reason, null);
});

test("no alarma si el WS lleva caído menos que el margen", function () {
  var state = baseState({
    wsConnected: false,
    wsDownSince: NOW - (WS_GRACE_MS - 1000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, false);
});

test("alarma ws-down si el WS lleva caído más que el margen", function () {
  var state = baseState({
    wsConnected: false,
    wsDownSince: NOW - (WS_GRACE_MS + 5000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, true);
  assert.equal(r.reason, "ws-down");
  assert.equal(r.silentSeconds, Math.floor((WS_GRACE_MS + 5000) / 1000));
});

test("no alarma con WS vivo y transcripción reciente", function () {
  var r = evaluateAlarm(baseState({ lastTranscriptionAt: NOW - 10000 }), NOW);
  assert.equal(r.shouldAlarm, false);
});

test("alarma transcription-timeout con WS vivo y silencio prolongado", function () {
  var state = baseState({
    lastTranscriptionAt: NOW - (TRANSCRIPTION_TIMEOUT_MS + 3000),
  });
  var r = evaluateAlarm(state, NOW);
  assert.equal(r.shouldAlarm, true);
  assert.equal(r.reason, "transcription-timeout");
});

test("defensivo: armada + WS vivo + lastTranscriptionAt null no alarma", function () {
  var r = evaluateAlarm(baseState({ lastTranscriptionAt: null }), NOW);
  assert.equal(r.shouldAlarm, false);
});

test("formatBannerMessage distingue las dos causas", function () {
  var wsMsg = formatBannerMessage("ws-down", 25);
  var txMsg = formatBannerMessage("transcription-timeout", 130);
  assert.match(wsMsg, /servidor/i);
  assert.match(wsMsg, /25/);
  assert.match(txMsg, /transcripci/i);
  assert.match(txMsg, /130/);
});
```

- [ ] **Step 3: Ejecutar el test y verificar que falla**

Run: `node --test tests/js/alarm-decision.test.js`
Expected: FAIL — `Cannot find module '.../alarm-decision.js'`.

- [ ] **Step 4: Implementar `alarm-decision.js`**

Create `src/rpg_scribe/web/static/js/alarm-decision.js`:

```js
/* RPG Scribe - alarma de transcripción: lógica de decisión pura (sin DOM/audio) */

export var TRANSCRIPTION_TIMEOUT_MS = 120000;
export var WS_GRACE_MS = 20000;
export var CHECK_INTERVAL_MS = 5000;

// state = { armed, wsConnected, wsDownSince, lastTranscriptionAt }
// Devuelve { shouldAlarm, reason, silentSeconds }.
export function evaluateAlarm(state, now) {
  if (!state.armed) {
    return { shouldAlarm: false, reason: null, silentSeconds: 0 };
  }

  // Servidor muerto/congelado: el WebSocket se cae. Toleramos un margen para
  // reconexiones transitorias.
  if (!state.wsConnected) {
    if (state.wsDownSince != null && now - state.wsDownSince > WS_GRACE_MS) {
      return {
        shouldAlarm: true,
        reason: "ws-down",
        silentSeconds: Math.floor((now - state.wsDownSince) / 1000),
      };
    }
    return { shouldAlarm: false, reason: null, silentSeconds: 0 };
  }

  // WS vivo: audio degradado = llegan cosas pero no transcripciones.
  if (
    state.lastTranscriptionAt != null &&
    now - state.lastTranscriptionAt > TRANSCRIPTION_TIMEOUT_MS
  ) {
    return {
      shouldAlarm: true,
      reason: "transcription-timeout",
      silentSeconds: Math.floor((now - state.lastTranscriptionAt) / 1000),
    };
  }

  return { shouldAlarm: false, reason: null, silentSeconds: 0 };
}

export function formatBannerMessage(reason, silentSeconds) {
  if (reason === "ws-down") {
    return (
      "⚠️ Conexión con el servidor perdida hace " +
      silentSeconds +
      "s — la transcripción puede estar detenida. Revisa el bot."
    );
  }
  return (
    "⚠️ Sin transcripción desde hace " +
    silentSeconds +
    "s — revisa el bot."
  );
}
```

- [ ] **Step 5: Ejecutar el test y verificar que pasa**

Run: `node --test tests/js/alarm-decision.test.js`
Expected: PASS — 7 tests, 0 fallos.

- [ ] **Step 6: Verificar que la suite Python sigue verde (package.json no la rompe)**

Run: `pytest -q`
Expected: mismos resultados que antes (los fallos pre-existentes conocidos siguen, nada nuevo roto).

- [ ] **Step 7: Commit** (solo si el usuario lo ha autorizado — ver Global Constraints)

```bash
git add package.json src/rpg_scribe/web/static/js/alarm-decision.js tests/js/alarm-decision.test.js
git commit -m "feat(alarm): lógica pura de decisión del watchdog de transcripción con tests Node"
```

---

## Task 2: Hook de conexión en `websocket.js`

**Files:**
- Modify: `src/rpg_scribe/web/static/js/websocket.js`

**Interfaces:**
- Consumes: nada de tareas previas.
- Produces:
  - `setConnectionListener(fn)` — registra un callback `fn(connected: boolean)` invocado con `true` en `ws.onopen` y `false` en `ws.onclose`.

**Nota:** no hay tests JS automatizados para este archivo (depende de `WebSocket` del navegador). Se verifica manualmente al final de la Task 3. El cambio es mínimo y de bajo riesgo.

- [ ] **Step 1: Añadir el registro del listener**

En `src/rpg_scribe/web/static/js/websocket.js`, tras la línea `var handlers = {};` (línea 9), añadir:

```js
var connectionListener = null;

export function setConnectionListener(fn) {
  connectionListener = fn;
}
```

- [ ] **Step 2: Invocar el listener en `onopen`**

En `ws.onopen`, tras poner el badge a "Connected" (después de la línea `connectionBadge.className = "badge badge-connected";` y su `}`), añadir dentro del handler:

```js
    if (connectionListener) connectionListener(true);
```

El bloque `ws.onopen` queda así:

```js
  ws.onopen = function () {
    reconnectDelay = 1000;
    var connectionBadge = document.getElementById("connection-badge");
    if (connectionBadge) {
      connectionBadge.textContent = "Connected";
      connectionBadge.className = "badge badge-connected";
    }
    if (connectionListener) connectionListener(true);
  };
```

- [ ] **Step 3: Invocar el listener en `onclose`**

`ws.onclose` queda así:

```js
  ws.onclose = function () {
    var connectionBadge = document.getElementById("connection-badge");
    if (connectionBadge) {
      connectionBadge.textContent = "Disconnected";
      connectionBadge.className = "badge badge-idle";
    }
    if (connectionListener) connectionListener(false);
    setTimeout(connectWS, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT);
  };
```

- [ ] **Step 4: Commit** (solo si el usuario lo ha autorizado)

```bash
git add src/rpg_scribe/web/static/js/websocket.js
git commit -m "feat(alarm): exponer cambios de conexión del WebSocket vía setConnectionListener"
```

---

## Task 3: Efectos, cableado y banner (`alarm.js` + `main.js` + HTML/CSS)

**Files:**
- Create: `src/rpg_scribe/web/static/js/alarm.js`
- Create: `src/rpg_scribe/web/static/css/features/alarm.css`
- Modify: `src/rpg_scribe/web/static/index.html`
- Modify: `src/rpg_scribe/web/static/js/main.js`

**Interfaces:**
- Consumes:
  - de `alarm-decision.js`: `evaluateAlarm`, `formatBannerMessage`, `CHECK_INTERVAL_MS`.
  - de `websocket.js`: `setConnectionListener`.
- Produces (desde `alarm.js`):
  - `initAlarm()` — cachea el DOM del banner, prima el AudioContext al primer clic, registra el listener de conexión y arranca el `setInterval` del watchdog.
  - `onStatus(data)` — recibe cada `SystemStatusEvent`; arma con `component==="listener" && status==="running"`, desarma y limpia con `status==="idle"`.
  - `onTranscription()` — refresca `lastTranscriptionAt`.

- [ ] **Step 1: Crear el CSS del banner**

Create `src/rpg_scribe/web/static/css/features/alarm.css`:

```css
/* Banner de alarma de transcripción detenida */
.stall-alarm {
  position: sticky;
  top: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: #b3261e;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  animation: stall-alarm-pulse 1s ease-in-out infinite;
}

.stall-alarm.hidden {
  display: none;
}

.stall-alarm-msg {
  flex: 1;
}

.stall-alarm-mute {
  flex: 0 0 auto;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  font-weight: 600;
}

.stall-alarm-mute:hover {
  background: rgba(255, 255, 255, 0.3);
}

@keyframes stall-alarm-pulse {
  0%, 100% { background: #b3261e; }
  50% { background: #8c1d18; }
}
```

- [ ] **Step 2: Añadir el banner y el `<link>` en `index.html`**

En `src/rpg_scribe/web/static/index.html`, tras la línea del CSS de bot-panel (línea 16, `<link rel="stylesheet" href="/css/features/bot-panel.css">`), añadir:

```html
  <link rel="stylesheet" href="/css/features/alarm.css">
```

Justo después de `<body>` (línea 18) y antes de `<header>` (línea 19), añadir el banner:

```html
  <div id="stall-alarm-banner" class="stall-alarm hidden" role="alert">
    <span class="stall-alarm-msg"></span>
    <button type="button" class="stall-alarm-mute">🔇 Silenciar</button>
  </div>
```

- [ ] **Step 3: Crear `alarm.js`**

Create `src/rpg_scribe/web/static/js/alarm.js`:

```js
/* RPG Scribe - watchdog de transcripción detenida (efectos + cableado) */

import { setConnectionListener } from "./websocket.js";
import {
  evaluateAlarm,
  formatBannerMessage,
  CHECK_INTERVAL_MS,
} from "./alarm-decision.js";

var alarmState = {
  armed: false,
  wsConnected: true,
  wsDownSince: null,
  lastTranscriptionAt: null,
};

var muted = false;

var bannerEl = null;
var bannerMsgEl = null;

var audioCtx = null;
var beepTimer = null;
var soundPlaying = false;

var originalTitle = document.title;
var titleTimer = null;
var titleFlipped = false;

// ── Entradas de señal ────────────────────────────────────────────────────────

export function onStatus(data) {
  if (!data || data.component !== "listener") return;
  if (data.status === "running") {
    alarmState.armed = true;
    // El reloj de silencio arranca al armar, no en la carga de la página.
    alarmState.lastTranscriptionAt = Date.now();
  } else if (data.status === "idle") {
    alarmState.armed = false;
    muted = false;
    clearAlarm();
  }
}

export function onTranscription() {
  alarmState.lastTranscriptionAt = Date.now();
}

// ── Init ─────────────────────────────────────────────────────────────────────

export function initAlarm() {
  bannerEl = document.getElementById("stall-alarm-banner");
  bannerMsgEl = bannerEl ? bannerEl.querySelector(".stall-alarm-msg") : null;

  var muteBtn = bannerEl ? bannerEl.querySelector(".stall-alarm-mute") : null;
  if (muteBtn) {
    muteBtn.addEventListener("click", function () {
      muted = true;
      stopSound();
    });
  }

  // Los navegadores bloquean audio sin gesto previo: primamos el contexto.
  document.addEventListener("click", primeAudio, { once: true });

  setConnectionListener(function (connected) {
    alarmState.wsConnected = connected;
    if (connected) {
      alarmState.wsDownSince = null;
    } else if (alarmState.wsDownSince == null) {
      alarmState.wsDownSince = Date.now();
    }
  });

  setInterval(tick, CHECK_INTERVAL_MS);

  // Ayuda de depuración/verificación manual (inerte en uso normal).
  window.__rpgAlarm = {
    state: alarmState,
    forceArmStale: function () {
      alarmState.armed = true;
      alarmState.wsConnected = true;
      alarmState.lastTranscriptionAt = Date.now() - 999999;
    },
    evaluate: function () {
      return evaluateAlarm(alarmState, Date.now());
    },
  };
}

// ── Bucle del watchdog ───────────────────────────────────────────────────────

function tick() {
  var decision = evaluateAlarm(alarmState, Date.now());
  if (decision.shouldAlarm) {
    showBanner(formatBannerMessage(decision.reason, decision.silentSeconds));
    startTitleFlash();
    if (!muted) startSound();
  } else {
    // Recuperación: reseteamos el silenciado para poder re-alarmar si reaparece.
    muted = false;
    clearAlarm();
  }
}

function clearAlarm() {
  stopSound();
  stopTitleFlash();
  hideBanner();
}

// ── Banner ───────────────────────────────────────────────────────────────────

function showBanner(msg) {
  if (bannerMsgEl) bannerMsgEl.textContent = msg;
  if (bannerEl) bannerEl.classList.remove("hidden");
}

function hideBanner() {
  if (bannerEl) bannerEl.classList.add("hidden");
}

// ── Título parpadeante ───────────────────────────────────────────────────────

function startTitleFlash() {
  if (titleTimer) return;
  titleTimer = setInterval(function () {
    document.title = titleFlipped ? originalTitle : "🚨 TRANSCRIPCIÓN DETENIDA";
    titleFlipped = !titleFlipped;
  }, 1000);
}

function stopTitleFlash() {
  if (titleTimer) {
    clearInterval(titleTimer);
    titleTimer = null;
  }
  document.title = originalTitle;
  titleFlipped = false;
}

// ── Sonido (Web Audio, sin ficheros) ─────────────────────────────────────────

function primeAudio() {
  if (!audioCtx) {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) audioCtx = new Ctx();
  }
  if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
}

function startSound() {
  if (soundPlaying) return;
  if (!audioCtx) return; // aún sin gesto de usuario → solo aviso visual
  soundPlaying = true;
  playBeep();
  beepTimer = setInterval(playBeep, 1200);
}

function stopSound() {
  soundPlaying = false;
  if (beepTimer) {
    clearInterval(beepTimer);
    beepTimer = null;
  }
}

function playBeep() {
  if (!audioCtx) return;
  var osc = audioCtx.createOscillator();
  var gain = audioCtx.createGain();
  osc.type = "square";
  osc.frequency.value = 880;
  var t = audioCtx.currentTime;
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.2, t + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.start(t);
  osc.stop(t + 0.36);
}
```

- [ ] **Step 4: Cablear `alarm.js` en `main.js`**

En `src/rpg_scribe/web/static/js/main.js`:

4a. Añadir el import tras el import de bot-panel (línea 13, `import { initBotPanel, showBotPanel } from "./bot-panel.js";`):

```js
import { initAlarm, onStatus as alarmOnStatus, onTranscription as alarmOnTranscription } from "./alarm.js";
```

4b. En el handler `registerHandler("transcription", ...)` (líneas 21-23), añadir la llamada al watchdog:

```js
registerHandler("transcription", function (data) {
  addTranscription(data);
  alarmOnTranscription();
});
```

4c. En la función `updateStatus(data)` (empieza en la línea 49), añadir como **primera línea** del cuerpo la notificación al watchdog. `updateStatus` es llamada tanto por el handler WS `"status"` como por `fetchStatus()` (carga inicial vía `/api/status`), así que cubre ambos caminos de armado:

```js
function updateStatus(data) {
  alarmOnStatus(data);
  var card = componentStatusEl ? componentStatusEl.querySelector(
    '[data-component="' + data.component + '"]'
  ) : null;
  ...
```

4d. En la sección `// ── Init all module listeners ──` (tras `initBotPanel();`, línea 276), añadir:

```js
initAlarm();
```

- [ ] **Step 5: Verificar que los tests de la Task 1 siguen pasando**

Run: `node --test tests/js/alarm-decision.test.js`
Expected: PASS — 7 tests, 0 fallos (no hemos tocado la lógica pura, pero confirmamos que nada de la integración la rompió).

- [ ] **Step 6: Verificación manual en navegador — camino `ws-down` (el caso de hoy)**

Este es el camino crítico y se puede probar de verdad:

1. Arranca la app: `rpg-scribe --campaign config/campaigns/<tuya>.toml` (o `rpg-scribe`).
2. Abre `http://127.0.0.1:8000`. Haz **un clic** en cualquier parte (desbloquea el audio).
3. Con `/scribe start` en Discord, arma la alarma (el `listener` pasa a `running`; verás el status card en verde). Si no quieres usar Discord, en la consola del navegador: `window.__rpgAlarm.state.armed = true`.
4. **Mata el proceso del servidor** (Ctrl+C en la terminal de `rpg-scribe`).
5. Espera ~20-25s. Esperado: el badge pasa a "Disconnected", y tras superar el margen de 20s aparece el **banner rojo** ("Conexión con el servidor perdida...") + **suena la alarma** + el **título de la pestaña parpadea**.
6. Pulsa "🔇 Silenciar". Esperado: el sonido para, el banner permanece.
7. Vuelve a arrancar el servidor. Cuando el WS reconecte y llegue estado, esperado: el banner desaparece y el título vuelve a "RPG Scribe".

- [ ] **Step 7: Verificación manual en navegador — camino `transcription-timeout`**

Para no esperar 120s reales, usa el hook de depuración:

1. Con la app abierta y tras un clic (audio primado), en la consola del navegador:
   `window.__rpgAlarm.forceArmStale()`
2. Espera hasta el siguiente `tick` (máx. 5s). Esperado: banner ("Sin transcripción desde hace ...s") + sonido + título parpadeando, **sin** que el WS esté caído (badge sigue "Connected").
3. Simula que vuelve la transcripción: `window.__rpgAlarm.state.lastTranscriptionAt = Date.now()`
4. En el siguiente `tick`, esperado: la alarma se apaga sola (auto-recuperación).

- [ ] **Step 8: Commit** (solo si el usuario lo ha autorizado)

```bash
git add src/rpg_scribe/web/static/js/alarm.js src/rpg_scribe/web/static/css/features/alarm.css src/rpg_scribe/web/static/index.html src/rpg_scribe/web/static/js/main.js
git commit -m "feat(alarm): watchdog de transcripción en el navegador (sonido + banner + flash de título)"
```

---

## Self-Review

**Spec coverage:**
- Watchdog 100% navegador, cero backend → Tasks 1-3, sin cambios en Python. ✓
- Armado por `listener=running`, desarmado por `idle` → Task 3 Step 3 (`onStatus`). ✓
- Fallo `ws-down` con margen 20s → Task 1 (`evaluateAlarm`) + Task 2 (hook) + Task 3 (listener). ✓
- Fallo `transcription-timeout` con umbral 120s → Task 1 + Task 3 (`onTranscription`). ✓
- Auto-recuperación → Task 3 `tick()` rama `else`. ✓
- Sonido en loop (Web Audio, sin assets) → Task 3 `startSound`/`playBeep`. ✓
- Banner rojo + flash de título → Task 3 CSS + `showBanner`/`startTitleFlash`. ✓
- Botón silenciar (silencia sonido, mantiene banner, re-arma en recuperación) → Task 3 mute handler + reseteo de `muted` en la rama de recuperación. ✓
- Priming de autoplay + fallback visual → Task 3 `primeAudio` + `startSound` retorna sin sonido si no hay contexto (banner/título igual se muestran). ✓
- Función de decisión pura y testeable aislada de efectos → Task 1. ✓
- Fuera de alcance (broadcast servidor, heartbeat, config UI) → no incluido. ✓

**Placeholder scan:** sin TBD/TODO; todo el código está completo en cada paso. ✓

**Type consistency:** `evaluateAlarm(state, now)` y su retorno `{shouldAlarm, reason, silentSeconds}` son idénticos entre Task 1 (definición + tests) y Task 3 (consumo en `tick`). `setConnectionListener(fn)` idéntico entre Task 2 (def) y Task 3 (uso). `onStatus`/`onTranscription`/`initAlarm` idénticos entre la definición en `alarm.js` (Task 3 Step 3) y el import/uso en `main.js` (Task 3 Step 4). Claves de estado (`armed`, `wsConnected`, `wsDownSince`, `lastTranscriptionAt`) consistentes en todo el plan. ✓
