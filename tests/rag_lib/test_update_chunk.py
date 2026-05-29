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


async def test_update_chunk_text_persisted(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, text="nuevo texto aquí", embedder=fake_embedder)
    assert isinstance(updated, Chunk)
    assert updated.text == "nuevo texto aquí"


async def test_update_chunk_recalculates_token_count(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    updated = await rag_lib.update_chunk(chunk_id, db_path, text="uno dos tres", embedder=fake_embedder)
    assert updated.token_count > 0


async def test_update_chunk_recalculates_text_hash(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    nuevo = "texto completamente diferente"
    updated = await rag_lib.update_chunk(chunk_id, db_path, text=nuevo, embedder=fake_embedder)
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
    database = Database(db_path)
    await database.connect()
    rows_before = await database.embeddings.load_all()
    await database.close()

    await rag_lib.update_chunk(chunk_id, db_path, text="texto muy diferente", embedder=fake_embedder)

    database = Database(db_path)
    await database.connect()
    rows_after = await database.embeddings.load_all()
    await database.close()
    assert len(rows_after) == len(rows_before)
    chunk_emb = next(r for r in rows_after if r["chunk_id"] == chunk_id)
    assert chunk_emb is not None


async def test_update_chunk_fts5_updated(ingested_chunk, fake_embedder) -> None:
    db_path, chunk_id = ingested_chunk
    nuevo_texto = "xtextouniquexyz frase especial"
    await rag_lib.update_chunk(chunk_id, db_path, text=nuevo_texto, embedder=fake_embedder)
    results = await rag_lib.search_fts("xtextouniquexyz", db_path)
    assert any(r.chunk_id == chunk_id for r in results)
