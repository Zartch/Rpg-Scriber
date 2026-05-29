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
