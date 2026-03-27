# TTS Narration

## Arquitectura

- Pluggable: `BaseTTSProvider` ABC en `src/rpg_scribe/tts/base.py`
- Primer provider: OpenAI TTS (`tts-1` / `tts-1-hd`) en `tts/openai_provider.py`

## Caché

- Directorio: `data/tts_cache/`
- Clave: `sha256(text|provider|voice|model)`
- Escritura atómica (archivo temporal → rename)

## Endpoints

- `POST /api/tts/narrate` → NDJSON streaming, una línea por párrafo: `{index, total, audio_url, cached}`
- `GET /api/tts/cache/{hash}.mp3` → archivos mp3 desde `data/tts_cache/`
- `GET /api/tts/voices` → `{provider, voices, current}`, 503 si TTS deshabilitado

## Frontend

- Botón "Narrar" en session summary, chronology y campaign summary; oculto si TTS no está disponible
- Playback con cola: reproduce primer párrafo al llegar, encola el resto; toggle para detener

## Configuración TOML

Sección `[tts]` con campos: `enabled`, `provider`, `voice`, `model`, `cache_dir`

## Añadir un provider nuevo

Extender `BaseTTSProvider` e instanciar en `web/app.py` según `tts_config.provider`.
