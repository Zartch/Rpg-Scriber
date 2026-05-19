# TTS Narration

## Arquitectura

- Pluggable: `BaseTTSProvider` ABC en `src/rpg_scribe/tts/base.py`
- Primer provider: OpenAI TTS (`tts-1` / `tts-1-hd`) en `tts/openai_provider.py`
- `synthesize(text, voice, response_format)` — el endpoint web pide `"pcm"` (raw 24 kHz mono int16 LE) y resamplea en proceso

## Dos modos de reproducción, una sola caché

| Modo | Botón | Driver |
|------|-------|--------|
| Navegador | "🔊 Narrar" | HTML5 `<audio>` |
| Discord | "🎤 Narrar en Discord" | `voice_client.play()` |

Ambos modos comparten **el mismo fichero en caché**. La pieza clave es que el formato canónico es WAV 48 kHz stereo int16 LE:

- El navegador reproduce el WAV directamente.
- Discord lee el WAV, descarta los 44 bytes de header y mete los bytes PCM en `discord.PCMAudio`.

Resultado: si un párrafo ya se generó para uno de los dos modos, el otro no llama a OpenAI.

## Pipeline de generación

```
OpenAI TTS (response_format="pcm", 24 kHz mono)
  → pcm_24k_mono_to_48k_stereo()         numpy interp 1× → 2×, mono → stereo intercalado
    → wrap_pcm_as_wav()                  header WAV de 44 bytes
      → cache.put(key, wav_bytes)        atomic write a data/tts_cache/{hash}.wav
```

Sin `ffmpeg`, sin `scipy`. Solo `numpy`. Helpers en `tts/audio_utils.py`.

## Caché

- Directorio: `data/tts_cache/`
- Extensión: `.wav` (parametrizable en `TTSCache(extension=...)`)
- Clave: `sha256(text|provider|voice|model)` — idéntica entre modos, por eso la comparten
- Escritura atómica (archivo temporal → rename)

Para verificar hits/misses en runtime, los logs marcan cada chunk:

```
narrate(web)     cache HIT  key=a3f8...
narrate(discord) cache HIT  key=a3f8...
narrate(web)     cache MISS key=e91b... → OpenAI synth
```

Si dos llamadas sobre el mismo texto producen `key=` distintos, algo mutó el texto entre clicks (suele ser un update WebSocket que reescribió el párrafo).

## Endpoints

### Genéricos
- `POST /api/tts/narrate` → NDJSON, una línea por chunk: `{index, total, audio_url, cached}`
- `GET /api/tts/cache/{hash}.wav` → archivos WAV servidos como estáticos desde `data/tts_cache/`
- `GET /api/tts/voices` → `{provider, voices, current}`, 503 si TTS deshabilitado

### Discord
- `POST /api/tts/narrate-discord` → NDJSON con los chunks listos + línea final `{status: "started"}`. La reproducción la maneja el `DiscordTTSPlayer` en background; el endpoint devuelve enseguida.
- `POST /api/tts/discord/pause` / `/resume` / `/stop`
- `POST /api/tts/discord/play-at` con `{"index": N}` — saltar a un chunk concreto
- `GET /api/tts/discord/status` → `{connected, total, index, playing, paused, active}`. Devuelve `{connected: false}` (no 409) si el bot no está en un canal de voz, para que el frontend pueda hacer polling sin spamear errores.

Códigos de error:
- 503: TTS deshabilitado en config
- 409: el bot no está en un canal de voz (solo endpoints `/discord/*`)
- 400: `text` vacío o `index` fuera de rango

## DiscordTTSPlayer

`src/rpg_scribe/discord_bot/tts_player.py`. Servicio inyectado en `Application` durante `_start_discord_bot()` (mismo patrón que `DiscordSummaryPublisher`).

Estado interno: `queue` (paths a `.wav`), `index` actual, tarea de fondo opcional.

Métodos:

- `get_voice_client()` — descubre el `VoiceClient` recorriendo `bot.cogs[*].listener._voice_client`. No acopla al nombre de la cog.
- `start_queue(wav_paths)` — reemplaza la cola y empieza la reproducción.
- `pause()` / `resume()` — proxys a `voice_client.pause/resume()`.
- `stop()` — cancela la tarea y limpia la cola.
- `play_at(index)` — fija `_jump_to = index` y llama `voice_client.stop()`. El callback `after` del chunk actual despierta el loop, que mira `_jump_to` antes de avanzar.

Bridge thread→asyncio: el callback `after` de discord.py corre en un hilo del `AudioPlayer`. Cada chunk arma un `asyncio.Event` y el callback hace `loop.call_soon_threadsafe(event.set)`. La coroutine espera con `await event.wait()`. Sin esto se rompe con `ClientException("Already playing audio.")`.

## Frontend

- Botones en session summary, chronology y campaign summary (ocultos si TTS no disponible)
- Botón hermano "Narrar en Discord" solo para session (los otros dos se replicarían igual)
- **Botonera compartida**: `_createNarrateControls(btn, driver)` recibe un driver con `prev/next/restart/pauseResume`. Dos drivers en `web/static/js/tts.js`:
  - `browserDriver` — HTML5 Audio
  - `discordDriver` — llama a los endpoints HTTP de control
- Cuando el driver es Discord, el frontend pollea `/api/tts/discord/status` cada 1 s para mantener el índice y el estado de pausa sincronizados con el servidor

## Configuración TOML

Sección `[tts]` con campos: `enabled`, `provider`, `voice`, `model`, `cache_dir`

## Añadir un provider nuevo

Extender `BaseTTSProvider` (la firma incluye `response_format`) e instanciar en `web/app.py` según `tts_config.provider`. El provider debe ser capaz de devolver al menos `"pcm"` para que funcione el modo Discord.
