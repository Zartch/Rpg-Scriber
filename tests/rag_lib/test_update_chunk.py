"""Tests for ChunkRepo.update() and update_chunk() public API."""
from __future__ import annotations

import hashlib

import pytest

from rag_lib.store import Database


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
