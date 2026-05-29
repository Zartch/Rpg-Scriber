# Spec: Fase A3 — Búsqueda híbrida + vista detalle con chunks similares

**Fecha:** 2026-05-23
**Fase:** A3 del plan-índice `ya-somos-capaces-de-glistening-dongarra.md`
**Prerrequisito:** Fase A2 completa (commit `34160f0`)

---

## Contexto

A2 entregó embeddings y búsqueda semántica (`rag_lib.search()`). A3 añade:

1. **Búsqueda híbrida** en la UI: FTS5 (keywords, SQLite, sin costo API) + semántica (vectores A2, OpenAI) como dos endpoints independientes que el frontend lanza en paralelo.
2. **Vista detalle con chunks similares**: panel derecho que muestra el texto completo de un chunk + los top-N chunks semánticamente similares.

Los bots (Fase B1 Rules Bot) reutilizarán `search_fts()` y `search_similar()` directamente desde la API pública de `rag_lib`.

---

## Decisiones tomadas

| # | Decisión | Elección | Razón |
|---|---|---|---|
| 1 | **Tipo de búsqueda FTS** | SQLite FTS5 completo | Soporta operadores (AND/OR/NOT/prefijo), rápido en PDFs grandes |
| 2 | **Arquitectura endpoints búsqueda** | Dos endpoints independientes (`/search/fts` y `/search/semantic`) | FTS5 es instantáneo (local); semántica tarda ~300-800ms (OpenAI). Loading progresivo por columna mejora la UX percibida |
| 3 | **Scope de búsqueda en UI** | Global + multiselect de manuales | Casillas en el panel izquierdo; ninguna seleccionada = todos los manuales |
| 4 | **Resultados en UI** | Dos columnas en el panel central (FTS \| Semántico) | Permite comparar resultados side by side |
| 5 | **Estado 4 (búsqueda + chunk abierto)** | Columnas colapsan a lista mezclada con badge (FTS/SEM) | Evita 4 columnas simultáneas; el panel derecho permanece |
| 6 | **Overflow de texto** | Previews truncados (ellipsis 1 línea) + click abre panel derecho (texto completo + scroll interno) | Tamaños siempre definidos; `section_path` largo → tooltip nativo |
| 7 | **Panel de similares** | Tercer panel derecho, aparece al clickear cualquier chunk (búsqueda o navegación) | Separa detalle del flujo principal sin romper el layout |
| 8 | **FTS5 sincronización** | Content table (`content="rag_chunks"`) + triggers `AFTER INSERT` / `AFTER DELETE` | No duplica texto en disco; CASCADE FK borra chunks → trigger actualiza el índice FTS5 |

---

## Schema

Añadir a `RAG_SCHEMA_SQL` en `schema.py`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
    text,
    section_path,
    content="rag_chunks",
    content_rowid="id"
);

CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
END;
```

`content="rag_chunks"` evita duplicar el texto. `content_rowid="id"` mapea el rowid de FTS5 con `rag_chunks.id`. Los triggers mantienen el índice sincronizado con el ciclo de vida de los chunks.

---

## API pública — funciones nuevas (`rag_lib/__init__.py`)

### `search_fts()`

```python
async def search_fts(
    query: str,
    db_path: str | Path,
    *,
    manual_ids: list[int] | None = None,
    k: int = 10,
) -> list[SearchResult]:
    """Keyword search using SQLite FTS5. Supports FTS5 operators (AND, OR, NOT, prefix*).

    Returns up to k results sorted by BM25 score descending.
    Score is normalized to [0.0, 1.0] (1.0 = best match).
    Empty query returns [].
    """
```

Implementación:

```sql
SELECT c.*, (-bm25(rag_chunks_fts)) AS raw_score
FROM rag_chunks_fts
JOIN rag_chunks c ON c.rowid = rag_chunks_fts.rowid
WHERE rag_chunks_fts MATCH :query
  [AND c.manual_id IN (...)]
ORDER BY raw_score DESC
LIMIT :k
```

`bm25()` devuelve valores negativos (más negativo = mejor). Se niega para obtener positivo. Normalización al máximo del batch: `score = raw / max(raws)` → rango `[0.0, 1.0]`. Si solo hay un resultado, `score = 1.0`. Si `max(raws) == 0` (no debería ocurrir con MATCH), devuelve `[]` como salvaguarda.

Los chunks son inmutables tras la ingesta, por lo que **no se necesita trigger `AFTER UPDATE`**.

### `search_similar()`

```python
async def search_similar(
    chunk_id: int,
    db_path: str | Path,
    *,
    k: int = 5,
) -> list[SearchResult]:
    """Return top-k chunks semantically similar to the given chunk.

    Uses the existing search() (vector cosine). Excludes chunk_id itself.
    Returns [] if chunk_id does not exist.
    """
```

Implementación:
1. `chunk = await get_chunk(chunk_id, db_path)` → si `None`, retorna `[]`
2. `results = await search(chunk.text, db_path, k=k+1)` — pide uno extra para poder filtrar
3. Filtra el `SearchResult` cuyo `chunk_id == chunk_id`
4. Retorna los primeros `k`

---

## Endpoints nuevos (`rag_lib/web/router.py`)

```
GET /api/rag/search/fts
    ?q=<str>              # query FTS5; vacía → []
    &manual_ids=1,2       # opcional, coma-separados
    &k=10                 # opcional, default 10
    → list[SearchResult.dict()]

GET /api/rag/search/semantic
    ?q=<str>
    &manual_ids=1,2
    &k=10
    → list[SearchResult.dict()]

GET /api/rag/chunks/{chunk_id}/similar
    ?k=5
    → list[SearchResult.dict()]
```

`manual_ids` se parsea como `str` y se convierte a `list[int]` en el endpoint (split por coma, cast).

---

## Layout UI — 4 estados

### Estructura de paneles

```
┌─ Barra de búsqueda (full-width, siempre visible) ──────────────────────────────────┐
│  🔍 Buscar en manuales…                                              [✕ limpiar]   │
└────────────────────────────────────────────────────────────────────────────────────┘
┌─ Panel izquierdo ─┬─ Panel central ──────────────────┬─ Panel derecho (opcional) ─┐
│                   │                                   │                            │
│  MANUALES         │  (chunks / resultados)            │  Chunk #N — detalle        │
│  ☑ D&D 5e         │                                   │  [texto completo scroll]   │
│  ☐ Tasha's        │                                   │  ───────────────           │
│  ☐ Xanathar's     │                                   │  SIMILARES (top-5)         │
│                   │                                   │  #87 · 0.92 · …            │
└───────────────────┴───────────────────────────────────┴────────────────────────────┘
```

### Estado 1 — Normal (sin búsqueda, sin chunk abierto)
- 2 paneles: izquierdo (manuales, multiselect) + central (chunks del manual activo).
- Barra de búsqueda vacía y sin foco.

### Estado 2 — Búsqueda activa (sin chunk abierto)
- Panel central → **dos columnas** lado a lado:
  - **KEYWORDS (FTS5)**: aparece primero (respuesta inmediata).
  - **SEMÁNTICO**: muestra spinner `◌` hasta que OpenAI responde; luego resultados.
- Panel izquierdo muestra las casillas de manuales para filtrar.
- Botón `✕` en la barra limpia la búsqueda y vuelve al Estado 1.

### Estado 3 — Chunk abierto (sin búsqueda)
- 3 paneles: izquierdo + central (chunks, más estrecho) + derecho (detalle + similares).
- Similares cargan automáticamente (`GET /api/rag/chunks/{id}/similar?k=5`).
- `✕` en el panel derecho lo cierra → Estado 1.

### Estado 4 — Búsqueda activa + chunk abierto
- Las dos columnas FTS/Semántico se **colapsan en una lista mezclada** con badge `FTS` o `SEM` por resultado.
- Panel derecho permanece con el chunk activo.
- 3 paneles en total: izquierdo (filtro) + central (lista mezclada) + derecho (detalle).

### Reglas de overflow / tamaño

- **Previews en listas**: 1 línea, `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`.
- **Panel de detalle** (texto del chunk): `max-height: 40vh; overflow-y: auto`.
- **Lista de similares**: `max-height: 30vh; overflow-y: auto`; cada ítem con preview truncado.
- **`section_path`**: truncado con ellipsis + `title="<valor completo>"` (tooltip nativo).
- Click en cualquier item de similares → abre ese chunk en el panel derecho (reemplaza el actual).

---

## Archivos a crear/modificar

### Modificados

| Archivo | Cambio |
|---|---|
| `src/rag_lib/schema.py` | Añade FTS5 virtual table + 2 triggers |
| `src/rag_lib/__init__.py` | Añade `search_fts()`, `search_similar()` |
| `src/rag_lib/web/router.py` | Añade 3 endpoints nuevos |
| `src/rag_lib/web/templates/rag.html` | Barra de búsqueda, 3 paneles, estructura de columnas |
| `src/rag_lib/web/static/js/rag.js` | Estado de búsqueda, fetch paralelo, gestión panel derecho |
| `src/rag_lib/web/static/css/rag.css` | Layout 3 columnas, badges, scroll en detalle |

### Creados

| Archivo | Contenido |
|---|---|
| `tests/rag_lib/test_search_fts.py` | Tests para `search_fts()` y `search_similar()` |
| `tests/rag_lib/test_web_router_a3.py` | Tests para los 3 endpoints nuevos |

---

## Estrategia TDD — ~18 tests estimados

### `tests/rag_lib/test_search_fts.py`

| Test | Descripción |
|---|---|
| `test_search_fts_returns_matching_chunks` | `search_fts("ataque", db)` → chunks que contienen "ataque" |
| `test_search_fts_score_range` | `score` en `[0.0, 1.0]` para todos los resultados |
| `test_search_fts_top_score_is_1` | El resultado con mejor BM25 tiene `score == 1.0` |
| `test_search_fts_manual_ids_filter` | Con 2 manuales en DB, `manual_ids=[1]` retorna solo chunks del manual 1 |
| `test_search_fts_empty_query_returns_empty` | `search_fts("", db)` → `[]` sin error |
| `test_search_fts_no_results_returns_empty` | Query sin matches → `[]` |
| `test_search_fts_multi_term_and` | `search_fts("ataque AND oportunidad", db)` → solo chunks con ambas palabras |
| `test_search_fts_k_respected` | `k=2` → máximo 2 resultados |
| `test_search_fts_result_is_search_result` | Devuelve instancias de `SearchResult` con `chunk.text` correcto |
| `test_search_similar_returns_k_results` | `search_similar(chunk_id, db, k=3)` → 3 resultados |
| `test_search_similar_excludes_self` | El `chunk_id` original no aparece en los resultados |
| `test_search_similar_nonexistent_chunk` | `search_similar(99999, db)` → `[]` sin error |

### `tests/rag_lib/test_web_router_a3.py`

| Test | Descripción |
|---|---|
| `test_search_fts_endpoint_returns_200` | `GET /api/rag/search/fts?q=text` → 200 con lista |
| `test_search_fts_endpoint_empty_query` | `GET /api/rag/search/fts?q=` → 200 con `[]` |
| `test_search_fts_endpoint_manual_ids_filter` | `?q=x&manual_ids=1` → filtra por manual |
| `test_search_semantic_endpoint_returns_200` | `GET /api/rag/search/semantic?q=text` → 200 con lista (mockea `OpenAIEmbedder` via `patch`) |
| `test_similar_endpoint_returns_200` | `GET /api/rag/chunks/{id}/similar?k=3` → 200, sin el chunk original (mockea `OpenAIEmbedder`) |
| `test_similar_endpoint_chunk_not_found` | `GET /api/rag/chunks/99999/similar` → 200 con `[]` |

---

## Criterios de aceptación

- `search_fts("ataque", db)` retorna `SearchResult`s con `score ∈ [0, 1]` y `chunk.text` que contiene "ataque".
- `search_fts("", db)` retorna `[]` sin excepción.
- `search_similar(chunk_id, db, k=5)` retorna hasta 5 resultados, ninguno con `chunk_id` igual al consultado.
- `GET /api/rag/search/fts?q=ataque` → 200 JSON.
- `GET /api/rag/search/semantic?q=ataque` → 200 JSON.
- `GET /api/rag/chunks/{id}/similar` → 200 JSON.
- UI: barra de búsqueda visible, al escribir aparecen dos columnas con loaders independientes.
- UI: click en chunk abre panel derecho con texto completo (scrollable) y lista de similares.
- UI: Estado 4 (búsqueda + chunk abierto) muestra lista mezclada con badges FTS/SEM.
- UI: ningún elemento crece sin límite; todos los textos largos tienen ellipsis + mecanismo de expansión.
- Triggers FTS5: ingestar un PDF → `rag_chunks_fts` contiene las filas. Borrar manual → `rag_chunks_fts` queda vacío para ese manual.
- `ruff check` limpio. Toda la suite rag_lib pasa.
