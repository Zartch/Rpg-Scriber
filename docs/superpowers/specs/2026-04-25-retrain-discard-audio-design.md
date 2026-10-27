# Retrain & Discard Audio — Diseño

## Contexto

El Live Transcription feed muestra cada fragmento transcrito con botones [M] [×] a la izquierda y [▶] a la derecha. Se añade:

1. **Botón ✎ (retrain)**: edición inline del texto completo → copia el audio a una carpeta de reentrenamiento junto a un JSON de emparejado.
2. **Botón × mejorado (discard)**: antes de borrar la transcripción, mueve el audio a una carpeta de descarte.

## UI — Frontend (`transcription.js`)

### Layout por entrada

```
[M] [×]  Speaker: texto...  [▶] [✎]  12:34
```

### Flujo del botón ✎

1. Click → `.transcription-text` se reemplaza por `<textarea>` con el texto actual.
2. `✎` cambia a `✓`; aparece `✗` (cancelar).
3. **Guardar** (`✓` o Enter):
   - `PUT /api/transcriptions/{id}` — actualiza el texto (endpoint existente).
   - `POST /api/audio/{session_id}/{filename}/retrain` — copia wav + crea JSON.
   - Restaura el texto corregido en el timeline. La entrada permanece.
4. **Cancelar** (`✗` o Escape): restaura el texto original sin petición al servidor.

### Flujo del botón × mejorado

1. Confirm dialog (ya existe).
2. `POST /api/audio/{session_id}/{filename}/discard` — mueve el wav.
3. `DELETE /api/transcriptions/{id}` — borra la transcripción (ya existe).
4. Si el wav no existe (sesión de test, archivo ya movido), el discard no falla — el delete prosigue igualmente.

### Construcción de `filename`

Igual que la URL del botón ▶ ya existente:
```
{timestamp}_{speaker_sanitized}.wav
```
El frontend ya construye esta URL en `addTranscription()` — se reutiliza `entry.dataset`.

## Backend — Nuevos endpoints (`web/routers/audio.py`)

### `POST /api/audio/{session_id}/{filename}/retrain`

**Body JSON:**
```json
{
  "original": "texto original",
  "corrected": "texto corregido",
  "speaker": "NombreJugador",
  "timestamp": 1234567.89
}
```

**Acciones:**
- Copia `data/audio/{session_id}/{filename}` → `data/audio/retrain/{session_id}/{filename}`.
- Crea `data/audio/retrain/{session_id}/{stem}.json` con el body recibido.
- Crea subcarpeta si no existe.

**Respuestas:** 200 OK | 404 si el wav origen no existe.

---

### `POST /api/audio/{session_id}/{filename}/discard`

**Body:** vacío.

**Acciones:**
- Mueve `data/audio/{session_id}/{filename}` → `data/audio/discard/{session_id}/{filename}`.
- Crea subcarpeta si no existe.
- Idempotente: si el archivo ya está en discard (o no existe), responde 200.

**Respuestas:** 200 OK.

---

### Cambio en `DELETE /api/transcriptions/{id}`

Antes de borrar la transcripción, invoca internamente la lógica de discard construyendo el filename igual que el frontend:
```
filename = f"{transcription.timestamp}_{sanitize(transcription.speaker_name)}.wav"
# sanitize: re.sub(r'\W', '_', name)[:30]
```
Si el wav no existe, continúa sin error.

## Estructura de archivos

```
data/audio/
├── {session_id}/           ← audio original (ya existe, sin cambios)
├── retrain/
│   └── {session_id}/
│       ├── {ts}_{speaker}.wav
│       └── {ts}_{speaker}.json
└── discard/
    └── {session_id}/
        └── {ts}_{speaker}.wav
```

`retrain/` y `discard/` son carpetas offline — no se sirven al browser, no requieren montaje estático.

## Resumen de cambios

| Capa | Cambio |
|---|---|
| `web/routers/audio.py` | Nuevo router: 2 endpoints POST |
| `web/app.py` | Registrar `audio` router |
| `web/routers/transcriptions.py` | `DELETE` llama a lógica discard antes de borrar |
| `web/static/js/transcription.js` | Botón ✎ + edición inline + llamada retrain |
| `web/static/js/transcription.js` | Botón × llama a discard antes de delete |

Sin cambios en: DB, modelos de datos, CSS global, otros routers.
