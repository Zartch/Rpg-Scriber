# Spec: Fase A2 — Embeddings + búsqueda por similitud

**Fecha:** 2026-05-23
**Fase:** A2 del plan-índice `ya-somos-capaces-de-glistening-dongarra.md`
**Prerrequisito:** Fase A1 completa (commit `ac4687b`)

---

## Contexto

A1 entregó el esqueleto de `rag_lib`: parser PDF → chunks → SQLite, API pública async y UI mínima de validación. A2 añade la capa de embeddings y búsqueda por similitud semántica que el Rules Bot (Fase B1) necesita para responder preguntas sobre manuales RPG.

Decisiones globales ya cerradas en el plan-índice que aplican aquí:
- OpenAI `text-embedding-3-small` (1536-d) como implementación por defecto, detrás de interfaz `Embedder`.
- BLOB float32 numpy en SQLite, búsqueda coseno in-memory (sin sqlite-vec en v1).
- `rag_embeddings` tabla separada de `rag_chunks` para permitir re-embeder sin re-parsear.
- API pública `rag_lib.search(query, db_path, *, manual_ids=None, k=10, threshold=None)`.

---

## Decisiones tomadas en este brainstorming

| # | Decisión | Elección | Razón |
|---|---|---|---|
| 1 | **Generación de embeddings** | Integrada en `ingest_pdf` | Un solo comando hace todo; no hay chunks sin embedding tras ingesta |
| 2 | **Inyección del embedder** | Parámetro opcional `embedder: Embedder \| None = None` | Consistente con patrón ABC; tests inyectan `FakeEmbedder` sin llamar a OpenAI |
| 3 | **Caché de vectores en RAM** | Singleton de módulo `_VECTOR_CACHE: dict[str, VectorIndex]` | Encaja con patrón `_PARSER` existente; carga lazy al primer `search()` |
| 4 | **Estructura del subpaquete** | `rag_lib/embedding/` (base, openai, index) | Anticipar múltiples implementaciones (local, otro servicio) justifica subpaquete desde A2 |

---

## Estructura de archivos

### Archivos nuevos

```
src/rag_lib/embedding/
├── __init__.py          # re-exporta Embedder, OpenAIEmbedder, VectorIndex
├── base.py              # Embedder ABC
├── openai.py            # OpenAIEmbedder (text-embedding-3-small)
└── index.py             # VectorIndex (caché RAM + cosine search)

tests/rag_lib/embedding/
├── __init__.py
├── test_base.py         # contrato ABC
├── test_openai.py       # batching + error wrapping (mock cliente)
└── test_index.py        # carga, cosine, recarga incremental

tests/rag_lib/test_store_embeddings.py   # EmbeddingRepo CRUD
tests/rag_lib/test_search.py             # search() end-to-end con FakeEmbedder
```

### Archivos modificados

| Archivo | Cambio |
|---|---|
| `schema.py` | Añade tabla `rag_embeddings` + índice |
| `store.py` | Añade `EmbeddingRepo`; `Database` expone `.embeddings`; `ChunkRepo.insert_many` devuelve `list[int]` de ids; añade `ChunkRepo.get_many_by_ids` |
| `types.py` | Añade `SearchResult` |
| `errors.py` | Añade `EmbeddingError` |
| `__init__.py` | Actualiza `ingest_pdf`; añade `search()`; añade `_VECTOR_CACHE` |

---

## Schema

Añadir a `RAG_SCHEMA_SQL` en `schema.py`:

```sql
CREATE TABLE IF NOT EXISTS rag_embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   INTEGER NOT NULL UNIQUE REFERENCES rag_chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON rag_embeddings(chunk_id);
```

`UNIQUE(chunk_id)` garantiza un embedding por chunk. Re-embeder usa `INSERT OR REPLACE`.

---

## Tipos nuevos

```python
# types.py
@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    manual_id: int
    score: float      # similitud coseno [0.0, 1.0]
    chunk: Chunk      # chunk completo (texto incluido, para construir el prompt)
```

---

## `Embedder` ABC (`embedding/base.py`)

```python
class Embedder(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """Identificador de modelo; se almacena en rag_embeddings.model."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Dimensión del vector."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Devuelve un vector por texto. Lanza EmbeddingError en fallo."""
```

---

## `OpenAIEmbedder` (`embedding/openai.py`)

```python
class OpenAIEmbedder(Embedder):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536
    _BATCH_SIZE = 2048   # límite de la API de OpenAI

    def __init__(self, api_key: str | None = None,
                 model: str = _MODEL) -> None:
        # api_key=None → lee OPENAI_API_KEY del entorno
        ...

    @property
    def model(self) -> str: ...
    @property
    def dim(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Divide en batches de ≤2048
        # openai.AsyncOpenAI().embeddings.create(model=..., input=batch)
        # Envuelve cualquier OpenAIError en EmbeddingError
```

Los textos vacíos se reemplazan por `" "` antes de enviar (la API los rechaza).

---

## `VectorIndex` (`embedding/index.py`)

```python
class VectorIndex:
    def __init__(self) -> None:
        self._matrix: np.ndarray | None = None   # shape (N, dim), float32
        self._chunk_ids: list[int] = []
        self._manual_ids: list[int] = []          # paralelo a _chunk_ids
        self._max_id: int = 0                     # max rag_embeddings.id cargado

    async def ensure_loaded(self, db: Database) -> None:
        """Carga incremental: solo filas con id > self._max_id."""
        rows = await db.embeddings.load_all(min_id=self._max_id)
        if not rows:
            return
        new_vecs = [
            np.frombuffer(r["vector"], dtype=np.float32)
            for r in rows
        ]
        block = np.stack(new_vecs)               # (M, dim)
        self._matrix = (
            np.vstack([self._matrix, block])
            if self._matrix is not None else block
        )
        self._chunk_ids.extend(r["chunk_id"] for r in rows)
        self._manual_ids.extend(r["manual_id"] for r in rows)
        self._max_id = rows[-1]["id"]

    def search(
        self,
        query_vec: list[float],
        *,
        k: int,
        threshold: float | None,
        manual_ids: list[int] | None,
    ) -> list[tuple[int, float]]:
        """Devuelve lista de (chunk_id, score) ordenada descendente."""
        if self._matrix is None or len(self._chunk_ids) == 0:
            return []
        q = np.array(query_vec, dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-10

        mat = self._matrix
        mask = None
        if manual_ids is not None:
            mask = np.array([mid in manual_ids for mid in self._manual_ids])
            mat = mat[mask]
            cids = [cid for cid, ok in zip(self._chunk_ids, mask) if ok]
        else:
            cids = self._chunk_ids

        if len(mat) == 0:
            return []

        norms = np.linalg.norm(mat, axis=1) + 1e-10
        scores = (mat @ q) / norms
        idx = np.argsort(scores)[::-1][:k]
        results = [(cids[i], float(scores[i])) for i in idx]
        if threshold is not None:
            results = [(cid, s) for cid, s in results if s >= threshold]
        return results
```

---

## `EmbeddingRepo` (`store.py`)

```python
class EmbeddingRepo:
    async def upsert_many(self, rows: list[dict]) -> None:
        # rows: [{chunk_id, vector_bytes, dim, model}, ...]
        # INSERT OR REPLACE INTO rag_embeddings (chunk_id, vector, dim, model)
        # executemany en una transacción

    async def load_all(self, min_id: int = 0) -> list[dict]:
        # SELECT e.id, e.chunk_id, c.manual_id, e.vector
        # FROM rag_embeddings e
        # JOIN rag_chunks c ON c.id = e.chunk_id
        # WHERE e.id > min_id
        # ORDER BY e.id
        # Devuelve dicts {id, chunk_id, manual_id, vector (bytes)}
```

`Database.__init__` añade `self.embeddings = EmbeddingRepo(self)`.

---

## Cambios en `ChunkRepo`

```python
# insert_many ahora devuelve list[int] (los chunk_ids insertados)
async def insert_many(self, manual_id: int, chunks: list[dict]) -> list[int]:
    ...  # igual que antes, pero acumula lastrowid de cada fila
    # Nota: executemany no expone lastrowid individual;
    # usar execute() en loop o SELECT id WHERE manual_id=? ORDER BY seq

# Nuevo método
async def get_many_by_ids(self, ids: list[int]) -> list[dict]:
    # SELECT * FROM rag_chunks WHERE id IN (?,?,...)
    # Devuelve en el mismo orden que ids
```

---

## API pública (`__init__.py`)

### `ingest_pdf` actualizado

```python
async def ingest_pdf(
    pdf_path: str | Path,
    *,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None = None,
) -> IngestResult:
    # ... lógica A1 igual hasta insertar chunks ...
    if chunks:
        inserted_ids = await db.chunks.insert_many(manual_id, chunks)
        _emb = embedder or OpenAIEmbedder()
        vectors = await _emb.embed([c["text"] for c in chunks])
        await db.embeddings.upsert_many([
            {"chunk_id": cid,
             "vector_bytes": np.array(v, dtype=np.float32).tobytes(),
             "dim": _emb.dim, "model": _emb.model}
            for cid, v in zip(inserted_ids, vectors)
        ])
        _VECTOR_CACHE.pop(str(db_path), None)   # fuerza recarga incremental
    ...
```

### `search()` nuevo

```python
async def search(
    query: str,
    db_path: str | Path,
    *,
    manual_ids: list[int] | None = None,
    k: int = 10,
    threshold: float | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    _emb = embedder or OpenAIEmbedder()
    [query_vec] = await _emb.embed([query])

    key = str(db_path)
    if key not in _VECTOR_CACHE:
        _VECTOR_CACHE[key] = VectorIndex()

    db = Database(db_path)
    await db.connect()
    try:
        await _VECTOR_CACHE[key].ensure_loaded(db)
        hits = _VECTOR_CACHE[key].search(
            query_vec, k=k, threshold=threshold, manual_ids=manual_ids
        )
        if not hits:
            return []
        rows = await db.chunks.get_many_by_ids([cid for cid, _ in hits])
        row_map = {r["id"]: r for r in rows}
        return [
            SearchResult(
                chunk_id=cid,
                manual_id=row_map[cid]["manual_id"],
                score=score,
                chunk=_row_to_chunk(row_map[cid]),
            )
            for cid, score in hits
            if cid in row_map
        ]
    finally:
        await db.close()
```

---

## Errores

```python
# errors.py
class EmbeddingError(Exception):
    """Fallo al generar embeddings (API, red, cuota)."""
```

---

## `FakeEmbedder` (en `tests/rag_lib/conftest.py`)

```python
class FakeEmbedder(Embedder):
    model = "fake-model"
    dim = 4

    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self._vectors = vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._vectors is not None:
            return self._vectors[: len(texts)]
        # Vector determinista por texto: seed individual por cada texto
        return [
            np.random.default_rng(abs(hash(t)) % (2**32)).random(self.dim).tolist()
            for t in texts
        ]
```

---

## Estrategia TDD — 25 tests estimados

| Archivo | Tests clave |
|---|---|
| `embedding/test_base.py` | `FakeEmbedder` cumple contrato; `embed()` devuelve N vecs de dim correcta |
| `embedding/test_openai.py` | Batching ≤2048 hace múltiples llamadas; `EmbeddingError` envuelve `OpenAIError`; texto vacío se reemplaza por espacio |
| `embedding/test_index.py` | `ensure_loaded` carga desde DB; cosine correcto para vectores ortogonales; top-k respetado; `threshold` filtra; `manual_ids` filtra; carga incremental detecta filas nuevas |
| `test_store_embeddings.py` | `upsert_many` → `load_all` roundtrip; cascade al borrar chunk; `INSERT OR REPLACE` en re-embed no duplica |
| `test_search.py` | `search()` retorna `SearchResult` con texto correcto; respeta `k`; respeta `threshold`; respeta `manual_ids`; caché hit en segunda llamada (sin DB query para vectores); índice vacío retorna `[]` |
| `test_integration_ingest.py` (ampliado) | `ingest_pdf` con `FakeEmbedder` guarda embeddings; re-ingesta idempotente no duplica; `delete_manual` cascade borra embeddings |

---

## Criterios de aceptación

- `ingest_pdf(pdf, name, db, embedder=FakeEmbedder())` → DB tiene `rag_embeddings` con una fila por chunk.
- `search("query", db, k=3, embedder=FakeEmbedder())` → lista de 3 `SearchResult` con `score` y `chunk.text` correctos.
- `search(..., manual_ids=[1])` filtra cuando hay 2 manuales en la misma DB.
- Re-ingesta del mismo PDF → `was_already_ingested=True`, `rag_embeddings` sin duplicados.
- `delete_manual(id, db)` → `rag_embeddings` vacía para ese manual (cascade).
- Segunda llamada a `search()` sin ingestas intermedias no lanza queries de vectores a DB (caché hit).
- Todos los tests pasan, `ruff check` limpio.

---

## Dependencias nuevas

- `numpy` (para serialización BLOB y operaciones matriciales) — añadir a `[project.dependencies]` en `pyproject.toml`.

`openai` ya es dependencia existente.
