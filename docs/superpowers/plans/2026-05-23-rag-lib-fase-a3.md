# Fase A3 — Búsqueda híbrida + vista detalle con chunks similares

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir búsqueda híbrida (FTS5 keywords + vectores semánticos, dos endpoints independientes) y un panel de detalle con chunks similares a la UI de `rag_lib`.

**Architecture:** SQLite FTS5 virtual table sincronizada via triggers; `search_fts()` y `search_similar()` en la API pública; tres endpoints REST nuevos; frontend refactorizado con barra de búsqueda, panel central (dos columnas o lista mezclada) y panel derecho (detalle + similares). Cuatro estados UI según si hay búsqueda activa y/o chunk abierto.

**Tech Stack:** SQLite FTS5 (ya incluido en Python stdlib), `aiosqlite` (ya instalado), `fastapi` + `httpx` para tests de endpoints, ES modules browser-nativos para el frontend.

---

## Mapa de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Modify | `src/rag_lib/schema.py` | Añade FTS5 virtual table + triggers AFTER INSERT/DELETE |
| Modify | `src/rag_lib/__init__.py` | Añade `search_fts()` y `search_similar()` |
| Modify | `src/rag_lib/web/router.py` | Añade 3 endpoints: `/search/fts`, `/search/semantic`, `/chunks/{id}/similar` |
| Modify | `src/rag_lib/web/templates/rag.html` | Barra de búsqueda, 3 paneles, estructura de columnas |
| Modify | `src/rag_lib/web/static/js/rag.js` | Estado de búsqueda, fetch paralelo, gestión panel derecho |
| Modify | `src/rag_lib/web/static/css/rag.css` | Layout 3 paneles, badges FTS/SEM, overflow/scroll |
| Create | `tests/rag_lib/test_search_fts.py` | Tests para `search_fts()` y `search_similar()` |
| Create | `tests/rag_lib/test_web_router_a3.py` | Tests para los 3 endpoints nuevos |

---

## Task 1: FTS5 schema + triggers (TDD)

**Files:**
- Modify: `src/rag_lib/schema.py`
- Test: `tests/rag_lib/test_search_fts.py` (primeros tests)

- [ ] **Step 1: Escribir tests de schema FTS5**

Crear `tests/rag_lib/test_search_fts.py`:

```python
"""Tests for FTS5 schema, search_fts(), and search_similar()."""
from __future__ import annotations

from pathlib import Path

import pytest

import rag_lib
from rag_lib.store import Database
from rag_lib.types import SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def fts_db(tmp_path: Path):
    """DB with 3 chunks in Manual A (2 about 'ataque', 1 about 'magia')."""
    db_path = tmp_path / "fts.db"
    db = Database(str(db_path))
    await db.connect()
    manual_id = await db.manuals.insert(
        name="Manual A", source_path="a.pdf", source_hash="sha_a",
        page_count=2, file_size=1000, parser="pdfplumber",
    )
    await db.chunks.insert_many(manual_id, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Combate",
         "text": "El ataque de oportunidad se realiza cuando el enemigo abandona tu alcance.",
         "text_hash": "h1", "token_count": 15},
        {"seq": 1, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Magia",
         "text": "Los hechizos de concentracion requieren que el mago mantenga el foco.",
         "text_hash": "h2", "token_count": 14},
        {"seq": 2, "chunk_type": "prose", "page": 2, "page_end": None,
         "section_path": "Combate",
         "text": "El ataque cuerpo a cuerpo permite golpear al enemigo adyacente.",
         "text_hash": "h3", "token_count": 13},
    ])
    yield db, manual_id, db_path
    await db.close()


@pytest.fixture
async def fts_db_two_manuals(tmp_path: Path):
    """DB with Manual A (3 chunks) and Manual B (1 chunk about 'ataque')."""
    db_path = tmp_path / "two.db"
    db = Database(str(db_path))
    await db.connect()
    m_a = await db.manuals.insert(
        name="Manual A", source_path="a.pdf", source_hash="sha_a",
        page_count=2, file_size=1000, parser="pdfplumber",
    )
    m_b = await db.manuals.insert(
        name="Manual B", source_path="b.pdf", source_hash="sha_b",
        page_count=1, file_size=500, parser="pdfplumber",
    )
    await db.chunks.insert_many(m_a, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Combate",
         "text": "El ataque de oportunidad ocurre en combate.",
         "text_hash": "ha1", "token_count": 10},
    ])
    await db.chunks.insert_many(m_b, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": "Reglas",
         "text": "El ataque a distancia usa arcos y ballistas.",
         "text_hash": "hb1", "token_count": 10},
    ])
    yield db, m_a, m_b, db_path
    await db.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

async def test_connect_creates_fts_table(fts_db) -> None:
    db, _, _ = fts_db
    cur = await db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_chunks_fts'"
    )
    row = await cur.fetchone()
    assert row is not None


async def test_insert_trigger_populates_fts(fts_db) -> None:
    db, _, _ = fts_db
    cur = await db.conn.execute(
        "SELECT rowid FROM rag_chunks_fts WHERE rag_chunks_fts MATCH 'ataque'"
    )
    rows = await cur.fetchall()
    assert len(rows) == 2  # chunks 0 and 2 contain 'ataque'


async def test_delete_trigger_removes_from_fts(fts_db) -> None:
    db, manual_id, _ = fts_db
    await db.manuals.delete(manual_id)
    cur = await db.conn.execute(
        "SELECT rowid FROM rag_chunks_fts WHERE rag_chunks_fts MATCH 'ataque'"
    )
    rows = await cur.fetchall()
    assert rows == []
```

- [ ] **Step 2: Verificar que los tests de schema fallan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py::test_connect_creates_fts_table tests/rag_lib/test_search_fts.py::test_insert_trigger_populates_fts tests/rag_lib/test_search_fts.py::test_delete_trigger_removes_from_fts -v
```

Expected: FAIL — `AssertionError` porque la tabla `rag_chunks_fts` no existe todavía.

- [ ] **Step 3: Añadir FTS5 a `schema.py`**

Reemplazar el contenido completo de `src/rag_lib/schema.py`:

```python
"""rag_lib SQLite schema DDL."""
from __future__ import annotations

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

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   INTEGER NOT NULL UNIQUE REFERENCES rag_chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
    text,
    section_path,
    content="rag_chunks",
    content_rowid="id"
);

CREATE INDEX IF NOT EXISTS idx_chunks_manual_page ON rag_chunks(manual_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_type        ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_hash        ON rag_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk   ON rag_embeddings(chunk_id);

CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
END;
"""
```

- [ ] **Step 4: Verificar que los tests de schema pasan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py::test_connect_creates_fts_table tests/rag_lib/test_search_fts.py::test_insert_trigger_populates_fts tests/rag_lib/test_search_fts.py::test_delete_trigger_removes_from_fts -v
```

Expected: 3 passed.

- [ ] **Step 5: Verificar que los tests existentes de store siguen en verde**

```bash
python -m pytest tests/rag_lib/test_store.py tests/rag_lib/test_store_embeddings.py -v
```

Expected: todos pasan (los triggers se activan en insert pero no rompen nada).

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/schema.py tests/rag_lib/test_search_fts.py
git commit -m "feat(rag-a3): add FTS5 virtual table and sync triggers to schema"
```

---

## Task 2: `search_fts()` (TDD)

**Files:**
- Modify: `src/rag_lib/__init__.py`
- Modify: `tests/rag_lib/test_search_fts.py`

- [ ] **Step 1: Añadir tests de `search_fts()` a `test_search_fts.py`**

Añadir al final de `tests/rag_lib/test_search_fts.py`:

```python
# ---------------------------------------------------------------------------
# search_fts() tests
# ---------------------------------------------------------------------------

async def test_search_fts_returns_matching_chunks(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("ataque", db_path)
    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert all("ataque" in r.chunk.text.lower() for r in results)


async def test_search_fts_score_in_range(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("ataque", db_path)
    assert all(0.0 <= r.score <= 1.0 for r in results)


async def test_search_fts_top_score_is_1(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("ataque", db_path)
    assert results[0].score == pytest.approx(1.0)


async def test_search_fts_empty_query_returns_empty(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("", db_path)
    assert results == []


async def test_search_fts_no_match_returns_empty(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("xyzzy_nonexistent_word", db_path)
    assert results == []


async def test_search_fts_k_respected(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("ataque", db_path, k=1)
    assert len(results) == 1


async def test_search_fts_result_has_chunk_text(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("magia", db_path)
    assert len(results) == 1
    assert isinstance(results[0].chunk.text, str)
    assert len(results[0].chunk.text) > 0


async def test_search_fts_manual_ids_filter(fts_db_two_manuals) -> None:
    db, m_a, m_b, db_path = fts_db_two_manuals
    results = await rag_lib.search_fts("ataque", db_path, manual_ids=[m_a])
    assert all(r.manual_id == m_a for r in results)
    results_b = await rag_lib.search_fts("ataque", db_path, manual_ids=[m_b])
    assert all(r.manual_id == m_b for r in results_b)


async def test_search_fts_multiterm_and(fts_db) -> None:
    _, _, db_path = fts_db
    # Only chunk 0 contains both 'ataque' and 'oportunidad'
    results = await rag_lib.search_fts("ataque AND oportunidad", db_path)
    assert len(results) == 1
    assert "oportunidad" in results[0].chunk.text
```

- [ ] **Step 2: Verificar que los tests de `search_fts` fallan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py -k "search_fts" -v
```

Expected: `AttributeError: module 'rag_lib' has no attribute 'search_fts'`.

- [ ] **Step 3: Implementar `search_fts()` en `src/rag_lib/__init__.py`**

Añadir después de la función `search()` y antes del bloque de helpers:

```python
async def search_fts(
    query: str,
    db_path: str | Path,
    *,
    manual_ids: list[int] | None = None,
    k: int = 10,
) -> list[SearchResult]:
    """Keyword search using SQLite FTS5. Supports FTS5 operators (AND, OR, NOT, prefix*).

    Score is normalized to [0.0, 1.0] (1.0 = best match in the result set).
    Empty or whitespace-only query returns [].
    """
    if not query.strip():
        return []

    db = Database(db_path)
    await db.connect()
    try:
        if manual_ids is not None:
            placeholders = ",".join("?" * len(manual_ids))
            sql = f"""
                SELECT c.*, (-bm25(rag_chunks_fts)) AS raw_score
                FROM rag_chunks_fts
                JOIN rag_chunks c ON c.rowid = rag_chunks_fts.rowid
                WHERE rag_chunks_fts MATCH ?
                  AND c.manual_id IN ({placeholders})
                ORDER BY raw_score DESC
                LIMIT ?
            """
            params: list = [query, *manual_ids, k]
        else:
            sql = """
                SELECT c.*, (-bm25(rag_chunks_fts)) AS raw_score
                FROM rag_chunks_fts
                JOIN rag_chunks c ON c.rowid = rag_chunks_fts.rowid
                WHERE rag_chunks_fts MATCH ?
                ORDER BY raw_score DESC
                LIMIT ?
            """
            params = [query, k]

        try:
            cur = await db.conn.execute(sql, params)
        except Exception:
            return []

        rows = await cur.fetchall()
        if not rows:
            return []

        dicts = [dict(r) for r in rows]
        raw_scores = [d["raw_score"] for d in dicts]
        max_score = max(raw_scores)
        if max_score <= 0:
            return []

        return [
            SearchResult(
                chunk_id=d["id"],
                manual_id=d["manual_id"],
                score=d["raw_score"] / max_score,
                chunk=_row_to_chunk(d),
            )
            for d in dicts
        ]
    finally:
        await db.close()
```

- [ ] **Step 4: Verificar que los tests de `search_fts` pasan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py -k "search_fts" -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/__init__.py tests/rag_lib/test_search_fts.py
git commit -m "feat(rag-a3): add search_fts() with FTS5 BM25 scoring and manual_ids filter"
```

---

## Task 3: `search_similar()` (TDD)

**Files:**
- Modify: `src/rag_lib/__init__.py`
- Modify: `tests/rag_lib/test_search_fts.py`

- [ ] **Step 1: Añadir tests de `search_similar()` a `test_search_fts.py`**

Añadir al final de `tests/rag_lib/test_search_fts.py`:

```python
# ---------------------------------------------------------------------------
# search_similar() tests
# ---------------------------------------------------------------------------

async def test_search_similar_returns_results(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "sim.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)
    assert len(chunks) >= 2, "need at least 2 chunks"
    target_id = chunks[0].id
    results = await rag_lib.search_similar(target_id, db_path, k=3, embedder=fake_embedder)
    assert len(results) <= 3
    assert all(isinstance(r, SearchResult) for r in results)


async def test_search_similar_excludes_self(
    simple_pdf: Path, tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "sim.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)
    target_id = chunks[0].id
    results = await rag_lib.search_similar(target_id, db_path, k=10, embedder=fake_embedder)
    assert all(r.chunk_id != target_id for r in results)


async def test_search_similar_nonexistent_chunk_returns_empty(
    tmp_path: Path, fake_embedder,
) -> None:
    db_path = tmp_path / "empty.db"
    results = await rag_lib.search_similar(99999, db_path, k=5, embedder=fake_embedder)
    assert results == []
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py -k "search_similar" -v
```

Expected: `AttributeError: module 'rag_lib' has no attribute 'search_similar'`.

- [ ] **Step 3: Implementar `search_similar()` en `src/rag_lib/__init__.py`**

Añadir justo después de `search_fts()`:

```python
async def search_similar(
    chunk_id: int,
    db_path: str | Path,
    *,
    k: int = 5,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Return top-k chunks semantically similar to chunk_id (self excluded).

    Returns [] if chunk_id does not exist.
    """
    chunk = await get_chunk(chunk_id, db_path)
    if chunk is None:
        return []
    results = await search(chunk.text, db_path, k=k + 1, embedder=embedder)
    return [r for r in results if r.chunk_id != chunk_id][:k]
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_search_fts.py -k "search_similar" -v
```

Expected: 3 passed.

- [ ] **Step 5: Correr todos los tests de `test_search_fts.py`**

```bash
python -m pytest tests/rag_lib/test_search_fts.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/__init__.py tests/rag_lib/test_search_fts.py
git commit -m "feat(rag-a3): add search_similar() — semantic top-k excluding self"
```

---

## Task 4: Endpoints REST nuevos (TDD)

**Files:**
- Create: `tests/rag_lib/test_web_router_a3.py`
- Modify: `src/rag_lib/web/router.py`

- [ ] **Step 1: Crear `tests/rag_lib/test_web_router_a3.py`**

```python
"""Tests for A3 web router endpoints: /search/fts, /search/semantic, /chunks/{id}/similar."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

import rag_lib
from rag_lib.web import build_router


@pytest.fixture
async def client(tmp_path: Path, simple_pdf: Path, fake_embedder):
    db_path = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Test Manual", db_path=db_path, embedder=fake_embedder,
    )
    app = FastAPI()
    app.include_router(build_router(db_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, db_path, result.manual_id


async def test_search_fts_returns_200(client) -> None:
    c, db_path, manual_id = client
    chunks = await rag_lib.list_chunks(manual_id, db_path=db_path)
    first_word = chunks[0].text.split()[0] if chunks else "el"
    resp = await c.get(f"/api/rag/search/fts?q={first_word}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_search_fts_empty_query_returns_empty_list(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/fts?q=")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_fts_manual_ids_filter(client) -> None:
    c, _, manual_id = client
    resp = await c.get(f"/api/rag/search/fts?q=el&manual_ids={manual_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["manual_id"] == manual_id for r in data)


async def test_search_fts_unknown_manual_id_returns_empty(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/fts?q=el&manual_ids=9999")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_semantic_returns_200(client, fake_embedder) -> None:
    c, _, _ = client
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get("/api/rag/search/semantic?q=combate")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_search_semantic_empty_query_returns_empty(client) -> None:
    c, _, _ = client
    resp = await c.get("/api/rag/search/semantic?q=")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_similar_endpoint_returns_200(client, fake_embedder) -> None:
    c, db_path, manual_id = client
    chunks = await rag_lib.list_chunks(manual_id, db_path=db_path)
    chunk_id = chunks[0].id
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get(f"/api/rag/chunks/{chunk_id}/similar?k=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert all(r["chunk_id"] != chunk_id for r in data)


async def test_similar_endpoint_nonexistent_chunk_returns_empty(client, fake_embedder) -> None:
    c, _, _ = client
    with patch("rag_lib.OpenAIEmbedder", return_value=fake_embedder):
        resp = await c.get("/api/rag/chunks/99999/similar")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_web_router_a3.py -v
```

Expected: `404 Not Found` en todos los tests de search/similar (endpoints no existen todavía).

- [ ] **Step 3: Añadir los 3 endpoints a `src/rag_lib/web/router.py`**

Reemplazar el contenido completo de `src/rag_lib/web/router.py`:

```python
"""rag_lib web router — REST endpoints + /rag HTML page."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

import rag_lib

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_router(db_path: str | Path) -> APIRouter:
    """Return an APIRouter with /rag page and /api/rag/* endpoints."""
    router = APIRouter()
    db = str(db_path)

    @router.get("/rag", response_class=HTMLResponse, include_in_schema=False)
    async def rag_page() -> str:
        return (_TEMPLATES_DIR / "rag.html").read_text(encoding="utf-8")

    @router.get("/api/rag/manuals")
    async def list_manuals_endpoint():
        manuals = await rag_lib.list_manuals(db_path=db)
        return [dataclasses.asdict(m) for m in manuals]

    @router.get("/api/rag/manuals/{manual_id}/chunks")
    async def list_chunks_endpoint(manual_id: int, offset: int = 0, limit: int = 50):
        chunks = await rag_lib.list_chunks(manual_id, db_path=db, offset=offset, limit=limit)
        return [dataclasses.asdict(c) for c in chunks]

    @router.get("/api/rag/chunks/{chunk_id}")
    async def get_chunk_endpoint(chunk_id: int):
        chunk = await rag_lib.get_chunk(chunk_id, db_path=db)
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return dataclasses.asdict(chunk)

    @router.delete("/api/rag/manuals/{manual_id}", status_code=204)
    async def delete_manual_endpoint(manual_id: int):
        deleted = await rag_lib.delete_manual(manual_id, db_path=db)
        if not deleted:
            raise HTTPException(status_code=404, detail="Manual not found")

    @router.get("/api/rag/search/fts")
    async def search_fts_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        ids = [int(x) for x in manual_ids.split(",") if x.strip()] if manual_ids.strip() else None
        results = await rag_lib.search_fts(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/search/semantic")
    async def search_semantic_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        if not q.strip():
            return []
        ids = [int(x) for x in manual_ids.split(",") if x.strip()] if manual_ids.strip() else None
        results = await rag_lib.search(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/chunks/{chunk_id}/similar")
    async def similar_chunks_endpoint(chunk_id: int, k: int = 5):
        results = await rag_lib.search_similar(chunk_id, db_path=db, k=k)
        return [dataclasses.asdict(r) for r in results]

    return router
```

- [ ] **Step 4: Verificar que los tests de router A3 pasan**

```bash
python -m pytest tests/rag_lib/test_web_router_a3.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Verificar que los tests de router originales siguen en verde**

```bash
python -m pytest tests/rag_lib/test_web_router.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/web/router.py tests/rag_lib/test_web_router_a3.py
git commit -m "feat(rag-a3): add /search/fts, /search/semantic, /chunks/{id}/similar endpoints"
```

---

## Task 5: Frontend HTML + CSS

**Files:**
- Modify: `src/rag_lib/web/templates/rag.html`
- Modify: `src/rag_lib/web/static/css/rag.css`

No hay TDD para HTML/CSS. Se verifica visualmente en el Task 7.

- [ ] **Step 1: Reemplazar `rag.html`**

Reemplazar el contenido completo de `src/rag_lib/web/templates/rag.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RAG — Manuales</title>
  <link rel="stylesheet" href="/static/css/rag.css">
</head>
<body>
  <div id="search-bar">
    <span class="search-icon">🔍</span>
    <input id="search-input" type="text" placeholder="Buscar en manuales… (FTS5 + semántico)">
    <button id="search-clear" hidden title="Limpiar búsqueda">✕</button>
  </div>

  <div id="app">
    <!-- Panel izquierdo: manuales -->
    <div id="manuals-panel">
      <h2>Manuales</h2>
      <ul id="manuals-list">
        <li class="loading">Cargando…</li>
      </ul>
    </div>

    <!-- Panel central: chunks o resultados de búsqueda -->
    <div id="center-panel">
      <!-- Modo navegación (sin búsqueda) -->
      <div id="chunks-area">
        <h2 id="chunks-title">Selecciona un manual</h2>
        <table id="chunks-table" hidden>
          <thead>
            <tr>
              <th>#</th><th>Pág.</th><th>Tipo</th><th>Sección</th><th>Texto</th>
            </tr>
          </thead>
          <tbody id="chunks-body"></tbody>
        </table>
        <button id="load-more" hidden>Cargar más ↓</button>
      </div>

      <!-- Modo búsqueda: dos columnas -->
      <div id="search-results" hidden>
        <div id="search-columns">
          <div class="search-col" id="fts-col">
            <div class="col-header">
              <span>Keywords</span>
              <span class="badge badge-fts">FTS5</span>
            </div>
            <div id="fts-results" class="results-list"></div>
          </div>
          <div class="search-col" id="sem-col">
            <div class="col-header">
              <span>Semántico</span>
              <span class="badge badge-sem">SEM</span>
            </div>
            <div id="sem-results" class="results-list"></div>
          </div>
        </div>
        <!-- Estado 4: lista mezclada (cuando hay chunk abierto) -->
        <div id="merged-results" hidden>
          <div class="col-header"><span>Resultados</span></div>
          <div id="merged-list" class="results-list"></div>
        </div>
      </div>
    </div>

    <!-- Panel derecho: detalle del chunk + similares -->
    <div id="detail-panel" hidden>
      <div id="detail-header">
        <span id="detail-title"></span>
        <button id="detail-close" title="Cerrar detalle">✕</button>
      </div>
      <div id="detail-text"></div>
      <div id="similar-section">
        <div class="col-header"><span>Similares</span></div>
        <div id="similar-list" class="results-list"></div>
      </div>
    </div>
  </div>

  <script type="module" src="/static/js/rag.js"></script>
</body>
</html>
```

- [ ] **Step 2: Reemplazar `rag.css`**

Reemplazar el contenido completo de `src/rag_lib/web/static/css/rag.css`:

```css
*, *::before, *::after { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: #1a1a2e; color: #e0e0e0; }

/* Search bar */
#search-bar {
  display: flex; align-items: center; gap: .6rem;
  padding: .6rem 1rem; background: #16213e;
  border-bottom: 1px solid #0f3460;
}
.search-icon { font-size: 1rem; flex-shrink: 0; }
#search-input {
  flex: 1; background: #0f1b2d; border: 1px solid #2d3748; border-radius: 6px;
  padding: .4rem .8rem; color: #e0e0e0; font-size: .9rem; outline: none;
}
#search-input:focus { border-color: #7c5cbf; }
#search-clear {
  background: none; border: none; color: #a0aec0; cursor: pointer;
  font-size: 1rem; padding: .2rem .5rem; flex-shrink: 0;
}
#search-clear:hover { color: #e0e0e0; }

/* App layout: 3 panels */
#app { display: flex; height: calc(100vh - 49px); overflow: hidden; }

/* Left panel */
#manuals-panel {
  width: 220px; min-width: 160px; padding: .75rem;
  border-right: 1px solid #0f3460; overflow-y: auto;
  background: #16213e; flex-shrink: 0;
}
#manuals-panel h2 { margin: 0 0 .6rem; font-size: .85rem; color: #a0aec0; text-transform: uppercase; letter-spacing: .05em; }
#manuals-list { list-style: none; padding: 0; margin: 0; }
#manuals-list li {
  padding: .45rem .6rem; border-radius: 6px; cursor: pointer;
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: .2rem; gap: .4rem;
}
#manuals-list li:hover { background: #1e2d47; }
#manuals-list li.active { background: #0f3460; }
#manuals-list .manual-name { font-size: .85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#manuals-list .meta { font-size: .7rem; color: #718096; margin-top: .1rem; }
.delete-btn {
  background: none; border: none; color: #fc8181; cursor: pointer;
  font-size: .85rem; padding: 0 .2rem; flex-shrink: 0; line-height: 1;
}
.delete-btn:hover { color: #feb2b2; }
.manual-check { flex-shrink: 0; accent-color: #7c5cbf; margin-top: .15rem; cursor: pointer; }
.loading { color: #718096; font-style: italic; font-size: .85rem; padding: .4rem 0; }

/* Center panel */
#center-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }

/* Chunks area (navigation mode) */
#chunks-area { flex: 1; display: flex; flex-direction: column; padding: .75rem; overflow: hidden; }
#chunks-area h2 { margin: 0 0 .6rem; font-size: .9rem; color: #a0aec0; }
#chunks-table { border-collapse: collapse; width: 100%; font-size: .82rem; }
#chunks-table th { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #0f3460; color: #718096; font-size: .75rem; text-transform: uppercase; }
#chunks-table td { padding: .3rem .5rem; border-bottom: 1px solid #0f3460; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px; }
#chunks-table tr:hover td { background: #16213e; cursor: pointer; }
#load-more { align-self: center; margin-top: .6rem; padding: .35rem 1rem; background: #0f3460; border: none; color: #e0e0e0; border-radius: 6px; cursor: pointer; font-size: .82rem; flex-shrink: 0; }
#load-more:hover { background: #1a4a8a; }

/* Search results area */
#search-results { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: .75rem; gap: .5rem; }
#search-columns { flex: 1; display: flex; gap: .75rem; overflow: hidden; }
.search-col { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #16213e; border-radius: 8px; padding: .6rem; }
.col-header { display: flex; align-items: center; gap: .4rem; margin-bottom: .5rem; padding-bottom: .4rem; border-bottom: 1px solid #0f3460; font-size: .75rem; text-transform: uppercase; color: #a0aec0; letter-spacing: .05em; flex-shrink: 0; }
.results-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: .3rem; }

/* Merged results (State 4) */
#merged-results { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #16213e; border-radius: 8px; padding: .6rem; }

/* Result items */
.result-item {
  padding: .4rem .55rem; border-radius: 5px; cursor: pointer;
  background: #1a1a2e; border: 1px solid transparent;
  display: flex; flex-direction: column; gap: .15rem;
  flex-shrink: 0;
}
.result-item:hover { border-color: #2d3748; background: #1e2840; }
.result-item.active { border-color: #7c5cbf; background: #1e1a3a; }
.result-meta { font-size: .72rem; color: #718096; display: flex; gap: .4rem; align-items: center; }
.result-preview { font-size: .8rem; color: #cbd5e0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-score { font-size: .7rem; color: #7c5cbf; margin-left: auto; }

/* Badges */
.badge { display: inline-block; padding: .1rem .4rem; border-radius: 4px; font-size: .68rem; font-weight: bold; line-height: 1.4; }
.badge-fts { background: #1a3340; color: #63b3ed; }
.badge-sem { background: #2d1f4a; color: #b794f4; }
.badge-prose { background: #2d3748; color: #90cdf4; }
.badge-table { background: #2d3748; color: #9ae6b4; }

/* Right panel: detail + similar */
#detail-panel {
  width: 360px; min-width: 280px; flex-shrink: 0;
  border-left: 1px solid #0f3460; background: #16213e;
  display: flex; flex-direction: column; overflow: hidden;
}
#detail-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: .6rem .75rem; border-bottom: 1px solid #0f3460; flex-shrink: 0;
}
#detail-title { font-size: .8rem; color: #a0aec0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#detail-close { background: none; border: 1px solid #2d3748; color: #a0aec0; border-radius: 4px; padding: .15rem .5rem; cursor: pointer; font-size: .8rem; flex-shrink: 0; }
#detail-close:hover { color: #e0e0e0; border-color: #4a5568; }
#detail-text {
  padding: .75rem; font-family: monospace; font-size: .78rem;
  white-space: pre-wrap; overflow-y: auto;
  max-height: 40vh; border-bottom: 1px solid #0f3460; flex-shrink: 0;
  color: #e2e8f0; line-height: 1.5;
}
#similar-section {
  flex: 1; display: flex; flex-direction: column; padding: .6rem; overflow: hidden; gap: .4rem;
}
#similar-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: .3rem; }
.similar-loading { font-size: .8rem; color: #718096; font-style: italic; }
```

- [ ] **Step 3: Commit**

```bash
git add src/rag_lib/web/templates/rag.html src/rag_lib/web/static/css/rag.css
git commit -m "feat(rag-a3): update HTML and CSS for 3-panel layout with search bar"
```

---

## Task 6: Frontend JS

**Files:**
- Modify: `src/rag_lib/web/static/js/rag.js`

- [ ] **Step 1: Reemplazar `rag.js` completo**

Reemplazar el contenido completo de `src/rag_lib/web/static/js/rag.js`:

```javascript
// rag.js — ES module for /rag page (A3: hybrid search + detail panel)
const API = "/api/rag";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let activeManualId = null;       // selected manual for navigation mode
let currentOffset = 0;
const LIMIT = 50;
let openChunkId = null;          // chunk open in right panel
let checkedManualIds = new Set(); // checked manuals for search filter (empty = all)
let searchQuery = "";             // current query ("" = no search)
let searchDebounce = null;        // debounce timer
let ftsResults = [];              // latest FTS results
let semResults = [];              // latest semantic results

// ---------------------------------------------------------------------------
// DOM refs (cached after DOMContentLoaded)
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------------------
// Derived state
// ---------------------------------------------------------------------------
const isSearchMode = () => searchQuery.trim() !== "";
const isDetailOpen = () => openChunkId !== null;
const isState4 = () => isSearchMode() && isDetailOpen();

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function buildSearchParams(extra = {}) {
  const params = new URLSearchParams(extra);
  if (checkedManualIds.size > 0) {
    params.set("manual_ids", [...checkedManualIds].join(","));
  }
  return params;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function makeResultItem(r, badgeClass, badgeLabel) {
  const div = document.createElement("div");
  div.className = "result-item" + (r.chunk_id === openChunkId ? " active" : "");
  div.dataset.chunkId = r.chunk_id;
  const meta = `#${r.chunk_id} · ${r.chunk.page ? `p.${r.chunk.page}` : ""} · <span class="badge ${badgeClass}">${badgeLabel}</span>`;
  const preview = escapeHtml((r.chunk.text || "").replace(/\n/g, " ").slice(0, 90));
  const score = `<span class="result-score">${r.score.toFixed(2)}</span>`;
  div.innerHTML = `
    <div class="result-meta">${meta}${score}</div>
    <div class="result-preview">${preview}</div>
  `;
  div.addEventListener("click", () => openDetail(r.chunk_id));
  return div;
}

function renderFtsResults(results) {
  const container = $("fts-results");
  container.innerHTML = "";
  if (!results.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  results.forEach(r => container.appendChild(makeResultItem(r, "badge-fts", "FTS")));
}

function renderSemResults(results) {
  const container = $("sem-results");
  container.innerHTML = "";
  if (!results.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  results.forEach(r => container.appendChild(makeResultItem(r, "badge-sem", "SEM")));
}

function renderMergedResults() {
  const container = $("merged-list");
  container.innerHTML = "";
  // Merge: FTS first, then SEM; deduplicate by chunk_id (FTS wins)
  const seen = new Set();
  const merged = [];
  for (const r of ftsResults) {
    if (!seen.has(r.chunk_id)) { seen.add(r.chunk_id); merged.push({ r, badge: "badge-fts", label: "FTS" }); }
  }
  for (const r of semResults) {
    if (!seen.has(r.chunk_id)) { seen.add(r.chunk_id); merged.push({ r, badge: "badge-sem", label: "SEM" }); }
  }
  if (!merged.length) {
    container.innerHTML = '<div class="loading">Sin resultados</div>';
    return;
  }
  merged.forEach(({ r, badge, label }) => container.appendChild(makeResultItem(r, badge, label)));
}

// ---------------------------------------------------------------------------
// Panel visibility
// ---------------------------------------------------------------------------
function applyLayout() {
  if (isSearchMode()) {
    $("chunks-area").hidden = true;
    $("search-results").hidden = false;
    if (isState4()) {
      $("search-columns").hidden = true;
      $("merged-results").hidden = false;
      renderMergedResults();
    } else {
      $("search-columns").hidden = false;
      $("merged-results").hidden = true;
    }
  } else {
    $("chunks-area").hidden = false;
    $("search-results").hidden = true;
  }
  $("detail-panel").hidden = !isDetailOpen();
}

// ---------------------------------------------------------------------------
// Manuals panel
// ---------------------------------------------------------------------------
async function loadManuals() {
  const list = $("manuals-list");
  list.innerHTML = '<li class="loading">Cargando…</li>';
  const manuals = await fetchJSON(`${API}/manuals`);
  list.innerHTML = "";
  if (!manuals.length) {
    list.innerHTML = '<li class="loading">Sin manuales. Usa el CLI para ingestar un PDF.</li>';
    return;
  }
  for (const m of manuals) {
    const li = document.createElement("li");
    li.dataset.id = m.id;
    const checked = checkedManualIds.has(m.id) ? "checked" : "";
    li.innerHTML = `
      <input type="checkbox" class="manual-check" data-id="${m.id}" ${checked}>
      <div style="flex:1;min-width:0;cursor:pointer" class="manual-label">
        <div class="manual-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
        <div class="meta">${m.page_count} pp · ${m.chunk_count} chunks</div>
      </div>
      <button class="delete-btn" title="Eliminar manual" data-id="${m.id}">✕</button>
    `;
    li.querySelector(".manual-check").addEventListener("change", e => {
      const id = +e.target.dataset.id;
      if (e.target.checked) checkedManualIds.add(id);
      else checkedManualIds.delete(id);
      if (isSearchMode()) executeSearch(searchQuery);
    });
    li.querySelector(".manual-label").addEventListener("click", () => {
      clearSearch();
      selectManual(m.id, m.name);
    });
    li.querySelector(".delete-btn").addEventListener("click", async e => {
      e.stopPropagation();
      if (!confirm(`¿Eliminar "${m.name}" y todos sus chunks?`)) return;
      await fetch(`${API}/manuals/${m.id}`, { method: "DELETE" });
      checkedManualIds.delete(m.id);
      if (activeManualId === m.id) clearChunks();
      if (openChunkId !== null) closeDetail();
      loadManuals();
    });
    if (!isSearchMode() && activeManualId === m.id) li.classList.add("active");
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Chunks panel (navigation mode)
// ---------------------------------------------------------------------------
function clearChunks() {
  activeManualId = null;
  $("chunks-title").textContent = "Selecciona un manual";
  $("chunks-table").hidden = true;
  $("chunks-body").innerHTML = "";
  $("load-more").hidden = true;
}

async function selectManual(id, name) {
  activeManualId = id;
  currentOffset = 0;
  document.querySelectorAll("#manuals-list li").forEach(li =>
    li.classList.toggle("active", +li.dataset.id === id)
  );
  $("chunks-title").textContent = name;
  $("chunks-body").innerHTML = "";
  $("chunks-table").hidden = false;
  applyLayout();
  await loadChunks(true);
}

async function loadChunks(replace = false) {
  const rows = await fetchJSON(`${API}/manuals/${activeManualId}/chunks?offset=${currentOffset}&limit=${LIMIT}`);
  const tbody = $("chunks-body");
  if (replace) tbody.innerHTML = "";
  for (const c of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = c.id;
    if (c.id === openChunkId) tr.classList.add("active");
    const sp = c.section_path
      ? `<small title="${escapeHtml(c.section_path)}">${escapeHtml(c.section_path.slice(0, 30))}${c.section_path.length > 30 ? "…" : ""}</small>`
      : "—";
    const preview = escapeHtml((c.text || "").replace(/\n/g, " ").slice(0, 80));
    tr.innerHTML = `
      <td>${c.seq}</td>
      <td>${c.page}${c.page_end ? `–${c.page_end}` : ""}</td>
      <td><span class="badge badge-${c.chunk_type}">${c.chunk_type}</span></td>
      <td title="${c.section_path || ""}">${sp}</td>
      <td title="${preview}">${preview}</td>
    `;
    tr.addEventListener("click", () => openDetail(c.id));
    tbody.appendChild(tr);
  }
  currentOffset += rows.length;
  $("load-more").hidden = rows.length < LIMIT;
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function clearSearch() {
  searchQuery = "";
  $("search-input").value = "";
  $("search-clear").hidden = true;
  ftsResults = [];
  semResults = [];
  applyLayout();
}

async function executeSearch(q) {
  searchQuery = q;
  ftsResults = [];
  semResults = [];

  // Show loading states immediately
  $("fts-results").innerHTML = '<div class="loading">Buscando…</div>';
  $("sem-results").innerHTML = '<div class="loading">Buscando… ◌</div>';
  applyLayout();

  const params = buildSearchParams({ q, k: 20 });

  // Fire both requests in parallel — FTS renders first, semantic when ready
  const ftsFetch = fetchJSON(`${API}/search/fts?${params}`)
    .then(results => {
      ftsResults = results;
      if (!isState4()) renderFtsResults(results);
      else renderMergedResults();
    })
    .catch(() => {
      $("fts-results").innerHTML = '<div class="loading">Error en búsqueda FTS</div>';
    });

  const semFetch = fetchJSON(`${API}/search/semantic?${params}`)
    .then(results => {
      semResults = results;
      if (!isState4()) renderSemResults(results);
      else renderMergedResults();
    })
    .catch(() => {
      $("sem-results").innerHTML = '<div class="loading">Error en búsqueda semántica</div>';
    });

  await Promise.allSettled([ftsFetch, semFetch]);
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------
async function openDetail(chunkId) {
  openChunkId = chunkId;
  $("detail-title").textContent = `Cargando #${chunkId}…`;
  $("detail-text").textContent = "";
  $("similar-list").innerHTML = '<div class="similar-loading">Cargando similares…</div>';
  applyLayout();

  // Mark active in current results
  document.querySelectorAll(".result-item").forEach(el =>
    el.classList.toggle("active", +el.dataset.chunkId === chunkId)
  );
  document.querySelectorAll("#chunks-body tr").forEach(tr =>
    tr.classList.toggle("active", +tr.dataset.id === chunkId)
  );

  // Load chunk detail
  const chunk = await fetchJSON(`${API}/chunks/${chunkId}`);
  const sp = chunk.section_path || "";
  $("detail-title").textContent = `#${chunk.id} · p.${chunk.page} · ${chunk.chunk_type}${sp ? " · " + sp : ""}`;
  $("detail-text").textContent = chunk.text;

  // Load similar
  const similar = await fetchJSON(`${API}/chunks/${chunkId}/similar?k=5`);
  const simList = $("similar-list");
  simList.innerHTML = "";
  if (!similar.length) {
    simList.innerHTML = '<div class="similar-loading">Sin similares</div>';
    return;
  }
  similar.forEach(r => {
    const div = makeResultItem(r, "badge-sem", "SEM");
    simList.appendChild(div);
  });
}

function closeDetail() {
  openChunkId = null;
  document.querySelectorAll(".result-item, #chunks-body tr").forEach(el =>
    el.classList.remove("active")
  );
  applyLayout();
  // If search was active, re-render as two columns
  if (isSearchMode()) {
    renderFtsResults(ftsResults);
    renderSemResults(semResults);
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
$("load-more").addEventListener("click", () => loadChunks(false));

$("detail-close").addEventListener("click", closeDetail);

$("search-clear").addEventListener("click", () => {
  clearSearch();
  if (activeManualId) {
    currentOffset = 0;
    $("chunks-body").innerHTML = "";
    loadChunks(true);
  }
});

$("search-input").addEventListener("input", e => {
  const q = e.target.value;
  $("search-clear").hidden = !q;
  clearTimeout(searchDebounce);
  if (!q.trim()) {
    clearSearch();
    return;
  }
  searchDebounce = setTimeout(() => executeSearch(q), 320);
});

loadManuals();
```

- [ ] **Step 2: Commit**

```bash
git add src/rag_lib/web/static/js/rag.js
git commit -m "feat(rag-a3): rewrite rag.js with hybrid search, parallel fetch, 4-state UI"
```

---

## Task 7: Verificación final

**Files:** ninguno nuevo

- [ ] **Step 1: Correr toda la suite rag_lib**

```bash
python -m pytest tests/rag_lib/ -v
```

Expected: todos los tests pasan (≥ 112 estimados: ~94 A1+A2 + ~18 A3).

- [ ] **Step 2: Ruff check**

```bash
ruff check src/rag_lib tests/rag_lib
```

Expected: `All checks passed!`

- [ ] **Step 3: Correr suite completa para detectar regresiones**

```bash
python -m pytest tests/ -q --ignore=tests/rag_lib/
```

Expected: mismos resultados que antes de A3 (fallos pre-existentes conocidos: `test_tts_config_from_toml`, etc.).

- [ ] **Step 4: Smoke test visual** (requiere RPG Scribe en ejecución)

```bash
rpg-scribe
```

Abrir `http://127.0.0.1:8000/rag` y verificar:
- La barra de búsqueda está visible en la parte superior.
- Los manuales en el panel izquierdo tienen checkbox.
- Escribir una palabra → aparecen dos columnas (FTS carga primero, semántico después con spinner).
- Click en un resultado → panel derecho abre con texto completo (scrollable) y lista de similares.
- Con búsqueda activa + chunk abierto → centro muestra lista mezclada con badges FTS/SEM.
- Borrar búsqueda (✕) → vuelve al modo navegación.
- Textos largos muestran ellipsis; `section_path` larga tiene tooltip.

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "feat(rag-a3): complete hybrid search + similar chunks — Fase A3"
```
