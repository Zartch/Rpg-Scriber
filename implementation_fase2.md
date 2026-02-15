# Plan de Implementación — Fase 2 (Funcionalidad Pendiente)

Este documento detalla las funcionalidades que faltan por implementar según el documento de arquitectura (`rpg-scribe-architecture.md`) y el análisis de diferencias (`architectural_differences.md`). Está organizado en subfases incrementales para que cada una sea abordable de forma independiente.

---

## Estado Actual

Lo que **ya funciona**:
- Core completo: Event Bus, eventos tipados, modelos, base de datos, configuración TOML
- Discord Listener con VAD, chunking y captura de audio por usuario
- Transcriber (OpenAI API + faster-whisper local)
- Summarizer con doble resumen (sesión + campaña) y clasificación in-game/meta
- Web UI con dashboard en tiempo real (transcripciones + resúmenes via WebSocket)
- Discord Bot con `/scribe start`, `/scribe stop`, `/scribe status`
- Publisher de resúmenes como embeds en Discord
- Sistema de resiliencia (retry, circuit breaker, reconnection)
- Logging estructurado con structlog
- Suite de 14 archivos de tests

Lo que **falta**:
- Sistema de preguntas al usuario (infraestructura existe pero sin conexión con la IA)
- Extracción automática de PNJs/localizaciones al finalizar sesión
- Comandos Discord `/scribe summary` y `/scribe ask`
- Historial de sesiones en Web UI
- Selector de campañas/sesiones en frontend
- `config/default.toml`
- `scripts/import_campaign.py`

---

## Fase 2A — Sistema de Preguntas del Summarizer

**Objetivo**: Que el summarizer pueda generar preguntas cuando algo no le queda claro, y que el usuario pueda responderlas desde la web o Discord.

**Contexto**: La infraestructura ya existe parcialmente:
- DB: tabla `questions` con métodos `save_question()`, `answer_question()`, `get_pending_questions()`
- Web API: endpoints `GET /api/questions` y `POST /api/questions/{id}/answer`
- Frontend: panel de preguntas con formulario de respuesta y polling cada 5s
- Summarizer: el prompt ya menciona `[PREGUNTA: ...]` como marcador

### Tareas

#### 2A.1 — Parsear preguntas de la respuesta del summarizer
**Archivo**: `src/rpg_scribe/summarizers/claude_summarizer.py`

El summarizer ya pide al LLM que marque dudas con `[PREGUNTA: ...]`. Falta:
1. Tras recibir la respuesta del LLM en `_update_summary()`, parsear el texto buscando patrones `[PREGUNTA: ...]`
2. Extraer el texto de cada pregunta
3. Guardarlas en la DB via `database.save_question(session_id, question_text)`
4. Opcionalmente limpiar los marcadores `[PREGUNTA: ...]` del resumen final para que no aparezcan en la UI

```python
# Pseudocódigo del parser
import re

def _extract_questions(self, summary_text: str, session_id: str) -> str:
    pattern = r'\[PREGUNTA:\s*(.+?)\]'
    questions = re.findall(pattern, summary_text)
    for q in questions:
        await self.database.save_question(session_id, q)
    # Devolver el resumen limpio (sin marcadores)
    return re.sub(pattern, '', summary_text).strip()
```

#### 2A.2 — Inyectar respuestas en el contexto del summarizer
**Archivo**: `src/rpg_scribe/summarizers/claude_summarizer.py`

Cuando el usuario responde una pregunta:
1. Antes de cada llamada al LLM, consultar `database.get_pending_questions()` para obtener las respondidas recientemente
2. Incluir las respuestas en la sección de contexto del prompt: `RESPUESTAS DEL USUARIO: ...`
3. Esto permite al summarizer incorporar la aclaración en el siguiente ciclo de resumen

Necesitará un nuevo método en la DB o una query para obtener preguntas respondidas pero aún no procesadas. Añadir un campo `processed` a la tabla `questions` o filtrar por `answered_at` reciente.

#### 2A.3 — Tests
**Archivo**: `tests/test_summarizer.py` (ampliar)

- Test de extracción de preguntas del texto
- Test de que las preguntas se guardan en DB
- Test de que el resumen devuelto está limpio de marcadores

---

## Fase 2B — Extracción Automática de PNJs y Localizaciones

**Objetivo**: Al finalizar una sesión, extraer automáticamente los PNJs nuevos y localizaciones descubiertos.

### Tareas

#### 2B.1 — Métodos CRUD para NPCs en la base de datos
**Archivo**: `src/rpg_scribe/core/database.py`

La tabla `npcs` existe pero no tiene métodos. Añadir:

```python
async def save_npc(self, campaign_id: str, name: str, description: str, first_seen_session: str) -> None: ...
async def get_npcs(self, campaign_id: str) -> list[dict]: ...
async def npc_exists(self, campaign_id: str, name: str) -> bool: ...
```

#### 2B.2 — Prompt de extracción en `finalize_session()`
**Archivo**: `src/rpg_scribe/summarizers/claude_summarizer.py`

Tras generar el resumen final de sesión, hacer una segunda llamada al LLM pidiendo:
1. Lista de PNJs nuevos mencionados que no estén en `known_npcs`
2. Lista de localizaciones nuevas visitadas
3. Formato estructurado (JSON) para facilitar el parseo

```python
# Prompt de extracción (segunda llamada al finalizar)
EXTRACTION_PROMPT = """
Basándote en la transcripción y resumen de esta sesión, extrae:

PNJs CONOCIDOS (no incluir estos):
{known_npcs}

Responde SOLO con JSON válido:
{
  "new_npcs": [{"name": "...", "description": "..."}],
  "new_locations": [{"name": "...", "description": "..."}]
}

Si no hay nuevos PNJs o localizaciones, devuelve listas vacías.
"""
```

#### 2B.3 — Guardar PNJs extraídos en la DB
**Archivo**: `src/rpg_scribe/summarizers/claude_summarizer.py`

Parsear la respuesta JSON y guardar cada PNJ nuevo con `database.save_npc()`.

#### 2B.4 — Tests
**Archivos**: `tests/test_summarizer.py`, `tests/test_database.py` (ampliar)

- Test de CRUD de NPCs en DB
- Test de parseo de la respuesta JSON de extracción
- Test de `finalize_session()` completo con mock del LLM

---

## Fase 2C — Comandos Discord: `/scribe summary` y `/scribe ask`

**Objetivo**: Poder consultar el resumen y responder preguntas directamente desde Discord.

### Tareas

#### 2C.1 — Comando `/scribe summary`
**Archivo**: `src/rpg_scribe/discord_bot/commands.py`

Añadir subcomando `summary` al grupo `/scribe`:
1. Obtener el `session_id` activo del listener
2. Consultar el resumen actual via la DB o el WebState
3. Responder con un embed formateado (usar el estilo del publisher)
4. Si el resumen es demasiado largo (>4096 chars para embed), truncar con "..." y sugerir ver la web

```python
@scribe_group.command(name="summary", description="Ver el resumen actual de la sesión")
async def summary(self, interaction: discord.Interaction):
    # Obtener resumen del WebState o DB
    # Formatear como embed
    # Responder
```

#### 2C.2 — Comando `/scribe ask`
**Archivo**: `src/rpg_scribe/discord_bot/commands.py`

Dos opciones de diseño (elegir una):

**Opción A — Listar y responder inline**: El comando muestra las preguntas pendientes como botones/select menu. El usuario selecciona una y responde con un modal.

**Opción B — Respuesta directa**: `/scribe ask` muestra la primera pregunta pendiente con un modal para responder.

Recomendación: **Opción B** por simplicidad. Si no hay preguntas pendientes, informar al usuario.

```python
@scribe_group.command(name="ask", description="Responder preguntas del cronista")
async def ask(self, interaction: discord.Interaction):
    # Obtener primera pregunta pendiente de la DB
    # Si no hay, responder "No hay preguntas pendientes"
    # Si hay, mostrar un Modal con la pregunta y campo de respuesta
    # Al enviar, guardar respuesta con database.answer_question()
```

#### 2C.3 — Tests
**Archivo**: `tests/test_discord_bot.py` (ampliar o crear)

- Test de que el comando summary devuelve el resumen actual
- Test de que el comando ask muestra preguntas pendientes
- Test de respuesta a preguntas via Discord

---

## Fase 2D — Historial de Sesiones (Backend + Frontend)

**Objetivo**: Poder ver sesiones pasadas con sus transcripciones y resúmenes desde la Web UI.

### Tareas

#### 2D.1 — Endpoint REST para listar sesiones
**Archivo**: `src/rpg_scribe/web/routes.py`

Añadir endpoint:

```python
@router.get("/api/campaigns/{campaign_id}/sessions")
async def list_sessions(campaign_id: str):
    # Usar database.list_sessions(campaign_id)
    # Devolver lista con id, started_at, ended_at, status, resumen truncado
```

El método `list_sessions()` ya existe en la DB. Solo falta exponerlo como API.

#### 2D.2 — Selector de sesiones en el frontend
**Archivo**: `src/rpg_scribe/web/static/index.html`

Añadir un `<select>` o panel lateral con la lista de sesiones:
- Sesión activa marcada visualmente
- Sesiones completadas con fecha y resumen corto
- Al seleccionar una sesión, cargar sus transcripciones y resumen

#### 2D.3 — Lógica de carga de sesión histórica en JS
**Archivo**: `src/rpg_scribe/web/static/app.js`

- Al seleccionar una sesión pasada, hacer `fetch('/api/sessions/{id}/transcriptions')` y `fetch('/api/sessions/{id}/summary')`
- Mostrar los datos en los paneles existentes
- Desactivar el WebSocket live cuando se ve una sesión histórica (reactivar al volver a la sesión activa)

#### 2D.4 — Tests
**Archivo**: `tests/test_web.py` (ampliar)

- Test del endpoint de listado de sesiones
- Test de que devuelve sesiones ordenadas por fecha

---

## Fase 2E — Archivos Auxiliares

**Objetivo**: Crear los archivos de soporte planificados en el documento de arquitectura.

### Tareas

#### 2E.1 — `config/default.toml`
**Archivo**: `config/default.toml`

Configuración global por defecto que actualmente está hardcodeada en los dataclasses de `models.py`:

```toml
[listener]
chunk_duration_sec = 10
silence_threshold_sec = 1.5
vad_aggressiveness = 2

[transcriber]
provider = "openai"          # "openai" | "faster-whisper"
language = "es"
max_concurrent = 3

[summarizer]
provider = "claude"
update_interval_sec = 120    # cada 2 minutos
max_buffer_entries = 20

[web]
host = "127.0.0.1"
port = 8000

[database]
path = "rpg_scribe.db"
```

Modificar `src/rpg_scribe/config.py` para:
1. Cargar `config/default.toml` como base
2. Sobreescribir con el TOML de campaña
3. Sobreescribir con variables de entorno

#### 2E.2 — `scripts/import_campaign.py`
**Archivo**: `scripts/import_campaign.py`

Script interactivo para crear/importar configuraciones de campaña:
1. Pedir nombre, sistema de juego, idioma, descripción
2. Pedir datos de jugadores (discord_id, nombre, personaje)
3. Generar archivo TOML en `config/campaigns/`
4. Opcionalmente insertar en la DB

```bash
# Uso esperado
python scripts/import_campaign.py
# O con argumentos
python scripts/import_campaign.py --name "Mi Campaña" --system "D&D 5e" --output config/campaigns/mi-campana.toml
```

#### 2E.3 — Tests
- Test de carga de `default.toml` con merge de configuraciones

---

## Fase 2F — Mejoras de Frontend (Opcional)

**Objetivo**: Mejorar la UI para acercarnos al diseño planificado.

> Esta fase es opcional y de menor prioridad. El frontend actual es funcional con CSS vanilla. Estas mejoras son cosméticas.

### Tareas

#### 2F.1 — Migrar a Tailwind CSS (opcional)
Si se desea seguir el documento original. Alternativa: quedarse con el CSS vanilla actual y solo mejorar los estilos existentes.

#### 2F.2 — Panel de preguntas mejorado
Actualmente el panel de preguntas funciona pero está vacío porque el summarizer no genera preguntas. Tras implementar la Fase 2A, verificar que el panel se actualiza correctamente y mejorar la UX si es necesario.

#### 2F.3 — Indicadores de latencia
Añadir al panel de estado los tiempos de respuesta de cada componente (latencia del transcriber, del summarizer, etc.). Los `SystemStatusEvent` ya se emiten, solo falta extraer/mostrar métricas de tiempo.

---

## Orden Recomendado de Implementación

```
Fase 2A (Preguntas)          ← Conectar infraestructura existente, impacto alto
    │
    ├── Fase 2C (Discord commands) ← Depende parcialmente de 2A para /scribe ask
    │
Fase 2B (Extracción PNJs)    ← Independiente, mejora la experiencia de finalización
    │
Fase 2D (Historial sesiones) ← Independiente, mejora usabilidad de la web
    │
Fase 2E (Archivos auxiliares) ← Independiente, mejora mantenibilidad
    │
Fase 2F (UI polish)          ← Opcional, hacer al final
```

Las fases 2A, 2B, 2D y 2E son independientes entre sí y se pueden hacer en cualquier orden. La 2C depende parcialmente de 2A (para `/scribe ask`), pero `/scribe summary` se puede hacer antes.

---

## Criterios de Verificación por Fase

| Fase | Verificación |
|---|---|
| 2A | Ejecutar el summarizer con transcripciones de ejemplo → aparecen preguntas en la web UI → se pueden responder → la respuesta aparece en el contexto del siguiente ciclo |
| 2B | Ejecutar `finalize_session()` → la DB contiene PNJs nuevos extraídos automáticamente |
| 2C | En Discord, `/scribe summary` muestra el resumen actual; `/scribe ask` permite responder preguntas |
| 2D | En la web, se puede seleccionar una sesión pasada y ver sus transcripciones y resumen |
| 2E | `config/default.toml` se carga como base y se puede sobreescribir; `import_campaign.py` genera un TOML válido |
| 2F | La UI se ve mejor visualmente; los indicadores de latencia funcionan |

---

## Notas para Claude Code

- **Leer antes de modificar**: siempre leer el archivo completo antes de editarlo.
- **Tests primero**: cada fase debe incluir tests que validen la funcionalidad.
- **No romper lo existente**: ejecutar `pytest` tras cada fase para asegurar que nada se ha roto.
- **Commits por subfase**: un commit por cada subfase completada (2A.1, 2A.2, etc.) o al menos uno por fase completa.
- **Respetar convenciones**: `from __future__ import annotations`, async/await, frozen dataclasses para eventos, ABC para interfaces.

---

## Prompts Recomendados para Claude Code

Copiar y pegar el prompt correspondiente a la fase que se quiera implementar. Cada prompt está diseñado para dar suficiente contexto sin necesidad de explicaciones adicionales.

---

### Fase 2A — Sistema de Preguntas

```
Lee los documentos rpg-scribe-architecture.md (sección 6.4),
architectural_differences.md e implementation_fase2.md (Fase 2A).

Implementa el sistema de preguntas del summarizer:

1. En claude_summarizer.py, tras recibir la respuesta del LLM en
   _update_summary(), parsea el texto buscando marcadores [PREGUNTA: ...].
   Extrae cada pregunta y guárdala en la DB con database.save_question().
   Limpia los marcadores del resumen antes de publicarlo.

2. Antes de cada llamada al LLM, consulta las preguntas respondidas
   recientemente (answered pero no procesadas) y añádelas al contexto
   del prompt como "RESPUESTAS DEL USUARIO: ...". Considera añadir un
   campo 'processed' a la tabla questions o filtrar por answered_at.

3. Crea tests en tests/test_summarizer.py:
   - Test de extracción de preguntas del texto
   - Test de que las preguntas se guardan en DB
   - Test de que el resumen queda limpio de marcadores
   - Test de inyección de respuestas en el contexto

Ejecuta pytest al terminar para verificar que no se ha roto nada.
Haz commit con un mensaje descriptivo.
```

---

### Fase 2B — Extracción de PNJs y Localizaciones

```
Lee los documentos rpg-scribe-architecture.md (secciones 6.4 y 8.1),
architectural_differences.md e implementation_fase2.md (Fase 2B).

Implementa la extracción automática de PNJs y localizaciones al
finalizar sesión:

1. En database.py, añade métodos CRUD para la tabla npcs:
   - save_npc(campaign_id, name, description, first_seen_session)
   - get_npcs(campaign_id) -> list[dict]
   - npc_exists(campaign_id, name) -> bool

2. En claude_summarizer.py, modifica finalize_session() para que tras
   generar el resumen final, haga una segunda llamada al LLM pidiendo
   extraer PNJs y localizaciones nuevas en formato JSON. El prompt debe
   incluir la lista de PNJs ya conocidos para no duplicar.
   Parsea la respuesta JSON y guarda los nuevos PNJs con save_npc().

3. Crea tests:
   - Tests de CRUD de NPCs en tests/test_database.py
   - Test de parseo JSON de extracción en tests/test_summarizer.py
   - Test de finalize_session() completo con mock del LLM

Ejecuta pytest al terminar. Haz commit con un mensaje descriptivo.
```

---

### Fase 2C — Comandos Discord `/scribe summary` y `/scribe ask`

```
Lee los documentos rpg-scribe-architecture.md (sección 7.3),
architectural_differences.md e implementation_fase2.md (Fase 2C).

Lee primero src/rpg_scribe/discord_bot/commands.py para ver los
comandos existentes (start, stop, status) y seguir el mismo patrón.

Implementa dos comandos nuevos:

1. /scribe summary:
   - Obtener el session_id activo
   - Consultar el resumen actual de la sesión (via DB o WebState)
   - Responder con un embed de Discord formateado
   - Si el resumen supera 4096 chars, truncar con indicación
     de que se puede ver completo en la web

2. /scribe ask:
   - Consultar la primera pregunta pendiente con
     database.get_pending_questions()
   - Si no hay preguntas, responder "No hay preguntas pendientes"
   - Si hay, mostrar un discord.ui.Modal con la pregunta y un
     campo de texto para la respuesta
   - Al enviar, guardar con database.answer_question()

3. Tests en tests/test_discord_bot.py (ampliar si existe, crear si no):
   - Test del comando summary
   - Test del comando ask con y sin preguntas pendientes

Ejecuta pytest al terminar. Haz commit con un mensaje descriptivo.
```

---

### Fase 2D — Historial de Sesiones

```
Lee implementation_fase2.md (Fase 2D) y luego lee los archivos:
- src/rpg_scribe/web/routes.py
- src/rpg_scribe/web/static/index.html
- src/rpg_scribe/web/static/app.js
- src/rpg_scribe/web/static/style.css
- src/rpg_scribe/core/database.py (método list_sessions)

Implementa el historial de sesiones:

1. Backend — en routes.py añade:
   GET /api/campaigns/{campaign_id}/sessions
   que llame a database.list_sessions() y devuelva la lista con
   id, started_at, ended_at, status y resumen truncado (primeros
   150 chars).

2. Frontend — en index.html:
   Añade un panel lateral o un <select> para elegir sesión.
   La sesión activa debe estar marcada visualmente.
   Las sesiones completadas muestran fecha y fragmento del resumen.

3. Frontend — en app.js:
   Al seleccionar una sesión pasada, hacer fetch de sus
   transcripciones y resumen y mostrarlos en los paneles existentes.
   Desactivar la actualización via WebSocket cuando se ve una sesión
   histórica. Reactivar al volver a la sesión activa.

4. Tests en tests/test_web.py:
   - Test del endpoint de listado de sesiones
   - Test de que devuelve sesiones ordenadas por fecha

Ejecuta pytest al terminar. Haz commit con un mensaje descriptivo.
```

---

### Fase 2E — Archivos Auxiliares

```
Lee implementation_fase2.md (Fase 2E) y luego lee:
- src/rpg_scribe/config.py
- src/rpg_scribe/core/models.py (para ver los defaults hardcodeados)
- config/campaigns/example.toml

Implementa los archivos auxiliares:

1. Crea config/default.toml con los valores por defecto del sistema:
   listener (chunk_duration, silence_threshold, vad_aggressiveness),
   transcriber (provider, language, max_concurrent),
   summarizer (provider, update_interval, max_buffer),
   web (host, port), database (path).
   Extrae los valores actuales de los dataclasses de models.py.

2. Modifica config.py para cargar default.toml como base,
   sobreescribir con el TOML de campaña, y finalmente sobreescribir
   con variables de entorno. Mantener retrocompatibilidad: si
   default.toml no existe, usar los defaults actuales de models.py.

3. Crea scripts/import_campaign.py:
   Script interactivo que pide nombre, sistema de juego, idioma,
   descripción, datos de jugadores (discord_id, nombre, personaje),
   y PNJs iniciales. Genera un archivo TOML en config/campaigns/.
   Soportar también modo no interactivo con argumentos CLI
   (--name, --system, --output).

4. Tests:
   - Test de carga de default.toml con merge de configuraciones
   - Test de que sin default.toml sigue funcionando

Ejecuta pytest al terminar. Haz commit con un mensaje descriptivo.
```

---

### Fase 2F — Mejoras de Frontend (Opcional)

```
Lee implementation_fase2.md (Fase 2F) y luego lee los archivos
del frontend en src/rpg_scribe/web/static/.

Esta fase es opcional y cosmética. Elige qué mejoras aplicar:

1. (Opcional) Migrar a Tailwind CSS o mejorar los estilos vanilla
   existentes. Si se usa Tailwind, añadir via CDN en index.html
   para no complicar el build.

2. Mejorar el panel de preguntas: añadir indicador visual cuando
   hay preguntas nuevas (badge/contador), mejorar el formulario
   de respuesta con feedback al usuario.

3. Añadir indicadores de latencia al panel de estado: mostrar
   el tiempo de respuesta del transcriber y summarizer. Los
   SystemStatusEvent ya contienen timestamps, solo falta calcular
   y mostrar los deltas.

No es necesario hacer las tres. Elige las que aporten más valor.
Ejecuta pytest al terminar. Haz commit con un mensaje descriptivo.
```
