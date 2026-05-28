# Fase A4 — Upload por web + edición de chunks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir upload de PDF por drag & drop con ingesta en background (jobs en SQLite + polling), aviso de duplicado, y edición inline de chunks (texto + section_path + chunk_type) con regeneración de embeddings desde la UI de `rag_lib`.

**Architecture:** Nueva tabla `rag_jobs` + trigger `rag_chunks_au`; `JobRepo` en store; `ChunkRepo.update()`; tres funciones nuevas en la API pública (`upload_pdf`, `get_job`, `update_chunk`) con `_run_ingest` como coroutine interna; tres endpoints REST nuevos; frontend: zona drag & drop en panel izquierdo con polling, modo edición inline en panel derecho.

**Tech Stack:** SQLite (rag_jobs, trigger AFTER UPDATE FTS5), `aiosqlite`, `uuid` stdlib, `tempfile` stdlib, `tiktoken` (recálculo token_count), `numpy`, `fastapi` (UploadFile, Form, pydantic Literal), `httpx` + `ASGITransport` (tests de endpoints), ES modules browser-nativos.

---

## Mapa de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Modify | `src/rag_lib/schema.py` | Añadir `rag_jobs` table + `idx_jobs_status` + trigger `rag_chunks_au` |
| Modify | `src/rag_lib/types.py` | Añadir `IngestJob` dataclass |
| Modify | `src/rag_lib/store.py` | Añadir `_UNSET` sentinel + `JobRepo` + `Database.jobs` + `ChunkRepo.update()` |
| Modify | `src/rag_lib/__init__.py` | Añadir `_UNSET`, `_ENC`, `upload_pdf`, `_run_ingest`, `get_job`, `update_chunk` |
| Modify | `src/rag_lib/web/router.py` | Añadir `embedder` param a `build_router`; añadir 3 endpoints; `ChunkUpdate` Pydantic model |
| Modify | `src/rag_lib/web/templates/rag.html` | Zona upload en panel izquierdo; botón editar + form inline en panel derecho |
| Modify | `src/rag_lib/web/static/js/rag.js` | Upload drag & drop + polling; edit mode toggle + PATCH save |
| Modify | `src/rag_lib/web/static/css/rag.css` | Estilos upload zone, estados drag, edit fields |
| Create | `tests/rag_lib/test_upload.py` | Tests para `upload_pdf()`, `get_job()` |
| Create | `tests/rag_lib/test_update_chunk.py` | Tests para `update_chunk()` |
| Create | `tests/rag_lib/test_web_router_a4.py` | Tests para los 3 endpoints nuevos |

---

## Task 1: Schema + IngestJob type

**Files:**
- Modify: `src/rag_lib/schema.py`
- Modify: `src/rag_lib/types.py`

- [ ] **Step 1: Añadir `rag_jobs`, `idx_jobs_status` y trigger `rag_chunks_au` a schema.py**

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

CREATE TABLE IF NOT EXISTS rag_jobs (
    id           TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'error')),
    manual_name  TEXT NOT NULL,
    manual_id    INTEGER,
    was_duplicate INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_jobs_status        ON rag_jobs(status);

CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
    INSERT INTO rag_chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;
"""
```

- [ ] **Step 2: Añadir `IngestJob` a types.py**

En `src/rag_lib/types.py`, añadir después del dataclass `SearchResult`:

```python
@dataclass(frozen=True)
class IngestJob:
    id: str
    status: str           # 'pending' | 'processing' | 'done' | 'error'
    manual_name: str
    manual_id: int | None
    was_duplicate: bool
    error: str | None
```

- [ ] **Step 3: Verificar schema smoke test**

```bash
python -c "
from rag_lib.schema import RAG_SCHEMA_SQL
assert 'rag_jobs' in RAG_SCHEMA_SQL
assert 'rag_chunks_au' in RAG_SCHEMA_SQL
assert 'was_duplicate' in RAG_SCHEMA_SQL
print('schema OK')
"
```

Expected: `schema OK`

- [ ] **Step 4: Commit**

```bash
git add src/rag_lib/schema.py src/rag_lib/types.py
git commit -m "feat(rag-a4): add rag_jobs schema, rag_chunks_au FTS5 trigger, IngestJob type"
```

---

## Task 2: JobRepo (TDD)

**Files:**
- Modify: `src/rag_lib/store.py`
- Create: `tests/rag_lib/test_upload.py` (primeros tests)

- [ ] **Step 1: Escribir tests RED para JobRepo**

Crear `tests/rag_lib/test_upload.py`:

```python
"""Tests for upload_pdf(), get_job() and JobRepo."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import rag_lib
from rag_lib.store import Database
from rag_lib.types import IngestJob


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def _wait_done(job_id: str, db_path: Path, *, timeout: float = 5.0) -> IngestJob:
    """Poll until job reaches a terminal status."""
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = await rag_lib.get_job(job_id, db_path)
        if j and j.status in ("done", "error"):
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish within {timeout}s")


# ── JobRepo unit tests ──────────────────────────────────────────────────────

async def test_connect_creates_rag_jobs_table(db: Database) -> None:
    cur = await db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_jobs'"
    )
    assert await cur.fetchone() is not None


async def test_job_create_sets_pending_status(db: Database) -> None:
    await db.jobs.create("job-1", "Test Manual")
    row = await db.jobs.get("job-1")
    assert row is not None
    assert row["status"] == "pending"
    assert row["manual_name"] == "Test Manual"
    assert row["was_duplicate"] == 0


async def test_job_set_processing(db: Database) -> None:
    await db.jobs.create("job-2", "Manual X")
    await db.jobs.set_processing("job-2")
    row = await db.jobs.get("job-2")
    assert row["status"] == "processing"


async def test_job_set_done(db: Database) -> None:
    await db.jobs.create("job-3", "Manual Y")
    await db.jobs.set_done("job-3", manual_id=42, was_duplicate=False)
    row = await db.jobs.get("job-3")
    assert row["status"] == "done"
    assert row["manual_id"] == 42
    assert row["was_duplicate"] == 0


async def test_job_set_done_duplicate(db: Database) -> None:
    await db.jobs.create("job-4", "Manual Z")
    await db.jobs.set_done("job-4", manual_id=7, was_duplicate=True)
    row = await db.jobs.get("job-4")
    assert row["was_duplicate"] == 1


async def test_job_set_error(db: Database) -> None:
    await db.jobs.create("job-5", "Manual W")
    await db.jobs.set_error("job-5", "PDF corrupto")
    row = await db.jobs.get("job-5")
    assert row["status"] == "error"
    assert row["error"] == "PDF corrupto"


async def test_job_get_nonexistent_returns_none(db: Database) -> None:
    row = await db.jobs.get("no-existe")
    assert row is None
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_upload.py -v -k "job"
```

Expected: `AttributeError: 'Database' object has no attribute 'jobs'`

- [ ] **Step 3: Añadir `_UNSET`, `JobRepo` y `Database.jobs` a store.py**

Añadir `_UNSET` al inicio de `src/rag_lib/store.py` (después de los imports, antes de `logger`):

```python
_UNSET = object()  # sentinel para distinguir "no cambiar" de None
```

Añadir en `Database.__init__` la línea `self.jobs = JobRepo(self)` después de `self.embeddings`:

```python
def __init__(self, db_path: str | Path = "rag.db") -> None:
    self._db_path = str(db_path)
    self._conn: aiosqlite.Connection | None = None
    self.manuals = ManualRepo(self)
    self.chunks = ChunkRepo(self)
    self.embeddings = EmbeddingRepo(self)
    self.jobs = JobRepo(self)
```

Añadir la clase `JobRepo` al final de `src/rag_lib/store.py`:

```python
class JobRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, job_id: str, manual_name: str) -> None:
        await self._db.conn.execute(
            "INSERT INTO rag_jobs (id, manual_name) VALUES (?, ?)",
            (job_id, manual_name),
        )
        await self._db.conn.commit()

    async def set_processing(self, job_id: str) -> None:
        await self._db.conn.execute(
            "UPDATE rag_jobs SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        await self._db.conn.commit()

    async def set_done(self, job_id: str, manual_id: int, *, was_duplicate: bool = False) -> None:
        await self._db.conn.execute(
            """UPDATE rag_jobs
               SET status='done', manual_id=?, was_duplicate=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (manual_id, 1 if was_duplicate else 0, job_id),
        )
        await self._db.conn.commit()

    async def set_error(self, job_id: str, error: str) -> None:
        await self._db.conn.execute(
            """UPDATE rag_jobs
               SET status='error', error=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (error, job_id),
        )
        await self._db.conn.commit()

    async def get(self, job_id: str) -> dict[str, Any] | None:
        cur = await self._db.conn.execute(
            "SELECT * FROM rag_jobs WHERE id=?", (job_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_upload.py -v -k "job"
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/store.py tests/rag_lib/test_upload.py
git commit -m "feat(rag-a4): add JobRepo + Database.jobs, _UNSET sentinel"
```

---

## Task 3: ChunkRepo.update() (TDD)

**Files:**
- Modify: `src/rag_lib/store.py`
- Create: `tests/rag_lib/test_update_chunk.py` (fixture setup)

- [ ] **Step 1: Escribir tests RED para ChunkRepo.update()**

Crear `tests/rag_lib/test_update_chunk.py`:

```python
"""Tests for ChunkRepo.update() and update_chunk() public API."""
from __future__ import annotations

import hashlib
from pathlib import Path

import rag_lib
import pytest

from rag_lib.store import Database
from rag_lib.types import Chunk


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def chunk_id(db: Database) -> int:
    """Insert one manual + one chunk; return the chunk id."""
    mid = await db.manuals.insert(
        name="M", source_path="m.pdf", source_hash="s1",
        page_count=1, file_size=100, parser="pdfplumber",
    )
    ids = await db.chunks.insert_many(mid, [
        {
            "seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
            "section_path": "Orig/Section", "text": "texto original",
            "text_hash": hashlib.sha256(b"texto original").hexdigest(),
            "token_count": 2,
        }
    ])
    return ids[0]


# ── ChunkRepo.update() unit tests ──────────────────────────────────────────

async def test_update_text_persisted(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, text="nuevo texto")
    assert row is not None
    assert row["text"] == "nuevo texto"


async def test_update_text_does_not_change_section_path(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, text="nuevo")
    assert row["section_path"] == "Orig/Section"


async def test_update_section_path_persisted(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, section_path="X/Y/Z")
    assert row["section_path"] == "X/Y/Z"


async def test_update_section_path_to_none(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, section_path=None)
    assert row["section_path"] is None


async def test_update_unset_section_path_unchanged(db: Database, chunk_id: int) -> None:
    """Not passing section_path (uses default _UNSET sentinel) must not change the stored value."""
    row = await db.chunks.update(chunk_id, text="changed")
    assert row["section_path"] == "Orig/Section"


async def test_update_chunk_type_persisted(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, chunk_type="table")
    assert row["chunk_type"] == "table"


async def test_update_text_hash_persisted(db: Database, chunk_id: int) -> None:
    new_hash = hashlib.sha256(b"nuevo texto").hexdigest()
    row = await db.chunks.update(chunk_id, text="nuevo texto", text_hash=new_hash)
    assert row["text_hash"] == new_hash


async def test_update_token_count_persisted(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id, token_count=99)
    assert row["token_count"] == 99


async def test_update_nonexistent_returns_none(db: Database) -> None:
    row = await db.chunks.update(99999, text="whatever")
    assert row is None


async def test_update_no_fields_returns_current_row(db: Database, chunk_id: int) -> None:
    row = await db.chunks.update(chunk_id)
    assert row is not None
    assert row["text"] == "texto original"
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_update_chunk.py -v
```

Expected: `AttributeError: type object 'ChunkRepo' has no attribute 'update'` o similar

- [ ] **Step 3: Añadir `ChunkRepo.update()` a store.py**

En la clase `ChunkRepo`, añadir el método `update()` después de `get_many_by_ids`:

```python
async def update(
    self,
    chunk_id: int,
    *,
    text: str | None = None,
    section_path: object = _UNSET,
    chunk_type: str | None = None,
    text_hash: str | None = None,
    token_count: int | None = None,
) -> dict[str, Any] | None:
    """Update specified fields. Returns updated row dict or None if chunk not found."""
    sets: list[str] = []
    params: list = []
    if text is not None:
        sets.append("text = ?")
        params.append(text)
    if section_path is not _UNSET:
        sets.append("section_path = ?")
        params.append(section_path)
    if chunk_type is not None:
        sets.append("chunk_type = ?")
        params.append(chunk_type)
    if text_hash is not None:
        sets.append("text_hash = ?")
        params.append(text_hash)
    if token_count is not None:
        sets.append("token_count = ?")
        params.append(token_count)

    if not sets:
        return await self.get_by_id(chunk_id)

    params.append(chunk_id)
    sql = f"UPDATE rag_chunks SET {', '.join(sets)} WHERE id = ?"
    cur = await self._db.conn.execute(sql, params)
    await self._db.conn.commit()
    if cur.rowcount == 0:
        return None
    return await self.get_by_id(chunk_id)
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_update_chunk.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/store.py tests/rag_lib/test_update_chunk.py
git commit -m "feat(rag-a4): add ChunkRepo.update() with _UNSET sentinel for section_path"
```

---

## Task 4: upload_pdf() + get_job() (TDD)

**Files:**
- Modify: `src/rag_lib/__init__.py`
- Modify: `tests/rag_lib/test_upload.py`

- [ ] **Step 1: Añadir tests para upload_pdf() y get_job()**

Añadir al final de `tests/rag_lib/test_upload.py`:

```python
# ── upload_pdf() + get_job() integration tests ─────────────────────────────

async def test_upload_pdf_returns_job_immediately(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        simple_pdf.read_bytes(), manual_name="Test", db_path=db_path, embedder=fake_embedder,
    )
    assert isinstance(job, IngestJob)
    assert job.status == "pending"
    assert job.manual_id is None
    assert job.id != ""


async def test_upload_pdf_job_created_in_db(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        simple_pdf.read_bytes(), manual_name="Test", db_path=db_path, embedder=fake_embedder,
    )
    found = await rag_lib.get_job(job.id, db_path)
    assert found is not None
    assert found.id == job.id


async def test_upload_pdf_job_reaches_done(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        simple_pdf.read_bytes(), manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    done = await _wait_done(job.id, db_path)
    assert done.status == "done"
    assert done.manual_id is not None
    assert done.was_duplicate is False


async def test_upload_pdf_creates_manual(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        simple_pdf.read_bytes(), manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    await _wait_done(job.id, db_path)
    manuals = await rag_lib.list_manuals(db_path)
    assert any(m.name == "Book" for m in manuals)


async def test_upload_pdf_duplicate_sets_was_duplicate(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    pdf_bytes = simple_pdf.read_bytes()
    job1 = await rag_lib.upload_pdf(pdf_bytes, manual_name="Book", db_path=db_path, embedder=fake_embedder)
    await _wait_done(job1.id, db_path)

    job2 = await rag_lib.upload_pdf(pdf_bytes, manual_name="Book", db_path=db_path, embedder=fake_embedder)
    done2 = await _wait_done(job2.id, db_path)
    assert done2.status == "done"
    assert done2.was_duplicate is True
    assert done2.manual_id is not None

    manuals = await rag_lib.list_manuals(db_path)
    assert len(manuals) == 1


async def test_upload_pdf_invalid_bytes_sets_error(tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        b"esto no es un PDF", manual_name="Bad", db_path=db_path, embedder=fake_embedder,
    )
    done = await _wait_done(job.id, db_path)
    assert done.status == "error"
    assert done.error is not None


async def test_get_job_nonexistent_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "rag.db"
    result = await rag_lib.get_job("no-existe", db_path)
    assert result is None


async def test_upload_pdf_embeddings_created(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db_path = tmp_path / "rag.db"
    job = await rag_lib.upload_pdf(
        simple_pdf.read_bytes(), manual_name="Book", db_path=db_path, embedder=fake_embedder,
    )
    done = await _wait_done(job.id, db_path)
    assert done.status == "done"
    db = Database(db_path)
    await db.connect()
    try:
        rows = await db.embeddings.load_all()
        assert len(rows) > 0
    finally:
        await db.close()
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_upload.py::test_upload_pdf_returns_job_immediately -v
```

Expected: `AttributeError: module 'rag_lib' has no attribute 'upload_pdf'`

- [ ] **Step 3: Añadir `upload_pdf`, `_run_ingest`, `get_job` y tipos necesarios a `__init__.py`**

Añadir imports al inicio de `src/rag_lib/__init__.py` (después de los imports existentes):

```python
import os
import tempfile
import uuid

import tiktoken

from rag_lib.types import Chunk, IngestJob, IngestResult, Manual, SearchResult
```

(Reemplaza la línea `from rag_lib.types import Chunk, IngestResult, Manual, SearchResult` existente.)

Añadir debajo de `_VECTOR_CACHE`:

```python
_ENC = tiktoken.get_encoding("cl100k_base")
_UNSET = object()
```

Añadir las tres funciones nuevas después de `search_similar()` y antes de los helpers `_row_to_*`:

```python
async def upload_pdf(
    pdf_bytes: bytes,
    *,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None = None,
) -> IngestJob:
    """Create a job and start ingestion in background. Returns immediately."""
    job_id = uuid.uuid4().hex
    db = Database(db_path)
    await db.connect()
    try:
        await db.jobs.create(job_id, manual_name)
    finally:
        await db.close()

    asyncio.create_task(
        _run_ingest(job_id, pdf_bytes, manual_name, db_path, embedder)
    )
    return IngestJob(
        id=job_id,
        status="pending",
        manual_name=manual_name,
        manual_id=None,
        was_duplicate=False,
        error=None,
    )


async def _run_ingest(
    job_id: str,
    pdf_bytes: bytes,
    manual_name: str,
    db_path: str | Path,
    embedder: Embedder | None,
) -> None:
    """Internal coroutine: write temp file, ingest, update job status."""
    # Step 1: mark as processing
    db = Database(db_path)
    await db.connect()
    try:
        await db.jobs.set_processing(job_id)
    finally:
        await db.close()

    # Step 2: write bytes to temp file, run ingest (manages its own DB connection)
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(pdf_bytes)
    tmp.close()

    result: IngestResult | None = None
    error_msg: str | None = None
    try:
        result = await ingest_pdf(
            Path(tmp.name),
            manual_name=manual_name,
            db_path=db_path,
            embedder=embedder,
        )
    except Exception as exc:
        error_msg = str(exc)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # Step 3: mark done or error
    db = Database(db_path)
    await db.connect()
    try:
        if result is not None:
            await db.jobs.set_done(
                job_id,
                result.manual_id,
                was_duplicate=result.was_already_ingested,
            )
        else:
            await db.jobs.set_error(job_id, error_msg or "Unknown error")
    finally:
        await db.close()


async def get_job(job_id: str, db_path: str | Path) -> IngestJob | None:
    """Return the current state of an ingestion job, or None if not found."""
    db = Database(db_path)
    await db.connect()
    try:
        row = await db.jobs.get(job_id)
        if row is None:
            return None
        return IngestJob(
            id=row["id"],
            status=row["status"],
            manual_name=row["manual_name"],
            manual_id=row["manual_id"],
            was_duplicate=bool(row["was_duplicate"]),
            error=row["error"],
        )
    finally:
        await db.close()
```

- [ ] **Step 4: Verificar tests de upload**

```bash
python -m pytest tests/rag_lib/test_upload.py -v
```

Expected: 15 passed (7 JobRepo + 8 upload_pdf/get_job)

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/__init__.py tests/rag_lib/test_upload.py
git commit -m "feat(rag-a4): add upload_pdf, _run_ingest, get_job to public API"
```

---

## Task 5: update_chunk() (TDD)

**Files:**
- Modify: `src/rag_lib/__init__.py`
- Modify: `tests/rag_lib/test_update_chunk.py`

- [ ] **Step 1: Añadir tests para update_chunk() al archivo existente**

Los imports `import rag_lib`, `from rag_lib.types import Chunk` ya están al inicio del archivo desde Task 3. Añadir solo los tests al final de `tests/rag_lib/test_update_chunk.py`:

```python
# ── update_chunk() public API tests ────────────────────────────────────────


@pytest.fixture
async def ingested_chunk(simple_pdf: Path, tmp_path: Path, fake_embedder):
    """Ingest a real PDF and return (db_path, chunk_id) of the first chunk."""
    db_path = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Test", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)
    return db_path, chunks[0].id


async def test_update_chunk_text_persisted(ingested_chunk) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, text="nuevo texto aquí")
    assert isinstance(updated, Chunk)
    assert updated.text == "nuevo texto aquí"


async def test_update_chunk_recalculates_token_count(ingested_chunk) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, text="uno dos tres")
    assert updated.token_count > 0


async def test_update_chunk_recalculates_text_hash(ingested_chunk) -> None:
    db_path, chunk_id = ingested_chunk
    nuevo = "texto completamente diferente"
    updated = await rag_lib.update_chunk(chunk_id, db_path, text=nuevo)
    import hashlib
    expected_hash = hashlib.sha256(nuevo.encode()).hexdigest()
    assert updated.text_hash == expected_hash


async def test_update_chunk_section_path_persisted(ingested_chunk) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, section_path="A/B/C")
    assert updated.section_path == "A/B/C"


async def test_update_chunk_chunk_type_persisted(ingested_chunk) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, chunk_type="table")
    assert updated.chunk_type == "table"


async def test_update_chunk_nonexistent_returns_none(ingested_chunk) -> None:
    db_path, _ = ingested_chunk
    result = await rag_lib.update_chunk(99999, db_path, text="whatever")
    assert result is None


async def test_update_chunk_regenerates_embedding(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    from rag_lib.store import Database
    db = Database(db_path)
    await db.connect()
    rows_before = await db.embeddings.load_all()
    await db.close()

    await rag_lib.update_chunk(chunk_id, db_path, text="texto muy diferente", embedder=fake_embedder)

    db = Database(db_path)
    await db.connect()
    rows_after = await db.embeddings.load_all()
    await db.close()
    assert len(rows_after) == len(rows_before)
    chunk_emb = next(r for r in rows_after if r["chunk_id"] == chunk_id)
    assert chunk_emb is not None


async def test_update_chunk_fts5_updated(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    nuevo_texto = "xtextouniquexyz frase especial"
    await rag_lib.update_chunk(chunk_id, db_path, text=nuevo_texto, embedder=fake_embedder)
    results = await rag_lib.search_fts("xtextouniquexyz", db_path)
    assert any(r.chunk_id == chunk_id for r in results)
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_update_chunk.py::test_update_chunk_text_persisted -v
```

Expected: `AttributeError: module 'rag_lib' has no attribute 'update_chunk'`

- [ ] **Step 3: Añadir `update_chunk()` a `__init__.py`**

Añadir después de `get_job()` y antes de los helpers `_row_to_*`:

```python
async def update_chunk(
    chunk_id: int,
    db_path: str | Path,
    *,
    text: str | None = None,
    section_path: object = _UNSET,
    chunk_type: str | None = None,
    embedder: Embedder | None = None,
) -> Chunk | None:
    """Update chunk text and/or metadata. Recalculates text_hash, token_count, and
    regenerates the embedding if text changes. Returns updated Chunk or None if not found.
    """
    db = Database(db_path)
    await db.connect()
    try:
        store_kwargs: dict = {}
        if text is not None:
            store_kwargs["text"] = text
            store_kwargs["text_hash"] = hashlib.sha256(text.encode()).hexdigest()
            store_kwargs["token_count"] = len(_ENC.encode(text))
        if section_path is not _UNSET:
            store_kwargs["section_path"] = section_path
        if chunk_type is not None:
            store_kwargs["chunk_type"] = chunk_type

        updated_row = await db.chunks.update(chunk_id, **store_kwargs)
        if updated_row is None:
            return None

        if text is not None:
            _emb = embedder or OpenAIEmbedder()
            [vec] = await _emb.embed([text])
            await db.embeddings.upsert_many([{
                "chunk_id": chunk_id,
                "vector_bytes": np.array(vec, dtype=np.float32).tobytes(),
                "dim": _emb.dim,
                "model": _emb.model,
            }])
            _VECTOR_CACHE.pop(str(db_path), None)

        return _row_to_chunk(updated_row)
    finally:
        await db.close()
```

- [ ] **Step 4: Verificar tests de update_chunk**

```bash
python -m pytest tests/rag_lib/test_update_chunk.py -v
```

Expected: 19 passed (10 ChunkRepo + 9 update_chunk)

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/__init__.py tests/rag_lib/test_update_chunk.py
git commit -m "feat(rag-a4): add update_chunk() with text_hash/token_count recalc and embedding regeneration"
```

---

## Task 6: Router — 3 nuevos endpoints (TDD)

**Files:**
- Modify: `src/rag_lib/web/router.py`
- Create: `tests/rag_lib/test_web_router_a4.py`

- [ ] **Step 1: Escribir tests RED para los 3 endpoints**

Crear `tests/rag_lib/test_web_router_a4.py`:

```python
"""Tests for A4 web endpoints: upload, job polling, chunk PATCH."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import rag_lib
from rag_lib.web import build_router


@pytest.fixture
async def app(tmp_path, fake_embedder):
    router = build_router(str(tmp_path / "test.db"), embedder=fake_embedder)
    application = FastAPI()
    application.include_router(router)
    return application


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


async def _poll_job(client: AsyncClient, job_id: str, *, timeout: float = 5.0) -> dict:
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        resp = await client.get(f"/api/rag/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("done", "error"):
            return data
        await asyncio.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish")


# ── upload endpoint ─────────────────────────────────────────────────────────

async def test_upload_endpoint_returns_202(app, simple_pdf: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/rag/manuals/upload",
            files={"file": ("test.pdf", simple_pdf.read_bytes(), "application/pdf")},
            data={"manual_name": "Test"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert "id" in body
    assert body["status"] == "pending"


async def test_upload_endpoint_invalid_content_type(app) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/rag/manuals/upload",
            files={"file": ("doc.txt", b"not a pdf", "text/plain")},
            data={"manual_name": "Bad"},
        )
    assert resp.status_code == 400


async def test_upload_endpoint_empty_name(app, simple_pdf: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/rag/manuals/upload",
            files={"file": ("test.pdf", simple_pdf.read_bytes(), "application/pdf")},
            data={"manual_name": ""},
        )
    assert resp.status_code == 422


# ── job polling endpoint ────────────────────────────────────────────────────

async def test_job_polling_reaches_done(app, simple_pdf: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload = await client.post(
            "/api/rag/manuals/upload",
            files={"file": ("test.pdf", simple_pdf.read_bytes(), "application/pdf")},
            data={"manual_name": "Book"},
        )
        job_id = upload.json()["id"]
        done = await _poll_job(client, job_id)
    assert done["status"] == "done"
    assert done["manual_id"] is not None
    assert "was_duplicate" in done


async def test_job_polling_not_found(app) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/rag/jobs/no-existe")
    assert resp.status_code == 404


# ── chunk PATCH endpoint ────────────────────────────────────────────────────

@pytest.fixture
async def chunk_id_in_db(tmp_path, fake_embedder, simple_pdf: Path):
    """Ingest a PDF and return (db_path_str, first_chunk_id)."""
    db_path = str(tmp_path / "test.db")
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Test", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)
    return db_path, chunks[0].id


async def test_patch_chunk_text_returns_200(tmp_path, fake_embedder, simple_pdf: Path) -> None:
    db_path = str(tmp_path / "test.db")
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="Test", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)
    cid = chunks[0].id

    router = build_router(db_path, embedder=fake_embedder)
    app2 = FastAPI()
    app2.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/rag/chunks/{cid}",
            json={"text": "nuevo texto editado"},
        )
    assert resp.status_code == 200
    assert resp.json()["text"] == "nuevo texto editado"


async def test_patch_chunk_not_found(app) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/api/rag/chunks/99999", json={"text": "x"})
    assert resp.status_code == 404


async def test_patch_chunk_invalid_chunk_type(app, tmp_path, fake_embedder, simple_pdf: Path) -> None:
    db_path = str(tmp_path / "test.db")
    result = await rag_lib.ingest_pdf(
        simple_pdf, manual_name="T", db_path=db_path, embedder=fake_embedder,
    )
    chunks = await rag_lib.list_chunks(result.manual_id, db_path)

    router = build_router(db_path, embedder=fake_embedder)
    app2 = FastAPI()
    app2.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/rag/chunks/{chunks[0].id}",
            json={"chunk_type": "imagen"},
        )
    assert resp.status_code == 422
```

- [ ] **Step 2: Verificar que los tests fallan**

```bash
python -m pytest tests/rag_lib/test_web_router_a4.py::test_upload_endpoint_returns_202 -v
```

Expected: error porque `build_router` no acepta `embedder` y el endpoint no existe

- [ ] **Step 3: Actualizar `router.py` con los 3 endpoints nuevos**

Reemplazar el contenido completo de `src/rag_lib/web/router.py`:

```python
"""rag_lib web router — REST endpoints + /rag HTML page."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import rag_lib
from rag_lib.embedding.base import Embedder

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_UNSET = object()


class ChunkUpdate(BaseModel):
    text: Optional[str] = None
    section_path: Optional[str] = None
    chunk_type: Optional[Literal["prose", "table"]] = None


def build_router(db_path: str | Path, embedder: Embedder | None = None) -> APIRouter:
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

    def _parse_manual_ids(raw: str) -> list[int] | None:
        if not raw.strip():
            return None
        try:
            return [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="manual_ids must be comma-separated integers")

    @router.get("/api/rag/search/fts")
    async def search_fts_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        ids = _parse_manual_ids(manual_ids)
        results = await rag_lib.search_fts(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/search/semantic")
    async def search_semantic_endpoint(q: str = "", manual_ids: str = "", k: int = 10):
        if not q.strip():
            return []
        ids = _parse_manual_ids(manual_ids)
        results = await rag_lib.search(q, db_path=db, manual_ids=ids, k=k)
        return [dataclasses.asdict(r) for r in results]

    @router.get("/api/rag/chunks/{chunk_id}/similar")
    async def similar_chunks_endpoint(chunk_id: int, k: int = 5):
        results = await rag_lib.search_similar(chunk_id, db_path=db, k=k)
        return [dataclasses.asdict(r) for r in results]

    # ── A4 endpoints ──────────────────────────────────────────────────────

    @router.post("/api/rag/manuals/upload", status_code=202)
    async def upload_manual_endpoint(
        file: UploadFile,
        manual_name: str = Form(...),
    ):
        if not manual_name.strip():
            raise HTTPException(status_code=422, detail="manual_name cannot be empty")
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="File must be a PDF (content-type: application/pdf)")
        pdf_bytes = await file.read()
        job = await rag_lib.upload_pdf(
            pdf_bytes,
            manual_name=manual_name,
            db_path=db,
            embedder=embedder,
        )
        return dataclasses.asdict(job)

    @router.get("/api/rag/jobs/{job_id}")
    async def get_job_endpoint(job_id: str):
        job = await rag_lib.get_job(job_id, db_path=db)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return dataclasses.asdict(job)

    @router.patch("/api/rag/chunks/{chunk_id}")
    async def patch_chunk_endpoint(chunk_id: int, body: ChunkUpdate):
        kwargs: dict = {}
        if "text" in body.model_fields_set:
            kwargs["text"] = body.text
        if "section_path" in body.model_fields_set:
            kwargs["section_path"] = body.section_path
        if "chunk_type" in body.model_fields_set:
            kwargs["chunk_type"] = body.chunk_type

        chunk = await rag_lib.update_chunk(chunk_id, db_path=db, embedder=embedder, **kwargs)
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return dataclasses.asdict(chunk)

    return router
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
python -m pytest tests/rag_lib/test_web_router_a4.py -v
```

Expected: 9 passed

- [ ] **Step 5: Verificar que los tests A1-A3 del router no regresionaron**

```bash
python -m pytest tests/rag_lib/test_web_router.py tests/rag_lib/test_web_router_a3.py -v
```

Expected: todos pasan (mismos que antes)

- [ ] **Step 6: Commit**

```bash
git add src/rag_lib/web/router.py tests/rag_lib/test_web_router_a4.py
git commit -m "feat(rag-a4): add upload, job polling, chunk PATCH endpoints; embedder param in build_router"
```

---

## Task 7: Frontend — Upload drag & drop

**Files:**
- Modify: `src/rag_lib/web/templates/rag.html`
- Modify: `src/rag_lib/web/static/js/rag.js`
- Modify: `src/rag_lib/web/static/css/rag.css`

- [ ] **Step 1: Añadir zona de upload al HTML**

En `src/rag_lib/web/templates/rag.html`, reemplazar el `<div id="manuals-panel">` por:

```html
    <!-- Panel izquierdo: manuales -->
    <div id="manuals-panel">
      <h2>Manuales</h2>

      <!-- Zona upload A4 -->
      <div id="upload-zone">
        <div id="upload-drop-area">
          <div class="upload-icon">📄</div>
          <p class="upload-hint">Arrastra un PDF aquí</p>
          <p class="upload-or">o</p>
          <label class="btn-file">
            Seleccionar archivo
            <input type="file" id="upload-file-input" accept=".pdf" hidden>
          </label>
          <input type="text" id="upload-name-input" placeholder="Nombre del manual" class="upload-name-input" disabled>
          <button id="upload-submit-btn" class="btn-primary" disabled>↑ Subir PDF</button>
        </div>
        <div id="upload-status" hidden></div>
      </div>

      <ul id="manuals-list">
        <li class="loading">Cargando…</li>
      </ul>
    </div>
```

- [ ] **Step 2: Añadir estado y funciones de upload al JS**

En `src/rag_lib/web/static/js/rag.js`, añadir las siguientes variables al bloque de State (después de `let searchDebounce`):

```js
// Upload state (A4)
let uploadFile = null;           // File object selected/dropped
let uploadJobId = null;          // active job id being polled
let uploadPollTimer = null;      // setInterval id for polling
```

Añadir las siguientes funciones después de la sección `// Search` y antes de `// Detail panel`:

```js
// ---------------------------------------------------------------------------
// Upload (A4)
// ---------------------------------------------------------------------------
function setUploadStatus(html, hidden = false) {
  const el = $("upload-status");
  el.hidden = hidden;
  el.innerHTML = html;
}

function resetUploadZone() {
  uploadFile = null;
  $("upload-file-input").value = "";
  $("upload-name-input").value = "";
  $("upload-name-input").disabled = true;
  $("upload-submit-btn").disabled = true;
  $("upload-drop-area").classList.remove("dragging");
  setUploadStatus("", true);
}

function onFileSelected(file) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    setUploadStatus('<span class="upload-error">⚠ Solo se admiten archivos PDF.</span>');
    return;
  }
  uploadFile = file;
  $("upload-name-input").value = file.name.replace(/\.pdf$/i, "");
  $("upload-name-input").disabled = false;
  $("upload-submit-btn").disabled = false;
  setUploadStatus("", true);
}

async function startUpload() {
  if (!uploadFile) return;
  const manualName = $("upload-name-input").value.trim();
  if (!manualName) {
    setUploadStatus('<span class="upload-error">⚠ Introduce un nombre para el manual.</span>');
    return;
  }

  // Lock UI during upload
  $("upload-submit-btn").disabled = true;
  $("upload-name-input").disabled = true;
  setUploadStatus(`<span class="upload-loading">⏳ Subiendo ${escapeHtml(manualName)}…</span>`);

  const formData = new FormData();
  formData.append("file", uploadFile, uploadFile.name);
  formData.append("manual_name", manualName);

  let jobId;
  try {
    const resp = await fetch(`${API}/manuals/upload`, { method: "POST", body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const job = await resp.json();
    jobId = job.id;
    uploadJobId = jobId;
  } catch (e) {
    setUploadStatus(`<span class="upload-error">⚠ Error al subir: ${escapeHtml(e.message)}</span>`);
    $("upload-submit-btn").disabled = false;
    $("upload-name-input").disabled = false;
    return;
  }

  setUploadStatus(`<span class="upload-loading">⏳ Procesando ${escapeHtml(manualName)}… (esto puede tardar 1-2 min)</span>`);
  pollUploadJob(jobId, manualName);
}

function pollUploadJob(jobId, manualName) {
  if (uploadPollTimer) clearInterval(uploadPollTimer);
  uploadPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`${API}/jobs/${jobId}`);
      if (!resp.ok) return;
      const job = await resp.json();
      if (job.status === "done") {
        clearInterval(uploadPollTimer);
        uploadPollTimer = null;
        if (job.was_duplicate) {
          setUploadStatus(
            `<span class="upload-dup">ℹ ${escapeHtml(manualName)} ya está importado. Para reimportarlo, elimínalo primero.</span>`
          );
        } else {
          setUploadStatus(`<span class="upload-ok">✓ ${escapeHtml(manualName)} importado.</span>`);
          setTimeout(() => { setUploadStatus("", true); resetUploadZone(); }, 3000);
        }
        loadManuals();
      } else if (job.status === "error") {
        clearInterval(uploadPollTimer);
        uploadPollTimer = null;
        setUploadStatus(`<span class="upload-error">⚠ Error: ${escapeHtml(job.error || "desconocido")}</span>`);
        $("upload-submit-btn").disabled = false;
        $("upload-name-input").disabled = false;
      }
    } catch (_) { /* network error, retry next tick */ }
  }, 2000);
}
```

Añadir los event listeners al bloque `// Init` (justo antes de `loadManuals()`):

```js
// Upload listeners (A4)
const dropArea = $("upload-drop-area");
dropArea.addEventListener("dragover", e => { e.preventDefault(); dropArea.classList.add("dragging"); });
dropArea.addEventListener("dragleave", () => dropArea.classList.remove("dragging"));
dropArea.addEventListener("drop", e => {
  e.preventDefault();
  dropArea.classList.remove("dragging");
  const file = e.dataTransfer.files[0];
  if (file) onFileSelected(file);
});
$("upload-file-input").addEventListener("change", e => {
  if (e.target.files[0]) onFileSelected(e.target.files[0]);
});
$("upload-submit-btn").addEventListener("click", startUpload);
```

- [ ] **Step 3: Añadir estilos de upload al CSS**

Añadir al final de `src/rag_lib/web/static/css/rag.css`:

```css
/* Upload zone (A4) */
#upload-zone {
  margin-bottom: 1rem;
}

#upload-drop-area {
  border: 2px dashed var(--border, #ccc);
  border-radius: 8px;
  padding: 0.75rem;
  text-align: center;
  transition: background 0.15s, border-color 0.15s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
}

#upload-drop-area.dragging {
  background: color-mix(in srgb, var(--accent, #4f8ef7) 10%, transparent);
  border-color: var(--accent, #4f8ef7);
}

.upload-icon { font-size: 1.5rem; }
.upload-hint { margin: 0; font-weight: 500; }
.upload-or   { margin: 0; color: #888; font-size: 0.78rem; }

.btn-file {
  cursor: pointer;
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  font-size: 0.82rem;
  background: transparent;
}
.btn-file:hover { background: var(--hover-bg, #f0f0f0); }

.upload-name-input {
  width: 90%;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  font-size: 0.82rem;
}
.upload-name-input:disabled { opacity: 0.5; }

#upload-submit-btn {
  padding: 0.3rem 0.75rem;
  font-size: 0.85rem;
}
#upload-submit-btn:disabled { opacity: 0.45; cursor: not-allowed; }

#upload-status { padding: 0.4rem 0; font-size: 0.82rem; text-align: center; }
.upload-ok    { color: #2a7f3e; }
.upload-error { color: #c0392b; }
.upload-dup   { color: #7a6500; }
.upload-loading { color: #555; }
```

- [ ] **Step 4: Smoke test visual**

```bash
rpg-scribe --campaign config/campaigns/cyberpunk-2060.toml
```

Abrir `http://127.0.0.1:8000/rag` y verificar:
- La zona de drag & drop aparece en el panel izquierdo
- Arrastrar un PDF activa el resaltado
- Soltar un PDF rellena el nombre y habilita el botón
- Hacer click en "↑ Subir PDF" muestra el estado de carga y luego el manual en la lista

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/web/templates/rag.html src/rag_lib/web/static/js/rag.js src/rag_lib/web/static/css/rag.css
git commit -m "feat(rag-a4): add drag & drop PDF upload with polling to /rag UI"
```

---

## Task 8: Frontend — Edición inline de chunks

**Files:**
- Modify: `src/rag_lib/web/templates/rag.html`
- Modify: `src/rag_lib/web/static/js/rag.js`
- Modify: `src/rag_lib/web/static/css/rag.css`

- [ ] **Step 1: Añadir botón editar y form inline al panel derecho**

En `src/rag_lib/web/templates/rag.html`, reemplazar el `<div id="detail-panel" hidden>` por:

```html
    <!-- Panel derecho: detalle del chunk + similares (A3 + edición A4) -->
    <div id="detail-panel" hidden>
      <div id="detail-header">
        <span id="detail-title"></span>
        <div class="detail-header-actions">
          <button id="detail-edit-btn" class="btn-secondary btn-sm">✎ Editar</button>
          <button id="detail-close" title="Cerrar detalle">✕</button>
        </div>
      </div>

      <!-- Vista normal (A3) -->
      <div id="detail-view">
        <div id="detail-text"></div>
        <div id="similar-section">
          <div class="col-header"><span>Similares</span></div>
          <div id="similar-list" class="results-list"></div>
        </div>
      </div>

      <!-- Modo edición (A4) -->
      <div id="detail-edit" hidden>
        <div class="edit-field">
          <label class="edit-label">Tipo</label>
          <select id="edit-chunk-type" class="edit-select">
            <option value="prose">prose</option>
            <option value="table">table</option>
          </select>
        </div>
        <div class="edit-field">
          <label class="edit-label">Sección</label>
          <input type="text" id="edit-section-path" class="edit-input" placeholder="(sin sección)">
        </div>
        <div class="edit-field edit-field-grow">
          <label class="edit-label">Texto</label>
          <textarea id="edit-text" class="edit-textarea" rows="10"></textarea>
        </div>
        <p class="edit-warning">⚠ Guardar regenera los embeddings (~1s)</p>
        <div class="edit-actions">
          <button id="edit-save-btn" class="btn-primary btn-sm">Guardar</button>
          <button id="edit-cancel-btn" class="btn-secondary btn-sm">Cancelar</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Añadir lógica de edición al JS**

Añadir estas variables al bloque de State en `rag.js` (después de las variables de upload):

```js
// Edit state (A4)
let editOriginalChunk = null;   // snapshot of chunk before editing
```

Añadir las siguientes funciones antes de `// Init`:

```js
// ---------------------------------------------------------------------------
// Chunk editing (A4)
// ---------------------------------------------------------------------------
function enterEditMode(chunk) {
  editOriginalChunk = chunk;
  $("edit-chunk-type").value = chunk.chunk_type;
  $("edit-section-path").value = chunk.section_path || "";
  $("edit-text").value = chunk.text;
  $("detail-view").hidden = true;
  $("detail-edit").hidden = false;
  $("detail-edit-btn").hidden = true;
}

function exitEditMode() {
  editOriginalChunk = null;
  $("detail-view").hidden = false;
  $("detail-edit").hidden = true;
  $("detail-edit-btn").hidden = false;
}

async function saveChunkEdit() {
  if (!editOriginalChunk || !openChunkId) return;

  const body = {};
  const newText = $("edit-text").value;
  const newSection = $("edit-section-path").value.trim() || null;
  const newType = $("edit-chunk-type").value;

  if (newText !== editOriginalChunk.text) body.text = newText;
  if (newSection !== (editOriginalChunk.section_path || null)) body.section_path = newSection;
  if (newType !== editOriginalChunk.chunk_type) body.chunk_type = newType;

  if (!Object.keys(body).length) { exitEditMode(); return; }

  $("edit-save-btn").disabled = true;
  $("edit-save-btn").textContent = "Guardando…";

  try {
    const resp = await fetch(`${API}/chunks/${openChunkId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const updated = await resp.json();
    exitEditMode();
    // Refresh detail panel with updated chunk data
    const sp = updated.section_path || "";
    $("detail-title").textContent =
      `#${updated.id} · p.${updated.page} · ${updated.chunk_type}${sp ? " · " + sp : ""}`;
    $("detail-text").textContent = updated.text;
    editOriginalChunk = updated;
  } catch (e) {
    alert(`Error al guardar: ${e.message}`);
  } finally {
    $("edit-save-btn").disabled = false;
    $("edit-save-btn").textContent = "Guardar";
  }
}
```

Añadir los event listeners al bloque `// Init` (después de los listeners de upload):

```js
// Edit listeners (A4)
$("detail-edit-btn").addEventListener("click", () => {
  if (!openChunkId) return;
  fetchJSON(`${API}/chunks/${openChunkId}`).then(chunk => enterEditMode(chunk));
});
$("edit-cancel-btn").addEventListener("click", exitEditMode);
$("edit-save-btn").addEventListener("click", saveChunkEdit);
```

- [ ] **Step 3: Añadir estilos de edición al CSS**

Añadir al final de `src/rag_lib/web/static/css/rag.css`:

```css
/* Chunk editing (A4) */
.detail-header-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.btn-sm { padding: 0.2rem 0.5rem; font-size: 0.8rem; }
.btn-secondary {
  background: transparent;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  cursor: pointer;
}
.btn-secondary:hover { background: var(--hover-bg, #f0f0f0); }

.btn-primary {
  background: var(--accent, #4f8ef7);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  padding: 0.3rem 0.75rem;
}
.btn-primary:hover { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }

#detail-edit {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem 0;
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.edit-field-grow { flex: 1; }

.edit-label { font-size: 0.78rem; font-weight: 600; color: #555; }

.edit-select, .edit-input {
  padding: 0.25rem 0.4rem;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  font-size: 0.85rem;
}

.edit-textarea {
  resize: vertical;
  padding: 0.4rem;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  font-size: 0.83rem;
  font-family: inherit;
  min-height: 6rem;
}

.edit-warning {
  font-size: 0.78rem;
  color: #9a6500;
  margin: 0;
}

.edit-actions {
  display: flex;
  gap: 0.5rem;
}
```

- [ ] **Step 4: Smoke test visual**

Con el servidor corriendo en `http://127.0.0.1:8000/rag`:
- Abrir el panel de detalle de un chunk (click en cualquier fila)
- Verificar que aparece el botón "✎ Editar"
- Click en "✎ Editar" → aparece el formulario con los datos del chunk
- Editar el texto y hacer click en "Guardar" → el panel se actualiza con el nuevo texto
- Hacer click en "Cancelar" → vuelve a la vista normal sin cambios

- [ ] **Step 5: Commit**

```bash
git add src/rag_lib/web/templates/rag.html src/rag_lib/web/static/js/rag.js src/rag_lib/web/static/css/rag.css
git commit -m "feat(rag-a4): add inline chunk editing (text + section_path + chunk_type) to detail panel"
```

---

## Task 9: Suite completa + lint

**Files:** ninguno nuevo

- [ ] **Step 1: Correr toda la suite rag_lib**

```bash
python -m pytest tests/rag_lib/ -v
```

Expected: todos pasan. Los nuevos tests añadidos en A4 (~26) más todos los de A1-A3 (~94). Si alguno falla por naming conflict en `test_upload.py` (la fixture `db` ya existe en `conftest.py`), renombrar la fixture local del test a `job_db`.

- [ ] **Step 2: Verificar que no hay regresiones fuera de rag_lib**

```bash
python -m pytest tests/ -q --ignore=tests/rag_lib/
```

Expected: mismos fallos pre-existentes que antes de A4 (ver CLAUDE.md: `test_tts_config_from_toml`, `test_defaults_from_toml_override_dataclass_defaults` si `RPG_SCRIBE_HOST` en env, `test_generate_toml_is_valid_toml`, `test_half_open_failure_reopens`).

- [ ] **Step 3: Correr lint**

```bash
ruff check src/rag_lib tests/rag_lib
```

Expected: `All checks passed!`

Si hay errores de `ruff`:
- `F401` (unused import): revisar los imports en `__init__.py` — `IngestJob` debe estar en el import de types.
- `E501` (line too long): reformatear la línea afectada.
- `ANN` / `ARG`: son warnings, no errores con la config actual del proyecto.

- [ ] **Step 4: Formatear si es necesario**

```bash
ruff format src/rag_lib tests/rag_lib
ruff check src/rag_lib tests/rag_lib
```

Expected: sin cambios pendientes tras formatear.

- [ ] **Step 5: Commit final de la fase**

```bash
git add -A
git commit -m "feat(rag-a4): complete web upload + chunk editing — Fase A4"
```
