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


async def test_patch_chunk_invalid_chunk_type(tmp_path, fake_embedder, simple_pdf: Path) -> None:
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
