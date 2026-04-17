# RPG Scribe — Refactor SOLID: Capas Limpias

**Fecha:** 2026-03-28
**Objetivo:** Dividir los ficheros monoliticos del proyecto en modulos manejables (<800 lineas) aplicando separacion de responsabilidades (Routers → Services → Repositories) en backend y ES modules por feature en frontend, sin cambiar la API publica ni introducir dependencias nuevas.

---

## Contexto

### Ficheros problematicos actuales

| Fichero | Lineas | Problema |
|---|---|---|
| `web/static/app.js` | 4,117 | Todo el frontend en un fichero |
| `web/routes.py` | 2,901 | 50+ endpoints + logica de negocio + helpers |
| `core/database.py` | 1,796 | Conexion + esquema + CRUD de 15+ tablas |
| `summarizers/claude_summarizer.py` | 1,541 | Prompts + summarizacion + extraccion entidades |
| `main.py` | 1,054 | Orquestacion + utilidades + logica de negocio |
| `web/static/style.css` | 1,266 | Todos los estilos en un fichero |
| `web/static/relationship-graph-3d.js` | 1,269 | Motor 3D con utilidades duplicadas |
| `web/exporter.py` | 843 | Cohesivo, se renombra a services/ |

### Enfoque elegido

**Capas limpias (Enfoque B):** Ademas de partir ficheros, se extrae una capa de servicios entre routers y database. Los routers solo parsean HTTP y delegan. Los servicios contienen la logica de negocio. El frontend se divide en ES modules nativos del navegador sin bundler.

### Decisiones de diseno

- **ES modules nativos** (no Vite/bundler): el proyecto corre en localhost, no necesita minificacion ni tree-shaking. `<script type="module">` evita dependencias de Node.js.
- **Capas separadas** (no slices verticales): frontend y backend se dividen segun sus propias fronteras naturales. El frontend comparte estado transversal (WebSocket, campaign context) que no encaja en slices por modulo backend.
- **Sin ABCs adicionales**: ya existen ABCs donde importan (BaseListener, BaseTranscriber, BaseSummarizer). No se crean interfaces abstractas para servicios/repos que solo tendran una implementacion.

---

## Arquitectura objetivo

```
src/rpg_scribe/
├── __init__.py
├── main.py                          ← ~400 lin (composition root + lifecycle)
├── config.py                        (sin cambios, 422 lin)
├── logging_config.py                (sin cambios, 85 lin)
│
├── core/
│   ├── models.py                    (sin cambios, 196 lin)
│   ├── events.py                    (sin cambios, 102 lin)
│   ├── event_bus.py                 (sin cambios, 68 lin)
│   ├── resilience.py                (sin cambios, 292 lin)
│   └── database/
│       ├── __init__.py              ← re-exporta Database para compatibilidad
│       ├── connection.py            ← clase Database: open/close/execute/fetchall
│       ├── schema.py               ← DDL: CREATE TABLEs, migraciones
│       └── repositories/
│           ├── __init__.py
│           ├── campaign_repo.py     ← CRUD campaigns + campaign_summaries
│           ├── session_repo.py      ← CRUD sessions + finalize/merge
│           ├── transcription_repo.py ← CRUD transcriptions + word_replacements
│           └── entity_repo.py       ← CRUD players/npcs/locations/entities/relationships
│
├── services/
│   ├── __init__.py
│   ├── campaign_service.py          ← Cargar contexto completo, validar campana
│   ├── session_service.py           ← Lifecycle sesiones, merge, finalize
│   ├── entity_service.py            ← CRUD entidades + normalizacion
│   ├── transcription_service.py     ← Persistir, editar, word replacements
│   ├── tts_service.py               ← Orquestar generacion audio
│   ├── export_service.py            ← Renombrado de web/exporter.py
│   ├── file_writer.py               ← TranscriptionFileWriter (de main.py)
│   └── audio_diagnostics.py         ← AudioDiagnosticSaver (de main.py)
│
├── summarizers/
│   ├── __init__.py                  ← re-exporta ClaudeSummarizer
│   ├── base.py                      (sin cambios, 147 lin)
│   ├── prompts.py                   ← ~200 lin: constantes de system prompts
│   ├── claude_summarizer.py         ← ~800 lin: core summarizacion sesion/campana
│   └── entity_extractor.py          ← ~500 lin: extraccion + parseo + persistencia
│
├── transcribers/                    (sin cambios, ya bien dividido)
├── listeners/                       (sin cambios)
├── discord_bot/                     (sin cambios)
├── tts/                             (sin cambios)
│
└── web/
    ├── app.py                       ← Ajusta imports, monta sub-routers
    ├── state.py                     ← WebState extraido de routes.py (~80 lin)
    ├── websocket.py                 (sin cambios, 129 lin)
    ├── routers/
    │   ├── __init__.py
    │   ├── campaigns.py             ← ~150 lin: GET/PATCH campaign, summaries
    │   ├── sessions.py              ← ~250 lin: CRUD sessions, merge, finalize, export
    │   ├── entities.py              ← ~350 lin: CRUD players/npcs/locations/entities/rels
    │   ├── transcriptions.py        ← ~120 lin: GET/PATCH/DELETE transcriptions, word repl
    │   ├── tts.py                   ← ~80 lin: POST narrate
    │   └── status.py               ← ~80 lin: GET status, WS endpoint
    └── static/
        ├── index.html               ← Ajusta <script> y <link> tags
        ├── campaign-summaries.html  (sin cambios)
        ├── js/
        │   ├── main.js              ← ~100 lin: entry point, inicializacion
        │   ├── state.js             ← ~50 lin: estado compartido singleton
        │   ├── api.js               ← ~80 lin: apiGet/apiPost/apiPatch/apiDelete
        │   ├── websocket.js         ← ~100 lin: conexion WS + dispatch mensajes
        │   ├── campaign.js          ← ~180 lin: campaign bar render/edit
        │   ├── entities.js          ← ~650 lin: tabs players/npcs/locations/entities
        │   ├── relationships/
        │   │   ├── index.js         ← Fachada: wiring, filtros, decide 2D vs 3D
        │   │   ├── graph-2d.js      ← Grafo SVG (extraido de app.js)
        │   │   └── graph-3d.js      ← Motor Canvas 3D (limpio, sin duplicados)
        │   ├── transcription.js     ← ~350 lin: feed, edicion inline, word replacements
        │   ├── summary.js           ← ~400 lin: tabs narrativa/cronologia, edicion parrafo
        │   ├── sessions.js          ← ~250 lin: sidebar, browse mode, merge
        │   ├── tts.js               ← ~200 lin: narrar, playback chunked, controles
        │   └── utils.js             ← ~80 lin: escapeHtml, formatDate, helpers puros
        └── css/
            ├── variables.css        ← Design tokens: --bg, --accent, --text, colores
            ├── base.css             ← Reset, tipografia, global
            ├── layout.css           ← Grid principal, sidebar, panels, responsive
            ├── components.css       ← Botones, inputs, badges, tabs, cards
            └── features/
                ├── campaign.css     ← Campaign bar estilos
                ├── entities.css     ← Entity lists, tabs, cards
                ├── relationships.css ← ~375 lin: grafo, filtros, legend, tooltip, sidebar
                ├── feed.css         ← Transcription feed, word edit inline
                └── summary.css      ← Summary tabs, editable paragraphs, TTS controls
```

---

## Seccion 1: Core — Database y Repositories

### Que cambia

`core/database.py` (1,796 lin) se divide en:

- **`database/connection.py`** — Clase `Database`: open, close, initialize, execute, fetchone, fetchall. La interfaz publica de acceso a SQLite.
- **`database/schema.py`** — DDL puro: todas las sentencias CREATE TABLE, indices, y logica de migracion de esquema.
- **`database/repositories/`** — Un repositorio por agregado de dominio.

### Repositories

Cada repository recibe la instancia de `Database` por constructor (inyeccion de dependencias):

```python
class CampaignRepository:
    def __init__(self, db: Database): ...
    async def get(self, campaign_id: int) -> dict | None: ...
    async def update(self, campaign_id: int, **fields) -> dict: ...
    async def list_summaries(self, campaign_id: int) -> list[dict]: ...
    async def create_summary(self, campaign_id: int, ...) -> dict: ...
```

| Repository | Tablas | Responsabilidad |
|---|---|---|
| `campaign_repo.py` | campaigns, campaign_summaries | CRUD campanas + resumenes de campana |
| `session_repo.py` | sessions | CRUD sesiones + finalize + merge |
| `transcription_repo.py` | transcriptions, word_replacements | CRUD transcripciones + reglas de sustitucion |
| `entity_repo.py` | players, npcs, locations, entities, relationships, relationship_types | CRUD todas las entidades + relaciones |

### Compatibilidad

`database/__init__.py` re-exporta `Database` para que los imports existentes (`from rpg_scribe.core.database import Database`) sigan funcionando sin cambios.

---

## Seccion 2: Services — Logica de negocio

### Motivacion

Hoy la logica de negocio esta desperdigada entre `routes.py` (validaciones, normalizaciones, hidratacion de contexto) y `main.py` (persistencia de transcripciones, word replacements, finalizacion de sesion). Los services la centralizan en un unico sitio, testeable sin HTTP.

### Que se mueve a donde

| Origen | Destino | Logica concreta |
|---|---|---|
| `routes.py` `_load_campaign_context_from_db()` | `campaign_service.py` | Hidratar CampaignContext completo |
| `routes.py` `_validate_campaign()` | `campaign_service.py` | Cargar campana de DB si no en state |
| `routes.py` `_normalize_locations/entities()` | `entity_service.py` | Normalizar formato entidades |
| `routes.py` logica de merge sessions | `session_service.py` | Combinar transcripciones + resumenes |
| `routes.py` logica de export | `session_service.py` → `export_service.py` | Generar ZIP |
| `main.py` `_persist_transcription()` | `transcription_service.py` | Guardar en DB |
| `main.py` `_apply_word_replacements()` | `transcription_service.py` | Sustitucion de palabras |
| `main.py` `TranscriptionFileWriter` | `file_writer.py` | Escribir a fichero rotativo |
| `main.py` `AudioDiagnosticSaver` | `audio_diagnostics.py` | Guardar WAV diagnostico |
| `web/exporter.py` | `export_service.py` | Renombrado, sin cambios internos |

### Patron de uso

```python
class SessionService:
    def __init__(self, session_repo, transcription_repo, event_bus): ...
    async def finalize(self, session_id: int) -> dict: ...
    async def merge(self, source_id: int, target_id: int) -> dict: ...
```

Los routers consumen servicios, no repos directamente:

```python
@router.post("/api/sessions/merge")
async def merge_sessions(body: dict):
    result = await session_service.merge(body["source_id"], body["target_id"])
    return result
```

---

## Seccion 3: Summarizer

### Que cambia

`claude_summarizer.py` (1,541 lin) se divide en 3 ficheros:

- **`prompts.py`** (~200 lin) — Solo constantes: SESSION_SYSTEM_PROMPT, GENERIC_SYSTEM_PROMPT, CHRONOLOGY_SYSTEM_PROMPT, CAMPAIGN_SUMMARY_SYSTEM, SESSION_UPDATE_USER, FINALIZE_USER.
- **`claude_summarizer.py`** (~800 lin) — Core: loop de summarizacion, llamadas a Claude, lifecycle (start/stop). Importa prompts desde `prompts.py`.
- **`entity_extractor.py`** (~500 lin) — Extraccion de entidades: prompt dedicado, parseo de respuesta, persistencia a DB via `entity_repo`.

### EntityExtractor

```python
class EntityExtractor:
    def __init__(self, client, campaign_context, entity_repo): ...
    async def extract_from_summary(self, summary_text: str) -> ExtractedEntities: ...
```

`ClaudeSummarizer` instancia y delega a `EntityExtractor` tras cada finalizacion. La extraccion es testeable independientemente pasando un texto fijo.

---

## Seccion 4: Web Routers

### Que cambia

`routes.py` (2,901 lin) se divide en:

- **`web/state.py`** (~80 lin) — Clase WebState: cache en memoria de transcriptions, summaries, component_status, active_campaign.
- **`web/routers/`** — Un router por dominio, usando `fastapi.APIRouter`.

### Routers

| Router | Endpoints | Lineas est. |
|---|---|---|
| `campaigns.py` | GET/PATCH campaign, campaign info, campaign summaries | ~150 |
| `sessions.py` | CRUD sessions, merge, finalize, export, generate-summary, chronology | ~250 |
| `entities.py` | CRUD players, NPCs, locations, entities, relationships | ~350 |
| `transcriptions.py` | GET/PATCH/DELETE transcriptions, word replacements | ~120 |
| `tts.py` | POST narrate, GET chunks | ~80 |
| `status.py` | GET status, WS endpoint | ~80 |

### Montaje en app.py

```python
from web.routers import campaigns, sessions, entities, transcriptions, tts, status

app.include_router(campaigns.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(transcriptions.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(status.router)
```

Las URLs de la API no cambian. El refactor es invisible para el frontend.

---

## Seccion 5: main.py

### Que cambia

`main.py` (1,054 lin) se reduce a ~400 lin extrayendo:

- `TranscriptionFileWriter` → `services/file_writer.py`
- `AudioDiagnosticSaver` → `services/audio_diagnostics.py`
- Logica de persistencia → ya en services (seccion 2)

### Que se queda

`Application` como **composition root**: crea repos, services, componentes. Suscribe eventos del EventBus delegando a services. Gestiona lifecycle (start/stop/signal handling).

```python
class Application:
    async def start(self):
        self.db = Database(self.config.db_path)
        await self.db.initialize()
        # Crear repos
        self.campaign_repo = CampaignRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        # Crear services
        self.transcription_service = TranscriptionService(...)
        self.session_service = SessionService(...)
        # Suscribir eventos
        self.event_bus.subscribe(TranscriptionEvent, self.transcription_service.handle)
        # Arrancar componentes
        await self._start_web()
        await self._start_discord_bot()
```

---

## Seccion 6: Frontend JavaScript

### Que cambia

`app.js` (4,117 lin) + `relationship-graph-3d.js` (1,269 lin) se dividen en ES modules nativos.

### Cambio en index.html

```html
<!-- Antes -->
<script src="app.js"></script>
<script src="relationship-graph-3d.js"></script>

<!-- Despues -->
<script type="module" src="js/main.js"></script>
```

### Modulos

| Modulo | Lineas est. | Responsabilidad |
|---|---|---|
| `main.js` | ~100 | Entry point: importa modulos, inicializa app |
| `state.js` | ~50 | Estado compartido: campaign, session, config |
| `api.js` | ~80 | apiGet/apiPost/apiPatch/apiDelete centralizados |
| `websocket.js` | ~100 | Conexion WS, dispatch mensajes a handlers |
| `campaign.js` | ~180 | Campaign bar: render, edicion, guardado |
| `entities.js` | ~650 | Tabs: players, NPCs, locations, entities |
| `relationships/index.js` | ~150 | Fachada: wiring, filtros, decide 2D vs 3D |
| `relationships/graph-2d.js` | ~200 | Grafo SVG |
| `relationships/graph-3d.js` | ~1,100 | Motor Canvas 3D (limpio, sin duplicados) |
| `transcription.js` | ~350 | Feed, edicion inline, word replacements |
| `summary.js` | ~400 | Tabs narrativa/cronologia, edicion parrafos |
| `sessions.js` | ~250 | Sidebar, browse mode, merge |
| `tts.js` | ~200 | Narrar, playback chunked, controles |
| `utils.js` | ~80 | escapeHtml, formatDate, helpers puros |

### Patron de estado compartido

```js
// state.js
export const state = {
    campaign: null,
    activeSessionId: null,
    ws: null,
    config: { maxTranscriptions: 200 }
};
```

Todos los modulos importan `state` — al ser la misma referencia en memoria, los cambios son visibles transversalmente.

### Patron de API centralizada

```js
// api.js
export async function apiGet(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
    return res.json();
}
export async function apiPatch(path, body) { ... }
export async function apiPost(path, body) { ... }
export async function apiDelete(path) { ... }
```

### Limpieza de graph-3d.js

- Se convierte de IIFE a ES module con `export`
- Utilidades duplicadas (escapeHtml, clamp, kindAccent) se importan desde `utils.js`
- Se eliminan ~50 lineas de codigo duplicado

---

## Seccion 7: Frontend CSS

### Que cambia

`style.css` (1,266 lin) se divide en capas + features:

### Estructura

| Fichero | Contenido | Lineas est. |
|---|---|---|
| `variables.css` | Design tokens: --bg, --accent, --text, --border, colores | ~20 |
| `base.css` | Reset, tipografia, font stack, max-width container | ~30 |
| `layout.css` | Grid principal, sidebar, panels, responsive breakpoints | ~200 |
| `components.css` | Botones, inputs, textareas, badges, tabs, cards genericas | ~250 |
| `features/campaign.css` | Campaign bar, labels, edit form | ~40 |
| `features/entities.css` | Entity lists, tabs, cards con iconos, status | ~200 |
| `features/relationships.css` | Grafo, filtros, controles, legend, tooltip, sidebar, stats | ~375 |
| `features/feed.css` | Transcription feed, word edit inline, log entries | ~100 |
| `features/summary.css` | Summary tabs, editable paragraphs, generation log, TTS | ~100 |

### Imports en index.html

```html
<link rel="stylesheet" href="css/variables.css">
<link rel="stylesheet" href="css/base.css">
<link rel="stylesheet" href="css/layout.css">
<link rel="stylesheet" href="css/components.css">
<link rel="stylesheet" href="css/features/campaign.css">
<link rel="stylesheet" href="css/features/entities.css">
<link rel="stylesheet" href="css/features/relationships.css">
<link rel="stylesheet" href="css/features/feed.css">
<link rel="stylesheet" href="css/features/summary.css">
```

---

## Principios de implementacion

1. **Ningun fichero supera ~800 lineas** (vs 4,117 / 2,901 / 1,796 actuales)
2. **3 capas backend**: Routers (HTTP parsing) → Services (logica negocio) → Repositories (datos)
3. **Frontend por feature**: cada modulo JS es un dominio de UI con imports explicitos
4. **Estado compartido via `state.js`** (frontend) e inyeccion de dependencias (backend)
5. **URLs de la API no cambian**: el refactor es invisible para clientes externos
6. **Modulos bien dimensionados no se tocan**: transcribers, listeners, discord_bot, tts
7. **Compatibilidad de imports**: `__init__.py` re-exporta clases movidas para no romper imports existentes
8. **Tests existentes deben seguir pasando** tras cada fase de migracion

---

## Lo que NO incluye este refactor

- No introduce framework JS (React, Vue, etc.)
- No introduce bundler (Vite, Webpack, etc.)
- No introduce ORM (SQLAlchemy, etc.)
- No introduce ABCs nuevos para services/repos
- No cambia la API REST (mismas URLs, mismos payloads)
- No cambia el esquema de base de datos
- No refactoriza modulos que ya estan bien dimensionados
