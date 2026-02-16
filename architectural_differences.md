# Diferencias Arquitectónicas: Documento vs Implementación

Diferencias significativas entre `rpg-scribe-architecture.md` y el código fuente actual.

---

## 1. Funcionalidad No Implementada

### Comandos de Discord faltantes

El documento planifica 5 comandos slash. Solo 3 están implementados:

| Comando | Estado |
|---|---|
| `/scribe summary` — Ver resumen actual desde Discord | No implementado |
| `/scribe ask` — Responder preguntas del summarizer | No implementado |

### Sistema de preguntas al usuario (parcial)

El documento describe un sistema donde el summarizer puede formular preguntas al usuario (ej: "No quedó claro si el grupo aceptó la misión"). La base de datos tiene la tabla `questions` y los métodos CRUD existen, pero **no hay flujo completo**: el summarizer no genera preguntas activamente y la UI web no tiene un panel funcional para responderlas.

### Extracción automática de PNJs/localizaciones

El documento menciona que al finalizar una sesión, el sistema debería extraer automáticamente nuevos PNJs y localizaciones descubiertos. Esto no está implementado en `ClaudeSummarizer.finalize_session()`.

### Web UI: historial de sesiones

El documento planifica un selector de campaña/sesión y un historial de sesiones pasadas en el frontend. La implementación actual solo muestra la sesión activa (estado en memoria via `WebState`), sin endpoint REST para listar sesiones históricas desde el frontend.

---

## 2. Cambios de Dependencias

| Documento | Implementación | Razón |
|---|---|---|
| `pydub>=0.25` | No incluido | Reemplazado por `soundfile` + `numpy` |
| `webrtcvad>=2.0.10` | `webrtcvad-wheels>=2.0.10` | Versión precompilada (evita compilar C) |

---

## 3. Archivos Planificados No Creados

- **`config/default.toml`** — Configuración global por defecto. No existe; los defaults están hardcodeados en los dataclasses de `models.py`.
- **`scripts/import_campaign.py`** — Script para importar campañas. No existe.
- **`tests/fixtures/sample_audio/`** — Audio de prueba para tests. No existe; los tests usan audio generado en memoria.

---

## 4. Frontend: Tailwind vs CSS Vanilla

El documento especifica "vanilla HTML + JS + Tailwind CSS". La implementación usa CSS vanilla puro sin Tailwind. El frontend es funcional pero con estilos más básicos que los planificados.

---

## 5. Módulos Extra (no en el diagrama de estructura)

Los siguientes módulos fueron implementados pero no aparecen en el diagrama de estructura del documento (sección 9), aunque algunos se mencionan en el texto de fases posteriores:

- **`logging_config.py`** — Logging estructurado con structlog (salida JSON y consola)
- **`core/resilience.py`** — Retry con backoff, circuit breaker, reconnection manager
- **`discord_bot/publisher.py`** — Publicación de resúmenes como embeds en Discord
