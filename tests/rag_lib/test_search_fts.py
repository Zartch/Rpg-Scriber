"""Tests for FTS5 schema — virtual table and sync triggers (Task 1), search_fts() (Task 2), search_similar() (Task 3)."""
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
    """DB with Manual A (1 chunk about 'ataque') and Manual B (1 chunk about 'ataque')."""
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


async def test_search_fts_empty_manual_ids_returns_empty(fts_db) -> None:
    _, _, db_path = fts_db
    results = await rag_lib.search_fts("ataque", db_path, manual_ids=[])
    assert results == []


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
    assert 1 <= len(results) <= 3
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
