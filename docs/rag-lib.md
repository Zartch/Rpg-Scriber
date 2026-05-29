# rag_lib — Módulo RAG de Manuales

Módulo standalone para ingestar, indexar y buscar en PDFs de manuales de rol. **No tiene dependencias de `rpg_scribe`** — vive en `src/rag_lib/` y puede usarse de forma independiente.

## Arquitectura

```
PDF  →  PdfplumberParser  →  extract_toc()  ──┐
             │                                 │
             ↓                                 ↓
        parse()  ──→  run_chunker(pages, toc=toc)  →  Database (SQLite)
                                                            ↓
                                                     OpenAIEmbedder  →  rag_embeddings
                                                            ↓
                                                       VectorIndex (in-memory cache)
```

- **`PdfplumberParser`** (`parsing/pdfplumber_parser.py`) — extrae páginas como bloques tipados (`ProseBlock`, `TableBlock`) y TOC/bookmarks del PDF.
- **`run_chunker`** (`chunking.py`) — convierte `ParsedPage`s en chunks con `section_path` derivado de TOC o fontsizes.
- **`Database`** (`store.py`) — wrapper aiosqlite con repositorios: `ManualRepo`, `ChunkRepo`, `EmbeddingRepo`, `JobRepo`.
- **`VectorIndex`** (`embedding/index.py`) — índice numpy en memoria, cacheado por `db_path`. Se invalida al ingestar o editar chunks.
- **`Embedder`** (`embedding/base.py`) — ABC. Implementación por defecto: `OpenAIEmbedder` (`text-embedding-3-small`, dim=1536). Inyectable para tests.

## Parsing y generación de `section_path`

El campo `section_path` de cada chunk representa la posición jerárquica en el manual (e.g. `"Combate / Iniciativa / Orden de turno"`). Hay dos modos de generación según si el PDF tiene índice digital (TOC/bookmarks):

### Modo TOC (recomendado)

Si el PDF tiene marcadores digitales (`extract_toc()` devuelve entradas), `run_chunker` recibe `toc=[...]` y:

- `section_path` se construye exclusivamente a partir de la jerarquía TOC (nivel 1 / nivel 2 / …).
- Los bloques de texto con fontsize en el percentil 90 o superior se **descartan** (son títulos artísticos o decorativos, no texto útil).
- El índice se extrae con `pdfminer` a través de `pdfplumber`. Soporta PDFs de Adobe InDesign / iLovePDF que usan acciones GoTo (`PDFObjRef → dict GoTo → destino nombrado`) en lugar de destinos directos.

### Modo fontsize (fallback)

Si no hay TOC, el chunker detecta encabezados por tamaño de fuente:

- Umbral = percentil 90 de todos los fontsizes del documento.
- Bloques con fontsize **estrictamente superior** al umbral → encabezado estructural (actualiza `section_path`).
- Bloques en o por debajo del umbral → texto de cuerpo.
- Se usa `>` estricto (no `>=`) para evitar que texto de cuerpo con fontsize uniforme se marque como encabezado.

### Limpieza de caracteres decorativos

Los PDFs de juegos de rol a menudo renderizan texto artístico de gran tamaño (títulos de capítulo, fondos) con glyphs superpuestos en las mismas coordenadas que el texto de cuerpo. El parser filtra estas superposiciones en cada línea usando la referencia del **percentil 10 de fontsizes** de esa línea:

- Glyphs con `size > max(p10, 6pt) × 1.5` se eliminan de la línea (son arte decorativo).
- Si tras el filtro la línea queda vacía se conserva la original (sin datos mejor que nada).

Esto evita que chunks contengan cadenas tipo `NNuunnccaa ssee ddeessttrrooyyaa` (caracteres duplicados de texto artístico).

## Schema SQLite

| Tabla | Descripción |
|-------|-------------|
| `rag_manuals` | Un registro por PDF. `source_hash` UNIQUE → deduplicación automática. |
| `rag_chunks` | Chunks extraídos. `chunk_type` ∈ `{prose, table}`. `UNIQUE(manual_id, seq)`. |
| `rag_embeddings` | Vector float32 por chunk (BLOB). `UNIQUE(chunk_id)`. |
| `rag_chunks_fts` | Tabla virtual FTS5. Sincronizada por triggers (INSERT/DELETE/UPDATE). |
| `rag_jobs` | Jobs de ingesta en background. `status` ∈ `{pending, processing, done, error}`. |

Triggers FTS5: `rag_chunks_ai` (insert), `rag_chunks_ad` (delete), `rag_chunks_au` (update).

## API Pública Python

Todas las funciones son `async`. El parámetro `db_path` acepta `str | Path`.

### Ingesta

```python
# Síncrona (bloquea hasta completar)
result: IngestResult = await rag_lib.ingest_pdf(
    pdf_path,
    manual_name="Manual del GM",
    db_path="manuals.db",
    embedder=None,          # None → OpenAIEmbedder (requiere OPENAI_API_KEY)
)
# result.manual_id, result.chunks_created, result.was_already_ingested

# Asíncrona (background) — devuelve IngestJob inmediatamente
job: IngestJob = await rag_lib.upload_pdf(
    pdf_bytes,
    manual_name="Manual del GM",
    db_path="manuals.db",
    embedder=None,
)
# Polling:
job = await rag_lib.get_job(job.id, db_path)
# job.status ∈ {'pending', 'processing', 'done', 'error'}
# job.was_duplicate — True si el PDF ya existía
```

`ingest_pdf` es **idempotente**: si el SHA256 ya existe devuelve el `manual_id` existente sin re-ingestar.

`_run_ingest` (interno) usa tres bloques DB secuenciales para evitar locking con el event loop principal. En Windows escribe a `NamedTemporaryFile(delete=False)` y hace `os.unlink` en el finally.

### Búsqueda

```python
# Semántica (cosine similarity, requiere embeddings)
results: list[SearchResult] = await rag_lib.search(
    "¿Cómo funciona el hackeo?",
    db_path="manuals.db",
    manual_ids=[1, 2],      # None → todos los manuales
    k=10,
)

# FTS5 (keywords, soporta AND/OR/NOT/prefix*)
results = await rag_lib.search_fts("hackeo sistema", db_path, k=10)
# score normalizado a [0.0, 1.0]

# Similares a un chunk concreto
results = await rag_lib.search_similar(chunk_id=42, db_path, k=5)
```

### CRUD

```python
manuals: list[Manual]  = await rag_lib.list_manuals(db_path)
deleted: bool          = await rag_lib.delete_manual(manual_id, db_path)

chunks: list[Chunk]    = await rag_lib.list_chunks(manual_id, db_path, offset=0, limit=50)
chunk: Chunk | None    = await rag_lib.get_chunk(chunk_id, db_path)

# Editar chunk — regenera embedding si cambia text
updated: Chunk | None  = await rag_lib.update_chunk(
    chunk_id, db_path,
    text="nuevo texto",         # opcional — regenera hash, token_count y embedding
    section_path="Cap 3/Reglas", # None limpia la sección; omitido = no cambia
    chunk_type="table",          # opcional
    embedder=None,
)
```

`section_path` usa el patrón sentinel `_UNSET`: pasar `None` lo pone a NULL, omitirlo no lo toca.

## Tipos

```python
@dataclass(frozen=True)
class Manual:
    id: int; name: str; source_path: str; source_hash: str
    page_count: int; file_size: int; parser: str; ingested_at: str; chunk_count: int

@dataclass(frozen=True)
class Chunk:
    id: int; manual_id: int; seq: int; chunk_type: str
    page: int; page_end: int | None; section_path: str | None
    text: str; text_hash: str; token_count: int

@dataclass(frozen=True)
class SearchResult:
    chunk_id: int; manual_id: int; score: float; chunk: Chunk

@dataclass(frozen=True)
class IngestJob:
    id: str; status: str; manual_name: str
    manual_id: int | None; was_duplicate: bool; error: str | None
```

## Web UI

La página `/rag` es una SPA de tres paneles:

| Panel | Contenido |
|-------|-----------|
| Izquierdo | Lista de manuales + zona drag & drop para subir PDFs |
| Central | Tabla de chunks del manual seleccionado, o resultados de búsqueda en dos columnas (FTS5 \| Semántico) |
| Derecho | Detalle del chunk + lista de similares + editor inline |

### Búsqueda híbrida

La barra de búsqueda lanza FTS5 y semántica en paralelo (debounce 320 ms). Resultados en dos columnas hasta que se abre un chunk; en ese estado (State 4) los resultados se colapsan en una lista mezclada.

Cada resultado muestra el `section_path` del chunk (si existe) en violeta bajo la metadata, para orientar al usuario dentro de la jerarquía del manual.

### Upload con polling

1. El frontend sube el PDF con `POST /api/rag/manuals/upload` → recibe `{id, status: "pending"}`.
2. Hace polling a `GET /api/rag/jobs/{id}` cada 2 s.
3. Si `was_duplicate: true` → muestra mensaje "ya existe; borra el manual primero".
4. Si `status: "done"` → recarga la lista de manuales.

## Montar el Router en FastAPI

```python
from rag_lib.web import build_router

router = build_router("manuals.db", embedder=None)
app.include_router(router, prefix="")  # expone /rag y /api/rag/*
```

`embedder=None` en producción usa `OpenAIEmbedder`. En tests se inyecta `fake_embedder` (fixture de `conftest.py`).
