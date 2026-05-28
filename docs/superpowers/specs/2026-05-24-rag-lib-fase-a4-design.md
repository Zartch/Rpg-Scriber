# Spec: Fase A4 — Upload por web + edición de chunks

**Fecha:** 2026-05-24
**Fase:** A4 del plan-índice `ya-somos-capaces-de-glistening-dongarra.md`
**Prerrequisito:** Fase A3 completa (commit `d6fbb3e`)

---

## Contexto

A3 entregó búsqueda híbrida FTS5 + semántica y panel de detalle con chunks similares. A4 añade las últimas operaciones de escritura que faltaban en la UI:

1. **Upload de PDF por web** — drag & drop con ingesta en background (jobs en SQLite) y polling de estado.
2. **Aviso de duplicado** — si el PDF ya existe (mismo SHA256), la UI lo informa y sugiere borrar primero.
3. **Edición inline de chunks** — texto + `section_path` + `chunk_type` editables desde el panel derecho; guarda en DB, recalcula token_count y text_hash, regenera embeddings, e invalida la caché de vectores.

---

## Decisiones tomadas

| # | Decisión | Elección | Razón |
|---|---|---|---|
| 1 | **Jobs storage** | SQLite (`rag_jobs` table) | Persistencia entre reinicios; consistente con el patrón del proyecto |
| 2 | **Ingesta background** | `asyncio.create_task()` + polling cada 2s | PDF grande puede tardar 30-120s; no bloquear el request |
| 3 | **Duplicado SHA256** | Aviso informativo; no re-ingesta automática | El usuario debe borrar manualmente si quiere re-importar |
| 4 | **Edición chunks** | Texto + `section_path` + `chunk_type` | Permite corregir tanto el contenido como la clasificación |
| 5 | **UX edición** | Inline en panel derecho (Editar → campos → Guardar/Cancelar) | Ya existe el panel de detalle en A3; extensión natural |
| 6 | **Embeddings tras edición** | Regeneración síncrona (~1s para un chunk) | Chunk único; costo pequeño; coherencia inmediata del índice |
| 7 | **FTS5 tras edición** | Trigger AFTER UPDATE en `rag_chunks` | Misma estrategia que A3 (AFTER INSERT/DELETE); mantiene FTS5 sincronizado |

---

## Schema

### Nueva tabla `rag_jobs` (en `schema.py`)

```sql
CREATE TABLE IF NOT EXISTS rag_jobs (
    id           TEXT PRIMARY KEY,           -- UUID hex (uuid.uuid4().hex)
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'error')),
    manual_name  TEXT NOT NULL,
    manual_id    INTEGER,                    -- NULL hasta que termina correctamente
    was_duplicate INTEGER NOT NULL DEFAULT 0, -- 1 si el PDF ya existía (SHA256 dup)
    error        TEXT,                       -- NULL o mensaje de error legible
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON rag_jobs(status);
```

### Nuevo trigger AFTER UPDATE en `rag_chunks` (en `schema.py`)

Añadir a `RAG_SCHEMA_SQL` después de los triggers `rag_chunks_ai` y `rag_chunks_ad` de A3:

```sql
CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;
```

---

## Tipos

### Nuevo dataclass `IngestJob` (`types.py`)

```python
@dataclass(frozen=True)
class IngestJob:
    id: str
    status: str           # 'pending' | 'processing' | 'done' | 'error'
    manual_name: str
    manual_id: int | None
    was_duplicate: bool   # True si el PDF ya existía (SHA256 dup)
    error: str | None
```

---

## Store

### Nuevo `JobRepo` (`store.py`)

```python
class JobRepo:
    async def create(self, job_id: str, manual_name: str) -> None:
        """Inserta un job con status='pending'."""

    async def set_processing(self, job_id: str) -> None:
        """Actualiza status='processing' y updated_at."""

    async def set_done(self, job_id: str, manual_id: int, *, was_duplicate: bool = False) -> None:
        """Actualiza status='done', manual_id, was_duplicate, updated_at."""

    async def set_error(self, job_id: str, error: str) -> None:
        """Actualiza status='error', error, updated_at."""

    async def get(self, job_id: str) -> dict[str, Any] | None:
        """Devuelve el job o None si no existe."""
```

`Database` añade `self.jobs = JobRepo(self)`.

### Cambios en `ChunkRepo` (`store.py`)

```python
async def update(
    self,
    chunk_id: int,
    *,
    text: str | None = None,
    section_path: str | _Unset = _UNSET,
    chunk_type: str | None = None,
    text_hash: str | None = None,
    token_count: int | None = None,
) -> dict[str, Any] | None:
    """Actualiza los campos indicados. Devuelve el chunk actualizado o None si no existe."""
```

`_UNSET` es un sentinel interno para distinguir "no cambiar `section_path`" de `None` (sección vacía).

---

## API pública — funciones nuevas (`rag_lib/__init__.py`)

### `upload_pdf()`

```python
async def upload_pdf(
    pdf_bytes: bytes,
    *,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None = None,
) -> IngestJob:
    """Crea un job y lanza la ingesta en background. Retorna IngestJob inmediatamente.

    Si el SHA256 ya existe, el job termina con status='done' y manual_id del existente,
    pero sin crear nuevos chunks.
    """
```

Flujo interno:
1. `job_id = uuid.uuid4().hex`
2. `JobRepo.create(job_id, manual_name)` → status='pending'
3. `asyncio.create_task(_run_ingest(job_id, pdf_bytes, manual_name, db_path, embedder))`
4. `return IngestJob(id=job_id, status='pending', manual_name=manual_name, manual_id=None, error=None)`

`_run_ingest()` (coroutine interna):
1. `JobRepo.set_processing(job_id)`
2. Llama a `ingest_pdf(tmp_file, manual_name=..., db_path=..., embedder=...)` (escribe bytes a un `NamedTemporaryFile` previo)
3. Si `was_already_ingested=True`: `JobRepo.set_done(job_id, result.manual_id)` — el job termina bien, la UI detecta el duplicado via el campo `manual_id` que ya existía antes
4. Si éxito: `JobRepo.set_done(job_id, result.manual_id)`
5. Si excepción: `JobRepo.set_error(job_id, str(exc))`

> **Nota sobre duplicados:** cuando `was_already_ingested=True`, el job termina con `status='done'` y el `manual_id` del manual existente. El endpoint de upload añade una clave `was_duplicate` en la respuesta del polling para que la UI pueda mostrar el aviso correcto.

### `get_job()`

```python
async def get_job(job_id: str, db_path: str | Path) -> IngestJob | None:
    """Consulta el estado de un job. Retorna None si no existe."""
```

### `update_chunk()`

```python
_UNSET = object()  # sentinel interno — distingue "no cambiar" de None

async def update_chunk(
    chunk_id: int,
    db_path: str | Path,
    *,
    text: str | None = None,
    section_path: str | None | object = _UNSET,  # _UNSET = no cambiar; None = borrar
    chunk_type: str | None = None,
    embedder: Embedder | None = None,
) -> Chunk | None:
    """Actualiza texto/metadatos del chunk.

    Si se cambia el texto: recalcula text_hash y token_count, regenera embeddings,
    invalida la entrada del chunk en _VECTOR_CACHE.
    Retorna el chunk actualizado o None si no existe.
    """
```

Flujo interno:
1. `get_chunk(chunk_id, db_path)` → si None, retorna None
2. Calcula nuevos `text_hash` (SHA256) y `token_count` (tiktoken) si `text` cambió
3. `ChunkRepo.update(chunk_id, ...)` → actualiza en DB (trigger AFTER UPDATE mantiene FTS5)
4. Si `text` cambió: genera embedding del nuevo texto, `EmbeddingRepo.upsert_many([...])`, invalida `_VECTOR_CACHE` para ese `db_path`
5. Retorna `Chunk` actualizado

---

## Endpoints REST nuevos (`router.py`)

```
POST  /api/rag/manuals/upload
      Content-Type: multipart/form-data
      Fields: file (PDF UploadFile), manual_name (str)
      → 202 { id, status, manual_name, manual_id, error }
      → 400 si file no es PDF (content_type != 'application/pdf')
      → 422 si manual_name vacío

GET   /api/rag/jobs/{job_id}
      → 200 { id, status, manual_name, manual_id, error, was_duplicate }
      → 404 si job no existe

PATCH /api/rag/chunks/{chunk_id}
      Content-Type: application/json
      Body: { "text"?: str, "section_path"?: str | null, "chunk_type"?: "prose"|"table" }
      → 200 Chunk.to_dict()
      → 404 si chunk no existe
      → 422 si chunk_type no es 'prose' o 'table'
```

El campo `was_duplicate` en `GET /api/rag/jobs/{job_id}` se lee directamente de la columna `was_duplicate` de `rag_jobs`, que `_run_ingest()` escribe cuando `result.was_already_ingested=True`.

---

## UI — cambios en archivos existentes

### Panel izquierdo — zona de upload (`rag.html`, `rag.js`, `rag.css`)

```
┌─ Panel izquierdo ──────────────────────────────┐
│  MANUALES                                      │
│                                                │
│ ┌─ Zona drag & drop ──────────────────────┐   │
│ │  📄 Arrastra un PDF aquí                │   │
│ │  o  [Seleccionar archivo]               │   │
│ │  Nombre: [_______________________]      │   │
│ │          [↑ Subir PDF]                  │   │
│ └─────────────────────────────────────────┘   │
│                                                │
│  ▸ D&D 5e                         [×]         │
│    452 pp · 1234 chunks                        │
│  ▸ Tasha                          [×]         │
│    298 pp · 876 chunks                         │
└────────────────────────────────────────────────┘
```

**Estados de la zona de upload:**

| Estado | Apariencia |
|---|---|
| Idle | Borde punteado, texto "Arrastra un PDF aquí" |
| Dragging | Fondo resaltado (`dragover`), texto cambia a "Suelta para subir" |
| Loading | Spinner + "Procesando `<nombre>`…" — campo y botón disabled |
| Done (nuevo) | "✓ `<nombre>` importado (N chunks)" — desaparece a los 3s, manual aparece en lista |
| Done (duplicado) | "ℹ `<nombre>` ya está importado. Para reimportarlo, elimínalo primero." |
| Error | "⚠ Error: `<mensaje>`" + botón Reintentar |

El frontend hace polling a `GET /api/rag/jobs/{id}` cada 2s mientras `status` sea `pending` o `processing`.

### Panel derecho — edición de chunk (`rag.html`, `rag.js`, `rag.css`)

**Modo vista** (estado A3 + nuevo botón):
```
┌─ Chunk #142 — detalle ────────────────────────┐
│  p.42 · prose · Combate/Acciones/Ataque       │
│                               [✎ Editar]      │
│ ────────────────────────────────────────────  │
│  El ataque cuerpo a cuerpo permite...         │
│  (scroll interno, max-height: 40vh)           │
│ ────────────────────────────────────────────  │
│  SIMILARES                                    │
│  ...                                          │
└───────────────────────────────────────────────┘
```

**Modo edición** (click en Editar):
```
┌─ Chunk #142 — edición ────────────────────────┐
│  Tipo:    [prose ▼]                           │
│  Sección: [Combate/Acciones/Ataque          ] │
│  Texto:                                       │
│  ┌───────────────────────────────────────┐    │
│  │ El ataque cuerpo a cuerpo permite...  │    │
│  │ ...                                   │    │
│  └───────────────────────────────────────┘    │
│  ⚠ Guardar regenera los embeddings (~1s)      │
│  [Guardar]  [Cancelar]                        │
└───────────────────────────────────────────────┘
```

- **Guardar** envía `PATCH /api/rag/chunks/{id}` con los campos modificados; mientras espera muestra spinner en el botón; al volver actualiza el panel con el chunk editado.
- **Cancelar** restaura la vista original sin llamar al servidor.
- El panel de similares se oculta en modo edición y reaparece al volver a vista.

---

## Archivos a crear/modificar

### Modificados

| Archivo | Cambio |
|---|---|
| `src/rag_lib/schema.py` | Añade `rag_jobs` table + index + trigger `rag_chunks_au` |
| `src/rag_lib/types.py` | Añade `IngestJob` dataclass |
| `src/rag_lib/store.py` | Añade `JobRepo`; añade `ChunkRepo.update()` con sentinel `_UNSET` |
| `src/rag_lib/__init__.py` | Añade `upload_pdf()`, `get_job()`, `update_chunk()`; función interna `_run_ingest()` |
| `src/rag_lib/web/router.py` | Añade 3 endpoints: upload, job polling, chunk PATCH |
| `src/rag_lib/web/templates/rag.html` | Zona drag & drop; botón Editar en panel derecho; campos inline edición |
| `src/rag_lib/web/static/js/rag.js` | Upload drag&drop, polling, modo edición inline |
| `src/rag_lib/web/static/css/rag.css` | Estilos zona upload, estados drag, modo edición |

### Creados

| Archivo | Contenido |
|---|---|
| `tests/rag_lib/test_upload.py` | Tests para `upload_pdf()`, `get_job()`, flujo completo con `FakeEmbedder` |
| `tests/rag_lib/test_update_chunk.py` | Tests para `update_chunk()` — texto, metadatos, embeddings, FTS5 |
| `tests/rag_lib/test_web_router_a4.py` | Tests para los 3 endpoints nuevos |

---

## Estrategia TDD — ~26 tests estimados

### `tests/rag_lib/test_upload.py` (~10 tests)

| Test | Descripción |
|---|---|
| `test_upload_pdf_returns_job_immediately` | `upload_pdf(bytes, ...)` retorna `IngestJob` con `status='pending'` inmediatamente |
| `test_upload_pdf_job_created_in_db` | Tras `upload_pdf()`, `get_job(id)` devuelve el job |
| `test_upload_pdf_job_reaches_done` | Tras esperar con `asyncio.sleep`, job tiene `status='done'` y `manual_id` poblado |
| `test_upload_pdf_creates_manual` | Tras job done, `list_manuals()` contiene el nuevo manual |
| `test_upload_pdf_duplicate_returns_done` | Subir mismo PDF dos veces → segundo job `status='done'` con `manual_id` del existente |
| `test_upload_pdf_invalid_bytes_sets_error` | Bytes no-PDF → job llega a `status='error'` con mensaje |
| `test_get_job_nonexistent_returns_none` | `get_job("no-existe", db)` → `None` |
| `test_get_job_returns_ingest_job_type` | Retorna instancia de `IngestJob` |
| `test_upload_pdf_job_table_created` | `connect()` crea la tabla `rag_jobs` (smoke test schema) |
| `test_upload_pdf_embeddings_created` | Tras job done, `db.embeddings.load_all()` tiene filas |

### `tests/rag_lib/test_update_chunk.py` (~8 tests)

| Test | Descripción |
|---|---|
| `test_update_chunk_text_persisted` | `update_chunk(id, text="nuevo")` → `chunk.text == "nuevo"` |
| `test_update_chunk_recalculates_token_count` | `token_count` se actualiza con tiktoken |
| `test_update_chunk_recalculates_text_hash` | `text_hash` se actualiza con SHA256 del nuevo texto |
| `test_update_chunk_section_path_persisted` | `update_chunk(id, section_path="X/Y")` → `chunk.section_path == "X/Y"` |
| `test_update_chunk_chunk_type_persisted` | `update_chunk(id, chunk_type="table")` → `chunk.chunk_type == "table"` |
| `test_update_chunk_nonexistent_returns_none` | `update_chunk(99999, ...)` → `None` |
| `test_update_chunk_regenerates_embedding` | Tras update de texto, `db.embeddings.load_all()` tiene el embedding actualizado |
| `test_update_chunk_fts5_updated` | Tras update, `search_fts(nuevo_texto, db)` encuentra el chunk; texto anterior no aparece |

### `tests/rag_lib/test_web_router_a4.py` (~8 tests)

| Test | Descripción |
|---|---|
| `test_upload_endpoint_returns_202` | `POST /api/rag/manuals/upload` con PDF válido → 202 con `job_id` |
| `test_upload_endpoint_invalid_content_type` | No-PDF → 400 |
| `test_upload_endpoint_empty_name` | `manual_name=""` → 422 |
| `test_job_polling_endpoint_returns_200` | `GET /api/rag/jobs/{id}` → 200 con shape correcto |
| `test_job_polling_endpoint_not_found` | `GET /api/rag/jobs/no-existe` → 404 |
| `test_patch_chunk_endpoint_returns_200` | `PATCH /api/rag/chunks/{id}` con body → 200 Chunk |
| `test_patch_chunk_endpoint_not_found` | `PATCH /api/rag/chunks/99999` → 404 |
| `test_patch_chunk_invalid_chunk_type` | `{"chunk_type": "imagen"}` → 422 |

---

## Criterios de aceptación

- `POST /api/rag/manuals/upload` con PDF válido → 202 con `job_id`; job visible en DB con `status='pending'`.
- Polling `GET /api/rag/jobs/{id}` → `status` evoluciona a `done` con `manual_id` poblado.
- Upload del mismo PDF dos veces → segundo job termina con `status='done'` y `manual_id` del existente; no se crea un segundo manual; `list_manuals()` sigue devolviendo 1 manual.
- `PATCH /api/rag/chunks/{id}` con nuevo texto → `chunk.text` actualizado, `token_count` recalculado, `text_hash` recalculado, embedding regenerado, caché de vectores invalidado.
- FTS5 consistente tras edición: `search_fts(nuevo_texto, db)` encuentra el chunk; `search_fts(texto_anterior, db)` no lo encuentra.
- `PATCH /api/rag/chunks/{id}` con `section_path` y `chunk_type` → persiste en DB.
- UI: zona drag & drop acepta archivos `.pdf`; rechaza otros formatos; muestra spinner durante procesamiento; muestra "✓ importado" o aviso de duplicado o error al terminar.
- UI: panel derecho tiene botón "✎ Editar"; al clickar muestra campos inline (`chunk_type`, `section_path`, `text`); Guardar envía PATCH y refresca; Cancelar restaura sin llamada al servidor.
- `ruff check src/rag_lib tests/rag_lib` → sin errores.
- Suite completa `pytest tests/rag_lib/` pasa (incluyendo tests A1-A3 sin regresiones).
