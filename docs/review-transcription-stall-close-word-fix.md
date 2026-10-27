# Revisión independiente: fix de bloqueo de transcripción (close-word del bot)

**Fecha:** 2026-07-17
**Rama:** `feat/rules-bot-rag`
**Archivo cambiado:** `src/rpg_scribe/bots/watcher.py` (un único edit, solo en working tree)
**Objetivo de este documento:** que un revisor que parte de cero pueda auditar el cambio en paralelo.

## Contexto del proyecto (lo mínimo que necesitas saber)

RPG Scribe transcribe partidas de rol de Discord en tiempo real. Arquitectura
**async event-driven** sobre un `EventBus` pub/sub. Flujo:

```
Listener (Discord) → AudioChunkEvent → Transcriber → TranscriptionEvent → [Summarizer, TriggerWatcher]
```

El `EventBus` (`src/rpg_scribe/core/event_bus.py`) publica así:

```python
async def publish(self, event):
    ...
    await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
```

**Clave: `publish` await-ea a que TODOS los handlers terminen.** Por tanto, el que
publica queda bloqueado hasta que el más lento de sus suscriptores retorna.

La rama `feat/rules-bot-rag` añadió un `TriggerWatcher`
(`src/rpg_scribe/bots/watcher.py`) que se suscribe a **cada** `TranscriptionEvent`.
Detecta una keyword de bot en el habla, acumula chunks del mismo hablante, y al
cerrar la captura ejecuta `_finalize`, que corre el pipeline pesado del bot: RAG
(embeddings + búsqueda) + respuesta de Claude (acotada a 30 s con `wait_for`) +
síntesis TTS + reproducción en Discord.

## El bug que se está arreglando

La captura se cierra por dos vías:

- **Timeout** (silencio del hablante): ya lanzaba `_finalize` en segundo plano vía
  `asyncio.create_task` → no bloquea. ✅
- **Close-word** (el usuario dice la palabra de cierre): ejecutaba
  `await self._finalize(...)` **inline dentro de `_on_transcription`**, que es el
  handler del evento. ❌

Como `_on_transcription` es un handler de `TranscriptionEvent`, y `publish`
await-ea a sus handlers, ese `await _finalize` inline ejecutaba TODO el pipeline
del bot (hasta 30 s+) **dentro del dispatch del evento**. Eso propaga back-pressure
por toda la cadena:

```
_periodic_flush (listener, bucle único cada 0.25s, en serie)
  └─ await bus.publish(AudioChunkEvent)
       └─ transcriber._handle_audio → await bus.publish(TranscriptionEvent)
            └─ TriggerWatcher._on_transcription → await _finalize(...)  ← BLOQUEO 30s
```

Mientras `_finalize` corre inline, `_periodic_flush` (el bucle que vacía los
buffers de audio de Discord, `src/rpg_scribe/listeners/discord_listener.py`) está
parado y **no se emite audio de ningún hablante** → la transcripción se cuelga
varios segundos cada vez que alguien cierra una consulta al bot. Síntoma reportado
por el usuario: "se me cuelga mucho la transcripción".

El Summarizer, el otro suscriptor de `TranscriptionEvent`, NO tiene este problema
porque su handler solo hace `self._pending.append(...)` y retorna al instante; la
llamada a Claude corre en tarea de fondo aparte. Por eso el cuelgue es nuevo de
esta rama.

## El cambio a revisar

Un único edit en `src/rpg_scribe/bots/watcher.py`, dentro de `_on_transcription`,
rama close-word. Antes:

```python
if cap.timer is not None:
    cap.timer.cancel()
await self._finalize(key, ev, reason="close_word")
return
```

Después:

```python
if cap.timer is not None:
    cap.timer.cancel()
asyncio.create_task(
    self._finalize(key, ev, reason="close_word"),
    name=f"trigger-finalize-{cap.bot.keyword}",
)
return
```

(Con un comentario explicativo encima.) Es exactamente el mismo patrón que ya usa
la rama timeout.

## Qué verificar en la revisión

1. **Corrección del backgrounding**: `_finalize` (mismo archivo) hace
   `cap = self._captures.pop(key, None)` de primera línea y retorna si es `None`.
   Confirma que esto evita doble-disparo si el timer y el close-word compitieran.
   Nota: el timer ya se cancela antes del `create_task`.
2. **Referencias a `ev` y `key`**: la tarea de fondo captura `ev` (el
   `TranscriptionEvent`) y `key` (tupla `(session_id, speaker_id)`). Verifica que no
   hay condición de carrera con capturas nuevas del mismo `key` creadas mientras la
   tarea de fondo aún corre (una nueva captura reusa el mismo `key` en
   `self._captures`, pero la tarea de fondo ya hizo `pop` de la vieja).
3. **Tarea huérfana / fire-and-forget**: `create_task` sin guardar referencia puede
   ser recolectado por el GC en teoría. Evalúa si importa aquí (el timeout path
   tampoco guarda referencia del finalize; `cap.timer` sí se guarda). Excepciones
   dentro de `_finalize` ya se capturan internamente (bot.handle envuelto en
   try/except, TTS y playback también).
4. **Tests**: `tests/test_trigger_watcher.py` (19 tests) pasa. Los tests de
   close-word (`test_close_word_finalizes_immediately`, `test_close_word_across_chunks`)
   dependen de un `await asyncio.sleep(0.02)` tras publicar para dejar correr la
   tarea de fondo. Valora si ese margen es frágil (bot de test es in-memory y rápido,
   pero en teoría es timing-dependent).
5. **Regla del proyecto**: NO hacer commits (CLAUDE.md). El cambio debe quedar solo
   en working tree.

## Cómo reproducir/probar

```bash
cd C:/Users/Zartch/pythonProjects/Rpg-Scriber
python -m pytest tests/test_trigger_watcher.py -q      # 19 passed
git diff src/rpg_scribe/bots/watcher.py                # revisar el único cambio
```

## Posible crítica de fondo (fuera del alcance de este fix, pero válida señalarla)

El arreglo elimina el bloqueo del camino close-word, pero el problema estructural
persiste: `EventBus.publish` await-ea a sus handlers, así que la ingesta de audio
(`_periodic_flush`, bucle en serie) sigue serializada detrás de `transcribe()`
(~1-3 s por chunk de OpenAI). Un fix más robusto sería que el transcriber publique
`TranscriptionEvent` en fire-and-forget, o que el bus no await-ee handlers no
críticos. No es necesario para el síntoma actual, pero es la deuda de diseño
subyacente.
