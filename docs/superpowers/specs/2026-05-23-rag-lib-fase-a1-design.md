# `rag_lib` Fase A1 — Esqueleto del módulo + ingesta de PDF — Diseño

## Contexto

Esta es la primera fase del plan-índice **RAG Manager + Rules Bot** (ver `~/.claude/plans/ya-somos-capaces-de-glistening-dongarra.md`). Construye los cimientos del módulo `rag_lib`: un paquete **independiente y reusable** que vivirá en `src/rag_lib/` (paralelo a `src/rpg_scribe/`, **sin imports de `rpg_scribe.*`**) preparado para ser extraído a PyPI en el futuro.

A1 entrega:

1. **Ingesta de PDFs** (parsing → chunks → SQLite).
2. **API pública asíncrona** mínima (`ingest_pdf`, `list_manuals`, `delete_manual`, `get_chunk`).
3. **CLI** (`python -m rag_lib …`) para operar sin UI.
4. **UI mínima de validación** (página `/rag`, sin edición ni upload) para auditar visualmente la calidad de los chunks.

Fuera de scope (otras fases):

- Embeddings + búsqueda por similitud → **A2**.
- Búsqueda full-text en UI, vista detalle con "chunks similares" → **A3**.
- Edición de chunks, upload por web, re-ingesta desde UI → **A4**.
- Migraciones DB versionadas, README standalone → **A5**.

## Decisiones clave (cerradas en brainstorming)

| # | Decisión | Elección |
|---|---|---|
| 1 | Parser PDF | `pdfplumber` único, detrás de ABC `PdfParser`. |
| 2 | Page boundaries en prosa | No cruzar página, salvo si el último párrafo continúa (heurística). |
| 3 | Tokenizer + tamaños | `tiktoken cl100k_base`, target 500 tok, overlap 75 tok. |
| 4 | Idempotencia | Skip silencioso — segunda ingesta con mismo SHA256 devuelve el `manual_id` existente. |
| 5 | Heading detection | Schema-ready + heurística fontsize > p90 → `section_path`. Degrada a NULL si falla. |
| 6 | Formato tablas | GFM Markdown, prefijado con `[section_path]` y caption inferido. |
| 7 | Scope UI en A1 | Solo visualización + borrado de manual completo. Sin edición ni upload. |

## Estructura del paquete

```
src/rag_lib/
├── __init__.py            # Re-exporta API pública
├── __main__.py            # Entry-point del CLI (delega a cli.py)
├── cli.py                 # argparse + 4 subcomandos
├── types.py               # Dataclasses
├── errors.py              # IngestError, PdfParseError, ManualNotFound
├── schema.py              # DDL string + lightweight migrations
├── store.py               # Database class + ManualRepo + ChunkRepo
├── chunking.py            # split_prose + format_table + run_chunker
├── parsing/
│   ├── __init__.py
│   ├── base.py            # ABC PdfParser
│   └── pdfplumber_parser.py
└── web/
    ├── __init__.py        # build_router(db_path) factory
    ├── router.py          # APIRouter (4 endpoints + página)
    ├── templates/
    │   └── rag.html
    └── static/
        ├── css/rag.css
        └── js/rag.js
```

Integración con RPG Scribe (en archivo nuevo, **fuera** del módulo `rag_lib`):

```
src/rpg_scribe/integrations/rag.py
```

Este envoltorio: (a) lee el path de la DB del config TOML de RPG Scribe; (b) invoca `rag_lib.web.build_router(db_path)`; (c) `app.include_router(router)` en `main.py`. **Es el único punto donde RPG Scribe toca `rag_lib`** — el módulo permanece extraíble.

## Modelo de datos

### Schema SQL (`rag_lib/schema.py`)

```sql
CREATE TABLE IF NOT EXISTS rag_manuals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    source_hash   TEXT NOT NULL UNIQUE,        -- SHA256 hex del PDF binario
    page_count    INTEGER NOT NULL,
    file_size     INTEGER NOT NULL,
    parser        TEXT NOT NULL DEFAULT 'pdfplumber',
    ingested_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id     INTEGER NOT NULL REFERENCES rag_manuals(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,             -- orden absoluto dentro del manual (0-indexed)
    chunk_type    TEXT NOT NULL CHECK (chunk_type IN ('prose', 'table')),
    page          INTEGER NOT NULL,             -- página donde empieza (1-indexed)
    page_end      INTEGER,                      -- NULL salvo cruce por continuación
    section_path  TEXT,                         -- e.g. "Combate / Acciones / Ataque" (NULL si no detectado)
    text          TEXT NOT NULL,                -- contenido (GFM para tablas, plano para prosa)
    text_hash     TEXT NOT NULL,                -- SHA256 hex del texto (para dedup + futura invalidación de embeddings)
    token_count   INTEGER NOT NULL,             -- conteo con tiktoken cl100k_base
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manual_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_chunks_manual_page ON rag_chunks(manual_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_type        ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_hash        ON rag_chunks(text_hash);
```

`PRAGMA foreign_keys = ON` se aplica al abrir cada conexión (SQLite lo desactiva por defecto).

### Dataclasses (`rag_lib/types.py`)

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass(frozen=True)
class Manual:
    id: int
    name: str
    source_path: str
    source_hash: str
    page_count: int
    file_size: int
    parser: str
    ingested_at: datetime
    chunk_count: int                # computado en list_manuals (LEFT JOIN COUNT)

@dataclass(frozen=True)
class Chunk:
    id: int
    manual_id: int
    seq: int
    chunk_type: str                 # 'prose' | 'table'
    page: int
    page_end: int | None
    section_path: str | None
    text: str
    text_hash: str
    token_count: int

@dataclass(frozen=True)
class IngestResult:
    manual_id: int
    chunks_created: int             # 0 si was_already_ingested=True
    was_already_ingested: bool

# Tipos internos del pipeline (no parte de la API pública)

@dataclass(frozen=True)
class ProseBlock:
    text: str
    page: int
    fontsize_avg: float

@dataclass(frozen=True)
class TableBlock:
    rows: list[list[str]]           # [[header...], [row1...], ...]
    page: int
    caption: str | None             # texto detectado encima/debajo

@dataclass(frozen=True)
class ParsedPage:
    page_num: int                   # 1-indexed
    blocks: list[ProseBlock | TableBlock]
```

## API pública (`rag_lib/__init__.py`)

Cinco funciones, todas async. Cada llamada gestiona su propia conexión `aiosqlite`.

```python
async def ingest_pdf(
    pdf_path: str | Path,
    *,
    manual_name: str,
    db_path: str | Path,
) -> IngestResult: ...

async def list_manuals(db_path: str | Path) -> list[Manual]: ...

async def delete_manual(manual_id: int, db_path: str | Path) -> bool: ...

async def get_chunk(chunk_id: int, db_path: str | Path) -> Chunk | None: ...

async def list_chunks(
    manual_id: int,
    db_path: str | Path,
    *,
    offset: int = 0,
    limit: int = 50,
) -> list[Chunk]: ...
```

`list_chunks` se necesita para la UI (paginación del panel derecho) y para el CLI `show`.

**Convenciones**:

- `db_path` puede no existir aún: la primera llamada que necesite la DB ejecuta el schema (idempotente con `CREATE TABLE IF NOT EXISTS`).
- `ingest_pdf` con un SHA256 ya presente devuelve `IngestResult(existing_id, 0, True)` sin tocar nada.
- `delete_manual` con `manual_id` inexistente devuelve `False`. Cascade borra chunks por FK.
- `get_chunk` con ID inexistente devuelve `None` (no lanza).

## Pipeline de ingesta

```
ingest_pdf(pdf_path, manual_name=..., db_path=...)
  │
  ├── 1. file_bytes = read_binary(pdf_path)
  │      source_hash = sha256(file_bytes).hexdigest()
  │      file_size = len(file_bytes)
  │
  ├── 2. existing = ManualRepo.find_by_hash(source_hash)
  │      if existing: return IngestResult(existing.id, 0, True)
  │
  ├── 3. parser = PdfplumberParser()
  │      pages: list[ParsedPage] = await asyncio.to_thread(parser.parse, pdf_path)
  │      # to_thread porque pdfplumber es síncrono y bloqueante
  │
  ├── 4. Heading detection (chunking.py:detect_headings)
  │      Calcula percentil 90 del fontsize de TODAS las páginas.
  │      Para cada ProseBlock con fontsize_avg >= p90 → es heading.
  │      Mantiene stack [h1, h2, h3] basado en niveles de fontsize.
  │      Resultado: cada block obtiene `section_path` (puede ser None).
  │
  ├── 5. Chunker (chunking.py:run_chunker)
  │      Recorre blocks en orden. Por cada uno:
  │        - TableBlock → 1 chunk atómico:
  │            text = f"[{section_path}]\nTabla: {caption or '<sin título>'}\n\n{gfm_table(rows)}"
  │            chunk_type='table', page=block.page
  │        - ProseBlock → acumula en buffer hasta superar 500 tokens.
  │            Cuando se cierra el chunk, las últimas ~75 tok del buffer (cortando
  │            en boundary de palabra) se prepend al siguiente buffer = overlap.
  │            Si toca cambiar de página, se invoca should_merge_across_pages():
  │            - True  → se mantiene el buffer y se sigue acumulando; el chunk
  │                      resultante tendrá page_end = página nueva.
  │            - False → se cierra el chunk en la página actual (page_end=NULL)
  │                      y se empieza buffer nuevo en la siguiente página.
  │
  ├── 6. Dedup interno
  │      Calcula text_hash de cada chunk. Descarta chunks con text_hash idéntico al
  │      inmediatamente anterior (headers/footers repetidos página a página).
  │
  ├── 7. Transacción única (aiosqlite):
  │        - INSERT INTO rag_manuals (...)
  │        - INSERT INTO rag_chunks (...) por cada chunk con executemany
  │        - COMMIT
  │
  └── 8. return IngestResult(manual_id, len(chunks), False)
```

### Heurística de continuación de párrafo

Función: `should_merge_across_pages(last_block_text: str, next_block_text: str) -> bool`

```python
def should_merge_across_pages(last_text: str, next_text: str) -> bool:
    if not last_text or not next_text:
        return False
    last_char = last_text.rstrip()[-1] if last_text.rstrip() else ""
    next_first = next_text.lstrip()[0] if next_text.lstrip() else ""
    sentence_terminators = set(".!?…")
    # Cruza solo si NO termina en terminador Y siguiente empieza minúscula
    return last_char not in sentence_terminators and next_first.islower()
```

### Formato GFM table (`chunking.py:gfm_table`)

```python
def gfm_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    # Primera fila = header. Si las filas tienen longitudes distintas, normalizamos
    # al máximo (rellenando con "").
    width = max(len(r) for r in rows)
    norm = [[(cell or "").replace("\n", " ").strip() for cell in r] + [""] * (width - len(r)) for r in rows]
    header, *body = norm
    sep = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)
```

Si una celda contiene `|` o salto de línea, se reemplaza por `\|` y espacio respectivamente (escapado GFM mínimo).

### Caption inferido

`PdfplumberParser` extrae texto plano de cada página con `page.extract_text()` y tablas con `page.extract_tables()`. Para cada tabla, busca:

1. La línea de texto inmediatamente **encima** de la `bbox` de la tabla (la más cercana en `y`).
2. Si esa línea coincide con el primer header de la tabla, descartar (es la fila de header).
3. Si la línea está en formato típico de caption (e.g. empieza con "Tabla", "Tabla N", numérico), usar como caption.
4. Si no hay coincidencia, `caption = None`.

Heurística simple, sin parsing complicado. NULL es aceptable.

## CLI (`rag_lib/cli.py`)

Implementado con `argparse`. Entry-point: `python -m rag_lib <cmd>` (vía `__main__.py`).

```
$ python -m rag_lib --help
usage: rag_lib [-h] {ingest,list,delete,show} ...

$ python -m rag_lib ingest <pdf> --name "D&D 5e" --db data/rag.db
Ingesting D&D 5e from <pdf>...
Parsed 452 pages, generated 1234 chunks (912 prose, 322 table).
Saved as manual_id=1.

$ python -m rag_lib ingest <pdf> --name "D&D 5e" --db data/rag.db   # 2ª vez
Already ingested as manual_id=1 (same SHA256). No changes.

$ python -m rag_lib list --db data/rag.db
ID  Name        Pages  Chunks  Size       Ingested
1   D&D 5e      452    1234    14.6 MB    2026-05-23 10:23:01
2   Tasha       298    876     8.9 MB     2026-05-23 11:04:55

$ python -m rag_lib delete 2 --db data/rag.db
Deleted manual_id=2 (and 876 chunks).

$ python -m rag_lib show 1 --db data/rag.db --page 42
Manual: D&D 5e
Page 42 — 8 chunks:
  #142  prose  [Combate / Acciones / Ataque]  "El ataque cuerpo a cuerpo permite..." (487 tok)
  #143  table  [Combate / Acciones / Daño]    "Tabla: Daño por arma..." (203 tok)
  ...
```

Cada subcomando devuelve exit code 0 en éxito, 1 en error con mensaje a stderr.

## UI mínima de validación

### Página `/rag` (`rag_lib/web/templates/rag.html`)

Layout: dos paneles con flexbox.

```
┌─ Panel izquierdo (manuales) ─┬─ Panel derecho (chunks del seleccionado) ─┐
│                              │                                            │
│ Manuales (2)                 │ D&D 5e — 1234 chunks                       │
│ ─────────────                │ ───────────────────────                    │
│                              │                                            │
│ ▸ D&D 5e         [×]         │ #142 · p.42 · prose · Combate/.../Ataque   │
│   452 pp · 1234 chunks       │ "El ataque cuerpo a cuerpo permite..."     │
│                              │ ─────────────                              │
│ ▸ Tasha          [×]         │ #143 · p.42 · table · Combate/.../Daño     │
│   298 pp · 876 chunks        │ Tabla: Daño por arma                       │
│                              │ ┌─────┬─────┬──────┐                       │
│                              │ │ Arma│ Daño│ Tipo │ ...                   │
│                              │ ...                                        │
│                              │                                            │
│                              │ [Cargar más ↓]                            │
└──────────────────────────────┴────────────────────────────────────────────┘
```

Interacciones:

- **Click en un manual** → carga sus chunks en el panel derecho (`GET /api/rag/manuals/{id}/chunks?offset=0&limit=50`).
- **Click en `[×]`** → confirm dialog → `DELETE /api/rag/manuals/{id}` → recarga lista.
- **Click en una fila de chunk** → expande inline mostrando el texto completo (especialmente útil para tablas, que se renderizan via `marked.js` ligero o un parser GFM inline).
- **Scroll al final del panel derecho** → carga la siguiente página (offset += limit).

### Endpoints REST (`rag_lib/web/router.py`)

```
GET /rag                                          → renderiza rag.html (Jinja2)
GET /api/rag/manuals                              → [Manual.to_dict() ...]
GET /api/rag/manuals/{manual_id}/chunks
       ?offset=0&limit=50                         → [Chunk.to_dict() ...]
GET /api/rag/chunks/{chunk_id}                    → Chunk.to_dict() | 404
DELETE /api/rag/manuals/{manual_id}               → 204 | 404
```

Factory:

```python
def build_router(db_path: str | Path) -> APIRouter:
    """Construye un APIRouter con la página /rag y los endpoints /api/rag/*."""
```

`db_path` se cierra sobre las handlers vía closure (las funciones internas lo usan al invocar la API pública del módulo).

### Frontend

Stack: HTML server-rendered con Jinja2, ES modules, CSS modular. **Sin frameworks** (patrón del proyecto). El JS hace `fetch()` directo a los endpoints.

```
rag_lib/web/static/css/rag.css   ~80 líneas
rag_lib/web/static/js/rag.js     ~150 líneas (ES module)
```

## Errores y logging

### Excepciones (`rag_lib/errors.py`)

```python
class IngestError(Exception):
    """Base para errores de ingesta de rag_lib."""

class PdfParseError(IngestError):
    """pdfplumber falló al abrir o parsear el PDF."""

class ManualNotFound(Exception):
    """manual_id no existe en la DB."""  # Solo por completitud; las APIs públicas
                                          # devuelven None/False en lugar de lanzar.
```

### Logging

`logging.getLogger("rag_lib.<submodule>")`. El módulo **no configura handlers**: el host (RPG Scribe) ya configura logging globalmente. Mensajes de nivel INFO en hitos de ingesta:

```
rag_lib.ingest: parsing 452 pages from D&D 5e.pdf
rag_lib.chunking: detected headings (n=187, p90=14.2pt)
rag_lib.chunking: generated 1234 chunks (912 prose, 322 table) in 3.4s
rag_lib.store: inserted manual_id=1 with 1234 chunks
```

DEBUG para detalles (font_stats, dedup descartados, etc.).

## Estrategia de tests (TDD)

PDFs sintéticos generados con `reportlab` en `tests/rag_lib/conftest.py`. Cero binarios fixturados en el repo. Fixtures expuestas:

- `simple_pdf(tmp_path)` — 3 páginas de prosa Lorem Ipsum.
- `pdf_with_table(tmp_path)` — 1 página con tabla 4×3.
- `pdf_with_headings(tmp_path)` — texto con 2 niveles de headings (font 18pt y 14pt sobre body 11pt).
- `pdf_with_continuation(tmp_path)` — párrafo que cruza de página 1 a 2.
- `pdf_with_repeated_footer(tmp_path)` — mismo footer en 3 páginas (para dedup).

### Tests por capa

```
tests/rag_lib/
├── conftest.py                          # fixtures de PDF sintéticos
├── parsing/
│   └── test_pdfplumber_parser.py       # ~6 tests
├── test_chunking.py                     # ~10 tests
├── test_store.py                        # ~6 tests
├── test_integration_ingest.py           # ~5 tests (end-to-end)
├── test_cli.py                          # ~5 tests
└── test_web_router.py                   # ~6 tests
```

**Casos específicos a cubrir** (no exhaustivo):

`test_pdfplumber_parser.py`:
- `parse()` devuelve `list[ParsedPage]` con `page_num` 1-indexed
- Prose blocks tienen `fontsize_avg` numérico
- Tables se extraen como `TableBlock` con `rows: list[list[str]]`
- PDF inexistente → `PdfParseError`
- PDF corrupto → `PdfParseError`

`test_chunking.py`:
- `gfm_table([["A","B"], ["1","2"]])` produce header + separator + body
- Celda con `\n` se reemplaza por espacio
- Celda con `|` se escapa con `\|`
- `should_merge_across_pages("frase.", "Mayuscula")` → False
- `should_merge_across_pages("frase sin punto", "minuscula")` → True
- `should_merge_across_pages("frase.", "minuscula")` → False (punto manda)
- Chunker prosa respeta target ~500 tok (con tolerancia ±15%)
- Overlap funcional: dos chunks consecutivos comparten ~75 tok
- Tabla → 1 chunk atómico con `chunk_type='table'`
- Heading detection: bloque con fontsize >= p90 se marca como heading, propaga a chunks siguientes

`test_store.py`:
- `Database.connect()` crea schema (todas las tablas + indices presentes)
- `ManualRepo.insert(...)` con `source_hash` duplicado → `IntegrityError`
- `ChunkRepo.list_by_manual(manual_id, offset, limit)` paginación correcta
- `ManualRepo.delete(manual_id)` cascade a chunks (FK ON)
- `PRAGMA foreign_keys` está ON tras `connect()`

`test_integration_ingest.py`:
- End-to-end: PDF sintético → DB tiene 1 manual + N chunks
- Re-ingesta del mismo PDF → `was_already_ingested=True`, sin chunks nuevos
- `delete_manual` borra chunks (verificar count tras delete)
- `list_manuals` devuelve `chunk_count` correcto
- `get_chunk` devuelve None para ID inexistente

`test_cli.py`:
- `python -m rag_lib ingest <pdf> --name X --db <tmp>` crea DB y muestra resultado en stdout
- `python -m rag_lib list --db <tmp>` lista el manual recién creado
- `python -m rag_lib delete <id> --db <tmp>` lo borra
- `python -m rag_lib show <id> --db <tmp>` lista chunks
- exit codes: 0 OK, 1 en error (manual no existe, archivo no existe)

`test_web_router.py`:
- `GET /api/rag/manuals` devuelve JSON con shape correcto
- `GET /api/rag/manuals/{id}/chunks?offset=0&limit=10` paginación
- `GET /api/rag/chunks/{id}` 200 si existe, 404 si no
- `DELETE /api/rag/manuals/{id}` 204 si existe, 404 si no, cascade
- `GET /rag` (HTML) status 200 (smoke test)

### Convenciones

Patrón fixture del proyecto:

```python
@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.connect()
    yield database
    await database.close()
```

`asyncio_mode = "auto"` ya configurado en `pyproject.toml`.

## Dependencias nuevas

En `pyproject.toml`:

```toml
[project]
dependencies = [
  ...,
  "pdfplumber>=0.10",
  "tiktoken>=0.7",
]

[project.optional-dependencies]
dev = [
  ...,
  "reportlab>=4.0",   # solo para tests
]
```

(`aiosqlite`, `fastapi`, `jinja2` ya están en el proyecto.)

## Patrones del repo a mimetizar

`rag_lib` no importa de `rpg_scribe`, pero replica idioms:

- `src/rpg_scribe/core/database/connection.py:14-103` — `Database` class con repos como atributos, `aiosqlite.Connection` interno
- `src/rpg_scribe/core/database/schema.py` — DDL en single string + `_ensure_column` para migraciones ligeras
- `src/rpg_scribe/core/database/repositories/campaign_repo.py` — convenciones de repo (CRUD explícito, return dicts o dataclasses)
- `tests/test_database.py:10-17` — fixture `tmp_path` + lifecycle `connect/close`
- Estilo de código: `from __future__ import annotations`, async/await, dataclasses `frozen=True` para tipos inmutables, ABC para interfaces.

## Verificación end-to-end

Tras cerrar A1, esto debe funcionar:

```bash
pip install -e ".[dev]"

# CLI smoke test
python -m rag_lib ingest path/to/manual.pdf --name "D&D 5e" --db data/rag.db
python -m rag_lib list   --db data/rag.db
python -m rag_lib show   1 --db data/rag.db --page 1
python -m rag_lib delete 1 --db data/rag.db

# UI smoke test
rpg-scribe   # arranca RPG Scribe; /rag visible en http://127.0.0.1:8000/rag
# → click en un manual → ver chunks paginados → click en chunk → ver texto completo
# → click en [×] → manual borrado + lista actualizada

# Tests
pytest tests/rag_lib/ -v
ruff check src/rag_lib tests/rag_lib
ruff format --check src/rag_lib tests/rag_lib
```

### Criterios de aceptación

- (a) Tablas se almacenan como chunks atómicos en GFM con `section_path` prefijado.
- (b) Prosa respeta target ~500 tok ± overlap (tolerancia ±15%), sin truncar palabras.
- (c) Re-ingesta del mismo PDF: `was_already_ingested=True`, mismo `manual_id`, sin duplicados.
- (d) `delete_manual` borra cascade (verificable con `SELECT COUNT(*) FROM rag_chunks WHERE manual_id=…`).
- (e) UI `/rag` lista manuales, muestra chunks paginados, permite borrar manual completo.
- (f) Todos los tests pasan; `ruff check` y `ruff format --check` limpios.
- (g) `rag_lib` no contiene ningún `import rpg_scribe...`. Verificable con: `grep -r "from rpg_scribe" src/rag_lib/` → 0 resultados.
