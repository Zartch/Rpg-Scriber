# Diseño: Alarma de transcripción detenida (watchdog en navegador)

**Fecha:** 2026-07-11
**Estado:** Aprobado (diseño) — pendiente de plan de implementación
**Approach elegido:** A (watchdog puro en el navegador, cero cambios en backend)

## Contexto y motivación

En la sesión `c315b1ca` la transcripción se detuvo y no se detectó hasta ~1h30m
después, con la partida aún en curso.

Diagnóstico del log `logs/1783714795.log`: la última línea (22:51 local) está
**completamente sana** (`received=95 transcribed=43 hallu=0 errored=0
last_success=3s ago`) y a partir de ahí el log **se corta en seco**. La tarea
`_periodic_stats` de `BaseTranscriber` loguea cada 30s incondicionalmente, así
que la ausencia total de líneas nuevas indica que **el proceso servidor se
congeló o murió**, no que el audio se degradara. Es un modo de fallo distinto
al bug documentado en `docs/discord-voice.md` (degradación de audio con proceso
vivo).

**Consecuencia de diseño:** un detector de stall *server-side* (como el
`_log_stats` actual) no puede avisar de esto — el proceso estaba muerto. El
navegador sí puede: su WebSocket se cae (`ws.onclose`). Por eso la alarma vive
en el navegador.

## Criterio de disparo (orientado a impacto)

La alarma solo está **armada** cuando de verdad debería haber transcripción:
partida activa + bot conectado + sesión no finalizada. Estando armada, si la
transcripción deja de fluir (por cualquier causa), suena.

Traducción a señales que el navegador ya recibe hoy:

| Concepto de impacto | Señal observable en el navegador |
|---|---|
| Bot en un canal + sesión activa + no finalizada | Último estado conocido de `listener` = `running` (pasa a `idle` solo al desconectar/finalizar) |
| Se paró la transcripción (servidor muerto) | `ws.onclose` — el WebSocket se cae |
| Se paró la transcripción (audio degradado, servidor vivo) | No llega ningún mensaje `transcription` durante > umbral con WS vivo |

Todas viajan por el WebSocket / API existentes → implementación 100% en JS.

## Arquitectura

Módulo nuevo `web/static/js/alarm.js`, aislado. Se engancha en `main.js`.

```
websocket.js  ──(transcription / status / onopen / onclose)──►  alarm.js
                                                                    │
                        estado: { armed, lastTranscriptionAt, wsConnected, muted }
                        setInterval(~5s) evalúa condiciones de fallo
                                                                    │
                                     ▼
                    alarma sonora (loop) + banner rojo + flash en document.title
```

### Cambio de soporte en `websocket.js`

Hoy `websocket.js` no expone los eventos de conexión a otros módulos. Se añade un
hook mínimo para que `alarm.js` sepa cuándo el WS cae/vuelve sin tocar el objeto
`ws` directamente. Opción preferida: un callback `onConnectionChange(connected)`
registrable (p. ej. `setConnectionListener(fn)`), invocado en `ws.onopen` (true)
y `ws.onclose` (false). Mantiene `alarm.js` aislado del transporte.

El resto de señales (`transcription`, `status`) las consume `alarm.js` vía
`registerHandler(...)` existente. `status` del componente `listener` arma/desarma;
`transcription` refresca `lastTranscriptionAt`.

## Máquina de estados

```
DESARMADA  ──(listener=running)──►  ARMADA  ──(condición de fallo)──►  ALARMANDO
   ▲                                   │                                  │
   └────(listener=idle / finalizada)───┘                                  │
   ▲                                                                      │
   └──(transcripción vuelve a fluir  ó  "Silenciar")──────────────────────┘
```

- **Armar:** último estado conocido de `listener` = `running`.
- **Desarmar (sin alarma):** `listener` pasa a `idle`. Nunca molesta fuera de partida.
- **Condiciones de fallo (solo estando ARMADA):**
  1. WS desconectado durante > **20 s** (margen para tolerar reconexiones transitorias), **o**
  2. Sin ningún mensaje `transcription` en > **120 s** con el WS vivo.
- **Auto-recuperación:** si vuelve a llegar una transcripción (o el WS reconecta
  y el listener sigue `running`), la alarma se apaga sola y el estado vuelve a
  ARMADA.

### Parámetros (constantes en el módulo)

| Parámetro | Valor | Racional |
|---|---|---|
| `TRANSCRIPTION_TIMEOUT_S` | 120 | Coincide con `_STALL_WARNING_S` del servidor |
| `WS_GRACE_S` | 20 | Tolera blips de red / reconexión con backoff |
| `CHECK_INTERVAL_S` | 5 | Resolución de evaluación del watchdog |

## La alarma

- **Sonido:** loop hasta reconocer. Web Audio API (oscilador) → sin fichero
  externo que empaquetar ni CSP que sortear.
- **Visual:** banner rojo fijo arriba ("⚠️ Transcripción detenida hace Xs —
  revisa el bot") + parpadeo de `document.title` para pestañas en segundo plano.
- **Botón "Silenciar":** corta el sonido actual pero deja el banner visible; si
  el fallo persiste o reaparece tras resolverse, **vuelve a sonar** (silencia y
  re-arma; no permite olvidarse del problema).
- **Autoplay:** los navegadores bloquean audio sin gesto previo. Se prima el
  `AudioContext` en el primer clic del usuario en la página. Si aun así está
  bloqueado, el banner + flash de título actúan como fallback visual.

## Aislamiento y testabilidad

`alarm.js` expone una unidad testeable: una función pura de decisión que, dado el
estado `{ armed, lastTranscriptionAt, wsConnected, wsDownSince, now }`, devuelve
si debe alarmar. Los efectos (sonido, DOM, título) se mantienen separados de esa
lógica para poder probar la decisión sin navegador.

## Fuera de alcance (YAGNI)

- Broadcast del stall desde el servidor (Approach B) — mejora incremental futura
  si los silencios reales largos generan falsos positivos molestos.
- Heartbeat del servidor (Approach C).
- Persistencia/configuración en UI de los umbrales — de momento constantes.
- Notificaciones del SO / push fuera de la pestaña.

## Riesgos conocidos

- **Falso positivo en silencios reales largos** (combate, pausa) con WS vivo:
  mitigado por umbral de 120 s + botón silenciar. Aceptado en Approach A.
- **Autoplay bloqueado** si el usuario no ha interactuado: mitigado con priming
  y fallback visual.
- **Throttling de timers en pestaña en segundo plano** (~1/min): irrelevante
  para umbrales de 120 s; la primera evaluación tras volver al foco dispara igual.
