# Audio Chunks — Diseño

## Objetivo

Guardar los fragmentos de audio que se envían a transcribir y permitir reproducirlos desde el Web UI junto a cada transcripción. Además, al iniciar sesión, logear el tamaño de las carpetas relevantes del proyecto.

## Estructura de archivos

```
data/
└── audio/
    └── {session_id}/
        ├── 1711234567.89_NombreJugador.wav
        ├── 1711234570.12_OtroJugador.wav
        └── ...
```

- **Carpeta raíz**: `data/audio/`
- **Subcarpeta por sesión**: `{session_id}/`
- **Nombre de archivo**: `{timestamp}_{speaker_name}.wav`
  - `timestamp`: Unix timestamp del chunk (mismo que `AudioChunkEvent.timestamp`)
  - `speaker_name`: Nombre del hablante (sanitizado para filesystem)
- **Formato**: WAV (16-bit, 48kHz, mono) — exactamente lo que se envía a OpenAI
- **Sin límite de espacio** — limpieza manual por el usuario

## Componentes

### A. Guardado de audio chunks (transcriber)

- **Dónde**: En `BaseTranscriber._handle_audio()`, justo antes de llamar a `transcribe()`
- **Qué**: Convertir el PCM del `AudioChunkEvent` a WAV y guardarlo en `data/audio/{session_id}/`
- **Nombre**: `{timestamp}_{speaker_name_sanitizado}.wav`
- **Creación de carpeta**: Crear `data/audio/{session_id}/` si no existe

### B. Mount estático en FastAPI

- **Dónde**: En `web/app.py`, montar `data/audio/` como ruta estática
- **URL**: `/audio/{session_id}/{filename}`
- **Implementación**: `app.mount("/audio", StaticFiles(directory="data/audio"), name="audio")`

### C. Botón de reproducción en frontend

- **Dónde**: En cada `feed-entry` del panel de transcripciones (`app.js`)
- **Posición**: A la derecha de cada transcripción, junto al timestamp
- **Comportamiento**: Click → reproduce el WAV correspondiente via `Audio()` API
- **Vinculación**: Por `timestamp` + `speaker_name` → construye URL `/audio/{session_id}/{timestamp}_{speaker}.wav`
- **CSS**: Botón discreto, estilo consistente con los botones existentes (M, ×)

### D. Log de tamaño de carpetas al iniciar sesión

- **Dónde**: En `Application.on_session_start()` o `_on_session_start_request()`
- **Carpetas a medir**:
  - `logs/` — logs generales
  - `exports/` — exportaciones
  - `data/audio/` — audio chunks guardados
- **Formato**: Log line con tamaño legible (KB/MB/GB)

## Paralelización

| Bloque | Independiente | Depende de |
|--------|--------------|------------|
| A (guardar WAV) | Sí | — |
| B (mount estático) | Sí (código) | A (archivos reales) |
| C (botón ▶ frontend) | Sí (código) | B (URLs) |
| D (log tamaños) | Sí | — |

**Fase 1** (paralelo): A + C + D
**Fase 2**: B (mount estático)
**Integración**: Conectar C con B (URL del audio en el botón)

## Notas

- El audio se guarda **antes** de transcribir — si la transcripción falla, el audio sigue disponible
- Los nombres de speaker se sanitizan para ser válidos en el filesystem (sin caracteres especiales)
- Si el archivo ya existe (mismo timestamp + speaker), se sobreescribe (no debería ocurrir en la práctica)
