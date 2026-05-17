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

El próximo `/scribe start` ya no choca con el guard de "Already recording". El path `on_voice_state_update` cubre el cleanup completo si el gateway finalmente lo reporta.

**Limitación conocida**: si el gateway tampoco dispara nunca el evento de salida, la sesión vieja queda huérfana — no se publica `SessionEndRequestEvent`, el summarizer no finaliza. Aceptable porque en ese caso el bot está esencialmente offline y hace falta un restart de todos modos.

## Stream de audio degradado vs. transcriber colgado

Síntoma confuso: deja de haber transcripciones pero los chunks siguen llegando como `near_silence` o `low_energy` aunque la gente esté hablando. **No es el filtro siendo agresivo** — es que `voice_recv` está entregando audio basura (DAVE roto, jitter buffer corrupto, ...).

Marcadores en el log que confirman este patrón:

1. **Última alucinación** justo antes del silencio en logs INFO — es el "último audio real" antes de degradarse.
2. **`⚠️ Transcriber stall: N chunks received but no successful transcription in Xs`** — auto-emitido por `BaseTranscriber._log_stats` cuando hay chunks entrando pero ninguno produce texto en >120s.
3. **RMS bajo en la última alucinación** — el log de alucinaciones incluye `RMS=N speech=M%` para ver si el audio ya iba degradándose en ese chunk.
4. **Carpeta `logs/audio/discarded/<session_id>/`** con WAVs `_AUDIO_near_silence_` o `_AUDIO_low_energy_` — confirma que los chunks llegaban pero sin contenido real.

Si confirmas este patrón, el fix no está en el filtro ni en el transcriber: hay que reiniciar el listener.

## faster-whisper y el event loop

`model.transcribe()` devuelve un **generador lazy**: la inferencia de GPU/CPU ocurre al iterar `segments`, no en la llamada inicial. Consumir el generador en el hilo del event loop bloquea asyncio durante toda la inferencia, afectando heartbeats del gateway y la tarea de flush del listener.

**Fix en `faster_whisper_transcriber.py`**: tanto `model.transcribe()` como la iteración del generador se ejecutan en `loop.run_in_executor`, manteniendo el event loop libre.

El transcriber `openai` no tiene este problema — usa `await` sobre HTTP, que cede al loop naturalmente.

## Particularidades Windows

- asyncio ProactorEventLoop requiere `os._exit(0)` para SIGINT handler
- uvicorn signal handlers deben ser `lambda: None` (no `False`)
- Python 3.10: no tiene `tomllib` → se usa `tomli` como fallback
