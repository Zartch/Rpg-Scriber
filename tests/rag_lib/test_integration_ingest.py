"""End-to-end ingestion tests — exercises the public API (rag_lib.__init__)."""
from __future__ import annotations

from pathlib import Path


import rag_lib
from rag_lib.store import Database
from rag_lib.types import IngestResult, Manual, Chunk


async def test_ingest_pdf_returns_ingest_result(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Test Manual", db_path=db, embedder=fake_embedder)
    assert isinstance(result, IngestResult)
    assert result.manual_id >= 1
    assert result.chunks_created >= 1
    assert result.was_already_ingested is False


async def test_ingest_creates_chunks_in_db(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Test Manual", db_path=db, embedder=fake_embedder)
    chunks = await rag_lib.list_chunks(result.manual_id, db_path=db)
    assert len(chunks) == result.chunks_created
    assert all(isinstance(c, Chunk) for c in chunks)


async def test_ingest_idempotent_same_hash(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    r1 = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Manual", db_path=db, embedder=fake_embedder)
    r2 = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Manual", db_path=db, embedder=fake_embedder)
    assert r2.was_already_ingested is True
    assert r2.manual_id == r1.manual_id
    assert r2.chunks_created == 0


async def test_list_manuals_returns_manual(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    await rag_lib.ingest_pdf(pdf_with_table, manual_name="D&D 5e", db_path=db, embedder=fake_embedder)
    manuals = await rag_lib.list_manuals(db_path=db)
    assert len(manuals) == 1
    assert isinstance(manuals[0], Manual)
    assert manuals[0].name == "D&D 5e"
    assert manuals[0].chunk_count >= 1


async def test_delete_manual_removes_manual_and_chunks(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Del Me", db_path=db, embedder=fake_embedder)
    deleted = await rag_lib.delete_manual(result.manual_id, db_path=db)
    assert deleted is True
    manuals = await rag_lib.list_manuals(db_path=db)
    assert manuals == []
    chunks = await rag_lib.list_chunks(result.manual_id, db_path=db)
    assert chunks == []


async def test_get_chunk_returns_chunk(simple_pdf: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(simple_pdf, manual_name="Simple", db_path=db, embedder=fake_embedder)
    chunks = await rag_lib.list_chunks(result.manual_id, db_path=db)
    chunk = await rag_lib.get_chunk(chunks[0].id, db_path=db)
    assert isinstance(chunk, Chunk)
    assert chunk.id == chunks[0].id


async def test_get_chunk_returns_none_for_missing(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    chunk = await rag_lib.get_chunk(9999, db_path=db)
    assert chunk is None


async def test_table_chunks_are_atomic(pdf_with_table: Path, tmp_path: Path, fake_embedder) -> None:
    db = tmp_path / "rag.db"
    result = await rag_lib.ingest_pdf(pdf_with_table, manual_name="Tables", db_path=db, embedder=fake_embedder)
    chunks = await rag_lib.list_chunks(result.manual_id, db_path=db)
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) >= 1
    for tc in table_chunks:
        assert "| Arma |" in tc.text or "---" in tc.text


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
