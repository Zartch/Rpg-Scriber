# Fase A2 — Embeddings + búsqueda por similitud

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir embeddings y búsqueda semántica a `rag_lib`: `ingest_pdf` genera vectores OpenAI y los persiste; `search()` hace búsqueda coseno in-memory con caché singleton de módulo.

**Architecture:** Subpaquete `rag_lib/embedding/` con ABC `Embedder`, `OpenAIEmbedder` y `VectorIndex`. `EmbeddingRepo` en `store.py`. Caché RAM `_VECTOR_CACHE: dict[str, VectorIndex]` en `__init__.py`, carga lazy al primer `search()`, recarga incremental tras cada ingest.

**Tech Stack:** `numpy` (vectores BLOB float32, cosine similarity), `openai` AsyncClient (ya instalado), `aiosqlite` (ya instalado), `pytest` + `pytest-asyncio` con `asyncio_mode="auto"`.

---

## Mapa de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Modify | `pyproject.toml` | Añadir `numpy>=1.26` a deps |
| Modify | `src/rag_lib/schema.py` | Añadir tabla `rag_embeddings` |
| Modify | `src/rag_lib/types.py` | Añadir `SearchResult` |
| Modify | `src/rag_lib/errors.py` | Añadir `EmbeddingError` |
| Modify | `src/rag_lib/store.py` | Añadir `EmbeddingRepo`; `ChunkRepo.insert_many` devuelve `list[int]`; añadir `ChunkRepo.get_many_by_ids` |
| Create | `src/rag_lib/embedding/__init__.py` | Re-exporta `Embedder`, `OpenAIEmbedder`, `VectorIndex` |
| Create | `src/rag_lib/embedding/base.py` | `Embedder` ABC |
| Create | `src/rag_lib/embedding/openai.py` | `OpenAIEmbedder` (text-embedding-3-small, batching ≤2048) |
| Create | `src/rag_lib/embedding/index.py` | `VectorIndex` (caché RAM, cosine search, recarga incremental) |
| Modify | `src/rag_lib/__init__.py` | Actualiza `ingest_pdf`; añade `search()`; añade `_VECTOR_CACHE` |
| Modify | `tests/rag_lib/conftest.py` | Añade `FakeEmbedder` |
| Create | `tests/rag_lib/embedding/__init__.py` | Paquete vacío |
| Create | `tests/rag_lib/embedding/test_base.py` | Contrato `Embedder` ABC |
| Create | `tests/rag_lib/embedding/test_openai.py` | `OpenAIEmbedder` con mock del cliente |
| Create | `tests/rag_lib/embedding/test_index.py` | `VectorIndex`: carga, cosine, filtros, recarga incremental |
| Create | `tests/rag_lib/test_store_embeddings.py` | `EmbeddingRepo` CRUD, cascade |
| Create | `tests/rag_lib/test_search.py` | `search()` end-to-end con `FakeEmbedder` |
| Modify | `tests/rag_lib/test_integration_ingest.py` | Ampliar: embeddings tras ingest, cascade en delete |

---

## Task 1: Setup — deps, schema, tipos, errores

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/rag_lib/schema.py`
- Modify: `src/rag_lib/types.py`
- Modify: `src/rag_lib/errors.py`

- [ ] **Step 1: Añadir numpy a pyproject.toml**

En `pyproject.toml`, la sección `[project] dependencies`:
```toml
dependencies = [
    "discord.py[voice]>=2.3",
    "discord-ext-voice-recv>=0.5.2a179",
    "davey>=0.1.0",
    "openai>=1.0",
    "anthropic>=0.20",
    "aiohttp>=3.9",
    "aiosqlite>=0.19",
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "python-dotenv>=1.0",
    "jinja2>=3.1",
    "pdfplumber>=0.10",
    "tiktoken>=0.7",
    "numpy>=1.26",
]
```

- [ ] **Step 2: Añadir tabla `rag_embeddings` a schema.py**

Al final de la cadena `RAG_SCHEMA_SQL` en `src/rag_lib/schema.py`, antes del `"""` de cierre:

```python
RAG_SCHEMA_SQL = """\
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rag_manuals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    source_hash   TEXT NOT NULL UNIQUE,
    page_count    INTEGER NOT NULL,
    file_size     INTEGER NOT NULL,
    parser        TEXT NOT NULL DEFAULT 'pdfplumber',
    ingested_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id     INTEGER NOT NULL REFERENCES rag_manuals(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    chunk_type    TEXT NOT NULL CHECK (chunk_type IN ('prose', 'table')),
    page          INTEGER NOT NULL,
    page_end      INTEGER,
    section_path  TEXT,
    text          TEXT NOT NULL,
    text_hash     TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manual_id, seq)
);

CREATE TABLE IF NOT EXISTS rag_embeddisi
ngs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   INTEGER NOT NULL UNIQUE REFERENCES rag_chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_manual_page ON rag_chunks(manual_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_type        ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_hash        ON rag_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk   ON rag_embeddings(chunk_id);
"""
```

- [ ] **Step 3: Añadir `SearchResult` a types.py**

En `src/rag_lib/types.py`, después de `IngestResult`:

```python
@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    manual_id: int
    score: float      # similitud coseno [0.0, 1.0]
    chunk: Chunk      # chunk completo con texto
```

- [ ] **Step 4: Añadir `EmbeddingError` a errors.py**

`src/rag_lib/errors.py` completo:

```python
"""rag_lib custom exceptions."""
from __future__ import annotations


class IngestError(Exception):
    """Base class for ingestion errors."""


class PdfParseError(IngestError):
    """Raised when the PDF cannot be parsed."""


class ManualNotFound(Exception):
    """Raised when a manual_id does not exist in the database."""


class EmbeddingError(Exception):
    """Raised when embedding generation fails (API error, network, quota)."""
```

- [ ] **Step 5: Instalar numpy y verificar**

```bash
pip install -e ".[dev]"
python -c "import numpy; print(numpy.__version__)"
```

Expected: versión ≥ 1.26 impresa sin error.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/rag_lib/schema.py src/rag_lib/types.py src/rag_lib/errors.py
git commit -m "feat(rag-a2): add rag_embeddings schema, SearchResult type, EmbeddingError, numpy dep"
```

---

## Task 2: EmbeddingRepo + cambios en ChunkRepo (TDD)

**Files:**
- Modify: `src/rag_lib/store.py`
- Create: `tests/rag_lib/test_store_embeddings.py`

- [ ] **Step 1: Escribir tests para EmbeddingRepo**

Crear `tests/rag_lib/test_store_embeddings.py`:

```python
"""Tests for EmbeddingRepo and updated ChunkRepo methods."""
from __future__ import annotations

import numpy as np
import pytest

from rag_lib.store import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def manual_id(db: Database) -> int:
    return await db.manuals.insert(
        name="Test", source_path="/tmp/t.pdf", source_hash="hash1",
        page_count=1, file_size=100, parser="pdfplumber",
    )


@pytest.fixture
async def chunk_ids(db: Database, manual_id: int) -> list[int]:
    chunks = [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Alpha", "text_hash": "ha", "token_count": 1},
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Beta", "text_hash": "hb", "token_count": 1},
    ]
    return await db.chunks.insert_many(manual_id, chunks)


async def test_connect_creates_rag_embeddings_table(db: Database) -> None:
    cur = await db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_embeddings'"
    )
    row = await cur.fetchone()
    assert row is not None


async def test_insert_many_returns_chunk_ids(db: Database, manual_id: int) -> None:
    chunks = [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Hello", "text_hash": "h1", "token_count": 1},
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "World", "text_hash": "h2", "token_count": 1},
    ]
    ids = await db.chunks.insert_many(manual_id, chunks)
    assert len(ids) == 2
    assert all(isinstance(i, int) for i in ids)
    assert ids[0] != ids[1]


async def test_get_many_by_ids_returns_in_order(db: Database, manual_id: int) -> None:
    chunks = [
        {"seq": i, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": f"text {i}", "text_hash": f"h{i}", "token_count": 1}
        for i in range(3)
    ]
    ids = await db.chunks.insert_many(manual_id, chunks)
    # Ask in reverse order
    result = await db.chunks.get_many_by_ids(list(reversed(ids)))
    assert [r["id"] for r in result] == list(reversed(ids))


async def test_get_many_by_ids_empty_returns_empty(db: Database) -> None:
    result = await db.chunks.get_many_by_ids([])
    assert result == []


async def test_upsert_many_stores_embeddings(
    db: Database, chunk_ids: list[int]
) -> None:
    vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec.tobytes(), "dim": 4, "model": "fake"},
    ])
    rows = await db.embeddings.load_all()
    assert len(rows) == 1
    assert rows[0]["chunk_id"] == chunk_ids[0]


async def test_upsert_many_replace_on_duplicate_chunk_id(
    db: Database, chunk_ids: list[int]
) -> None:
    vec1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    vec2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec1.tobytes(), "dim": 4, "model": "fake"},
    ])
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec2.tobytes(), "dim": 4, "model": "fake"},
    ])
    rows = await db.embeddings.load_all()
    assert len(rows) == 1
    loaded = np.frombuffer(rows[0]["vector"], dtype=np.float32)
    assert np.allclose(loaded, vec2)


async def test_load_all_returns_manual_id(
    db: Database, manual_id: int, chunk_ids: list[int]
) -> None:
    vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec.tobytes(), "dim": 4, "model": "fake"},
    ])
    rows = await db.embeddings.load_all()
    assert rows[0]["manual_id"] == manual_id


async def test_load_all_min_id_returns_only_new(
    db: Database, chunk_ids: list[int]
) -> None:
    vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec.tobytes(), "dim": 4, "model": "fake"},
        {"chunk_id": chunk_ids[1], "vector_bytes": vec.tobytes(), "dim": 4, "model": "fake"},
    ])
    all_rows = await db.embeddings.load_all()
    first_id = all_rows[0]["id"]
    newer = await db.embeddings.load_all(min_id=first_id)
    assert len(newer) == 1
    assert newer[0]["chunk_id"] == chunk_ids[1]


async def test_delete_chunk_cascades_to_embeddings(
    db: Database, manual_id: int, chunk_ids: list[int]
) -> None:
    vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    await db.embeddings.upsert_many([
        {"chunk_id": chunk_ids[0], "vector_bytes": vec.tobytes(), "dim": 4, "model": "fake"},
    ])
    await db.manuals.delete(manual_id)
    rows = await db.embeddings.load_all()
    assert rows == []
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_store_embeddings.py -v
```

Expected: todos fallen con `AttributeError: 'Database' object has no attribute 'embeddings'` o similares.

- [ ] **Step 3: Implementar cambios en store.py**

`src/rag_lib/store.py` completo:

```python
"""rag_lib database layer: Database class + repositories."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

from rag_lib.schema import RAG_SCHEMA_SQL

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite wrapper for rag_lib."""

    def __init__(self, db_path: str | Path = "rag.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self.manuals = ManualRepo(self)
        self.chunks = ChunkRepo(self)
        self.embeddings = EmbeddingRepo(self)

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(RAG_SCHEMA_SQL)
        await self._conn.commit()
        logger.debug("rag_lib database connected: %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn


class ManualRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def find_by_hash(self, source_hash: str) -> dict[str, Any] | None:
        cur = await self._db.conn.execute(
            "SELECT * FROM rag_manuals WHERE source_hash = ?", (source_hash,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def insert(
        self, *, name: str, source_path: str, source_hash: str,
        page_count: int, file_size: int, parser: str,
    ) -> int:
        cur = await self._db.conn.execute(
            """INSERT INTO rag_manuals (name, source_path, source_hash, page_count, file_size, parser)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, source_path, source_hash, page_count, file_size, parser),
        )
        await self._db.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def list_all(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            """SELECT m.*, COUNT(c.id) AS chunk_count
               FROM rag_manuals m
               LEFT JOIN rag_chunks c ON c.manual_id = m.id
               GROUP BY m.id
               ORDER BY m.ingested_at DESC"""
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, manual_id: int) -> bool:
        cur = await self._db.conn.execute(
            "DELETE FROM rag_manuals WHERE id = ?", (manual_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount > 0


class ChunkRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_many(self, manual_id: int, chunks: list[dict[str, Any]]) -> list[int]:
        """Insert chunks and return the list of new chunk ids in insertion order."""
        ids: list[int] = []
        for c in chunks:
            cur = await self._db.conn.execute(
                """INSERT INTO rag_chunks
                   (manual_id, seq, chunk_type, page, page_end, section_path,
                    text, text_hash, token_count)
                   VALUES (:manual_id, :seq, :chunk_type, :page, :page_end,
                           :section_path, :text, :text_hash, :token_count)""",
                {"manual_id": manual_id, **c},
            )
            assert cur.lastrowid is not None
            ids.append(cur.lastrowid)
        await self._db.conn.commit()
        return ids

    async def list_by_manual(
        self, manual_id: int, *, offset: int = 0, limit: int = 50,
    ) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            """SELECT * FROM rag_chunks WHERE manual_id = ?
               ORDER BY seq LIMIT ? OFFSET ?""",
            (manual_id, limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_id(self, chunk_id: int) -> dict[str, Any] | None:
        cur = await self._db.conn.execute(
            "SELECT * FROM rag_chunks WHERE id = ?", (chunk_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_many_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Return chunks for the given ids, in the same order as ids."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        cur = await self._db.conn.execute(
            f"SELECT * FROM rag_chunks WHERE id IN ({placeholders})",
            ids,
        )
        rows = await cur.fetchall()
        row_map = {dict(r)["id"]: dict(r) for r in rows}
        return [row_map[i] for i in ids if i in row_map]


class EmbeddingRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, rows: list[dict[str, Any]]) -> None:
        """Insert or replace embeddings. rows: [{chunk_id, vector_bytes, dim, model}]"""
        await self._db.conn.executemany(
            """INSERT OR REPLACE INTO rag_embeddings (chunk_id, vector, dim, model)
               VALUES (:chunk_id, :vector_bytes, :dim, :model)""",
            rows,
        )
        await self._db.conn.commit()

    async def load_all(self, min_id: int = 0) -> list[dict[str, Any]]:
        """Load embeddings with id > min_id, joining manual_id from rag_chunks."""
        cur = await self._db.conn.execute(
            """SELECT e.id, e.chunk_id, c.manual_id, e.vector
               FROM rag_embeddings e
               JOIN rag_chunks c ON c.id = e.chunk_id
               WHERE e.id > ?
               ORDER BY e.id""",
            (min_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_store_embeddings.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Verificar que los tests existentes de store siguen en verde**

```bash
python -m pytest tests/rag_lib/test_store.py -v
```

Expected: 16 passed (el cambio de `insert_many` es compatible — los tests no usaban el valor de retorno).

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/store.py tests/rag_lib/test_store_embeddings.py
git commit -m "feat(rag-a2): add EmbeddingRepo, update ChunkRepo.insert_many to return ids"
```

---

## Task 3: Embedder ABC + subpaquete embedding + FakeEmbedder

**Files:**
- Create: `src/rag_lib/embedding/__init__.py`
- Create: `src/rag_lib/embedding/base.py`
- Create: `tests/rag_lib/embedding/__init__.py`
- Create: `tests/rag_lib/embedding/test_base.py`
- Modify: `tests/rag_lib/conftest.py`

- [ ] **Step 1: Escribir tests para el contrato ABC**

Crear `tests/rag_lib/embedding/__init__.py` vacío.

Crear `tests/rag_lib/embedding/test_base.py`:

```python
"""Tests for Embedder ABC contract using FakeEmbedder."""
from __future__ import annotations

import pytest

from rag_lib.embedding import Embedder


async def test_fake_embedder_returns_one_vector_per_text(fake_embedder) -> None:
    texts = ["hello", "world", "foo"]
    result = await fake_embedder.embed(texts)
    assert len(result) == 3


async def test_fake_embedder_vector_has_correct_dim(fake_embedder) -> None:
    result = await fake_embedder.embed(["text"])
    assert len(result[0]) == fake_embedder.dim


async def test_fake_embedder_is_embedder_subclass(fake_embedder) -> None:
    assert isinstance(fake_embedder, Embedder)


async def test_fake_embedder_model_is_string(fake_embedder) -> None:
    assert isinstance(fake_embedder.model, str)


async def test_fake_embedder_with_fixed_vectors(fake_embedder_factory) -> None:
    vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    emb = fake_embedder_factory(vectors=vecs)
    result = await emb.embed(["a", "b"])
    assert result[0] == [1.0, 0.0, 0.0, 0.0]
    assert result[1] == [0.0, 1.0, 0.0, 0.0]


async def test_fake_embedder_deterministic_for_same_text(fake_embedder) -> None:
    r1 = await fake_embedder.embed(["same text"])
    r2 = await fake_embedder.embed(["same text"])
    assert r1 == r2


async def test_fake_embedder_different_texts_differ(fake_embedder) -> None:
    r = await fake_embedder.embed(["alpha", "beta"])
    assert r[0] != r[1]
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/embedding/test_base.py -v
```

Expected: `ModuleNotFoundError: No module named 'rag_lib.embedding'`.

- [ ] **Step 3: Crear `embedding/base.py`**

```python
"""Embedder ABC — interface for all embedding implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """Model identifier stored in rag_embeddings.model."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Vector dimension."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text. Raises EmbeddingError on failure."""
```

- [ ] **Step 4: Crear `embedding/__init__.py`**

```python
"""rag_lib embedding subpackage."""
from __future__ import annotations

from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex
from rag_lib.embedding.openai import OpenAIEmbedder

__all__ = ["Embedder", "OpenAIEmbedder", "VectorIndex"]
```

Nota: `VectorIndex` y `OpenAIEmbedder` aún no existen — se crean en Tasks 4 y 5. Por ahora `__init__.py` fallará al importar, pero los tests de `test_base.py` solo necesitan `Embedder`. Inicialmente, pon solo `Embedder`:

```python
"""rag_lib embedding subpackage."""
from __future__ import annotations

from rag_lib.embedding.base import Embedder

__all__ = ["Embedder"]
```

Se completará en Task 5.

- [ ] **Step 5: Añadir `FakeEmbedder` y fixtures a `tests/rag_lib/conftest.py`**

Añadir al final de `tests/rag_lib/conftest.py`:

```python
import numpy as np

from rag_lib.embedding.base import Embedder


class FakeEmbedder(Embedder):
    """Deterministic test embedder. Does NOT call any external API."""

    _MODEL = "fake-model"
    _DIM = 4

    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self._vectors = vectors

    @property
    def model(self) -> str:
        return self._MODEL

    @property
    def dim(self) -> int:
        return self._DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._vectors is not None:
            return self._vectors[: len(texts)]
        return [
            np.random.default_rng(abs(hash(t)) % (2**32)).random(self._DIM).tolist()
            for t in texts
        ]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_embedder_factory():
    return FakeEmbedder
```

- [ ] **Step 6: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/embedding/test_base.py -v
```

Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add src/rag_lib/embedding/ tests/rag_lib/embedding/ tests/rag_lib/conftest.py
git commit -m "feat(rag-a2): add Embedder ABC, embedding subpackage scaffold, FakeEmbedder"
```

---

## Task 4: VectorIndex (TDD)

**Files:**
- Create: `src/rag_lib/embedding/index.py`
- Create: `tests/rag_lib/embedding/test_index.py`

- [ ] **Step 1: Escribir tests para VectorIndex**

Crear `tests/rag_lib/embedding/test_index.py`:

```python
"""Tests for VectorIndex: load, cosine search, filters, incremental reload."""
from __future__ import annotations

import numpy as np
import pytest

from rag_lib.embedding.index import VectorIndex
from rag_lib.store import Database


@pytest.fixture
async def db_with_two_chunks(tmp_path):
    """DB with 2 chunks and their embeddings: vec1=[1,0,0,0], vec2=[0,1,0,0]."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    manual_id = await db.manuals.insert(
        name="M1", source_path="m1.pdf", source_hash="s1",
        page_count=1, file_size=100, parser="pdfplumber",
    )
    ids = await db.chunks.insert_many(manual_id, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Alpha", "text_hash": "ha", "token_count": 1},
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Beta", "text_hash": "hb", "token_count": 1},
    ])
    await db.embeddings.upsert_many([
        {"chunk_id": ids[0], "vector_bytes": np.array([1,0,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
        {"chunk_id": ids[1], "vector_bytes": np.array([0,1,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
    ])
    yield db, ids, manual_id
    await db.close()


async def test_ensure_loaded_populates_matrix(db_with_two_chunks) -> None:
    db, chunk_ids, _ = db_with_two_chunks
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    assert idx._matrix is not None
    assert idx._matrix.shape == (2, 4)


async def test_search_returns_closest_chunk(db_with_two_chunks) -> None:
    db, chunk_ids, _ = db_with_two_chunks
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    # query aligned with chunk 0 ([1,0,0,0])
    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=1, threshold=None, manual_ids=None)
    assert len(hits) == 1
    assert hits[0][0] == chunk_ids[0]
    assert hits[0][1] == pytest.approx(1.0, abs=1e-5)


async def test_search_top_k_respected(db_with_two_chunks) -> None:
    db, chunk_ids, _ = db_with_two_chunks
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=1, threshold=None, manual_ids=None)
    assert len(hits) == 1


async def test_search_threshold_filters_low_scores(db_with_two_chunks) -> None:
    db, chunk_ids, _ = db_with_two_chunks
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    # query aligned with chunk 0; chunk 1 score ≈ 0.0 → filtered by threshold=0.5
    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=10, threshold=0.5, manual_ids=None)
    assert all(score >= 0.5 for _, score in hits)
    assert len(hits) == 1


async def test_search_manual_ids_filter(tmp_path) -> None:
    """Two manuals, search with manual_ids=[1] returns only manual 1 chunks."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    m1 = await db.manuals.insert(
        name="M1", source_path="m1.pdf", source_hash="s1",
        page_count=1, file_size=100, parser="pdfplumber",
    )
    m2 = await db.manuals.insert(
        name="M2", source_path="m2.pdf", source_hash="s2",
        page_count=1, file_size=100, parser="pdfplumber",
    )
    ids1 = await db.chunks.insert_many(m1, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "M1 chunk", "text_hash": "hm1", "token_count": 1},
    ])
    ids2 = await db.chunks.insert_many(m2, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "M2 chunk", "text_hash": "hm2", "token_count": 1},
    ])
    await db.embeddings.upsert_many([
        {"chunk_id": ids1[0], "vector_bytes": np.array([1,0,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
        {"chunk_id": ids2[0], "vector_bytes": np.array([1,0,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
    ])
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=10, threshold=None, manual_ids=[m1])
    assert all(cid == ids1[0] for cid, _ in hits)
    await db.close()


async def test_search_empty_index_returns_empty(tmp_path) -> None:
    db = Database(str(tmp_path / "empty.db"))
    await db.connect()
    idx = VectorIndex()
    await idx.ensure_loaded(db)
    hits = idx.search([1.0, 0.0, 0.0, 0.0], k=5, threshold=None, manual_ids=None)
    assert hits == []
    await db.close()


async def test_ensure_loaded_incremental_reload(tmp_path) -> None:
    """Loading twice only fetches new rows the second time."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    m = await db.manuals.insert(
        name="M", source_path="m.pdf", source_hash="sm",
        page_count=1, file_size=100, parser="pdfplumber",
    )
    ids = await db.chunks.insert_many(m, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "First", "text_hash": "hf", "token_count": 1},
    ])
    await db.embeddings.upsert_many([
        {"chunk_id": ids[0], "vector_bytes": np.array([1,0,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
    ])

    idx = VectorIndex()
    await idx.ensure_loaded(db)
    assert idx._matrix.shape[0] == 1
    first_max_id = idx._max_id

    # Add a second chunk
    ids2 = await db.chunks.insert_many(m, [
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Second", "text_hash": "hs", "token_count": 1},
    ])
    await db.embeddings.upsert_many([
        {"chunk_id": ids2[0], "vector_bytes": np.array([0,1,0,0], dtype=np.float32).tobytes(), "dim": 4, "model": "fake"},
    ])

    await idx.ensure_loaded(db)
    assert idx._matrix.shape[0] == 2
    assert idx._max_id > first_max_id
    await db.close()
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/embedding/test_index.py -v
```

Expected: `ImportError: cannot import name 'VectorIndex' from 'rag_lib.embedding.index'`.

- [ ] **Step 3: Implementar `embedding/index.py`**

```python
"""VectorIndex — in-RAM cosine-similarity index backed by SQLite embeddings."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from rag_lib.store import Database


class VectorIndex:
    """Lazy-loading in-RAM vector index for one db_path.

    Call ensure_loaded(db) before search(). Subsequent calls to ensure_loaded
    are incremental: only rows with id > self._max_id are fetched.
    """

    def __init__(self) -> None:
        self._matrix: np.ndarray | None = None   # shape (N, dim), float32
        self._chunk_ids: list[int] = []
        self._manual_ids: list[int] = []
        self._max_id: int = 0

    async def ensure_loaded(self, db: Database) -> None:
        rows = await db.embeddings.load_all(min_id=self._max_id)
        if not rows:
            return
        new_vecs = [
            np.frombuffer(r["vector"], dtype=np.float32)
            for r in rows
        ]
        block = np.stack(new_vecs)
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
        """Return list of (chunk_id, score) sorted by descending cosine similarity."""
        if self._matrix is None or not self._chunk_ids:
            return []

        q = np.array(query_vec, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-10:
            return []
        q = q / q_norm

        if manual_ids is not None:
            manual_set = set(manual_ids)
            mask = np.array([mid in manual_set for mid in self._manual_ids])
            mat = self._matrix[mask]
            cids = [cid for cid, ok in zip(self._chunk_ids, mask) if ok]
        else:
            mat = self._matrix
            cids = self._chunk_ids

        if len(mat) == 0:
            return []

        norms = np.linalg.norm(mat, axis=1) + 1e-10
        scores = (mat @ q) / norms

        top_k = min(k, len(scores))
        idx = np.argsort(scores)[::-1][:top_k]
        results = [(cids[i], float(scores[i])) for i in idx]

        if threshold is not None:
            results = [(cid, s) for cid, s in results if s >= threshold]
        return results
```

- [ ] **Step 4: Actualizar `embedding/__init__.py` para exportar VectorIndex**

```python
"""rag_lib embedding subpackage."""
from __future__ import annotations

from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex

__all__ = ["Embedder", "VectorIndex"]
```

(`OpenAIEmbedder` se añadirá en Task 5.)

- [ ] **Step 5: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/embedding/test_index.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/embedding/index.py src/rag_lib/embedding/__init__.py tests/rag_lib/embedding/test_index.py tests/rag_lib/embedding/__init__.py
git commit -m "feat(rag-a2): add VectorIndex with lazy load and incremental reload"
```

---

## Task 5: OpenAIEmbedder (TDD con mock)

**Files:**
- Create: `src/rag_lib/embedding/openai.py`
- Create: `tests/rag_lib/embedding/test_openai.py`

- [ ] **Step 1: Escribir tests para OpenAIEmbedder**

Crear `tests/rag_lib/embedding/test_openai.py`:

```python
"""Tests for OpenAIEmbedder — API calls are mocked."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag_lib.embedding.openai import OpenAIEmbedder
from rag_lib.errors import EmbeddingError


def _make_openai_response(vectors: list[list[float]]):
    """Build a mock openai embeddings response."""
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors]
    return resp


async def test_embed_returns_one_vector_per_text() -> None:
    vecs = [[0.1, 0.2], [0.3, 0.4]]
    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = AsyncMock(return_value=_make_openai_response(vecs))
        embedder = OpenAIEmbedder(api_key="fake-key")
        result = await embedder.embed(["hello", "world"])
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2])
    assert result[1] == pytest.approx([0.3, 0.4])


async def test_embed_batches_large_input() -> None:
    """Inputs exceeding _BATCH_SIZE trigger multiple API calls."""
    batch_size = 3  # override for test
    total = 7
    texts = [f"text {i}" for i in range(total)]
    vecs = [[float(i)] for i in range(total)]

    call_count = 0

    async def fake_create(model, input):
        nonlocal call_count
        call_count += 1
        start = (call_count - 1) * batch_size
        end = start + len(input)
        return _make_openai_response(vecs[start:end])

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = fake_create
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._BATCH_SIZE = batch_size
        result = await embedder.embed(texts)

    assert len(result) == total
    assert call_count == 3   # ceil(7/3) = 3


async def test_embed_empty_string_replaced_by_space() -> None:
    """Empty strings must be replaced with a space before sending to API."""
    captured_inputs: list[list[str]] = []

    async def fake_create(model, input):
        captured_inputs.append(list(input))
        return _make_openai_response([[0.0]] * len(input))

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = fake_create
        embedder = OpenAIEmbedder(api_key="fake-key")
        await embedder.embed(["", "real text", "   "])

    sent = captured_inputs[0]
    assert sent[0] == " "
    assert sent[2] == " "
    assert sent[1] == "real text"


async def test_embed_wraps_api_error_in_embedding_error() -> None:
    from openai import OpenAIError

    with patch("rag_lib.embedding.openai.AsyncOpenAI") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.embeddings.create = AsyncMock(
            side_effect=OpenAIError("quota exceeded")
        )
        embedder = OpenAIEmbedder(api_key="fake-key")
        with pytest.raises(EmbeddingError, match="quota exceeded"):
            await embedder.embed(["hello"])


async def test_model_property_returns_correct_value() -> None:
    with patch("rag_lib.embedding.openai.AsyncOpenAI"):
        embedder = OpenAIEmbedder(api_key="fake-key")
    assert embedder.model == "text-embedding-3-small"


async def test_dim_property_returns_1536() -> None:
    with patch("rag_lib.embedding.openai.AsyncOpenAI"):
        embedder = OpenAIEmbedder(api_key="fake-key")
    assert embedder.dim == 1536
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/embedding/test_openai.py -v
```

Expected: `ImportError: cannot import name 'OpenAIEmbedder' from 'rag_lib.embedding.openai'`.

- [ ] **Step 3: Implementar `embedding/openai.py`**

```python
"""OpenAIEmbedder — text-embedding-3-small via OpenAI async API."""
from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI, OpenAIError

from rag_lib.embedding.base import Embedder
from rag_lib.errors import EmbeddingError

logger = logging.getLogger(__name__)


class OpenAIEmbedder(Embedder):
    _MODEL = "text-embedding-3-small"
    _DIM = 1536
    _BATCH_SIZE = 2048

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,
    ) -> None:
        self._model_name = model
        self._client = AsyncOpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = [t if t.strip() else " " for t in texts]
        results: list[list[float]] = []
        try:
            for i in range(0, len(cleaned), self._BATCH_SIZE):
                batch = cleaned[i : i + self._BATCH_SIZE]
                response = await self._client.embeddings.create(
                    model=self._model_name,
                    input=batch,
                )
                results.extend(item.embedding for item in response.data)
        except OpenAIError as exc:
            raise EmbeddingError(str(exc)) from exc
        return results
```

- [ ] **Step 4: Actualizar `embedding/__init__.py` para exportar OpenAIEmbedder**

```python
"""rag_lib embedding subpackage."""
from __future__ import annotations

from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex
from rag_lib.embedding.openai import OpenAIEmbedder

__all__ = ["Embedder", "OpenAIEmbedder", "VectorIndex"]
```

- [ ] **Step 5: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/embedding/test_openai.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/embedding/openai.py src/rag_lib/embedding/__init__.py tests/rag_lib/embedding/test_openai.py
git commit -m "feat(rag-a2): add OpenAIEmbedder with batching and EmbeddingError wrapping"
```

---

## Task 6: Tests RED para ingest + search, luego implementación completa de `__init__.py`

Se escriben primero los tests de integración (ingest con embeddings) y los tests de `search()`, se verifica que fallen, y luego se implementa `__init__.py` de una sola vez para pasar ambos conjuntos.

**Files:**
- Modify: `src/rag_lib/__init__.py`
- Modify: `tests/rag_lib/test_integration_ingest.py`
- Create: `tests/rag_lib/test_search.py`

- [ ] **Step 1: Escribir tests nuevos para ingest con embeddings**

Añadir al final de `tests/rag_lib/test_integration_ingest.py`:

```python
async def test_ingest_saves_embeddings_for_all_chunks(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Embedded", db_path=db_path, embedder=fake_embedder,
    )
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.embeddings.load_all()
        assert len(rows) == result.chunks_created
    finally:
        await db.close()


async def test_ingest_twice_does_not_duplicate_embeddings(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    result2 = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    assert result2.was_already_ingested
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.embeddings.load_all()
        # No duplicates: unique chunk_id
        chunk_ids = [r["chunk_id"] for r in rows]
        assert len(chunk_ids) == len(set(chunk_ids))
    finally:
        await db.close()


async def test_delete_manual_cascades_to_embeddings(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="ToDelete", db_path=db_path, embedder=fake_embedder,
    )
    await rag_lib.delete_manual(result.manual_id, db_path)
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.embeddings.load_all()
        assert rows == []
    finally:
        await db.close()
```

Añadir el import que falta en la cabecera del archivo:

```python
from rag_lib.store import Database
```

- [ ] **Step 2: Verificar que los tests de integración fallan**

```bash
python -m pytest tests/rag_lib/test_integration_ingest.py::test_ingest_saves_embeddings_for_all_chunks -v
```

Expected: `TypeError: ingest_pdf() got an unexpected keyword argument 'embedder'`.

- [ ] **Step 2b: Escribir `tests/rag_lib/test_search.py` y verificar que también falla**

Crear `tests/rag_lib/test_search.py`:

```python
"""End-to-end tests for rag_lib.search() using FakeEmbedder."""
from __future__ import annotations

from pathlib import Path

import pytest

import rag_lib
from rag_lib.embedding.base import Embedder
from rag_lib.types import SearchResult


@pytest.fixture(autouse=True)
def clear_vector_cache():
    rag_lib._VECTOR_CACHE.clear()
    yield
    rag_lib._VECTOR_CACHE.clear()


async def test_search_returns_search_results(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)


async def test_search_result_has_chunk_text(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert all(isinstance(r.chunk.text, str) and len(r.chunk.text) > 0 for r in results)


async def test_search_respects_k_limit(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, k=2, embedder=fake_embedder)
    assert len(results) <= 2


async def test_search_respects_threshold(
    simple_pdf: Path, tmp_path: Path,
) -> None:
    db = tmp_path / "rag.db"

    chunk_vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]

    class CyclicEmbedder(Embedder):
        def __init__(self, vecs: list[list[float]]) -> None:
            self._cycle = vecs
        @property
        def model(self) -> str: return "cyclic"
        @property
        def dim(self) -> int: return 4
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [self._cycle[i % len(self._cycle)] for i in range(len(texts))]

    emb = CyclicEmbedder(chunk_vecs)
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=emb)

    query_emb = CyclicEmbedder([[1.0, 0.0, 0.0, 0.0]])
    results_no_thresh = await rag_lib.search("q", db, k=10, embedder=query_emb)
    results_high_thresh = await rag_lib.search("q", db, k=10, threshold=0.9, embedder=query_emb)
    assert len(results_high_thresh) < len(results_no_thresh)
    assert all(r.score >= 0.9 for r in results_high_thresh)


async def test_search_manual_ids_filter(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    r1 = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Manual A", db_path=db, embedder=fake_embedder,
    )
    results_filtered = await rag_lib.search(
        "query", db, manual_ids=[r1.manual_id], embedder=fake_embedder,
    )
    assert all(r.manual_id == r1.manual_id for r in results_filtered)


async def test_search_empty_db_returns_empty_list(
    tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "empty.db"
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert results == []


async def test_search_scores_are_between_0_and_1(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert all(0.0 <= r.score <= 1.0 for r in results)


async def test_search_results_sorted_descending_by_score(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
```

```bash
python -m pytest tests/rag_lib/test_search.py::test_search_returns_search_results -v
```

Expected: `TypeError: ingest_pdf() got an unexpected keyword argument 'embedder'` (o `AttributeError` por `_VECTOR_CACHE`).

- [ ] **Step 3: Actualizar `src/rag_lib/__init__.py`**

Reemplazar el contenido completo de `src/rag_lib/__init__.py`:

```python
"""rag_lib — reusable RAG module. Public API."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import numpy as np

from rag_lib.chunking import run_chunker
from rag_lib.embedding.base import Embedder
from rag_lib.embedding.index import VectorIndex
from rag_lib.embedding.openai import OpenAIEmbedder
from rag_lib.errors import EmbeddingError as EmbeddingError
from rag_lib.errors import PdfParseError as PdfParseError
from rag_lib.parsing.pdfplumber_parser import PdfplumberParser
from rag_lib.store import Database
from rag_lib.types import Chunk, IngestResult, Manual, SearchResult

logger = logging.getLogger(__name__)

_PARSER = PdfplumberParser()
_VECTOR_CACHE: dict[str, VectorIndex] = {}


async def ingest_pdf(
    pdf_path: str | Path,
    *,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None = None,
) -> IngestResult:
    """Ingest a PDF. Idempotent: same SHA256 → returns existing manual_id.

    Generates and stores embeddings for all chunks using *embedder*
    (default: OpenAIEmbedder from OPENAI_API_KEY env var).
    """
    pdf_path = Path(pdf_path)
    file_bytes = pdf_path.read_bytes()
    source_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size = len(file_bytes)

    db = Database(db_path)
    await db.connect()
    try:
        existing = await db.manuals.find_by_hash(source_hash)
        if existing:
            logger.info(
                "rag_lib.ingest: %s already ingested as manual_id=%d",
                manual_name, existing["id"],
            )
            return IngestResult(
                manual_id=existing["id"], chunks_created=0, was_already_ingested=True,
            )

        logger.info("rag_lib.ingest: parsing %s", pdf_path.name)
        pages = await asyncio.to_thread(_PARSER.parse, pdf_path)
        page_count = len(pages)
        chunks = run_chunker(pages)

        manual_id = await db.manuals.insert(
            name=manual_name,
            source_path=str(pdf_path),
            source_hash=source_hash,
            page_count=page_count,
            file_size=file_size,
            parser="pdfplumber",
        )

        if chunks:
            inserted_ids = await db.chunks.insert_many(manual_id, chunks)
            _emb = embedder or OpenAIEmbedder()
            vectors = await _emb.embed([c["text"] for c in chunks])
            await db.embeddings.upsert_many([
                {
                    "chunk_id": cid,
                    "vector_bytes": np.array(v, dtype=np.float32).tobytes(),
                    "dim": _emb.dim,
                    "model": _emb.model,
                }
                for cid, v in zip(inserted_ids, vectors)
            ])
            _VECTOR_CACHE.pop(str(db_path), None)

        logger.info(
            "rag_lib.ingest: saved manual_id=%d with %d chunks", manual_id, len(chunks),
        )
        return IngestResult(
            manual_id=manual_id, chunks_created=len(chunks), was_already_ingested=False,
        )
    finally:
        await db.close()


async def list_manuals(db_path: str | Path) -> list[Manual]:
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.manuals.list_all()
        return [_row_to_manual(r) for r in rows]
    finally:
        await db.close()


async def delete_manual(manual_id: int, db_path: str | Path) -> bool:
    """Delete a manual and its chunks + embeddings (cascade). Returns True if existed."""
    db = Database(db_path)
    await db.connect()
    try:
        return await db.manuals.delete(manual_id)
    finally:
        await db.close()


async def get_chunk(chunk_id: int, db_path: str | Path) -> Chunk | None:
    db = Database(db_path)
    await db.connect()
    try:
        row = await db.chunks.get_by_id(chunk_id)
        return _row_to_chunk(row) if row else None
    finally:
        await db.close()


async def list_chunks(
    manual_id: int,
    db_path: str | Path,
    *,
    offset: int = 0,
    limit: int = 50,
) -> list[Chunk]:
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.chunks.list_by_manual(manual_id, offset=offset, limit=limit)
        return [_row_to_chunk(r) for r in rows]
    finally:
        await db.close()


async def search(
    query: str,
    db_path: str | Path,
    *,
    manual_ids: list[int] | None = None,
    k: int = 10,
    threshold: float | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Search for chunks by semantic similarity.

    Returns up to *k* results sorted by descending cosine score.
    If *manual_ids* is given, only chunks from those manuals are considered.
    """
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
            query_vec, k=k, threshold=threshold, manual_ids=manual_ids,
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


# ---------------------------------------------------------------------------
# Row → dataclass helpers
# ---------------------------------------------------------------------------

def _row_to_manual(row: dict[str, Any]) -> Manual:
    return Manual(
        id=row["id"],
        name=row["name"],
        source_path=row["source_path"],
        source_hash=row["source_hash"],
        page_count=row["page_count"],
        file_size=row["file_size"],
        parser=row["parser"],
        ingested_at=row["ingested_at"],
        chunk_count=row.get("chunk_count", 0),
    )


def _row_to_chunk(row: dict[str, Any]) -> Chunk:
    return Chunk(
        id=row["id"],
        manual_id=row["manual_id"],
        seq=row["seq"],
        chunk_type=row["chunk_type"],
        page=row["page"],
        page_end=row.get("page_end"),
        section_path=row.get("section_path"),
        text=row["text"],
        text_hash=row["text_hash"],
        token_count=row["token_count"],
    )
```

- [ ] **Step 4: Verificar tests de integración ampliados**

```bash
python -m pytest tests/rag_lib/test_integration_ingest.py -v
```

Expected: 11 passed (8 originales + 3 nuevos).

- [ ] **Step 5: Verificar tests de search**

```bash
python -m pytest tests/rag_lib/test_search.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/__init__.py tests/rag_lib/test_integration_ingest.py tests/rag_lib/test_search.py
git commit -m "feat(rag-a2): integrate embedding into ingest_pdf, add search() with vector cache"
```

---

## Task 7: Suite completa y lint — OBSOLETO (ver Task 6 Step 2b para test_search.py)

> test_search.py se crea en Task 6 Step 2b junto con la implementación. Este bloque se conserva como referencia pero los pasos ya están cubiertos.

Crear `tests/rag_lib/test_search.py`:

```python
"""End-to-end tests for rag_lib.search() using FakeEmbedder."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import rag_lib
from rag_lib.types import SearchResult


# Clear module-level vector cache between tests to avoid cross-contamination.
@pytest.fixture(autouse=True)
def clear_vector_cache():
    rag_lib._VECTOR_CACHE.clear()
    yield
    rag_lib._VECTOR_CACHE.clear()


async def test_search_returns_search_results(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)


async def test_search_result_has_chunk_text(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("any query", db, embedder=fake_embedder)
    assert all(isinstance(r.chunk.text, str) and len(r.chunk.text) > 0 for r in results)


async def test_search_respects_k_limit(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, k=2, embedder=fake_embedder)
    assert len(results) <= 2


async def test_search_respects_threshold(
    simple_pdf: Path, tmp_path: Path,
) -> None:
    db = tmp_path / "rag.db"

    # Use controlled vectors so we know exact scores.
    # chunk 0 → [1,0,0,0], chunk 1 → [0,1,0,0]
    # query → [1,0,0,0]: chunk 0 score≈1.0, chunk 1 score≈0.0
    from tests.rag_lib.conftest import FakeEmbedder

    chunk_vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    # ingest needs one vec per chunk; simple_pdf has at least 1 chunk
    # Use a single-vec embedder that repeats the pattern cyclically
    class CyclicEmbedder(FakeEmbedder):
        def __init__(self, vecs):
            super().__init__()
            self._cycle = vecs
        async def embed(self, texts):
            return [self._cycle[i % len(self._cycle)] for i in range(len(texts))]

    emb = CyclicEmbedder(chunk_vecs)
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=emb)

    # query is [1,0,0,0] → aligned with chunk 0
    query_emb = CyclicEmbedder([[1.0, 0.0, 0.0, 0.0]])
    results_no_thresh = await rag_lib.search("q", db, k=10, embedder=query_emb)
    results_high_thresh = await rag_lib.search("q", db, k=10, threshold=0.9, embedder=query_emb)
    assert len(results_high_thresh) < len(results_no_thresh)
    assert all(r.score >= 0.9 for r in results_high_thresh)


async def test_search_manual_ids_filter(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    r1 = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Manual A", db_path=db, embedder=fake_embedder,
    )

    import hashlib, shutil
    pdf2 = tmp_path / "copy.pdf"
    # Create a distinct PDF so it doesn't deduplicate
    src_bytes = simple_pdf.read_bytes()
    # We can't easily create a second PDF here; skip if only 1 manual available
    # Instead test that filtering by [manual_id] returns only results from that manual
    results_all = await rag_lib.search("query", db, embedder=fake_embedder)
    results_filtered = await rag_lib.search(
        "query", db, manual_ids=[r1.manual_id], embedder=fake_embedder,
    )
    assert all(r.manual_id == r1.manual_id for r in results_filtered)
    assert len(results_filtered) <= len(results_all)


async def test_search_empty_db_returns_empty_list(
    tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "empty.db"
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert results == []


async def test_search_scores_are_between_0_and_1(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    assert all(0.0 <= r.score <= 1.0 for r in results)


async def test_search_results_sorted_descending_by_score(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(simple_pdf, manual_name="Book", db_path=db, embedder=fake_embedder)
    results = await rag_lib.search("query", db, embedder=fake_embedder)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_search.py -v
```

Expected: 7 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/rag_lib/test_search.py
git commit -m "feat(rag-a2): add search() end-to-end tests with FakeEmbedder"
```

---

## Task 8: Suite completa y lint (verificación final)

**Files:** ninguno nuevo

- [ ] **Step 1: Correr toda la suite rag_lib**

```bash
python -m pytest tests/rag_lib/ -v
```

Expected: todos los tests pasan (≥ 94 tests: 69 A1 + ~25 A2).

- [ ] **Step 2: Correr lint**

```bash
ruff check src/rag_lib tests/rag_lib
```

Expected: `All checks passed!`

- [ ] **Step 3: Correr suite completa para detectar regresiones**

```bash
python -m pytest tests/ -q --ignore=tests/rag_lib/
```

Expected: mismos resultados que antes de A2 (1 fallo pre-existente `test_tts_config_from_toml`).

- [ ] **Step 4: Commit final de la fase**

```bash
git add -A
git commit -m "feat(rag-a2): complete embeddings + semantic search — Fase A2"
```
