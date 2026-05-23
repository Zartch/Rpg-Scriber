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
    """Two manuals, search with manual_ids=[m1] returns only manual 1 chunks."""
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
