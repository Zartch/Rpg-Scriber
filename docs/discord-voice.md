# Discord Voice & DAVE E2EE

## 🐛 Bug abierto: degradación silenciosa del audio en sesiones largas

**Estado:** SIN RESOLVER — solo paliado con observabilidad y recuperación de estado. **No dar por cerrado.**

**Síntoma reproducido en al menos 3 sesiones consecutivas:**

1. La sesión arranca normal y transcribe bien durante un rato.
2. En algún momento se loguea **una alucinación** (frases tipo `"No, no, no, no."`, `"Bye. Dicho bye. Bye."`, `"¡Suscríbete!"`, etc.).
3. A partir de ese chunk, **no vuelven a salir transcripciones exitosas** aunque los jugadores siguen hablando con normalidad.
4. Los chunks SÍ siguen llegando al transcriber, pero `voice_recv` los entrega con `RMS<50` (umbral 200) → todos se descartan en `analyze_audio` como `near_silence` / `low_energy`.
5. Eventualmente (minutos u horas después) el bot acaba siendo expulsado del canal o cae silenciosamente, dejando estado zombie (`/scribe start` responde `"Already recording!"`).

**Pruebas de que el audio se corrompe, no es el filtro:**

- Carpeta `logs/audio/discarded/<session_id>/`: los WAVs guardados durante la degradación están efectivamente silenciosos al reproducirlos.
- La transición coincide con la alucinación porque ese chunk es el último audio "casi real" que recibe el modelo antes de que el stream se rompa del todo.

**Causa raíz no confirmada.** Hipótesis ordenadas por probabilidad:

1. **Renegociación DAVE fallida** que rompe el descifrado sin que el monkey-patch lo note. Encajaría con el aviso del comentario en `_patch_dave_decryption`: *"Intermittent per-packet failures are normal during DAVE key renegotiation"* — si esos fallos se vuelven persistentes, todos los paquetes salen como silencio.
2. **`voice_recv` jitter buffer corrupto** tras un drop de red transitorio.
3. **Algo específico de faster-whisper local** — el reporte original menciona que con OpenAI transcriber el patrón quizá no aparezca; está sin confirmar.

**Mitigaciones actuales (no fix):**

- Logging enriquecido + stall detection (ver más abajo) para confirmar el patrón cuando vuelva a pasar.
- Recuperación de estado de sesión para que `/scribe start` funcione sin reiniciar el bot.
- Fix del bloqueo del event loop en faster-whisper — relacionado pero no es la causa raíz del audio corrupto.

**Próximos pasos sugeridos cuando se priorice:**

- Reproducir con transcriber `openai` para descartar/confirmar la pista de faster-whisper.
- Loguear cada N segundos el estado de `dave_session` del `VoiceClient` (`dave_session is None`, versión de protocolo activa).
- Considerar reset proactivo del listener si `_log_stats` detecta stall confirmado (auto-recovery vs. fallar ruidoso — decisión de producto).

## DAVE E2EE

- discord.py 2.7+ incluye DAVE (Discord Audio-Visual Experience) E2EE para voz
- `discord-ext-voice-recv` NO soporta descifrado DAVE → audio es ruido, no silencio
- **Fix**: monkey-patch `_patch_disable_dave()` en `discord_listener.py` que fuerza `max_dave_protocol_version = 0`
- También hay `_patch_packet_router()` que hace PacketRouter resiliente a OpusError por paquete

## Recuperación de estado de sesión (zombie state)

El listener de Discord puede quedar desincronizado de la realidad: `is_connected() == True` pero el bot ya no está en el canal de voz. Síntoma típico: `/scribe start` responde **"Already recording!"** aunque el bot no esté en la sala.

Dos caminos lo causan, ambos cubiertos:

### A. Bot expulsado del canal (evento de gateway disponible)

`ScribeCog.on_voice_state_update` detecta cuando el bot deja un canal sin entrar a otro (`before.channel != None and after.channel is None`). Si había sesión activa (`self.session_id is not None`):

1. Limpia `self.listener` y `self.session_id` **sincrónicamente** antes de cualquier `await` — evita que un `/scribe start` paralelo vea estado inconsistente.
2. Lanza un `asyncio.create_task` para el `disconnect()` + `SessionEndRequestEvent` — no bloquea el handler del gateway, que de otra forma colaría detrás cualquier transcripción pendiente.

El guard mira `self.session_id`, **no** `listener.is_connected()`, para no saltarse el cleanup cuando `_periodic_flush` ya marcó `_connected = False` (ver B).

### B. Caída silenciosa de la conexión de voz (sin evento)

Cuando la WebSocket de voz muere pero el gateway no notifica (renegociación DAVE fallida, drop de red, etc.), `on_voice_state_update` no se dispara. `DiscordListener._periodic_flush` actúa como red de seguridad: cada 250 ms comprueba `self._voice_client.is_connected()`. Si devuelve `False`:

- Setea `self._connected = False` y rompe el loop
- Emite `WARNING` `"VoiceClient desconectado silenciosamente"`
- Publica `ListenerRecoverRequestEvent(reason="voice_silent_drop")` — un listener muerto no emite chunks, así que el stall detector del transcriber no lo notaría nunca.

### C. Reconexión automática con reintentos (`ScribeCog._recover_listener`)

Disparadores: stall del transcriber, caída silenciosa (B) y `on_resumed`/`on_ready` del gateway si hay sesión activa con el listener desconectado.

- Mantiene el mismo `session_id`. Hasta `_LISTENER_RECOVERY_MAX_ATTEMPTS` (20) intentos con backoff `5, 10, 20, 30, 60, 60…` s (~16 min).
- Antes de cada intento espera hasta 60 s a que el **gateway** esté vivo (`bot.ws.open`). `bot.is_ready()` no sirve: sigue `True` mientras discord.py reintenta el gateway. Reconectar la voz con el gateway caído falla con `ClientConnectionResetError('Cannot write to closing transport')` (incidente del 2026-10-23, Cloudflare 520/503 en `gateway-us-east1-d`).
- Limpia un `guild.voice_client` residual antes de reconectar (si no, "Already connected to a voice channel").
- Cooldown: 90 s si el listener sigue vivo (stall), 15 s si está muerto (solo anti-bucle).
- Agotados los intentos: `ERROR "🛑 Recovery agotado"` y se cierra la sesión limpiamente (`SessionEndRequestEvent`), así el resumen se finaliza.
- `/scribe stop` durante el recovery lo aborta en el siguiente punto de control.

### D. Expulsión manual vs. caída (`_handle_bot_voice_leave`)

Una expulsión manual (moderador → "Desconectar") **no** reconecta: cierra la sesión. Para distinguirla, al recibir `on_voice_state_update` de salida del bot se consulta el audit log (`member_disconnect`, hasta 3 s porque la entrada llega con retraso):

- La entrada no dice *a quién* se desconectó, solo `count`, y Discord agrupa desconexiones repetidas del mismo moderador incrementando `count`. Por eso se compara contra un baseline `{entry_id: count}` tomado en `/scribe start` y refrescado cada vez que un jugador sale del canal.
- Entrada nueva o `count` mayor → `👢 expulsado manualmente` → se cancela cualquier recovery en curso y se cierra la sesión.
- Sin cambios → caída → recovery (`reason=voice_state_leave`).
- Sin permiso **View Audit Log** → se trata como expulsión manual (comportamiento conservador) y se avisa en el log. **Dar ese permiso al rol del bot** para que las caídas reales se recuperen.
- Caída silenciosa (`voice_silent_drop`): el primer intento espera `_SILENT_DROP_GRACE_S` (5 s) para que una expulsión manual se detecte antes de que el bot vuelva a entrar.
- Limitación: si un moderador desconecta a otro jugador en los mismos ~3 s en que el bot cae, se interpreta como expulsión del bot (falla hacia "no reconectar").

Logs para seguir un incidente: `🔌 Gateway de Discord desconectado/resumed/ready`, `♻️ Recuperando…`, `⏳ Gateway de Discord caído…`, `❌ Intento N/M…`, `♻️ Reintento N/M… en Xs`, `✅ Listener recuperado…`, `🛑 Recovery agotado…`.

## Por qué dejan de salir transcripciones (diagnóstico diferencial)

"Se me cuelga la transcripción" tiene **tres causas distintas** con fixes opuestos. No las confundas: mira primero los marcadores de log para saber cuál es.

### Causa A — Stream de audio degradado (`voice_recv` entrega basura)

Los chunks siguen llegando como `near_silence` o `low_energy` aunque la gente esté hablando. **No es el filtro siendo agresivo** — `voice_recv` entrega audio corrupto (DAVE roto, jitter buffer, ...). Es el [bug abierto de arriba](#-bug-abierto-degradación-silenciosa-del-audio-en-sesiones-largas).

Marcadores en el log:

1. **Última alucinación** justo antes del silencio en logs INFO — es el "último audio real" antes de degradarse.
2. **`⚠️ Transcriber stall: N chunks received but no successful transcription in Xs`** — auto-emitido por `BaseTranscriber._log_stats` cuando hay chunks entrando pero ninguno produce texto en >`_STALL_WARNING_S` (30s).
3. **RMS bajo en la última alucinación** — el log de alucinaciones incluye `RMS=N speech=M%` para ver si el audio ya iba degradándose en ese chunk.
4. **Carpeta `logs/audio/discarded/<session_id>/`** con WAVs `_AUDIO_near_silence_` o `_AUDIO_low_energy_` — confirma que los chunks llegaban pero sin contenido real.

Fix: no está en el filtro ni en el transcriber — hay que reiniciar el listener (o dejar que actúe la recuperación automática).

### Causa B — Event loop bloqueado por un handler downstream (bot/TTS) — **arreglado**

`EventBus.publish` hace `await asyncio.gather(todos los handlers)`, así que **quien publica espera a todos sus suscriptores**. La cadena entera va en serie: `_periodic_flush` (ingesta de audio, bucle único) → `publish(AudioChunkEvent)` → `transcribe()` → `publish(TranscriptionEvent)` → `[summarizer, TriggerWatcher]`. Si un handler bloquea, la ingesta de audio se para **para todos los hablantes**.

El culpable era el `TriggerWatcher`: en la rama **close-word** ejecutaba `await self._finalize(...)` **inline dentro del handler del evento**, corriendo todo el pipeline del bot (RAG + Claude ≤30s + TTS + playback Discord) dentro del dispatch. **Fix (`bots/watcher.py`)**: la rama close-word ahora lanza `_finalize` con `asyncio.create_task`, igual que la rama timeout, para que ningún trabajo pesado del bot viva dentro del dispatch. Ver [`review-transcription-stall-close-word-fix.md`](review-transcription-stall-close-word-fix.md).

A diferencia de la Causa A, aquí **no** hay chunks descartados por RMS bajo: el audio es bueno pero nunca se procesa. Marcadores en el log (instrumentación añadida para estudiar esto):

1. **`⏱️ Flush loop bloqueado Xs`** (`discord_listener._periodic_flush`, umbral `_FLUSH_WARN_S` = 2s) — síntoma directo: la ingesta estuvo parada X segundos.
2. **`⏱️ publish(TranscriptionEvent) de '…' tardó Xs`** (`transcribers/base.py`, umbral `_PUBLISH_WARN_S` = 3s) — localiza el bloqueo como "downstream de la transcripción".
3. **`🎯 Trigger detectado` / `▶️ Finalize bot … inicio pipeline` / `✅ Finalize … pipeline total Xs`** (`bots/watcher.py`) con tiempos por etapa (`handle`, `TTS`, `playback`) — identifica al bot como causa y cuánto cuesta cada fase.

Si ves `⏱️ Flush loop bloqueado` **junto a** un `▶️ Finalize bot` con tiempos altos → es esta causa. Con el fix aplicado no debería reaparecer; si lo hace, hay otro handler pesado corriendo inline en el dispatch.

### Causa C — Freeze o muerte del proceso

El log se **corta en seco** estando sano (`last_success` bajo, contadores subiendo) y no vuelve a aparecer ninguna línea — ni siquiera los stats periódicos (cada `_STATS_INTERVAL_S` = 5s) ni `📊 Final transcriber stats`. Como `_periodic_stats` loguea incondicionalmente, la ausencia total de líneas nuevas = el proceso servidor se congeló o murió. Un detector server-side no puede avisar de esto (está muerto); solo el navegador lo nota (su WebSocket cae). Ver el diseño de la alarma en `docs/superpowers/specs/2026-07-11-transcription-stall-alarm-design.md`.

Fix: reiniciar el proceso. La alarma de navegador (en desarrollo) es la mitigación para enterarse a tiempo.

## faster-whisper y el event loop

`model.transcribe()` devuelve un **generador lazy**: la inferencia de GPU/CPU ocurre al iterar `segments`, no en la llamada inicial. Consumir el generador en el hilo del event loop bloquea asyncio durante toda la inferencia, afectando heartbeats del gateway y la tarea de flush del listener.

**Fix en `faster_whisper_transcriber.py`**: tanto `model.transcribe()` como la iteración del generador se ejecutan en `loop.run_in_executor`, manteniendo el event loop libre.

El transcriber `openai` no tiene este problema — usa `await` sobre HTTP, que cede al loop naturalmente.

## Playback (output) — narración por voz

Además de escuchar, el bot puede **hablar**: el botón "Narrar en Discord" del Web UI envía el TTS por el `VoiceClient` activo. El servicio responsable es `DiscordTTSPlayer` (`src/rpg_scribe/discord_bot/tts_player.py`), inyectado en `Application` durante el arranque del bot, igual que `DiscordSummaryPublisher`.

- El audio se obtiene de OpenAI como PCM 24 kHz mono y se resamplea a 48 kHz stereo en proceso con `numpy` (sin `ffmpeg`).
- Se envuelve como WAV de 48 kHz stereo y se cachea en `data/tts_cache/`. El mismo WAV sirve para el navegador y para Discord — el player lee el fichero, descarta los 44 bytes de header y pasa los bytes PCM crudos a `discord.PCMAudio`.
- El callback `after=` de `voice_client.play()` corre en un hilo del `AudioPlayer`. El bridge a asyncio se hace con `loop.call_soon_threadsafe(event.set)` para que el queue loop pueda usar `await event.wait()`.

Endpoints HTTP de control: `/api/tts/discord/{pause,resume,stop,play-at,status}`. Documentación completa del flujo en [`tts-narration.md`](tts-narration.md).

## Particularidades Windows

- asyncio ProactorEventLoop requiere `os._exit(0)` para SIGINT handler
- uvicorn signal handlers deben ser `lambda: None` (no `False`)
- Python 3.10: no tiene `tomllib` → se usa `tomli` como fallback
