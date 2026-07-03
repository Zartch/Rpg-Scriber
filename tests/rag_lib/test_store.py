"""Tests for store.py — Database, ManualRepo, ChunkRepo."""
from __future__ import annotations

import pytest

import rag_lib
from rag_lib.store import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

async def test_connect_creates_rag_manuals_table(db: Database) -> None:
    cur = await db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_manuals'")
    row = await cur.fetchone()
    assert row is not None


async def test_connect_creates_rag_chunks_table(db: Database) -> None:
    cur = await db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_chunks'")
    row = await cur.fetchone()
    assert row is not None


async def test_foreign_keys_are_enabled(db: Database) -> None:
    cur = await db.conn.execute("PRAGMA foreign_keys")
    row = await cur.fetchone()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# ManualRepo
# ---------------------------------------------------------------------------

async def test_insert_manual_returns_integer_id(db: Database) -> None:
    manual_id = await db.manuals.insert(
        name="D&D 5e", source_path="/tmp/dnd.pdf",
        source_hash="abc123", page_count=452, file_size=14_600_000, parser="pdfplumber",
    )
    assert isinstance(manual_id, int)
    assert manual_id >= 1


async def test_find_by_hash_returns_row(db: Database) -> None:
    await db.manuals.insert(
        name="D&D 5e", source_path="/tmp/dnd.pdf",
        source_hash="abc123", page_count=452, file_size=14_600_000, parser="pdfplumber",
    )
    row = await db.manuals.find_by_hash("abc123")
    assert row is not None
    assert row["name"] == "D&D 5e"


async def test_find_by_hash_returns_none_for_unknown(db: Database) -> None:
    row = await db.manuals.find_by_hash("nonexistent_hash")
    assert row is None


async def test_duplicate_source_hash_raises(db: Database) -> None:
    await db.manuals.insert(
        name="D&D 5e", source_path="/tmp/dnd.pdf",
        source_hash="unique_hash", page_count=100, file_size=1000, parser="pdfplumber",
    )
    with pytest.raises(Exception):  # aiosqlite raises IntegrityError
        await db.manuals.insert(
            name="Other", source_path="/tmp/other.pdf",
            source_hash="unique_hash", page_count=50, file_size=500, parser="pdfplumber",
        )


async def test_list_all_manuals_empty(db: Database) -> None:
    rows = await db.manuals.list_all()
    assert rows == []


async def test_list_all_returns_inserted_manual(db: Database) -> None:
    await db.manuals.insert(
        name="Tasha", source_path="/tmp/tasha.pdf",
        source_hash="hash_tasha", page_count=298, file_size=8_900_000, parser="pdfplumber",
    )
    rows = await db.manuals.list_all()
    assert len(rows) == 1
    assert rows[0]["name"] == "Tasha"


async def test_delete_manual_returns_true_when_exists(db: Database) -> None:
    mid = await db.manuals.insert(
        name="Tasha", source_path="/tmp/t.pdf",
        source_hash="h1", page_count=1, file_size=1, parser="pdfplumber",
    )
    result = await db.manuals.delete(mid)
    assert result is True


async def test_delete_manual_returns_false_when_missing(db: Database) -> None:
    result = await db.manuals.delete(9999)
    assert result is False


# ---------------------------------------------------------------------------
# ChunkRepo
# ---------------------------------------------------------------------------

@pytest.fixture
async def manual_id(db: Database) -> int:
    return await db.manuals.insert(
        name="Test", source_path="/tmp/t.pdf",
        source_hash="htest", page_count=10, file_size=1000, parser="pdfplumber",
    )


async def test_insert_many_chunks(db: Database, manual_id: int) -> None:
    chunks = [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "Hello world", "text_hash": "h1", "token_count": 2},
        {"seq": 1, "chunk_type": "table", "page": 2, "page_end": None,
         "section_path": "Combat", "text": "| A | B |\n|---|---|\n| 1 | 2 |", "text_hash": "h2", "token_count": 10},
    ]
    await db.chunks.insert_many(manual_id, chunks)
    rows = await db.chunks.list_by_manual(manual_id)
    assert len(rows) == 2


async def test_list_chunks_pagination(db: Database, manual_id: int) -> None:
    chunks = [
        {"seq": i, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": f"text {i}", "text_hash": f"h{i}", "token_count": 2}
        for i in range(10)
    ]
    await db.chunks.insert_many(manual_id, chunks)
    first_page = await db.chunks.list_by_manual(manual_id, offset=0, limit=5)
    second_page = await db.chunks.list_by_manual(manual_id, offset=5, limit=5)
    assert len(first_page) == 5
    assert len(second_page) == 5
    assert first_page[0]["seq"] == 0
    assert second_page[0]["seq"] == 5


async def test_get_chunk_by_id(db: Database, manual_id: int) -> None:
    chunks = [{"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
               "section_path": None, "text": "Hello", "text_hash": "hh", "token_count": 1}]
    await db.chunks.insert_many(manual_id, chunks)
    rows = await db.chunks.list_by_manual(manual_id)
    chunk_id = rows[0]["id"]
    row = await db.chunks.get_by_id(chunk_id)
    assert row is not None
    assert row["text"] == "Hello"


async def test_get_chunk_by_id_returns_none_for_missing(db: Database) -> None:
    row = await db.chunks.get_by_id(9999)
    assert row is None


async def test_delete_manual_cascades_to_chunks(db: Database, manual_id: int) -> None:
    chunks = [{"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
               "section_path": None, "text": "text", "text_hash": "hc", "token_count": 1}]
    await db.chunks.insert_many(manual_id, chunks)
    await db.manuals.delete(manual_id)
    rows = await db.chunks.list_by_manual(manual_id)
    assert rows == []


# ---------------------------------------------------------------------------
# list_by_page / list_chunks_by_page — chunks que cubren una página
# ---------------------------------------------------------------------------


async def _page_db(tmp_path):
    """Manual con 4 chunks: pág 1, rango 2-4, pág 5, y un segundo manual en pág 3."""
    db = Database(str(tmp_path / "pages.db"))
    await db.connect()
    m1 = await db.manuals.insert(
        name="Manual A", source_path="a.pdf", source_hash="sha_pa",
        page_count=5, file_size=10, parser="pdfplumber",
    )
    m2 = await db.manuals.insert(
        name="Manual B", source_path="b.pdf", source_hash="sha_pb",
        page_count=5, file_size=10, parser="pdfplumber",
    )
    await db.chunks.insert_many(m1, [
        {"seq": 0, "chunk_type": "prose", "page": 1, "page_end": None,
         "section_path": None, "text": "uno", "text_hash": "p1", "token_count": 1},
        {"seq": 1, "chunk_type": "prose", "page": 2, "page_end": 4,
         "section_path": None, "text": "dos-cuatro", "text_hash": "p2", "token_count": 1},
        {"seq": 2, "chunk_type": "prose", "page": 5, "page_end": None,
         "section_path": None, "text": "cinco", "text_hash": "p3", "token_count": 1},
    ])
    await db.chunks.insert_many(m2, [
        {"seq": 0, "chunk_type": "prose", "page": 3, "page_end": None,
         "section_path": None, "text": "otro manual", "text_hash": "p4", "token_count": 1},
    ])
    return db, m1, m2


async def test_list_by_page_single_page_chunk(tmp_path):
    db, m1, _ = await _page_db(tmp_path)
    try:
        rows = await db.chunks.list_by_page(m1, 1)
        assert [r["text"] for r in rows] == ["uno"]
    finally:
        await db.close()


async def test_list_by_page_within_range(tmp_path):
    """Página 3 cae dentro del rango 2-4 → devuelve el chunk de rango."""
    db, m1, _ = await _page_db(tmp_path)
    try:
        rows = await db.chunks.list_by_page(m1, 3)
        assert [r["text"] for r in rows] == ["dos-cuatro"]
    finally:
        await db.close()


async def test_list_by_page_scopes_to_manual(tmp_path):
    """La página 3 del Manual B no contamina los resultados del Manual A."""
    db, m1, m2 = await _page_db(tmp_path)
    try:
        rows_a = await db.chunks.list_by_page(m1, 3)
        rows_b = await db.chunks.list_by_page(m2, 3)
        assert [r["text"] for r in rows_a] == ["dos-cuatro"]
        assert [r["text"] for r in rows_b] == ["otro manual"]
    finally:
        await db.close()


async def test_public_list_chunks_by_page_returns_chunks(tmp_path):
    db, m1, _ = await _page_db(tmp_path)
    db_path = str(tmp_path / "pages.db")
    await db.close()
    chunks = await rag_lib.list_chunks_by_page(m1, 3, db_path)
    assert len(chunks) == 1
    assert chunks[0].text == "dos-cuatro"
    assert chunks[0].page == 2
    assert chunks[0].page_end == 4
