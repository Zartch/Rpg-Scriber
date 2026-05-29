"""Tests for upload_pdf(), get_job() and JobRepo."""
from __future__ import annotations

import asyncio
import time
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
    database = Database(db_path)
    await database.connect()
    try:
        rows = await database.embeddings.load_all()
        assert len(rows) > 0
    finally:
        await database.close()
