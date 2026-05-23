"""Tests for web router (build_router factory + 4 endpoints)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

import rag_lib
from rag_lib.web import build_router


@pytest.fixture
async def client(tmp_path: Path, pdf_with_table: Path):
    db = tmp_path / "rag.db"
    # Pre-ingest a manual so tests have data
    await rag_lib.ingest_pdf(pdf_with_table, manual_name="Test Manual", db_path=db)

    app = FastAPI()
    app.include_router(build_router(db))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, db


async def test_list_manuals_returns_json_array(client) -> None:
    c, _ = client
    resp = await c.get("/api/rag/manuals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Test Manual"


async def test_list_manuals_includes_chunk_count(client) -> None:
    c, _ = client
    resp = await c.get("/api/rag/manuals")
    data = resp.json()
    assert "chunk_count" in data[0]
    assert data[0]["chunk_count"] >= 1


async def test_list_chunks_returns_paginated_json(client) -> None:
    c, _ = client
    resp = await c.get("/api/rag/manuals/1/chunks?offset=0&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


async def test_list_chunks_unknown_manual_returns_empty(client) -> None:
    c, _ = client
    resp = await c.get("/api/rag/manuals/9999/chunks")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_chunk_returns_chunk(client, tmp_path: Path) -> None:
    c, db = client
    chunks = await rag_lib.list_chunks(1, db_path=db)
    resp = await c.get(f"/api/rag/chunks/{chunks[0].id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == chunks[0].id
    assert "text" in data


async def test_get_chunk_404_for_missing(client) -> None:
    c, _ = client
    resp = await c.get("/api/rag/chunks/9999")
    assert resp.status_code == 404


async def test_delete_manual_returns_204(client) -> None:
    c, _ = client
    resp = await c.delete("/api/rag/manuals/1")
    assert resp.status_code == 204


async def test_delete_manual_404_for_missing(client) -> None:
    c, _ = client
    resp = await c.delete("/api/rag/manuals/9999")
    assert resp.status_code == 404


async def test_rag_page_returns_html(client) -> None:
    c, _ = client
    resp = await c.get("/rag")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
