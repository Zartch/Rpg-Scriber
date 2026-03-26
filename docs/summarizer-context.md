# Summarizer: Generación de Resúmenes y Contexto

Documento de referencia sobre cómo el summarizer genera resúmenes, qué contexto recibe y de dónde se obtiene cada dato.

## Archivo principal

`src/rpg_scribe/summarizers/claude_summarizer.py`

## Tipos de resumen

El summarizer genera **tres productos** distintos:

| Producto | Cuándo | Prompt system | Prompt user |
|----------|--------|---------------|-------------|
| **Resumen de sesión (incremental)** | Cada N transcripciones durante la sesión | `SESSION_SYSTEM_PROMPT` | `SESSION_UPDATE_USER` |
| **Resumen de sesión (final)** | Al finalizar la sesión | `SESSION_SYSTEM_PROMPT` | `FINALIZE_USER` |
| **Resumen de campaña** | Al finalizar sesión o bajo demanda | `CAMPAIGN_SUMMARY_SYSTEM` | `CAMPAIGN_SUMMARY_USER` |
| **Cronología** | Al finalizar sesión | `CHRONOLOGY_SYSTEM_PROMPT` | `CHRONOLOGY_USER` |

## Contexto que recibe el LLM

### System prompt de sesión (`SESSION_SYSTEM_PROMPT`)

Contiene toda la información de contexto estático:

```
CONTEXTO DE LA CAMPAÑA:
- Sistema: {game_system}           ← CampaignContext.game_system
- Campaña: {name} — {description}  ← CampaignContext.name, .description
- Resumen hasta ahora: {campaign_summary}  ← CampaignContext.campaign_summary

JUGADORES:
{players_block}    ← _build_players_block()

PNJS CONOCIDOS:
{npcs_block}       ← _build_npcs_block()

LOCALIZACIONES CONOCIDAS:
{locations_block}  ← _build_locations_block()

ENTIDADES CONOCIDAS:
{entities_block}   ← CampaignContext.entities

RELACIONES CONOCIDAS:
{relationships_block}  ← _build_relationships_block()

{custom_instructions}  ← CampaignContext.custom_instructions
```

### Bloque de jugadores (`_build_players_block`)

Separa explícitamente al **Director de Juego** de los **Personajes Jugadores**:

```
DIRECTOR DE JUEGO:
- {discord_name} es el Director de Juego (DM/Master). Narra las escenas,
  describe el entorno, interpreta a todos los PNJs y controla los eventos del mundo.

PERSONAJES JUGADORES (protagonistas de la historia):
- {discord_name} juega como {character_name} (personaje jugador / protagonista) — {character_description}
```

- El DM se identifica comparando `PlayerInfo.discord_id` con `CampaignContext.dm_speaker_id`
- Si no hay `dm_speaker_id` configurado, no se genera sección de DM

### Instrucciones al LLM (dentro del system prompt)

Las instrucciones clave para el modelo son:

1. **Los PJs son protagonistas** — el relato debe centrarse en sus acciones y decisiones
2. **Meta-rol se excluye** — conversaciones OOC se marcan como `[META]`, no van en el resumen narrativo
3. **El DM habla como múltiples PNJs y narra** — no atribuir automáticamente a un único PNJ. Las líneas marcadas `[MASTER]` en la transcripción indican narración del director
4. **Preguntas** — si algo no está claro, el LLM puede marcar `[PREGUNTA: ...]`

## De dónde sale cada dato

### CampaignContext (modelo en `core/models.py`)

| Campo | Origen | Persistencia |
|-------|--------|--------------|
| `campaign_id` | TOML `[campaign].id` | DB tabla `campaigns` |
| `name` | TOML `[campaign].name` | DB |
| `game_system` | TOML `[campaign].game_system` | DB |
| `description` | TOML `[campaign].description` | DB, editable via Web UI |
| `language` | TOML `[campaign].language` | DB |
| `players` | TOML `[[players]]` | DB tabla `players`, editable via Web UI |
| `known_npcs` | TOML `[[npcs]]` + extraídos automáticamente | DB tabla `npcs`, editable via Web UI |
| `locations` | TOML `[[locations]]` + extraídos | DB tabla `locations`, editable via Web UI |
| `entities` | TOML `[[entities]]` + extraídos | DB tabla `entities`, editable via Web UI |
| `relationships` | Web UI | DB tabla `character_relationships` |
| `relation_types` | TOML `[[relation_types]]` | DB |
| `campaign_summary` | Generado por el summarizer | DB columna `campaigns.campaign_summary` |
| `speaker_map` | Calculado: `{discord_id: character_name}` por cada player | DB JSON, se recalcula al cargar players |
| `dm_speaker_id` | TOML `[campaign].dm_speaker_id` | DB |
| `custom_instructions` | TOML `[campaign].custom_instructions` | DB, editable via Web UI |
| `is_generic` | `True` si no se pasa `--campaign` | No persiste |

### Sync TOML → DB

Al arrancar con `--campaign`, los datos del TOML se sincronizan idempotentemente a la DB:
- Players: por `discord_id`, no se duplican
- NPCs/Locations: por `name`, no se duplican
- Cambios vía Web UI solo se guardan en DB + memoria (no modifican el TOML)

### speaker_map

Mapeo `discord_id → character_name` calculado desde la lista de `players`:

```python
speaker_map = {p.discord_id: p.character_name for p in players if p.character_name}
```

Se usa en `process_transcription()` para traducir el `speaker_id` del audio al nombre del personaje antes de pasarlo al resumen.

## Flujo de transcripción al resumen

```
Audio (Discord) → TranscriptionEvent(speaker_id, text, is_ingame)
                         ↓
              process_transcription()
              → speaker_map traduce speaker_id → character_name
              → se acumula en self._pending como TranscriptionEntry
                         ↓
              _update_summary() (periódico o on-demand)
              → _format_transcriptions(entries):
                 • DM se etiqueta como "[speaker [MASTER]]"
                 • Frases de cambio de escena → "--- [CAMBIO DE ESCENA] ---"
                 • Líneas no in-game se prefijan con "[META]"
              → _build_system_prompt(): contexto completo de campaña
              → SESSION_UPDATE_USER: transcripción reciente + resumen actual
              → Claude API → resumen actualizado
              → _extract_questions(): extrae [PREGUNTA: ...] del resultado
                         ↓
              _publish_summary() → SummaryUpdateEvent → WebSocket → Web UI
```

## Formato de transcripción que ve el LLM

Cada línea tiene el formato:

```
[CharacterName]: texto que dijo
[MasterName [MASTER]]: narración o diálogo de PNJ
[META][CharacterName]: comentario fuera de juego
--- [CAMBIO DE ESCENA] ---
[MasterName [MASTER]]: nueva escena...
```

## Finalización de sesión

`finalize_session()` ejecuta en orden:

1. Recoge todas las transcripciones pendientes
2. Si caben en una llamada → `FINALIZE_USER` directo
3. Si no caben → **batches progresivos**: intermedios con `SESSION_UPDATE_USER`, último con `FINALIZE_USER`
4. Parsea la respuesta: `---SESSION_SUMMARY---` y `---CAMPAIGN_SUMMARY---`
5. Genera **cronología** (timeline escena a escena)
6. **Extrae entidades** (NPCs, locations, entities nuevos) del resumen final
7. Publica resumen como "final"

## Resumen de campaña

`generate_campaign_summary()`:

- Recibe lista de `session_summaries` (dicts con `session_summary`, `started_at`, `id`)
- Usa `CAMPAIGN_SUMMARY_SYSTEM` (incluye players, NPCs, entities, relationships pero NO locations ni campaign_summary previo)
- Si los resúmenes no caben → **compresión progresiva**: comprime sesiones antiguas antes de combinar con recientes
- Se guarda en `campaign_summaries` (tabla historial append-only) y en `campaigns.campaign_summary` (cache del último)

## Resumen post-hoc

`generate_session_summary_from_transcriptions()`:

- Genera resumen de sesión a partir de transcripciones de DB (cuando falta el resumen)
- Stateless: no modifica `self._pending` ni `self._session_summary`
- Se usa antes de generar resumen de campaña si hay sesiones sin resumir
- Mismo flujo de batches que `finalize_session`

## Preguntas y respuestas

- El LLM puede incluir `[PREGUNTA: ...]` en el resumen
- `_extract_questions()` las extrae y las guarda en DB
- El usuario las responde via Web UI (`POST /api/questions/{id}/answer`)
- En la siguiente actualización, `_build_user_answers_block()` inyecta las respuestas en el prompt como sección `RESPUESTAS DEL USUARIO:`
- Tras inyectarlas se marcan como procesadas (no se repiten)

## Extracción automática de entidades

El summarizer extrae automáticamente NPCs, localizaciones, entidades (clanes, facciones, grupos) y relaciones a partir de los resúmenes de sesión. Esto permite que el mundo de la campaña se enriquezca progresivamente sin intervención manual.

### Cuándo se ejecuta

La extracción se dispara en **tres momentos**:

| Momento | Función | Modo |
|---------|---------|------|
| **Periódico durante sesión** | `_update_summary()` → `_extract_entities()` | Background (`asyncio.create_task`), cada N actualizaciones de resumen |
| **Al finalizar sesión** | `finalize_session()` → `_extract_entities()` | Síncrono (await), tras generar resumen final |
| **Bajo demanda desde Web UI** | `POST /api/sessions/{id}/extract-entities` | Síncrono, funciona con sesiones activas e históricas |

#### Frecuencia periódica

Controlada por `SummarizerConfig.extraction_every_n_updates` (default: `3`):
- Un contador `_extraction_counter` se incrementa con cada `_update_summary()`
- Cuando `counter % n == 0`, se lanza `_extract_entities()` como task en background
- Si `n = 0`, solo se extrae al finalizar la sesión

### Prompt de extracción (`EXTRACTION_USER`)

Se envía al LLM con un system prompt mínimo ("extrae información estructurada, responde solo con JSON válido") y un user message que incluye:

```
- Resumen de la sesión actual
- Lista de PNJs YA CONOCIDOS (para que no los repita)
- Lista de localizaciones YA CONOCIDAS
- Lista de entidades YA CONOCIDAS
- Lista de relaciones YA CONOCIDAS
```

Se le pide que responda con JSON válido en este formato:

```json
{
  "npcs": [{"name": "...", "description": "..."}],
  "locations": [{"name": "...", "description": "..."}],
  "entities": [{"name": "...", "entity_type": "clan|corporacion|faccion|grupo", "description": "..."}],
  "relationships": [{
    "source_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad",
    "target_key": "player:123|npc:Nombre|loc:Lugar|ent:Entidad",
    "relation_type": "aliado de|enemigo de|miembro de...",
    "category": "general|politica|familiar|social",
    "notes": "opcional"
  }]
}
```

### Doble capa de deduplicación

1. **Capa LLM**: el prompt incluye las listas de entidades ya conocidas para que el modelo no las repita
2. **Capa DB**: antes de guardar cada entidad, se comprueba existencia con `npc_exists()`, `location_exists()`, `entity_exists()` (comparación por `campaign_id` + `name`)

### Parseo de respuesta (`_parse_extraction_response`)

- Busca el primer bloque `{...}` en el texto con regex (`re.search(r"\{.*\}", text, re.DOTALL)`)
- Parsea como JSON; si falla, devuelve listas vacías
- Normaliza cada lista: si no es `list`, la reemplaza por `[]`

### Persistencia y actualización en memoria

Para cada tipo de entidad extraída, el flujo es idéntico:

```
LLM devuelve JSON → parseo → por cada item:
  1. Strip nombre y descripción
  2. Skip si nombre vacío
  3. Comprobar existencia en DB (dedup capa 2)
  4. Guardar en DB (save_npc / save_location / save_entity)
     → incluye campaign_id y first_seen_session
  5. Añadir al CampaignContext en memoria
     → self.campaign.known_npcs / .locations / .entities .append(...)
  6. Registrar en results["new_X"]
```

Para **relaciones**, hay un paso adicional de resolución de claves:

#### Resolución de claves de relación (`_resolve_relation_key`)

El LLM puede devolver claves en formatos variados. La función normaliza:

1. Si la clave ya tiene prefijo válido (`player:`, `npc:`, `loc:`, `ent:`), se usa directa
2. Si usa `location:` o `entity:`, se normaliza a `loc:` / `ent:`
3. Si es un nombre sin prefijo, se busca en un mapa de seed construido a partir de todos los players, NPCs, locations y entities conocidos (incluidos los recién guardados), por nombre case-insensitive

Las relaciones se guardan con `save_character_relationship()`. Si falla (ej. clave inválida), se silencia el error y se continúa con las siguientes.

### Evento de notificación

Si se extrajeron entidades nuevas, se publica un `EntitiesUpdatedEvent`:

```python
EntitiesUpdatedEvent(
    campaign_id: str,
    session_id: str,
    new_npcs: tuple[str, ...],        # nombres
    new_locations: tuple[str, ...],    # nombres
    new_entities: tuple[str, ...],     # nombres (grupos, facciones, corporaciones…)
    new_relationships: tuple[str, ...] # "source -> target: type"
)
```

Este evento se propaga al WebSocket y permite al Web UI actualizar dinámicamente las tabs de NPCs, Locations, Entities y Relationships.

### Endpoint Web (`POST /api/sessions/{id}/extract-entities`)

Permite disparar la extracción manualmente desde el Web UI:

- **Sesión activa**: usa el resumen en memoria (`state.session_summary`)
- **Sesión histórica**: carga el resumen desde DB (`db.get_session()`)
- **Siempre carga la campaña de la sesión desde DB** vía `_load_campaign_context_from_db()`, de modo que funciona en browse mode (sin `--campaign`)
- Crea un `ClaudeSummarizer` temporal con la config y campaña cargada
- Llama a `extract_entities_from_summary()`
- Si hay nuevas entidades, publica `EntitiesUpdatedEvent`
- Devuelve `{"ok": true, "new_npcs": [...], "new_locations": [...], "new_entities": [...], "new_relationships": [...]}`

### Tablas de DB involucradas

| Tabla | Función de guardado | Función de existencia |
|-------|--------------------|-----------------------|
| `npcs` | `save_npc(campaign_id, name, description, first_seen_session)` | `npc_exists(campaign_id, name)` |
| `locations` | `save_location(campaign_id, name, description, first_seen_session)` | `location_exists(campaign_id, name)` |
| `entities` | `save_entity(campaign_id, name, entity_type, description, first_seen_session)` | `entity_exists(campaign_id, name)` |
| `character_relationships` | `save_character_relationship(campaign_id, source, target, type, notes, category)` | — (upsert) |

### Efecto en el contexto del summarizer

Las entidades extraídas se añaden inmediatamente al `CampaignContext` en memoria, lo que significa que:

- Los **siguientes resúmenes incrementales** ya incluyen los NPCs/locations/entities nuevos en el system prompt
- La **siguiente extracción** ya los lista como "conocidos", evitando duplicados
- El ciclo es acumulativo: cada extracción enriquece el contexto para la siguiente
